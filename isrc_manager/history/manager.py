"""Persistent linear-plus-branch-aware history manager."""

from __future__ import annotations

import base64
import json
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PySide6.QtCore import QByteArray, QPoint, QSettings

from isrc_manager.services import (
    ProfileKVService,
    SettingsMutationService,
    SettingsReadService,
    TrackService,
    TrackSnapshot,
)
from isrc_manager.theme_builder import theme_setting_keys

from .models import BackupRecord, HistoryEntry, HistoryIssue, HistoryRepairResult, SnapshotRecord


class HistoryRecoveryError(RuntimeError):
    """Raised when history recovery artifacts are missing or inconsistent."""


_UNSET = object()
_ENTRY_SELECT_COLUMNS = """
    id, parent_id, created_at, label, action_type, entity_type, entity_id,
    reversible, strategy, payload_json, inverse_json, redo_json,
    snapshot_before_id, snapshot_after_id, status, visible_in_history
"""


class HistoryManager:
    """Stores history entries and applies undo/redo for supported actions."""

    MANAGED_DIRECTORIES = (
        "licenses",
        "track_media",
        "release_media",
        "contract_documents",
        "asset_registry",
        "custom_field_media",
        "gs1_templates",
        "contract_template_sources",
        "contract_template_drafts",
        "contract_template_artifacts",
    )
    FILE_COMPANION_SUFFIXES = (".wal", ".shm")
    SETTINGS_COALESCE_WINDOW_SECONDS = 2.0
    STATUS_APPLIED = "applied"
    STATUS_BROKEN = "broken"
    STATUS_UNDONE = "undone"
    STATUS_SUPERSEDED = "superseded"
    STATUS_ARTIFACT_MISSING = "artifact_missing"
    SNAPSHOT_EXCLUDED_TABLES = frozenset(
        {
            "AuditLog",
            "HistoryBackups",
            "HistoryEntries",
            "HistoryHead",
            "HistorySnapshots",
            "_MigrationLog",
        }
    )
    SNAPSHOT_SIDECAR_SUFFIX = ".snapshot.json"
    BACKUP_SIDECAR_SUFFIX = ".backup.json"

    def __init__(
        self,
        conn: sqlite3.Connection,
        settings: QSettings,
        db_path: str | Path,
        history_root: str | Path,
        managed_root: str | Path | None = None,
        backups_root: str | Path | None = None,
    ):
        self.conn = conn
        self.settings = settings
        self.db_path = Path(db_path)
        self.history_root = Path(history_root)
        self.managed_root = Path(managed_root) if managed_root is not None else None
        self.backups_root = Path(backups_root) if backups_root is not None else None
        self.track_service = TrackService(conn, managed_root)
        self.settings_mutations = SettingsMutationService(conn, settings)
        self.settings_reads = SettingsReadService(conn)
        self.profile_kv = ProfileKVService(conn)
        if self._history_tables_ready():
            self._ensure_history_invariants()

    # ------------------------------------------------------------------
    # Public queries
    # ------------------------------------------------------------------
    def list_entries(self, limit: int = 250, *, include_hidden: bool = False) -> list[HistoryEntry]:
        current_id = (
            self.get_current_entry_id() if include_hidden else self.get_current_visible_entry_id()
        )
        where_sql = "" if include_hidden else "WHERE visible_in_history=1"
        rows = self.conn.execute(
            f"""
            SELECT
                {_ENTRY_SELECT_COLUMNS}
            FROM HistoryEntries
            {where_sql}
            ORDER BY id DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
        return [self._entry_from_row(row, current_id=current_id) for row in rows]

    def list_snapshots(self, limit: int = 250) -> list[SnapshotRecord]:
        rows = self.conn.execute(
            """
            SELECT id, created_at, kind, label, db_snapshot_path, settings_json, manifest_json
            FROM HistorySnapshots
            ORDER BY id DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
        return [self._snapshot_from_row(row) for row in rows]

    def list_backups(self, limit: int = 250) -> list[BackupRecord]:
        rows = self.conn.execute(
            """
            SELECT id, created_at, kind, label, backup_path, source_db_path, metadata_json
            FROM HistoryBackups
            ORDER BY id DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
        return [self._backup_from_row(row) for row in rows]

    def get_current_entry_id(self) -> int | None:
        row = self.conn.execute("SELECT current_entry_id FROM HistoryHead WHERE id=1").fetchone()
        return int(row[0]) if row and row[0] is not None else None

    def get_current_entry(self) -> HistoryEntry | None:
        self._ensure_history_invariants()
        current_id = self.get_current_entry_id()
        if current_id is None:
            return None
        return self.fetch_entry(current_id)

    def get_current_visible_entry(self) -> HistoryEntry | None:
        self._ensure_history_invariants()
        plan = self._visible_undo_plan()
        if plan:
            return plan[-1]
        return None

    def get_current_visible_entry_id(self) -> int | None:
        entry = self.get_current_visible_entry()
        return entry.entry_id if entry is not None else None

    def fetch_entry(self, entry_id: int) -> HistoryEntry | None:
        row = self.conn.execute(
            f"""
            SELECT
                {_ENTRY_SELECT_COLUMNS}
            FROM HistoryEntries
            WHERE id=?
            """,
            (int(entry_id),),
        ).fetchone()
        if not row:
            return None
        return self._entry_from_row(row, current_id=self.get_current_entry_id())

    def fetch_backup(self, backup_id: int) -> BackupRecord | None:
        row = self.conn.execute(
            """
            SELECT id, created_at, kind, label, backup_path, source_db_path, metadata_json
            FROM HistoryBackups
            WHERE id=?
            """,
            (int(backup_id),),
        ).fetchone()
        if not row:
            return None
        return self._backup_from_row(row)

    def delete_backup(self, backup_id: int) -> None:
        backup = self.fetch_backup(backup_id)
        if backup is None:
            raise ValueError(f"Backup {backup_id} not found")

        with self.conn:
            self.conn.execute("DELETE FROM HistoryBackups WHERE id=?", (int(backup_id),))

        backup_path = Path(backup.backup_path)
        self._remove_path(backup_path)
        self._remove_path(self._backup_sidecar_path(backup_path))

    def can_undo(self) -> bool:
        self._ensure_history_invariants()
        return bool(self._visible_undo_plan())

    def can_redo(self) -> bool:
        self._ensure_history_invariants()
        return self.get_default_redo_entry() is not None

    def describe_undo(self) -> str | None:
        self._ensure_history_invariants()
        entry = self.get_current_visible_entry()
        return entry.label if entry is not None else None

    def describe_redo(self) -> str | None:
        self._ensure_history_invariants()
        entry = self.get_default_redo_entry()
        if entry is not None:
            return entry.label
        return None

    # ------------------------------------------------------------------
    # Recording actions
    # ------------------------------------------------------------------
    def create_manual_snapshot(self, label: str | None = None) -> SnapshotRecord:
        snapshot = self.capture_snapshot(
            kind="manual", label=label or f"Manual Snapshot {self._now_stamp()}"
        )
        self.record_snapshot_create(snapshot)
        return snapshot

    def record_snapshot_create(
        self,
        snapshot: SnapshotRecord,
        *,
        label: str | None = None,
    ) -> HistoryEntry:
        archived_snapshot = self._archive_snapshot_record(snapshot, prefix="snapshot_create")
        entry_id = self._insert_entry(
            label=label or f"Create Snapshot: {snapshot.label}",
            action_type="snapshot.create",
            entity_type="Snapshot",
            entity_id=str(snapshot.snapshot_id),
            reversible=True,
            strategy="inverse",
            payload={"snapshot_id": snapshot.snapshot_id, "label": snapshot.label},
            inverse_payload={"snapshot_id": snapshot.snapshot_id},
            redo_payload={"archived_snapshot": archived_snapshot},
            snapshot_before_id=None,
            snapshot_after_id=None,
            move_head=True,
        )
        return self.fetch_entry(entry_id)

    def delete_snapshot_as_action(
        self, snapshot_id: int, *, label: str | None = None
    ) -> HistoryEntry:
        snapshot = self.fetch_snapshot(snapshot_id)
        if snapshot is None:
            raise ValueError(f"Snapshot {snapshot_id} not found")
        if self._snapshot_missing_paths(snapshot):
            snapshot_label = snapshot.label
            self.delete_snapshot(snapshot_id)
            entry_id = self._insert_entry(
                label=label or f"Delete Missing Snapshot Reference: {snapshot_label}",
                action_type="snapshot.delete_missing",
                entity_type="Snapshot",
                entity_id=str(snapshot_id),
                reversible=False,
                strategy="event",
                payload={"snapshot_id": snapshot_id, "label": snapshot_label},
                inverse_payload=None,
                redo_payload=None,
                snapshot_before_id=None,
                snapshot_after_id=None,
                move_head=False,
            )
            return self.fetch_entry(entry_id)
        archived_snapshot = self._archive_snapshot_record(snapshot, prefix="snapshot_delete")
        snapshot_label = snapshot.label
        self.delete_snapshot(snapshot_id)
        entry_id = self._insert_entry(
            label=label or f"Delete Snapshot: {snapshot_label}",
            action_type="snapshot.delete",
            entity_type="Snapshot",
            entity_id=str(snapshot_id),
            reversible=True,
            strategy="inverse",
            payload={"snapshot_id": snapshot_id, "label": snapshot_label},
            inverse_payload={"archived_snapshot": archived_snapshot},
            redo_payload={"snapshot_id": None},
            snapshot_before_id=None,
            snapshot_after_id=None,
            move_head=True,
        )
        return self.fetch_entry(entry_id)

    def capture_snapshot(self, *, kind: str, label: str) -> SnapshotRecord:
        return self._create_snapshot(kind=kind, label=label)

    def record_snapshot_action(
        self,
        *,
        label: str,
        action_type: str,
        snapshot_before_id: int,
        snapshot_after_id: int,
        entity_type: str | None = None,
        entity_id: str | None = None,
        payload: dict | None = None,
        visible_in_history: bool = True,
    ) -> HistoryEntry:
        entry_id = self._insert_entry(
            label=label,
            action_type=action_type,
            entity_type=entity_type,
            entity_id=entity_id,
            reversible=True,
            strategy="snapshot",
            payload=payload or {},
            inverse_payload=None,
            redo_payload=None,
            snapshot_before_id=snapshot_before_id,
            snapshot_after_id=snapshot_after_id,
            move_head=True,
            visible_in_history=visible_in_history,
        )
        return self.fetch_entry(entry_id)

    def restore_snapshot_as_action(
        self, snapshot_id: int, *, label: str | None = None
    ) -> HistoryEntry:
        target = self.fetch_snapshot(snapshot_id)
        if target is None:
            raise ValueError(f"Snapshot {snapshot_id} not found")
        self._validate_snapshot_restore_ready(target)
        before = self.capture_snapshot(kind="auto_pre_restore", label="Before Snapshot Restore")
        restore_applied = False
        try:
            self._restore_snapshot_state(target)
            restore_applied = True
            return self.record_snapshot_action(
                label=label or f"Restore Snapshot: {target.label}",
                action_type="snapshot.restore",
                entity_type="Snapshot",
                entity_id=str(snapshot_id),
                payload={"snapshot_id": snapshot_id, "label": target.label},
                snapshot_before_id=before.snapshot_id,
                snapshot_after_id=target.snapshot_id,
            )
        except Exception:
            if restore_applied:
                try:
                    self.restore_snapshot(before.snapshot_id)
                except Exception:
                    pass
            self._delete_snapshot_if_unreferenced(before.snapshot_id)
            raise

    def restore_snapshot(self, snapshot_id: int) -> SnapshotRecord:
        snapshot = self.fetch_snapshot(snapshot_id)
        if snapshot is None:
            raise ValueError(f"Snapshot {snapshot_id} not found")
        self._validate_snapshot_restore_ready(snapshot)
        self._restore_snapshot_state(snapshot)
        return snapshot

    def capture_file_state(
        self,
        target_path: str | Path,
        *,
        companion_suffixes: tuple[str, ...] = (),
    ) -> dict:
        target = Path(target_path)
        file_dir = self.history_root / "file_states" / self.db_path.stem
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        bundle_dir = file_dir / f"{timestamp}_{target.name}"

        files = []
        for suffix in ("", *tuple(companion_suffixes)):
            source = Path(str(target) + suffix) if suffix else target
            if not source.exists():
                continue
            bundle_dir.mkdir(parents=True, exist_ok=True)
            artifact = bundle_dir / source.name
            shutil.copy2(source, artifact)
            files.append({"suffix": suffix, "artifact_path": str(artifact)})

        return {
            "target_path": str(target),
            "companion_suffixes": list(companion_suffixes),
            "exists": bool(files),
            "files": files,
        }

    def restore_file_state(self, target_path: str | Path, state: dict) -> None:
        target = Path(target_path)
        companion_suffixes = tuple(state.get("companion_suffixes", []))
        for suffix in ("", *companion_suffixes):
            self._remove_path(Path(str(target) + suffix) if suffix else target)

        for file_info in state.get("files", []):
            artifact = Path(file_info["artifact_path"])
            if not artifact.exists():
                raise HistoryRecoveryError(
                    "History file restore could not proceed because a stored artifact is missing.\n"
                    f"Artifact: {artifact}\n\n"
                    "Run Diagnostics and use the history repair action to reconcile backup and file artifacts."
                )
            suffix = file_info.get("suffix", "")
            destination = Path(str(target) + suffix) if suffix else target
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(artifact, destination)

    def capture_setting_states(self, keys: list[str]) -> list[dict]:
        return [self._capture_setting_state(key) for key in keys]

    def apply_setting_entries(self, entries: list[dict]) -> None:
        for entry in entries:
            self._apply_setting_state_entry(entry)
        self.settings.sync()

    def record_file_write_action(
        self,
        *,
        label: str,
        action_type: str,
        target_path: str | Path,
        before_state: dict,
        after_state: dict,
        entity_type: str | None = "File",
        entity_id: str | None = None,
        payload: dict | None = None,
        visible_in_history: bool = True,
    ) -> HistoryEntry:
        entry_id = self._insert_entry(
            label=label,
            action_type=action_type,
            entity_type=entity_type,
            entity_id=entity_id or str(target_path),
            reversible=False,
            strategy="event",
            payload={
                **(payload or {}),
                "target_path": str(target_path),
                "before_exists": bool(before_state.get("exists")),
                "after_exists": bool(after_state.get("exists")),
            },
            inverse_payload={"target_path": str(target_path), "state": before_state},
            redo_payload={"target_path": str(target_path), "state": after_state},
            snapshot_before_id=None,
            snapshot_after_id=None,
            move_head=False,
            visible_in_history=visible_in_history,
        )
        return self.fetch_entry(entry_id)

    def record_setting_bundle_change(
        self,
        *,
        label: str,
        before_entries: list[dict],
        after_entries: list[dict],
        entity_id: str | None = None,
        visible_in_history: bool = True,
    ) -> HistoryEntry:
        history_entity_id = entity_id or label
        current = self.get_current_entry()
        if self._can_coalesce_setting_bundle(current, history_entity_id, visible_in_history):
            inverse_payload = current.inverse_payload or {
                "key": "bundle",
                "entries": before_entries,
            }
            self._update_entry_payloads(
                current.entry_id,
                label=label,
                payload={"keys": [entry["setting_key"] for entry in after_entries]},
                inverse_payload=inverse_payload,
                redo_payload={"key": "bundle", "entries": after_entries},
                created_at=self._history_timestamp_now(),
            )
            return self.fetch_entry(current.entry_id)
        entry_id = self._insert_entry(
            label=label,
            action_type="settings.bundle",
            entity_type="Settings",
            entity_id=history_entity_id,
            reversible=True,
            strategy="inverse",
            payload={"keys": [entry["setting_key"] for entry in after_entries]},
            inverse_payload={"key": "bundle", "entries": before_entries},
            redo_payload={"key": "bundle", "entries": after_entries},
            snapshot_before_id=None,
            snapshot_after_id=None,
            move_head=True,
            visible_in_history=visible_in_history,
        )
        return self.fetch_entry(entry_id)

    def register_snapshot(
        self,
        snapshot: SnapshotRecord,
        *,
        kind: str | None = None,
        label: str | None = None,
    ) -> SnapshotRecord:
        snapshot_path = Path(snapshot.db_snapshot_path)
        if not snapshot_path.exists():
            raise FileNotFoundError(snapshot_path)
        register_kind = kind or snapshot.kind or "registered"
        snapshot_dir = self.history_root / "snapshots" / self.db_path.stem
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        registered_path = snapshot_dir / f"{timestamp}_{register_kind}.db"
        shutil.copy2(snapshot_path, registered_path)
        manifest = self._clone_managed_manifest(
            snapshot.manifest, registered_path.with_suffix(".assets")
        )
        return self._insert_snapshot_row(
            kind=register_kind,
            label=label or snapshot.label,
            db_snapshot_path=str(registered_path),
            settings_state=snapshot.settings_state,
            manifest=manifest,
        )

    def register_backup(
        self,
        backup_path: str | Path,
        *,
        kind: str = "manual",
        label: str | None = None,
        source_db_path: str | Path | None = None,
        metadata: dict | None = None,
    ) -> BackupRecord:
        backup = Path(backup_path)
        if not backup.exists():
            raise FileNotFoundError(backup)
        return self._insert_backup_row(
            kind=kind or "manual",
            label=label or backup.name,
            backup_path=str(backup),
            source_db_path=str(source_db_path) if source_db_path is not None else None,
            metadata=metadata or {},
        )

    def record_event(
        self,
        *,
        label: str,
        action_type: str,
        entity_type: str | None = None,
        entity_id: str | None = None,
        payload: dict | None = None,
        visible_in_history: bool = True,
    ) -> int:
        return self._insert_entry(
            label=label,
            action_type=action_type,
            entity_type=entity_type,
            entity_id=entity_id,
            reversible=False,
            strategy="event",
            payload=payload or {},
            inverse_payload=None,
            redo_payload=None,
            snapshot_before_id=None,
            snapshot_after_id=None,
            move_head=False,
            visible_in_history=visible_in_history,
        )

    def record_setting_change(
        self,
        *,
        key: str,
        label: str,
        before_value: Any,
        after_value: Any,
        visible_in_history: bool = True,
    ) -> HistoryEntry:
        entry_id = self._insert_entry(
            label=label,
            action_type=f"settings.{key}",
            entity_type="Settings",
            entity_id=key,
            reversible=True,
            strategy="inverse",
            payload={"key": key},
            inverse_payload={"key": key, "value": self._normalize_json_value(before_value)},
            redo_payload={"key": key, "value": self._normalize_json_value(after_value)},
            snapshot_before_id=None,
            snapshot_after_id=None,
            move_head=True,
            visible_in_history=visible_in_history,
        )
        return self.fetch_entry(entry_id)

    def record_track_create(
        self,
        *,
        track_id: int,
        cleanup_artist_names: list[str],
        cleanup_album_titles: list[str],
    ) -> HistoryEntry:
        after = self.track_service.fetch_track_snapshot(track_id)
        if after is None:
            raise ValueError(f"Track {track_id} not found after create")
        entry_id = self._insert_entry(
            label=f"Create Track: {after.track_title}",
            action_type="track.create",
            entity_type="Track",
            entity_id=str(track_id),
            reversible=True,
            strategy="inverse",
            payload={"track_id": track_id, "track_title": after.track_title},
            inverse_payload={
                "track_id": track_id,
                "cleanup_artist_names": sorted(set(cleanup_artist_names)),
                "cleanup_album_titles": sorted(set(cleanup_album_titles)),
            },
            redo_payload={"snapshot": after.to_dict()},
            snapshot_before_id=None,
            snapshot_after_id=None,
            move_head=True,
        )
        return self.fetch_entry(entry_id)

    def record_track_update(
        self,
        *,
        before_snapshot: TrackSnapshot,
        cleanup_artist_names: list[str],
        cleanup_album_titles: list[str],
    ) -> HistoryEntry:
        after = self.track_service.fetch_track_snapshot(before_snapshot.track_id)
        if after is None:
            raise ValueError(f"Track {before_snapshot.track_id} not found after update")
        entry_id = self._insert_entry(
            label=f"Update Track: {after.track_title}",
            action_type="track.update",
            entity_type="Track",
            entity_id=str(before_snapshot.track_id),
            reversible=True,
            strategy="inverse",
            payload={"track_id": before_snapshot.track_id, "track_title": after.track_title},
            inverse_payload={
                "snapshot": before_snapshot.to_dict(),
                "cleanup_artist_names": sorted(set(cleanup_artist_names)),
                "cleanup_album_titles": sorted(set(cleanup_album_titles)),
            },
            redo_payload={"snapshot": after.to_dict()},
            snapshot_before_id=None,
            snapshot_after_id=None,
            move_head=True,
        )
        return self.fetch_entry(entry_id)

    def record_track_delete(self, *, before_snapshot: TrackSnapshot) -> HistoryEntry:
        entry_id = self._insert_entry(
            label=f"Delete Track: {before_snapshot.track_title}",
            action_type="track.delete",
            entity_type="Track",
            entity_id=str(before_snapshot.track_id),
            reversible=True,
            strategy="inverse",
            payload={
                "track_id": before_snapshot.track_id,
                "track_title": before_snapshot.track_title,
            },
            inverse_payload={"snapshot": before_snapshot.to_dict()},
            redo_payload={"track_id": before_snapshot.track_id},
            snapshot_before_id=None,
            snapshot_after_id=None,
            move_head=True,
        )
        return self.fetch_entry(entry_id)

    # ------------------------------------------------------------------
    # Undo / redo
    # ------------------------------------------------------------------
    def undo(self) -> HistoryEntry | None:
        self._ensure_history_invariants()
        plan = self._visible_undo_plan()
        if not plan:
            return None
        visible_entry = plan[-1]
        for entry in plan:
            self._replay_entry(
                entry,
                entry.inverse_payload,
                direction="undo",
                next_current_entry_id=entry.parent_id,
                next_entry_status=self.STATUS_UNDONE,
            )
        return visible_entry

    def redo(self, entry_id: int | None = None) -> HistoryEntry | None:
        self._ensure_history_invariants()
        if entry_id is not None:
            entry = self.fetch_entry(entry_id)
            plan = [entry] if entry is not None else []
        else:
            plan = self._visible_redo_plan()
        if not plan:
            return None
        visible_entry = next(
            (candidate for candidate in plan if candidate.visible_in_history),
            plan[-1],
        )
        first_entry = plan[0]
        if not self._is_entry_redoable(first_entry):
            raise HistoryRecoveryError(
                f"History entry {first_entry.entry_id} is not redoable from the current position."
            )
        for entry in plan:
            if not self._is_entry_redoable(entry):
                raise HistoryRecoveryError(
                    f"History entry {entry.entry_id} is not redoable from the current position."
                )
            self._replay_entry(
                entry,
                entry.redo_payload,
                direction="redo",
                next_current_entry_id=entry.entry_id,
                next_entry_status=self.STATUS_APPLIED,
            )
        return visible_entry

    def get_default_redo_entry(self) -> HistoryEntry | None:
        self._ensure_history_invariants()
        plan = self._visible_redo_plan()
        return next((entry for entry in plan if entry.visible_in_history), None)

    def _get_default_redo_child(self, parent_id: int | None) -> HistoryEntry | None:
        if parent_id is None:
            row = self.conn.execute(
                f"""
                SELECT
                    {_ENTRY_SELECT_COLUMNS}
                FROM HistoryEntries
                WHERE parent_id IS NULL AND reversible=1 AND status=?
                ORDER BY id DESC
                LIMIT 1
                """,
                (self.STATUS_UNDONE,),
            ).fetchone()
        else:
            row = self.conn.execute(
                f"""
                SELECT
                    {_ENTRY_SELECT_COLUMNS}
                FROM HistoryEntries
                WHERE parent_id=? AND reversible=1 AND status=?
                ORDER BY id DESC
                LIMIT 1
                """,
                (int(parent_id), self.STATUS_UNDONE),
            ).fetchone()
        if not row:
            return None
        return self._entry_from_row(row, current_id=self.get_current_entry_id())

    def _visible_undo_plan(self) -> list[HistoryEntry]:
        entry = self.get_current_entry()
        if entry is None or not entry.reversible or entry.status != self.STATUS_APPLIED:
            return []

        plan: list[HistoryEntry] = []
        seen_ids: set[int] = set()
        current = entry
        while current is not None and current.entry_id not in seen_ids:
            if not current.reversible or current.status != self.STATUS_APPLIED:
                break
            seen_ids.add(current.entry_id)
            plan.append(current)
            if current.visible_in_history:
                return plan
            if current.parent_id is None:
                break
            current = self.fetch_entry(current.parent_id)
        return []

    def _visible_redo_plan(self) -> list[HistoryEntry]:
        plan: list[HistoryEntry] = []
        seen_visible = False
        seen_ids: set[int] = set()
        entry = self._get_default_redo_child(self.get_current_entry_id())
        while entry is not None and entry.entry_id not in seen_ids:
            seen_ids.add(entry.entry_id)
            plan.append(entry)
            if entry.visible_in_history:
                seen_visible = True
            next_entry = self._get_default_redo_child(entry.entry_id)
            if next_entry is None:
                break
            if seen_visible and next_entry.visible_in_history:
                break
            entry = next_entry
        return plan if seen_visible else []

    # ------------------------------------------------------------------
    # Snapshot restore
    # ------------------------------------------------------------------
    def fetch_snapshot(self, snapshot_id: int) -> SnapshotRecord | None:
        row = self.conn.execute(
            """
            SELECT id, created_at, kind, label, db_snapshot_path, settings_json, manifest_json
            FROM HistorySnapshots
            WHERE id=?
            """,
            (int(snapshot_id),),
        ).fetchone()
        if not row:
            return None
        return self._snapshot_from_row(row)

    def delete_snapshot(self, snapshot_id: int) -> None:
        snapshot = self.fetch_snapshot(snapshot_id)
        if snapshot is None:
            raise ValueError(f"Snapshot {snapshot_id} not found")
        ref = self.conn.execute(
            """
            SELECT 1
            FROM HistoryEntries
            WHERE snapshot_before_id=? OR snapshot_after_id=?
            LIMIT 1
            """,
            (int(snapshot_id), int(snapshot_id)),
        ).fetchone()
        if ref:
            raise ValueError("Snapshot is referenced by history and cannot be deleted")

        with self.conn:
            self.conn.execute("DELETE FROM HistorySnapshots WHERE id=?", (int(snapshot_id),))

        snapshot_path = Path(snapshot.db_snapshot_path)
        self._remove_path(snapshot_path)
        self._remove_path(self._snapshot_sidecar_path(snapshot_path))
        for state in (snapshot.manifest or {}).get("managed_directories", {}).values():
            snapshot_asset_path = state.get("snapshot_path")
            if snapshot_asset_path:
                self._remove_path(Path(snapshot_asset_path))

    def _delete_snapshot_if_unreferenced(self, snapshot_id: int) -> None:
        try:
            self.delete_snapshot(snapshot_id)
        except Exception:
            pass

    def inspect_recovery_state(self) -> list[HistoryIssue]:
        self._ensure_registry_sidecars()
        issues: list[HistoryIssue] = []
        current_id = self.get_current_entry_id()
        if current_id is not None and self.fetch_entry(current_id) is None:
            issues.append(
                HistoryIssue(
                    issue_type="stale_current_head",
                    severity="warning",
                    message=f"HistoryHead points to missing entry {current_id}.",
                    entry_id=current_id,
                )
            )

        referenced_snapshot_ids = self._referenced_snapshot_ids()
        for snapshot in self._all_snapshots():
            missing_paths = self._snapshot_missing_paths(snapshot)
            if not missing_paths:
                continue
            issues.append(
                HistoryIssue(
                    issue_type="missing_snapshot_artifact",
                    severity="warning",
                    message=(
                        f"Snapshot #{snapshot.snapshot_id} '{snapshot.label}' is missing "
                        f"{len(missing_paths)} artifact(s)."
                    ),
                    snapshot_id=snapshot.snapshot_id,
                    path=snapshot.db_snapshot_path,
                    details={
                        "missing_paths": [str(path) for path in missing_paths],
                        "referenced": snapshot.snapshot_id in referenced_snapshot_ids,
                    },
                )
            )

        registered_snapshot_paths = {
            str(Path(snapshot.db_snapshot_path))
            for snapshot in self._all_snapshots()
            if snapshot.db_snapshot_path
        }
        for path in self._orphan_snapshot_files(registered_snapshot_paths):
            issues.append(
                HistoryIssue(
                    issue_type="orphan_snapshot_file",
                    severity="warning",
                    message=f"Snapshot file is present on disk but not registered: {path.name}",
                    path=str(path),
                    details=self._read_json_sidecar(self._snapshot_sidecar_path(path)),
                )
            )

        for issue in self._dangling_snapshot_reference_issues():
            issues.append(issue)

        for entry, archived_snapshot in self._all_snapshot_archive_entries():
            missing_paths = self._archived_snapshot_missing_paths(archived_snapshot)
            if not missing_paths:
                continue
            issues.append(
                HistoryIssue(
                    issue_type="missing_snapshot_archive",
                    severity="warning",
                    message=(
                        f"History entry #{entry.entry_id} ({entry.action_type}) is missing "
                        f"{len(missing_paths)} archived snapshot artifact(s)."
                    ),
                    entry_id=entry.entry_id,
                    details={
                        "missing_paths": [str(path) for path in missing_paths],
                        "snapshot_id": self._int_or_none((entry.payload or {}).get("snapshot_id")),
                    },
                )
            )

        registered_backup_paths = {
            str(Path(record.backup_path)) for record in self._all_backups() if record.backup_path
        }
        for backup in self._all_backups():
            backup_path = Path(backup.backup_path)
            if backup_path.exists():
                continue
            history_entry = self._find_backup_entry_for_path(backup_path)
            issues.append(
                HistoryIssue(
                    issue_type="missing_backup_file",
                    severity="warning",
                    message=f"Backup #{backup.backup_id} '{backup.label}' is missing on disk.",
                    backup_id=backup.backup_id,
                    path=str(backup_path),
                    entry_id=history_entry.entry_id if history_entry is not None else None,
                    details={
                        "recoverable_from_history": bool(
                            history_entry
                            and self._state_has_all_artifacts(
                                (history_entry.redo_payload or {}).get("state", {})
                            )
                        )
                    },
                )
            )

        for path in self._orphan_backup_files(registered_backup_paths):
            issues.append(
                HistoryIssue(
                    issue_type="orphan_backup_file",
                    severity="warning",
                    message=f"Backup file is present on disk but not registered: {path.name}",
                    path=str(path),
                    details=self._read_json_sidecar(self._backup_sidecar_path(path)),
                )
            )

        for entry in self._all_backup_file_entries():
            backup_path = self._backup_entry_target_path(entry)
            redo_state = (entry.redo_payload or {}).get("state", {})
            missing_paths = self._file_state_missing_paths(redo_state)
            if not missing_paths or not backup_path.exists():
                continue
            issues.append(
                HistoryIssue(
                    issue_type="missing_backup_history_artifact",
                    severity="warning",
                    message=(
                        f"History entry #{entry.entry_id} is missing stored backup artifacts for "
                        f"{backup_path.name}."
                    ),
                    entry_id=entry.entry_id,
                    path=str(backup_path),
                    details={"missing_paths": [str(path) for path in missing_paths]},
                )
            )

        return issues

    def repair_recovery_state(self) -> HistoryRepairResult:
        changes: list[str] = []
        unresolved: list[str] = []
        self._ensure_history_invariants(changes=changes)
        self._ensure_registry_sidecars()

        referenced_snapshot_ids = self._referenced_snapshot_ids()
        orphan_snapshot_paths = self._orphan_snapshot_files(
            {
                str(Path(snapshot.db_snapshot_path))
                for snapshot in self._all_snapshots()
                if snapshot.db_snapshot_path
            }
        )
        orphan_snapshot_by_id: dict[int, Path] = {}
        for path in orphan_snapshot_paths:
            sidecar = self._read_json_sidecar(self._snapshot_sidecar_path(path))
            snapshot_id = self._int_or_none(sidecar.get("snapshot_id")) if sidecar else None
            if snapshot_id is not None:
                orphan_snapshot_by_id[snapshot_id] = path

        for snapshot in self._all_snapshots():
            missing_paths = self._snapshot_missing_paths(snapshot)
            if not missing_paths:
                continue
            orphan_match = orphan_snapshot_by_id.pop(snapshot.snapshot_id, None)
            if orphan_match is not None:
                metadata = self._load_snapshot_metadata(orphan_match)
                with self.conn:
                    self.conn.execute(
                        """
                        UPDATE HistorySnapshots
                        SET kind=?, label=?, db_snapshot_path=?, settings_json=?, manifest_json=?
                        WHERE id=?
                        """,
                        (
                            metadata["kind"],
                            metadata["label"],
                            str(orphan_match),
                            json.dumps(metadata["settings_state"]),
                            json.dumps(metadata["manifest"]),
                            int(snapshot.snapshot_id),
                        ),
                    )
                refreshed = self.fetch_snapshot(snapshot.snapshot_id)
                if refreshed is not None:
                    self._write_snapshot_sidecar(refreshed)
                changes.append(
                    f"Re-linked snapshot #{snapshot.snapshot_id} to recovered file {orphan_match.name}."
                )
                continue

            if self._restore_snapshot_from_archive_if_possible(snapshot):
                changes.append(
                    f"Recovered missing artifacts for snapshot #{snapshot.snapshot_id} from archived history data."
                )
                continue

            if snapshot.snapshot_id in referenced_snapshot_ids:
                affected_entries = self._quarantine_snapshot_references(snapshot.snapshot_id)
                self._remove_snapshot_record(snapshot.snapshot_id)
                changes.append(
                    f"Quarantined {len(affected_entries)} history entr{'y' if len(affected_entries) == 1 else 'ies'} "
                    f"that referenced missing snapshot #{snapshot.snapshot_id}."
                )
                continue

            self._remove_snapshot_record(snapshot.snapshot_id)
            changes.append(
                f"Removed stale snapshot #{snapshot.snapshot_id} because required artifacts were missing."
            )

        registered_snapshot_paths = {
            str(Path(snapshot.db_snapshot_path))
            for snapshot in self._all_snapshots()
            if snapshot.db_snapshot_path
        }
        for path in self._orphan_snapshot_files(registered_snapshot_paths):
            if not self._snapshot_sidecar_path(path).exists():
                unresolved.append(
                    f"Left orphan snapshot file {path.name} in place because no sidecar metadata was available."
                )
                continue
            metadata = self._load_snapshot_metadata(path)
            requested_snapshot_id = self._int_or_none(metadata.get("snapshot_id"))
            if requested_snapshot_id is not None and self.fetch_snapshot(requested_snapshot_id):
                requested_snapshot_id = None
            restored = self._insert_snapshot_row(
                kind=str(metadata["kind"]),
                label=str(metadata["label"]),
                db_snapshot_path=str(path),
                settings_state=dict(metadata["settings_state"]),
                manifest=dict(metadata["manifest"]),
                snapshot_id=requested_snapshot_id,
            )
            changes.append(
                f"Registered orphan snapshot file {path.name} as snapshot #{restored.snapshot_id}."
            )

        for entry, archived_snapshot in self._all_snapshot_archive_entries():
            missing_paths = self._archived_snapshot_missing_paths(archived_snapshot)
            if not missing_paths:
                continue
            snapshot_id = self._int_or_none((entry.payload or {}).get("snapshot_id"))
            source_snapshot = self.fetch_snapshot(snapshot_id) if snapshot_id is not None else None
            if source_snapshot is not None and not self._snapshot_missing_paths(source_snapshot):
                rebuilt_archive = self._archive_snapshot_record(
                    source_snapshot, prefix=f"repair_{entry.action_type.replace('.', '_')}"
                )
                if entry.action_type == "snapshot.create":
                    self._update_entry_payloads(
                        entry.entry_id,
                        redo_payload={"archived_snapshot": rebuilt_archive},
                    )
                else:
                    self._update_entry_payloads(
                        entry.entry_id,
                        inverse_payload={"archived_snapshot": rebuilt_archive},
                    )
                changes.append(
                    f"Rebuilt archived snapshot artifacts for history entry #{entry.entry_id}."
                )
                continue
            unresolved.append(
                f"History entry #{entry.entry_id} is missing archived snapshot artifacts and no current snapshot copy was available."
            )

        for entry in self._all_backup_file_entries():
            registered = self._register_backup_from_history_entry_if_needed(entry)
            if registered is not None:
                changes.append(registered)

        orphan_backup_paths = self._orphan_backup_files(
            {str(Path(record.backup_path)) for record in self._all_backups() if record.backup_path}
        )
        orphan_backup_by_id: dict[int, Path] = {}
        for path in orphan_backup_paths:
            sidecar = self._read_json_sidecar(self._backup_sidecar_path(path))
            backup_id = self._int_or_none(sidecar.get("backup_id")) if sidecar else None
            if backup_id is not None:
                orphan_backup_by_id[backup_id] = path

        for backup in self._all_backups():
            backup_path = Path(backup.backup_path)
            if backup_path.exists():
                continue
            orphan_match = orphan_backup_by_id.pop(backup.backup_id, None)
            if orphan_match is not None:
                metadata = self._load_backup_metadata(orphan_match)
                with self.conn:
                    self.conn.execute(
                        """
                        UPDATE HistoryBackups
                        SET kind=?, label=?, backup_path=?, source_db_path=?, metadata_json=?
                        WHERE id=?
                        """,
                        (
                            metadata["kind"],
                            metadata["label"],
                            str(orphan_match),
                            metadata["source_db_path"],
                            json.dumps(metadata["metadata"]),
                            int(backup.backup_id),
                        ),
                    )
                refreshed = self.fetch_backup(backup.backup_id)
                if refreshed is not None:
                    self._write_backup_sidecar(refreshed)
                changes.append(
                    f"Re-linked backup #{backup.backup_id} to recovered file {orphan_match.name}."
                )
                continue

            history_entry = self._find_backup_entry_for_path(backup_path)
            if history_entry is not None and self._restore_backup_from_history_entry(history_entry):
                refreshed = self.fetch_backup(backup.backup_id)
                if refreshed is not None:
                    self._write_backup_sidecar(refreshed)
                changes.append(
                    f"Restored missing backup #{backup.backup_id} from history artifacts."
                )
                continue

            with self.conn:
                self.conn.execute("DELETE FROM HistoryBackups WHERE id=?", (int(backup.backup_id),))
            changes.append(
                f"Removed stale backup record #{backup.backup_id} because its file was missing and could not be reconstructed."
            )

        registered_backup_paths = {
            str(Path(record.backup_path)) for record in self._all_backups() if record.backup_path
        }
        for path in self._orphan_backup_files(registered_backup_paths):
            metadata = self._load_backup_metadata(path)
            requested_backup_id = self._int_or_none(metadata.get("backup_id"))
            if requested_backup_id is not None and self.fetch_backup(requested_backup_id):
                requested_backup_id = None
            restored = self._insert_backup_row(
                kind=str(metadata["kind"]),
                label=str(metadata["label"]),
                backup_path=str(path),
                source_db_path=(
                    str(metadata["source_db_path"]) if metadata["source_db_path"] else None
                ),
                metadata=dict(metadata["metadata"]),
                backup_id=requested_backup_id,
            )
            changes.append(
                f"Registered orphan backup file {path.name} as backup #{restored.backup_id}."
            )

        for entry in self._all_backup_file_entries():
            backup_path = self._backup_entry_target_path(entry)
            redo_state = (entry.redo_payload or {}).get("state", {})
            missing_paths = self._file_state_missing_paths(redo_state)
            if not missing_paths or not backup_path.exists():
                continue
            refreshed_state = self.capture_file_state(
                backup_path,
                companion_suffixes=tuple(redo_state.get("companion_suffixes", [])),
            )
            self._update_entry_payloads(
                entry.entry_id,
                redo_payload={"target_path": str(backup_path), "state": refreshed_state},
            )
            changes.append(
                f"Rebuilt backup history artifacts for entry #{entry.entry_id} from {backup_path.name}."
            )

        return HistoryRepairResult(changes=changes, unresolved=unresolved)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _entry_from_row(self, row, *, current_id: int | None) -> HistoryEntry:
        return HistoryEntry(
            entry_id=int(row[0]),
            parent_id=int(row[1]) if row[1] is not None else None,
            created_at=row[2] or "",
            label=row[3] or "",
            action_type=row[4] or "",
            entity_type=row[5],
            entity_id=row[6],
            reversible=bool(row[7]),
            strategy=row[8] or "",
            payload=self._loads(row[9]),
            inverse_payload=self._loads(row[10]) if row[10] else None,
            redo_payload=self._loads(row[11]) if row[11] else None,
            snapshot_before_id=int(row[12]) if row[12] is not None else None,
            snapshot_after_id=int(row[13]) if row[13] is not None else None,
            status=row[14] or "applied",
            visible_in_history=bool(row[15]),
            is_current=int(row[0]) == current_id,
        )

    def _snapshot_from_row(self, row) -> SnapshotRecord:
        return SnapshotRecord(
            snapshot_id=int(row[0]),
            created_at=row[1] or "",
            kind=row[2] or "",
            label=row[3] or "",
            db_snapshot_path=row[4] or "",
            settings_state=self._loads(row[5]),
            manifest=self._loads(row[6]),
        )

    def _backup_from_row(self, row) -> BackupRecord:
        return BackupRecord(
            backup_id=int(row[0]),
            created_at=row[1] or "",
            kind=row[2] or "",
            label=row[3] or "",
            backup_path=row[4] or "",
            source_db_path=row[5],
            metadata=self._loads(row[6]),
        )

    def _insert_entry(
        self,
        *,
        label: str,
        action_type: str,
        entity_type: str | None,
        entity_id: str | None,
        reversible: bool,
        strategy: str,
        payload: dict,
        inverse_payload: dict | None,
        redo_payload: dict | None,
        snapshot_before_id: int | None,
        snapshot_after_id: int | None,
        move_head: bool,
        visible_in_history: bool = True,
    ) -> int:
        parent_id = self.get_current_entry_id()
        with self.conn:
            cur = self.conn.cursor()
            if move_head:
                self._mark_redo_children_superseded(parent_id, cursor=cur)
            cur.execute(
                """
                INSERT INTO HistoryEntries (
                    parent_id, label, action_type, entity_type, entity_id,
                    reversible, strategy, payload_json, inverse_json, redo_json,
                    snapshot_before_id, snapshot_after_id, status, visible_in_history
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'applied', ?)
                """,
                (
                    parent_id,
                    label,
                    action_type,
                    entity_type,
                    entity_id,
                    int(reversible),
                    strategy,
                    json.dumps(payload),
                    json.dumps(inverse_payload) if inverse_payload is not None else None,
                    json.dumps(redo_payload) if redo_payload is not None else None,
                    snapshot_before_id,
                    snapshot_after_id,
                    int(bool(visible_in_history)),
                ),
            )
            entry_id = int(cur.lastrowid)
            if move_head:
                self._set_current_entry_id_in_cursor(entry_id, cursor=cur)
        return entry_id

    def _set_current_entry_id(self, entry_id: int | None) -> None:
        with self.conn:
            self._set_current_entry_id_in_cursor(entry_id, cursor=self.conn.cursor())

    def _set_current_entry_id_in_cursor(
        self, entry_id: int | None, *, cursor: sqlite3.Cursor
    ) -> None:
        cursor.execute(
            """
            INSERT INTO HistoryHead (id, current_entry_id)
            VALUES (1, ?)
            ON CONFLICT(id) DO UPDATE SET current_entry_id=excluded.current_entry_id
            """,
            (entry_id,),
        )

    def _set_entry_status_in_cursor(
        self,
        entry_id: int,
        status: str,
        *,
        cursor: sqlite3.Cursor,
    ) -> None:
        cursor.execute(
            "UPDATE HistoryEntries SET status=? WHERE id=?",
            (status, int(entry_id)),
        )

    def _mark_redo_children_superseded(
        self, parent_id: int | None, *, cursor: sqlite3.Cursor
    ) -> None:
        if parent_id is None:
            cursor.execute(
                """
                UPDATE HistoryEntries
                SET status=?
                WHERE parent_id IS NULL AND status=?
                """,
                (self.STATUS_SUPERSEDED, self.STATUS_UNDONE),
            )
            return
        cursor.execute(
            """
            UPDATE HistoryEntries
            SET status=?
            WHERE parent_id=? AND status=?
            """,
            (self.STATUS_SUPERSEDED, int(parent_id), self.STATUS_UNDONE),
        )

    def _is_entry_redoable(self, entry: HistoryEntry) -> bool:
        current_id = self.get_current_entry_id()
        if entry.status != self.STATUS_UNDONE:
            return False
        if current_id is None:
            return entry.parent_id is None
        return entry.parent_id == current_id

    def _replay_entry(
        self,
        entry: HistoryEntry,
        payload: dict | None,
        *,
        direction: str,
        next_current_entry_id: int | None,
        next_entry_status: str,
    ) -> None:
        if entry.strategy == "snapshot":
            target_snapshot_id = (
                entry.snapshot_before_id if direction == "undo" else entry.snapshot_after_id
            )
            rollback_snapshot_id = (
                entry.snapshot_after_id if direction == "undo" else entry.snapshot_before_id
            )
            rollback_head_id = entry.entry_id if direction == "undo" else entry.parent_id
            rollback_status = self.STATUS_APPLIED if direction == "undo" else self.STATUS_UNDONE
            if target_snapshot_id is None:
                raise HistoryRecoveryError(
                    f"History entry {entry.entry_id} is missing its {direction} snapshot."
                )
            target_snapshot = self.fetch_snapshot(target_snapshot_id)
            if target_snapshot is None:
                raise HistoryRecoveryError(
                    f"Snapshot {target_snapshot_id} referenced by history entry {entry.entry_id} was not found."
                )

            rollback_file_states = []
            for effect in (entry.payload or {}).get("file_effects", []):
                target_path = effect.get("target_path")
                if not target_path:
                    continue
                desired_state = (
                    effect.get("before_state") if direction == "undo" else effect.get("after_state")
                )
                if desired_state is None:
                    continue
                rollback_file_states.append(
                    (
                        str(target_path),
                        self.capture_file_state(
                            target_path,
                            companion_suffixes=tuple(desired_state.get("companion_suffixes", [])),
                        ),
                    )
                )

            try:
                self._restore_snapshot_state(
                    target_snapshot,
                    next_current_entry_id=next_current_entry_id,
                    update_current_entry=True,
                    status_updates=[(entry.entry_id, next_entry_status)],
                )
                self._apply_snapshot_side_effects(entry.payload, direction=direction)
            except Exception:
                for target_path, state in rollback_file_states:
                    try:
                        self.restore_file_state(target_path, state)
                    except Exception:
                        pass
                if rollback_snapshot_id is not None:
                    rollback_snapshot = self.fetch_snapshot(rollback_snapshot_id)
                    if rollback_snapshot is not None:
                        try:
                            self._restore_snapshot_state(
                                rollback_snapshot,
                                next_current_entry_id=rollback_head_id,
                                update_current_entry=True,
                                status_updates=[(entry.entry_id, rollback_status)],
                            )
                        except Exception:
                            pass
                raise
            return

        self._apply_entry_payload(entry, payload, direction=direction)
        with self.conn:
            cur = self.conn.cursor()
            self._set_entry_status_in_cursor(entry.entry_id, next_entry_status, cursor=cur)
            self._set_current_entry_id_in_cursor(next_current_entry_id, cursor=cur)

    def _apply_entry_payload(
        self, entry: HistoryEntry, payload: dict | None, *, direction: str
    ) -> None:
        if entry.strategy == "snapshot":
            snapshot_id = (
                entry.snapshot_before_id if direction == "undo" else entry.snapshot_after_id
            )
            if snapshot_id is None:
                return
            snapshot = self.fetch_snapshot(snapshot_id)
            if snapshot is None:
                raise HistoryRecoveryError(
                    f"Snapshot {snapshot_id} referenced by history entry {entry.entry_id} was not found."
                )
            self._restore_snapshot_state(snapshot)
            self._apply_snapshot_side_effects(entry.payload, direction=direction)
            return

        action_type = entry.action_type
        if payload is None:
            return

        if action_type == "track.create":
            if direction == "undo":
                self._undo_track_create(payload)
            else:
                self._restore_track_from_payload(payload)
        elif action_type == "track.update":
            if direction == "undo":
                self._restore_track_from_payload(payload)
                self._cleanup_catalog_from_payload(payload)
            else:
                self._restore_track_from_payload(payload)
        elif action_type == "track.delete":
            if direction == "undo":
                self._restore_track_from_payload(payload)
            else:
                self._redo_track_delete(payload)
        elif action_type == "snapshot.create":
            if direction == "undo":
                self._apply_snapshot_create_undo(entry, payload)
            else:
                self._apply_snapshot_create_redo(entry, payload)
        elif action_type == "snapshot.delete":
            if direction == "undo":
                self._apply_snapshot_delete_undo(entry, payload)
            else:
                self._apply_snapshot_delete_redo(entry, payload)
        elif action_type.startswith("file."):
            self._apply_file_payload(payload)
        elif action_type.startswith("settings."):
            self._apply_setting_payload(payload)
        else:
            raise ValueError(f"Undo/redo not implemented for {action_type}")

    def _undo_track_create(self, payload: dict) -> None:
        track_id = int(payload["track_id"])
        with self.conn:
            cur = self.conn.cursor()
            cur.execute("DELETE FROM Tracks WHERE id=?", (track_id,))
            self.track_service.delete_unused_artists_by_names(
                payload.get("cleanup_artist_names", []), cursor=cur
            )
            self.track_service.delete_unused_albums_by_titles(
                payload.get("cleanup_album_titles", []), cursor=cur
            )

    def _redo_track_delete(self, payload: dict) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM Tracks WHERE id=?", (int(payload["track_id"]),))

    def _restore_track_from_payload(self, payload: dict) -> None:
        snapshot = TrackSnapshot(**payload["snapshot"])
        with self.conn:
            cur = self.conn.cursor()
            self.track_service.restore_track_snapshot(snapshot, cursor=cur)

    def _cleanup_catalog_from_payload(self, payload: dict) -> None:
        with self.conn:
            cur = self.conn.cursor()
            self.track_service.delete_unused_artists_by_names(
                payload.get("cleanup_artist_names", []), cursor=cur
            )
            self.track_service.delete_unused_albums_by_titles(
                payload.get("cleanup_album_titles", []), cursor=cur
            )

    def _apply_setting_payload(self, payload: dict) -> None:
        key = payload["key"]
        if key == "bundle":
            for entry in payload.get("entries", []):
                self._apply_setting_state_entry(entry)
            self.settings.sync()
            return

        value = payload["value"]
        if key == "identity":
            self.settings_mutations.set_identity(
                window_title=value.get("window_title") or "",
                icon_path=value.get("icon_path") or "",
            )
        elif key == "artist_code":
            self.settings_mutations.set_artist_code(str(value))
        elif key == "auto_snapshot_enabled":
            self.settings_mutations.set_auto_snapshot_enabled(bool(value))
        elif key == "auto_snapshot_interval_minutes":
            self.settings_mutations.set_auto_snapshot_interval_minutes(int(value))
        elif key == "history_retention_mode":
            self.settings_mutations.set_history_retention_mode(str(value))
        elif key == "history_auto_cleanup_enabled":
            self.settings_mutations.set_history_auto_cleanup_enabled(bool(value))
        elif key == "history_storage_budget_mb":
            self.settings_mutations.set_history_storage_budget_mb(int(value))
        elif key == "history_auto_snapshot_keep_latest":
            self.settings_mutations.set_history_auto_snapshot_keep_latest(int(value))
        elif key == "history_prune_pre_restore_copies_after_days":
            self.settings_mutations.set_history_prune_pre_restore_copies_after_days(int(value))
        elif key == "theme_settings":
            if not isinstance(value, dict):
                raise ValueError("Theme settings payload must be a dict")
            for theme_key in theme_setting_keys():
                self.settings.setValue(f"theme/{theme_key}", value.get(theme_key))
            self.settings.sync()
        elif key == "theme_library":
            self.settings.setValue("theme/library_json", json.dumps(value or {}, sort_keys=True))
            self.settings.sync()
        elif key == "isrc_prefix":
            self.settings_mutations.set_isrc_prefix(str(value))
        elif key == "sena_number":
            self.settings_mutations.set_sena_number(str(value))
        elif key == "btw_number":
            self.settings_mutations.set_btw_number(str(value))
        elif key == "buma_relatie_nummer":
            self.settings_mutations.set_buma_relatie_nummer(str(value))
        elif key == "buma_ipi":
            self.settings_mutations.set_buma_ipi(str(value))
        elif key == "owner_party_id":
            owner_party_id = None if value in (None, "") else int(value)
            self.settings_mutations.set_owner_party_id(owner_party_id)
        else:
            raise ValueError(f"Unknown setting history key: {key}")

    def _apply_file_payload(self, payload: dict) -> None:
        self.restore_file_state(payload["target_path"], payload["state"])

    def _apply_snapshot_side_effects(self, payload: dict | None, *, direction: str) -> None:
        if not payload:
            return
        for effect in payload.get("file_effects", []):
            state = effect.get("before_state") if direction == "undo" else effect.get("after_state")
            if state is None:
                continue
            self.restore_file_state(effect["target_path"], state)

    def _apply_snapshot_create_undo(self, entry: HistoryEntry, payload: dict) -> None:
        snapshot_id = payload.get("snapshot_id")
        if snapshot_id is None:
            raise ValueError("Missing snapshot_id for snapshot.create undo")
        self.delete_snapshot(int(snapshot_id))

    def _apply_snapshot_create_redo(self, entry: HistoryEntry, payload: dict) -> None:
        archived_snapshot = payload.get("archived_snapshot")
        if not archived_snapshot:
            raise ValueError("Missing archived snapshot for snapshot.create redo")
        restored = self._restore_snapshot_from_archive(archived_snapshot)
        self._update_entry_payloads(
            entry.entry_id,
            payload={"snapshot_id": restored.snapshot_id, "label": restored.label},
            inverse_payload={"snapshot_id": restored.snapshot_id},
        )

    def _apply_snapshot_delete_undo(self, entry: HistoryEntry, payload: dict) -> None:
        archived_snapshot = payload.get("archived_snapshot")
        if not archived_snapshot:
            raise ValueError("Missing archived snapshot for snapshot.delete undo")
        restored = self._restore_snapshot_from_archive(archived_snapshot)
        self._update_entry_payloads(
            entry.entry_id,
            payload={"snapshot_id": restored.snapshot_id, "label": restored.label},
            redo_payload={"snapshot_id": restored.snapshot_id},
        )

    def _apply_snapshot_delete_redo(self, entry: HistoryEntry, payload: dict) -> None:
        snapshot_id = payload.get("snapshot_id")
        if snapshot_id is None:
            raise ValueError("Missing snapshot_id for snapshot.delete redo")
        self.delete_snapshot(int(snapshot_id))

    def _create_snapshot(self, *, kind: str, label: str) -> SnapshotRecord:
        snapshot_dir = self.history_root / "snapshots" / self.db_path.stem
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        snapshot_path = snapshot_dir / f"{timestamp}_{kind}.db"

        self.conn.commit()
        snapshot_conn = sqlite3.connect(str(snapshot_path))
        try:
            self.conn.backup(snapshot_conn)
            snapshot_conn.commit()
        finally:
            snapshot_conn.close()

        settings_state = self._capture_settings_state()
        manifest = self._capture_managed_state(snapshot_path.with_suffix(".assets"))
        return self._insert_snapshot_row(
            kind=kind,
            label=label,
            db_snapshot_path=str(snapshot_path),
            settings_state=settings_state,
            manifest=manifest,
        )

    def _restore_snapshot_state(
        self,
        snapshot: SnapshotRecord,
        *,
        next_current_entry_id: int | None | object = _UNSET,
        update_current_entry: bool = False,
        status_updates: list[tuple[int, str]] | None = None,
    ) -> None:
        self._validate_snapshot_restore_ready(snapshot)
        snapshot_path = Path(snapshot.db_snapshot_path)
        rollback_root = self.history_root / "restore_rollbacks" / self.db_path.stem
        rollback_root.mkdir(parents=True, exist_ok=True)
        rollback_dir = Path(
            tempfile.mkdtemp(prefix=f"{self.db_path.stem}_", dir=str(rollback_root))
        )
        rollback_manifest: dict = {}
        previous_settings_state = self._capture_settings_state()
        try:
            rollback_manifest = self._capture_managed_state(rollback_dir / "managed")
        except Exception:
            rollback_manifest = {}

        attach_path = snapshot_path.as_posix()
        external_restore_started = False
        self.conn.commit()
        self.conn.execute("PRAGMA foreign_keys = OFF")
        self.conn.execute("ATTACH DATABASE ? AS snapshot_restore", (attach_path,))
        try:
            try:
                self.conn.execute("BEGIN")
                for table_name in self._snapshot_domain_tables("main"):
                    self.conn.execute(f"DELETE FROM {table_name}")
                for table_name in self._snapshot_domain_tables("snapshot_restore"):
                    if not self._table_exists("snapshot_restore", table_name):
                        continue
                    columns = self._shared_columns(table_name)
                    if not columns:
                        continue
                    cols_sql = ", ".join(columns)
                    self.conn.execute(
                        f"INSERT INTO {table_name} ({cols_sql}) "
                        f"SELECT {cols_sql} FROM snapshot_restore.{table_name}"
                    )
                if update_current_entry:
                    self._set_current_entry_id_in_cursor(
                        (next_current_entry_id if isinstance(next_current_entry_id, int) else None),
                        cursor=self.conn.cursor(),
                    )
                if status_updates:
                    cur = self.conn.cursor()
                    for entry_id, status in status_updates:
                        self._set_entry_status_in_cursor(entry_id, status, cursor=cur)

                external_restore_started = True
                self._restore_managed_state(snapshot.manifest)
                self._apply_settings_state(snapshot.settings_state)
                self.conn.commit()
            except Exception as exc:
                self.conn.rollback()
                rollback_error = None
                if external_restore_started:
                    rollback_error = self._restore_external_state(
                        rollback_manifest=rollback_manifest,
                        settings_state=previous_settings_state,
                    )
                if rollback_error is not None:
                    raise HistoryRecoveryError(
                        f"{exc} (external rollback also failed: {rollback_error})"
                    ) from exc
                raise
        finally:
            self.conn.execute("DETACH DATABASE snapshot_restore")
            self.conn.execute("PRAGMA foreign_keys = ON")
            self._remove_path(rollback_dir)

    def _insert_snapshot_row(
        self,
        *,
        kind: str,
        label: str,
        db_snapshot_path: str,
        settings_state: dict,
        manifest: dict,
        snapshot_id: int | None = None,
    ) -> SnapshotRecord:
        with self.conn:
            cur = self.conn.cursor()
            if snapshot_id is None:
                cur.execute(
                    """
                    INSERT INTO HistorySnapshots (kind, label, db_snapshot_path, settings_json, manifest_json)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        kind,
                        label,
                        db_snapshot_path,
                        json.dumps(settings_state),
                        json.dumps(manifest),
                    ),
                )
                snapshot_id = int(cur.lastrowid)
            else:
                cur.execute(
                    """
                    INSERT INTO HistorySnapshots (
                        id, kind, label, db_snapshot_path, settings_json, manifest_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        int(snapshot_id),
                        kind,
                        label,
                        db_snapshot_path,
                        json.dumps(settings_state),
                        json.dumps(manifest),
                    ),
                )
        snapshot = self.fetch_snapshot(snapshot_id)
        if snapshot is None:
            raise RuntimeError(f"Snapshot {snapshot_id} could not be reloaded")
        self._write_snapshot_sidecar(snapshot)
        return snapshot

    def _insert_backup_row(
        self,
        *,
        kind: str,
        label: str,
        backup_path: str,
        source_db_path: str | None,
        metadata: dict,
        backup_id: int | None = None,
    ) -> BackupRecord:
        with self.conn:
            cur = self.conn.cursor()
            if backup_id is None:
                cur.execute(
                    """
                    INSERT INTO HistoryBackups (kind, label, backup_path, source_db_path, metadata_json)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        kind,
                        label,
                        backup_path,
                        source_db_path,
                        json.dumps(metadata or {}),
                    ),
                )
                backup_id = int(cur.lastrowid)
            else:
                cur.execute(
                    """
                    INSERT INTO HistoryBackups (
                        id, kind, label, backup_path, source_db_path, metadata_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        int(backup_id),
                        kind,
                        label,
                        backup_path,
                        source_db_path,
                        json.dumps(metadata or {}),
                    ),
                )
        record = self.fetch_backup(backup_id)
        if record is None:
            raise RuntimeError(f"Backup record {backup_id} could not be reloaded")
        self._write_backup_sidecar(record)
        return record

    def _table_exists(self, db_alias: str, table_name: str) -> bool:
        row = self.conn.execute(
            f"SELECT 1 FROM {db_alias}.sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        ).fetchone()
        return bool(row)

    def _snapshot_domain_tables(self, db_alias: str) -> list[str]:
        rows = self.conn.execute(
            f"""
            SELECT name
            FROM {db_alias}.sqlite_master
            WHERE type='table'
              AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        ).fetchall()
        return [
            str(row[0])
            for row in rows
            if row and row[0] and str(row[0]) not in self.SNAPSHOT_EXCLUDED_TABLES
        ]

    def _shared_columns(self, table_name: str) -> list[str]:
        main_cols = {
            row[1] for row in self.conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        }
        snapshot_cols = {
            row[1]
            for row in self.conn.execute(
                f"PRAGMA snapshot_restore.table_info({table_name})"
            ).fetchall()
        }
        return [
            column
            for column in self._ordered_columns(table_name)
            if column in main_cols and column in snapshot_cols
        ]

    def _ordered_columns(self, table_name: str) -> list[str]:
        rows = self.conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        return [row[1] for row in rows]

    def _history_tables_ready(self) -> bool:
        required = {"HistoryEntries", "HistoryHead", "HistorySnapshots", "HistoryBackups"}
        rows = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'History%'"
        ).fetchall()
        table_names = {str(row[0]) for row in rows if row and row[0]}
        return required.issubset(table_names)

    def _entry_affects_state(self, *, action_type: str, strategy: str, reversible: bool) -> bool:
        return bool(reversible)

    def _ensure_history_invariants(self, *, changes: list[str] | None = None) -> None:
        if not self._history_tables_ready():
            return

        rows = self.conn.execute(
            """
            SELECT id, parent_id, action_type, strategy, reversible, status
            FROM HistoryEntries
            ORDER BY id
            """
        ).fetchall()
        if not rows:
            if self.get_current_entry_id() is not None:
                self._set_current_entry_id(None)
                if changes is not None:
                    changes.append(
                        "Cleared stale HistoryHead pointer because no history entries remain."
                    )
            return

        snapshot_ids = {snapshot.snapshot_id for snapshot in self._all_snapshots()}
        entry_state: dict[int, dict[str, object]] = {}
        for entry_id, parent_id, action_type, strategy, reversible, status in rows:
            reversible_bool = bool(reversible)
            affects_state = self._entry_affects_state(
                action_type=str(action_type or ""),
                strategy=str(strategy or ""),
                reversible=reversible_bool,
            )
            entry_state[int(entry_id)] = {
                "id": int(entry_id),
                "parent_id": int(parent_id) if parent_id is not None else None,
                "action_type": str(action_type or ""),
                "strategy": str(strategy or ""),
                "reversible": reversible_bool,
                "status": str(status or self.STATUS_APPLIED),
                "affects_state": affects_state,
            }

        with self.conn:
            cur = self.conn.cursor()
            changed = False

            # Non-reversible audit/event rows should never sit on the main undo chain.
            for state in entry_state.values():
                if state["affects_state"]:
                    continue
                if state["reversible"]:
                    cur.execute(
                        "UPDATE HistoryEntries SET reversible=0, status=? WHERE id=?",
                        (self.STATUS_APPLIED, int(state["id"])),
                    )
                    state["reversible"] = False
                    state["status"] = self.STATUS_APPLIED
                    changed = True
                    if changes is not None:
                        changes.append(
                            f"Converted non-state history entry #{state['id']} into a non-undoable event."
                        )

            # Entries that reference deleted snapshots cannot remain reversible.
            dangling_rows = self.conn.execute(
                """
                SELECT id, snapshot_before_id, snapshot_after_id
                FROM HistoryEntries
                WHERE reversible=1
                  AND (snapshot_before_id IS NOT NULL OR snapshot_after_id IS NOT NULL)
                """
            ).fetchall()
            for entry_id, before_id, after_id in dangling_rows:
                missing_ref = False
                if before_id is not None and int(before_id) not in snapshot_ids:
                    missing_ref = True
                if after_id is not None and int(after_id) not in snapshot_ids:
                    missing_ref = True
                if not missing_ref:
                    continue
                cur.execute(
                    """
                    UPDATE HistoryEntries
                    SET reversible=0,
                        status=?,
                        snapshot_before_id=?,
                        snapshot_after_id=?
                    WHERE id=?
                    """,
                    (
                        self.STATUS_ARTIFACT_MISSING,
                        before_id if before_id in snapshot_ids else None,
                        after_id if after_id in snapshot_ids else None,
                        int(entry_id),
                    ),
                )
                state = entry_state.get(int(entry_id))
                if state is not None:
                    state["reversible"] = False
                    state["status"] = self.STATUS_ARTIFACT_MISSING
                    state["affects_state"] = False
                changed = True
                if changes is not None:
                    changes.append(
                        f"Disabled undo/redo for history entry #{entry_id} because a referenced snapshot is missing."
                    )

            def normalized_stateful_parent(parent_id: int | None) -> int | None:
                seen: set[int] = set()
                candidate = int(parent_id) if parent_id is not None else None
                while candidate is not None and candidate not in seen:
                    seen.add(candidate)
                    parent_state = entry_state.get(candidate)
                    if parent_state is None:
                        return None
                    if parent_state["affects_state"]:
                        return candidate
                    raw_parent = parent_state["parent_id"]
                    candidate = int(raw_parent) if raw_parent is not None else None
                return None

            for state in entry_state.values():
                if not state["affects_state"]:
                    continue
                desired_parent = normalized_stateful_parent(state["parent_id"])
                if desired_parent == state["parent_id"]:
                    continue
                cur.execute(
                    "UPDATE HistoryEntries SET parent_id=? WHERE id=?",
                    (desired_parent, int(state["id"])),
                )
                if changes is not None:
                    changes.append(
                        f"Re-linked history entry #{state['id']} to stateful parent {desired_parent}."
                    )
                state["parent_id"] = desired_parent
                changed = True

            stateful_ids = [
                int(state["id"])
                for state in entry_state.values()
                if state["affects_state"] and state["reversible"]
            ]
            original_current_id = self.get_current_entry_id()
            current_id = original_current_id
            seen_ids: set[int] = set()
            while current_id is not None and current_id not in seen_ids:
                seen_ids.add(int(current_id))
                current_state = entry_state.get(int(current_id))
                if current_state is None:
                    current_id = None
                    break
                if current_state["affects_state"] and current_state["reversible"]:
                    break
                raw_parent = current_state["parent_id"]
                current_id = int(raw_parent) if raw_parent is not None else None
            if current_id is None and original_current_id is not None:
                current_id = self._select_fallback_current_entry_id()
            if not stateful_ids:
                fallback_head_id = self._select_fallback_current_entry_id()
                if self.get_current_entry_id() != fallback_head_id:
                    self._set_current_entry_id_in_cursor(fallback_head_id, cursor=cur)
                    changed = True
                    if changes is not None:
                        if fallback_head_id is None:
                            changes.append(
                                "Cleared HistoryHead because no reversible stateful entries remain."
                            )
                        else:
                            changes.append(
                                f"Reset HistoryHead pointer to surviving history entry {fallback_head_id}."
                            )
                return

            path_nodes: list[int] = []
            path_seen: set[int] = set()
            cursor_id = current_id
            while cursor_id is not None and cursor_id not in path_seen:
                state = entry_state.get(int(cursor_id))
                if state is None or not state["affects_state"] or not state["reversible"]:
                    break
                path_seen.add(int(cursor_id))
                path_nodes.append(int(cursor_id))
                raw_parent = state["parent_id"]
                cursor_id = int(raw_parent) if raw_parent is not None else None
            path_nodes.reverse()
            path_child_by_parent: dict[int | None, int] = {}
            parent_cursor: int | None = None
            for node_id in path_nodes:
                path_child_by_parent[parent_cursor] = node_id
                parent_cursor = node_id

            children_by_parent: dict[int | None, list[int]] = {}
            for state in entry_state.values():
                if not state["affects_state"] or not state["reversible"]:
                    continue
                parent_key = int(state["parent_id"]) if state["parent_id"] is not None else None
                children_by_parent.setdefault(parent_key, []).append(int(state["id"]))
            for child_ids in children_by_parent.values():
                child_ids.sort()

            desired_status: dict[int, str] = {}

            def mark_subtree(entry_ids: list[int], status_value: str) -> None:
                stack = list(entry_ids)
                while stack:
                    entry_id = stack.pop()
                    if entry_id in desired_status:
                        continue
                    desired_status[entry_id] = status_value
                    stack.extend(children_by_parent.get(entry_id, []))

            def assign_undone_chain(parent_entry_id: int) -> None:
                child_ids = children_by_parent.get(parent_entry_id, [])
                if not child_ids:
                    return
                undone_id = child_ids[-1]
                desired_status[undone_id] = self.STATUS_UNDONE
                for sibling_id in child_ids[:-1]:
                    mark_subtree([sibling_id], self.STATUS_SUPERSEDED)
                assign_undone_chain(undone_id)

            def assign_tree(parent_id: int | None) -> None:
                child_ids = children_by_parent.get(parent_id, [])
                if not child_ids:
                    return
                applied_child = path_child_by_parent.get(parent_id)
                if applied_child is not None:
                    desired_status[applied_child] = self.STATUS_APPLIED
                    for sibling_id in child_ids:
                        if sibling_id != applied_child:
                            mark_subtree([sibling_id], self.STATUS_SUPERSEDED)
                    assign_tree(applied_child)
                    return
                undone_id = child_ids[-1]
                desired_status[undone_id] = self.STATUS_UNDONE
                for sibling_id in child_ids[:-1]:
                    mark_subtree([sibling_id], self.STATUS_SUPERSEDED)
                assign_undone_chain(undone_id)

            assign_tree(None)
            for entry_id in stateful_ids:
                desired_status.setdefault(int(entry_id), self.STATUS_SUPERSEDED)

            for entry_id, desired in desired_status.items():
                state = entry_state[int(entry_id)]
                if str(state["status"]) == desired:
                    continue
                self._set_entry_status_in_cursor(int(entry_id), desired, cursor=cur)
                state["status"] = desired
                changed = True

            if self.get_current_entry_id() != current_id:
                self._set_current_entry_id_in_cursor(current_id, cursor=cur)
                changed = True
                if changes is not None:
                    changes.append(f"Reset HistoryHead pointer to stateful entry {current_id}.")

            if changed and changes is not None and not changes:
                changes.append("Normalized history undo/redo metadata.")

    def _history_statuses_need_bootstrap(self) -> bool:
        row = self.conn.execute(
            """
            SELECT COUNT(*)
            FROM HistoryEntries
            WHERE reversible=1 AND status IN (?, ?)
            """,
            (self.STATUS_UNDONE, self.STATUS_SUPERSEDED),
        ).fetchone()
        return int(row[0] or 0) == 0

    def _bootstrap_history_statuses(self) -> None:
        current_id = self.get_current_entry_id()
        applied_ids: set[int] = set()
        cursor = self.conn.cursor()
        while current_id is not None:
            applied_ids.add(int(current_id))
            row = cursor.execute(
                "SELECT parent_id FROM HistoryEntries WHERE id=?",
                (int(current_id),),
            ).fetchone()
            current_id = int(row[0]) if row and row[0] is not None else None

        with self.conn:
            self.conn.execute(
                "UPDATE HistoryEntries SET status=? WHERE reversible=0",
                (self.STATUS_APPLIED,),
            )
            self.conn.execute(
                "UPDATE HistoryEntries SET status=? WHERE reversible=1",
                (self.STATUS_UNDONE,),
            )
            for entry_id in applied_ids:
                self.conn.execute(
                    "UPDATE HistoryEntries SET status=? WHERE id=?",
                    (self.STATUS_APPLIED, int(entry_id)),
                )

    def _select_fallback_current_entry_id(self) -> int | None:
        row = self.conn.execute(
            """
            SELECT e.id
            FROM HistoryEntries e
            LEFT JOIN HistoryEntries child
                ON child.parent_id = e.id AND child.status = ?
            WHERE e.status = ?
              AND child.id IS NULL
            ORDER BY e.id DESC
            LIMIT 1
            """,
            (self.STATUS_APPLIED, self.STATUS_APPLIED),
        ).fetchone()
        return int(row[0]) if row and row[0] is not None else None

    def _all_snapshots(self) -> list[SnapshotRecord]:
        rows = self.conn.execute(
            """
            SELECT id, created_at, kind, label, db_snapshot_path, settings_json, manifest_json
            FROM HistorySnapshots
            ORDER BY id
            """
        ).fetchall()
        return [self._snapshot_from_row(row) for row in rows]

    def _all_backups(self) -> list[BackupRecord]:
        rows = self.conn.execute(
            """
            SELECT id, created_at, kind, label, backup_path, source_db_path, metadata_json
            FROM HistoryBackups
            ORDER BY id
            """
        ).fetchall()
        return [self._backup_from_row(row) for row in rows]

    def _all_history_entries(self, *, action_type: str | None = None) -> list[HistoryEntry]:
        current_id = self.get_current_entry_id()
        if action_type is None:
            rows = self.conn.execute(
                f"""
                SELECT
                    {_ENTRY_SELECT_COLUMNS}
                FROM HistoryEntries
                ORDER BY id
                """
            ).fetchall()
        else:
            rows = self.conn.execute(
                f"""
                SELECT
                    {_ENTRY_SELECT_COLUMNS}
                FROM HistoryEntries
                WHERE action_type=?
                ORDER BY id
                """,
                (str(action_type),),
            ).fetchall()
        return [self._entry_from_row(row, current_id=current_id) for row in rows]

    def _all_backup_file_entries(self) -> list[HistoryEntry]:
        return self._all_history_entries(action_type="file.db_backup")

    def _all_snapshot_archive_entries(self) -> list[tuple[HistoryEntry, dict]]:
        entries = []
        for entry in self._all_history_entries():
            archived_snapshot = {}
            if entry.action_type == "snapshot.create":
                archived_snapshot = (entry.redo_payload or {}).get("archived_snapshot") or {}
            elif entry.action_type == "snapshot.delete":
                archived_snapshot = (entry.inverse_payload or {}).get("archived_snapshot") or {}
            if isinstance(archived_snapshot, dict) and archived_snapshot:
                entries.append((entry, archived_snapshot))
        return entries

    def _ensure_registry_sidecars(self) -> None:
        for snapshot in self._all_snapshots():
            snapshot_path = Path(snapshot.db_snapshot_path)
            if snapshot_path.exists():
                self._write_snapshot_sidecar(snapshot)
        for backup in self._all_backups():
            backup_path = Path(backup.backup_path)
            if backup_path.exists():
                self._write_backup_sidecar(backup)

    def _backup_entry_target_path(self, entry: HistoryEntry) -> Path:
        payload = entry.payload or {}
        return Path(str(payload.get("path") or entry.entity_id or ""))

    def _find_backup_entry_for_path(self, backup_path: str | Path) -> HistoryEntry | None:
        normalized = str(Path(backup_path))
        for entry in self._all_backup_file_entries():
            if str(self._backup_entry_target_path(entry)) == normalized:
                return entry
        return None

    def _file_state_missing_paths(self, state: dict) -> list[Path]:
        missing_paths: list[Path] = []
        for file_info in state.get("files", []):
            artifact_path = Path(str(file_info.get("artifact_path") or ""))
            if artifact_path and not artifact_path.exists():
                missing_paths.append(artifact_path)
        return missing_paths

    def _state_has_all_artifacts(self, state: dict) -> bool:
        return not self._file_state_missing_paths(state)

    def _archived_snapshot_missing_paths(self, archived_snapshot: dict) -> list[Path]:
        missing_paths: list[Path] = []
        snapshot_path = Path(str(archived_snapshot.get("db_snapshot_path") or ""))
        if not snapshot_path.exists():
            missing_paths.append(snapshot_path)
        for state in (
            (archived_snapshot.get("manifest") or {}).get("managed_directories", {}).values()
        ):
            if not state.get("exists"):
                continue
            asset_path = Path(str(state.get("snapshot_path") or ""))
            if not asset_path.exists():
                missing_paths.append(asset_path)
        return missing_paths

    def _restore_backup_from_history_entry(self, entry: HistoryEntry) -> bool:
        redo_state = (entry.redo_payload or {}).get("state", {})
        if not redo_state or not self._state_has_all_artifacts(redo_state):
            return False
        self.restore_file_state(self._backup_entry_target_path(entry), redo_state)
        return True

    def _register_backup_from_history_entry_if_needed(self, entry: HistoryEntry) -> str | None:
        backup_path = self._backup_entry_target_path(entry)
        if not backup_path.exists():
            return None
        existing = next(
            (
                record
                for record in self._all_backups()
                if str(Path(record.backup_path)) == str(backup_path)
            ),
            None,
        )
        if existing is not None:
            return None
        payload = entry.payload or {}
        self.register_backup(
            backup_path,
            kind="manual",
            label=f"Backup: {backup_path.name}",
            source_db_path=str(self.db_path),
            metadata={"method": payload.get("method")},
        )
        return f"Registered backup history entry #{entry.entry_id} as backup metadata for {backup_path.name}."

    def _referenced_snapshot_ids(self) -> set[int]:
        rows = self.conn.execute(
            """
            SELECT snapshot_before_id, snapshot_after_id
            FROM HistoryEntries
            WHERE snapshot_before_id IS NOT NULL OR snapshot_after_id IS NOT NULL
            """
        ).fetchall()
        snapshot_ids: set[int] = set()
        for before_id, after_id in rows:
            if before_id is not None:
                snapshot_ids.add(int(before_id))
            if after_id is not None:
                snapshot_ids.add(int(after_id))
        return snapshot_ids

    def _dangling_snapshot_reference_issues(self) -> list[HistoryIssue]:
        snapshot_ids = {snapshot.snapshot_id for snapshot in self._all_snapshots()}
        issues: list[HistoryIssue] = []
        rows = self.conn.execute(
            """
            SELECT id, snapshot_before_id, snapshot_after_id
            FROM HistoryEntries
            WHERE snapshot_before_id IS NOT NULL OR snapshot_after_id IS NOT NULL
            """
        ).fetchall()
        for entry_id, before_id, after_id in rows:
            for snapshot_id in (before_id, after_id):
                if snapshot_id is None or int(snapshot_id) in snapshot_ids:
                    continue
                issues.append(
                    HistoryIssue(
                        issue_type="dangling_snapshot_reference",
                        severity="warning",
                        message=(
                            f"History entry #{entry_id} references missing snapshot #{snapshot_id}."
                        ),
                        entry_id=int(entry_id),
                        snapshot_id=int(snapshot_id),
                    )
                )
        return issues

    def _snapshot_missing_paths(self, snapshot: SnapshotRecord) -> list[Path]:
        missing_paths: list[Path] = []
        snapshot_path = Path(snapshot.db_snapshot_path)
        if not snapshot_path.exists():
            missing_paths.append(snapshot_path)
        for state in (snapshot.manifest or {}).get("managed_directories", {}).values():
            if not state.get("exists"):
                continue
            snapshot_asset_path = Path(state.get("snapshot_path") or "")
            if not snapshot_asset_path.exists():
                missing_paths.append(snapshot_asset_path)
        return missing_paths

    def _validate_snapshot_restore_ready(self, snapshot: SnapshotRecord) -> None:
        missing_paths = self._snapshot_missing_paths(snapshot)
        if not missing_paths:
            return
        missing = "\n".join(str(path) for path in missing_paths[:10])
        raise HistoryRecoveryError(
            "Snapshot restore could not proceed because required artifacts are missing.\n"
            f"Snapshot #{snapshot.snapshot_id} '{snapshot.label}' is missing:\n{missing}\n\n"
            "Run Diagnostics and use the history repair action to reconcile stale references."
        )

    def _orphan_snapshot_files(self, registered_paths: set[str]) -> list[Path]:
        snapshot_dir = self.history_root / "snapshots" / self.db_path.stem
        if not snapshot_dir.exists():
            return []
        return sorted(
            [path for path in snapshot_dir.glob("*.db") if str(path) not in registered_paths]
        )

    def _orphan_backup_files(self, registered_paths: set[str]) -> list[Path]:
        if self.backups_root is None or not self.backups_root.exists():
            return []
        return sorted(
            [path for path in self.backups_root.rglob("*.db") if str(path) not in registered_paths]
        )

    def _snapshot_sidecar_path(self, snapshot_path: Path) -> Path:
        return snapshot_path.with_suffix(snapshot_path.suffix + self.SNAPSHOT_SIDECAR_SUFFIX)

    def _backup_sidecar_path(self, backup_path: Path) -> Path:
        return backup_path.with_suffix(backup_path.suffix + self.BACKUP_SIDECAR_SUFFIX)

    def _ensure_registry_sidecars(self) -> None:
        for snapshot in self._all_snapshots():
            sidecar_path = self._snapshot_sidecar_path(Path(snapshot.db_snapshot_path))
            if not sidecar_path.exists():
                self._write_snapshot_sidecar(snapshot)
        for backup in self._all_backups():
            sidecar_path = self._backup_sidecar_path(Path(backup.backup_path))
            if not sidecar_path.exists():
                self._write_backup_sidecar(backup)

    def _write_snapshot_sidecar(self, snapshot: SnapshotRecord) -> None:
        payload = {
            "snapshot_id": snapshot.snapshot_id,
            "created_at": snapshot.created_at,
            "kind": snapshot.kind,
            "label": snapshot.label,
            "settings_state": snapshot.settings_state,
            "manifest": snapshot.manifest,
        }
        try:
            self._write_json_sidecar(
                self._snapshot_sidecar_path(Path(snapshot.db_snapshot_path)), payload
            )
        except Exception:
            pass

    def _write_backup_sidecar(self, backup: BackupRecord) -> None:
        payload = {
            "backup_id": backup.backup_id,
            "created_at": backup.created_at,
            "kind": backup.kind,
            "label": backup.label,
            "source_db_path": backup.source_db_path,
            "metadata": backup.metadata,
        }
        try:
            self._write_json_sidecar(self._backup_sidecar_path(Path(backup.backup_path)), payload)
        except Exception:
            pass

    @staticmethod
    def _write_json_sidecar(path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    @staticmethod
    def _read_json_sidecar(path: Path) -> dict:
        if not path.exists():
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return raw if isinstance(raw, dict) else {}

    def _load_snapshot_metadata(self, snapshot_path: Path) -> dict:
        sidecar = self._read_json_sidecar(self._snapshot_sidecar_path(snapshot_path))
        return {
            "snapshot_id": sidecar.get("snapshot_id"),
            "kind": sidecar.get("kind") or self._infer_snapshot_kind(snapshot_path),
            "label": sidecar.get("label") or snapshot_path.stem,
            "settings_state": sidecar.get("settings_state") or {},
            "manifest": sidecar.get("manifest") or self._infer_snapshot_manifest(snapshot_path),
        }

    def _load_backup_metadata(self, backup_path: Path) -> dict:
        sidecar = self._read_json_sidecar(self._backup_sidecar_path(backup_path))
        return {
            "backup_id": sidecar.get("backup_id"),
            "kind": sidecar.get("kind") or self._infer_backup_kind(backup_path),
            "label": sidecar.get("label") or backup_path.name,
            "source_db_path": sidecar.get("source_db_path"),
            "metadata": sidecar.get("metadata") or {},
        }

    def _restore_snapshot_from_archive_if_possible(self, snapshot: SnapshotRecord) -> bool:
        archived_snapshot = self._find_archived_snapshot_payload(snapshot.snapshot_id)
        if not archived_snapshot:
            return False
        if self._archived_snapshot_missing_paths(archived_snapshot):
            return False
        archived_path = Path(str(archived_snapshot.get("db_snapshot_path") or ""))
        manifest = archived_snapshot.get("manifest") or self._infer_snapshot_manifest(archived_path)
        settings_state = archived_snapshot.get("settings_state") or {}
        kind = str(archived_snapshot.get("kind") or snapshot.kind or "recovered_archive")
        label = str(archived_snapshot.get("label") or snapshot.label or archived_path.stem)
        with self.conn:
            self.conn.execute(
                """
                UPDATE HistorySnapshots
                SET kind=?, label=?, db_snapshot_path=?, settings_json=?, manifest_json=?
                WHERE id=?
                """,
                (
                    kind,
                    label,
                    str(archived_path),
                    json.dumps(settings_state),
                    json.dumps(manifest),
                    int(snapshot.snapshot_id),
                ),
            )
        refreshed = self.fetch_snapshot(snapshot.snapshot_id)
        if refreshed is not None:
            self._write_snapshot_sidecar(refreshed)
        return True

    def _find_archived_snapshot_payload(self, snapshot_id: int) -> dict:
        rows = self.conn.execute(
            """
            SELECT payload_json, inverse_json, redo_json
            FROM HistoryEntries
            WHERE action_type IN ('snapshot.create', 'snapshot.delete')
            ORDER BY id DESC
            """
        ).fetchall()
        for payload_json, inverse_json, redo_json in rows:
            payload = self._loads(payload_json)
            inverse_payload = self._loads(inverse_json)
            redo_payload = self._loads(redo_json)
            payload_snapshot_id = self._int_or_none(payload.get("snapshot_id"))
            if payload_snapshot_id != int(snapshot_id):
                continue
            archived_snapshot = (
                payload.get("archived_snapshot")
                or inverse_payload.get("archived_snapshot")
                or redo_payload.get("archived_snapshot")
            )
            if isinstance(archived_snapshot, dict):
                return archived_snapshot
        return {}

    def _quarantine_snapshot_references(self, snapshot_id: int) -> list[int]:
        rows = self.conn.execute(
            """
            SELECT id, parent_id
            FROM HistoryEntries
            WHERE snapshot_before_id=? OR snapshot_after_id=?
            ORDER BY id
            """,
            (int(snapshot_id), int(snapshot_id)),
        ).fetchall()
        entry_ids = [int(row[0]) for row in rows]
        if not entry_ids:
            return []
        current_id = self.get_current_entry_id()
        fallback_head_id = None
        with self.conn:
            for entry_id, parent_id in rows:
                self.conn.execute(
                    """
                    UPDATE HistoryEntries
                    SET reversible=0,
                        status=?,
                        snapshot_before_id=NULL,
                        snapshot_after_id=NULL
                    WHERE id=?
                    """,
                    (self.STATUS_ARTIFACT_MISSING, int(entry_id)),
                )
                if current_id is not None and int(entry_id) == int(current_id):
                    fallback_head_id = int(parent_id) if parent_id is not None else None
            if current_id is not None and current_id in entry_ids:
                self._set_current_entry_id_in_cursor(fallback_head_id, cursor=self.conn.cursor())
        return entry_ids

    def _remove_snapshot_record(self, snapshot_id: int) -> None:
        snapshot = self.fetch_snapshot(snapshot_id)
        if snapshot is not None:
            snapshot_path = Path(snapshot.db_snapshot_path)
            self._remove_path(snapshot_path)
            self._remove_path(self._snapshot_sidecar_path(snapshot_path))
            for state in (snapshot.manifest or {}).get("managed_directories", {}).values():
                asset_path = state.get("snapshot_path")
                if asset_path:
                    self._remove_path(Path(asset_path))
        with self.conn:
            self.conn.execute("DELETE FROM HistorySnapshots WHERE id=?", (int(snapshot_id),))

    def _infer_snapshot_manifest(self, snapshot_path: Path) -> dict:
        assets_root = snapshot_path.with_suffix(".assets")
        if not assets_root.exists():
            return {}
        managed_directories = {}
        for dir_name in self.MANAGED_DIRECTORIES:
            asset_dir = assets_root / dir_name
            managed_directories[dir_name] = {
                "exists": asset_dir.exists(),
                "snapshot_path": str(asset_dir) if asset_dir.exists() else None,
            }
        return {"managed_directories": managed_directories}

    @staticmethod
    def _infer_snapshot_kind(snapshot_path: Path) -> str:
        stem = snapshot_path.stem
        return stem.split("_")[-1] if "_" in stem else "recovered_orphan"

    @staticmethod
    def _infer_backup_kind(backup_path: Path) -> str:
        return "pre_restore" if "pre_restore" in backup_path.name else "manual"

    def _restore_external_state(
        self, *, rollback_manifest: dict, settings_state: dict
    ) -> str | None:
        restore_errors: list[str] = []
        try:
            self._restore_managed_state(rollback_manifest)
        except Exception as exc:
            restore_errors.append(f"managed files: {exc}")
        try:
            self._apply_settings_state(settings_state)
        except Exception as exc:
            restore_errors.append(f"settings: {exc}")
        if restore_errors:
            return "; ".join(restore_errors)
        return None

    @staticmethod
    def _int_or_none(value: object) -> int | None:
        try:
            return int(value) if value is not None else None
        except Exception:
            return None

    def _capture_settings_state(self) -> dict:
        return {
            key: self._serialize_setting_value(self.settings.value(key))
            for key in self.settings.allKeys()
        }

    def _capture_setting_state(self, key: str) -> dict:
        exists = self.settings.contains(key)
        return {
            "setting_key": key,
            "exists": bool(exists),
            "serialized": (
                self._serialize_setting_value(self.settings.value(key)) if exists else None
            ),
        }

    def _capture_managed_state(self, assets_dir: Path) -> dict:
        if self.managed_root is None:
            return {}

        manifest = {"managed_directories": {}}
        for dir_name in self.MANAGED_DIRECTORIES:
            source_dir = self.managed_root / dir_name
            if source_dir.exists():
                assets_dir.mkdir(parents=True, exist_ok=True)
                snapshot_dir = assets_dir / dir_name
                if snapshot_dir.exists():
                    shutil.rmtree(snapshot_dir)
                shutil.copytree(source_dir, snapshot_dir)
                manifest["managed_directories"][dir_name] = {
                    "exists": True,
                    "snapshot_path": str(snapshot_dir),
                }
            else:
                manifest["managed_directories"][dir_name] = {
                    "exists": False,
                    "snapshot_path": None,
                }
        return manifest

    def _clone_managed_manifest(self, manifest: dict, assets_dir: Path) -> dict:
        cloned = json.loads(json.dumps(manifest or {}))
        managed_directories = cloned.get("managed_directories", {})
        for dir_name, state in managed_directories.items():
            source_path = state.get("snapshot_path")
            if not state.get("exists") or not source_path:
                state["snapshot_path"] = None
                continue
            src_dir = Path(source_path)
            if not src_dir.exists():
                raise FileNotFoundError(src_dir)
            assets_dir.mkdir(parents=True, exist_ok=True)
            dest_dir = assets_dir / dir_name
            if dest_dir.exists():
                shutil.rmtree(dest_dir)
            shutil.copytree(src_dir, dest_dir)
            state["snapshot_path"] = str(dest_dir)
        return cloned

    def _restore_managed_state(self, manifest: dict) -> None:
        if self.managed_root is None:
            return

        managed_directories = (manifest or {}).get("managed_directories", {})
        if not managed_directories:
            return

        self.managed_root.mkdir(parents=True, exist_ok=True)
        for dir_name, state in managed_directories.items():
            target_dir = self.managed_root / dir_name
            self._remove_path(target_dir)
            if not state.get("exists"):
                continue
            snapshot_dir = Path(state.get("snapshot_path") or "")
            if not snapshot_dir.exists():
                raise FileNotFoundError(snapshot_dir)
            shutil.copytree(snapshot_dir, target_dir)

    def _archive_snapshot_record(self, snapshot: SnapshotRecord, *, prefix: str) -> dict:
        archive_dir = self.history_root / "snapshot_archives" / self.db_path.stem
        archive_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        archive_path = archive_dir / f"{timestamp}_{prefix}.db"
        shutil.copy2(snapshot.db_snapshot_path, archive_path)
        manifest = self._clone_managed_manifest(
            snapshot.manifest, archive_path.with_suffix(".assets")
        )
        return {
            "kind": snapshot.kind,
            "label": snapshot.label,
            "db_snapshot_path": str(archive_path),
            "settings_state": snapshot.settings_state,
            "manifest": manifest,
        }

    def _restore_snapshot_from_archive(self, archived_snapshot: dict) -> SnapshotRecord:
        snapshot = SnapshotRecord(
            snapshot_id=0,
            created_at="",
            kind=archived_snapshot.get("kind", "manual"),
            label=archived_snapshot.get("label", "Restored Snapshot"),
            db_snapshot_path=archived_snapshot["db_snapshot_path"],
            settings_state=archived_snapshot.get("settings_state", {}),
            manifest=archived_snapshot.get("manifest", {}),
        )
        return self.register_snapshot(snapshot, kind=snapshot.kind, label=snapshot.label)

    def _apply_settings_state(self, state: dict) -> None:
        self.settings.clear()
        for key, serialized in state.items():
            self.settings.setValue(key, self._deserialize_setting_value(serialized))
        self.settings.sync()

    def _apply_setting_state_entry(self, entry: dict) -> None:
        key = entry["setting_key"]
        if not entry.get("exists"):
            self.settings.remove(key)
            return
        self.settings.setValue(key, self._deserialize_setting_value(entry["serialized"]))

    def _serialize_setting_value(self, value) -> dict:
        if isinstance(value, QByteArray):
            return {"kind": "qbytearray", "value": bytes(value.toBase64()).decode("ascii")}
        if isinstance(value, QPoint):
            return {"kind": "qpoint", "x": int(value.x()), "y": int(value.y())}
        if isinstance(value, bytes):
            return {"kind": "bytes", "value": base64.b64encode(value).decode("ascii")}
        if isinstance(value, list):
            return {
                "kind": "list",
                "value": [self._serialize_setting_value(item) for item in value],
            }
        if isinstance(value, tuple):
            return {
                "kind": "tuple",
                "value": [self._serialize_setting_value(item) for item in value],
            }
        if value is None or isinstance(value, (bool, int, float, str)):
            return {"kind": "json", "value": value}
        return {"kind": "string", "value": str(value)}

    def _deserialize_setting_value(self, serialized: dict):
        kind = serialized.get("kind")
        if kind == "qbytearray":
            return QByteArray.fromBase64(serialized.get("value", "").encode("ascii"))
        if kind == "qpoint":
            return QPoint(int(serialized.get("x", 0)), int(serialized.get("y", 0)))
        if kind == "bytes":
            return base64.b64decode(serialized.get("value", "").encode("ascii"))
        if kind == "list":
            return [self._deserialize_setting_value(item) for item in serialized.get("value", [])]
        if kind == "tuple":
            return tuple(
                self._deserialize_setting_value(item) for item in serialized.get("value", [])
            )
        return serialized.get("value")

    @staticmethod
    def _normalize_json_value(value):
        if isinstance(value, dict):
            return {key: HistoryManager._normalize_json_value(val) for key, val in value.items()}
        if isinstance(value, list):
            return [HistoryManager._normalize_json_value(item) for item in value]
        if value is None or isinstance(value, (bool, int, float, str)):
            return value
        return str(value)

    def _can_coalesce_setting_bundle(
        self, entry: HistoryEntry | None, entity_id: str, visible_in_history: bool
    ) -> bool:
        if entry is None:
            return False
        if not entry.reversible or entry.action_type != "settings.bundle":
            return False
        if (entry.entity_id or "") != entity_id:
            return False
        if bool(entry.visible_in_history) != bool(visible_in_history):
            return False
        if not entry.created_at:
            return False
        try:
            created_at = datetime.fromisoformat(entry.created_at)
        except ValueError:
            return False
        created_at_utc = created_at.replace(tzinfo=timezone.utc)
        return (
            datetime.now(timezone.utc) - created_at_utc
        ).total_seconds() <= self.SETTINGS_COALESCE_WINDOW_SECONDS

    def _update_entry_payloads(
        self,
        entry_id: int,
        *,
        label: str | None = None,
        payload: dict | None = None,
        inverse_payload: dict | None = None,
        redo_payload: dict | None = None,
        created_at: str | None = None,
    ) -> None:
        current = self.fetch_entry(entry_id)
        if current is None:
            raise ValueError(f"History entry {entry_id} not found")
        with self.conn:
            self.conn.execute(
                """
                UPDATE HistoryEntries
                SET label=?, created_at=?, payload_json=?, inverse_json=?, redo_json=?
                WHERE id=?
                """,
                (
                    label if label is not None else current.label,
                    created_at if created_at is not None else current.created_at,
                    json.dumps(payload if payload is not None else current.payload),
                    json.dumps(
                        inverse_payload if inverse_payload is not None else current.inverse_payload
                    ),
                    json.dumps(redo_payload if redo_payload is not None else current.redo_payload),
                    int(entry_id),
                ),
            )

    @staticmethod
    def _remove_path(path: Path) -> None:
        if not path.exists() and not path.is_symlink():
            return
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()

    @staticmethod
    def _loads(raw: str | None) -> dict:
        if not raw:
            return {}
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _now_stamp() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _history_timestamp_now() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

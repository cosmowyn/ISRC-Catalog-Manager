"""Persistent linear-plus-branch-aware history manager."""

from __future__ import annotations

import base64
import json
import sqlite3
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import QByteArray, QSettings

from isrc_manager.services import (
    ProfileKVService,
    SettingsMutationService,
    SettingsReadService,
    TrackService,
    TrackSnapshot,
)

from .models import HistoryEntry, SnapshotRecord


class HistoryManager:
    """Stores history entries and applies undo/redo for supported actions."""

    DOMAIN_TABLES_DELETE_ORDER = [
        "Licenses",
        "CustomFieldValues",
        "TrackArtists",
        "Tracks",
        "Licensees",
        "CustomFieldDefs",
        "Albums",
        "Artists",
        "ISRC_Prefix",
        "SENA",
        "BTW",
        "BUMA_STEMRA",
        "app_kv",
    ]
    DOMAIN_TABLES_COPY_ORDER = [
        "Artists",
        "Albums",
        "Licensees",
        "CustomFieldDefs",
        "Tracks",
        "TrackArtists",
        "CustomFieldValues",
        "Licenses",
        "ISRC_Prefix",
        "SENA",
        "BTW",
        "BUMA_STEMRA",
        "app_kv",
    ]

    def __init__(
        self,
        conn: sqlite3.Connection,
        settings: QSettings,
        db_path: str | Path,
        history_root: str | Path,
    ):
        self.conn = conn
        self.settings = settings
        self.db_path = Path(db_path)
        self.history_root = Path(history_root)
        self.track_service = TrackService(conn)
        self.settings_mutations = SettingsMutationService(conn, settings)
        self.settings_reads = SettingsReadService(conn)
        self.profile_kv = ProfileKVService(conn)

    # ------------------------------------------------------------------
    # Public queries
    # ------------------------------------------------------------------
    def list_entries(self, limit: int = 250) -> list[HistoryEntry]:
        current_id = self.get_current_entry_id()
        rows = self.conn.execute(
            """
            SELECT
                id, parent_id, created_at, label, action_type, entity_type, entity_id,
                reversible, strategy, payload_json, inverse_json, redo_json,
                snapshot_before_id, snapshot_after_id, status
            FROM HistoryEntries
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

    def get_current_entry_id(self) -> int | None:
        row = self.conn.execute("SELECT current_entry_id FROM HistoryHead WHERE id=1").fetchone()
        return int(row[0]) if row and row[0] is not None else None

    def get_current_entry(self) -> HistoryEntry | None:
        current_id = self.get_current_entry_id()
        if current_id is None:
            return None
        return self.fetch_entry(current_id)

    def fetch_entry(self, entry_id: int) -> HistoryEntry | None:
        row = self.conn.execute(
            """
            SELECT
                id, parent_id, created_at, label, action_type, entity_type, entity_id,
                reversible, strategy, payload_json, inverse_json, redo_json,
                snapshot_before_id, snapshot_after_id, status
            FROM HistoryEntries
            WHERE id=?
            """,
            (int(entry_id),),
        ).fetchone()
        if not row:
            return None
        return self._entry_from_row(row, current_id=self.get_current_entry_id())

    def can_undo(self) -> bool:
        entry = self.get_current_entry()
        return bool(entry and entry.reversible)

    def can_redo(self) -> bool:
        return self.get_default_redo_entry() is not None

    def describe_undo(self) -> str | None:
        entry = self.get_current_entry()
        if entry and entry.reversible:
            return entry.label
        return None

    def describe_redo(self) -> str | None:
        entry = self.get_default_redo_entry()
        if entry is not None:
            return entry.label
        return None

    # ------------------------------------------------------------------
    # Recording actions
    # ------------------------------------------------------------------
    def create_manual_snapshot(self, label: str | None = None) -> SnapshotRecord:
        snapshot = self.capture_snapshot(kind="manual", label=label or f"Manual Snapshot {self._now_stamp()}")
        self.record_event(
            label=f"Create Snapshot: {snapshot.label}",
            action_type="snapshot.create",
            entity_type="Snapshot",
            entity_id=str(snapshot.snapshot_id),
            payload={"snapshot_id": snapshot.snapshot_id},
        )
        return snapshot

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
        )
        return self.fetch_entry(entry_id)

    def restore_snapshot_as_action(self, snapshot_id: int, *, label: str | None = None) -> HistoryEntry:
        before = self.capture_snapshot(kind="auto_pre_restore", label="Before Snapshot Restore")
        target = self.fetch_snapshot(snapshot_id)
        if target is None:
            raise ValueError(f"Snapshot {snapshot_id} not found")
        self._restore_snapshot_state(target)
        entry = self.record_snapshot_action(
            label=label or f"Restore Snapshot: {target.label}",
            action_type="snapshot.restore",
            entity_type="Snapshot",
            entity_id=str(snapshot_id),
            payload={"snapshot_id": snapshot_id, "label": target.label},
            snapshot_before_id=before.snapshot_id,
            snapshot_after_id=target.snapshot_id,
        )
        return entry

    def record_event(
        self,
        *,
        label: str,
        action_type: str,
        entity_type: str | None = None,
        entity_id: str | None = None,
        payload: dict | None = None,
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
        )

    def record_setting_change(
        self,
        *,
        key: str,
        label: str,
        before_value: Any,
        after_value: Any,
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
            payload={"track_id": before_snapshot.track_id, "track_title": before_snapshot.track_title},
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
        entry = self.get_current_entry()
        if entry is None or not entry.reversible:
            return None
        self._apply_entry_payload(entry, entry.inverse_payload, direction="undo")
        self._set_current_entry_id(entry.parent_id)
        return entry

    def redo(self, entry_id: int | None = None) -> HistoryEntry | None:
        entry = self.fetch_entry(entry_id) if entry_id is not None else self.get_default_redo_entry()
        if entry is None or not entry.reversible:
            return None
        self._apply_entry_payload(entry, entry.redo_payload, direction="redo")
        self._set_current_entry_id(entry.entry_id)
        return entry

    def get_default_redo_entry(self) -> HistoryEntry | None:
        current_id = self.get_current_entry_id()
        if current_id is None:
            row = self.conn.execute(
                """
                SELECT
                    id, parent_id, created_at, label, action_type, entity_type, entity_id,
                    reversible, strategy, payload_json, inverse_json, redo_json,
                    snapshot_before_id, snapshot_after_id, status
                FROM HistoryEntries
                WHERE parent_id IS NULL AND reversible=1
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
        else:
            row = self.conn.execute(
                """
                SELECT
                    id, parent_id, created_at, label, action_type, entity_type, entity_id,
                    reversible, strategy, payload_json, inverse_json, redo_json,
                    snapshot_before_id, snapshot_after_id, status
                FROM HistoryEntries
                WHERE parent_id=? AND reversible=1
                ORDER BY id DESC
                LIMIT 1
                """,
                (int(current_id),),
            ).fetchone()
        if not row:
            return None
        return self._entry_from_row(row, current_id=self.get_current_entry_id())

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
        if snapshot_path.exists():
            snapshot_path.unlink()

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
    ) -> int:
        parent_id = self.get_current_entry_id() if move_head else self.get_current_entry_id()
        with self.conn:
            cur = self.conn.cursor()
            cur.execute(
                """
                INSERT INTO HistoryEntries (
                    parent_id, label, action_type, entity_type, entity_id,
                    reversible, strategy, payload_json, inverse_json, redo_json,
                    snapshot_before_id, snapshot_after_id, status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'applied')
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
                ),
            )
            entry_id = int(cur.lastrowid)
            if move_head:
                cur.execute(
                    """
                    INSERT INTO HistoryHead (id, current_entry_id)
                    VALUES (1, ?)
                    ON CONFLICT(id) DO UPDATE SET current_entry_id=excluded.current_entry_id
                    """,
                    (entry_id,),
                )
        return entry_id

    def _set_current_entry_id(self, entry_id: int | None) -> None:
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO HistoryHead (id, current_entry_id)
                VALUES (1, ?)
                ON CONFLICT(id) DO UPDATE SET current_entry_id=excluded.current_entry_id
                """,
                (entry_id,),
            )

    def _apply_entry_payload(self, entry: HistoryEntry, payload: dict | None, *, direction: str) -> None:
        if entry.strategy == "snapshot":
            snapshot_id = entry.snapshot_before_id if direction == "undo" else entry.snapshot_after_id
            if snapshot_id is None:
                return
            snapshot = self.fetch_snapshot(snapshot_id)
            if snapshot is None:
                raise ValueError(f"Snapshot {snapshot_id} not found")
            self._restore_snapshot_state(snapshot)
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
        elif action_type.startswith("settings."):
            self._apply_setting_payload(payload)
        else:
            raise ValueError(f"Undo/redo not implemented for {action_type}")

    def _undo_track_create(self, payload: dict) -> None:
        track_id = int(payload["track_id"])
        with self.conn:
            cur = self.conn.cursor()
            cur.execute("DELETE FROM Tracks WHERE id=?", (track_id,))
            self.track_service.delete_unused_artists_by_names(payload.get("cleanup_artist_names", []), cursor=cur)
            self.track_service.delete_unused_albums_by_titles(payload.get("cleanup_album_titles", []), cursor=cur)

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
            self.track_service.delete_unused_artists_by_names(payload.get("cleanup_artist_names", []), cursor=cur)
            self.track_service.delete_unused_albums_by_titles(payload.get("cleanup_album_titles", []), cursor=cur)

    def _apply_setting_payload(self, payload: dict) -> None:
        key = payload["key"]
        value = payload["value"]
        if key == "identity":
            self.settings_mutations.set_identity(
                window_title=value.get("window_title") or "",
                icon_path=value.get("icon_path") or "",
            )
        elif key == "artist_code":
            self.settings_mutations.set_artist_code(str(value))
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
        else:
            raise ValueError(f"Unknown setting history key: {key}")

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
        manifest = {}

        with self.conn:
            cur = self.conn.cursor()
            cur.execute(
                """
                INSERT INTO HistorySnapshots (kind, label, db_snapshot_path, settings_json, manifest_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    kind,
                    label,
                    str(snapshot_path),
                    json.dumps(settings_state),
                    json.dumps(manifest),
                ),
            )
            snapshot_id = int(cur.lastrowid)

        return SnapshotRecord(
            snapshot_id=snapshot_id,
            created_at=datetime.now().isoformat(timespec="seconds"),
            kind=kind,
            label=label,
            db_snapshot_path=str(snapshot_path),
            settings_state=settings_state,
            manifest=manifest,
        )

    def _restore_snapshot_state(self, snapshot: SnapshotRecord) -> None:
        snapshot_path = Path(snapshot.db_snapshot_path)
        if not snapshot_path.exists():
            raise FileNotFoundError(snapshot_path)

        self.conn.commit()
        attach_path = snapshot_path.as_posix()
        self.conn.execute("PRAGMA foreign_keys = OFF")
        self.conn.execute("ATTACH DATABASE ? AS snapshot_restore", (attach_path,))
        try:
            self.conn.execute("BEGIN")
            for table_name in self.DOMAIN_TABLES_DELETE_ORDER:
                self.conn.execute(f"DELETE FROM {table_name}")
            for table_name in self.DOMAIN_TABLES_COPY_ORDER:
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
            user_version_row = self.conn.execute("PRAGMA snapshot_restore.user_version").fetchone()
            if user_version_row and user_version_row[0] is not None:
                self.conn.execute(f"PRAGMA user_version = {int(user_version_row[0])}")
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        finally:
            self.conn.execute("DETACH DATABASE snapshot_restore")
            self.conn.execute("PRAGMA foreign_keys = ON")

        self._apply_settings_state(snapshot.settings_state)

    def _table_exists(self, db_alias: str, table_name: str) -> bool:
        row = self.conn.execute(
            f"SELECT 1 FROM {db_alias}.sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        ).fetchone()
        return bool(row)

    def _shared_columns(self, table_name: str) -> list[str]:
        main_cols = {
            row[1] for row in self.conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        }
        snapshot_cols = {
            row[1] for row in self.conn.execute(f"PRAGMA snapshot_restore.table_info({table_name})").fetchall()
        }
        return [column for column in self._ordered_columns(table_name) if column in main_cols and column in snapshot_cols]

    def _ordered_columns(self, table_name: str) -> list[str]:
        rows = self.conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        return [row[1] for row in rows]

    def _capture_settings_state(self) -> dict:
        return {
            key: self._serialize_setting_value(self.settings.value(key))
            for key in self.settings.allKeys()
        }

    def _apply_settings_state(self, state: dict) -> None:
        self.settings.clear()
        for key, serialized in state.items():
            self.settings.setValue(key, self._deserialize_setting_value(serialized))
        self.settings.sync()

    def _serialize_setting_value(self, value) -> dict:
        if isinstance(value, QByteArray):
            return {"kind": "qbytearray", "value": bytes(value.toBase64()).decode("ascii")}
        if isinstance(value, bytes):
            return {"kind": "bytes", "value": base64.b64encode(value).decode("ascii")}
        if isinstance(value, list):
            return {"kind": "list", "value": [self._serialize_setting_value(item) for item in value]}
        if isinstance(value, tuple):
            return {"kind": "tuple", "value": [self._serialize_setting_value(item) for item in value]}
        if value is None or isinstance(value, (bool, int, float, str)):
            return {"kind": "json", "value": value}
        return {"kind": "string", "value": str(value)}

    def _deserialize_setting_value(self, serialized: dict):
        kind = serialized.get("kind")
        if kind == "qbytearray":
            return QByteArray.fromBase64(serialized.get("value", "").encode("ascii"))
        if kind == "bytes":
            return base64.b64decode(serialized.get("value", "").encode("ascii"))
        if kind == "list":
            return [self._deserialize_setting_value(item) for item in serialized.get("value", [])]
        if kind == "tuple":
            return [self._deserialize_setting_value(item) for item in serialized.get("value", [])]
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

    @staticmethod
    def _loads(raw: str | None) -> dict:
        if not raw:
            return {}
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _now_stamp() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

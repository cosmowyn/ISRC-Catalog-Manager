"""Safe cleanup helpers for history storage artifacts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from isrc_manager.services.settings_reads import HistoryRetentionSettings

from .manager import HistoryManager
from .models import HistoryEntry


class HistoryCleanupBlockedError(RuntimeError):
    """Raised when cleanup is blocked until recovery issues are repaired."""


@dataclass(slots=True)
class HistoryCleanupItem:
    item_key: str
    item_type: str
    label: str
    created_at: str
    path: str
    bytes_on_disk: int
    reason: str
    eligible: bool
    kind: str = ""
    record_id: int | None = None
    entry_id: int | None = None


@dataclass(slots=True)
class HistoryCleanupPreview:
    repair_required: bool
    repair_messages: tuple[str, ...]
    eligible_items: tuple[HistoryCleanupItem, ...]
    protected_items: tuple[HistoryCleanupItem, ...]


@dataclass(slots=True)
class HistoryCleanupResult:
    removed_item_keys: tuple[str, ...]
    removed_paths: tuple[str, ...]
    removed_entry_ids: tuple[int, ...]


@dataclass(slots=True)
class HistoryTrimPreview:
    keep_visible_entries: int
    removable_entry_ids: tuple[int, ...]
    removable_labels: tuple[str, ...]


@dataclass(slots=True)
class HistoryStorageBudgetPreview:
    total_bytes: int
    budget_bytes: int
    over_budget_bytes: int
    auto_cleanup_enabled: bool
    candidate_items: tuple[HistoryCleanupItem, ...]
    protected_over_budget_items: tuple[HistoryCleanupItem, ...]


@dataclass(slots=True)
class HistoryStorageBudgetResult:
    removed_item_keys: tuple[str, ...]
    removed_paths: tuple[str, ...]
    total_bytes: int
    budget_bytes: int
    over_budget_bytes: int
    blocked_by_protected_items: bool


@dataclass(slots=True)
class HistoryStorageProjection:
    additional_bytes: int
    current_total_bytes: int
    projected_total_bytes: int
    budget_bytes: int
    reclaimable_bytes: int
    projected_over_budget_bytes: int
    projected_over_budget_after_cleanup_bytes: int
    auto_cleanup_enabled: bool
    candidate_items: tuple[HistoryCleanupItem, ...]
    blocked_by_protected_items: bool


class HistoryStorageCleanupService:
    """Inspects and removes safe-to-delete history artifacts."""

    SESSION_SNAPSHOT_SUFFIXES = ("", "-wal", "-shm")
    AUTO_SNAPSHOT_KIND_PREFIX = "auto_"
    AUTO_CLEANUP_ITEM_TYPES = {
        "orphan_snapshot_file",
        "orphan_backup_file",
        "snapshot_archive",
        "file_state_bundle",
        "session_snapshot",
    }
    BLOCKING_ISSUE_TYPES = {
        "stale_current_head",
        "missing_snapshot_artifact",
        "missing_snapshot_archive",
        "missing_backup_file",
        "missing_backup_history_artifact",
        "dangling_snapshot_reference",
    }

    def __init__(self, history_manager: HistoryManager):
        self.history_manager = history_manager

    def inspect(self) -> HistoryCleanupPreview:
        issues = self.history_manager.inspect_recovery_state()
        blocking_issues = [
            issue for issue in issues if issue.issue_type in self.BLOCKING_ISSUE_TYPES
        ]
        repair_messages = tuple(issue.message for issue in blocking_issues)
        eligible: list[HistoryCleanupItem] = []
        protected: list[HistoryCleanupItem] = []

        entries = self.history_manager._all_history_entries()
        protected_snapshot_ids = self._protected_snapshot_ids(entries)
        live_archive_paths = self._live_paths_under_root(entries, self._snapshot_archive_root())
        live_file_state_paths = self._live_paths_under_root(entries, self._file_states_root())
        live_session_snapshot_paths = self._session_snapshot_paths()

        for snapshot in self.history_manager._all_snapshots():
            snapshot_path = Path(snapshot.db_snapshot_path)
            is_protected = snapshot.snapshot_id in protected_snapshot_ids
            item = HistoryCleanupItem(
                item_key=f"snapshot_record:{snapshot.snapshot_id}",
                item_type="snapshot_record",
                label=snapshot.label,
                created_at=snapshot.created_at,
                path=str(snapshot_path),
                bytes_on_disk=self._path_size(snapshot_path)
                + self._path_size(self.history_manager._snapshot_sidecar_path(snapshot_path))
                + self._path_size(snapshot_path.with_suffix(".assets")),
                reason=(
                    "This snapshot is still referenced by undo, redo, or retained snapshot history."
                    if is_protected
                    else "This snapshot is no longer referenced by retained history entries."
                ),
                eligible=not is_protected,
                kind=str(snapshot.kind or ""),
                record_id=snapshot.snapshot_id,
            )
            (protected if is_protected else eligible).append(item)

        for backup in self.history_manager._all_backups():
            backup_path = Path(backup.backup_path)
            kind_label = str(backup.kind or "manual").lower()
            eligible.append(
                HistoryCleanupItem(
                    item_key=f"backup_record:{backup.backup_id}",
                    item_type="backup_record",
                    label=backup.label,
                    created_at=backup.created_at,
                    path=str(backup_path),
                    bytes_on_disk=self._path_size(backup_path)
                    + self._path_size(self.history_manager._backup_sidecar_path(backup_path)),
                    reason=(
                        "Safety backup created before a restore."
                        if "pre_restore" in kind_label
                        else "Backup files are not required for undo/redo history."
                    ),
                    eligible=True,
                    kind=str(backup.kind or ""),
                    record_id=backup.backup_id,
                )
            )

        for path in self.history_manager._orphan_snapshot_files(self._registered_snapshot_paths()):
            eligible.append(
                HistoryCleanupItem(
                    item_key=f"orphan_snapshot_file:{path}",
                    item_type="orphan_snapshot_file",
                    label=path.name,
                    created_at=self._path_created_at(path),
                    path=str(path),
                    bytes_on_disk=self._path_size(path)
                    + self._path_size(self.history_manager._snapshot_sidecar_path(path))
                    + self._path_size(path.with_suffix(".assets")),
                    reason="Snapshot file is present on disk but not registered in HistorySnapshots.",
                    eligible=True,
                )
            )

        for path in self.history_manager._orphan_backup_files(self._registered_backup_paths()):
            eligible.append(
                HistoryCleanupItem(
                    item_key=f"orphan_backup_file:{path}",
                    item_type="orphan_backup_file",
                    label=path.name,
                    created_at=self._path_created_at(path),
                    path=str(path),
                    bytes_on_disk=self._path_size(path)
                    + self._path_size(self.history_manager._backup_sidecar_path(path)),
                    reason="Backup file is present on disk but not registered in HistoryBackups.",
                    eligible=True,
                )
            )

        for archive_path in self._archive_bundle_paths():
            is_protected = self._path_is_referenced(archive_path, live_archive_paths)
            item = HistoryCleanupItem(
                item_key=f"snapshot_archive:{archive_path}",
                item_type="snapshot_archive",
                label=archive_path.name,
                created_at=self._path_created_at(archive_path),
                path=str(archive_path),
                bytes_on_disk=self._path_size(archive_path)
                + self._path_size(self.history_manager._snapshot_sidecar_path(archive_path))
                + self._path_size(archive_path.with_suffix(".assets")),
                reason=(
                    "This archived snapshot is still required by snapshot create/delete history."
                    if is_protected
                    else "No retained history entry references this archived snapshot bundle."
                ),
                eligible=not is_protected,
            )
            (protected if is_protected else eligible).append(item)

        for bundle_path in self._file_state_bundle_paths():
            is_protected = self._path_is_referenced(bundle_path, live_file_state_paths)
            item = HistoryCleanupItem(
                item_key=f"file_state_bundle:{bundle_path}",
                item_type="file_state_bundle",
                label=bundle_path.name,
                created_at=self._path_created_at(bundle_path),
                path=str(bundle_path),
                bytes_on_disk=self._path_size(bundle_path),
                reason=(
                    "This stored file-state bundle is still referenced by history payloads."
                    if is_protected
                    else "No retained history entry references this stored file-state bundle."
                ),
                eligible=not is_protected,
            )
            (protected if is_protected else eligible).append(item)

        for snapshot_path in self._session_snapshot_bundle_paths():
            is_protected = self._path_is_referenced(snapshot_path, live_session_snapshot_paths)
            item = HistoryCleanupItem(
                item_key=f"session_snapshot:{snapshot_path}",
                item_type="session_snapshot",
                label=snapshot_path.name,
                created_at=self._path_created_at(snapshot_path),
                path=str(snapshot_path),
                bytes_on_disk=self._session_snapshot_size(snapshot_path),
                reason=(
                    "This session profile snapshot is still referenced by session undo/redo."
                    if is_protected
                    else "Session history no longer references this stored profile snapshot."
                ),
                eligible=not is_protected,
            )
            (protected if is_protected else eligible).append(item)

        eligible.sort(key=lambda item: (item.item_type, item.created_at, item.label))
        protected.sort(key=lambda item: (item.item_type, item.created_at, item.label))
        return HistoryCleanupPreview(
            repair_required=bool(repair_messages),
            repair_messages=repair_messages,
            eligible_items=tuple(eligible),
            protected_items=tuple(protected),
        )

    def preview_trim_history(self, keep_visible_entries: int) -> HistoryTrimPreview:
        keep_count = max(1, int(keep_visible_entries))
        keep_entry_ids = self._trim_keep_entry_ids(keep_count)
        removable = [
            entry
            for entry in self.history_manager._all_history_entries()
            if entry.entry_id not in keep_entry_ids
        ]
        return HistoryTrimPreview(
            keep_visible_entries=keep_count,
            removable_entry_ids=tuple(entry.entry_id for entry in removable),
            removable_labels=tuple(entry.label for entry in removable[:10]),
        )

    def cleanup_selected(self, item_keys: list[str] | tuple[str, ...]) -> HistoryCleanupResult:
        self._raise_if_cleanup_blocked()
        preview = self.inspect()
        eligible_by_key = {item.item_key: item for item in preview.eligible_items}
        removed_keys: list[str] = []
        removed_paths: list[str] = []

        for item_key in item_keys:
            item = eligible_by_key.get(str(item_key))
            if item is None:
                raise ValueError(f"Cleanup item is not eligible: {item_key}")
            removed_paths.extend(self._remove_item(item))
            removed_keys.append(item.item_key)

        self.history_manager._ensure_history_invariants()
        return HistoryCleanupResult(
            removed_item_keys=tuple(removed_keys),
            removed_paths=tuple(removed_paths),
            removed_entry_ids=(),
        )

    def trim_history(self, keep_visible_entries: int) -> HistoryCleanupResult:
        self._raise_if_cleanup_blocked()
        preview = self.preview_trim_history(keep_visible_entries)
        removable_entry_ids = [int(entry_id) for entry_id in preview.removable_entry_ids]
        if not removable_entry_ids:
            return HistoryCleanupResult((), (), ())

        with self.history_manager.conn:
            self.history_manager.conn.executemany(
                "DELETE FROM HistoryEntries WHERE id=?",
                [(entry_id,) for entry_id in removable_entry_ids],
            )

        self.history_manager._ensure_history_invariants()

        post_trim_preview = self.inspect()
        removable_artifact_keys = [
            item.item_key
            for item in post_trim_preview.eligible_items
            if item.item_type in {"snapshot_record", "snapshot_archive", "file_state_bundle"}
        ]
        cleanup_result = (
            self.cleanup_selected(removable_artifact_keys)
            if removable_artifact_keys
            else (HistoryCleanupResult((), (), ()))
        )
        return HistoryCleanupResult(
            removed_item_keys=cleanup_result.removed_item_keys,
            removed_paths=cleanup_result.removed_paths,
            removed_entry_ids=tuple(removable_entry_ids),
        )

    def preview_storage_budget(
        self, settings: HistoryRetentionSettings
    ) -> HistoryStorageBudgetPreview:
        preview = self.inspect()
        candidate_items = self._automatic_cleanup_candidates(
            preview.eligible_items,
            settings=settings,
        )
        total_bytes = sum(
            int(item.bytes_on_disk or 0)
            for item in (*preview.eligible_items, *preview.protected_items)
        )
        budget_mb = max(0, int(settings.storage_budget_mb or 0))
        budget_bytes = budget_mb * 1024 * 1024
        over_budget_bytes = max(0, total_bytes - budget_bytes) if budget_bytes > 0 else 0
        candidate_keys = {item.item_key for item in candidate_items}
        protected_over_budget_items = (
            tuple(item for item in preview.eligible_items if item.item_key not in candidate_keys)
            + preview.protected_items
        )
        return HistoryStorageBudgetPreview(
            total_bytes=total_bytes,
            budget_bytes=budget_bytes,
            over_budget_bytes=over_budget_bytes,
            auto_cleanup_enabled=bool(settings.auto_cleanup_enabled),
            candidate_items=candidate_items,
            protected_over_budget_items=protected_over_budget_items,
        )

    def enforce_storage_budget(
        self, settings: HistoryRetentionSettings
    ) -> HistoryStorageBudgetResult:
        preview = self.preview_storage_budget(settings)
        removed_item_keys: tuple[str, ...] = ()
        removed_paths: tuple[str, ...] = ()
        if preview.auto_cleanup_enabled and preview.candidate_items:
            cleanup_result = self.cleanup_selected(
                [item.item_key for item in preview.candidate_items]
            )
            removed_item_keys = cleanup_result.removed_item_keys
            removed_paths = cleanup_result.removed_paths
            preview = self.preview_storage_budget(settings)
        blocked = (
            preview.budget_bytes > 0
            and preview.over_budget_bytes > 0
            and bool(preview.protected_over_budget_items)
        )
        return HistoryStorageBudgetResult(
            removed_item_keys=removed_item_keys,
            removed_paths=removed_paths,
            total_bytes=preview.total_bytes,
            budget_bytes=preview.budget_bytes,
            over_budget_bytes=preview.over_budget_bytes,
            blocked_by_protected_items=blocked,
        )

    def preview_storage_projection(
        self,
        settings: HistoryRetentionSettings,
        *,
        additional_bytes: int = 0,
    ) -> HistoryStorageProjection:
        budget_preview = self.preview_storage_budget(settings)
        added_bytes = max(0, int(additional_bytes or 0))
        projected_total = budget_preview.total_bytes + added_bytes
        reclaimable_bytes = sum(
            int(item.bytes_on_disk or 0) for item in budget_preview.candidate_items
        )
        projected_over_budget = (
            max(0, projected_total - budget_preview.budget_bytes)
            if budget_preview.budget_bytes > 0
            else 0
        )
        projected_after_cleanup = projected_total
        if budget_preview.auto_cleanup_enabled:
            projected_after_cleanup = max(0, projected_total - reclaimable_bytes)
        projected_over_budget_after_cleanup = (
            max(0, projected_after_cleanup - budget_preview.budget_bytes)
            if budget_preview.budget_bytes > 0
            else 0
        )
        return HistoryStorageProjection(
            additional_bytes=added_bytes,
            current_total_bytes=budget_preview.total_bytes,
            projected_total_bytes=projected_total,
            budget_bytes=budget_preview.budget_bytes,
            reclaimable_bytes=reclaimable_bytes,
            projected_over_budget_bytes=projected_over_budget,
            projected_over_budget_after_cleanup_bytes=projected_over_budget_after_cleanup,
            auto_cleanup_enabled=budget_preview.auto_cleanup_enabled,
            candidate_items=budget_preview.candidate_items,
            blocked_by_protected_items=(
                budget_preview.budget_bytes > 0 and projected_over_budget_after_cleanup > 0
            ),
        )

    def _raise_if_cleanup_blocked(self) -> None:
        preview = self.inspect()
        if preview.repair_required:
            message = "\n".join(preview.repair_messages[:10])
            raise HistoryCleanupBlockedError(
                "Cleanup is blocked until history diagnostics are repaired.\n\n" f"{message}"
            )

    def _remove_item(self, item: HistoryCleanupItem) -> list[str]:
        item_path = Path(item.path)
        removed: list[str] = []

        if item.item_type == "snapshot_record":
            snapshot = self.history_manager.fetch_snapshot(int(item.record_id or 0))
            if snapshot is None:
                raise ValueError(f"Snapshot {item.record_id} not found.")
            self.history_manager.delete_snapshot(int(item.record_id))
            removed.append(str(item_path))
            return removed

        if item.item_type == "backup_record":
            removed.extend(self._delete_backup_record(int(item.record_id or 0)))
            return removed

        if item.item_type == "orphan_snapshot_file":
            self._remove_snapshot_bundle(item_path)
            removed.append(str(item_path))
            return removed

        if item.item_type == "orphan_backup_file":
            self._remove_backup_bundle(item_path)
            removed.append(str(item_path))
            return removed

        if item.item_type == "snapshot_archive":
            self._remove_snapshot_bundle(item_path)
            removed.append(str(item_path))
            return removed

        if item.item_type == "file_state_bundle":
            self.history_manager._remove_path(item_path)
            removed.append(str(item_path))
            return removed

        if item.item_type == "session_snapshot":
            for suffix in self.SESSION_SNAPSHOT_SUFFIXES:
                path = Path(str(item_path) + suffix) if suffix else item_path
                if path.exists():
                    self.history_manager._remove_path(path)
                    removed.append(str(path))
            return removed

        raise ValueError(f"Unknown cleanup item type: {item.item_type}")

    def _automatic_cleanup_candidates(
        self,
        eligible_items: tuple[HistoryCleanupItem, ...],
        *,
        settings: HistoryRetentionSettings,
    ) -> tuple[HistoryCleanupItem, ...]:
        keep_snapshot_ids = self._auto_snapshot_ids_to_keep(
            int(settings.auto_snapshot_keep_latest or 0)
        )
        candidates: list[HistoryCleanupItem] = []
        for item in eligible_items:
            if item.item_type in self.AUTO_CLEANUP_ITEM_TYPES:
                candidates.append(item)
                continue
            if item.item_type == "snapshot_record" and self._is_auto_snapshot_cleanup_candidate(
                item,
                keep_snapshot_ids=keep_snapshot_ids,
            ):
                candidates.append(item)
                continue
            if item.item_type == "backup_record" and self._is_prunable_pre_restore_backup(
                item,
                max_age_days=int(settings.prune_pre_restore_copies_after_days or 0),
            ):
                candidates.append(item)
        return tuple(candidates)

    def _auto_snapshot_ids_to_keep(self, keep_latest: int) -> set[int]:
        keep_count = max(0, int(keep_latest or 0))
        auto_snapshots = [
            snapshot
            for snapshot in self.history_manager._all_snapshots()
            if str(snapshot.kind or "").strip().lower().startswith(self.AUTO_SNAPSHOT_KIND_PREFIX)
        ]
        auto_snapshots.sort(key=lambda snapshot: int(snapshot.snapshot_id), reverse=True)
        return {
            int(snapshot.snapshot_id)
            for snapshot in auto_snapshots[:keep_count]
            if int(snapshot.snapshot_id or 0) > 0
        }

    def _is_auto_snapshot_cleanup_candidate(
        self,
        item: HistoryCleanupItem,
        *,
        keep_snapshot_ids: set[int],
    ) -> bool:
        if not item.eligible or int(item.record_id or 0) <= 0:
            return False
        kind = str(item.kind or "").strip().lower()
        if not kind.startswith(self.AUTO_SNAPSHOT_KIND_PREFIX):
            return False
        return int(item.record_id or 0) not in keep_snapshot_ids

    def _is_prunable_pre_restore_backup(
        self,
        item: HistoryCleanupItem,
        *,
        max_age_days: int,
    ) -> bool:
        if not item.eligible or max_age_days <= 0:
            return False
        kind = str(item.kind or "").strip().lower()
        if "pre_restore" not in kind:
            return False
        created_at = self._parse_created_at(item.created_at)
        if created_at is None:
            return False
        age_days = max(0.0, (datetime.now() - created_at).total_seconds() / 86400.0)
        return age_days >= float(max_age_days)

    def _delete_backup_record(self, backup_id: int) -> list[str]:
        backup = self.history_manager.fetch_backup(backup_id)
        if backup is None:
            raise ValueError(f"Backup {backup_id} not found.")
        backup_path = Path(backup.backup_path)
        self.history_manager.delete_backup(backup_id)
        return [str(backup_path)]

    def _remove_snapshot_bundle(self, snapshot_path: Path) -> None:
        self.history_manager._remove_path(snapshot_path)
        self.history_manager._remove_path(
            self.history_manager._snapshot_sidecar_path(snapshot_path)
        )
        self.history_manager._remove_path(snapshot_path.with_suffix(".assets"))

    def _remove_backup_bundle(self, backup_path: Path) -> None:
        self.history_manager._remove_path(backup_path)
        self.history_manager._remove_path(self.history_manager._backup_sidecar_path(backup_path))

    def _protected_snapshot_ids(self, entries: list[HistoryEntry]) -> set[int]:
        snapshot_ids = set(self.history_manager._referenced_snapshot_ids())
        for entry in entries:
            snapshot_ids.update(self._collect_int_values(entry.payload, "snapshot_id"))
            snapshot_ids.update(self._collect_int_values(entry.inverse_payload, "snapshot_id"))
            snapshot_ids.update(self._collect_int_values(entry.redo_payload, "snapshot_id"))
        return snapshot_ids

    def _trim_keep_entry_ids(self, keep_visible_entries: int) -> set[int]:
        keep_ids: set[int] = set()

        visible_kept = 0
        current = self.history_manager.get_current_entry()
        while current is not None:
            keep_ids.add(current.entry_id)
            if current.reversible and current.visible_in_history:
                visible_kept += 1
                if visible_kept >= keep_visible_entries:
                    break
            if current.parent_id is None:
                break
            current = self.history_manager.fetch_entry(current.parent_id)

        redo_cursor = self.history_manager._get_default_redo_child(
            self.history_manager.get_current_entry_id()
        )
        seen_ids: set[int] = set()
        while redo_cursor is not None and redo_cursor.entry_id not in seen_ids:
            seen_ids.add(redo_cursor.entry_id)
            keep_ids.add(redo_cursor.entry_id)
            redo_cursor = self.history_manager._get_default_redo_child(redo_cursor.entry_id)

        return keep_ids

    def _registered_snapshot_paths(self) -> set[str]:
        return {
            str(Path(snapshot.db_snapshot_path))
            for snapshot in self.history_manager._all_snapshots()
            if snapshot.db_snapshot_path
        }

    def _registered_backup_paths(self) -> set[str]:
        return {
            str(Path(backup.backup_path))
            for backup in self.history_manager._all_backups()
            if backup.backup_path
        }

    def _snapshot_archive_root(self) -> Path:
        return (
            self.history_manager.history_root
            / "snapshot_archives"
            / self.history_manager.db_path.stem
        )

    def _file_states_root(self) -> Path:
        return self.history_manager.history_root / "file_states" / self.history_manager.db_path.stem

    def _session_snapshots_root(self) -> Path:
        return self.history_manager.history_root / "session_profile_snapshots"

    def _archive_bundle_paths(self) -> list[Path]:
        root = self._snapshot_archive_root()
        if not root.exists():
            return []
        return sorted(path for path in root.glob("*.db") if path.is_file())

    def _file_state_bundle_paths(self) -> list[Path]:
        root = self._file_states_root()
        if not root.exists():
            return []
        return sorted(path for path in root.iterdir() if path.is_dir())

    def _session_snapshot_bundle_paths(self) -> list[Path]:
        root = self._session_snapshots_root()
        if not root.exists():
            return []
        return sorted(path for path in root.glob("*.db") if path.is_file())

    def _session_snapshot_paths(self) -> set[Path]:
        session_history_path = self.history_manager.history_root / "session_history.json"
        if not session_history_path.exists():
            return set()
        try:
            state = json.loads(session_history_path.read_text(encoding="utf-8"))
        except Exception:
            return set()
        return self._paths_under_root(state, self._session_snapshots_root())

    def _live_paths_under_root(self, entries: list[HistoryEntry], root: Path) -> set[Path]:
        live_paths: set[Path] = set()
        for entry in entries:
            live_paths.update(self._paths_under_root(entry.payload, root))
            live_paths.update(self._paths_under_root(entry.inverse_payload, root))
            live_paths.update(self._paths_under_root(entry.redo_payload, root))
        return live_paths

    def _path_is_referenced(self, path: Path, live_paths: set[Path]) -> bool:
        target = path.resolve()
        bundle_root = path if path.is_dir() else path.with_suffix(".assets")
        for live_path in live_paths:
            try:
                candidate = live_path.resolve()
            except Exception:
                candidate = live_path
            if candidate == target:
                return True
            if bundle_root.exists():
                try:
                    candidate.relative_to(bundle_root.resolve())
                    return True
                except Exception:
                    pass
        return False

    def _paths_under_root(self, value: Any, root: Path) -> set[Path]:
        paths: set[Path] = set()
        if isinstance(value, dict):
            for item in value.values():
                paths.update(self._paths_under_root(item, root))
            return paths
        if isinstance(value, list):
            for item in value:
                paths.update(self._paths_under_root(item, root))
            return paths
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return paths
            try:
                candidate = Path(text)
            except Exception:
                return paths
            if not candidate.is_absolute():
                return paths
            try:
                resolved = candidate.resolve()
                resolved.relative_to(root.resolve())
            except Exception:
                return paths
            paths.add(resolved)
        return paths

    def _collect_int_values(self, value: Any, key_name: str) -> set[int]:
        values: set[int] = set()
        if isinstance(value, dict):
            for key, item in value.items():
                if key == key_name:
                    try:
                        values.add(int(item))
                    except Exception:
                        pass
                values.update(self._collect_int_values(item, key_name))
            return values
        if isinstance(value, list):
            for item in value:
                values.update(self._collect_int_values(item, key_name))
        return values

    @staticmethod
    def _path_size(path: Path) -> int:
        try:
            if path.is_dir():
                return sum(
                    file_path.stat().st_size for file_path in path.rglob("*") if file_path.is_file()
                )
            if path.exists():
                return int(path.stat().st_size)
        except Exception:
            return 0
        return 0

    def _session_snapshot_size(self, snapshot_path: Path) -> int:
        total = 0
        for suffix in self.SESSION_SNAPSHOT_SUFFIXES:
            path = Path(str(snapshot_path) + suffix) if suffix else snapshot_path
            total += self._path_size(path)
        return total

    @staticmethod
    def _parse_created_at(value: str) -> datetime | None:
        text = str(value or "").strip()
        if not text:
            return None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
        return None

    @staticmethod
    def _path_created_at(path: Path) -> str:
        try:
            return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return ""

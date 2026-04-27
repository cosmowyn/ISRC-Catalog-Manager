"""App-owned storage layout inspection and migration helpers."""

from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from PySide6.QtCore import QSettings
else:
    try:
        from PySide6.QtCore import QSettings
    except Exception:  # pragma: no cover - optional Qt fallback
        QSettings = None

from .paths import (
    APP_NAME,
    BACKUPS_SUBDIR,
    DATABASE_SUBDIR,
    EXPORTS_SUBDIR,
    HELP_SUBDIR,
    HISTORY_SUBDIR,
    LOGS_SUBDIR,
    MANAGED_STORAGE_SUBDIRS,
    STORAGE_ACTIVE_DATA_ROOT_KEY,
    STORAGE_LEGACY_DATA_ROOT_KEY,
    STORAGE_MIGRATION_JOURNAL_BASENAME,
    STORAGE_MIGRATION_STATE_KEY,
    STORAGE_STATE_COMPLETE,
    STORAGE_STATE_DEFERRED,
    STORAGE_STATE_FAILED,
    AppStorageLayout,
)

APP_OWNED_SUBDIRS = (
    DATABASE_SUBDIR,
    BACKUPS_SUBDIR,
    HISTORY_SUBDIR,
    LOGS_SUBDIR,
    EXPORTS_SUBDIR,
    HELP_SUBDIR,
    *MANAGED_STORAGE_SUBDIRS,
)

SOURCE_BACKED_SUBDIRS = (
    DATABASE_SUBDIR,
    BACKUPS_SUBDIR,
    HISTORY_SUBDIR,
    EXPORTS_SUBDIR,
    *MANAGED_STORAGE_SUBDIRS,
)

PREFERRED_STATE_EMPTY = "empty"
PREFERRED_STATE_VALID_COMPLETE = "valid_complete"
PREFERRED_STATE_RESUMABLE_STAGE = "resumable_stage"
PREFERRED_STATE_SAFE_NOISE = "safe_noise"
PREFERRED_STATE_CONFLICT = "conflict"

SNAPSHOT_TABLE_SQL = """
    SELECT id, db_snapshot_path, settings_json, manifest_json
    FROM HistorySnapshots
"""

BACKUP_TABLE_SQL = """
    SELECT id, backup_path, source_db_path, metadata_json
    FROM HistoryBackups
"""

ENTRY_TABLE_SQL = """
    SELECT id, payload_json, inverse_json, redo_json
    FROM HistoryEntries
"""


@dataclass(slots=True)
class StorageLayoutInspection:
    layout: AppStorageLayout
    legacy_root: Path | None
    legacy_items: tuple[str, ...]
    preferred_items: tuple[str, ...]
    preferred_state: str
    migration_needed: bool
    deferred: bool
    journal_status: str
    journal_path: Path | None
    journal: dict[str, Any]
    journal_source_root: Path | None
    stage_root: Path | None
    conflict_items: tuple[str, ...]

    @property
    def target_items(self) -> tuple[str, ...]:
        return self.preferred_items

    @property
    def target_ready(self) -> bool:
        return self.preferred_state != PREFERRED_STATE_EMPTY

    @property
    def adopt_needed(self) -> bool:
        return self.preferred_state == PREFERRED_STATE_VALID_COMPLETE

    @property
    def resume_needed(self) -> bool:
        return self.preferred_state == PREFERRED_STATE_RESUMABLE_STAGE


@dataclass(slots=True)
class StorageMigrationResult:
    action: str
    source_root: Path
    target_root: Path
    copied_items: tuple[str, ...]
    rewritten_files: tuple[str, ...]
    verified_databases: tuple[str, ...]
    journal_path: Path


ProgressReporter = Callable[[int, int, str], None]


class StorageMigrationService:
    """Detects and migrates legacy app-owned storage into the preferred layout."""

    SQLITE_COMPANION_SUFFIXES = ("-wal", "-shm", "-journal")
    SAFE_HELP_FILE = Path(HELP_SUBDIR) / "isrc_catalog_manager_help.html"

    def __init__(
        self,
        layout: AppStorageLayout,
        settings: QSettings | None = None,
        reporter: Callable[..., None] | None = None,
        progress_reporter: ProgressReporter | None = None,
    ):
        self.layout = layout
        self.settings = settings
        self.reporter = reporter
        self.progress_reporter = progress_reporter

    def inspect(self) -> StorageLayoutInspection:
        self._progress(8, 100, "Checking existing app storage roots...")
        legacy_root = self._select_legacy_root()
        self._progress(16, 100, "Scanning legacy app-data folder...")
        legacy_items = (
            self._present_items(legacy_root, progress_value=16, label="legacy app-data")
            if legacy_root is not None
            else ()
        )
        self._progress(24, 100, "Scanning preferred app-data folder...")
        preferred_items = self._present_items(
            self.layout.preferred_data_root,
            progress_value=24,
            label="preferred app-data",
        )
        self._progress(32, 100, "Reading storage migration journal...")
        journal, journal_path = self._load_journal_details()
        journal_status = str(journal.get("status") or "").strip()
        journal_source_root = self._journal_path_value(journal.get("source_root"))
        stage_root = self._journal_path_value(journal.get("stage_root"))
        self._progress(40, 100, "Validating preferred storage layout...")
        preferred_state, conflict_items = self._assess_preferred_root_state(
            legacy_root=legacy_root,
            legacy_items=legacy_items,
            preferred_items=preferred_items,
            journal=journal,
            stage_root=stage_root,
        )
        self._progress(46, 100, "Checking stored migration preference...")
        deferred = self._settings_value(STORAGE_MIGRATION_STATE_KEY) == STORAGE_STATE_DEFERRED
        migration_needed = bool(
            legacy_root is not None
            and legacy_items
            and legacy_root != self.layout.preferred_data_root
            and preferred_state in (PREFERRED_STATE_EMPTY, PREFERRED_STATE_SAFE_NOISE)
        )
        self._progress(50, 100, "Finished storage layout inspection.")
        return StorageLayoutInspection(
            layout=self.layout,
            legacy_root=legacy_root,
            legacy_items=legacy_items,
            preferred_items=preferred_items,
            preferred_state=preferred_state,
            migration_needed=migration_needed,
            deferred=deferred,
            journal_status=journal_status,
            journal_path=journal_path,
            journal=journal,
            journal_source_root=journal_source_root,
            stage_root=stage_root,
            conflict_items=conflict_items,
        )

    def defer(self, legacy_root: Path | None = None) -> None:
        if self.settings is None:
            return
        root = legacy_root or self._select_legacy_root()
        if root is None:
            return
        preferred_root = self.layout.preferred_data_root.resolve()
        last_path = str(self.settings.value("db/last_path", "", str) or "").strip()
        if last_path:
            updated_last_path = self._rewrite_path_string(last_path, preferred_root, root.resolve())
            if updated_last_path != last_path:
                self.settings.setValue("db/last_path", updated_last_path)
        database_dir = str(self.settings.value("paths/database_dir", "", str) or "").strip()
        if database_dir:
            updated_database_dir = self._rewrite_path_string(
                database_dir,
                preferred_root,
                root.resolve(),
            )
            if updated_database_dir != database_dir:
                self.settings.setValue("paths/database_dir", updated_database_dir)
        self.settings.setValue(STORAGE_LEGACY_DATA_ROOT_KEY, str(root.resolve()))
        self.settings.setValue(STORAGE_ACTIVE_DATA_ROOT_KEY, str(root.resolve()))
        self.settings.setValue(STORAGE_MIGRATION_STATE_KEY, STORAGE_STATE_DEFERRED)
        self.settings.sync()

    def mark_complete(self) -> None:
        if self.settings is None:
            return
        self.settings.setValue(
            STORAGE_ACTIVE_DATA_ROOT_KEY, str(self.layout.preferred_data_root.resolve())
        )
        legacy_root = self._select_legacy_root(progress_value=94)
        if legacy_root is not None:
            self.settings.setValue(STORAGE_LEGACY_DATA_ROOT_KEY, str(legacy_root.resolve()))
        self.settings.setValue(STORAGE_MIGRATION_STATE_KEY, STORAGE_STATE_COMPLETE)
        self.settings.sync()

    def mark_failed(self, legacy_root: Path | None = None) -> None:
        if self.settings is None:
            return
        root = legacy_root or self._select_legacy_root(progress_value=94)
        if root is not None:
            self.settings.setValue(STORAGE_LEGACY_DATA_ROOT_KEY, str(root.resolve()))
        self.settings.setValue(STORAGE_MIGRATION_STATE_KEY, STORAGE_STATE_FAILED)
        self.settings.sync()

    def migrate(self) -> StorageMigrationResult:
        inspection = self.inspect()
        target_root = self.layout.preferred_data_root.resolve()
        source_root = self._resolve_source_root(inspection)

        if inspection.preferred_state == PREFERRED_STATE_VALID_COMPLETE:
            self._progress(56, 100, "Adopting verified preferred storage root...")
            self._report(
                "storage.migration.adopt",
                "Adopting verified preferred app-data root",
                source_root=source_root,
                target_root=target_root,
                journal_status=inspection.journal_status,
            )
            return self._adopt_preferred_root(inspection, source_root, target_root)

        if inspection.preferred_state == PREFERRED_STATE_CONFLICT:
            self._progress(56, 100, "Preferred storage contains conflicting content.")
            self._report(
                "storage.migration.conflict",
                "Preferred app-data root contains conflicting content",
                target_root=target_root,
                conflict_items=list(inspection.conflict_items),
            )
            raise RuntimeError(self._format_conflict_error(target_root, inspection.conflict_items))

        if inspection.preferred_state == PREFERRED_STATE_RESUMABLE_STAGE:
            try:
                self._progress(56, 100, "Resuming staged storage migration...")
                self._report(
                    "storage.migration.resume",
                    "Resuming preserved staged app-data migration",
                    source_root=source_root,
                    target_root=target_root,
                    stage_root=inspection.stage_root,
                )
                return self._resume_migration_stage(inspection, source_root, target_root)
            except Exception as exc:
                if inspection.legacy_root is None or not inspection.legacy_items:
                    raise
                self._report(
                    "storage.migration.resume_fallback",
                    "Preserved staged migration could not be resumed; restaging from legacy",
                    level="warning",
                    source_root=inspection.legacy_root,
                    target_root=target_root,
                    stage_root=inspection.stage_root,
                    error=str(exc),
                )

        if inspection.legacy_root is None:
            raise RuntimeError("No legacy app-data root was detected.")
        source_root = inspection.legacy_root.resolve()
        copied_items = [name for name in APP_OWNED_SUBDIRS if (source_root / name).exists()]
        if not copied_items:
            raise RuntimeError("No app-owned legacy storage was found to migrate.")

        if inspection.preferred_state == PREFERRED_STATE_SAFE_NOISE:
            self._progress(56, 100, "Clearing safe preferred-storage bootstrap files...")
            self._report(
                "storage.migration.safe_noise",
                "Clearing safe bootstrap residue from preferred app-data root",
                target_root=target_root,
            )
            self._clear_safe_target_noise(target_root)

        self._progress(60, 100, "Inventorying legacy app-data files...")
        source_inventory = self._source_inventory(
            source_root,
            copied_items,
            progress_value=60,
            label="legacy app-data",
        )
        self._progress(64, 100, "Creating temporary storage migration stage...")
        target_root.parent.mkdir(parents=True, exist_ok=True)
        stage_container = Path(
            tempfile.mkdtemp(prefix=f"{target_root.name}_migration_", dir=str(target_root.parent))
        )
        stage_root = stage_container / target_root.name
        journal_path = stage_root / STORAGE_MIGRATION_JOURNAL_BASENAME
        stage_root.mkdir(parents=True, exist_ok=True)
        self._write_journal(
            journal_path,
            {
                "status": "in_progress",
                "app_name": APP_NAME,
                "source_root": str(source_root),
                "target_root": str(target_root),
                "stage_root": str(stage_root),
                "copied_items": copied_items,
                "source_inventory_count": len(source_inventory),
                "rewritten_files": [],
                "verified_databases": [],
                "started_at": self._timestamp(),
            },
        )
        self._report(
            "storage.migration.stage",
            "Staging legacy app-owned data into the preferred layout",
            source_root=source_root,
            target_root=target_root,
            stage_root=stage_root,
            copied_items=copied_items,
        )

        try:
            copy_start = 68
            copy_end = 82
            for index, name in enumerate(copied_items, start=1):
                copy_progress = copy_start + int(
                    ((index - 1) / max(1, len(copied_items))) * (copy_end - copy_start)
                )
                self._progress(copy_progress, 100, f"Copying storage item: {name}")
                self._copy_item(
                    source_root / name,
                    stage_root / name,
                    progress_value=copy_progress,
                )

            self._progress(82, 100, "Verifying staged storage inventory...")
            self._validate_stage_inventory(stage_root, source_inventory)

            self._progress(86, 100, "Rewriting internal storage references...")
            rewritten_files = list(
                self._rewrite_target_storage(source_root, stage_root, progress_value=86)
            )
            self._progress(90, 100, "Checking migrated profile databases...")
            verified = list(self._verify_target_databases(stage_root, progress_value=90))
            self._progress(94, 100, "Activating preferred storage root...")
            self._promote_stage_root(stage_root, target_root)
            self._rewrite_settings_paths(source_root, target_root)
            self.mark_complete()
            payload = self._complete_payload(
                action="migrated",
                source_root=source_root,
                target_root=target_root,
                copied_items=copied_items,
                source_inventory_count=len(source_inventory),
                rewritten_files=rewritten_files,
                verified_databases=verified,
            )
            self._write_journal(target_root / STORAGE_MIGRATION_JOURNAL_BASENAME, payload)
            self._remove_empty_stage_container(stage_container)
            self._progress(98, 100, "Storage migration completed.")
            self._report(
                "storage.migration.promote",
                "Migrated legacy app-owned data into the preferred layout",
                source_root=source_root,
                target_root=target_root,
                copied_items=copied_items,
                verified_databases=verified,
            )
            return StorageMigrationResult(
                action="migrated",
                source_root=source_root,
                target_root=target_root,
                copied_items=tuple(copied_items),
                rewritten_files=tuple(rewritten_files),
                verified_databases=tuple(verified),
                journal_path=target_root / STORAGE_MIGRATION_JOURNAL_BASENAME,
            )
        except Exception:
            self.mark_failed(source_root)
            failure_payload = {
                "status": STORAGE_STATE_FAILED,
                "app_name": APP_NAME,
                "source_root": str(source_root),
                "target_root": str(target_root),
                "stage_root": str(stage_root),
                "copied_items": copied_items,
                "source_inventory_count": len(source_inventory),
                "failed_at": self._timestamp(),
            }
            self._write_journal(journal_path, failure_payload)
            self._write_journal(
                target_root.parent / f".{target_root.name}_{STORAGE_MIGRATION_JOURNAL_BASENAME}",
                failure_payload,
            )
            self._report(
                "storage.migration.failed",
                "App-data migration failed",
                level="error",
                source_root=source_root,
                target_root=target_root,
                stage_root=stage_root,
            )
            raise

    def load_journal(self) -> dict[str, Any]:
        journal, _journal_path = self._load_journal_details()
        return journal

    def _load_journal_details(self) -> tuple[dict[str, Any], Path | None]:
        for journal_path in self._journal_candidates():
            self._progress_path(32, 100, "Checking storage migration journal", journal_path)
            if not journal_path.exists():
                continue
            try:
                raw = json.loads(journal_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if isinstance(raw, dict):
                return raw, journal_path
        return {}, None

    def _select_legacy_root(self, *, progress_value: int = 8) -> Path | None:
        configured = self._settings_value(STORAGE_LEGACY_DATA_ROOT_KEY)
        if configured:
            candidate = Path(configured).resolve()
            self._progress_path(
                progress_value, 100, "Checking configured legacy storage root", candidate
            )
            if candidate.exists():
                return candidate
        for candidate in self.layout.legacy_data_roots:
            resolved_candidate = Path(candidate).resolve()
            self._progress_path(
                progress_value, 100, "Checking legacy storage root", resolved_candidate
            )
            if self._present_items(
                resolved_candidate,
                progress_value=progress_value,
                label="legacy app-data candidate",
            ):
                return resolved_candidate
        return None

    def _present_items(
        self,
        root: Path | None,
        *,
        progress_value: int = 0,
        label: str = "app-data",
    ) -> tuple[str, ...]:
        if root is None:
            return ()
        self._progress_path(progress_value, 100, f"Scanning {label} root", root)
        if not root.exists():
            return ()
        items: list[str] = []
        for name in APP_OWNED_SUBDIRS:
            candidate = root / name
            self._progress_path(progress_value, 100, f"Scanning {label} path", candidate)
            if candidate.exists():
                items.append(name)
        return tuple(items)

    def _settings_value(self, key: str) -> str:
        if self.settings is None:
            return ""
        return str(self.settings.value(key, "", str) or "").strip()

    def _report(self, event: str, message: str, **fields: Any) -> None:
        if self.reporter is None:
            return
        level_name = str(fields.pop("level", "info")).strip().lower()
        self.reporter(event, message, level=self._report_level(level_name), **fields)

    def _progress(self, value: int, maximum: int, message: str) -> None:
        if self.progress_reporter is None:
            return
        try:
            self.progress_reporter(int(value), int(maximum), str(message or ""))
        except Exception:
            pass

    def _progress_path(self, value: int, maximum: int, action: str, path: Path) -> None:
        action_text = str(action or "Scanning storage path").rstrip(":")
        self._progress(value, maximum, f"{action_text}: {self._display_path(path)}")

    @staticmethod
    def _display_path(path: Path) -> str:
        try:
            return str(Path(path).expanduser().resolve())
        except Exception:
            return str(path)

    @staticmethod
    def _report_level(level_name: str) -> int:
        levels = {"debug": 10, "info": 20, "warning": 30, "error": 40}
        return levels.get(level_name, 20)

    def _assess_preferred_root_state(
        self,
        *,
        legacy_root: Path | None,
        legacy_items: tuple[str, ...],
        preferred_items: tuple[str, ...],
        journal: dict[str, Any],
        stage_root: Path | None,
    ) -> tuple[str, tuple[str, ...]]:
        target_root = self.layout.preferred_data_root.resolve()
        base_state = PREFERRED_STATE_EMPTY
        conflict_items: tuple[str, ...] = ()

        if self._preferred_root_valid(
            target_root, legacy_root, legacy_items, journal, preferred_items
        ):
            base_state = PREFERRED_STATE_VALID_COMPLETE
        elif not target_root.exists() or not any(target_root.iterdir()):
            base_state = PREFERRED_STATE_EMPTY
        else:
            conflict_items = self._preferred_root_conflicts(target_root)
            if conflict_items:
                base_state = PREFERRED_STATE_CONFLICT
            else:
                base_state = PREFERRED_STATE_SAFE_NOISE

        if (
            base_state in (PREFERRED_STATE_EMPTY, PREFERRED_STATE_SAFE_NOISE)
            and stage_root is not None
            and stage_root.exists()
            and any(stage_root.iterdir())
        ):
            return PREFERRED_STATE_RESUMABLE_STAGE, ()
        return base_state, conflict_items

    def _preferred_root_valid(
        self,
        target_root: Path,
        legacy_root: Path | None,
        legacy_items: tuple[str, ...],
        journal: dict[str, Any],
        preferred_items: tuple[str, ...],
    ) -> bool:
        if not target_root.exists():
            return False
        required_items = self._required_source_backed_items(
            legacy_items=legacy_items,
            journal=journal,
            preferred_items=preferred_items,
        )
        if not required_items:
            return False
        for name in required_items:
            required_path = target_root / name
            self._progress_path(40, 100, "Checking preferred storage item", required_path)
            if not required_path.exists():
                return False
        try:
            self._verify_target_databases(target_root, progress_value=40)
        except Exception:
            return False
        validation_root = legacy_root or self._journal_path_value(journal.get("source_root"))
        if validation_root is not None:
            try:
                if self._find_legacy_references(
                    validation_root.resolve(),
                    target_root,
                    progress_value=40,
                    label="preferred storage",
                ):
                    return False
            except Exception:
                return False
        journal_target = self._journal_path_value(journal.get("target_root"))
        journal_status = str(journal.get("status") or "").strip()
        if journal_status == STORAGE_STATE_COMPLETE and journal_target is not None:
            if journal_target.resolve() != target_root.resolve():
                return False
        return True

    @staticmethod
    def _required_source_backed_items(
        *,
        legacy_items: tuple[str, ...],
        journal: dict[str, Any],
        preferred_items: tuple[str, ...],
    ) -> tuple[str, ...]:
        required = [name for name in legacy_items if name in SOURCE_BACKED_SUBDIRS]
        if not required:
            copied_items = journal.get("copied_items")
            if isinstance(copied_items, list):
                required = [
                    str(name)
                    for name in copied_items
                    if isinstance(name, str) and str(name) in SOURCE_BACKED_SUBDIRS
                ]
        if not required:
            required = [name for name in preferred_items if name in SOURCE_BACKED_SUBDIRS]
        deduped: list[str] = []
        for name in required:
            if name not in deduped:
                deduped.append(name)
        return tuple(deduped)

    def _preferred_root_conflicts(
        self,
        target_root: Path,
        *,
        progress_value: int = 40,
        label: str = "preferred app-data",
    ) -> tuple[str, ...]:
        conflicts: list[str] = []
        if not target_root.exists():
            return ()
        for path in sorted(target_root.rglob("*")):
            if path.is_dir():
                continue
            self._progress_path(progress_value, 100, f"Scanning {label} file", path)
            try:
                relative = path.relative_to(target_root)
            except Exception:
                relative = Path(path.name)
            if self._is_safe_noise_path(relative):
                continue
            conflicts.append(str(relative))
        return tuple(conflicts)

    def _resume_migration_stage(
        self,
        inspection: StorageLayoutInspection,
        source_root: Path | None,
        target_root: Path,
    ) -> StorageMigrationResult:
        if inspection.stage_root is None:
            raise RuntimeError("No preserved staged migration was found to resume.")
        stage_root = inspection.stage_root.resolve()
        if not stage_root.exists():
            raise RuntimeError("The preserved staged migration folder is missing.")

        self._progress(60, 100, "Inspecting preserved storage migration stage...")
        copied_items = self._journal_copied_items(inspection.journal, inspection.legacy_items)
        stage_inventory = self._collect_inventory(
            stage_root,
            progress_value=60,
            label="preserved migration stage",
        )
        if source_root is not None and copied_items:
            self._progress(66, 100, "Verifying staged storage against legacy inventory...")
            source_inventory = self._source_inventory(
                source_root,
                copied_items,
                progress_value=66,
                label="legacy app-data",
            )
            self._validate_stage_inventory(stage_root, source_inventory)
            source_inventory_count = len(source_inventory)
        else:
            expected_count = int(inspection.journal.get("source_inventory_count") or 0)
            if expected_count and len(stage_inventory) != expected_count:
                raise RuntimeError(
                    "The preserved staged migration is incomplete and cannot be resumed safely."
                )
            source_inventory_count = len(stage_inventory)

        rewrite_root = source_root or inspection.journal_source_root
        self._progress(74, 100, "Rewriting staged storage references...")
        rewritten_files = list(
            self._rewrite_target_storage(rewrite_root, stage_root, progress_value=74)
            if rewrite_root is not None
            else ()
        )
        self._progress(82, 100, "Checking staged profile databases...")
        verified = list(self._verify_target_databases(stage_root, progress_value=82))
        if (
            self._find_legacy_references(
                rewrite_root,
                stage_root,
                progress_value=86,
                label="staged storage",
            )
            if rewrite_root is not None
            else ()
        ):
            raise RuntimeError(
                "The preserved staged migration still contains legacy-root references."
            )
        if target_root.exists() and any(target_root.iterdir()):
            target_conflicts = self._preferred_root_conflicts(
                target_root,
                progress_value=88,
                label="preferred app-data",
            )
            if target_conflicts:
                raise RuntimeError(self._format_conflict_error(target_root, target_conflicts))
            self._clear_safe_target_noise(target_root)
        self._progress(90, 100, "Activating resumed storage migration...")
        self._promote_stage_root(stage_root, target_root)
        if rewrite_root is not None:
            self._rewrite_settings_paths(rewrite_root, target_root)
        else:
            self._activate_target_root(target_root)
        self.mark_complete()
        payload = self._complete_payload(
            action="resumed",
            source_root=rewrite_root,
            target_root=target_root,
            copied_items=copied_items,
            source_inventory_count=source_inventory_count,
            rewritten_files=rewritten_files,
            verified_databases=verified,
        )
        self._write_journal(target_root / STORAGE_MIGRATION_JOURNAL_BASENAME, payload)
        self._remove_empty_stage_container(stage_root.parent)
        self._progress(98, 100, "Resumed storage migration completed.")
        return StorageMigrationResult(
            action="resumed",
            source_root=(rewrite_root or target_root).resolve(),
            target_root=target_root,
            copied_items=tuple(copied_items),
            rewritten_files=tuple(rewritten_files),
            verified_databases=tuple(verified),
            journal_path=target_root / STORAGE_MIGRATION_JOURNAL_BASENAME,
        )

    def _adopt_preferred_root(
        self,
        inspection: StorageLayoutInspection,
        source_root: Path | None,
        target_root: Path,
    ) -> StorageMigrationResult:
        copied_items = self._journal_copied_items(inspection.journal, inspection.legacy_items)
        if not copied_items:
            copied_items = list(inspection.preferred_items)
        self._progress(64, 100, "Checking preferred storage databases...")
        verified = list(self._verify_target_databases(target_root, progress_value=64))
        source_inventory_count = self._adoption_inventory_count(
            source_root,
            copied_items,
            inspection.journal,
            progress_value=72,
        )
        self._progress(78, 100, "Updating active storage settings...")
        if source_root is not None:
            self._rewrite_settings_paths(source_root, target_root)
        else:
            self._activate_target_root(target_root)
        self.mark_complete()
        payload = self._complete_payload(
            action="adopted",
            source_root=source_root,
            target_root=target_root,
            copied_items=copied_items,
            source_inventory_count=source_inventory_count,
            rewritten_files=[],
            verified_databases=verified,
        )
        self._write_journal(target_root / STORAGE_MIGRATION_JOURNAL_BASENAME, payload)
        self._progress(98, 100, "Preferred storage root is ready.")
        return StorageMigrationResult(
            action="adopted",
            source_root=(source_root or target_root).resolve(),
            target_root=target_root,
            copied_items=tuple(copied_items),
            rewritten_files=(),
            verified_databases=tuple(verified),
            journal_path=target_root / STORAGE_MIGRATION_JOURNAL_BASENAME,
        )

    @staticmethod
    def _journal_copied_items(
        journal: dict[str, Any], fallback_items: tuple[str, ...]
    ) -> list[str]:
        copied_items = journal.get("copied_items")
        if isinstance(copied_items, list):
            return [str(name) for name in copied_items if isinstance(name, str)]
        return list(fallback_items)

    def _adoption_inventory_count(
        self,
        source_root: Path | None,
        copied_items: list[str],
        journal: dict[str, Any],
        *,
        progress_value: int,
    ) -> int:
        if source_root is not None and copied_items:
            return len(
                self._source_inventory(
                    source_root,
                    copied_items,
                    progress_value=progress_value,
                    label="legacy app-data",
                )
            )
        try:
            return int(journal.get("source_inventory_count") or 0)
        except Exception:
            return 0

    def _resolve_source_root(self, inspection: StorageLayoutInspection) -> Path | None:
        if inspection.legacy_root is not None:
            return inspection.legacy_root.resolve()
        if inspection.journal_source_root is not None:
            return inspection.journal_source_root.resolve()
        return None

    def _activate_target_root(self, target_root: Path) -> None:
        if self.settings is None:
            return
        self.settings.setValue(STORAGE_ACTIVE_DATA_ROOT_KEY, str(target_root.resolve()))
        self.settings.sync()

    def _clear_safe_target_noise(self, target_root: Path) -> None:
        if not target_root.exists():
            return
        for path in sorted(target_root.rglob("*"), reverse=True):
            if path.is_dir():
                try:
                    path.rmdir()
                except OSError:
                    pass
                continue
            relative = path.relative_to(target_root)
            if not self._is_safe_noise_path(relative):
                raise RuntimeError(self._format_conflict_error(target_root, (str(relative),)))
            path.unlink(missing_ok=True)
        try:
            target_root.rmdir()
        except OSError:
            pass

    @classmethod
    def _is_safe_noise_path(cls, relative: Path) -> bool:
        if not relative.parts:
            return True
        if relative == cls.SAFE_HELP_FILE:
            return True
        return bool(relative.parts[0] == LOGS_SUBDIR)

    @staticmethod
    def _format_conflict_error(target_root: Path, conflict_items: tuple[str, ...]) -> str:
        preview = "\n".join(f"- {item}" for item in conflict_items[:20]) or "- (unknown)"
        return (
            "Preferred app-data root contains conflicting content and cannot be replaced automatically.\n\n"
            f"Preferred root: {target_root}\n"
            f"Conflicting items:\n{preview}"
        )

    @staticmethod
    def _journal_path_value(raw: object) -> Path | None:
        text = str(raw or "").strip()
        if not text:
            return None
        try:
            return Path(text).resolve()
        except Exception:
            return None

    def _journal_candidates(self) -> tuple[Path, Path]:
        target_root = self.layout.preferred_data_root
        return (
            target_root / STORAGE_MIGRATION_JOURNAL_BASENAME,
            target_root.parent / f".{target_root.name}_{STORAGE_MIGRATION_JOURNAL_BASENAME}",
        )

    def _collect_inventory(
        self,
        root: Path,
        *,
        progress_value: int,
        label: str,
    ) -> tuple[str, ...]:
        if not root.exists():
            return ()
        inventory: list[str] = []
        for path in sorted(root.rglob("*")):
            if path.is_dir():
                continue
            self._progress_path(progress_value, 100, f"Scanning {label} file", path)
            if self._is_transient_sqlite_companion(path):
                continue
            inventory.append(str(path.relative_to(root)))
        return tuple(inventory)

    def _find_legacy_references(
        self,
        source_root: Path | None,
        target_root: Path,
        *,
        progress_value: int,
        label: str,
    ) -> tuple[str, ...]:
        if source_root is None:
            return ()
        source_root = source_root.resolve()
        references: list[str] = []

        database_dir = target_root / DATABASE_SUBDIR
        if database_dir.exists():
            for db_path in sorted(database_dir.glob("*.db")):
                self._progress_path(progress_value, 100, f"Scanning {label} database", db_path)
                if self._database_contains_legacy_reference(db_path, source_root):
                    references.append(str(db_path))

        history_root = target_root / HISTORY_SUBDIR
        if history_root.exists():
            session_history_path = history_root / "session_history.json"
            if session_history_path.exists():
                self._progress_path(
                    progress_value,
                    100,
                    f"Scanning {label} history file",
                    session_history_path,
                )
                if self._json_file_contains_legacy_reference(session_history_path, source_root):
                    references.append(str(session_history_path))
            for sidecar in sorted(history_root.rglob("*.snapshot.json")):
                self._progress_path(
                    progress_value,
                    100,
                    f"Scanning {label} snapshot sidecar",
                    sidecar,
                )
                if self._json_file_contains_legacy_reference(sidecar, source_root):
                    references.append(str(sidecar))

        backups_root = target_root / BACKUPS_SUBDIR
        if backups_root.exists():
            for sidecar in sorted(backups_root.rglob("*.backup.json")):
                self._progress_path(
                    progress_value,
                    100,
                    f"Scanning {label} backup sidecar",
                    sidecar,
                )
                if self._json_file_contains_legacy_reference(sidecar, source_root):
                    references.append(str(sidecar))

        return tuple(dict.fromkeys(references))

    def _database_contains_legacy_reference(self, db_path: Path, source_root: Path) -> bool:
        conn = sqlite3.connect(str(db_path))
        try:
            for sql in (SNAPSHOT_TABLE_SQL, BACKUP_TABLE_SQL, ENTRY_TABLE_SQL):
                try:
                    rows = conn.execute(sql).fetchall()
                except sqlite3.DatabaseError:
                    continue
                for row in rows:
                    for value in row[1:]:
                        if self._value_contains_legacy_reference(value, source_root):
                            return True
            return False
        finally:
            conn.close()

    def _json_file_contains_legacy_reference(self, path: Path, source_root: Path) -> bool:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return False
        return self._value_contains_legacy_reference(data, source_root)

    def _value_contains_legacy_reference(self, value: Any, source_root: Path) -> bool:
        if isinstance(value, dict):
            return any(
                self._value_contains_legacy_reference(item, source_root) for item in value.values()
            )
        if isinstance(value, list):
            return any(self._value_contains_legacy_reference(item, source_root) for item in value)
        if isinstance(value, str):
            return self._string_points_into_root(value, source_root)
        return False

    @staticmethod
    def _string_points_into_root(value: str, source_root: Path) -> bool:
        text = str(value or "").strip()
        if not text:
            return False
        try:
            candidate = Path(text)
        except Exception:
            return False
        if not candidate.is_absolute():
            return False
        try:
            candidate.resolve().relative_to(source_root.resolve())
        except Exception:
            return False
        return True

    @staticmethod
    def _complete_payload(
        *,
        action: str,
        source_root: Path | None,
        target_root: Path,
        copied_items: list[str],
        source_inventory_count: int,
        rewritten_files: list[str],
        verified_databases: list[str],
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": STORAGE_STATE_COMPLETE,
            "action": action,
            "app_name": APP_NAME,
            "target_root": str(target_root),
            "copied_items": copied_items,
            "source_inventory_count": int(source_inventory_count),
            "rewritten_files": rewritten_files,
            "verified_databases": verified_databases,
            "completed_at": StorageMigrationService._timestamp(),
        }
        if source_root is not None:
            payload["source_root"] = str(source_root)
        return payload

    def _copy_item(self, source: Path, target: Path, *, progress_value: int) -> None:
        if source.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            for child in sorted(source.iterdir()):
                if StorageMigrationService._is_transient_sqlite_companion(child):
                    continue
                self._copy_item(child, target / child.name, progress_value=progress_value)
            return
        if source.suffix.lower() == ".db":
            self._progress_path(progress_value, 100, "Copying storage database", source)
            StorageMigrationService._copy_sqlite_database(source, target)
            return
        self._progress_path(progress_value, 100, "Copying storage file", source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    @staticmethod
    def _copy_sqlite_database(source: Path, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            target.unlink()
        source_uri = f"{source.resolve().as_uri()}?mode=ro"
        source_conn = sqlite3.connect(source_uri, uri=True)
        target_conn = sqlite3.connect(str(target))
        try:
            source_conn.execute("PRAGMA busy_timeout = 5000")
            source_conn.backup(target_conn)
            target_conn.commit()
        finally:
            target_conn.close()
            source_conn.close()

    @classmethod
    def _is_transient_sqlite_companion(cls, path: Path) -> bool:
        name = path.name.lower()
        return any(name.endswith(f".db{suffix}") for suffix in cls.SQLITE_COMPANION_SUFFIXES)

    def _source_inventory(
        self,
        source_root: Path,
        copied_items: list[str],
        *,
        progress_value: int,
        label: str,
    ) -> tuple[str, ...]:
        inventory: list[str] = []
        for name in copied_items:
            item_root = source_root / name
            self._progress_path(progress_value, 100, f"Scanning {label} item", item_root)
            if item_root.is_dir():
                for path in sorted(item_root.rglob("*")):
                    if path.is_dir():
                        continue
                    self._progress_path(progress_value, 100, f"Scanning {label} file", path)
                    if self._is_transient_sqlite_companion(path):
                        continue
                    inventory.append(str(path.relative_to(source_root)))
            elif item_root.exists():
                self._progress_path(progress_value, 100, f"Scanning {label} file", item_root)
                if not self._is_transient_sqlite_companion(item_root):
                    inventory.append(str(item_root.relative_to(source_root)))
        return tuple(inventory)

    @staticmethod
    def _validate_stage_inventory(stage_root: Path, source_inventory: tuple[str, ...]) -> None:
        missing = [
            relative_path
            for relative_path in source_inventory
            if not (stage_root / relative_path).exists()
        ]
        if missing:
            preview = "\n".join(missing[:20])
            raise RuntimeError(
                "Migration staging did not copy all expected files.\n\n"
                f"Missing staged files:\n{preview}"
            )

    @staticmethod
    def _promote_stage_root(stage_root: Path, target_root: Path) -> None:
        if target_root.exists():
            if any(target_root.iterdir()):
                raise RuntimeError(
                    f"Preferred app-data root contains data and cannot be replaced safely: {target_root}"
                )
            target_root.rmdir()
        stage_root.rename(target_root)

    @staticmethod
    def _remove_empty_stage_container(stage_container: Path) -> None:
        try:
            if stage_container.exists() and not any(stage_container.iterdir()):
                stage_container.rmdir()
        except Exception:
            pass

    def _rewrite_target_storage(
        self,
        source_root: Path,
        target_root: Path,
        *,
        progress_value: int,
    ) -> tuple[str, ...]:
        rewritten: list[str] = []

        database_dir = target_root / DATABASE_SUBDIR
        if database_dir.exists():
            for db_path in sorted(database_dir.glob("*.db")):
                self._progress_path(progress_value, 100, "Rewriting storage database", db_path)
                self._rewrite_profile_database(db_path, source_root, target_root)
                rewritten.append(str(db_path))

        history_root = target_root / HISTORY_SUBDIR
        if history_root.exists():
            session_history_path = history_root / "session_history.json"
            if session_history_path.exists():
                self._progress_path(
                    progress_value,
                    100,
                    "Rewriting session history file",
                    session_history_path,
                )
                if self._rewrite_json_file(session_history_path, source_root, target_root):
                    rewritten.append(str(session_history_path))
            for sidecar in sorted(history_root.rglob("*.snapshot.json")):
                self._progress_path(progress_value, 100, "Rewriting snapshot sidecar", sidecar)
                if self._rewrite_json_file(sidecar, source_root, target_root):
                    rewritten.append(str(sidecar))

        backups_root = target_root / BACKUPS_SUBDIR
        if backups_root.exists():
            for sidecar in sorted(backups_root.rglob("*.backup.json")):
                self._progress_path(progress_value, 100, "Rewriting backup sidecar", sidecar)
                if self._rewrite_json_file(sidecar, source_root, target_root):
                    rewritten.append(str(sidecar))

        return tuple(rewritten)

    def _rewrite_profile_database(
        self, db_path: Path, source_root: Path, target_root: Path
    ) -> None:
        conn = sqlite3.connect(str(db_path))
        try:
            with conn:
                snapshot_rows = conn.execute(SNAPSHOT_TABLE_SQL).fetchall()
                for snapshot_id, snapshot_path, settings_json, manifest_json in snapshot_rows:
                    settings_state = self._loads(settings_json)
                    manifest = self._loads(manifest_json)
                    updated_settings = self._rewrite_json_value(
                        settings_state, source_root, target_root
                    )
                    updated_manifest = self._rewrite_json_value(manifest, source_root, target_root)
                    updated_path = self._rewrite_path_string(
                        snapshot_path, source_root, target_root
                    )
                    conn.execute(
                        """
                        UPDATE HistorySnapshots
                        SET db_snapshot_path=?, settings_json=?, manifest_json=?
                        WHERE id=?
                        """,
                        (
                            updated_path,
                            json.dumps(updated_settings),
                            json.dumps(updated_manifest),
                            int(snapshot_id),
                        ),
                    )

                backup_rows = conn.execute(BACKUP_TABLE_SQL).fetchall()
                for backup_id, backup_path, source_db_path, metadata_json in backup_rows:
                    metadata = self._loads(metadata_json)
                    updated_metadata = self._rewrite_json_value(metadata, source_root, target_root)
                    updated_path = self._rewrite_path_string(backup_path, source_root, target_root)
                    updated_source_db_path = self._rewrite_path_string(
                        source_db_path, source_root, target_root
                    )
                    conn.execute(
                        """
                        UPDATE HistoryBackups
                        SET backup_path=?, source_db_path=?, metadata_json=?
                        WHERE id=?
                        """,
                        (
                            updated_path,
                            updated_source_db_path,
                            json.dumps(updated_metadata),
                            int(backup_id),
                        ),
                    )

                entry_rows = conn.execute(ENTRY_TABLE_SQL).fetchall()
                for entry_id, payload_json, inverse_json, redo_json in entry_rows:
                    payload = self._rewrite_json_value(
                        self._loads(payload_json), source_root, target_root
                    )
                    inverse = self._rewrite_json_value(
                        self._loads(inverse_json), source_root, target_root
                    )
                    redo = self._rewrite_json_value(
                        self._loads(redo_json), source_root, target_root
                    )
                    conn.execute(
                        """
                        UPDATE HistoryEntries
                        SET payload_json=?, inverse_json=?, redo_json=?
                        WHERE id=?
                        """,
                        (
                            json.dumps(payload) if payload else None,
                            json.dumps(inverse) if inverse else None,
                            json.dumps(redo) if redo else None,
                            int(entry_id),
                        ),
                    )
        finally:
            conn.close()

    def _rewrite_settings_paths(self, source_root: Path | None, target_root: Path) -> None:
        if self.settings is None:
            return
        last_path = str(self.settings.value("db/last_path", "", str) or "").strip()
        if last_path and source_root is not None:
            updated = self._rewrite_path_string(last_path, source_root, target_root)
            if updated != last_path:
                self.settings.setValue("db/last_path", updated)
        database_dir = str(self.settings.value("paths/database_dir", "", str) or "").strip()
        if database_dir and source_root is not None:
            updated_database_dir = self._rewrite_path_string(database_dir, source_root, target_root)
            if updated_database_dir != database_dir:
                self.settings.setValue("paths/database_dir", updated_database_dir)
        self.settings.setValue(STORAGE_ACTIVE_DATA_ROOT_KEY, str(target_root.resolve()))
        if source_root is not None:
            self.settings.setValue(STORAGE_LEGACY_DATA_ROOT_KEY, str(source_root.resolve()))
        self.settings.sync()

    def _verify_target_databases(
        self,
        target_root: Path,
        *,
        progress_value: int,
    ) -> tuple[str, ...]:
        verified: list[str] = []
        for db_path in sorted(target_root.rglob("*.db")):
            self._progress_path(progress_value, 100, "Verifying storage database", db_path)
            conn = sqlite3.connect(str(db_path))
            try:
                row = conn.execute("PRAGMA integrity_check").fetchone()
            finally:
                conn.close()
            result = str(row[0] if row else "unknown")
            if result.lower() != "ok":
                raise RuntimeError(f"Integrity check failed for migrated database: {db_path}")
            verified.append(str(db_path))
        return tuple(verified)

    def _rewrite_json_file(self, path: Path, source_root: Path, target_root: Path) -> bool:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return False
        updated = self._rewrite_json_value(data, source_root, target_root)
        if updated == data:
            return False
        path.write_text(json.dumps(updated, indent=2, sort_keys=True), encoding="utf-8")
        return True

    def _rewrite_json_value(self, value: Any, source_root: Path, target_root: Path) -> Any:
        if isinstance(value, dict):
            return {
                str(key): self._rewrite_json_value(item, source_root, target_root)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [self._rewrite_json_value(item, source_root, target_root) for item in value]
        if isinstance(value, str):
            return self._rewrite_path_string(value, source_root, target_root)
        return value

    @staticmethod
    def _loads(raw: object) -> Any:
        if not raw:
            return {}
        try:
            return json.loads(str(raw))
        except Exception:
            return {}

    @staticmethod
    def _rewrite_path_string(value: object, source_root: Path, target_root: Path) -> str:
        text = str(value or "").strip()
        if not text:
            return text
        try:
            candidate = Path(text)
        except Exception:
            return text
        if not candidate.is_absolute():
            return text
        try:
            relative = candidate.resolve().relative_to(source_root.resolve())
        except Exception:
            return text
        return str((target_root / relative).resolve())

    @staticmethod
    def _write_journal(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

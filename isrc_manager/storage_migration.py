"""App-owned storage layout inspection and migration helpers."""

from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
    target_items: tuple[str, ...]
    migration_needed: bool
    target_ready: bool
    deferred: bool


@dataclass(slots=True)
class StorageMigrationResult:
    source_root: Path
    target_root: Path
    copied_items: tuple[str, ...]
    rewritten_files: tuple[str, ...]
    verified_databases: tuple[str, ...]
    journal_path: Path


class StorageMigrationService:
    """Detects and migrates legacy app-owned storage into the preferred layout."""

    SQLITE_COMPANION_SUFFIXES = ("-wal", "-shm", "-journal")

    def __init__(self, layout: AppStorageLayout, settings: QSettings | None = None):
        self.layout = layout
        self.settings = settings

    def inspect(self) -> StorageLayoutInspection:
        legacy_root = self._select_legacy_root()
        legacy_items = self._present_items(legacy_root) if legacy_root is not None else ()
        target_items = self._present_items(self.layout.preferred_data_root)
        deferred = self._settings_value(STORAGE_MIGRATION_STATE_KEY) == STORAGE_STATE_DEFERRED
        target_ready = bool(target_items)
        migration_needed = bool(
            legacy_root is not None
            and legacy_items
            and legacy_root != self.layout.preferred_data_root
            and not target_ready
        )
        return StorageLayoutInspection(
            layout=self.layout,
            legacy_root=legacy_root,
            legacy_items=legacy_items,
            target_items=target_items,
            migration_needed=migration_needed,
            target_ready=target_ready,
            deferred=deferred,
        )

    def defer(self, legacy_root: Path | None = None) -> None:
        if self.settings is None:
            return
        root = legacy_root or self._select_legacy_root()
        if root is None:
            return
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
        legacy_root = self._select_legacy_root()
        if legacy_root is not None:
            self.settings.setValue(STORAGE_LEGACY_DATA_ROOT_KEY, str(legacy_root.resolve()))
        self.settings.setValue(STORAGE_MIGRATION_STATE_KEY, STORAGE_STATE_COMPLETE)
        self.settings.sync()

    def mark_failed(self, legacy_root: Path | None = None) -> None:
        if self.settings is None:
            return
        root = legacy_root or self._select_legacy_root()
        if root is not None:
            self.settings.setValue(STORAGE_LEGACY_DATA_ROOT_KEY, str(root.resolve()))
            self.settings.setValue(STORAGE_ACTIVE_DATA_ROOT_KEY, str(root.resolve()))
        self.settings.setValue(STORAGE_MIGRATION_STATE_KEY, STORAGE_STATE_FAILED)
        self.settings.sync()

    def migrate(self) -> StorageMigrationResult:
        inspection = self.inspect()
        if inspection.legacy_root is None:
            raise RuntimeError("No legacy app-data root was detected.")
        source_root = inspection.legacy_root.resolve()
        target_root = self.layout.preferred_data_root.resolve()
        copied_items = [name for name in APP_OWNED_SUBDIRS if (source_root / name).exists()]
        if not copied_items:
            raise RuntimeError("No app-owned legacy storage was found to migrate.")

        source_inventory = self._source_inventory(source_root, copied_items)
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

        try:
            for name in copied_items:
                self._copy_item(source_root / name, stage_root / name)

            self._validate_stage_inventory(stage_root, source_inventory)

            rewritten_files = list(self._rewrite_target_storage(source_root, stage_root))
            verified = list(self._verify_target_databases(stage_root))
            self._promote_stage_root(stage_root, target_root)
            self._rewrite_settings_paths(source_root, target_root)
            self.mark_complete()
            payload = {
                "status": STORAGE_STATE_COMPLETE,
                "app_name": APP_NAME,
                "source_root": str(source_root),
                "target_root": str(target_root),
                "copied_items": copied_items,
                "source_inventory_count": len(source_inventory),
                "rewritten_files": rewritten_files,
                "verified_databases": verified,
                "completed_at": self._timestamp(),
            }
            self._write_journal(target_root / STORAGE_MIGRATION_JOURNAL_BASENAME, payload)
            self._remove_empty_stage_container(stage_container)
            return StorageMigrationResult(
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
            raise

    def load_journal(self) -> dict[str, Any]:
        for journal_path in (
            self.layout.preferred_data_root / STORAGE_MIGRATION_JOURNAL_BASENAME,
            self.layout.preferred_data_root.parent
            / f".{self.layout.preferred_data_root.name}_{STORAGE_MIGRATION_JOURNAL_BASENAME}",
        ):
            if not journal_path.exists():
                continue
            try:
                raw = json.loads(journal_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if isinstance(raw, dict):
                return raw
        return {}

    def _select_legacy_root(self) -> Path | None:
        configured = self._settings_value(STORAGE_LEGACY_DATA_ROOT_KEY)
        if configured:
            candidate = Path(configured).resolve()
            if candidate.exists():
                return candidate
        for candidate in self.layout.legacy_data_roots:
            resolved_candidate = Path(candidate).resolve()
            if self._present_items(resolved_candidate):
                return resolved_candidate
        return None

    @staticmethod
    def _present_items(root: Path | None) -> tuple[str, ...]:
        if root is None or not root.exists():
            return ()
        return tuple(name for name in APP_OWNED_SUBDIRS if (root / name).exists())

    def _settings_value(self, key: str) -> str:
        if self.settings is None:
            return ""
        return str(self.settings.value(key, "", str) or "").strip()

    @staticmethod
    def _copy_item(source: Path, target: Path) -> None:
        if source.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            for child in sorted(source.iterdir()):
                if StorageMigrationService._is_transient_sqlite_companion(child):
                    continue
                StorageMigrationService._copy_item(child, target / child.name)
            return
        if source.suffix.lower() == ".db":
            StorageMigrationService._copy_sqlite_database(source, target)
            return
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

    @classmethod
    def _source_inventory(cls, source_root: Path, copied_items: list[str]) -> tuple[str, ...]:
        inventory: list[str] = []
        for name in copied_items:
            item_root = source_root / name
            if item_root.is_dir():
                for path in sorted(item_root.rglob("*")):
                    if path.is_dir() or cls._is_transient_sqlite_companion(path):
                        continue
                    inventory.append(str(path.relative_to(source_root)))
            elif item_root.exists() and not cls._is_transient_sqlite_companion(item_root):
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
                    f"Preferred app-data root is not empty and cannot be replaced safely: {target_root}"
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

    def _rewrite_target_storage(self, source_root: Path, target_root: Path) -> tuple[str, ...]:
        rewritten: list[str] = []

        database_dir = target_root / DATABASE_SUBDIR
        if database_dir.exists():
            for db_path in sorted(database_dir.glob("*.db")):
                self._rewrite_profile_database(db_path, source_root, target_root)
                rewritten.append(str(db_path))

        history_root = target_root / HISTORY_SUBDIR
        if history_root.exists():
            session_history_path = history_root / "session_history.json"
            if session_history_path.exists() and self._rewrite_json_file(
                session_history_path, source_root, target_root
            ):
                rewritten.append(str(session_history_path))
            for sidecar in sorted(history_root.rglob("*.snapshot.json")):
                if self._rewrite_json_file(sidecar, source_root, target_root):
                    rewritten.append(str(sidecar))

        backups_root = target_root / BACKUPS_SUBDIR
        if backups_root.exists():
            for sidecar in sorted(backups_root.rglob("*.backup.json")):
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

    def _rewrite_settings_paths(self, source_root: Path, target_root: Path) -> None:
        if self.settings is None:
            return
        last_path = str(self.settings.value("db/last_path", "", str) or "").strip()
        if last_path:
            updated = self._rewrite_path_string(last_path, source_root, target_root)
            if updated != last_path:
                self.settings.setValue("db/last_path", updated)
        database_dir = str(self.settings.value("paths/database_dir", "", str) or "").strip()
        if database_dir:
            updated_database_dir = self._rewrite_path_string(database_dir, source_root, target_root)
            if updated_database_dir != database_dir:
                self.settings.setValue("paths/database_dir", updated_database_dir)
        self.settings.setValue(STORAGE_ACTIVE_DATA_ROOT_KEY, str(target_root.resolve()))
        self.settings.setValue(STORAGE_LEGACY_DATA_ROOT_KEY, str(source_root.resolve()))
        self.settings.sync()

    def _verify_target_databases(self, target_root: Path) -> tuple[str, ...]:
        verified: list[str] = []
        for db_path in sorted(target_root.rglob("*.db")):
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

    def _rewrite_json_value(self, value: Any, source_root: Path, target_root: Path):
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

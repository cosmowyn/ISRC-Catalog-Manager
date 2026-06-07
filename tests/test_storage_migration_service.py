import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PySide6.QtCore import QSettings

from isrc_manager.constants import APP_NAME
from isrc_manager.history import HistoryManager, SessionHistoryManager
from isrc_manager.paths import AppStorageLayout
from isrc_manager.services import DatabaseSchemaService, DatabaseSessionService
from isrc_manager.storage_migration import StorageLayoutInspection, StorageMigrationService


class StorageMigrationServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.source_root = self.root / "legacy-data"
        self.target_root = self.root / "preferred-data"
        self.settings_root = self.root / "settings"
        self.settings_root.mkdir(parents=True, exist_ok=True)
        self.settings_path = self.settings_root / "settings.ini"
        self.db_path = self.source_root / "Database" / "library.db"
        self.history_root = self.source_root / "history"
        self.backups_root = self.source_root / "backups"
        self.exports_root = self.source_root / "exports"
        self.track_media_root = self.source_root / "track_media"
        self.settings = QSettings(str(self.settings_path), QSettings.IniFormat)
        self.settings.setFallbacksEnabled(False)
        self.settings.setValue("db/last_path", str(self.db_path))
        self.settings.setValue("paths/database_dir", str(self.source_root / "Database"))
        self.settings.sync()
        self._build_legacy_storage()

    def _build_service(self, progress_reporter=None) -> StorageMigrationService:
        return StorageMigrationService(
            self._build_layout(),
            settings=self.settings,
            progress_reporter=progress_reporter,
        )

    def tearDown(self):
        self.settings.clear()
        self.settings.sync()
        self.tmpdir.cleanup()

    def _build_layout(self) -> AppStorageLayout:
        return AppStorageLayout(
            app_name=APP_NAME,
            portable=False,
            settings_root=self.settings_root,
            settings_path=self.settings_path,
            lock_path=self.settings_root / f"{APP_NAME}.lock",
            preferred_data_root=self.target_root,
            active_data_root=self.source_root,
            legacy_data_roots=(self.source_root,),
            database_dir=self.source_root / "Database",
            exports_dir=self.source_root / "exports",
            logs_dir=self.source_root / "logs",
            backups_dir=self.source_root / "backups",
            history_dir=self.source_root / "history",
            help_dir=self.source_root / "help",
        )

    def _build_inspection(self, **overrides) -> StorageLayoutInspection:
        values = {
            "layout": self._build_layout(),
            "legacy_root": None,
            "legacy_items": (),
            "preferred_items": (),
            "preferred_state": "empty",
            "migration_needed": False,
            "deferred": False,
            "journal_status": "",
            "journal_path": None,
            "journal": {},
            "journal_source_root": None,
            "stage_root": None,
            "conflict_items": (),
        }
        values.update(overrides)
        return StorageLayoutInspection(**values)

    def _build_legacy_storage(self) -> None:
        self.track_media_root.mkdir(parents=True, exist_ok=True)
        (self.track_media_root / "audio.wav").write_bytes(b"WAVE")
        self.exports_root.mkdir(parents=True, exist_ok=True)
        exported_file = self.exports_root / "catalog_export.txt"
        exported_file.write_text("legacy export", encoding="utf-8")

        session = DatabaseSessionService().open(self.db_path)
        try:
            schema = DatabaseSchemaService(session.conn, data_root=self.source_root)
            schema.init_db()
            schema.migrate_schema()
            history = HistoryManager(
                session.conn,
                self.settings,
                self.db_path,
                self.history_root,
                self.source_root,
                self.backups_root,
            )
            history.create_manual_snapshot("Legacy Manual Snapshot")

            before_state = history.capture_file_state(exported_file)
            exported_file.write_text("legacy export updated", encoding="utf-8")
            after_state = history.capture_file_state(exported_file)
            history.record_file_write_action(
                label="Export File",
                action_type="file.export",
                target_path=exported_file,
                before_state=before_state,
                after_state=after_state,
            )

            self.backups_root.mkdir(parents=True, exist_ok=True)
            backup_path = self.backups_root / "legacy_backup.db"
            shutil.copy2(self.db_path, backup_path)
            history.register_backup(
                backup_path,
                kind="manual",
                label="Legacy Backup",
                source_db_path=self.db_path,
                metadata={
                    "source_backup": str(backup_path),
                    "external_reference": str((self.root / "external-license.pdf").resolve()),
                },
            )
        finally:
            DatabaseSessionService.close(session.conn)

        session_history = SessionHistoryManager(self.history_root)
        session_history.record_profile_create(
            created_path=str(self.db_path),
            previous_path=str(self.db_path),
        )

    def test_migrate_copies_storage_and_rewrites_internal_paths(self):
        service = self._build_service()

        inspection = service.inspect()
        self.assertTrue(inspection.migration_needed)
        self.assertEqual(inspection.preferred_state, "empty")
        self.assertEqual(inspection.legacy_root, self.source_root.resolve())
        self.assertIn("Database", inspection.legacy_items)
        self.assertIn("history", inspection.legacy_items)

        result = service.migrate()
        self.assertEqual(result.action, "migrated")

        self.assertTrue((self.target_root / "Database" / "library.db").exists())
        self.assertTrue((self.source_root / "Database" / "library.db").exists())
        self.assertEqual(
            self.settings.value("db/last_path", "", str),
            str((self.target_root / "Database" / "library.db").resolve()),
        )
        self.assertEqual(
            self.settings.value("paths/database_dir", "", str),
            str((self.target_root / "Database").resolve()),
        )
        self.assertEqual(
            self.settings.value("storage/active_data_root", "", str),
            str(self.target_root.resolve()),
        )

        migrated_conn = (
            DatabaseSessionService().open(self.target_root / "Database" / "library.db").conn
        )
        try:
            snapshot_row = migrated_conn.execute(
                "SELECT db_snapshot_path, settings_json, manifest_json FROM HistorySnapshots LIMIT 1"
            ).fetchone()
            self.assertIsNotNone(snapshot_row)
            assert snapshot_row is not None
            self.assertTrue(
                str(Path(snapshot_row[0]).resolve()).startswith(str(self.target_root.resolve()))
            )
            self.assertIn(str(self.target_root.resolve()), str(snapshot_row[1]))
            self.assertIn(str(self.target_root.resolve()), str(snapshot_row[2]))
            self.assertNotIn(str(self.source_root.resolve()), str(snapshot_row[1]))
            self.assertNotIn(str(self.source_root.resolve()), str(snapshot_row[2]))

            backup_row = migrated_conn.execute(
                "SELECT backup_path, source_db_path, metadata_json FROM HistoryBackups LIMIT 1"
            ).fetchone()
            self.assertIsNotNone(backup_row)
            assert backup_row is not None
            self.assertTrue(
                str(Path(backup_row[0]).resolve()).startswith(str(self.target_root.resolve()))
            )
            self.assertTrue(
                str(Path(backup_row[1]).resolve()).startswith(str(self.target_root.resolve()))
            )
            self.assertIn(str(self.target_root.resolve()), str(backup_row[2]))
            self.assertIn(str((self.root / "external-license.pdf").resolve()), str(backup_row[2]))

            entry_rows = migrated_conn.execute(
                "SELECT payload_json, inverse_json, redo_json FROM HistoryEntries ORDER BY id"
            ).fetchall()
            serialized_entries = "\n".join(str(value or "") for row in entry_rows for value in row)
            self.assertIn(str(self.target_root.resolve()), serialized_entries)
            self.assertNotIn(str(self.source_root.resolve()), serialized_entries)
        finally:
            migrated_conn.close()

        session_history_path = self.target_root / "history" / "session_history.json"
        self.assertTrue(session_history_path.exists())
        session_history_text = session_history_path.read_text(encoding="utf-8")
        self.assertIn(str(self.target_root.resolve()), session_history_text)
        self.assertNotIn(str(self.source_root.resolve()), session_history_text)

        snapshot_sidecars = list((self.target_root / "history").rglob("*.snapshot.json"))
        self.assertTrue(snapshot_sidecars)
        self.assertTrue(
            any(
                str(self.target_root.resolve()) in sidecar.read_text(encoding="utf-8")
                for sidecar in snapshot_sidecars
            )
        )
        backup_sidecars = list((self.target_root / "backups").rglob("*.backup.json"))
        self.assertTrue(backup_sidecars)
        self.assertTrue(
            any(
                str(self.target_root.resolve()) in sidecar.read_text(encoding="utf-8")
                for sidecar in backup_sidecars
            )
        )

        journal = service.load_journal()
        self.assertEqual(journal.get("status"), "complete")
        self.assertEqual(
            Path(result.journal_path).resolve(),
            (self.target_root / "storage_migration.json").resolve(),
        )
        self.assertTrue(result.copied_items)
        self.assertTrue(result.rewritten_files)
        self.assertTrue(result.verified_databases)

    def test_migrate_reports_truthful_storage_progress_steps(self):
        progress_updates: list[tuple[int, int, str]] = []
        service = self._build_service(
            progress_reporter=lambda value, maximum, message: progress_updates.append(
                (value, maximum, message)
            )
        )

        service.migrate()

        messages = [message for _value, _maximum, message in progress_updates]
        self.assertIn("Checking existing app storage roots...", messages)
        self.assertIn("Validating preferred storage layout...", messages)
        self.assertIn("Inventorying legacy app-data files...", messages)
        self.assertTrue(any(message.startswith("Copying storage item:") for message in messages))
        self.assertTrue(
            any(
                message.startswith("Scanning legacy app-data file:")
                and str(self.db_path.resolve()) in message
                for message in messages
            )
        )
        self.assertTrue(
            any(
                message.startswith("Scanning preferred app-data root:")
                and str(self.target_root.resolve()) in message
                for message in messages
            )
        )
        self.assertTrue(
            any(
                message.startswith("Copying storage database:")
                and str(self.db_path.resolve()) in message
                for message in messages
            )
        )
        self.assertIn("Checking migrated profile databases...", messages)
        self.assertTrue(
            any(
                message.startswith("Running SQLite integrity test PRAGMA integrity_check")
                and str(self.db_path.name) in message
                for message in messages
            )
        )
        self.assertIn("Storage migration completed.", messages)
        values = [value for value, _maximum, _message in progress_updates]
        self.assertEqual(values, sorted(values))
        self.assertTrue(all(maximum == 100 for _value, maximum, _message in progress_updates))

    def test_preferred_root_noise_conflicts_and_json_rewrite_helpers(self):
        service = self._build_service()
        safe_root = self.root / "safe-target"
        (safe_root / "logs").mkdir(parents=True)
        (safe_root / "logs" / "startup.log").write_text("log", encoding="utf-8")
        (safe_root / "help").mkdir()
        (safe_root / "help" / "isrc_catalog_manager_help.html").write_text(
            "help",
            encoding="utf-8",
        )

        self.assertEqual(service._preferred_root_conflicts(safe_root), ())
        service._clear_safe_target_noise(safe_root)
        self.assertFalse(safe_root.exists())

        conflict_root = self.root / "conflict-target"
        conflict_root.mkdir()
        (conflict_root / "keep.db").write_bytes(b"db")
        self.assertEqual(service._preferred_root_conflicts(conflict_root), ("keep.db",))
        with self.assertRaisesRegex(RuntimeError, "conflicting content"):
            service._clear_safe_target_noise(conflict_root)

        rewritten = service._rewrite_json_value(
            {
                "db": str(self.source_root / "Database" / "library.db"),
                "items": [
                    str(self.source_root / "exports" / "catalog.csv"),
                    "relative/path",
                    3,
                ],
            },
            self.source_root,
            self.target_root,
        )
        self.assertEqual(
            rewritten["db"],
            str((self.target_root / "Database" / "library.db").resolve()),
        )
        self.assertEqual(
            rewritten["items"][0],
            str((self.target_root / "exports" / "catalog.csv").resolve()),
        )
        self.assertEqual(rewritten["items"][1:], ["relative/path", 3])

        json_path = self.root / "paths.json"
        json_path.write_text('{"path": "relative"}', encoding="utf-8")
        self.assertFalse(service._rewrite_json_file(json_path, self.source_root, self.target_root))
        json_path.write_text(
            '{"path": "' + str(self.source_root / "history" / "state.json") + '"}',
            encoding="utf-8",
        )
        self.assertTrue(service._rewrite_json_file(json_path, self.source_root, self.target_root))
        self.assertIn(str(self.target_root.resolve()), json_path.read_text(encoding="utf-8"))

        self.assertEqual(service._loads("not-json"), {})
        self.assertIsNone(service._journal_path_value(""))
        self.assertIsNotNone(service._journal_path_value(str(self.source_root)))

    def test_preferred_root_startup_validation_reports_lightweight_sqlite_commands(self):
        initial_service = self._build_service()
        initial_service.migrate()
        self.settings.setValue("storage/migration_state", "failed")
        self.settings.setValue("storage/legacy_data_root", str(self.source_root.resolve()))
        self.settings.setValue("storage/active_data_root", str(self.source_root.resolve()))
        self.settings.sync()

        progress_updates: list[tuple[int, int, str]] = []
        service = self._build_service(
            progress_reporter=lambda value, maximum, message: progress_updates.append(
                (value, maximum, message)
            )
        )

        inspection = service.inspect()

        self.assertEqual(inspection.preferred_state, "valid_complete")
        messages = [message for _value, _maximum, message in progress_updates]
        self.assertTrue(
            any(
                message.startswith("Found ") and "SQLite startup metadata test" in message
                for message in messages
            )
        )
        self.assertTrue(
            any("Running SQLite command PRAGMA schema_version" in message for message in messages)
        )
        self.assertTrue(
            any("Running SQLite command PRAGMA user_version" in message for message in messages)
        )
        self.assertTrue(
            any(
                "Running SQLite command SELECT name FROM sqlite_master LIMIT 1" in message
                for message in messages
            )
        )
        self.assertFalse(
            any("PRAGMA integrity_check" in message for message in messages),
            "normal startup preferred-root validation should not run full integrity checks",
        )
        values = [value for value, _maximum, _message in progress_updates]
        self.assertEqual(values, sorted(values))

    def test_migrate_copies_live_wal_backed_profile_database_safely(self):
        live_conn = sqlite3.connect(str(self.db_path))
        try:
            live_conn.execute("PRAGMA journal_mode=WAL")
            live_conn.execute("PRAGMA wal_autocheckpoint=0")
            live_conn.execute(
                "CREATE TABLE IF NOT EXISTS MigrationProof (id INTEGER PRIMARY KEY, value TEXT)"
            )
            live_conn.execute("DELETE FROM MigrationProof")
            live_conn.execute(
                "INSERT INTO MigrationProof(value) VALUES (?)",
                ("copied from wal-backed source",),
            )
            live_conn.commit()
            self.assertTrue(Path(f"{self.db_path}-wal").exists())

            service = self._build_service()
            service.migrate()
        finally:
            live_conn.close()

        migrated_conn = sqlite3.connect(str(self.target_root / "Database" / "library.db"))
        try:
            row = migrated_conn.execute(
                "SELECT value FROM MigrationProof ORDER BY id DESC LIMIT 1"
            ).fetchone()
        finally:
            migrated_conn.close()

        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row[0], "copied from wal-backed source")

    def test_migrate_adopts_verified_complete_preferred_root_with_stale_legacy_settings(self):
        initial_service = self._build_service()
        initial_result = initial_service.migrate()
        self.assertEqual(initial_result.action, "migrated")

        self.settings.setValue("storage/migration_state", "failed")
        self.settings.setValue("storage/legacy_data_root", str(self.source_root.resolve()))
        self.settings.setValue("storage/active_data_root", str(self.source_root.resolve()))
        self.settings.setValue("db/last_path", str(self.db_path.resolve()))
        self.settings.setValue("paths/database_dir", str((self.source_root / "Database").resolve()))
        self.settings.sync()

        service = self._build_service()
        inspection = service.inspect()
        self.assertEqual(inspection.preferred_state, "valid_complete")

        result = service.migrate()

        self.assertEqual(result.action, "adopted")
        self.assertEqual(
            self.settings.value("storage/active_data_root", "", str),
            str(self.target_root.resolve()),
        )
        self.assertEqual(
            self.settings.value("db/last_path", "", str),
            str((self.target_root / "Database" / "library.db").resolve()),
        )
        self.assertEqual(
            self.settings.value("paths/database_dir", "", str),
            str((self.target_root / "Database").resolve()),
        )

    def test_resume_from_failed_stage_promotes_preserved_stage_root(self):
        service = self._build_service()

        with mock.patch.object(
            StorageMigrationService,
            "_promote_stage_root",
            side_effect=RuntimeError("promotion blocked for test"),
        ):
            with self.assertRaisesRegex(RuntimeError, "promotion blocked for test"):
                service.migrate()

        journal = service.load_journal()
        stage_root = Path(str(journal.get("stage_root")))
        self.assertEqual(journal.get("status"), "failed")
        self.assertTrue(stage_root.exists())
        self.assertFalse(self.target_root.exists())

        resumed_service = self._build_service()
        with mock.patch.object(
            StorageMigrationService,
            "_copy_item",
            side_effect=AssertionError("resume should not recopy legacy files"),
        ):
            result = resumed_service.migrate()

        self.assertEqual(result.action, "resumed")
        self.assertTrue((self.target_root / "Database" / "library.db").exists())
        self.assertFalse(stage_root.exists())
        self.assertEqual(
            self.settings.value("storage/active_data_root", "", str),
            str(self.target_root.resolve()),
        )
        self.assertEqual(
            resumed_service.load_journal().get("status"),
            "complete",
        )

    def test_migrate_can_replace_safe_bootstrap_noise_in_preferred_root(self):
        (self.target_root / "logs").mkdir(parents=True, exist_ok=True)
        (self.target_root / "logs" / "bootstrap.log").write_text("bootstrap", encoding="utf-8")
        (self.target_root / "help").mkdir(parents=True, exist_ok=True)
        (self.target_root / "help" / "isrc_catalog_manager_help.html").write_text(
            "<html>help</html>",
            encoding="utf-8",
        )

        service = self._build_service()
        inspection = service.inspect()
        self.assertEqual(inspection.preferred_state, "safe_noise")

        result = service.migrate()

        self.assertEqual(result.action, "migrated")
        self.assertTrue((self.target_root / "Database" / "library.db").exists())
        self.assertFalse((self.target_root / "logs" / "bootstrap.log").exists())
        self.assertFalse((self.target_root / "help" / "isrc_catalog_manager_help.html").exists())

    def test_migrate_blocks_conflicting_nonempty_preferred_root(self):
        (self.target_root / "Database").mkdir(parents=True, exist_ok=True)
        (self.target_root / "Database" / "foreign.db").write_text("not managed", encoding="utf-8")

        service = self._build_service()
        inspection = service.inspect()
        self.assertEqual(inspection.preferred_state, "conflict")

        with self.assertRaisesRegex(RuntimeError, "conflicting content"):
            service.migrate()

        self.assertTrue((self.source_root / "Database" / "library.db").exists())
        self.assertEqual(
            self.settings.value("storage/active_data_root", "", str),
            "",
        )

    def test_storage_layout_inspection_properties_and_settings_noop_branches(self):
        service = StorageMigrationService(self._build_layout(), settings=None)
        inspection = service.inspect()

        self.assertEqual(inspection.target_items, inspection.preferred_items)
        self.assertFalse(inspection.target_ready)
        self.assertFalse(inspection.adopt_needed)
        self.assertFalse(inspection.resume_needed)

        service.defer()
        service.mark_complete()
        service.mark_failed()

        self.assertEqual(StorageMigrationService._journal_path_value(""), None)
        self.assertIn(
            "- (unknown)",
            StorageMigrationService._format_conflict_error(self.target_root, ()),
        )

    def test_storage_helper_branches_for_inventory_json_rewrites_and_safe_noise(self):
        service = self._build_service()
        missing_root = self.root / "missing"
        self.assertEqual(
            service._collect_inventory(missing_root, progress_value=1, label="missing"),
            (),
        )

        inventory_root = self.root / "inventory"
        inventory_root.mkdir()
        (inventory_root / "library.db").write_text("database", encoding="utf-8")
        (inventory_root / "library.db-wal").write_text("wal", encoding="utf-8")
        self.assertEqual(
            service._collect_inventory(inventory_root, progress_value=1, label="inventory"),
            ("library.db",),
        )

        source_root = self.root / "source-json"
        target_root = self.root / "target-json"
        source_root.mkdir()
        target_root.mkdir()
        inside_path = source_root / "Database" / "library.db"
        inside_path.parent.mkdir()
        inside_path.write_text("db", encoding="utf-8")
        payload = {
            "inside": str(inside_path),
            "list": [str(inside_path), str(self.root / "outside.txt"), "relative/path"],
            "number": 5,
        }
        self.assertTrue(service._value_contains_legacy_reference(payload, source_root))
        self.assertFalse(service._value_contains_legacy_reference("relative/path", source_root))
        self.assertEqual(
            service._rewrite_path_string(str(inside_path), source_root, target_root),
            str((target_root / "Database" / "library.db").resolve()),
        )
        self.assertEqual(
            service._rewrite_path_string("relative/path", source_root, target_root),
            "relative/path",
        )

        invalid_json = self.root / "invalid.json"
        invalid_json.write_text("{", encoding="utf-8")
        self.assertFalse(service._rewrite_json_file(invalid_json, source_root, target_root))
        unchanged_json = self.root / "unchanged.json"
        unchanged_json.write_text('{"path": "relative/path"}', encoding="utf-8")
        self.assertFalse(service._rewrite_json_file(unchanged_json, source_root, target_root))
        changed_json = self.root / "changed.json"
        changed_json.write_text(
            '{"path": "%s"}' % str(inside_path).replace("\\", "\\\\"),
            encoding="utf-8",
        )
        self.assertTrue(service._rewrite_json_file(changed_json, source_root, target_root))
        self.assertIn(str(target_root.resolve()), changed_json.read_text(encoding="utf-8"))

        safe_root = self.root / "safe-noise"
        (safe_root / "logs").mkdir(parents=True)
        (safe_root / "logs" / "startup.log").write_text("ok", encoding="utf-8")
        (safe_root / "help").mkdir()
        (safe_root / "help" / "isrc_catalog_manager_help.html").write_text(
            "help",
            encoding="utf-8",
        )
        service._clear_safe_target_noise(safe_root)
        self.assertFalse(safe_root.exists())

        conflict_root = self.root / "conflict-noise"
        conflict_root.mkdir()
        (conflict_root / "foreign.txt").write_text("conflict", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "foreign.txt"):
            service._clear_safe_target_noise(conflict_root)

    def test_storage_stage_and_progress_helpers_report_failures_without_side_effects(self):
        stage_root = self.root / "stage"
        stage_root.mkdir()
        (stage_root / "present.txt").write_text("present", encoding="utf-8")

        StorageMigrationService._validate_stage_inventory(stage_root, ("present.txt",))
        with self.assertRaisesRegex(RuntimeError, "missing.txt"):
            StorageMigrationService._validate_stage_inventory(
                stage_root,
                ("present.txt", "missing.txt"),
            )

        target_root = self.root / "occupied-target"
        target_root.mkdir()
        (target_root / "file.txt").write_text("occupied", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "contains data"):
            StorageMigrationService._promote_stage_root(stage_root, target_root)

        empty_container = self.root / "empty-container"
        empty_container.mkdir()
        StorageMigrationService._remove_empty_stage_container(empty_container)
        self.assertFalse(empty_container.exists())

        non_empty_container = self.root / "non-empty-container"
        non_empty_container.mkdir()
        (non_empty_container / "child").write_text("child", encoding="utf-8")
        StorageMigrationService._remove_empty_stage_container(non_empty_container)
        self.assertTrue(non_empty_container.exists())

        self.assertEqual(
            StorageMigrationService._database_verify_progress_value(
                10,
                20,
                database_index=1,
                database_total=0,
                step=1,
                steps_per_database=4,
            ),
            10,
        )
        self.assertEqual(
            StorageMigrationService._database_verify_progress_value(
                10,
                10,
                database_index=1,
                database_total=1,
                step=1,
                steps_per_database=4,
            ),
            10,
        )

    def test_defer_and_migration_entry_guardrails_cover_missing_sources(self):
        service = self._build_service()
        self.settings.setValue(
            "db/last_path",
            str((self.target_root / "Database" / "library.db").resolve()),
        )
        self.settings.setValue(
            "paths/database_dir",
            str((self.target_root / "Database").resolve()),
        )

        service.defer(self.source_root)

        self.assertEqual(
            self.settings.value("db/last_path", "", str),
            str((self.source_root / "Database" / "library.db").resolve()),
        )
        self.assertEqual(
            self.settings.value("paths/database_dir", "", str),
            str((self.source_root / "Database").resolve()),
        )
        self.assertEqual(self.settings.value("storage/migration_state", "", str), "deferred")

        no_legacy_layout = AppStorageLayout(
            app_name=APP_NAME,
            portable=False,
            settings_root=self.settings_root,
            settings_path=self.settings_path,
            lock_path=self.settings_root / f"{APP_NAME}.lock",
            preferred_data_root=self.target_root,
            active_data_root=self.target_root,
            legacy_data_roots=(),
            database_dir=self.target_root / "Database",
            exports_dir=self.target_root / "exports",
            logs_dir=self.target_root / "logs",
            backups_dir=self.target_root / "backups",
            history_dir=self.target_root / "history",
            help_dir=self.target_root / "help",
        )
        no_legacy_service = StorageMigrationService(no_legacy_layout, settings=self.settings)
        self.settings.setValue("storage/migration_state", "")
        self.settings.setValue("storage/legacy_data_root", "")
        no_legacy_service.defer()
        self.assertEqual(self.settings.value("storage/migration_state", "", str), "")

        with mock.patch.object(
            service,
            "inspect",
            return_value=self._build_inspection(
                preferred_state="resumable_stage",
                stage_root=self.root / "missing-stage",
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "staged migration folder is missing"):
                service.migrate()

        with mock.patch.object(
            service,
            "inspect",
            return_value=self._build_inspection(legacy_root=None),
        ):
            with self.assertRaisesRegex(RuntimeError, "No legacy app-data root"):
                service.migrate()

        empty_legacy_root = self.root / "empty-legacy"
        empty_legacy_root.mkdir()
        with mock.patch.object(
            service,
            "inspect",
            return_value=self._build_inspection(
                legacy_root=empty_legacy_root,
                legacy_items=(),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "No app-owned legacy storage"):
                service.migrate()

    def test_journal_loading_and_preferred_validation_failure_branches(self):
        service = self._build_service()
        self.target_root.mkdir(parents=True)
        target_journal = self.target_root / "storage_migration.json"
        target_journal.write_text("{", encoding="utf-8")
        fallback_journal = self.target_root.parent / ".preferred-data_storage_migration.json"
        fallback_journal.write_text('{"status": "complete"}', encoding="utf-8")

        journal, journal_path = service._load_journal_details()

        self.assertEqual(journal, {"status": "complete"})
        self.assertEqual(journal_path, fallback_journal)
        target_journal.write_text("[]", encoding="utf-8")
        fallback_journal.unlink()
        self.assertEqual(service._load_journal_details(), ({}, None))

        preferred_db = self.target_root / "Database" / "library.db"
        preferred_db.parent.mkdir()
        sqlite3.connect(str(preferred_db)).close()

        self.assertFalse(
            service._preferred_root_valid(
                self.target_root,
                self.source_root,
                ("Database",),
                {"status": "complete", "target_root": str(self.root / "other-target")},
                ("Database",),
            )
        )
        with mock.patch.object(
            service,
            "_verify_target_databases",
            side_effect=RuntimeError("metadata unavailable"),
        ):
            self.assertFalse(
                service._preferred_root_valid(
                    self.target_root,
                    self.source_root,
                    ("Database",),
                    {},
                    ("Database",),
                )
            )
        with mock.patch.object(
            service,
            "_find_legacy_references",
            return_value=(str(preferred_db),),
        ):
            self.assertFalse(
                service._preferred_root_valid(
                    self.target_root,
                    self.source_root,
                    ("Database",),
                    {},
                    ("Database",),
                )
            )
        with mock.patch.object(
            service,
            "_find_legacy_references",
            side_effect=RuntimeError("scan failed"),
        ):
            self.assertFalse(
                service._preferred_root_valid(
                    self.target_root,
                    self.source_root,
                    ("Database",),
                    {},
                    ("Database",),
                )
            )

        self.assertEqual(
            StorageMigrationService._required_source_backed_items(
                legacy_items=("Database", "Database", "logs"),
                journal={},
                preferred_items=(),
            ),
            ("Database",),
        )
        self.assertEqual(
            StorageMigrationService._required_source_backed_items(
                legacy_items=(),
                journal={"copied_items": ["Database", 3, "logs", "Database"]},
                preferred_items=(),
            ),
            ("Database",),
        )
        self.assertEqual(
            StorageMigrationService._required_source_backed_items(
                legacy_items=(),
                journal={},
                preferred_items=("exports", "exports", "logs"),
            ),
            ("exports",),
        )
        self.assertEqual(
            service._preferred_root_conflicts(
                self.root / "missing-target",
                progress_value=1,
            ),
            (),
        )

    def test_resume_stage_branches_cover_inventory_mismatch_conflict_and_no_source_activation(
        self,
    ):
        service = self._build_service()

        mismatch_stage = self.root / "mismatch-stage"
        mismatch_stage.mkdir()
        (mismatch_stage / "only-file.txt").write_text("stage", encoding="utf-8")
        mismatch_inspection = self._build_inspection(
            preferred_state="resumable_stage",
            stage_root=mismatch_stage,
            journal={"source_inventory_count": 2},
        )
        with self.assertRaisesRegex(RuntimeError, "incomplete"):
            service._resume_migration_stage(mismatch_inspection, None, self.target_root)

        conflict_target = self.root / "conflict-resume-target"
        conflict_target.mkdir()
        (conflict_target / "foreign.txt").write_text("conflict", encoding="utf-8")
        conflict_stage = self.root / "conflict-stage"
        conflict_db = conflict_stage / "Database" / "library.db"
        conflict_db.parent.mkdir(parents=True)
        sqlite3.connect(str(conflict_db)).close()
        conflict_inspection = self._build_inspection(
            preferred_state="resumable_stage",
            stage_root=conflict_stage,
            journal={"source_inventory_count": 1, "copied_items": ["Database"]},
        )
        with self.assertRaisesRegex(RuntimeError, "foreign.txt"):
            service._resume_migration_stage(conflict_inspection, None, conflict_target)

        success_container = self.root / "resume-container"
        success_stage = success_container / self.target_root.name
        success_db = success_stage / "Database" / "library.db"
        success_db.parent.mkdir(parents=True)
        sqlite3.connect(str(success_db)).close()
        success_inspection = self._build_inspection(
            preferred_state="resumable_stage",
            stage_root=success_stage,
            journal={"source_inventory_count": 1, "copied_items": ["Database"]},
        )

        result = service._resume_migration_stage(success_inspection, None, self.target_root)

        self.assertEqual(result.action, "resumed")
        self.assertEqual(result.source_root, self.target_root.resolve())
        self.assertTrue((self.target_root / "Database" / "library.db").exists())
        self.assertFalse(success_container.exists())
        self.assertEqual(
            self.settings.value("storage/active_data_root", "", str),
            str(self.target_root.resolve()),
        )

    def test_storage_reference_sqlite_and_progress_edge_helpers(self):
        progress_messages: list[str] = []
        service = StorageMigrationService(
            self._build_layout(),
            settings=None,
            progress_reporter=lambda _value, _maximum, message: progress_messages.append(message),
        )
        reported_events: list[tuple[tuple, dict]] = []
        reporting_service = StorageMigrationService(
            self._build_layout(),
            reporter=lambda *args, **kwargs: reported_events.append((args, kwargs)),
        )
        reporting_service._report("storage.test", "message", level="unknown", path=self.db_path)
        self.assertEqual(reported_events[0][0], ("storage.test", "message"))
        self.assertEqual(reported_events[0][1]["level"], 20)

        def raising_progress(_value, _maximum, _message):
            raise RuntimeError("progress sink failed")

        StorageMigrationService(
            self._build_layout(),
            progress_reporter=raising_progress,
        )._progress(1, 2, "ignored")

        self.assertEqual(
            service._find_legacy_references(
                None,
                self.target_root,
                progress_value=1,
                label="target",
            ),
            (),
        )
        reference_root = self.root / "reference-target"
        (reference_root / "history").mkdir(parents=True)
        (reference_root / "backups").mkdir()
        (reference_root / "history" / "session_history.json").write_text(
            json.dumps({"path": str(self.source_root / "Database" / "library.db")}),
            encoding="utf-8",
        )
        (reference_root / "history" / "manual.snapshot.json").write_text(
            json.dumps({"path": str(self.source_root / "history" / "snap.db")}),
            encoding="utf-8",
        )
        (reference_root / "backups" / "manual.backup.json").write_text(
            json.dumps({"path": str(self.source_root / "backups" / "backup.db")}),
            encoding="utf-8",
        )
        references = service._find_legacy_references(
            self.source_root,
            reference_root,
            progress_value=1,
            label="target",
        )
        self.assertEqual(len(references), 3)
        self.assertEqual(
            service._verify_target_databases(
                self.root / "no-databases",
                progress_value=3,
            ),
            (),
        )
        self.assertTrue(
            any(message.startswith("No storage databases found") for message in progress_messages)
        )
        service._activate_target_root(self.target_root)

        plain_db = self.root / "plain.db"
        sqlite3.connect(str(plain_db)).close()
        self.assertFalse(service._database_contains_legacy_reference(plain_db, self.source_root))
        self.assertTrue(service._database_contains_legacy_reference(self.db_path, self.source_root))

        target_db = self.root / "target-existing.db"
        sqlite3.connect(str(target_db)).close()
        source_db = self.root / "source-copy.db"
        source_conn = sqlite3.connect(str(source_db))
        try:
            source_conn.execute("CREATE TABLE CopyProof(value TEXT)")
            source_conn.execute("INSERT INTO CopyProof(value) VALUES ('fresh')")
            source_conn.commit()
        finally:
            source_conn.close()

        StorageMigrationService._copy_sqlite_database(source_db, target_db)
        copied_conn = sqlite3.connect(str(target_db))
        try:
            self.assertEqual(
                copied_conn.execute("SELECT value FROM CopyProof").fetchone()[0], "fresh"
            )
        finally:
            copied_conn.close()

        integrity_db = self.root / "integrity.db"
        sqlite3.connect(str(integrity_db)).close()
        with mock.patch.object(
            service,
            "_run_integrity_check_with_progress",
            return_value=("not ok",),
        ):
            with self.assertRaisesRegex(RuntimeError, "Integrity check failed"):
                service._verify_target_databases(
                    integrity_db.parent,
                    progress_value=10,
                    progress_end=12,
                )

        self.assertEqual(
            service._adoption_inventory_count(
                None,
                [],
                {"source_inventory_count": "not-an-int"},
                progress_value=1,
            ),
            0,
        )
        self.assertGreater(
            service._adoption_inventory_count(
                self.source_root,
                ["Database"],
                {},
                progress_value=1,
            ),
            0,
        )
        self.assertEqual(
            service._resolve_source_root(
                self._build_inspection(journal_source_root=self.source_root)
            ),
            self.source_root.resolve(),
        )
        self.assertEqual(service._present_items(None), ())
        self.assertEqual(
            service._source_inventory(
                self.source_root,
                ["catalog-path.txt"],
                progress_value=1,
                label="legacy",
            ),
            (),
        )
        single_file = self.source_root / "catalog-path.txt"
        single_file.write_text("file", encoding="utf-8")
        self.assertEqual(
            service._source_inventory(
                self.source_root,
                ["catalog-path.txt"],
                progress_value=1,
                label="legacy",
            ),
            ("catalog-path.txt",),
        )
        service._clear_safe_target_noise(self.root / "missing-safe-root")
        settings_service = self._build_service()
        settings_service.mark_complete()
        self.assertEqual(
            self.settings.value("storage/legacy_data_root", "", str),
            str(self.source_root.resolve()),
        )
        settings_service.mark_failed(self.source_root)
        self.assertEqual(self.settings.value("storage/migration_state", "", str), "failed")
        settings_service._rewrite_settings_paths(None, self.target_root)
        self.assertEqual(
            self.settings.value("storage/active_data_root", "", str),
            str(self.target_root.resolve()),
        )
        service._rewrite_settings_paths(self.source_root, self.target_root)

        stage_root = self.root / "promote-stage"
        target_root = self.root / "empty-promote-target"
        stage_root.mkdir()
        target_root.mkdir()
        (stage_root / "file.txt").write_text("promoted", encoding="utf-8")
        StorageMigrationService._promote_stage_root(stage_root, target_root)
        self.assertEqual((target_root / "file.txt").read_text(encoding="utf-8"), "promoted")

        with mock.patch.object(Path, "rmdir", side_effect=OSError):
            StorageMigrationService._remove_empty_stage_container(self.root / "non-removable")

        with mock.patch.object(Path, "resolve", side_effect=RuntimeError("bad path")):
            self.assertEqual(StorageMigrationService._display_path(Path("broken")), "broken")
            self.assertIsNone(StorageMigrationService._journal_path_value("broken"))
            self.assertFalse(
                StorageMigrationService._string_points_into_root(
                    str(self.source_root / "Database"),
                    self.source_root,
                )
            )
        self.assertTrue(StorageMigrationService._is_safe_noise_path(Path()))
        self.assertFalse(StorageMigrationService._string_points_into_root("", self.source_root))
        self.assertEqual(StorageMigrationService._loads(None), {})


if __name__ == "__main__":
    unittest.main()

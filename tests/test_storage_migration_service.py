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
from isrc_manager.storage_migration import StorageMigrationService


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

    def _build_service(self) -> StorageMigrationService:
        return StorageMigrationService(self._build_layout(), settings=self.settings)

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


if __name__ == "__main__":
    unittest.main()

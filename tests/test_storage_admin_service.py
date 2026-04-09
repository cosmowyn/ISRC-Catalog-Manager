import json
import shutil
import tempfile
import unittest
from pathlib import Path

try:
    from PySide6.QtCore import QSettings
except ImportError as exc:  # pragma: no cover - environment-specific fallback
    QSettings = None
    QT_IMPORT_ERROR = exc
else:
    QT_IMPORT_ERROR = None

from isrc_manager.history import HistoryManager, SessionHistoryManager
from isrc_manager.paths import resolve_app_storage_layout
from isrc_manager.services import DatabaseSchemaService, DatabaseSessionService
from isrc_manager.storage_admin import (
    STATUS_DELETED_PROFILE,
    STATUS_IN_USE,
    STATUS_ORPHANED,
    ApplicationStorageAdminService,
)


class StorageAdminServiceTests(unittest.TestCase):
    def setUp(self):
        if QSettings is None:
            raise unittest.SkipTest(f"PySide6 QtCore unavailable: {QT_IMPORT_ERROR}")
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.settings_path = self.root / "settings.ini"
        self.settings = QSettings(str(self.settings_path), QSettings.IniFormat)
        self.settings.setFallbacksEnabled(False)
        self.layout = resolve_app_storage_layout(
            settings=self.settings,
            active_data_root=self.root,
        )
        for directory in self.layout.iter_standard_dirs():
            directory.mkdir(parents=True, exist_ok=True)

        self.db_path = self.layout.database_dir / "library.db"
        self.deleted_profile_path = self.layout.database_dir / "removed.db"

        session = DatabaseSessionService().open(self.db_path)
        self.conn = session.conn
        schema = DatabaseSchemaService(self.conn, data_root=self.layout.data_root)
        schema.init_db()
        schema.migrate_schema()
        self.history = HistoryManager(
            self.conn,
            self.settings,
            self.db_path,
            self.layout.history_dir,
            self.layout.data_root,
            self.layout.backups_dir,
        )
        self.service = ApplicationStorageAdminService(self.layout)

        self.conn.execute(
            """
            INSERT INTO Parties(legal_name, display_name, artist_name, party_type)
            VALUES ('Test Artist', 'Test Artist', 'Test Artist', 'artist')
            """
        )
        artist_id = int(self.conn.execute("SELECT id FROM Parties").fetchone()[0])

        self.live_audio_path = self.layout.data_root / "track_media" / "live_audio.wav"
        self.live_audio_path.write_bytes(b"live-audio")
        self.orphan_audio_path = self.layout.data_root / "track_media" / "orphan_audio.wav"
        self.orphan_audio_path.write_bytes(b"orphan-audio")
        self.conn.execute(
            """
            INSERT INTO Tracks (
                isrc,
                isrc_compact,
                track_title,
                main_artist_party_id,
                audio_file_path,
                audio_file_storage_mode,
                audio_file_size_bytes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "NLABC2500001",
                "NLABC2500001",
                "Live Track",
                artist_id,
                str(self.live_audio_path.relative_to(self.layout.data_root)),
                "managed_file",
                self.live_audio_path.stat().st_size,
            ),
        )
        self.conn.commit()

        self.protected_snapshot = self.history.create_manual_snapshot("Protected Snapshot")
        self.loose_snapshot = self.history.capture_snapshot(kind="manual", label="Loose Snapshot")

        self.registered_backup_path = self.layout.backups_dir / "registered_backup.db"
        shutil.copy2(self.db_path, self.registered_backup_path)
        self.history.register_backup(
            self.registered_backup_path,
            kind="manual",
            label="Registered Backup",
            source_db_path=self.db_path,
        )

        self.deleted_history_dir = self.layout.history_dir / "snapshots" / "removed"
        self.deleted_history_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.db_path, self.deleted_history_dir / "deleted_snapshot.db")

        self.orphan_backup_path = self.layout.backups_dir / "removed_profile_backup.db"
        shutil.copy2(self.db_path, self.orphan_backup_path)
        self.orphan_backup_path.with_suffix(".db.backup.json").write_text(
            json.dumps({"source_db_path": str(self.deleted_profile_path)}),
            encoding="utf-8",
        )

        shutil.copy2(self.db_path, self.deleted_profile_path)
        session_history = SessionHistoryManager(self.layout.history_dir)
        deleted_snapshot_path = session_history.capture_profile_snapshot(
            self.deleted_profile_path,
            kind="profile_remove",
        )
        session_history.record_profile_remove(
            deleted_path=str(self.deleted_profile_path),
            current_path=str(self.db_path),
            fallback_path=str(self.db_path),
            deleting_current=False,
            snapshot_path=deleted_snapshot_path,
        )
        self.deleted_profile_path.unlink()

    def tearDown(self):
        self.settings.clear()
        DatabaseSessionService.close(self.conn)
        self.tmpdir.cleanup()

    def test_inspect_reports_application_wide_totals_and_current_profile_usage(self):
        audit = self.service.inspect(current_db_path=self.db_path)

        self.assertGreater(audit.summary.total_app_bytes, 0)
        self.assertGreater(audit.summary.current_profile_bytes, 0)
        self.assertGreater(audit.summary.reclaimable_bytes, 0)
        self.assertEqual(audit.summary.current_profile_name, self.db_path.name)

    def test_inspect_classifies_in_use_orphaned_and_deleted_profile_artifacts(self):
        audit = self.service.inspect(current_db_path=self.db_path)
        items_by_path = {item.path: item for item in audit.items}

        live_item = items_by_path[str(self.live_audio_path)]
        orphan_item = items_by_path[str(self.orphan_audio_path)]
        deleted_tree_item = items_by_path[str(self.deleted_history_dir)]
        backup_item = items_by_path[str(self.orphan_backup_path)]
        session_item = next(item for item in audit.items if item.category_key == "session_snapshot")
        protected_snapshot_item = next(
            item
            for item in audit.items
            if item.category_key == "history_snapshot"
            and item.status_key == STATUS_IN_USE
            and item.path == self.protected_snapshot.db_snapshot_path
        )

        self.assertEqual(live_item.status_key, STATUS_IN_USE)
        self.assertTrue(live_item.warning_required)
        self.assertEqual(orphan_item.status_key, STATUS_ORPHANED)
        self.assertEqual(deleted_tree_item.status_key, STATUS_DELETED_PROFILE)
        self.assertEqual(backup_item.status_key, STATUS_DELETED_PROFILE)
        self.assertEqual(session_item.status_key, STATUS_DELETED_PROFILE)
        self.assertTrue(session_item.warning_required)
        self.assertEqual(protected_snapshot_item.status_key, STATUS_IN_USE)
        self.assertTrue(protected_snapshot_item.warning_required)

    def test_cleanup_of_orphaned_items_does_not_create_new_history_or_session_entries(self):
        audit = self.service.inspect(current_db_path=self.db_path)
        orphan_keys = [
            item.item_key
            for item in audit.items
            if item.path in {str(self.orphan_audio_path), str(self.deleted_history_dir)}
        ]
        history_entries_before = self.conn.execute(
            "SELECT COUNT(*) FROM HistoryEntries"
        ).fetchone()[0]
        session_entries_before = len(SessionHistoryManager(self.layout.history_dir).list_entries())

        result = self.service.cleanup_selected(orphan_keys, current_db_path=self.db_path)

        history_entries_after = self.conn.execute("SELECT COUNT(*) FROM HistoryEntries").fetchone()[
            0
        ]
        session_entries_after = len(SessionHistoryManager(self.layout.history_dir).list_entries())

        self.assertEqual(len(result.removed_item_keys), 2)
        self.assertFalse(self.orphan_audio_path.exists())
        self.assertFalse(self.deleted_history_dir.exists())
        self.assertEqual(history_entries_after, history_entries_before)
        self.assertEqual(session_entries_after, session_entries_before)

    def test_cleanup_of_protected_snapshot_purges_dependent_history_without_new_entries(self):
        audit = self.service.inspect(current_db_path=self.db_path)
        protected_snapshot_item = next(
            item
            for item in audit.items
            if item.category_key == "history_snapshot"
            and item.path == self.protected_snapshot.db_snapshot_path
        )
        history_entries_before = self.conn.execute(
            "SELECT COUNT(*) FROM HistoryEntries"
        ).fetchone()[0]

        result = self.service.cleanup_selected(
            [protected_snapshot_item.item_key],
            current_db_path=self.db_path,
            allow_warning_deletes=True,
        )

        history_entries_after = self.conn.execute("SELECT COUNT(*) FROM HistoryEntries").fetchone()[
            0
        ]
        self.assertGreaterEqual(len(result.removed_history_entry_ids), 1)
        self.assertLess(history_entries_after, history_entries_before)
        self.assertFalse(Path(self.protected_snapshot.db_snapshot_path).exists())
        self.assertIsNone(self.history.fetch_snapshot(self.protected_snapshot.snapshot_id))

    def test_cleanup_of_deleted_profile_session_snapshot_prunes_session_history(self):
        audit = self.service.inspect(current_db_path=self.db_path)
        session_item = next(item for item in audit.items if item.category_key == "session_snapshot")
        session_history = SessionHistoryManager(self.layout.history_dir)
        session_entries_before = len(session_history.list_entries())

        result = self.service.cleanup_selected(
            [session_item.item_key],
            current_db_path=self.db_path,
            allow_warning_deletes=True,
        )

        refreshed_history = SessionHistoryManager(self.layout.history_dir)
        session_entries_after = len(refreshed_history.list_entries())
        self.assertGreaterEqual(len(result.removed_session_entry_ids), 1)
        self.assertLess(session_entries_after, session_entries_before)
        self.assertFalse(Path(session_item.path).exists())


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import QSettings

from isrc_manager.history import HistoryManager
from isrc_manager.services import (
    DatabaseSchemaService,
    DatabaseSessionService,
    SettingsMutationService,
    SettingsReadService,
    TrackCreatePayload,
    TrackService,
    TrackUpdatePayload,
)


class HistoryManagerTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.db_path = self.root / "Database" / "library.db"
        self.settings_path = self.root / "settings.ini"
        self.history_root = self.root / "history"
        self.settings = QSettings(str(self.settings_path), QSettings.IniFormat)
        self.settings.setFallbacksEnabled(False)

        self.session_service = DatabaseSessionService()
        self.session = self.session_service.open(self.db_path)
        self.conn = self.session.conn
        self.schema = DatabaseSchemaService(self.conn)
        self.schema.init_db()
        self.schema.migrate_schema()

        self.track_service = TrackService(self.conn)
        self.settings_mutations = SettingsMutationService(self.conn, self.settings)
        self.settings_reads = SettingsReadService(self.conn)
        self.history = HistoryManager(self.conn, self.settings, self.db_path, self.history_root)

    def tearDown(self):
        self.settings.clear()
        self.session_service.close(self.conn)
        self.tmpdir.cleanup()

    def _create_track(self, *, title: str = "First Song", artist_name: str = "Main Artist") -> int:
        return self.track_service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-00001",
                track_title=title,
                artist_name=artist_name,
                additional_artists=["Guest Artist"],
                album_title="Debut Album",
                release_date="2026-03-13",
                track_length_sec=245,
                iswc=None,
                upc=None,
                genre="Pop",
            )
        )

    def test_setting_change_undo_and_redo_are_persistent(self):
        self.settings_mutations.set_isrc_prefix("NLABC")
        self.history.record_setting_change(
            key="isrc_prefix",
            label="Set ISRC Prefix: NLABC",
            before_value="",
            after_value="NLABC",
        )

        self.assertEqual(self.settings_reads.load_isrc_prefix(), "NLABC")
        self.assertTrue(self.history.can_undo())

        self.history.undo()
        self.assertEqual(self.settings_reads.load_isrc_prefix(), "")

        self.history.redo()
        self.assertEqual(self.settings_reads.load_isrc_prefix(), "NLABC")

    def test_track_create_delete_and_redo_work_through_history(self):
        track_id = self._create_track()
        self.history.record_track_create(
            track_id=track_id,
            cleanup_artist_names=["Main Artist", "Guest Artist"],
            cleanup_album_titles=["Debut Album"],
        )

        self.assertIsNotNone(self.track_service.fetch_track_snapshot(track_id))

        self.history.undo()
        self.assertIsNone(self.track_service.fetch_track_snapshot(track_id))

        self.history.redo()
        snapshot = self.track_service.fetch_track_snapshot(track_id)
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.track_title, "First Song")

        before_delete = self.track_service.fetch_track_snapshot(track_id)
        self.track_service.delete_track(track_id)
        self.history.record_track_delete(before_snapshot=before_delete)

        self.assertIsNone(self.track_service.fetch_track_snapshot(track_id))

        self.history.undo()
        self.assertIsNotNone(self.track_service.fetch_track_snapshot(track_id))

        self.history.redo()
        self.assertIsNone(self.track_service.fetch_track_snapshot(track_id))

    def test_track_update_and_snapshot_restore_round_trip(self):
        track_id = self._create_track()
        self.history.record_track_create(
            track_id=track_id,
            cleanup_artist_names=["Main Artist", "Guest Artist"],
            cleanup_album_titles=["Debut Album"],
        )

        before_update = self.track_service.fetch_track_snapshot(track_id)
        self.track_service.update_track(
            TrackUpdatePayload(
                track_id=track_id,
                isrc="NL-ABC-26-00002",
                track_title="Updated Song",
                artist_name="New Artist",
                additional_artists=["Guest Artist"],
                album_title="New Album",
                release_date="2026-03-14",
                track_length_sec=300,
                iswc=None,
                upc=None,
                genre="Electronic",
            )
        )
        self.history.record_track_update(
            before_snapshot=before_update,
            cleanup_artist_names=["New Artist"],
            cleanup_album_titles=["New Album"],
        )

        self.assertEqual(self.track_service.fetch_track_snapshot(track_id).track_title, "Updated Song")

        self.history.undo()
        self.assertEqual(self.track_service.fetch_track_snapshot(track_id).track_title, "First Song")

        self.history.redo()
        self.assertEqual(self.track_service.fetch_track_snapshot(track_id).track_title, "Updated Song")

        snapshot = self.history.create_manual_snapshot("Before manual restore")

        self.track_service.update_track(
            TrackUpdatePayload(
                track_id=track_id,
                isrc="NL-ABC-26-00002",
                track_title="Changed Again",
                artist_name="New Artist",
                additional_artists=["Guest Artist"],
                album_title="New Album",
                release_date="2026-03-14",
                track_length_sec=300,
                iswc=None,
                upc=None,
                genre="Electronic",
            )
        )
        self.assertEqual(self.track_service.fetch_track_snapshot(track_id).track_title, "Changed Again")

        self.history.restore_snapshot_as_action(snapshot.snapshot_id)
        self.assertEqual(self.track_service.fetch_track_snapshot(track_id).track_title, "Updated Song")

        self.history.undo()
        self.assertEqual(self.track_service.fetch_track_snapshot(track_id).track_title, "Changed Again")

        self.history.redo()
        self.assertEqual(self.track_service.fetch_track_snapshot(track_id).track_title, "Updated Song")


if __name__ == "__main__":
    unittest.main()

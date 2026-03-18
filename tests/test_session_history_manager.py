import tempfile
import unittest
from pathlib import Path

from isrc_manager.history import SessionHistoryManager


class _FakeApp:
    def __init__(self, current_db_path: str):
        self.current_db_path = str(current_db_path)
        self.conn = object()
        self.opened_paths = []
        self.reloaded_paths = []

    def _session_history_open_profile(self, path: str):
        self.current_db_path = str(path)
        self.conn = object()
        self.opened_paths.append(str(path))

    def _session_history_reload_profiles(self, select_path: str | None = None):
        self.reloaded_paths.append(select_path)

    def _session_history_delete_profile(self, path: str):
        target = Path(path)
        if self.current_db_path == str(target):
            self.conn = None
        target.unlink(missing_ok=True)


class SessionHistoryManagerTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.history = SessionHistoryManager(self.root / "history")
        self.primary = self.root / "Database" / "library.db"
        self.secondary = self.root / "Database" / "alt.db"
        self.created = self.root / "Database" / "new_profile.db"
        self.primary.parent.mkdir(parents=True, exist_ok=True)
        self.primary.write_text("primary", encoding="utf-8")
        self.secondary.write_text("secondary", encoding="utf-8")

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_profile_switch_undo_and_redo(self):
        app = _FakeApp(self.primary)
        self.history.record_profile_switch(from_path=str(self.primary), to_path=str(self.secondary))

        self.assertTrue(self.history.can_undo())
        self.history.undo(app)
        self.assertEqual(app.current_db_path, str(self.primary))

        self.history.redo(app)
        self.assertEqual(app.current_db_path, str(self.secondary))

    def test_profile_create_undo_and_redo_restore_file(self):
        self.created.write_text("created", encoding="utf-8")
        app = _FakeApp(self.created)

        self.history.record_profile_create(
            created_path=str(self.created), previous_path=str(self.primary)
        )

        self.history.undo(app)
        self.assertFalse(self.created.exists())
        self.assertEqual(app.current_db_path, str(self.primary))

        self.history.redo(app)
        self.assertTrue(self.created.exists())
        self.assertEqual(self.created.read_text(encoding="utf-8"), "created")
        self.assertEqual(app.current_db_path, str(self.created))

    def test_profile_remove_current_undo_and_redo_restore_file(self):
        app = _FakeApp(self.secondary)
        snapshot_path = self.history.capture_profile_snapshot(self.primary, kind="profile_remove")
        self.primary.unlink()

        self.history.record_profile_remove(
            deleted_path=str(self.primary),
            current_path=str(self.primary),
            fallback_path=str(self.secondary),
            deleting_current=True,
            snapshot_path=snapshot_path,
        )

        self.history.undo(app)
        self.assertTrue(self.primary.exists())
        self.assertEqual(self.primary.read_text(encoding="utf-8"), "primary")
        self.assertEqual(app.current_db_path, str(self.primary))

        self.history.redo(app)
        self.assertFalse(self.primary.exists())
        self.assertEqual(app.current_db_path, str(self.secondary))

    def test_branching_after_undo_supersedes_session_redo(self):
        app = _FakeApp(self.primary)
        first = self.history.record_profile_switch(from_path=str(self.primary), to_path=str(self.secondary))
        second = self.history.record_profile_switch(from_path=str(self.secondary), to_path=str(self.primary))

        self.history.undo(app)
        self.assertEqual(self.history.get_default_redo_entry().entry_id, second.entry_id)

        third = self.history.record_profile_switch(from_path=str(self.secondary), to_path=str(self.created))

        self.assertEqual(third.parent_id, first.entry_id)
        self.assertIsNone(self.history.get_default_redo_entry())
        self.assertEqual(self.history.fetch_entry(second.entry_id).status, "superseded")


if __name__ == "__main__":
    unittest.main()

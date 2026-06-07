import json
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

    def test_empty_history_noop_and_missing_snapshot_paths(self):
        app = _FakeApp(self.primary)

        self.assertFalse(self.history.can_undo())
        self.assertFalse(self.history.can_redo())
        self.assertIsNone(self.history.describe_undo())
        self.assertIsNone(self.history.describe_redo())
        self.assertIsNone(self.history.undo(app))
        self.assertIsNone(self.history.redo(app, entry_id=999))
        self.assertEqual(self.history.remove_entries([]), ())
        self.assertEqual(self.history.remove_entries([999]), ())
        self.assertIsNone(
            self.history.record_profile_switch(
                from_path=str(self.primary),
                to_path=str(self.primary),
            )
        )
        with self.assertRaises(FileNotFoundError):
            self.history.capture_profile_snapshot(self.root / "missing.db", kind="missing")

    def test_redo_selection_skips_nonreversible_and_rejects_wrong_parent(self):
        app = _FakeApp(self.primary)
        first = self.history.record_profile_switch(
            from_path=str(self.primary),
            to_path=str(self.secondary),
        )
        second = self.history.record_profile_switch(
            from_path=str(self.secondary),
            to_path=str(self.created),
        )

        self.history.undo(app)
        self.history.undo(app)
        self.assertIsNone(self.history.get_current_entry_id())
        self.assertEqual(self.history.get_default_redo_entry().entry_id, first.entry_id)

        first_row = next(
            row for row in self.history._state["entries"] if row["entry_id"] == first.entry_id
        )
        first_row["reversible"] = False
        self.assertIsNone(self.history.get_default_redo_entry())
        first_row["reversible"] = True

        with self.assertRaisesRegex(ValueError, "not redoable"):
            self.history.redo(app, entry_id=second.entry_id)

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

    def test_profile_remove_payload_variants_reload_profiles(self):
        app = _FakeApp(self.primary)
        snapshot_path = self.history.capture_profile_snapshot(self.primary, kind="profile_remove")

        self.history._apply_payload(
            app,
            "profile.remove",
            {
                "snapshot_path": snapshot_path,
                "deleted_path": str(self.created),
                "restore_open_path": "",
            },
            direction="undo",
        )
        self.assertTrue(self.created.exists())
        self.assertEqual(app.reloaded_paths, [None])

        self.created.write_text("remove me", encoding="utf-8")
        self.history._apply_payload(
            app,
            "profile.remove",
            {
                "deleted_path": str(self.created),
                "deleting_current": False,
                "current_path": str(self.primary),
            },
            direction="redo",
        )
        self.assertFalse(self.created.exists())
        self.assertEqual(app.reloaded_paths[-1], str(self.primary))

        with self.assertRaisesRegex(ValueError, "Unknown session history action"):
            self.history._apply_payload(app, "profile.unknown", {}, direction="redo")

    def test_branching_after_undo_supersedes_session_redo(self):
        app = _FakeApp(self.primary)
        first = self.history.record_profile_switch(
            from_path=str(self.primary), to_path=str(self.secondary)
        )
        second = self.history.record_profile_switch(
            from_path=str(self.secondary), to_path=str(self.primary)
        )

        self.history.undo(app)
        self.assertEqual(self.history.get_default_redo_entry().entry_id, second.entry_id)

        third = self.history.record_profile_switch(
            from_path=str(self.secondary), to_path=str(self.created)
        )

        self.assertEqual(third.parent_id, first.entry_id)
        self.assertIsNone(self.history.get_default_redo_entry())
        self.assertEqual(self.history.fetch_entry(second.entry_id).status, "superseded")

    def test_state_invariants_snapshot_references_and_bundle_companions(self):
        raw_state = {
            "next_entry_id": 4,
            "current_entry_id": 999,
            "entries": [
                {
                    "entry_id": 1,
                    "parent_id": None,
                    "created_at": "2026-06-07T10:00:00",
                    "label": "Root",
                    "action_type": "profile.create",
                    "entity_type": "Profile",
                    "entity_id": str(self.primary),
                    "reversible": True,
                    "strategy": "session",
                    "payload": {"created_path": str(self.primary)},
                    "inverse_payload": {
                        "snapshot_path": str(self.root / "snap-root.db"),
                        "created_path": str(self.primary),
                    },
                    "redo_payload": {},
                    "status": "applied",
                    "visible_in_history": True,
                },
                {
                    "entry_id": 2,
                    "parent_id": 1,
                    "created_at": "2026-06-07T10:01:00",
                    "label": "Child",
                    "action_type": "profile.remove",
                    "entity_type": "Profile",
                    "entity_id": str(self.secondary),
                    "reversible": True,
                    "strategy": "session",
                    "payload": {"deleted_path": str(self.secondary)},
                    "inverse_payload": {
                        "snapshot_path": str(self.root / "snap-child.db"),
                        "deleted_path": str(self.secondary),
                    },
                    "redo_payload": {
                        "snapshot_path": str(self.root / "snap-child-redo.db"),
                    },
                    "status": "applied",
                    "visible_in_history": True,
                },
            ],
        }
        self.history.state_path.write_text(json.dumps(raw_state), encoding="utf-8")

        repaired = SessionHistoryManager(self.root / "history")

        self.assertEqual(repaired.get_current_entry_id(), 2)
        references = repaired.snapshot_references()
        self.assertEqual(
            {(reference["source_name"], reference["profile_path"]) for reference in references},
            {
                ("inverse_payload", str(self.primary)),
                ("inverse_payload", str(self.secondary)),
                ("redo_payload", str(self.secondary)),
            },
        )
        self.assertEqual(
            repaired.remove_entries_for_snapshot(self.root / "snap-child.db"),
            (2,),
        )
        self.assertEqual(repaired.get_current_entry_id(), 1)

        with self.assertRaises(FileNotFoundError):
            SessionHistoryManager._restore_profile_bundle(
                self.root / "missing-snapshot.db",
                self.created,
            )

        self.primary.with_name(self.primary.name + "-wal").write_text("wal", encoding="utf-8")
        self.primary.with_name(self.primary.name + "-shm").write_text("shm", encoding="utf-8")
        snapshot_path = self.history.capture_profile_snapshot(self.primary, kind="companions")
        target = self.root / "Database" / "restored.db"
        target.write_text("stale", encoding="utf-8")
        target_wal = target.with_name(target.name + "-wal")
        target_shm = target.with_name(target.name + "-shm")
        target_wal.write_text("stale-wal", encoding="utf-8")
        target_shm.write_text("stale-shm", encoding="utf-8")

        SessionHistoryManager._restore_profile_bundle(snapshot_path, target)

        self.assertEqual(target.read_text(encoding="utf-8"), "primary")
        self.assertEqual(target_wal.read_text(encoding="utf-8"), "wal")
        self.assertEqual(target_shm.read_text(encoding="utf-8"), "shm")


if __name__ == "__main__":
    unittest.main()

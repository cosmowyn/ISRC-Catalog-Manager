import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from isrc_manager.history import SessionHistoryManager
from isrc_manager.services.db_access import SQLiteConnectionFactory


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


class _DeleteThenFailApp(_FakeApp):
    def _session_history_delete_profile(self, path: str):
        super()._session_history_delete_profile(path)
        raise OSError("simulated delete callback failure")


class _OpenFailApp(_FakeApp):
    def _session_history_open_profile(self, path: str):
        raise OSError("simulated profile open failure")


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

    def test_profile_remove_undo_refuses_to_overwrite_new_profile_and_is_retryable(self):
        app = _FakeApp(self.secondary)
        snapshot_path = self.history.capture_profile_snapshot(self.primary, kind="profile_remove")
        self.primary.unlink()
        entry = self.history.record_profile_remove(
            deleted_path=str(self.primary),
            current_path=str(self.primary),
            fallback_path=str(self.secondary),
            deleting_current=True,
            snapshot_path=snapshot_path,
        )
        self.primary.write_text("unrelated replacement", encoding="utf-8")

        with self.assertRaisesRegex(RuntimeError, "occupies the target path"):
            self.history.undo(app)

        self.assertEqual(self.primary.read_text(encoding="utf-8"), "unrelated replacement")
        self.assertEqual(self.history.get_current_entry_id(), entry.entry_id)
        self.assertEqual(self.history.fetch_entry(entry.entry_id).status, "applied")
        self.assertTrue(self.history.can_undo())
        reloaded = SessionHistoryManager(self.history.history_root)
        self.assertEqual(reloaded.get_current_entry_id(), entry.entry_id)
        self.assertEqual(reloaded.fetch_entry(entry.entry_id).status, "applied")

        self.primary.unlink()
        self.history.undo(app)
        self.assertEqual(self.primary.read_text(encoding="utf-8"), "primary")

    def test_profile_remove_is_not_recorded_until_target_is_absent(self):
        snapshot_path = self.history.capture_profile_snapshot(self.primary, kind="profile_remove")

        with self.assertRaisesRegex(RuntimeError, "became occupied"):
            self.history.record_profile_remove(
                deleted_path=str(self.primary),
                current_path=str(self.primary),
                fallback_path=str(self.secondary),
                deleting_current=True,
                snapshot_path=snapshot_path,
            )

        self.assertEqual(self.primary.read_text(encoding="utf-8"), "primary")
        self.assertEqual(self.history.list_entries(), [])

    def test_profile_remove_redo_refuses_modified_restore_and_is_retryable(self):
        app = _FakeApp(self.secondary)
        snapshot_path = self.history.capture_profile_snapshot(self.primary, kind="profile_remove")
        self.primary.unlink()
        entry = self.history.record_profile_remove(
            deleted_path=str(self.primary),
            current_path=str(self.primary),
            fallback_path=str(self.secondary),
            deleting_current=True,
            snapshot_path=snapshot_path,
        )
        self.history.undo(app)
        self.primary.write_text("modified after undo", encoding="utf-8")

        with self.assertRaisesRegex(RuntimeError, "changed after this history action"):
            self.history.redo(app)

        self.assertEqual(self.primary.read_text(encoding="utf-8"), "modified after undo")
        self.assertIsNone(self.history.get_current_entry_id())
        self.assertEqual(self.history.fetch_entry(entry.entry_id).status, "undone")
        self.assertTrue(self.history.can_redo())

        self.primary.write_text("primary", encoding="utf-8")
        self.history.redo(app)
        self.assertFalse(self.primary.exists())

    def test_profile_create_conflicts_do_not_overwrite_later_files(self):
        self.created.write_text("created", encoding="utf-8")
        app = _FakeApp(self.created)
        entry = self.history.record_profile_create(
            created_path=str(self.created),
            previous_path=str(self.primary),
        )
        self.created.write_text("edited after creation", encoding="utf-8")

        with self.assertRaisesRegex(RuntimeError, "changed after this history action"):
            self.history.undo(app)
        self.assertEqual(self.created.read_text(encoding="utf-8"), "edited after creation")
        self.assertEqual(self.history.get_current_entry_id(), entry.entry_id)

        self.created.write_text("created", encoding="utf-8")
        self.history.undo(app)
        self.created.write_text("replacement after undo", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "occupies the target path"):
            self.history.redo(app)
        self.assertEqual(self.created.read_text(encoding="utf-8"), "replacement after undo")
        self.assertTrue(self.history.can_redo())

        self.created.unlink()
        self.history.redo(app)
        self.assertEqual(self.created.read_text(encoding="utf-8"), "created")

    def test_logical_match_does_not_authorize_newer_profile_data(self):
        profile = self.root / "Database" / "logical-profile.db"
        conn = sqlite3.connect(profile)
        conn.execute("CREATE TABLE records(id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute("INSERT INTO records(id, value) VALUES (1, 'captured')")
        conn.commit()
        conn.close()
        history = SessionHistoryManager(
            self.root / "logical-history",
            connection_factory=SQLiteConnectionFactory(),
        )
        entry = history.record_profile_create(
            created_path=str(profile),
            previous_path=str(self.primary),
        )
        conn = sqlite3.connect(profile)
        conn.execute("UPDATE records SET value = 'newer' WHERE id = 1")
        conn.commit()
        conn.close()

        with self.assertRaisesRegex(RuntimeError, "changed after this history action"):
            history.undo(_FakeApp(str(profile)))

        conn = sqlite3.connect(profile)
        self.assertEqual(conn.execute("SELECT value FROM records").fetchone(), ("newer",))
        conn.close()
        self.assertEqual(history.get_current_entry_id(), entry.entry_id)
        self.assertEqual(history.fetch_entry(entry.entry_id).status, "applied")

    def test_logically_authorized_delete_restores_exact_live_bytes_when_save_fails(self):
        profile = self.root / "Database" / "logical-rollback.db"
        conn = sqlite3.connect(profile)
        conn.execute("CREATE TABLE records(id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute("INSERT INTO records(id, value) VALUES (1, 'captured')")
        conn.commit()
        conn.close()
        history = SessionHistoryManager(
            self.root / "logical-rollback-history",
            connection_factory=SQLiteConnectionFactory(),
        )
        entry = history.record_profile_create(
            created_path=str(profile),
            previous_path=str(self.primary),
        )
        conn = sqlite3.connect(profile)
        conn.execute("CREATE TABLE HistoryEntries(entry_id INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO HistoryEntries(entry_id) VALUES (77)")
        conn.commit()
        conn.close()
        exact_live_bytes = profile.read_bytes()
        original_save = history._save_state
        save_calls = 0

        def fail_replay_save():
            nonlocal save_calls
            save_calls += 1
            if save_calls == 2:
                raise OSError("simulated replay state save failure")
            original_save()

        app = _FakeApp(str(profile))
        with (
            mock.patch.object(history, "_save_state", side_effect=fail_replay_save),
            self.assertRaisesRegex(RuntimeError, "profile change was rolled back"),
        ):
            history.undo(app)

        self.assertEqual(profile.read_bytes(), exact_live_bytes)
        conn = sqlite3.connect(profile)
        self.assertEqual(conn.execute("SELECT entry_id FROM HistoryEntries").fetchone(), (77,))
        conn.close()
        self.assertEqual(app.current_db_path, str(profile))
        self.assertEqual(history.get_current_entry_id(), entry.entry_id)
        self.assertEqual(history.fetch_entry(entry.entry_id).status, "applied")

    def test_binary_profile_bundle_round_trips_exact_bytes(self):
        expected = {
            "": b"\x00SQLCipher\xffprofile\x00",
            "-wal": b"\x00encrypted-wal\xfe",
            "-shm": b"\x00encrypted-shm\xfd",
        }
        for suffix, content in expected.items():
            Path(f"{self.created}{suffix}").write_bytes(content)
        app = _FakeApp(self.created)
        self.history.record_profile_create(
            created_path=str(self.created),
            previous_path=str(self.primary),
        )

        self.history.undo(app)
        for suffix in expected:
            self.assertFalse(Path(f"{self.created}{suffix}").exists())

        self.history.redo(app)
        for suffix, content in expected.items():
            self.assertEqual(Path(f"{self.created}{suffix}").read_bytes(), content)

    def test_snapshot_main_tampering_fails_before_profile_restore(self):
        app = _FakeApp(self.secondary)
        snapshot_path = self.history.capture_profile_snapshot(self.primary, kind="profile_remove")
        self.primary.unlink()
        entry = self.history.record_profile_remove(
            deleted_path=str(self.primary),
            current_path=str(self.primary),
            fallback_path=str(self.secondary),
            deleting_current=True,
            snapshot_path=snapshot_path,
        )
        Path(snapshot_path).write_text("tampered", encoding="utf-8")

        with self.assertRaisesRegex(RuntimeError, "integrity check"):
            self.history.undo(app)

        self.assertFalse(self.primary.exists())
        self.assertEqual(self.history.get_current_entry_id(), entry.entry_id)
        self.assertEqual(self.history.fetch_entry(entry.entry_id).status, "applied")

    def test_missing_snapshot_main_fails_before_profile_restore(self):
        app = _FakeApp(self.secondary)
        snapshot_path = self.history.capture_profile_snapshot(self.primary, kind="profile_remove")
        self.primary.unlink()
        entry = self.history.record_profile_remove(
            deleted_path=str(self.primary),
            current_path=str(self.primary),
            fallback_path=str(self.secondary),
            deleting_current=True,
            snapshot_path=snapshot_path,
        )
        Path(snapshot_path).unlink()

        with self.assertRaises(FileNotFoundError):
            self.history.undo(app)

        self.assertFalse(self.primary.exists())
        self.assertEqual(self.history.get_current_entry_id(), entry.entry_id)
        self.assertEqual(self.history.fetch_entry(entry.entry_id).status, "applied")

    def test_missing_or_tampered_snapshot_companion_fails_before_restore(self):
        for tamper_mode in ("missing", "changed"):
            with self.subTest(tamper_mode=tamper_mode):
                case_root = self.root / tamper_mode
                history = SessionHistoryManager(case_root / "history")
                source = case_root / "Database" / "source.db"
                fallback = case_root / "Database" / "fallback.db"
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_bytes(b"main")
                Path(f"{source}-wal").write_bytes(b"wal")
                fallback.write_bytes(b"fallback")
                snapshot_path = history.capture_profile_snapshot(source, kind="profile_remove")
                source.unlink()
                entry = history.record_profile_remove(
                    deleted_path=str(source),
                    current_path=str(source),
                    fallback_path=str(fallback),
                    deleting_current=True,
                    snapshot_path=snapshot_path,
                )
                snapshot_wal = Path(f"{snapshot_path}-wal")
                if tamper_mode == "missing":
                    snapshot_wal.unlink()
                else:
                    snapshot_wal.write_bytes(b"changed")

                with self.assertRaisesRegex(RuntimeError, "integrity check"):
                    history.undo(_FakeApp(str(fallback)))

                self.assertFalse(source.exists())
                self.assertFalse(Path(f"{source}-wal").exists())
                self.assertEqual(history.get_current_entry_id(), entry.entry_id)
                self.assertEqual(history.fetch_entry(entry.entry_id).status, "applied")

    def test_payload_snapshot_path_outside_fixed_root_is_rejected(self):
        app = _FakeApp(self.secondary)
        snapshot_path = self.history.capture_profile_snapshot(self.primary, kind="profile_remove")
        self.primary.unlink()
        entry = self.history.record_profile_remove(
            deleted_path=str(self.primary),
            current_path=str(self.primary),
            fallback_path=str(self.secondary),
            deleting_current=True,
            snapshot_path=snapshot_path,
        )
        outside = self.root / "outside.db"
        outside.write_text("primary", encoding="utf-8")
        entry.inverse_payload["snapshot_path"] = str(outside)

        with self.assertRaisesRegex(ValueError, "direct children"):
            self.history.undo(app)

        self.assertFalse(self.primary.exists())
        self.assertEqual(self.history.get_current_entry_id(), entry.entry_id)
        self.assertEqual(self.history.fetch_entry(entry.entry_id).status, "applied")

    def test_payload_snapshot_symlink_is_rejected_before_restore(self):
        app = _FakeApp(self.secondary)
        snapshot_path = self.history.capture_profile_snapshot(self.primary, kind="profile_remove")
        self.primary.unlink()
        entry = self.history.record_profile_remove(
            deleted_path=str(self.primary),
            current_path=str(self.primary),
            fallback_path=str(self.secondary),
            deleting_current=True,
            snapshot_path=snapshot_path,
        )
        outside = self.root / "outside.db"
        outside.write_text("primary", encoding="utf-8")
        Path(snapshot_path).unlink()
        Path(snapshot_path).symlink_to(outside)

        with self.assertRaisesRegex(ValueError, "symbolic links"):
            self.history.undo(app)

        self.assertFalse(self.primary.exists())
        self.assertEqual(self.history.get_current_entry_id(), entry.entry_id)

    def test_symlinked_snapshot_root_is_rejected_before_restore(self):
        app = _FakeApp(self.secondary)
        snapshot_path = self.history.capture_profile_snapshot(self.primary, kind="profile_remove")
        self.primary.unlink()
        entry = self.history.record_profile_remove(
            deleted_path=str(self.primary),
            current_path=str(self.primary),
            fallback_path=str(self.secondary),
            deleting_current=True,
            snapshot_path=snapshot_path,
        )
        outside_root = self.root / "outside-snapshots"
        outside_root.mkdir()
        outside_snapshot = outside_root / Path(snapshot_path).name
        Path(snapshot_path).replace(outside_snapshot)
        self.history.snapshot_dir.rmdir()
        self.history.snapshot_dir.symlink_to(outside_root, target_is_directory=True)

        with self.assertRaisesRegex(ValueError, "storage cannot use symbolic links"):
            self.history.undo(app)

        self.assertFalse(self.primary.exists())
        self.assertEqual(self.history.get_current_entry_id(), entry.entry_id)

    def test_legacy_profile_history_without_inventory_fails_safe(self):
        app = _FakeApp(self.secondary)
        snapshot_path = self.history.capture_profile_snapshot(self.primary, kind="profile_remove")
        self.primary.unlink()
        entry = self.history.record_profile_remove(
            deleted_path=str(self.primary),
            current_path=str(self.primary),
            fallback_path=str(self.secondary),
            deleting_current=True,
            snapshot_path=snapshot_path,
        )
        entry.inverse_payload.pop("snapshot_inventory")

        with self.assertRaisesRegex(RuntimeError, "cannot be replayed safely"):
            self.history.undo(app)

        self.assertFalse(self.primary.exists())
        self.assertEqual(self.history.get_current_entry_id(), entry.entry_id)

    def test_authorized_snapshot_rewrite_can_refresh_recorded_inventory(self):
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
        Path(snapshot_path).write_bytes(b"authorised encrypted rewrite")

        refreshed = self.history.refresh_snapshot_inventories(
            [self.root / "unreferenced.db", snapshot_path]
        )

        self.assertEqual(refreshed, 1)
        self.history.undo(app)
        self.assertEqual(self.primary.read_bytes(), b"authorised encrypted rewrite")

    def test_callback_failures_roll_back_files_and_leave_history_retryable(self):
        self.created.write_text("created", encoding="utf-8")
        create_entry = self.history.record_profile_create(
            created_path=str(self.created),
            previous_path=str(self.primary),
        )

        with self.assertRaisesRegex(OSError, "delete callback failure"):
            self.history.undo(_DeleteThenFailApp(str(self.created)))

        self.assertEqual(self.created.read_text(encoding="utf-8"), "created")
        self.assertEqual(self.history.get_current_entry_id(), create_entry.entry_id)
        self.assertEqual(self.history.fetch_entry(create_entry.entry_id).status, "applied")

        separate_history = SessionHistoryManager(self.root / "remove-history")
        snapshot_path = separate_history.capture_profile_snapshot(
            self.primary,
            kind="profile_remove",
        )
        self.primary.unlink()
        remove_entry = separate_history.record_profile_remove(
            deleted_path=str(self.primary),
            current_path=str(self.primary),
            fallback_path=str(self.secondary),
            deleting_current=True,
            snapshot_path=snapshot_path,
        )

        with self.assertRaisesRegex(OSError, "profile open failure"):
            separate_history.undo(_OpenFailApp(str(self.secondary)))

        self.assertFalse(self.primary.exists())
        self.assertEqual(separate_history.get_current_entry_id(), remove_entry.entry_id)
        self.assertEqual(separate_history.fetch_entry(remove_entry.entry_id).status, "applied")
        self.assertTrue(separate_history.can_undo())

    def test_profile_remove_record_failure_restores_bundle_without_history_entry(self):
        Path(f"{self.primary}-wal").write_bytes(b"wal")
        Path(f"{self.primary}-shm").write_bytes(b"shm")
        expected = {
            suffix: Path(f"{self.primary}{suffix}").read_bytes() for suffix in ("", "-wal", "-shm")
        }
        snapshot_path = self.history.capture_profile_snapshot(self.primary, kind="profile_remove")
        for suffix in expected:
            Path(f"{self.primary}{suffix}").unlink()

        with (
            mock.patch.object(
                self.history,
                "_save_state",
                side_effect=OSError("simulated session history save failure"),
            ),
            self.assertRaisesRegex(OSError, "session history save failure"),
        ):
            self.history.record_profile_remove(
                deleted_path=str(self.primary),
                current_path=str(self.primary),
                fallback_path=str(self.secondary),
                deleting_current=True,
                snapshot_path=snapshot_path,
            )

        for suffix, content in expected.items():
            self.assertEqual(Path(f"{self.primary}{suffix}").read_bytes(), content)
        self.assertEqual(self.history._state["entries"], [])
        self.assertIsNone(self.history.get_current_entry_id())
        reloaded = SessionHistoryManager(self.history.history_root)
        self.assertEqual(reloaded.list_entries(), [])

    def test_undo_state_save_failure_compensates_profile_change(self):
        self.created.write_text("created", encoding="utf-8")
        entry = self.history.record_profile_create(
            created_path=str(self.created),
            previous_path=str(self.primary),
        )
        app = _FakeApp(str(self.created))
        original_save = self.history._save_state
        save_calls = 0

        def _fail_replay_save():
            nonlocal save_calls
            save_calls += 1
            if save_calls == 2:
                raise OSError("simulated replay state save failure")
            original_save()

        with (
            mock.patch.object(self.history, "_save_state", side_effect=_fail_replay_save),
            self.assertRaisesRegex(RuntimeError, "profile change was rolled back"),
        ):
            self.history.undo(app)

        self.assertEqual(self.created.read_text(encoding="utf-8"), "created")
        self.assertEqual(app.current_db_path, str(self.created))
        self.assertEqual(self.history.get_current_entry_id(), entry.entry_id)
        self.assertEqual(self.history.fetch_entry(entry.entry_id).status, "applied")
        reloaded = SessionHistoryManager(self.history.history_root)
        self.assertEqual(reloaded.get_current_entry_id(), entry.entry_id)
        self.assertEqual(reloaded.fetch_entry(entry.entry_id).status, "applied")

    def test_redo_state_save_failure_compensates_profile_change(self):
        self.created.write_text("created", encoding="utf-8")
        entry = self.history.record_profile_create(
            created_path=str(self.created),
            previous_path=str(self.primary),
        )
        app = _FakeApp(str(self.created))
        self.history.undo(app)
        original_save = self.history._save_state
        save_calls = 0

        def _fail_replay_save():
            nonlocal save_calls
            save_calls += 1
            if save_calls == 2:
                raise OSError("simulated replay state save failure")
            original_save()

        with (
            mock.patch.object(self.history, "_save_state", side_effect=_fail_replay_save),
            self.assertRaisesRegex(RuntimeError, "profile change was rolled back"),
        ):
            self.history.redo(app)

        self.assertFalse(self.created.exists())
        self.assertEqual(app.current_db_path, str(self.primary))
        self.assertIsNone(self.history.get_current_entry_id())
        self.assertEqual(self.history.fetch_entry(entry.entry_id).status, "undone")
        reloaded = SessionHistoryManager(self.history.history_root)
        self.assertIsNone(reloaded.get_current_entry_id())
        self.assertEqual(reloaded.fetch_entry(entry.entry_id).status, "undone")

    def test_replay_state_and_compensation_failure_is_reported_loudly(self):
        self.created.write_text("created", encoding="utf-8")
        entry = self.history.record_profile_create(
            created_path=str(self.created),
            previous_path=str(self.primary),
        )
        app = _DeleteThenFailApp(str(self.created))
        self.history.undo(_FakeApp(str(self.created)))
        original_save = self.history._save_state
        save_calls = 0

        def _fail_replay_save():
            nonlocal save_calls
            save_calls += 1
            if save_calls == 2:
                raise OSError("simulated replay state save failure")
            original_save()

        with (
            mock.patch.object(self.history, "_save_state", side_effect=_fail_replay_save),
            self.assertRaisesRegex(RuntimeError, "automatic filesystem rollback also failed"),
        ):
            self.history.redo(app)

        self.assertEqual(self.created.read_text(encoding="utf-8"), "created")
        self.assertIsNone(self.history.get_current_entry_id())
        self.assertEqual(self.history.fetch_entry(entry.entry_id).status, "undone")

    def test_profile_remove_payload_variants_reload_profiles(self):
        app = _FakeApp(self.primary)
        snapshot_path = self.history.capture_profile_snapshot(self.primary, kind="profile_remove")
        snapshot_inventory = self.history._inventory_for_record(snapshot_path)

        self.history._apply_payload(
            app,
            "profile.remove",
            {
                "snapshot_path": snapshot_path,
                "deleted_path": str(self.created),
                "restore_open_path": "",
                "snapshot_inventory": snapshot_inventory,
            },
            direction="undo",
        )
        self.assertTrue(self.created.exists())
        self.assertEqual(app.reloaded_paths, [None])

        self.history._apply_payload(
            app,
            "profile.remove",
            {
                "snapshot_path": snapshot_path,
                "deleted_path": str(self.created),
                "deleting_current": False,
                "current_path": str(self.primary),
                "snapshot_inventory": snapshot_inventory,
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
            repaired._restore_profile_bundle(
                repaired.snapshot_dir / "missing-snapshot.db",
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

        with self.assertRaisesRegex(RuntimeError, "occupies the target path"):
            self.history._restore_profile_bundle(snapshot_path, target)

        for suffix in ("", "-wal", "-shm"):
            Path(f"{target}{suffix}").unlink(missing_ok=True)
        self.history._restore_profile_bundle(snapshot_path, target)

        self.assertEqual(target.read_text(encoding="utf-8"), "primary")
        self.assertEqual(target_wal.read_text(encoding="utf-8"), "wal")
        self.assertEqual(target_shm.read_text(encoding="utf-8"), "shm")


if __name__ == "__main__":
    unittest.main()

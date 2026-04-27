import argparse
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from isrc_manager import updater_helper


class UpdaterHelperTests(unittest.TestCase):
    def test_parse_args_requires_core_update_inputs(self):
        args = updater_helper.parse_args(
            [
                "--current-pid",
                "123",
                "--target",
                "/tmp/app",
                "--replacement",
                "/tmp/new-app",
                "--expected-version",
                "3.5.4",
                "--backup",
                "/tmp/app.backup",
                "--handoff-json",
                "/tmp/update-handoff.json",
                "--restart-json",
                '["/tmp/app"]',
                "--log",
                "/tmp/update.log",
            ]
        )

        self.assertEqual(args.current_pid, 123)
        self.assertEqual(args.expected_version, "3.5.4")
        self.assertEqual(args.handoff_json, "/tmp/update-handoff.json")

    def test_replace_installation_moves_target_to_backup_and_replacement_into_place(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "app.txt"
            replacement = root / "stage" / "app.txt"
            backup = root / "app.backup"
            target.write_text("old", encoding="utf-8")
            replacement.parent.mkdir()
            replacement.write_text("new", encoding="utf-8")

            installed = updater_helper.replace_installation(
                target, replacement, backup, io.StringIO()
            )

            self.assertEqual(installed, target)
            self.assertEqual(target.read_text(encoding="utf-8"), "new")
            self.assertEqual(backup.read_text(encoding="utf-8"), "old")
            self.assertFalse(replacement.exists())

    def test_replace_installation_uses_replacement_name_when_it_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "ISRCManager-3.6.10-macos.app"
            replacement = root / "stage" / "Music Catalog Manager.app"
            backup = root / "app.backup"
            target.write_text("old", encoding="utf-8")
            replacement.parent.mkdir()
            replacement.write_text("new", encoding="utf-8")

            installed = updater_helper.replace_installation(
                target, replacement, backup, io.StringIO()
            )

            self.assertEqual(installed, root / "Music Catalog Manager.app")
            self.assertFalse(target.exists())
            self.assertEqual(installed.read_text(encoding="utf-8"), "new")
            self.assertEqual(backup.read_text(encoding="utf-8"), "old")

    def test_replace_installation_rolls_back_when_second_move_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "app.txt"
            replacement = root / "stage" / "app.txt"
            backup = root / "app.backup"
            target.write_text("old", encoding="utf-8")
            replacement.parent.mkdir()
            replacement.write_text("new", encoding="utf-8")
            real_move = updater_helper.shutil.move
            calls = 0

            def _move(source, destination):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("blocked")
                return real_move(source, destination)

            with mock.patch.object(updater_helper.shutil, "move", side_effect=_move):
                with self.assertRaises(updater_helper.UpdaterHelperError):
                    updater_helper.replace_installation(target, replacement, backup, io.StringIO())

            self.assertEqual(target.read_text(encoding="utf-8"), "old")

    def test_run_update_restores_backup_if_restart_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "app.txt"
            replacement = root / "stage" / "new.txt"
            backup = root / "app.backup"
            handoff = root / "handoff.json"
            log = root / "update.log"
            target.write_text("old", encoding="utf-8")
            replacement.parent.mkdir()
            replacement.write_text("new", encoding="utf-8")
            args = argparse.Namespace(
                current_pid=0,
                target=str(target),
                replacement=str(replacement),
                expected_version="3.5.4",
                backup=str(backup),
                handoff_json=str(handoff),
                restart_json=json.dumps([str(target)]),
                log=str(log),
                wait_timeout=1.0,
            )

            with mock.patch.object(
                updater_helper,
                "restart_application",
                side_effect=updater_helper.UpdaterHelperError("restart failed"),
            ):
                exit_code = updater_helper.run_update(args)

            self.assertEqual(exit_code, updater_helper.EXIT_RESTART_FAILED)
            self.assertEqual(target.read_text(encoding="utf-8"), "old")
            self.assertFalse((root / "new.txt").exists())
            self.assertFalse(backup.exists())
            state = json.loads(handoff.read_text(encoding="utf-8"))
            self.assertEqual(state["status"], "destroyed")
            self.assertIn("restart failed", log.read_text(encoding="utf-8"))

    def test_run_update_records_backup_handoff_after_successful_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "app.txt"
            replacement = root / "stage" / "app.txt"
            backup = root / "app.backup"
            handoff = root / "handoff.json"
            log = root / "update.log"
            target.write_text("old", encoding="utf-8")
            replacement.parent.mkdir()
            replacement.write_text("new", encoding="utf-8")
            args = argparse.Namespace(
                current_pid=0,
                target=str(target),
                replacement=str(replacement),
                expected_version="3.5.4",
                backup=str(backup),
                handoff_json=str(handoff),
                restart_json=json.dumps([str(target)]),
                log=str(log),
                wait_timeout=1.0,
            )

            with mock.patch.object(updater_helper, "restart_application"):
                exit_code = updater_helper.run_update(args)

            self.assertEqual(exit_code, updater_helper.EXIT_SUCCESS)
            self.assertEqual(target.read_text(encoding="utf-8"), "new")
            self.assertTrue(backup.exists())
            state = json.loads(handoff.read_text(encoding="utf-8"))
            self.assertEqual(state["status"], "created")
            self.assertEqual(state["backup_path"], str(backup.resolve()))
            log_text = log.read_text(encoding="utf-8")
            self.assertIn("Recorded update backup handoff", log_text)
            self.assertIn("retained until the updated app confirms a clean run", log_text)
            self.assertIn("Update helper completed successfully", log_text)

    def test_run_update_rolls_back_when_backup_handoff_cannot_be_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "app.txt"
            replacement = root / "stage" / "app.txt"
            backup = root / "app.backup"
            handoff = root / "missing-parent" / "handoff.json"
            log = root / "update.log"
            target.write_text("old", encoding="utf-8")
            replacement.parent.mkdir()
            replacement.write_text("new", encoding="utf-8")
            args = argparse.Namespace(
                current_pid=0,
                target=str(target),
                replacement=str(replacement),
                expected_version="3.5.4",
                backup=str(backup),
                handoff_json=str(handoff),
                restart_json=json.dumps([str(target)]),
                log=str(log),
                wait_timeout=1.0,
            )

            with mock.patch.object(
                updater_helper,
                "record_update_backup_created",
                side_effect=OSError("handoff blocked"),
            ):
                exit_code = updater_helper.run_update(args)

            self.assertEqual(exit_code, updater_helper.EXIT_REPLACEMENT_FAILED)
            self.assertEqual(target.read_text(encoding="utf-8"), "old")
            self.assertFalse(backup.exists())
            log_text = log.read_text(encoding="utf-8")
            self.assertIn("Could not record update backup handoff", log_text)
            self.assertIn("Restoring backup", log_text)

    def test_run_update_rejects_invalid_restart_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = argparse.Namespace(
                current_pid=0,
                target=str(root / "app.txt"),
                replacement=str(root / "new.txt"),
                expected_version="3.5.4",
                backup=str(root / "app.backup"),
                handoff_json=str(root / "handoff.json"),
                restart_json="{}",
                log=str(root / "update.log"),
                wait_timeout=1.0,
            )

            self.assertEqual(updater_helper.run_update(args), updater_helper.EXIT_INVALID_ARGUMENTS)

    def test_wait_for_process_exit_ignores_zero_pid(self):
        updater_helper.wait_for_process_exit(0, timeout_seconds=0.01)


if __name__ == "__main__":
    unittest.main()

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from isrc_manager import update_handoff


class UpdateBackupHandoffTests(unittest.TestCase):
    def test_record_created_overwrites_previous_backup_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = root / "handoff.json"
            first_backup = root / "old.backup"
            second_backup = root / "new.backup"

            update_handoff.record_update_backup_created(first_backup, state_path=state_path)
            state = update_handoff.record_update_backup_created(
                second_backup,
                expected_version="3.6.9",
                target_path=root / "app",
                installed_path=root / "Music Catalog Manager.app",
                state_path=state_path,
            )

            saved = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state["status"], update_handoff.UPDATE_BACKUP_STATUS_CREATED)
            self.assertEqual(saved["backup_path"], str(second_backup.resolve()))
            self.assertEqual(saved["expected_version"], "3.6.9")
            self.assertEqual(saved["target_path"], str((root / "app").resolve()))
            self.assertEqual(
                saved["installed_path"],
                str((root / "Music Catalog Manager.app").resolve()),
            )

    def test_cleanup_ignores_backup_until_handoff_is_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = root / "handoff.json"
            backup = root / "app.backup"
            backup.write_text("old app", encoding="utf-8")

            update_handoff.record_update_backup_created(backup, state_path=state_path)
            state = update_handoff.cleanup_ready_update_backup(state_path=state_path)

            self.assertEqual(state["status"], update_handoff.UPDATE_BACKUP_STATUS_CREATED)
            self.assertTrue(backup.exists())

    def test_ready_backup_is_deleted_and_marked_destroyed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = root / "handoff.json"
            backup = root / "app.backup"
            (backup / "Contents").mkdir(parents=True)
            (backup / "Contents" / "old").write_text("old app", encoding="utf-8")

            update_handoff.record_update_backup_created(backup, state_path=state_path)
            update_handoff.mark_update_backup_ready_for_deletion(state_path=state_path)
            state = update_handoff.cleanup_ready_update_backup(state_path=state_path)

            self.assertEqual(state["status"], update_handoff.UPDATE_BACKUP_STATUS_DESTROYED)
            self.assertFalse(backup.exists())
            self.assertTrue(state["destroyed_at"])

    def test_cleanup_failure_keeps_handoff_ready_for_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = root / "handoff.json"
            backup = root / "app.backup"
            backup.write_text("old app", encoding="utf-8")

            update_handoff.record_update_backup_created(backup, state_path=state_path)
            update_handoff.mark_update_backup_ready_for_deletion(state_path=state_path)
            with mock.patch.object(
                update_handoff,
                "_remove_path",
                side_effect=OSError("delete blocked"),
            ):
                with self.assertRaises(OSError):
                    update_handoff.cleanup_ready_update_backup(state_path=state_path)

            state = update_handoff.read_update_backup_handoff(state_path=state_path)
            self.assertEqual(
                state["status"], update_handoff.UPDATE_BACKUP_STATUS_READY_FOR_DELETION
            )
            self.assertIn("delete blocked", state["error"])
            self.assertTrue(backup.exists())

    def test_legacy_cleanup_removes_only_current_version_update_backups(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            installed = root / "Music Catalog Manager.app"
            installed.mkdir()
            matching_backup = root / "ISRCManager-3.6.8-macos.app.backup-before-v3.6.9-20260427"
            matching_backup.mkdir()
            old_version_backup = root / "ISRCManager-3.6.7-macos.app.backup-before-v3.6.8-20260426"
            old_version_backup.mkdir()
            unrelated = root / "manual-backup"
            unrelated.mkdir()

            removed = update_handoff.cleanup_legacy_update_backups_for_version(
                installed,
                "3.6.9",
            )

            self.assertEqual(removed, [matching_backup.resolve()])
            self.assertFalse(matching_backup.exists())
            self.assertTrue(old_version_backup.exists())
            self.assertTrue(unrelated.exists())

    def test_sibling_cleanup_removes_all_update_backups_for_started_app(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            installed = root / "Music Catalog Manager.app"
            installed.mkdir()
            current_version_backup = (
                root / "Music Catalog Manager.app.backup-before-v3.7.5-20260427-200000"
            )
            current_version_backup.mkdir()
            older_backup = root / "Music Catalog Manager.app.backup-before-v3.7.4-20260427-190000"
            older_backup.mkdir()
            unrelated = root / "manual-backup"
            unrelated.mkdir()

            removed = update_handoff.cleanup_update_backup_siblings(installed)

            self.assertEqual(removed, [older_backup.resolve(), current_version_backup.resolve()])
            self.assertFalse(current_version_backup.exists())
            self.assertFalse(older_backup.exists())
            self.assertTrue(unrelated.exists())

    def test_update_cache_cleanup_removes_workspaces_but_keeps_handoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = root / update_handoff.UPDATE_BACKUP_HANDOFF_FILENAME
            state_path.write_text("{}", encoding="utf-8")
            workspace = root / "v3.7.5-macos"
            workspace.mkdir()
            package = root / "download.zip"
            package.write_bytes(b"pkg")

            removed = update_handoff.cleanup_update_cache_artifacts(update_root=root)

            self.assertEqual(removed, [package.resolve(), workspace.resolve()])
            self.assertTrue(state_path.exists())
            self.assertFalse(workspace.exists())
            self.assertFalse(package.exists())


if __name__ == "__main__":
    unittest.main()

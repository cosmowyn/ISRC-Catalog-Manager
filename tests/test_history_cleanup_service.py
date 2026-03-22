import shutil
import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import QSettings

from isrc_manager.history import (
    HistoryCleanupBlockedError,
    HistoryManager,
    HistoryStorageCleanupService,
    SessionHistoryManager,
)
from isrc_manager.services import (
    DatabaseSchemaService,
    DatabaseSessionService,
    HistoryRetentionSettings,
    SettingsMutationService,
)


class HistoryCleanupServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.db_path = self.root / "Database" / "library.db"
        self.settings_path = self.root / "settings.ini"
        self.history_root = self.root / "history"
        self.data_root = self.root / "data"
        self.backups_root = self.root / "backups"
        self.settings = QSettings(str(self.settings_path), QSettings.IniFormat)
        self.settings.setFallbacksEnabled(False)

        session = DatabaseSessionService().open(self.db_path)
        self.conn = session.conn
        self.schema = DatabaseSchemaService(self.conn, data_root=self.data_root)
        self.schema.init_db()
        self.schema.migrate_schema()
        self.history = HistoryManager(
            self.conn,
            self.settings,
            self.db_path,
            self.history_root,
            self.data_root,
            self.backups_root,
        )
        self.settings_mutations = SettingsMutationService(self.conn, self.settings)
        self.cleanup = HistoryStorageCleanupService(self.history)

    def tearDown(self):
        self.settings.clear()
        DatabaseSessionService.close(self.conn)
        self.tmpdir.cleanup()

    def test_inspect_classifies_eligible_and_protected_artifacts(self):
        protected_snapshot = self.history.create_manual_snapshot("Protected Snapshot")
        loose_snapshot = self.history.capture_snapshot(kind="manual", label="Loose Snapshot")

        backup_path = self.backups_root / "manual_backup.db"
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn.commit()
        shutil.copy2(self.db_path, backup_path)
        backup_record = self.history.register_backup(
            backup_path,
            kind="manual",
            label="Manual Backup",
            source_db_path=self.db_path,
        )

        orphan_snapshot_dir = self.history_root / "snapshots" / self.db_path.stem
        orphan_snapshot_dir.mkdir(parents=True, exist_ok=True)
        orphan_snapshot_path = orphan_snapshot_dir / "orphan_snapshot.db"
        self.conn.commit()
        shutil.copy2(self.db_path, orphan_snapshot_path)

        export_path = self.root / "exports" / "catalog.txt"
        export_path.parent.mkdir(parents=True, exist_ok=True)
        export_path.write_text("before", encoding="utf-8")
        before_state = self.history.capture_file_state(export_path)
        export_path.write_text("after", encoding="utf-8")
        after_state = self.history.capture_file_state(export_path)
        self.history.record_file_write_action(
            label="Export File",
            action_type="file.export",
            target_path=export_path,
            before_state=before_state,
            after_state=after_state,
        )
        protected_file_state_dir = Path(after_state["files"][0]["artifact_path"]).parent

        stale_file_state_dir = (
            self.history_root / "file_states" / self.db_path.stem / "stale_bundle"
        )
        stale_file_state_dir.mkdir(parents=True, exist_ok=True)
        (stale_file_state_dir / "artifact.bin").write_bytes(b"stale")

        session_history = SessionHistoryManager(self.history_root)
        session_history.record_profile_create(
            created_path=str(self.db_path),
            previous_path=str(self.db_path),
        )
        protected_session_snapshot = next(
            (self.history_root / "session_profile_snapshots").glob("*.db")
        )
        stale_session_snapshot = self.history_root / "session_profile_snapshots" / "stale.db"
        self.conn.commit()
        shutil.copy2(self.db_path, stale_session_snapshot)

        preview = self.cleanup.inspect()
        eligible_keys = {item.item_key for item in preview.eligible_items}
        protected_keys = {item.item_key for item in preview.protected_items}

        self.assertIn(f"snapshot_record:{loose_snapshot.snapshot_id}", eligible_keys)
        self.assertIn(f"backup_record:{backup_record.backup_id}", eligible_keys)
        self.assertIn(f"orphan_snapshot_file:{orphan_snapshot_path}", eligible_keys)
        self.assertIn(f"file_state_bundle:{stale_file_state_dir}", eligible_keys)
        self.assertIn(f"session_snapshot:{stale_session_snapshot}", eligible_keys)

        self.assertIn(f"snapshot_record:{protected_snapshot.snapshot_id}", protected_keys)
        self.assertIn(f"file_state_bundle:{protected_file_state_dir}", protected_keys)
        self.assertIn(f"session_snapshot:{protected_session_snapshot}", protected_keys)
        self.assertFalse(preview.repair_required)

    def test_cleanup_selected_removes_snapshot_backup_and_orphan_artifacts(self):
        loose_snapshot = self.history.capture_snapshot(kind="manual", label="Loose Snapshot")

        backup_path = self.backups_root / "cleanup_backup.db"
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn.commit()
        shutil.copy2(self.db_path, backup_path)
        backup_record = self.history.register_backup(
            backup_path,
            kind="pre_restore_safety_copy",
            label="Cleanup Backup",
            source_db_path=self.db_path,
        )

        orphan_snapshot_dir = self.history_root / "snapshots" / self.db_path.stem
        orphan_snapshot_dir.mkdir(parents=True, exist_ok=True)
        orphan_snapshot_path = orphan_snapshot_dir / "cleanup_orphan.db"
        self.conn.commit()
        shutil.copy2(self.db_path, orphan_snapshot_path)

        result = self.cleanup.cleanup_selected(
            [
                f"snapshot_record:{loose_snapshot.snapshot_id}",
                f"backup_record:{backup_record.backup_id}",
                f"orphan_snapshot_file:{orphan_snapshot_path}",
            ]
        )

        self.assertEqual(len(result.removed_item_keys), 3)
        self.assertIsNone(self.history.fetch_snapshot(loose_snapshot.snapshot_id))
        self.assertIsNone(self.history.fetch_backup(backup_record.backup_id))
        self.assertFalse(Path(loose_snapshot.db_snapshot_path).exists())
        self.assertFalse(backup_path.exists())
        self.assertFalse(orphan_snapshot_path.exists())

    def test_trim_history_removes_old_entries_and_newly_unreferenced_snapshot_storage(self):
        self.settings_mutations.set_auto_snapshot_enabled(True)
        self.history.record_setting_change(
            key="auto_snapshot_enabled",
            label="Toggle Auto Snapshot",
            before_value=False,
            after_value=True,
        )
        old_snapshot = self.history.create_manual_snapshot("Trim Me")
        self.history.record_setting_change(
            key="isrc_prefix",
            label="Set ISRC Prefix",
            before_value="",
            after_value="NLTST",
        )
        self.history.record_setting_change(
            key="sena_number",
            label="Set SENA Number",
            before_value="",
            after_value="12345",
        )

        archive_dir = self.history_root / "snapshot_archives" / self.db_path.stem
        self.assertTrue(any(archive_dir.glob("*.db")))

        preview = self.cleanup.preview_trim_history(1)
        self.assertGreaterEqual(len(preview.removable_entry_ids), 1)

        result = self.cleanup.trim_history(1)

        remaining_entries = self.history.list_entries(limit=50, include_hidden=True)
        self.assertLessEqual(len(remaining_entries), 1)
        self.assertGreaterEqual(len(result.removed_entry_ids), 1)
        self.assertIsNone(self.history.fetch_snapshot(old_snapshot.snapshot_id))
        self.assertFalse(Path(old_snapshot.db_snapshot_path).exists())
        self.assertFalse(any(archive_dir.glob("*.db")))

    def test_cleanup_is_blocked_when_repair_issues_exist(self):
        protected_snapshot = self.history.create_manual_snapshot("Protected Snapshot")
        Path(protected_snapshot.db_snapshot_path).unlink()

        preview = self.cleanup.inspect()
        self.assertTrue(preview.repair_required)

        with self.assertRaises(HistoryCleanupBlockedError):
            self.cleanup.trim_history(1)

    def test_preview_storage_budget_identifies_automatic_cleanup_candidates(self):
        old_auto_snapshot = self.history.capture_snapshot(kind="auto_interval", label="Old Auto")
        self.history.capture_snapshot(kind="auto_interval", label="Keep Auto")

        stale_bundle = self.history_root / "file_states" / self.db_path.stem / "stale_bundle"
        stale_bundle.mkdir(parents=True, exist_ok=True)
        (stale_bundle / "artifact.bin").write_bytes(b"stale")

        settings = HistoryRetentionSettings(
            auto_cleanup_enabled=True,
            storage_budget_mb=1,
            auto_snapshot_keep_latest=1,
            prune_pre_restore_copies_after_days=0,
        )

        preview = self.cleanup.preview_storage_budget(settings)
        candidate_keys = {item.item_key for item in preview.candidate_items}

        self.assertIn(f"snapshot_record:{old_auto_snapshot.snapshot_id}", candidate_keys)
        self.assertIn(f"file_state_bundle:{stale_bundle}", candidate_keys)
        self.assertGreater(preview.budget_bytes, 0)

    def test_enforce_storage_budget_removes_old_auto_snapshots_but_not_manual_ones(self):
        manual_snapshot = self.history.create_manual_snapshot("Manual Keep")
        old_auto_snapshot = self.history.capture_snapshot(kind="auto_interval", label="Old Auto")
        self.history.capture_snapshot(kind="auto_interval", label="Keep Auto")

        settings = HistoryRetentionSettings(
            auto_cleanup_enabled=True,
            storage_budget_mb=1,
            auto_snapshot_keep_latest=1,
            prune_pre_restore_copies_after_days=0,
        )

        result = self.cleanup.enforce_storage_budget(settings)

        self.assertIn(
            f"snapshot_record:{old_auto_snapshot.snapshot_id}",
            set(result.removed_item_keys),
        )
        self.assertIsNone(self.history.fetch_snapshot(old_auto_snapshot.snapshot_id))
        self.assertIsNotNone(self.history.fetch_snapshot(manual_snapshot.snapshot_id))


if __name__ == "__main__":
    unittest.main()

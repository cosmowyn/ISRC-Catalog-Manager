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

    def _snapshot_create_entry(self, snapshot_id: int):
        for entry in self.history.list_entries(limit=100, include_hidden=True):
            if entry.action_type == "snapshot.create" and str(entry.entity_id or "") == str(
                int(snapshot_id)
            ):
                return entry
        self.fail(f"Could not find snapshot.create entry for snapshot {snapshot_id}")

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

        self.assertNotIn(f"snapshot_record:{old_auto_snapshot.snapshot_id}", candidate_keys)
        self.assertIn(f"file_state_bundle:{stale_bundle}", candidate_keys)
        self.assertGreater(preview.budget_bytes, 0)

    def test_enforce_storage_budget_applies_hard_cap_to_live_snapshots_before_cleanup(self):
        oldest_manual = self.history.capture_snapshot(kind="manual", label="Manual One")
        middle_manual = self.history.capture_snapshot(kind="manual", label="Manual Two")
        newest_manual = self.history.capture_snapshot(kind="manual", label="Manual Three")

        settings = HistoryRetentionSettings(
            auto_cleanup_enabled=True,
            storage_budget_mb=1,
            auto_snapshot_keep_latest=1,
            prune_pre_restore_copies_after_days=0,
        )

        result = self.cleanup.enforce_storage_budget(settings)

        self.assertIn(
            f"snapshot_record:{oldest_manual.snapshot_id}",
            set(result.removed_item_keys),
        )
        self.assertIn(
            f"snapshot_record:{middle_manual.snapshot_id}",
            set(result.removed_item_keys),
        )
        self.assertIsNone(self.history.fetch_snapshot(oldest_manual.snapshot_id))
        self.assertIsNone(self.history.fetch_snapshot(middle_manual.snapshot_id))
        self.assertIsNotNone(self.history.fetch_snapshot(newest_manual.snapshot_id))

    def test_enforce_snapshot_retention_keeps_visible_undo_boundary_even_when_it_exceeds_cap(self):
        protected_target = self.history.create_manual_snapshot("Protected Target")
        pruned_candidate = self.history.create_manual_snapshot("Pruned Candidate")
        self.history.restore_snapshot_as_action(
            protected_target.snapshot_id,
            label="Restore Protected Target",
        )

        settings = HistoryRetentionSettings(
            auto_cleanup_enabled=True,
            storage_budget_mb=2048,
            auto_snapshot_keep_latest=1,
            prune_pre_restore_copies_after_days=0,
        )

        result = self.cleanup.enforce_snapshot_retention(settings)
        retained_ids = set(result.retained_snapshot_ids)
        protected_ids = set(result.protected_visible_undo_snapshot_ids)

        self.assertTrue(result.cap_limited_by_visible_undo)
        self.assertEqual(retained_ids, protected_ids)
        self.assertNotIn(pruned_candidate.snapshot_id, retained_ids)
        self.assertEqual(result.retained_live_snapshot_count, 2)

        undone = self.history.undo()
        self.assertIsNotNone(undone)
        self.assertEqual(undone.action_type, "snapshot.restore")

    def test_enforce_snapshot_retention_prunes_oldest_first_at_keep_latest_five(self):
        snapshots = [
            self.history.capture_snapshot(kind="manual", label=f"Snapshot {index}")
            for index in range(1, 8)
        ]
        oldest_path = Path(snapshots[0].db_snapshot_path)
        oldest_assets = oldest_path.with_suffix(".assets")
        oldest_assets.mkdir(parents=True, exist_ok=True)
        (oldest_assets / "artifact.bin").write_bytes(b"artifact")
        oldest_companion = Path(f"{oldest_path}-journal")
        oldest_companion.write_bytes(b"journal")

        settings = HistoryRetentionSettings(
            auto_cleanup_enabled=True,
            storage_budget_mb=2048,
            auto_snapshot_keep_latest=5,
            prune_pre_restore_copies_after_days=0,
        )

        result = self.cleanup.enforce_snapshot_retention(settings)

        self.assertEqual(
            result.pruned_snapshot_ids,
            (snapshots[0].snapshot_id, snapshots[1].snapshot_id),
        )
        self.assertEqual(
            result.retained_snapshot_ids,
            tuple(snapshot.snapshot_id for snapshot in snapshots[2:]),
        )
        self.assertFalse(oldest_path.exists())
        self.assertFalse(oldest_assets.exists())
        self.assertFalse(oldest_companion.exists())

    def test_enforce_snapshot_retention_quarantines_old_snapshot_history_in_place(self):
        old_snapshot = self.history.create_manual_snapshot("Old Snapshot")
        old_entry = self._snapshot_create_entry(old_snapshot.snapshot_id)
        old_archive_path = Path(old_entry.redo_payload["archived_snapshot"]["db_snapshot_path"])
        self.assertTrue(old_archive_path.exists())

        current_snapshot = self.history.create_manual_snapshot("Current Snapshot")

        settings = HistoryRetentionSettings(
            auto_cleanup_enabled=True,
            storage_budget_mb=2048,
            auto_snapshot_keep_latest=1,
            prune_pre_restore_copies_after_days=0,
        )

        result = self.cleanup.enforce_snapshot_retention(settings)
        refreshed_old_entry = self.history.fetch_entry(old_entry.entry_id)

        self.assertIsNotNone(refreshed_old_entry)
        self.assertIn(old_snapshot.snapshot_id, result.pruned_snapshot_ids)
        self.assertNotIn(current_snapshot.snapshot_id, result.pruned_snapshot_ids)
        self.assertIn(old_entry.entry_id, result.quarantined_entry_ids)
        self.assertFalse(refreshed_old_entry.reversible)
        self.assertEqual(refreshed_old_entry.status, self.history.STATUS_ARTIFACT_MISSING)
        self.assertIsNone(refreshed_old_entry.payload.get("snapshot_id"))
        self.assertIsNone(refreshed_old_entry.inverse_payload.get("snapshot_id"))
        self.assertFalse(old_archive_path.exists())

    def test_preview_storage_budget_counts_orphan_snapshot_assets_and_companions(self):
        snapshot_dir = self.history_root / "snapshots" / self.db_path.stem
        snapshot_dir.mkdir(parents=True, exist_ok=True)

        orphan_assets = snapshot_dir / "orphan_snapshot.assets"
        orphan_assets.mkdir(parents=True, exist_ok=True)
        (orphan_assets / "artifact.bin").write_bytes(b"bundle")

        orphan_companion = snapshot_dir / "orphan_snapshot.db-journal"
        orphan_companion.write_bytes(b"journal")

        settings = HistoryRetentionSettings(
            auto_cleanup_enabled=True,
            storage_budget_mb=1,
            auto_snapshot_keep_latest=1,
            prune_pre_restore_copies_after_days=0,
        )

        preview = self.cleanup.preview_storage_budget(settings)
        candidate_keys = {item.item_key for item in preview.candidate_items}

        self.assertIn(f"orphan_snapshot_bundle:{orphan_assets}", candidate_keys)
        self.assertIn(f"orphan_snapshot_companion:{orphan_companion}", candidate_keys)
        self.assertGreaterEqual(preview.total_bytes, len(b"bundle") + len(b"journal"))

        result = self.cleanup.enforce_storage_budget(settings)
        removed_keys = set(result.removed_item_keys)
        self.assertIn(f"orphan_snapshot_bundle:{orphan_assets}", removed_keys)
        self.assertIn(f"orphan_snapshot_companion:{orphan_companion}", removed_keys)
        self.assertFalse(orphan_assets.exists())
        self.assertFalse(orphan_companion.exists())

    def test_delete_snapshot_removes_assets_root_and_companion_files(self):
        snapshot = self.history.capture_snapshot(kind="manual", label="Loose Snapshot")
        snapshot_path = Path(snapshot.db_snapshot_path)
        assets_root = snapshot_path.with_suffix(".assets")
        assets_root.mkdir(parents=True, exist_ok=True)
        (assets_root / "artifact.bin").write_bytes(b"artifact")
        companion = Path(f"{snapshot_path}-journal")
        companion.write_bytes(b"journal")

        self.history.delete_snapshot(snapshot.snapshot_id)

        self.assertFalse(snapshot_path.exists())
        self.assertFalse(assets_root.exists())
        self.assertFalse(companion.exists())

    def test_preview_storage_projection_flags_when_growth_would_exceed_budget(self):
        self.history.create_manual_snapshot("Manual Keep")

        settings = HistoryRetentionSettings(
            retention_mode="maximum_safety",
            auto_cleanup_enabled=True,
            storage_budget_mb=1,
            auto_snapshot_keep_latest=50,
            prune_pre_restore_copies_after_days=0,
        )

        projection = self.cleanup.preview_storage_projection(
            settings,
            additional_bytes=8 * 1024 * 1024,
        )

        self.assertGreater(projection.projected_over_budget_bytes, 0)
        self.assertTrue(projection.blocked_by_protected_items)
        self.assertEqual(len(projection.candidate_items), 0)


if __name__ == "__main__":
    unittest.main()

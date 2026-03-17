import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import QPoint, QSettings

from isrc_manager.history import HistoryManager
from isrc_manager.services import (
    ContractService,
    DatabaseSchemaService,
    DatabaseSessionService,
    LegacyLicenseMigrationService,
    LicenseService,
    PartyService,
    SettingsMutationService,
    SettingsReadService,
    TrackCreatePayload,
    TrackService,
    TrackUpdatePayload,
)
from isrc_manager.theme_builder import theme_setting_defaults


class HistoryManagerTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.db_path = self.root / "Database" / "library.db"
        self.settings_path = self.root / "settings.ini"
        self.history_root = self.root / "history"
        self.data_root = self.root / "data"
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.settings = QSettings(str(self.settings_path), QSettings.IniFormat)
        self.settings.setFallbacksEnabled(False)

        self.session_service = DatabaseSessionService()
        self.session = self.session_service.open(self.db_path)
        self.conn = self.session.conn
        self.schema = DatabaseSchemaService(self.conn)
        self.schema.init_db()
        self.schema.migrate_schema()

        self.track_service = TrackService(self.conn)
        self.license_service = LicenseService(self.conn, self.data_root)
        self.party_service = PartyService(self.conn)
        self.contract_service = ContractService(
            self.conn, self.data_root, party_service=self.party_service
        )
        self.license_migration_service = LegacyLicenseMigrationService(
            self.conn,
            license_service=self.license_service,
            party_service=self.party_service,
            contract_service=self.contract_service,
        )
        self.settings_mutations = SettingsMutationService(self.conn, self.settings)
        self.settings_reads = SettingsReadService(self.conn)
        self.history = HistoryManager(
            self.conn,
            self.settings,
            self.db_path,
            self.history_root,
            self.data_root,
        )

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

    def _create_source_pdf(self, name: str = "signed_license.pdf") -> Path:
        pdf_path = self.root / name
        pdf_path.write_bytes(b"%PDF-1.4\n% history test\n")
        return pdf_path

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

    def test_auto_snapshot_setting_changes_undo_and_redo(self):
        self.settings_mutations.set_auto_snapshot_enabled(True)
        self.settings_mutations.set_auto_snapshot_interval_minutes(30)

        self.history.record_setting_change(
            key="auto_snapshot_enabled",
            label="Automatic Snapshots Enabled",
            before_value=True,
            after_value=False,
        )
        self.settings_mutations.set_auto_snapshot_enabled(False)

        self.history.record_setting_change(
            key="auto_snapshot_interval_minutes",
            label="Set Auto Snapshot Interval: 45 minutes",
            before_value=30,
            after_value=45,
        )
        self.settings_mutations.set_auto_snapshot_interval_minutes(45)

        self.assertFalse(self.settings_reads.load_auto_snapshot_enabled())
        self.assertEqual(self.settings_reads.load_auto_snapshot_interval_minutes(), 45)

        self.history.undo()
        self.assertEqual(self.settings_reads.load_auto_snapshot_interval_minutes(), 30)

        self.history.undo()
        self.assertTrue(self.settings_reads.load_auto_snapshot_enabled())

        self.history.redo()
        self.assertFalse(self.settings_reads.load_auto_snapshot_enabled())

        self.history.redo()
        self.assertEqual(self.settings_reads.load_auto_snapshot_interval_minutes(), 45)

    def test_expanded_theme_settings_undo_and_redo_restore_new_fields(self):
        before_theme = theme_setting_defaults()
        after_theme = dict(before_theme)
        after_theme["button_hover_bg"] = "#224488"
        after_theme["menu_radius"] = 14
        after_theme["dialog_title_font_size"] = 22

        for key, value in after_theme.items():
            self.settings.setValue(f"theme/{key}", value)
        self.settings.sync()
        self.history.record_setting_change(
            key="theme_settings",
            label="Update Theme Settings",
            before_value=before_theme,
            after_value=after_theme,
        )

        self.history.undo()
        self.assertEqual(
            self.settings.value("theme/button_hover_bg", "", str) or "",
            before_theme["button_hover_bg"],
        )
        self.assertEqual(
            int(self.settings.value("theme/menu_radius", 0, int)),
            int(before_theme["menu_radius"]),
        )
        self.assertEqual(
            int(self.settings.value("theme/dialog_title_font_size", 0, int)),
            int(before_theme["dialog_title_font_size"]),
        )

        self.history.redo()
        self.assertEqual(
            self.settings.value("theme/button_hover_bg", "", str),
            "#224488",
        )
        self.assertEqual(int(self.settings.value("theme/menu_radius", 0, int)), 14)
        self.assertEqual(int(self.settings.value("theme/dialog_title_font_size", 0, int)), 22)

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

        self.assertEqual(
            self.track_service.fetch_track_snapshot(track_id).track_title, "Updated Song"
        )

        self.history.undo()
        self.assertEqual(
            self.track_service.fetch_track_snapshot(track_id).track_title, "First Song"
        )

        self.history.redo()
        self.assertEqual(
            self.track_service.fetch_track_snapshot(track_id).track_title, "Updated Song"
        )

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
        self.assertEqual(
            self.track_service.fetch_track_snapshot(track_id).track_title, "Changed Again"
        )

        self.history.restore_snapshot_as_action(snapshot.snapshot_id)
        self.assertEqual(
            self.track_service.fetch_track_snapshot(track_id).track_title, "Updated Song"
        )

        self.history.undo()
        self.assertEqual(
            self.track_service.fetch_track_snapshot(track_id).track_title, "Changed Again"
        )

        self.history.redo()
        self.assertEqual(
            self.track_service.fetch_track_snapshot(track_id).track_title, "Updated Song"
        )

    def test_snapshot_actions_restore_managed_license_files(self):
        track_id = self._create_track()
        source_pdf = self._create_source_pdf()

        before = self.history.capture_snapshot(kind="pre_license_add", label="Before Add License")
        record_id = self.license_service.add_license(
            track_id=track_id,
            licensee_name="Publisher BV",
            source_pdf_path=source_pdf,
        )
        stored = self.license_service.fetch_license(record_id)
        self.assertIsNotNone(stored)
        stored_path = self.license_service.resolve_path(stored.file_path)
        self.assertTrue(stored_path.exists())

        after = self.history.capture_snapshot(kind="post_license_add", label="After Add License")
        self.history.record_snapshot_action(
            label="Add License PDF",
            action_type="license.add",
            entity_type="License",
            entity_id=str(record_id),
            payload={"record_id": record_id},
            snapshot_before_id=before.snapshot_id,
            snapshot_after_id=after.snapshot_id,
        )

        self.history.undo()
        self.assertEqual(self.license_service.list_rows(), [])
        self.assertFalse((self.data_root / "licenses").exists())

        self.history.redo()
        restored = self.license_service.fetch_license(record_id)
        self.assertIsNotNone(restored)
        self.assertTrue(self.license_service.resolve_path(restored.file_path).exists())

    def test_registered_snapshot_can_be_restored(self):
        snapshot = self.history.create_manual_snapshot("Initial State")
        registered = self.history.register_snapshot(
            snapshot, kind="registered", label="Registered Initial State"
        )
        self.assertNotEqual(snapshot.snapshot_id, registered.snapshot_id)

        track_id = self._create_track()
        self.assertIsNotNone(self.track_service.fetch_track_snapshot(track_id))

        self.history.restore_snapshot_as_action(registered.snapshot_id)
        self.assertIsNone(self.track_service.fetch_track_snapshot(track_id))

    def test_manual_snapshot_create_and_delete_can_be_undone(self):
        created = self.history.create_manual_snapshot("Manual Snapshot")
        self.assertIsNotNone(self.history.fetch_snapshot(created.snapshot_id))

        self.history.undo()
        self.assertIsNone(self.history.fetch_snapshot(created.snapshot_id))

        self.history.redo()
        restored_snapshots = [
            snap for snap in self.history.list_snapshots() if snap.label == "Manual Snapshot"
        ]
        self.assertEqual(len(restored_snapshots), 1)

        restored = restored_snapshots[0]
        self.history.delete_snapshot_as_action(restored.snapshot_id)
        self.assertIsNone(self.history.fetch_snapshot(restored.snapshot_id))

        self.history.undo()
        restored_again = [
            snap for snap in self.history.list_snapshots() if snap.label == "Manual Snapshot"
        ]
        self.assertEqual(len(restored_again), 1)

        self.history.redo()
        self.assertEqual(
            [snap for snap in self.history.list_snapshots() if snap.label == "Manual Snapshot"], []
        )

    def test_setting_bundle_change_restores_qpoint_and_coalesces(self):
        key = "display/col_hint_pos"
        self.settings.setValue(key, QPoint(12, 18))
        self.settings.sync()
        before = self.history.capture_setting_states([key])

        self.settings.setValue(key, QPoint(30, 45))
        self.settings.sync()
        after_first = self.history.capture_setting_states([key])
        self.history.record_setting_bundle_change(
            label="Move Column Hint",
            before_entries=before,
            after_entries=after_first,
            entity_id=key,
        )

        self.settings.setValue(key, QPoint(60, 90))
        self.settings.sync()
        after_second = self.history.capture_setting_states([key])
        self.history.record_setting_bundle_change(
            label="Move Column Hint",
            before_entries=after_first,
            after_entries=after_second,
            entity_id=key,
        )

        bundle_entries = [
            entry
            for entry in self.history.list_entries(limit=20)
            if entry.action_type == "settings.bundle"
        ]
        self.assertEqual(len(bundle_entries), 1)

        self.history.undo()
        self.assertEqual(self.settings.value(key, type=QPoint), QPoint(12, 18))

        self.history.redo()
        self.assertEqual(self.settings.value(key, type=QPoint), QPoint(60, 90))

    def test_snapshot_actions_restore_external_file_side_effects(self):
        before = self.history.capture_snapshot(
            kind="pre_file_side_effect", label="Before file side effect"
        )
        export_path = self.root / "exports" / "catalog.xml"
        export_path.parent.mkdir(parents=True, exist_ok=True)
        export_path.write_text("<catalog/>", encoding="utf-8")
        after = self.history.capture_snapshot(
            kind="post_file_side_effect", label="After file side effect"
        )

        self.history.record_snapshot_action(
            label="Create Export File",
            action_type="file.export_xml_all",
            entity_type="File",
            entity_id=str(export_path),
            payload={
                "file_effects": [
                    {
                        "target_path": str(export_path),
                        "before_state": {
                            "target_path": str(export_path),
                            "companion_suffixes": [],
                            "exists": False,
                            "files": [],
                        },
                        "after_state": self.history.capture_file_state(export_path),
                    }
                ]
            },
            snapshot_before_id=before.snapshot_id,
            snapshot_after_id=after.snapshot_id,
        )

        self.history.undo()
        self.assertFalse(export_path.exists())

        self.history.redo()
        self.assertTrue(export_path.exists())
        self.assertEqual(export_path.read_text(encoding="utf-8"), "<catalog/>")

    def test_snapshot_actions_restore_legacy_license_migration_state(self):
        track_id = self._create_track(title="Migration History Song")
        source_pdf = self._create_source_pdf("history_legacy_license.pdf")
        record_id = self.license_service.add_license(
            track_id=track_id,
            licensee_name="History Label",
            source_pdf_path=source_pdf,
        )
        legacy_record = self.license_service.fetch_license(record_id)
        self.assertIsNotNone(legacy_record)
        assert legacy_record is not None
        legacy_path = self.license_service.resolve_path(legacy_record.file_path)
        self.assertTrue(legacy_path.exists())

        before = self.history.capture_snapshot(
            kind="pre_license_migration", label="Before Legacy License Migration"
        )
        result = self.license_migration_service.migrate_all()
        after = self.history.capture_snapshot(
            kind="post_license_migration", label="After Legacy License Migration"
        )
        self.history.record_snapshot_action(
            label="Migrate Legacy Licenses to Contracts",
            action_type="license.migrate_legacy",
            entity_type="License",
            entity_id="legacy_migration",
            payload={"legacy_license_count": 1},
            snapshot_before_id=before.snapshot_id,
            snapshot_after_id=after.snapshot_id,
        )

        self.assertIsNone(self.license_service.fetch_license(record_id))
        self.assertFalse(legacy_path.exists())
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM Contracts").fetchone()[0], 1)
        contract_detail = self.contract_service.fetch_contract_detail(result.contract_ids[0])
        self.assertIsNotNone(contract_detail)
        assert contract_detail is not None
        migrated_path = self.contract_service.resolve_document_path(
            contract_detail.documents[0].file_path
        )
        self.assertIsNotNone(migrated_path)
        assert migrated_path is not None
        self.assertTrue(migrated_path.exists())

        self.history.undo()
        restored_legacy = self.license_service.fetch_license(record_id)
        self.assertIsNotNone(restored_legacy)
        self.assertTrue(legacy_path.exists())
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM Contracts").fetchone()[0], 0)
        self.assertFalse((self.data_root / "contract_documents").exists())

        self.history.redo()
        self.assertIsNone(self.license_service.fetch_license(record_id))
        self.assertFalse(legacy_path.exists())
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM Contracts").fetchone()[0], 1)
        restored_contract_detail = self.contract_service.fetch_contract_detail(
            result.contract_ids[0]
        )
        self.assertIsNotNone(restored_contract_detail)
        assert restored_contract_detail is not None
        restored_migrated_path = self.contract_service.resolve_document_path(
            restored_contract_detail.documents[0].file_path
        )
        self.assertIsNotNone(restored_migrated_path)
        assert restored_migrated_path is not None
        self.assertTrue(restored_migrated_path.exists())


if __name__ == "__main__":
    unittest.main()

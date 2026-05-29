import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QByteArray, QPoint, QSettings

from isrc_manager.code_registry import BUILTIN_CATEGORY_CATALOG_NUMBER, CodeRegistryService
from isrc_manager.history import HistoryManager, HistoryRecoveryError
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
from isrc_manager.tasks.history_helpers import run_file_history_action, run_snapshot_history_action
from isrc_manager.theme_builder import theme_setting_defaults


class HistoryManagerTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.db_path = self.root / "Database" / "library.db"
        self.settings_path = self.root / "settings.ini"
        self.history_root = self.root / "history"
        self.data_root = self.root / "data"
        self.backups_root = self.root / "backups"
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.backups_root.mkdir(parents=True, exist_ok=True)
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
            self.backups_root,
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

    def _write_backup_file(self, name: str = "library_backup.db") -> Path:
        backup_path = self.backups_root / name
        backup_path.write_bytes(b"SQLite backup bytes")
        return backup_path

    def _snapshot_create_entry(self, snapshot_id: int):
        for entry in self.history.list_entries(limit=200, include_hidden=True):
            if entry.action_type == "snapshot.create" and str(entry.entity_id or "") == str(
                int(snapshot_id)
            ):
                return entry
        self.fail(f"Could not find snapshot.create entry for snapshot {snapshot_id}")

    def case_setting_change_undo_and_redo_are_persistent(self):
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

    def case_auto_snapshot_setting_changes_undo_and_redo(self):
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

    def case_history_retention_setting_changes_undo_and_redo(self):
        self.settings_mutations.set_history_retention_mode("balanced")
        self.settings_mutations.set_history_auto_cleanup_enabled(True)
        self.settings_mutations.set_history_storage_budget_mb(2048)
        self.settings_mutations.set_history_auto_snapshot_keep_latest(25)
        self.settings_mutations.set_history_prune_pre_restore_copies_after_days(0)

        self.history.record_setting_change(
            key="history_retention_mode",
            label="Set History Retention Level: Lean",
            before_value="balanced",
            after_value="lean",
        )
        self.settings_mutations.set_history_retention_mode("lean")

        self.history.record_setting_change(
            key="history_auto_cleanup_enabled",
            label="History Automatic Cleanup Disabled",
            before_value=True,
            after_value=False,
        )
        self.settings_mutations.set_history_auto_cleanup_enabled(False)

        self.history.record_setting_change(
            key="history_storage_budget_mb",
            label="Set History Storage Budget: 1024 MB",
            before_value=2048,
            after_value=1024,
        )
        self.settings_mutations.set_history_storage_budget_mb(1024)

        self.history.record_setting_change(
            key="history_auto_snapshot_keep_latest",
            label="Set Automatic Snapshot Retention: 12",
            before_value=25,
            after_value=12,
        )
        self.settings_mutations.set_history_auto_snapshot_keep_latest(12)

        self.history.record_setting_change(
            key="history_prune_pre_restore_copies_after_days",
            label="Set Pre-Restore Backup Prune Age: 14 days",
            before_value=0,
            after_value=14,
        )
        self.settings_mutations.set_history_prune_pre_restore_copies_after_days(14)

        settings = self.settings_reads.load_history_retention_settings()
        self.assertEqual(settings.retention_mode, "lean")
        self.assertFalse(settings.auto_cleanup_enabled)
        self.assertEqual(settings.storage_budget_mb, 1024)
        self.assertEqual(settings.auto_snapshot_keep_latest, 12)
        self.assertEqual(settings.prune_pre_restore_copies_after_days, 14)

        self.history.undo()
        self.assertEqual(
            self.settings_reads.load_history_prune_pre_restore_copies_after_days(),
            0,
        )

        self.history.undo()
        self.assertEqual(self.settings_reads.load_history_auto_snapshot_keep_latest(), 25)

        self.history.undo()
        self.assertEqual(self.settings_reads.load_history_storage_budget_mb(), 2048)

        self.history.undo()
        self.assertTrue(self.settings_reads.load_history_auto_cleanup_enabled())

        self.history.undo()
        self.assertEqual(self.settings_reads.load_history_retention_mode(), "balanced")

        self.history.redo()
        self.assertEqual(self.settings_reads.load_history_retention_mode(), "lean")

        self.history.redo()
        self.assertFalse(self.settings_reads.load_history_auto_cleanup_enabled())

        self.history.redo()
        self.assertEqual(self.settings_reads.load_history_storage_budget_mb(), 1024)

        self.history.redo()
        self.assertEqual(self.settings_reads.load_history_auto_snapshot_keep_latest(), 12)

        self.history.redo()
        self.assertEqual(
            self.settings_reads.load_history_prune_pre_restore_copies_after_days(),
            14,
        )

    def case_expanded_theme_settings_undo_and_redo_restore_new_fields(self):
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

    def case_track_create_delete_and_redo_work_through_history(self):
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

    def case_record_event_and_missing_track_recording_errors_are_explicit(self):
        event_id = self.history.record_event(
            label="Import Dry Run",
            action_type="import.preview",
            entity_type="Import",
            entity_id="dry-run",
            payload={"rows": 0},
            visible_in_history=False,
        )
        event = self.history.fetch_entry(event_id)
        self.assertIsNotNone(event)
        self.assertFalse(event.reversible)
        self.assertFalse(event.visible_in_history)
        self.assertEqual(event.payload["rows"], 0)

        with self.assertRaisesRegex(ValueError, "Track 999999 not found after create"):
            self.history.record_track_create(
                track_id=999999,
                cleanup_artist_names=[],
                cleanup_album_titles=[],
            )

        track_id = self._create_track(title="Missing Update Source")
        before_update = self.track_service.fetch_track_snapshot(track_id)
        self.assertIsNotNone(before_update)
        self.track_service.delete_track(track_id)

        with self.assertRaisesRegex(ValueError, f"Track {track_id} not found after update"):
            self.history.record_track_update(
                before_snapshot=before_update,
                cleanup_artist_names=[],
                cleanup_album_titles=[],
            )

    def case_track_update_and_snapshot_restore_round_trip(self):
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

    def case_snapshot_actions_restore_managed_license_files(self):
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

    def case_snapshot_actions_restore_custom_field_media_and_gs1_templates(self):
        custom_media_dir = self.data_root / "custom_field_media"
        gs1_templates_dir = self.data_root / "gs1_templates"
        custom_media_dir.mkdir(parents=True, exist_ok=True)
        gs1_templates_dir.mkdir(parents=True, exist_ok=True)
        custom_file = custom_media_dir / "waveform.bin"
        gs1_file = gs1_templates_dir / "template.pdf"
        custom_file.write_bytes(b"custom-field-media")
        gs1_file.write_bytes(b"%PDF-gs1-template")

        snapshot = self.history.capture_snapshot(
            kind="managed_roots",
            label="Before Managed Root Restore",
        )
        managed_directories = snapshot.manifest.get("managed_directories", {})
        self.assertTrue(managed_directories["custom_field_media"]["exists"])
        self.assertTrue(managed_directories["gs1_templates"]["exists"])

        custom_file.unlink()
        gs1_file.unlink()
        self.assertFalse(custom_file.exists())
        self.assertFalse(gs1_file.exists())

        self.history.restore_snapshot(snapshot.snapshot_id)
        self.assertTrue(custom_file.exists())
        self.assertEqual(custom_file.read_bytes(), b"custom-field-media")
        self.assertTrue(gs1_file.exists())
        self.assertEqual(gs1_file.read_bytes(), b"%PDF-gs1-template")

    def case_snapshot_actions_restore_contract_template_roots(self):
        sources_dir = self.data_root / "contract_template_sources"
        drafts_dir = self.data_root / "contract_template_drafts"
        artifacts_dir = self.data_root / "contract_template_artifacts"
        sources_dir.mkdir(parents=True, exist_ok=True)
        drafts_dir.mkdir(parents=True, exist_ok=True)
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        source_template = sources_dir / "template-source.txt"
        draft_template = drafts_dir / "template-draft.txt"
        artifact_pdf = artifacts_dir / "template-output.pdf"
        source_template.write_text("source-template-v1", encoding="utf-8")
        draft_template.write_text("draft-template-v1", encoding="utf-8")
        artifact_pdf.write_bytes(b"%PDF-1.4\ncontract-template-artifact\n")

        snapshot = self.history.capture_snapshot(
            kind="managed_roots",
            label="Before Contract Template Restore",
        )
        managed_directories = snapshot.manifest.get("managed_directories", {})
        self.assertTrue(managed_directories["contract_template_sources"]["exists"])
        self.assertTrue(managed_directories["contract_template_drafts"]["exists"])
        self.assertTrue(managed_directories["contract_template_artifacts"]["exists"])

        source_template.unlink()
        draft_template.unlink()
        artifact_pdf.unlink()
        self.assertFalse(source_template.exists())
        self.assertFalse(draft_template.exists())
        self.assertFalse(artifact_pdf.exists())

        self.history.restore_snapshot(snapshot.snapshot_id)
        self.assertTrue(source_template.exists())
        self.assertEqual(source_template.read_text(encoding="utf-8"), "source-template-v1")
        self.assertTrue(draft_template.exists())
        self.assertEqual(draft_template.read_text(encoding="utf-8"), "draft-template-v1")
        self.assertTrue(artifact_pdf.exists())
        self.assertEqual(artifact_pdf.read_bytes(), b"%PDF-1.4\ncontract-template-artifact\n")

    def case_snapshot_restore_sanitizes_legacy_text_custom_field_attachment_state(self):
        track_id = self._create_track()
        with self.conn:
            self.conn.execute("""
                INSERT INTO CustomFieldDefs(id, name, active, sort_order, field_type, options)
                VALUES (901, 'Mood Notes', 1, 1, 'text', NULL)
                """)
            self.conn.execute(
                """
                INSERT INTO CustomFieldValues(
                    track_id,
                    field_def_id,
                    value,
                    blob_value,
                    managed_file_path,
                    storage_mode,
                    filename,
                    mime_type,
                    size_bytes
                )
                VALUES (?, 901, ?, NULL, '', '', '', '', 0)
                """,
                (track_id, "Original Mood"),
            )

        snapshot = self.history.create_manual_snapshot("Before Legacy Text Custom Restore")

        snapshot_conn = sqlite3.connect(snapshot.db_snapshot_path)
        try:
            snapshot_conn.execute("DROP TRIGGER IF EXISTS trg_cfvalues_text_enforce_ins")
            snapshot_conn.execute("DROP TRIGGER IF EXISTS trg_cfvalues_text_enforce_upd")
            snapshot_conn.execute(
                """
                UPDATE CustomFieldValues
                SET blob_value=?,
                    managed_file_path=?,
                    storage_mode=?,
                    filename=?,
                    mime_type=?,
                    size_bytes=?
                WHERE track_id=? AND field_def_id=901
                """,
                (
                    sqlite3.Binary(b"legacy"),
                    "custom_field_media/legacy.bin",
                    "database",
                    "legacy.bin",
                    "application/octet-stream",
                    6,
                    track_id,
                ),
            )
            snapshot_conn.commit()
        finally:
            snapshot_conn.close()

        with self.conn:
            self.conn.execute(
                "UPDATE CustomFieldValues SET value=? WHERE track_id=? AND field_def_id=901",
                ("Updated Mood", track_id),
            )

        self.history.restore_snapshot(snapshot.snapshot_id)

        restored = self.conn.execute(
            """
            SELECT value, blob_value, managed_file_path, storage_mode, filename, mime_type, size_bytes
            FROM CustomFieldValues
            WHERE track_id=? AND field_def_id=901
            """,
            (track_id,),
        ).fetchone()
        self.assertEqual(restored, ("Original Mood", None, "", "", "", "", 0))

    def case_registered_snapshot_can_be_restored(self):
        snapshot = self.history.create_manual_snapshot("Initial State")
        registered = self.history.register_snapshot(
            snapshot, kind="registered", label="Registered Initial State"
        )
        self.assertNotEqual(snapshot.snapshot_id, registered.snapshot_id)

        track_id = self._create_track()
        self.assertIsNotNone(self.track_service.fetch_track_snapshot(track_id))

        self.history.restore_snapshot_as_action(registered.snapshot_id)
        self.assertIsNone(self.track_service.fetch_track_snapshot(track_id))

    def case_manual_snapshot_create_and_delete_can_be_undone(self):
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

    def case_setting_bundle_change_restores_qpoint_and_coalesces(self):
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

    def case_hidden_internal_entries_are_skipped_by_visible_history_and_boundary_undo(self):
        visible_key = "display/action_ribbon_visible"
        hidden_key = "display/catalog_table_panel"
        self.settings.setValue(visible_key, False)
        self.settings.setValue(hidden_key, False)
        self.settings.sync()

        before_visible = self.history.capture_setting_states([visible_key])
        self.settings.setValue(visible_key, True)
        self.settings.sync()
        after_visible = self.history.capture_setting_states([visible_key])
        visible_entry = self.history.record_setting_bundle_change(
            label="Update Settings",
            before_entries=before_visible,
            after_entries=after_visible,
            entity_id=visible_key,
            visible_in_history=True,
        )

        before_hidden = self.history.capture_setting_states([hidden_key])
        self.settings.setValue(hidden_key, True)
        self.settings.sync()
        after_hidden = self.history.capture_setting_states([hidden_key])
        hidden_entry = self.history.record_setting_bundle_change(
            label="Internal UI Sync",
            before_entries=before_hidden,
            after_entries=after_hidden,
            entity_id=hidden_key,
            visible_in_history=False,
        )

        visible_entries = self.history.list_entries(limit=20)
        self.assertEqual([entry.label for entry in visible_entries], ["Update Settings"])
        self.assertTrue(visible_entries[0].is_current)
        self.assertEqual(self.history.describe_undo(), "Update Settings")
        self.assertEqual(self.history.get_current_entry_id(), hidden_entry.entry_id)
        self.assertEqual(self.history.get_current_visible_entry_id(), visible_entry.entry_id)

        all_entries = self.history.list_entries(limit=20, include_hidden=True)
        self.assertEqual(
            [entry.label for entry in all_entries],
            ["Internal UI Sync", "Update Settings"],
        )
        self.assertFalse(all_entries[0].visible_in_history)
        self.assertTrue(all_entries[1].visible_in_history)

        undone = self.history.undo()
        self.assertIsNotNone(undone)
        self.assertEqual(undone.entry_id, visible_entry.entry_id)
        self.assertFalse(self.settings.value(visible_key, False, bool))
        self.assertFalse(self.settings.value(hidden_key, False, bool))
        self.assertEqual(self.history.describe_redo(), "Update Settings")

        redone = self.history.redo()
        self.assertIsNotNone(redone)
        self.assertEqual(redone.entry_id, visible_entry.entry_id)
        self.assertTrue(self.settings.value(visible_key, False, bool))
        self.assertTrue(self.settings.value(hidden_key, False, bool))
        self.assertEqual(self.history.get_current_entry_id(), hidden_entry.entry_id)

    def case_setting_entry_application_and_serialization_edges_round_trip(self):
        self.settings.setValue("history/remove_me", "present")
        self.settings.sync()

        self.history.apply_setting_entries(
            [
                {
                    "setting_key": "history/remove_me",
                    "exists": False,
                    "serialized": None,
                }
            ]
        )

        self.assertFalse(self.settings.contains("history/remove_me"))

        qbyte_payload = self.history._serialize_setting_value(QByteArray(b"qt-state"))
        bytes_payload = self.history._serialize_setting_value(b"raw-state")
        list_payload = self.history._serialize_setting_value([QPoint(3, 4), b"nested"])
        tuple_payload = self.history._serialize_setting_value((QPoint(5, 6), "tuple"))

        self.assertEqual(
            bytes(self.history._deserialize_setting_value(qbyte_payload)),
            b"qt-state",
        )
        self.assertEqual(self.history._deserialize_setting_value(bytes_payload), b"raw-state")
        self.assertEqual(
            self.history._deserialize_setting_value(list_payload),
            [QPoint(3, 4), b"nested"],
        )
        self.assertEqual(
            self.history._deserialize_setting_value(tuple_payload),
            (QPoint(5, 6), "tuple"),
        )

    def case_snapshot_actions_restore_external_file_side_effects(self):
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

    def case_snapshot_side_effect_failure_rolls_back_database_and_files(self):
        before = self.history.capture_snapshot(
            kind="pre_failed_side_effect", label="Before failed side effect"
        )
        track_id = self._create_track(title="Rollback Side Effect Track")
        export_path = self.root / "exports" / "side-effect.txt"
        export_path.parent.mkdir(parents=True, exist_ok=True)
        export_path.write_text("after", encoding="utf-8")
        after_state = self.history.capture_file_state(export_path)
        after = self.history.capture_snapshot(
            kind="post_failed_side_effect", label="After failed side effect"
        )

        self.history.record_snapshot_action(
            label="Create Track With Failed File Effect",
            action_type="track.create_with_file_effect",
            entity_type="Track",
            entity_id=str(track_id),
            payload={
                "file_effects": [
                    {"target_path": ""},
                    {
                        "target_path": str(export_path),
                        "before_state": {
                            "target_path": str(export_path),
                            "companion_suffixes": [],
                            "exists": True,
                            "files": [
                                {
                                    "suffix": "",
                                    "artifact_path": str(self.root / "missing-before-artifact.bin"),
                                }
                            ],
                        },
                        "after_state": after_state,
                    },
                    {
                        "target_path": str(export_path),
                    },
                ]
            },
            snapshot_before_id=before.snapshot_id,
            snapshot_after_id=after.snapshot_id,
        )

        with self.assertRaises(HistoryRecoveryError):
            self.history.undo()

        self.assertIsNotNone(self.track_service.fetch_track_snapshot(track_id))
        self.assertTrue(export_path.exists())
        self.assertEqual(export_path.read_text(encoding="utf-8"), "after")

    def case_snapshot_actions_restore_legacy_license_migration_state(self):
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

    def case_snapshot_restore_preserves_audit_log_and_supports_undo_redo(self):
        snapshot = self.history.create_manual_snapshot("Before Audit Restore")
        self.conn.execute(
            "INSERT INTO AuditLog (action, entity, ref_id, details) VALUES (?, ?, ?, ?)",
            ("TEST", "Audit", "1", "seed row"),
        )
        self.conn.commit()

        track_id = self._create_track(title="Audited Song")
        self.assertIsNotNone(self.track_service.fetch_track_snapshot(track_id))

        entry = self.history.restore_snapshot_as_action(snapshot.snapshot_id)

        self.assertEqual(entry.action_type, "snapshot.restore")
        self.assertIsNone(self.track_service.fetch_track_snapshot(track_id))
        audit_count_after_restore = self.conn.execute("SELECT COUNT(*) FROM AuditLog").fetchone()[0]
        self.assertEqual(audit_count_after_restore, 1)

        self.history.undo()
        self.assertIsNotNone(self.track_service.fetch_track_snapshot(track_id))
        self.assertEqual(self.history.get_current_entry_id(), entry.parent_id)

        self.history.redo()
        self.assertIsNone(self.track_service.fetch_track_snapshot(track_id))
        self.assertEqual(self.history.get_current_entry_id(), entry.entry_id)

    def case_snapshot_restore_preserves_immutable_code_registry_entries(self):
        registry = CodeRegistryService(self.conn)
        category = registry.fetch_category_by_system_key(BUILTIN_CATEGORY_CATALOG_NUMBER)
        self.assertIsNotNone(category)
        assert category is not None
        registry.update_category(category.id, prefix="ACR")
        generated = registry.generate_next_code(
            category_id=category.id,
            created_via="test.history.snapshot",
        ).entry
        track_id = self._create_track(title="Registry Linked Song")
        self.conn.execute(
            """
            UPDATE Tracks
            SET catalog_number=?,
                catalog_registry_entry_id=?
            WHERE id=?
            """,
            (generated.value, generated.id, track_id),
        )
        self.conn.commit()
        snapshot = self.history.create_manual_snapshot("Registry linked snapshot")

        entry = self.history.restore_snapshot_as_action(snapshot.snapshot_id)

        self.assertEqual(entry.action_type, "snapshot.restore")
        restored_track = self.track_service.fetch_track_snapshot(track_id)
        self.assertIsNotNone(restored_track)
        restored_link = self.conn.execute(
            """
            SELECT catalog_registry_entry_id
            FROM Tracks
            WHERE id=?
            """,
            (track_id,),
        ).fetchone()
        self.assertIsNotNone(restored_link)
        assert restored_link is not None
        self.assertEqual(restored_link[0], generated.id)
        self.assertIsNotNone(registry.fetch_entry(generated.id))

    def case_snapshot_history_undo_redo_does_not_duplicate_entries(self):
        created_track_id = run_snapshot_history_action(
            history_manager=self.history,
            action_label="Create Track: Snapshot Path",
            action_type="track.create",
            entity_type="Track",
            entity_id="snapshot-path",
            payload={"track_title": "Snapshot Path"},
            mutation=lambda: self.track_service.create_track(
                TrackCreatePayload(
                    isrc="NL-ABC-26-00044",
                    track_title="Snapshot Path",
                    artist_name="Snapshot Artist",
                    additional_artists=[],
                    album_title=None,
                    release_date="2026-03-18",
                    track_length_sec=120,
                    iswc=None,
                    upc=None,
                    genre=None,
                )
            ),
        )
        self.conn.execute(
            "INSERT INTO AuditLog (action, entity, ref_id, details) VALUES (?, ?, ?, ?)",
            ("TEST", "Track", str(created_track_id), "seed row"),
        )
        self.conn.commit()

        self.assertEqual(len(self.history.list_entries(limit=20)), 1)

        self.history.undo()
        self.assertIsNone(self.track_service.fetch_track_snapshot(created_track_id))
        self.assertEqual(len(self.history.list_entries(limit=20)), 1)

        self.history.redo()
        self.assertIsNotNone(self.track_service.fetch_track_snapshot(created_track_id))
        self.assertEqual(len(self.history.list_entries(limit=20)), 1)

    def case_branching_after_undo_supersedes_old_redo(self):
        self.settings_mutations.set_isrc_prefix("NLAAA")
        first = self.history.record_setting_change(
            key="isrc_prefix",
            label="Set ISRC Prefix: NLAAA",
            before_value="",
            after_value="NLAAA",
        )
        self.settings_mutations.set_isrc_prefix("NLBBB")
        second = self.history.record_setting_change(
            key="isrc_prefix",
            label="Set ISRC Prefix: NLBBB",
            before_value="NLAAA",
            after_value="NLBBB",
        )

        self.history.undo()
        self.assertEqual(self.history.get_default_redo_entry().entry_id, second.entry_id)

        self.settings_mutations.set_isrc_prefix("NLCCC")
        third = self.history.record_setting_change(
            key="isrc_prefix",
            label="Set ISRC Prefix: NLCCC",
            before_value="NLAAA",
            after_value="NLCCC",
        )

        self.assertEqual(third.parent_id, first.entry_id)
        self.assertIsNone(self.history.get_default_redo_entry())
        self.assertEqual(self.history.fetch_entry(second.entry_id).status, "superseded")

    def case_redo_and_corrupted_snapshot_boundaries_fail_explicitly(self):
        self.assertIsNone(self.history.undo())
        self.assertIsNone(self.history.redo(entry_id=999999))

        self.settings_mutations.set_isrc_prefix("NLRED")
        applied_entry = self.history.record_setting_change(
            key="isrc_prefix",
            label="Set ISRC Prefix: NLRED",
            before_value="",
            after_value="NLRED",
        )
        with self.assertRaisesRegex(HistoryRecoveryError, "not redoable"):
            self.history.redo(applied_entry.entry_id)

        snapshot_after = self.history.capture_snapshot(
            kind="corrupted_boundary", label="Corrupted Boundary"
        )
        self.history.record_snapshot_action(
            label="Corrupted Snapshot Boundary",
            action_type="snapshot.corrupted_boundary",
            snapshot_before_id=None,  # type: ignore[arg-type]
            snapshot_after_id=snapshot_after.snapshot_id,
        )

        with self.assertRaisesRegex(HistoryRecoveryError, "missing its undo snapshot"):
            self.history.undo()

    def case_missing_snapshot_file_raises_clear_error_without_creating_pre_restore_snapshot(self):
        snapshot = self.history.create_manual_snapshot("Missing Snapshot")
        snapshot_path = Path(snapshot.db_snapshot_path)
        snapshot_path.unlink()

        snapshot_count_before = len(self.history.list_snapshots(limit=100))

        with self.assertRaises(HistoryRecoveryError):
            self.history.restore_snapshot_as_action(snapshot.snapshot_id)

        self.assertEqual(len(self.history.list_snapshots(limit=100)), snapshot_count_before)

    def case_snapshot_restore_action_rolls_back_when_history_recording_fails_after_apply(self):
        track_id = self._create_track(title="Restore Rollback Source")
        snapshot = self.history.create_manual_snapshot("Restore Rollback Target")

        self.track_service.update_track(
            TrackUpdatePayload(
                track_id=track_id,
                isrc="NL-ABC-26-00101",
                track_title="Changed Before Restore Action",
                artist_name="Main Artist",
                additional_artists=["Guest Artist"],
                album_title="Debut Album",
                release_date="2026-03-13",
                track_length_sec=245,
                iswc=None,
                upc=None,
                genre="Pop",
            )
        )

        with patch.object(
            self.history,
            "record_snapshot_action",
            side_effect=RuntimeError("history recording failed after restore"),
        ):
            with self.assertRaisesRegex(RuntimeError, "history recording failed after restore"):
                self.history.restore_snapshot_as_action(snapshot.snapshot_id)

        current = self.track_service.fetch_track_snapshot(track_id)
        self.assertIsNotNone(current)
        self.assertEqual(current.track_title, "Changed Before Restore Action")
        self.assertFalse(
            any(
                record.label == "Before Snapshot Restore"
                for record in self.history.list_snapshots(limit=50)
            )
        )

    def case_snapshot_restore_rolls_back_database_when_external_restore_fails(self):
        track_id = self._create_track(title="Rollback Song")
        snapshot = self.history.create_manual_snapshot("Rollback Point")

        self.track_service.update_track(
            TrackUpdatePayload(
                track_id=track_id,
                isrc="NL-ABC-26-00077",
                track_title="Changed After Snapshot",
                artist_name="Main Artist",
                additional_artists=["Guest Artist"],
                album_title="Debut Album",
                release_date="2026-03-13",
                track_length_sec=245,
                iswc=None,
                upc=None,
                genre="Pop",
            )
        )

        with patch.object(
            self.history,
            "_apply_settings_state",
            side_effect=RuntimeError("settings restore failed"),
        ):
            with self.assertRaises(RuntimeError):
                self.history.restore_snapshot(snapshot.snapshot_id)

        current = self.track_service.fetch_track_snapshot(track_id)
        self.assertIsNotNone(current)
        self.assertEqual(current.track_title, "Changed After Snapshot")

    def case_snapshot_missing_delete_and_restore_boundaries_are_explicit(self):
        with self.assertRaisesRegex(ValueError, "Snapshot 999999 not found"):
            self.history.restore_snapshot_as_action(999999)
        with self.assertRaisesRegex(ValueError, "Snapshot 999999 not found"):
            self.history.restore_snapshot(999999)
        with self.assertRaisesRegex(ValueError, "Snapshot 999999 not found"):
            self.history.delete_snapshot(999999)
        with self.assertRaisesRegex(ValueError, "Snapshot 999999 not found"):
            self.history.delete_snapshot_as_action(999999)

        missing_snapshot = self.history.capture_snapshot(
            kind="manual", label="Missing Delete Target"
        )
        Path(missing_snapshot.db_snapshot_path).unlink()
        with self.assertRaises(FileNotFoundError):
            self.history.register_snapshot(missing_snapshot, kind="registered")

        entry = self.history.delete_snapshot_as_action(missing_snapshot.snapshot_id)

        self.assertEqual(entry.action_type, "snapshot.delete_missing")
        self.assertFalse(entry.reversible)
        self.assertIsNone(self.history.fetch_snapshot(missing_snapshot.snapshot_id))

        asset_snapshot = self.history.capture_snapshot(kind="manual", label="Asset Snapshot")
        asset_snapshot_path = Path(asset_snapshot.db_snapshot_path)
        asset_dir = asset_snapshot_path.with_suffix(".assets") / "licenses"
        asset_dir.mkdir(parents=True, exist_ok=True)
        (asset_dir / "asset.bin").write_bytes(b"asset")
        with self.conn:
            self.conn.execute(
                "UPDATE HistorySnapshots SET manifest_json=? WHERE id=?",
                (
                    json.dumps(
                        {
                            "managed_directories": {
                                "licenses": {
                                    "exists": True,
                                    "snapshot_path": str(asset_dir),
                                }
                            }
                        }
                    ),
                    asset_snapshot.snapshot_id,
                ),
            )

        self.history.delete_snapshot(asset_snapshot.snapshot_id)

        self.assertFalse(asset_dir.exists())

        before = self.history.capture_snapshot(kind="before_ref", label="Before Reference")
        after = self.history.capture_snapshot(kind="after_ref", label="After Reference")
        self.history.record_snapshot_action(
            label="Referenced Snapshot Action",
            action_type="snapshot.reference",
            snapshot_before_id=before.snapshot_id,
            snapshot_after_id=after.snapshot_id,
        )

        with self.assertRaisesRegex(ValueError, "referenced by history"):
            self.history.delete_snapshot(before.snapshot_id)

    def case_repair_recovery_state_relinks_missing_snapshot_and_registers_orphan_backup(self):
        snapshot = self.history.create_manual_snapshot("Repairable Snapshot")
        snapshot_path = Path(snapshot.db_snapshot_path)
        repaired_snapshot_path = snapshot_path.with_name(f"relinked_{snapshot_path.name}")
        snapshot_path.replace(repaired_snapshot_path)
        snapshot_sidecar = self.history._snapshot_sidecar_path(snapshot_path)
        repaired_sidecar = self.history._snapshot_sidecar_path(repaired_snapshot_path)
        if snapshot_sidecar.exists():
            snapshot_sidecar.replace(repaired_sidecar)

        missing_backup = self._write_backup_file("missing_backup.db")
        before_state = {
            "target_path": str(missing_backup),
            "companion_suffixes": [],
            "exists": False,
            "files": [],
        }
        after_state = self.history.capture_file_state(missing_backup)
        backup_entry = self.history.record_file_write_action(
            label="Create Database Backup",
            action_type="file.db_backup",
            target_path=missing_backup,
            before_state=before_state,
            after_state=after_state,
            entity_type="DB",
            entity_id=str(missing_backup),
            payload={"path": str(missing_backup), "method": "file_copy"},
        )
        backup_record = self.history.register_backup(
            missing_backup,
            kind="manual",
            label="Missing Backup",
            source_db_path=self.db_path,
            metadata={"method": "file_copy"},
        )
        missing_backup.unlink()

        orphan_backup = self._write_backup_file("orphan_backup.db")

        with self.conn:
            self.conn.execute("UPDATE HistoryHead SET current_entry_id=?", (9999,))

        issues_before = self.history.inspect_recovery_state()
        self.assertTrue(any(issue.issue_type == "stale_current_head" for issue in issues_before))
        self.assertTrue(
            any(
                issue.issue_type == "missing_snapshot_artifact"
                and issue.snapshot_id == snapshot.snapshot_id
                for issue in issues_before
            )
        )
        self.assertTrue(
            any(
                issue.issue_type == "missing_backup_file"
                and issue.backup_id == backup_record.backup_id
                for issue in issues_before
            )
        )
        self.assertTrue(
            any(
                issue.issue_type == "orphan_backup_file" and issue.path == str(orphan_backup)
                for issue in issues_before
            )
        )

        repair_result = self.history.repair_recovery_state()
        self.assertTrue(repair_result.changes)
        self.assertFalse(repair_result.unresolved)

        repaired_snapshot = self.history.fetch_snapshot(snapshot.snapshot_id)
        self.assertIsNotNone(repaired_snapshot)
        self.assertTrue(Path(repaired_snapshot.db_snapshot_path).exists())
        repaired_backup = self.history.fetch_backup(backup_record.backup_id)
        self.assertIsNotNone(repaired_backup)
        self.assertEqual(repaired_backup.backup_path, str(missing_backup))
        self.assertTrue(missing_backup.exists())
        self.assertEqual(
            self.history.fetch_entry(backup_entry.entry_id).entry_id, backup_entry.entry_id
        )
        registered_orphan_backups = [
            backup
            for backup in self.history.list_backups(limit=20)
            if backup.backup_path == str(orphan_backup)
        ]
        self.assertEqual(len(registered_orphan_backups), 1)
        repaired_head_id = self.history.get_current_entry_id()
        self.assertIsNotNone(repaired_head_id)
        self.assertIsNotNone(self.history.fetch_entry(repaired_head_id))

        second_pass = self.history.repair_recovery_state()
        self.assertFalse(second_pass.unresolved)

    def case_repair_recovery_state_rebuilds_missing_backup_history_artifacts(self):
        backup_path = self._write_backup_file("artifact_repair_backup.db")
        before_state = {
            "target_path": str(backup_path),
            "companion_suffixes": [],
            "exists": False,
            "files": [],
        }
        after_state = self.history.capture_file_state(backup_path)
        entry = self.history.record_file_write_action(
            label="Create Database Backup",
            action_type="file.db_backup",
            target_path=backup_path,
            before_state=before_state,
            after_state=after_state,
            entity_type="DB",
            entity_id=str(backup_path),
            payload={"path": str(backup_path), "method": "file_copy"},
        )

        for file_info in after_state["files"]:
            Path(file_info["artifact_path"]).unlink()

        issues_before = self.history.inspect_recovery_state()
        self.assertTrue(
            any(
                issue.issue_type == "missing_backup_history_artifact"
                and issue.entry_id == entry.entry_id
                for issue in issues_before
            )
        )

        repair_result = self.history.repair_recovery_state()
        self.assertTrue(repair_result.changes)
        self.assertFalse(repair_result.unresolved)

        refreshed_entry = self.history.fetch_entry(entry.entry_id)
        self.assertIsNotNone(refreshed_entry)
        refreshed_state = (refreshed_entry.redo_payload or {}).get("state", {})
        self.assertTrue(refreshed_state.get("files"))
        self.assertTrue(
            all(Path(file_info["artifact_path"]).exists() for file_info in refreshed_state["files"])
        )

    def case_repair_recovery_state_removes_missing_backup_with_invalid_history_artifact(self):
        backup_path = self._write_backup_file("invalid_artifact_backup.db")
        before_state = {
            "target_path": str(backup_path),
            "companion_suffixes": [],
            "exists": False,
            "files": [],
        }
        after_state = self.history.capture_file_state(backup_path)
        for file_info in after_state["files"]:
            file_info["artifact_path"] = None
        entry = self.history.record_file_write_action(
            label="Create Database Backup",
            action_type="file.db_backup",
            target_path=backup_path,
            before_state=before_state,
            after_state=after_state,
            entity_type="DB",
            entity_id=str(backup_path),
            payload={"path": str(backup_path), "method": "file_copy"},
        )
        backup_record = self.history.register_backup(
            backup_path,
            kind="manual",
            label="Invalid Artifact Backup",
            source_db_path=self.db_path,
            metadata={"method": "file_copy"},
        )
        backup_path.unlink()

        issues_before = self.history.inspect_recovery_state()
        missing_backup_issue = next(
            issue
            for issue in issues_before
            if issue.issue_type == "missing_backup_file"
            and issue.backup_id == backup_record.backup_id
        )
        self.assertEqual(missing_backup_issue.entry_id, entry.entry_id)
        self.assertFalse(missing_backup_issue.details["recoverable_from_history"])

        repair_result = self.history.repair_recovery_state()
        self.assertTrue(repair_result.changes)
        self.assertFalse(repair_result.unresolved)
        self.assertIsNone(self.history.fetch_backup(backup_record.backup_id))

    def case_repair_recovery_state_relinks_moved_backup_sidecar(self):
        backup_path = self._write_backup_file("moved_backup.db")
        backup_record = self.history.register_backup(
            backup_path,
            kind="manual",
            label="Moved Backup",
            source_db_path=self.db_path,
        )
        moved_path = self.backups_root / "relinked_moved_backup.db"
        backup_path.replace(moved_path)
        self.history._backup_sidecar_path(backup_path).replace(
            self.history._backup_sidecar_path(moved_path)
        )

        issues = self.history.inspect_recovery_state()
        self.assertTrue(
            any(
                issue.issue_type == "missing_backup_file"
                and issue.backup_id == backup_record.backup_id
                for issue in issues
            )
        )

        repair_result = self.history.repair_recovery_state()

        refreshed = self.history.fetch_backup(backup_record.backup_id)
        self.assertIsNotNone(refreshed)
        self.assertEqual(refreshed.backup_path, str(moved_path))
        self.assertTrue(any("Re-linked backup" in change for change in repair_result.changes))

    def case_repair_recovery_state_recovers_removes_and_rebuilds_snapshot_archives(self):
        recoverable = self.history.create_manual_snapshot("Recoverable Archive Snapshot")
        recoverable_entry = self._snapshot_create_entry(recoverable.snapshot_id)
        archived_path = Path(
            recoverable_entry.redo_payload["archived_snapshot"]["db_snapshot_path"]
        )
        Path(recoverable.db_snapshot_path).unlink()

        recover_result = self.history.repair_recovery_state()

        recovered = self.history.fetch_snapshot(recoverable.snapshot_id)
        self.assertIsNotNone(recovered)
        self.assertEqual(Path(recovered.db_snapshot_path), archived_path)
        self.assertTrue(archived_path.exists())
        self.assertTrue(
            any("Recovered missing artifacts" in change for change in recover_result.changes)
        )

        stale = self.history.capture_snapshot(kind="manual", label="Stale Loose Snapshot")
        Path(stale.db_snapshot_path).unlink()

        remove_result = self.history.repair_recovery_state()

        self.assertIsNone(self.history.fetch_snapshot(stale.snapshot_id))
        self.assertTrue(any("Removed stale snapshot" in change for change in remove_result.changes))

        rebuild = self.history.create_manual_snapshot("Rebuild Archive Snapshot")
        rebuild_entry = self._snapshot_create_entry(rebuild.snapshot_id)
        old_archive_path = Path(rebuild_entry.redo_payload["archived_snapshot"]["db_snapshot_path"])
        old_archive_path.unlink()

        issues = self.history.inspect_recovery_state()
        self.assertTrue(
            any(
                issue.issue_type == "missing_snapshot_archive"
                and issue.entry_id == rebuild_entry.entry_id
                for issue in issues
            )
        )

        rebuild_result = self.history.repair_recovery_state()
        refreshed_entry = self.history.fetch_entry(rebuild_entry.entry_id)
        self.assertIsNotNone(refreshed_entry)
        rebuilt_path = Path(refreshed_entry.redo_payload["archived_snapshot"]["db_snapshot_path"])
        self.assertTrue(rebuilt_path.exists())
        self.assertNotEqual(rebuilt_path, old_archive_path)
        self.assertTrue(
            any("Rebuilt archived snapshot" in change for change in rebuild_result.changes)
        )

        delete_target = self.history.create_manual_snapshot("Delete Archive Rebuild Target")
        delete_entry = self.history.delete_snapshot_as_action(delete_target.snapshot_id)
        self.history.undo()
        refreshed_delete_entry = self.history.fetch_entry(delete_entry.entry_id)
        self.assertIsNotNone(refreshed_delete_entry)
        delete_archive_path = Path(
            refreshed_delete_entry.inverse_payload["archived_snapshot"]["db_snapshot_path"]
        )
        delete_archive_path.unlink()

        delete_rebuild_result = self.history.repair_recovery_state()
        rebuilt_delete_entry = self.history.fetch_entry(delete_entry.entry_id)
        self.assertIsNotNone(rebuilt_delete_entry)
        rebuilt_delete_path = Path(
            rebuilt_delete_entry.inverse_payload["archived_snapshot"]["db_snapshot_path"]
        )
        self.assertTrue(rebuilt_delete_path.exists())
        self.assertNotEqual(rebuilt_delete_path, delete_archive_path)
        self.assertTrue(
            any("Rebuilt archived snapshot" in change for change in delete_rebuild_result.changes)
        )

        unresolved = self.history.create_manual_snapshot("Unresolved Archive Snapshot")
        unresolved_entry = self._snapshot_create_entry(unresolved.snapshot_id)
        unresolved_archive_path = Path(
            unresolved_entry.redo_payload["archived_snapshot"]["db_snapshot_path"]
        )
        unresolved_archive_path.unlink()
        self.history._update_entry_payloads(
            unresolved_entry.entry_id,
            payload={"snapshot_id": 987654, "label": unresolved.label},
        )

        unresolved_result = self.history.repair_recovery_state()

        self.assertTrue(
            any(
                "missing archived snapshot artifacts" in item
                for item in unresolved_result.unresolved
            )
        )

    def case_inspect_recovery_state_reports_dangling_snapshot_references(self):
        before = self.history.capture_snapshot(kind="before_dangling", label="Before Dangling")
        after = self.history.capture_snapshot(kind="after_dangling", label="After Dangling")
        entry = self.history.record_snapshot_action(
            label="Dangling Snapshot Reference",
            action_type="snapshot.dangling",
            snapshot_before_id=before.snapshot_id,
            snapshot_after_id=after.snapshot_id,
        )
        with self.conn:
            self.conn.execute("DELETE FROM HistorySnapshots WHERE id=?", (before.snapshot_id,))

        issues = self.history.inspect_recovery_state()

        self.assertTrue(
            any(
                issue.issue_type == "dangling_snapshot_reference"
                and issue.entry_id == entry.entry_id
                and issue.snapshot_id == before.snapshot_id
                for issue in issues
            )
        )

    def case_repair_recovery_state_handles_orphan_sidecar_conflicts(self):
        live_snapshot = self.history.capture_snapshot(kind="manual", label="Live Snapshot")
        orphan_snapshot = self.history.capture_snapshot(kind="manual", label="Snapshot Orphan")
        orphan_snapshot_path = Path(orphan_snapshot.db_snapshot_path)
        self.history._write_json_sidecar(
            self.history._snapshot_sidecar_path(orphan_snapshot_path),
            {
                "snapshot_id": live_snapshot.snapshot_id,
                "kind": "manual",
                "label": "Snapshot Conflict Orphan",
                "settings_state": {},
                "manifest": {},
            },
        )
        with self.conn:
            self.conn.execute(
                "DELETE FROM HistorySnapshots WHERE id=?",
                (orphan_snapshot.snapshot_id,),
            )

        no_sidecar_snapshot = self.history.capture_snapshot(
            kind="manual", label="No Sidecar Orphan"
        )
        no_sidecar_path = Path(no_sidecar_snapshot.db_snapshot_path)
        self.history._snapshot_sidecar_path(no_sidecar_path).unlink()
        with self.conn:
            self.conn.execute(
                "DELETE FROM HistorySnapshots WHERE id=?",
                (no_sidecar_snapshot.snapshot_id,),
            )

        existing_backup_path = self._write_backup_file("existing_conflict_backup.db")
        existing_backup = self.history.register_backup(
            existing_backup_path,
            kind="manual",
            label="Existing Backup",
            source_db_path=self.db_path,
        )
        orphan_backup_path = self._write_backup_file("orphan_conflict_backup.db")
        self.history._write_json_sidecar(
            self.history._backup_sidecar_path(orphan_backup_path),
            {
                "backup_id": existing_backup.backup_id,
                "kind": "pre_restore",
                "label": "Backup Conflict Orphan",
                "source_db_path": str(self.db_path),
                "metadata": {"method": "copy"},
            },
        )

        repair_result = self.history.repair_recovery_state()

        registered_snapshots = [
            snapshot
            for snapshot in self.history.list_snapshots(limit=50)
            if snapshot.db_snapshot_path == str(orphan_snapshot_path)
        ]
        self.assertEqual(len(registered_snapshots), 1)
        self.assertNotEqual(registered_snapshots[0].snapshot_id, live_snapshot.snapshot_id)
        self.assertEqual(registered_snapshots[0].label, "Snapshot Conflict Orphan")
        self.assertTrue(any("no sidecar metadata" in item for item in repair_result.unresolved))

        registered_backups = [
            backup
            for backup in self.history.list_backups(limit=50)
            if backup.backup_path == str(orphan_backup_path)
        ]
        self.assertEqual(len(registered_backups), 1)
        self.assertNotEqual(registered_backups[0].backup_id, existing_backup.backup_id)
        self.assertEqual(registered_backups[0].kind, "pre_restore")
        self.assertEqual(registered_backups[0].source_db_path, str(self.db_path))

    def case_run_snapshot_history_action_rolls_back_when_history_recording_fails(self):
        with patch.object(
            self.history,
            "record_snapshot_action",
            side_effect=RuntimeError("history recording failed"),
        ):
            with self.assertRaises(RuntimeError):
                run_snapshot_history_action(
                    history_manager=self.history,
                    action_label="Create Track: Rollback",
                    action_type="track.create",
                    entity_type="Track",
                    entity_id="rollback",
                    payload={"track_title": "Rollback"},
                    mutation=lambda: self.track_service.create_track(
                        TrackCreatePayload(
                            isrc="NL-ABC-26-00088",
                            track_title="Rollback",
                            artist_name="Rollback Artist",
                            additional_artists=[],
                            album_title=None,
                            release_date="2026-03-18",
                            track_length_sec=90,
                            iswc=None,
                            upc=None,
                            genre=None,
                        )
                    ),
                )

        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM Tracks").fetchone()[0], 0)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM HistorySnapshots").fetchone()[0], 0
        )

    def case_restore_snapshot_missing_file_does_not_create_extra_restore_point(self):
        snapshot = self.history.create_manual_snapshot("Missing Restore Target")
        Path(snapshot.db_snapshot_path).unlink()

        before_snapshot_ids = [
            record.snapshot_id for record in self.history.list_snapshots(limit=20)
        ]
        with self.assertRaises(HistoryRecoveryError):
            self.history.restore_snapshot_as_action(snapshot.snapshot_id)

        after_snapshot_ids = [
            record.snapshot_id for record in self.history.list_snapshots(limit=20)
        ]
        self.assertEqual(after_snapshot_ids, before_snapshot_ids)

    def case_snapshot_helper_rolls_back_when_history_recording_fails(self):
        snapshot_count_before = len(self.history.list_snapshots(limit=50))

        with patch.object(
            self.history,
            "record_snapshot_action",
            side_effect=RuntimeError("history capture failed"),
        ):
            with self.assertRaises(RuntimeError):
                run_snapshot_history_action(
                    history_manager=self.history,
                    action_label="Create Track via Helper",
                    action_type="track.helper_create",
                    mutation=lambda: self._create_track(title="Helper Rollback"),
                )

        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM Tracks").fetchone()[0], 0)
        self.assertEqual(len(self.history.list_snapshots(limit=50)), snapshot_count_before)

    def case_file_helper_rolls_back_when_history_recording_fails(self):
        export_path = self.root / "exports" / "helper.txt"

        def mutation():
            export_path.parent.mkdir(parents=True, exist_ok=True)
            export_path.write_text("helper", encoding="utf-8")
            return str(export_path)

        with patch.object(
            self.history,
            "record_file_write_action",
            side_effect=RuntimeError("file history capture failed"),
        ):
            with self.assertRaises(RuntimeError):
                run_file_history_action(
                    history_manager=self.history,
                    action_label="Write Helper Export",
                    action_type="file.helper_export",
                    target_path=export_path,
                    mutation=mutation,
                )

        self.assertFalse(export_path.exists())

    def case_file_helper_rejects_directory_target_before_mutation(self):
        export_dir = self.root / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        mutation_called = False

        def mutation():
            nonlocal mutation_called
            mutation_called = True
            return str(export_dir / "should-not-run.txt")

        with self.assertRaisesRegex(ValueError, "requires a file path, not a directory"):
            run_file_history_action(
                history_manager=self.history,
                action_label="Write Helper Export",
                action_type="file.helper_export",
                target_path=export_dir,
                mutation=mutation,
            )

        self.assertFalse(mutation_called)

    def case_file_state_rejects_directory_targets(self):
        target_dir = self.root / "file-state-directory"
        target_dir.mkdir(parents=True, exist_ok=True)

        with self.assertRaisesRegex(ValueError, "capture requires a file path"):
            self.history.capture_file_state(target_dir)
        with self.assertRaisesRegex(ValueError, "restore requires a file path"):
            self.history.restore_file_state(target_dir, {"companion_suffixes": [], "files": []})

    def case_backup_registration_delete_and_file_restore_errors_are_explicit(self):
        self.assertFalse(self.history.can_redo())
        self.assertIsNone(self.history.describe_redo())
        self.assertIsNone(self.history.fetch_backup(999999))
        with self.assertRaises(FileNotFoundError):
            self.history.register_backup(self.backups_root / "missing.db")
        with self.assertRaisesRegex(ValueError, "Backup 999999 not found"):
            self.history.delete_backup(999999)

        backup_path = self._write_backup_file("delete_me_backup.db")
        companions = [
            Path(f"{backup_path}{suffix}")
            for suffix in self.history.DATABASE_ARTIFACT_COMPANION_SUFFIXES
        ]
        for companion in companions:
            companion.write_bytes(b"companion")
        backup = self.history.register_backup(
            backup_path,
            kind="manual",
            label="Delete Me Backup",
            source_db_path=self.db_path,
            metadata={"method": "file_copy"},
        )
        sidecar = self.history._backup_sidecar_path(backup_path)

        self.assertEqual(self.history.fetch_backup(backup.backup_id), backup)
        self.assertEqual(self.history.list_backups(limit=1), [backup])
        self.assertTrue(sidecar.exists())

        self.history.delete_backup(backup.backup_id)

        self.assertIsNone(self.history.fetch_backup(backup.backup_id))
        self.assertFalse(backup_path.exists())
        self.assertFalse(sidecar.exists())
        self.assertTrue(all(not companion.exists() for companion in companions))

        with self.assertRaises(HistoryRecoveryError):
            self.history.restore_file_state(
                self.root / "restore-target.txt",
                {"companion_suffixes": [], "files": [{}]},
            )
        with self.assertRaises(HistoryRecoveryError):
            self.history.restore_file_state(
                self.root / "restore-target.txt",
                {
                    "companion_suffixes": [],
                    "files": [{"suffix": "", "artifact_path": str(self.root / "missing.bin")}],
                },
            )

    def case_repair_recovery_state_quarantines_referenced_missing_snapshot(self):
        before = self.history.capture_snapshot(kind="pre_quarantine", label="Before quarantine")
        created_track_id = self._create_track(title="Quarantine Target")
        after = self.history.capture_snapshot(kind="post_quarantine", label="After quarantine")
        entry = self.history.record_snapshot_action(
            label="Create Track Snapshot Action",
            action_type="track.snapshot_create",
            entity_type="Track",
            entity_id=str(created_track_id),
            payload={"track_id": created_track_id},
            snapshot_before_id=before.snapshot_id,
            snapshot_after_id=after.snapshot_id,
        )

        Path(before.db_snapshot_path).unlink()

        repair_result = self.history.repair_recovery_state()
        self.assertTrue(repair_result.changes)

        repaired_entry = self.history.fetch_entry(entry.entry_id)
        self.assertIsNotNone(repaired_entry)
        self.assertFalse(repaired_entry.reversible)
        self.assertEqual(repaired_entry.status, self.history.STATUS_ARTIFACT_MISSING)
        self.assertIsNone(repaired_entry.snapshot_before_id)
        self.assertIsNotNone(self.history.fetch_snapshot(after.snapshot_id))
        self.assertIsNone(self.history.fetch_snapshot(before.snapshot_id))


if __name__ == "__main__":
    unittest.main()


def load_tests(loader, tests, pattern):
    return unittest.TestSuite()

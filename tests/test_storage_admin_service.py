import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    from PySide6.QtCore import QSettings
except ImportError as exc:  # pragma: no cover - environment-specific fallback
    QSettings = None
    QT_IMPORT_ERROR = exc
else:
    QT_IMPORT_ERROR = None

from isrc_manager import update_handoff
from isrc_manager.history import HistoryManager, SessionHistoryManager
from isrc_manager.paths import resolve_app_storage_layout
from isrc_manager.services import DatabaseSchemaService, DatabaseSessionService
from isrc_manager.storage_admin import (
    STATUS_DELETED_PROFILE,
    STATUS_IN_USE,
    STATUS_ORPHANED,
    STATUS_OTHER,
    STATUS_RECOVERABILITY,
    ApplicationStorageAdminService,
    StorageAdminItem,
    StorageAdminReference,
)


class StorageAdminServiceTests(unittest.TestCase):
    def setUp(self):
        if QSettings is None:
            raise unittest.SkipTest(f"PySide6 QtCore unavailable: {QT_IMPORT_ERROR}")
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.settings_path = self.root / "settings.ini"
        self.settings = QSettings(str(self.settings_path), QSettings.IniFormat)
        self.settings.setFallbacksEnabled(False)
        self.layout = resolve_app_storage_layout(
            settings=self.settings,
            active_data_root=self.root,
        )
        for directory in self.layout.iter_standard_dirs():
            directory.mkdir(parents=True, exist_ok=True)

        self.db_path = self.layout.database_dir / "library.db"
        self.deleted_profile_path = self.layout.database_dir / "removed.db"

        session = DatabaseSessionService().open(self.db_path)
        self.conn = session.conn
        schema = DatabaseSchemaService(self.conn, data_root=self.layout.data_root)
        schema.init_db()
        schema.migrate_schema()
        self.history = HistoryManager(
            self.conn,
            self.settings,
            self.db_path,
            self.layout.history_dir,
            self.layout.data_root,
            self.layout.backups_dir,
        )
        self.service = ApplicationStorageAdminService(self.layout)

        self.conn.execute("""
            INSERT INTO Parties(legal_name, display_name, artist_name, party_type)
            VALUES ('Test Artist', 'Test Artist', 'Test Artist', 'artist')
            """)
        artist_id = int(self.conn.execute("SELECT id FROM Parties").fetchone()[0])

        self.live_audio_path = self.layout.data_root / "track_media" / "live_audio.wav"
        self.live_audio_path.write_bytes(b"live-audio")
        self.orphan_audio_path = self.layout.data_root / "track_media" / "orphan_audio.wav"
        self.orphan_audio_path.write_bytes(b"orphan-audio")
        self.conn.execute(
            """
            INSERT INTO Tracks (
                isrc,
                isrc_compact,
                track_title,
                main_artist_party_id,
                audio_file_path,
                audio_file_storage_mode,
                audio_file_size_bytes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "NLABC2500001",
                "NLABC2500001",
                "Live Track",
                artist_id,
                str(self.live_audio_path.relative_to(self.layout.data_root)),
                "managed_file",
                self.live_audio_path.stat().st_size,
            ),
        )
        self.conn.commit()

        self.protected_snapshot = self.history.create_manual_snapshot("Protected Snapshot")
        self.loose_snapshot = self.history.capture_snapshot(kind="manual", label="Loose Snapshot")

        self.registered_backup_path = self.layout.backups_dir / "registered_backup.db"
        shutil.copy2(self.db_path, self.registered_backup_path)
        self.history.register_backup(
            self.registered_backup_path,
            kind="manual",
            label="Registered Backup",
            source_db_path=self.db_path,
        )

        self.deleted_history_dir = self.layout.history_dir / "snapshots" / "removed"
        self.deleted_history_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.db_path, self.deleted_history_dir / "deleted_snapshot.db")

        self.orphan_backup_path = self.layout.backups_dir / "removed_profile_backup.db"
        shutil.copy2(self.db_path, self.orphan_backup_path)
        self.orphan_backup_path.with_suffix(".db.backup.json").write_text(
            json.dumps({"source_db_path": str(self.deleted_profile_path)}),
            encoding="utf-8",
        )

        shutil.copy2(self.db_path, self.deleted_profile_path)
        session_history = SessionHistoryManager(self.layout.history_dir)
        deleted_snapshot_path = session_history.capture_profile_snapshot(
            self.deleted_profile_path,
            kind="profile_remove",
        )
        session_history.record_profile_remove(
            deleted_path=str(self.deleted_profile_path),
            current_path=str(self.db_path),
            fallback_path=str(self.db_path),
            deleting_current=False,
            snapshot_path=deleted_snapshot_path,
        )
        self.deleted_profile_path.unlink()

    def tearDown(self):
        self.settings.clear()
        DatabaseSessionService.close(self.conn)
        self.tmpdir.cleanup()

    def test_inspect_reports_application_wide_totals_and_current_profile_usage(self):
        audit = self.service.inspect(current_db_path=self.db_path)

        self.assertGreater(audit.summary.total_app_bytes, 0)
        self.assertGreater(audit.summary.current_profile_bytes, 0)
        self.assertGreater(audit.summary.reclaimable_bytes, 0)
        self.assertEqual(audit.summary.current_profile_name, self.db_path.name)

    def test_inspect_reports_progress_status_and_generated_files_without_history_mutation(self):
        export_path = self.layout.exports_dir / "delivery.csv"
        log_path = self.layout.logs_dir / "support.log"
        export_path.write_text("isrc,title\n", encoding="utf-8")
        log_path.write_text("diagnostic line\n", encoding="utf-8")
        statuses: list[str] = []
        progress_updates: list[tuple[int, int, str]] = []

        total = self.service.inspect_progress_total(current_db_path=self.db_path)
        audit = self.service.inspect(
            current_db_path=self.db_path,
            status_callback=statuses.append,
            progress_callback=lambda value, maximum, message: progress_updates.append(
                (value, maximum, message)
            ),
        )
        items_by_path = {item.path: item for item in audit.items}

        self.assertEqual(total, max(1, len({self.db_path.resolve()}) + 6))
        self.assertIn("Discovering active profiles...", statuses)
        self.assertIn("Finalizing application storage summary...", statuses)
        self.assertEqual(
            progress_updates[-1], (total, total, "Application-wide storage summary ready.")
        )
        self.assertEqual(items_by_path[str(export_path)].status_key, STATUS_OTHER)
        self.assertEqual(items_by_path[str(export_path)].category_key, "export_file")
        self.assertEqual(items_by_path[str(log_path)].category_key, "log_file")
        self.assertFalse(items_by_path[str(export_path)].recommended)

    def test_inspect_includes_explicit_current_profile_and_legacy_reference_fallbacks(self):
        external_profile = self.root / "external_profile.db"
        managed_license = self.layout.data_root / "licenses" / "legacy_contract.pdf"
        managed_license.parent.mkdir(parents=True, exist_ok=True)
        managed_license.write_bytes(b"legacy-license")
        stored_license_path = str(managed_license.relative_to(self.layout.data_root))
        with sqlite3.connect(external_profile) as conn:
            conn.execute("CREATE TABLE Licenses(id INTEGER PRIMARY KEY, file_path TEXT)")
            conn.execute(
                "INSERT INTO Licenses(id, file_path) VALUES (?, ?)",
                (42, stored_license_path),
            )

        audit = self.service.inspect(current_db_path=external_profile)
        items_by_path = {item.path: item for item in audit.items}
        license_item = items_by_path[str(managed_license)]

        self.assertEqual(audit.summary.current_profile_name, external_profile.name)
        self.assertEqual(license_item.status_key, STATUS_IN_USE)
        self.assertEqual(license_item.category_key, "license_file")
        self.assertTrue(license_item.warning_required)
        self.assertEqual(license_item.profile_name, external_profile.name)
        self.assertEqual(license_item.profile_path, str(external_profile.resolve()))
        self.assertEqual(len(license_item.references), 1)
        self.assertEqual(license_item.references[0].owner_label, "License #42 'Untitled'")

    def test_inspect_classifies_in_use_orphaned_and_deleted_profile_artifacts(self):
        audit = self.service.inspect(current_db_path=self.db_path)
        items_by_path = {item.path: item for item in audit.items}

        live_item = items_by_path[str(self.live_audio_path)]
        orphan_item = items_by_path[str(self.orphan_audio_path)]
        deleted_tree_item = items_by_path[str(self.deleted_history_dir)]
        backup_item = items_by_path[str(self.orphan_backup_path)]
        session_item = next(item for item in audit.items if item.category_key == "session_snapshot")
        protected_snapshot_item = next(
            item
            for item in audit.items
            if item.category_key == "history_snapshot"
            and item.status_key == STATUS_IN_USE
            and item.path == self.protected_snapshot.db_snapshot_path
        )

        self.assertEqual(live_item.status_key, STATUS_IN_USE)
        self.assertTrue(live_item.warning_required)
        self.assertEqual(orphan_item.status_key, STATUS_ORPHANED)
        self.assertEqual(deleted_tree_item.status_key, STATUS_DELETED_PROFILE)
        self.assertEqual(backup_item.status_key, STATUS_DELETED_PROFILE)
        self.assertEqual(session_item.status_key, STATUS_DELETED_PROFILE)
        self.assertTrue(session_item.warning_required)
        self.assertEqual(protected_snapshot_item.status_key, STATUS_IN_USE)
        self.assertTrue(protected_snapshot_item.warning_required)

    def test_cleanup_of_orphaned_items_does_not_create_new_history_or_session_entries(self):
        audit = self.service.inspect(current_db_path=self.db_path)
        orphan_keys = [
            item.item_key
            for item in audit.items
            if item.path in {str(self.orphan_audio_path), str(self.deleted_history_dir)}
        ]
        history_entries_before = self.conn.execute(
            "SELECT COUNT(*) FROM HistoryEntries"
        ).fetchone()[0]
        session_entries_before = len(SessionHistoryManager(self.layout.history_dir).list_entries())

        result = self.service.cleanup_selected(orphan_keys, current_db_path=self.db_path)

        history_entries_after = self.conn.execute("SELECT COUNT(*) FROM HistoryEntries").fetchone()[
            0
        ]
        session_entries_after = len(SessionHistoryManager(self.layout.history_dir).list_entries())

        self.assertEqual(len(result.removed_item_keys), 2)
        self.assertFalse(self.orphan_audio_path.exists())
        self.assertFalse(self.deleted_history_dir.exists())
        self.assertEqual(history_entries_after, history_entries_before)
        self.assertEqual(session_entries_after, session_entries_before)

    def test_cleanup_rejects_stale_keys_and_reports_progress_for_direct_cleanup(self):
        audit = self.service.inspect(current_db_path=self.db_path)
        orphan_item = next(item for item in audit.items if item.path == str(self.orphan_audio_path))
        statuses: list[str] = []
        progress_updates: list[tuple[int, int, str]] = []

        with self.assertRaisesRegex(ValueError, "Cleanup item is no longer available"):
            self.service.cleanup_selected(["missing:item"], current_db_path=self.db_path)

        result = self.service.cleanup_selected(
            [orphan_item.item_key],
            current_db_path=self.db_path,
            status_callback=statuses.append,
            progress_callback=lambda value, maximum, message: progress_updates.append(
                (value, maximum, message)
            ),
        )

        self.assertEqual(result.removed_item_keys, (orphan_item.item_key,))
        self.assertEqual(result.removed_paths, (str(self.orphan_audio_path),))
        self.assertGreater(result.removed_bytes, 0)
        self.assertFalse(self.orphan_audio_path.exists())
        self.assertIn("Storage cleanup finished.", statuses)
        self.assertEqual(progress_updates[-1], (100, 100, "Storage cleanup finished."))

    def test_cleanup_of_protected_snapshot_purges_dependent_history_without_new_entries(self):
        audit = self.service.inspect(current_db_path=self.db_path)
        protected_snapshot_item = next(
            item
            for item in audit.items
            if item.category_key == "history_snapshot"
            and item.path == self.protected_snapshot.db_snapshot_path
        )
        history_entries_before = self.conn.execute(
            "SELECT COUNT(*) FROM HistoryEntries"
        ).fetchone()[0]

        result = self.service.cleanup_selected(
            [protected_snapshot_item.item_key],
            current_db_path=self.db_path,
            allow_warning_deletes=True,
        )

        history_entries_after = self.conn.execute("SELECT COUNT(*) FROM HistoryEntries").fetchone()[
            0
        ]
        quarantined_rows = self.conn.execute("""
            SELECT reversible, status
            FROM HistoryEntries
            WHERE status='artifact_missing'
            """).fetchall()

        self.assertGreaterEqual(len(result.removed_history_entry_ids), 1)
        self.assertEqual(history_entries_after, history_entries_before)
        self.assertTrue(quarantined_rows)
        self.assertTrue(all(int(reversible) == 0 for reversible, _status in quarantined_rows))
        self.assertFalse(Path(self.protected_snapshot.db_snapshot_path).exists())
        self.assertIsNone(self.history.fetch_snapshot(self.protected_snapshot.snapshot_id))

    def test_inspect_reports_orphan_snapshot_and_backup_companion_artifacts(self):
        snapshot_root = self.layout.history_dir / "snapshots" / self.db_path.stem
        snapshot_root.mkdir(parents=True, exist_ok=True)
        orphan_snapshot_assets = snapshot_root / "orphan_snapshot.assets"
        orphan_snapshot_assets.mkdir(parents=True, exist_ok=True)
        (orphan_snapshot_assets / "artifact.bin").write_bytes(b"artifact")
        orphan_snapshot_companion = snapshot_root / "orphan_snapshot.db-journal"
        orphan_snapshot_companion.write_bytes(b"journal")

        orphan_backup_companion = self.layout.backups_dir / "orphan_backup.db-journal"
        orphan_backup_companion.write_bytes(b"backup-journal")
        deleted_profile_sidecar = self.layout.backups_dir / "deleted_profile.db.backup.json"
        deleted_profile_sidecar.write_text(
            json.dumps({"source_db_path": str(self.deleted_profile_path)}),
            encoding="utf-8",
        )

        audit = self.service.inspect(current_db_path=self.db_path)
        items_by_path = {item.path: item for item in audit.items}

        self.assertEqual(
            items_by_path[str(orphan_snapshot_assets)].status_key,
            STATUS_ORPHANED,
        )
        self.assertEqual(
            items_by_path[str(orphan_snapshot_companion)].status_key,
            STATUS_ORPHANED,
        )
        self.assertEqual(
            items_by_path[str(orphan_backup_companion)].status_key,
            STATUS_ORPHANED,
        )
        self.assertEqual(
            items_by_path[str(deleted_profile_sidecar)].status_key,
            STATUS_DELETED_PROFILE,
        )

    def test_cleanup_of_deleted_profile_session_snapshot_prunes_session_history(self):
        audit = self.service.inspect(current_db_path=self.db_path)
        session_item = next(item for item in audit.items if item.category_key == "session_snapshot")
        session_history = SessionHistoryManager(self.layout.history_dir)
        session_entries_before = len(session_history.list_entries())

        result = self.service.cleanup_selected(
            [session_item.item_key],
            current_db_path=self.db_path,
            allow_warning_deletes=True,
        )

        refreshed_history = SessionHistoryManager(self.layout.history_dir)
        session_entries_after = len(refreshed_history.list_entries())
        self.assertGreaterEqual(len(result.removed_session_entry_ids), 1)
        self.assertLess(session_entries_after, session_entries_before)
        self.assertFalse(Path(session_item.path).exists())

    def test_cleanup_of_file_state_bundle_quarantines_dependent_history(self):
        target_path = self.root / "tracked_document.txt"
        target_path.write_text("original", encoding="utf-8")
        before_state = self.history.capture_file_state(target_path)
        entry = self.history.record_file_write_action(
            label="Track file-state bundle",
            action_type="file.write",
            target_path=target_path,
            before_state=before_state,
            after_state={"exists": False, "files": []},
        )
        protected_bundle = Path(before_state["files"][0]["artifact_path"]).parent
        orphan_bundle = protected_bundle.parent / "orphan_state_bundle"
        orphan_bundle.mkdir(parents=True)
        (orphan_bundle / "loose.bin").write_bytes(b"loose")

        audit = self.service.inspect(current_db_path=self.db_path)
        items_by_path = {item.path: item for item in audit.items}
        protected_item = items_by_path[str(protected_bundle)]
        orphan_item = items_by_path[str(orphan_bundle)]

        self.assertEqual(protected_item.category_key, "file_state_bundle")
        self.assertEqual(protected_item.status_key, STATUS_IN_USE)
        self.assertTrue(protected_item.warning_required)
        self.assertFalse(protected_item.recommended)
        self.assertEqual(orphan_item.status_key, STATUS_RECOVERABILITY)
        self.assertFalse(orphan_item.warning_required)
        self.assertTrue(orphan_item.recommended)

        result = self.service.cleanup_selected(
            [protected_item.item_key, orphan_item.item_key],
            current_db_path=self.db_path,
            allow_warning_deletes=True,
        )

        quarantined_entry = self.conn.execute(
            "SELECT reversible, status, inverse_json FROM HistoryEntries WHERE id=?",
            (entry.entry_id,),
        ).fetchone()
        self.assertIsNotNone(quarantined_entry)
        assert quarantined_entry is not None
        reversible, status, inverse_json = quarantined_entry
        self.assertEqual(int(reversible), 0)
        self.assertEqual(status, self.history.STATUS_ARTIFACT_MISSING)
        self.assertIn(entry.entry_id, result.removed_history_entry_ids)
        self.assertNotIn(str(protected_bundle), str(inverse_json))
        self.assertFalse(protected_bundle.exists())
        self.assertFalse(orphan_bundle.exists())

    def test_inspect_and_cleanup_update_backups_and_workspaces(self):
        app_root = self.root / "installed-app"
        installed_app = app_root / "ISRC Catalog Manager.app"
        installed_app.mkdir(parents=True)
        backup = app_root / "ISRC Catalog Manager.app.backup-before-v3.6.9-20260427-010203"
        (backup / "Contents").mkdir(parents=True)
        (backup / "Contents" / "old-app").write_bytes(b"old app")

        update_root = self.root / "updates"
        workspace = update_root / "v3.6.9-macos"
        (workspace / "staging").mkdir(parents=True)
        (workspace / "staging" / "replacement").write_bytes(b"new app")
        state_path = update_root / update_handoff.UPDATE_BACKUP_HANDOFF_FILENAME
        update_handoff.record_update_backup_created(
            backup,
            expected_version="3.6.9",
            target_path=installed_app,
            installed_path=installed_app,
            state_path=state_path,
        )
        service = ApplicationStorageAdminService(
            self.layout,
            update_root=update_root,
            installed_update_target_path=installed_app,
        )

        audit = service.inspect(current_db_path=self.db_path)
        backup_item = next(
            item for item in audit.items if item.category_key == "update_install_backup"
        )
        workspace_item = next(
            item for item in audit.items if item.category_key == "update_workspace"
        )

        self.assertEqual(backup_item.status_key, STATUS_IN_USE)
        self.assertTrue(backup_item.warning_required)
        self.assertFalse(backup_item.recommended)
        self.assertTrue(workspace_item.recommended)

        with self.assertRaises(ValueError):
            service.cleanup_selected([backup_item.item_key], current_db_path=self.db_path)

        result = service.cleanup_selected(
            [backup_item.item_key, workspace_item.item_key],
            current_db_path=self.db_path,
            allow_warning_deletes=True,
        )

        state = update_handoff.read_update_backup_handoff(state_path=state_path)
        self.assertEqual(len(result.removed_item_keys), 2)
        self.assertFalse(backup.exists())
        self.assertFalse(workspace.exists())
        self.assertEqual(state["status"], update_handoff.UPDATE_BACKUP_STATUS_DESTROYED)
        self.assertIn("Application Storage Admin", state["error"])

    def test_update_backup_ready_stale_and_cache_file_paths_are_audited_and_cleaned(self):
        app_root = self.root / "installed-ready-app"
        installed_app = app_root / "ISRC Catalog Manager.app"
        installed_app.mkdir(parents=True)
        update_root = self.root / "ready-updates"
        state_path = update_root / update_handoff.UPDATE_BACKUP_HANDOFF_FILENAME
        ready_backup = app_root / "ISRC Catalog Manager.app.backup-before-v4.0.0-20260525-101112"
        ready_backup.mkdir(parents=True)
        (ready_backup / "old-app").write_bytes(b"old")
        cache_file = update_root / "download.pkg"
        cache_file.parent.mkdir(parents=True)
        cache_file.write_bytes(b"package")
        service = ApplicationStorageAdminService(
            self.layout,
            update_root=update_root,
            installed_update_target_path=installed_app,
        )
        update_handoff.record_update_backup_created(
            ready_backup,
            expected_version="4.0.0",
            target_path=installed_app,
            installed_path=installed_app,
            state_path=state_path,
        )
        update_handoff.mark_update_backup_ready_for_deletion(state_path=state_path)

        ready_audit = service.inspect(current_db_path=self.db_path)
        ready_item = next(
            item
            for item in ready_audit.items
            if Path(item.path).resolve() == ready_backup.resolve()
        )
        cache_item = next(
            item for item in ready_audit.items if Path(item.path).resolve() == cache_file.resolve()
        )

        self.assertEqual(ready_item.status_key, STATUS_RECOVERABILITY)
        self.assertEqual(ready_item.status_label, "Ready for Update Cleanup")
        self.assertTrue(ready_item.recommended)
        self.assertFalse(ready_item.warning_required)
        self.assertIn("Handoff status: ready_for_deletion", ready_item.reason)
        self.assertEqual(cache_item.category_key, "update_cache_file")

        cleanup_result = service.cleanup_selected(
            [ready_item.item_key, cache_item.item_key],
            current_db_path=self.db_path,
        )
        cleaned_state = update_handoff.read_update_backup_handoff(state_path=state_path)
        self.assertEqual(len(cleanup_result.removed_item_keys), 2)
        self.assertFalse(ready_backup.exists())
        self.assertFalse(cache_file.exists())
        self.assertEqual(cleaned_state["status"], update_handoff.UPDATE_BACKUP_STATUS_DESTROYED)

        stale_backup = app_root / "ISRC Catalog Manager.app.backup-before-v4.0.1-20260525-121314"
        stale_backup.mkdir(parents=True)
        (stale_backup / "old-app").write_bytes(b"old")
        update_handoff.record_update_backup_created(
            stale_backup,
            expected_version="4.0.1",
            target_path=installed_app,
            installed_path=installed_app,
            state_path=state_path,
        )
        update_handoff.mark_update_backup_destroyed(
            state_path=state_path,
            reason="Simulated prior cleanup.",
        )

        stale_audit = service.inspect(current_db_path=self.db_path)
        stale_item = next(
            item
            for item in stale_audit.items
            if Path(item.path).resolve() == stale_backup.resolve()
        )

        self.assertEqual(stale_item.status_key, STATUS_RECOVERABILITY)
        self.assertEqual(stale_item.status_label, "Stale Update Backup")
        self.assertTrue(stale_item.recommended)
        self.assertIn("Handoff status: destroyed", stale_item.reason)

    def test_storage_admin_helper_edges_preserve_recoverability_classification(self):
        invalid_sidecar = self.root / "invalid.json"
        invalid_sidecar.write_text("{not-json", encoding="utf-8")
        list_sidecar = self.root / "list.json"
        list_sidecar.write_text("[1, 2, 3]", encoding="utf-8")
        self.assertEqual(self.service._load_json_sidecar(self.root / "missing.json"), {})
        self.assertEqual(self.service._load_json_sidecar(invalid_sidecar), {})
        self.assertEqual(self.service._load_json_sidecar(list_sidecar), {})

        payload = {
            "snapshot_id": "3",
            "nested": [
                {"snapshot_id": 5},
                {"snapshot_id": "bad"},
            ],
        }
        self.assertEqual(self.service._collect_int_values(payload, "snapshot_id"), {3, 5})
        self.assertIsNone(self.service._load_json("not-json"))
        self.assertEqual(self.service._load_json('{"ok": true}'), {"ok": True})

        archive_root = self.layout.history_dir / "snapshot_archives" / self.db_path.stem
        archive_root.mkdir(parents=True, exist_ok=True)
        archive_path = archive_root / "archive.db"
        archive_path.write_bytes(b"archive")
        bundle = archive_path.with_suffix(".assets")
        bundle.mkdir()
        nested_artifact = bundle / "media.bin"
        nested_artifact.write_bytes(b"media")
        live_paths = self.service._paths_under_root(
            {
                "good": str(nested_artifact),
                "empty": "",
                "outside": str(self.root / "outside.bin"),
                "nested": [42, {"again": str(archive_path)}],
            },
            archive_root,
        )
        self.assertEqual(live_paths, {archive_path.resolve(), nested_artifact.resolve()})
        self.assertTrue(self.service._path_is_referenced(archive_path, {nested_artifact}))
        self.assertFalse(self.service._path_is_referenced(self.root / "missing.db", live_paths))

        self.assertEqual(
            self.service._parse_update_backup_name("App.app.backup-before-v3.6.9-20260427-010203"),
            ("3.6.9", "2026-04-27 01:02:03"),
        )
        self.assertEqual(self.service._parse_update_backup_name("not-a-backup"), ("", ""))
        self.assertEqual(
            self.service._version_label_from_update_workspace(Path("v3.6.9-macos")), "v3.6.9"
        )
        self.assertEqual(self.service._version_label_from_update_workspace(Path("cache")), "")

        recoverable_item = next(
            item
            for item in self.service.inspect(current_db_path=self.db_path).items
            if item.status_key == STATUS_RECOVERABILITY
        )
        self.assertTrue(recoverable_item.recommended)

    def test_cleanup_tolerates_disappearing_items_and_closes_context_failures(self):
        audit = self.service.inspect(current_db_path=self.db_path)
        orphan_item = next(item for item in audit.items if item.path == str(self.orphan_audio_path))

        class BadConnection:
            def close(self):
                raise RuntimeError("close failed")

        def disappearing_cleanup(
            _item,
            *,
            history_contexts,
            **_kwargs,
        ):
            history_contexts["bad"] = (BadConnection(), None, None)
            raise FileNotFoundError("already gone")

        with mock.patch.object(self.service, "_cleanup_item", side_effect=disappearing_cleanup):
            result = self.service.cleanup_selected(
                [orphan_item.item_key],
                current_db_path=self.db_path,
            )

        self.assertEqual(result.removed_item_keys, (orphan_item.item_key,))
        self.assertEqual(result.removed_paths, (str(orphan_item.path),))
        self.assertEqual(result.skipped_item_keys, ())

    def test_session_snapshot_items_distinguish_active_deleted_and_orphaned_references(self):
        session_history = SessionHistoryManager(self.layout.history_dir)
        created_entry = session_history.record_profile_create(
            created_path=str(self.db_path),
            previous_path=str(self.deleted_profile_path),
        )
        self.assertIsNotNone(created_entry)
        active_snapshot_path = Path(created_entry.inverse_payload["snapshot_path"])
        orphan_snapshot_path = self.layout.history_dir / "session_profile_snapshots" / "orphan.db"
        shutil.copy2(self.db_path, orphan_snapshot_path)
        Path(str(orphan_snapshot_path) + "-wal").write_bytes(b"wal")

        audit = self.service.inspect(current_db_path=self.db_path)
        items_by_path = {item.path: item for item in audit.items}
        active_item = items_by_path[str(active_snapshot_path)]
        orphan_item = items_by_path[str(orphan_snapshot_path)]

        self.assertEqual(active_item.status_key, STATUS_IN_USE)
        self.assertFalse(active_item.recommended)
        self.assertTrue(active_item.warning_required)
        self.assertEqual(active_item.profile_name, self.db_path.name)
        self.assertGreaterEqual(active_item.bytes_on_disk, active_snapshot_path.stat().st_size)

        self.assertEqual(orphan_item.status_key, STATUS_ORPHANED)
        self.assertTrue(orphan_item.recommended)
        self.assertFalse(orphan_item.warning_required)
        self.assertGreaterEqual(orphan_item.bytes_on_disk, orphan_snapshot_path.stat().st_size)

    def test_storage_admin_reference_and_missing_root_helpers_cover_boundary_paths(self):
        shutil.rmtree(self.layout.backups_dir)
        self.assertEqual(
            self.service._backup_file_items(
                registered_backup_paths=set(),
                active_profile_set={str(self.db_path.resolve())},
            ),
            [],
        )

        references = (
            StorageAdminReference(
                profile_path="/profiles/one.db",
                profile_name="one.db",
                owner_label="Track #1",
            ),
            StorageAdminReference(
                profile_path="/profiles/two.db",
                profile_name="two.db",
                owner_label="Track #2",
            ),
        )
        self.assertIn("2 active profile", self.service._format_reference_reason(references))
        self.assertEqual(
            self.service._profile_name_from_references(references), "2 active profiles"
        )
        self.assertIsNone(self.service._profile_path_from_references(references))
        self.assertTrue(
            self.service._item_belongs_to_profile(
                StorageAdminItem(
                    item_key="managed:test",
                    status_key=STATUS_IN_USE,
                    status_label="In Use",
                    category_key="track_media",
                    category_label="Track Media",
                    label="file.wav",
                    path="/tmp/file.wav",
                    bytes_on_disk=1,
                    profile_name=None,
                    profile_path=None,
                    reason="Referenced.",
                    recommended=False,
                    warning_required=True,
                    references=references,
                ),
                "/profiles/two.db",
            )
        )


if __name__ == "__main__":
    unittest.main()

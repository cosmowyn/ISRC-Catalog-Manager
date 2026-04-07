import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from PySide6.QtWidgets import QDialog, QMessageBox

from isrc_manager.code_registry import (
    BUILTIN_CATEGORY_CATALOG_NUMBER,
    BUILTIN_CATEGORY_CONTRACT_NUMBER,
    CodeRegistryService,
    CodeRegistryWorkspacePanel,
)
from isrc_manager.code_registry.models import CodeRegistryCategoryPayload
from isrc_manager.services import DatabaseSchemaService, TrackCreatePayload, TrackService
from tests.qt_test_helpers import pump_events, require_qapplication


class CodeRegistryWorkspacePanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = require_qapplication()

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("PRAGMA foreign_keys = ON")
        schema = DatabaseSchemaService(self.conn, data_root=self.root)
        schema.init_db()
        schema.migrate_schema()
        self.track_service = TrackService(self.conn, self.root)
        self.registry = CodeRegistryService(self.conn)
        category = self.registry.fetch_category_by_system_key(BUILTIN_CATEGORY_CATALOG_NUMBER)
        assert category is not None
        self.registry.update_category(category.id, prefix="ACR")
        self.panel = CodeRegistryWorkspacePanel(service_provider=lambda: self.registry)
        self.panel.show()
        pump_events(app=self.app, cycles=3)

    def tearDown(self):
        self.panel.close()
        self.panel.deleteLater()
        pump_events(app=self.app, cycles=2)
        self.conn.close()
        self.tmpdir.cleanup()

    def _create_track(self, *, isrc: str, title: str) -> int:
        return self.track_service.create_track(
            TrackCreatePayload(
                isrc=isrc,
                track_title=title,
                artist_name="Workspace Artist",
                additional_artists=[],
                album_title="Workspace Album",
                release_date="2026-04-07",
                track_length_sec=180,
                iswc=None,
                upc=None,
                genre="Ambient",
                catalog_number=None,
            )
        )

    def _select_category_row(
        self, *, system_key: str | None = None, display_name: str | None = None
    ):
        target_row = None
        for row in range(self.panel.category_table.rowCount()):
            system_key_item = self.panel.category_table.item(row, 2)
            name_item = self.panel.category_table.item(row, 1)
            if (
                system_key is not None
                and system_key_item is not None
                and system_key_item.text() == system_key
            ):
                target_row = row
                break
            if (
                display_name is not None
                and name_item is not None
                and name_item.text() == display_name
            ):
                target_row = row
                break
        self.assertIsNotNone(target_row)
        self.panel.category_table.selectRow(int(target_row))
        pump_events(app=self.app, cycles=2)

    def test_workspace_exposes_tabs_and_usage_details(self):
        track_id = self._create_track(isrc="NL-TST-26-50001", title="Internal Linked Track")
        generated = self.registry.generate_next_code(
            system_key=BUILTIN_CATEGORY_CATALOG_NUMBER,
            created_via="test.workspace",
        ).entry
        resolution = self.registry.resolve_catalog_input(
            mode="internal",
            value=generated.value,
            registry_entry_id=generated.id,
        )
        self.registry.assign_catalog_to_owner(
            owner_kind="track",
            owner_id=track_id,
            resolution=resolution,
            provenance_kind="generated",
            source_label="test.workspace",
        )

        self.panel.refresh()
        pump_events(app=self.app, cycles=2)
        self.assertEqual(
            [self.panel.tabs.tabText(index) for index in range(self.panel.tabs.count())],
            ["Internal Registry", "External Catalogs", "Categories"],
        )
        self.assertGreaterEqual(self.panel.category_table.rowCount(), 4)
        self.assertGreaterEqual(self.panel.entry_table.rowCount(), 1)

        target_row = None
        for row in range(self.panel.entry_table.rowCount()):
            item = self.panel.entry_table.item(row, 0)
            if item is not None and item.text() == str(generated.id):
                target_row = row
                break
        self.assertIsNotNone(target_row)
        self.panel.entry_table.selectRow(int(target_row))
        pump_events(app=self.app, cycles=2)
        self.assertEqual(self.panel.entry_value_label.text(), generated.value)
        self.assertIn("Track #", self.panel.entry_usage_text.toPlainText())

    def test_workspace_actions_generate_hash_and_promote_external_catalogs(self):
        canonical_track_id = self._create_track(
            isrc="NL-TST-26-50002",
            title="Promotion Candidate",
        )
        yy = datetime.now().year % 100
        canonical_value = f"ACR{yy:02d}0042"
        external_resolution = self.registry.resolve_catalog_input(
            mode="external",
            value=canonical_value,
            created_via="test.workspace.external",
        )
        self.registry.assign_catalog_to_owner(
            owner_kind="track",
            owner_id=canonical_track_id,
            resolution=external_resolution,
            provenance_kind="imported",
            source_label="test.workspace.external",
        )
        self.panel.refresh()
        pump_events(app=self.app, cycles=2)

        with mock.patch("isrc_manager.code_registry.workspace.QMessageBox.critical") as critical:
            self.panel._generate_catalog_code()
            self.panel._generate_registry_hash()

        critical.assert_not_called()
        self.assertIn("Registry SHA-256 Key", self.panel.status_label.text())
        self.assertGreaterEqual(self.panel.entry_table.rowCount(), 2)

        self.panel.tabs.setCurrentIndex(1)
        self.panel.refresh_external()
        pump_events(app=self.app, cycles=2)
        self.assertGreaterEqual(self.panel.external_table.rowCount(), 1)
        self.panel.external_table.selectRow(0)

        with mock.patch("isrc_manager.code_registry.workspace.QMessageBox.critical") as critical:
            self.panel._promote_external()

        critical.assert_not_called()
        row = self.conn.execute(
            """
            SELECT catalog_number, catalog_registry_entry_id, external_catalog_identifier_id
            FROM Tracks
            WHERE id=?
            """,
            (canonical_track_id,),
        ).fetchone()
        self.assertEqual(row[0], canonical_value)
        self.assertIsNotNone(row[1])
        self.assertIsNone(row[2])
        self.assertIn("Promoted external catalog value", self.panel.status_label.text())

    def test_workspace_external_catalog_tab_shows_shared_usage_counts(self):
        first_track_id = self._create_track(isrc="NL-TST-26-50003", title="Shared One")
        second_track_id = self._create_track(isrc="NL-TST-26-50004", title="Shared Two")
        shared_value = "ALB-2501"
        resolution = self.registry.resolve_catalog_input(
            mode="external",
            value=shared_value,
            created_via="test.workspace.shared",
        )
        self.registry.assign_catalog_to_owner(
            owner_kind="track",
            owner_id=first_track_id,
            resolution=resolution,
            provenance_kind="manual",
            source_label="test.workspace.shared",
        )
        self.registry.assign_catalog_to_owner(
            owner_kind="track",
            owner_id=second_track_id,
            resolution=resolution,
            provenance_kind="manual",
            source_label="test.workspace.shared",
        )

        self.panel.tabs.setCurrentIndex(1)
        self.panel.refresh_external()
        pump_events(app=self.app, cycles=2)

        self.assertEqual(self.panel.external_table.rowCount(), 1)
        self.assertEqual(self.panel.external_table.item(0, 1).text(), shared_value)
        self.assertEqual(self.panel.external_table.item(0, 2).text(), "2")

    def test_workspace_can_link_selected_internal_entry(self):
        track_id = self._create_track(isrc="NL-TST-26-50005", title="Assignment Target")
        entry = self.registry.generate_next_code(
            system_key=BUILTIN_CATEGORY_CATALOG_NUMBER,
            created_via="test.workspace.assign",
        ).entry
        self.panel.refresh_entries()
        pump_events(app=self.app, cycles=2)

        target_row = None
        for row in range(self.panel.entry_table.rowCount()):
            item = self.panel.entry_table.item(row, 0)
            if item is not None and item.text() == str(entry.id):
                target_row = row
                break
        self.assertIsNotNone(target_row)
        self.panel.entry_table.selectRow(int(target_row))
        pump_events(app=self.app, cycles=2)

        with mock.patch(
            "isrc_manager.code_registry.workspace._RegistryOwnerAssignmentDialog"
        ) as dialog_cls:
            dialog = dialog_cls.return_value
            dialog.exec.return_value = QDialog.Accepted
            dialog.assignment.return_value = ("track", track_id)
            with mock.patch(
                "isrc_manager.code_registry.workspace.QMessageBox.critical"
            ) as critical:
                self.panel._assign_selected_entry()

        critical.assert_not_called()
        row = self.conn.execute(
            """
            SELECT catalog_number, catalog_registry_entry_id
            FROM Tracks
            WHERE id=?
            """,
            (track_id,),
        ).fetchone()
        self.assertEqual(row, (entry.value, entry.id))
        self.assertIn("Linked internal registry value", self.panel.status_label.text())

    def test_workspace_can_delete_unused_registry_sha256_key(self):
        entry = self.registry.generate_sha256_key(created_via="test.workspace.delete").entry
        self.panel.refresh_entries()
        pump_events(app=self.app, cycles=2)

        target_row = None
        for row in range(self.panel.entry_table.rowCount()):
            item = self.panel.entry_table.item(row, 0)
            if item is not None and item.text() == str(entry.id):
                target_row = row
                break
        self.assertIsNotNone(target_row)
        self.panel.entry_table.selectRow(int(target_row))
        pump_events(app=self.app, cycles=2)
        self.assertTrue(self.panel.delete_entry_button.isEnabled())

        with mock.patch(
            "isrc_manager.code_registry.workspace.QMessageBox.question",
            return_value=QMessageBox.Yes,
        ) as question:
            with mock.patch(
                "isrc_manager.code_registry.workspace.QMessageBox.critical"
            ) as critical:
                self.panel._delete_selected_entry()

        question.assert_called_once()
        critical.assert_not_called()
        self.assertIsNone(self.registry.fetch_entry(entry.id))
        self.assertIn("Deleted unused Registry SHA-256 Key", self.panel.status_label.text())

    def test_workspace_saves_builtin_prefix_without_warning(self):
        self._select_category_row(system_key=BUILTIN_CATEGORY_CONTRACT_NUMBER)
        self.panel.category_prefix_edit.setText("CTR")

        with mock.patch("isrc_manager.code_registry.workspace.QMessageBox.critical") as critical:
            self.panel._save_category()

        critical.assert_not_called()
        category = self.registry.fetch_category_by_system_key(BUILTIN_CATEGORY_CONTRACT_NUMBER)
        self.assertIsNotNone(category)
        assert category is not None
        self.assertEqual(category.prefix, "CTR")
        self.assertIn("Saved category changes.", self.panel.status_label.text())

    def test_workspace_can_delete_custom_category(self):
        category_id = self.registry.create_category(
            CodeRegistryCategoryPayload(
                display_name="Temporary Category",
                subject_kind="generic",
                generation_strategy="manual",
                prefix=None,
                active_flag=True,
            )
        )
        self.panel.refresh_categories()
        pump_events(app=self.app, cycles=2)
        self._select_category_row(display_name="Temporary Category")

        with mock.patch(
            "isrc_manager.code_registry.workspace.QMessageBox.question",
            return_value=QMessageBox.Yes,
        ) as question:
            with mock.patch(
                "isrc_manager.code_registry.workspace.QMessageBox.critical"
            ) as critical:
                self.panel._delete_category()

        question.assert_called_once()
        critical.assert_not_called()
        self.assertIsNone(self.registry.fetch_category(category_id))
        self.assertIn("Deleted custom category", self.panel.status_label.text())


if __name__ == "__main__":
    unittest.main()

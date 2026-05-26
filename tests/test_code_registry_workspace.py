import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QMessageBox

from isrc_manager.code_registry import (
    BUILTIN_CATEGORY_CATALOG_NUMBER,
    BUILTIN_CATEGORY_CONTRACT_NUMBER,
    BUILTIN_CATEGORY_REGISTRY_SHA256_KEY,
    CodeRegistryAssignmentTarget,
    CodeRegistryService,
    CodeRegistryWorkspacePanel,
)
from isrc_manager.code_registry.models import CodeRegistryCategoryPayload
from isrc_manager.code_registry.workspace import _RegistryOwnerAssignmentDialog
from isrc_manager.contracts import ContractPayload, ContractService
from isrc_manager.parties import PartyService
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
        self.party_service = PartyService(self.conn)
        self.contract_service = ContractService(
            self.conn,
            self.root,
            party_service=self.party_service,
        )
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

    def _create_contract(self, *, title: str) -> int:
        return self.contract_service.create_contract(
            ContractPayload(
                title=title,
                contract_type="license",
                status="draft",
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

    def _select_entry_row(self, entry_id: int) -> None:
        target_row = None
        for row in range(self.panel.entry_table.rowCount()):
            item = self.panel.entry_table.item(row, 0)
            if item is not None and item.text() == str(entry_id):
                target_row = row
                break
        self.assertIsNotNone(target_row)
        self.panel.entry_table.selectRow(int(target_row))
        pump_events(app=self.app, cycles=2)

    def _create_external_catalog_identifier(self, value: str) -> int:
        track_id = self._create_track(isrc=f"NL-TST-26-{50020 + hash(value) % 1000}", title=value)
        resolution = self.registry.resolve_catalog_input(
            mode="external",
            value=value,
            created_via="test.workspace.external.failure",
        )
        self.registry.assign_catalog_to_owner(
            owner_kind="track",
            owner_id=track_id,
            resolution=resolution,
            provenance_kind="imported",
            source_label="test.workspace.external.failure",
        )
        self.panel.tabs.setCurrentIndex(1)
        self.panel.refresh_external()
        pump_events(app=self.app, cycles=2)
        self.assertGreaterEqual(self.panel.external_table.rowCount(), 1)
        self.panel.external_table.selectRow(0)
        pump_events(app=self.app, cycles=2)
        external_id = self.panel._selected_row_id(
            self.panel.external_table, self.panel._external_row_ids
        )
        self.assertIsNotNone(external_id)
        assert external_id is not None
        return external_id

    def test_assignment_dialog_handles_unavailable_unsupported_and_target_selection(self):
        unavailable = _RegistryOwnerAssignmentDialog(
            service_provider=lambda: (_ for _ in ()).throw(RuntimeError("offline")),
            entry_id=101,
            entry_value="ACR260001",
        )
        self.addCleanup(unavailable.deleteLater)
        self.assertIn("unavailable", unavailable.empty_label.text())
        self.assertEqual(unavailable.target_table.rowCount(), 0)
        ok_button = unavailable.button_box.button(QDialogButtonBox.Ok)
        self.assertIsNotNone(ok_button)
        assert ok_button is not None
        self.assertFalse(ok_button.isEnabled())
        with mock.patch("isrc_manager.code_registry.workspace.QMessageBox.warning") as warning:
            unavailable._accept_selection()
        warning.assert_called_once()

        class UnsupportedAssignmentService:
            def assignment_owner_kinds_for_entry(self, entry_id):
                return []

            def list_assignment_targets_for_entry(self, entry_id, *, owner_kind, search_text=None):
                raise AssertionError("unsupported entries should not query targets")

        unsupported = _RegistryOwnerAssignmentDialog(
            service_provider=UnsupportedAssignmentService,
            entry_id=102,
            entry_value="MANUAL-ONLY",
        )
        self.addCleanup(unsupported.deleteLater)
        self.assertEqual(unsupported.owner_kind_combo.count(), 0)
        self.assertIn("does not support", unsupported.empty_label.text())

        class AssignmentService:
            def __init__(self):
                self.requests = []

            def assignment_owner_kinds_for_entry(self, entry_id):
                return ["track", "contract"]

            def list_assignment_targets_for_entry(self, entry_id, *, owner_kind, search_text=None):
                self.requests.append((entry_id, owner_kind, search_text))
                if search_text == "missing":
                    return []
                if owner_kind == "contract":
                    return [
                        CodeRegistryAssignmentTarget(
                            owner_kind="contract",
                            owner_id=77,
                            label="Publishing Agreement",
                            detail="draft",
                        )
                    ]
                return [
                    CodeRegistryAssignmentTarget(
                        owner_kind="track",
                        owner_id=42,
                        label="Focused Track",
                        detail="NL-TST-26-00042",
                    )
                ]

        service = AssignmentService()
        selectable = _RegistryOwnerAssignmentDialog(
            service_provider=lambda: service,
            entry_id=103,
            entry_value="ACR260103",
        )
        self.addCleanup(selectable.deleteLater)
        self.assertEqual(selectable.target_table.rowCount(), 1)
        self.assertEqual(selectable.assignment(), ("track", 42))
        ok_button = selectable.button_box.button(QDialogButtonBox.Ok)
        self.assertIsNotNone(ok_button)
        assert ok_button is not None
        self.assertTrue(ok_button.isEnabled())

        selectable.search_edit.setText("missing")
        pump_events(app=self.app, cycles=2)
        self.assertEqual(selectable.target_table.rowCount(), 0)
        self.assertIn("No matching owners", selectable.empty_label.text())
        self.assertIsNone(selectable.assignment())
        self.assertFalse(ok_button.isEnabled())

        selectable.search_edit.clear()
        selectable.owner_kind_combo.setCurrentIndex(1)
        pump_events(app=self.app, cycles=2)
        self.assertEqual(selectable.target_table.item(0, 0).text(), "Contract")
        self.assertEqual(selectable.assignment(), ("contract", 77))
        selectable._accept_selection()
        self.assertEqual(selectable.result(), QDialog.Accepted)

    def test_workspace_unavailable_service_resets_controls_and_noops(self):
        def raise_service():
            raise RuntimeError("profile closed")

        panel = CodeRegistryWorkspacePanel(service_provider=raise_service)
        self.addCleanup(panel.deleteLater)
        panel.show()
        pump_events(app=self.app, cycles=2)

        self.assertEqual(panel.category_table.rowCount(), 0)
        self.assertEqual(panel.entry_table.rowCount(), 0)
        self.assertEqual(panel.external_table.rowCount(), 0)
        self.assertEqual(panel.entry_category_filter.count(), 1)
        self.assertFalse(panel.generate_code_button.isEnabled())
        self.assertIn("Open a profile", panel.generate_code_button.toolTip())
        self.assertIsNone(panel._selected_generation_category())

        with mock.patch("isrc_manager.code_registry.workspace.QMessageBox.critical") as critical:
            panel._create_category()
            panel._generate_catalog_code()
            panel._generate_registry_hash()
            panel._promote_external()
            panel._reclassify_external()
            panel._delete_category()
            panel._assign_selected_entry()
            panel._reassign_selected_entry()
            panel._delete_selected_entry()

        critical.assert_not_called()

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
            ["Internal Registry", "External Identifiers", "Categories"],
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

    def test_workspace_actions_generate_hash_and_promote_external_identifiers(self):
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
            SELECT catalog_number, catalog_registry_entry_id, catalog_external_code_identifier_id
            FROM Tracks
            WHERE id=?
            """,
            (canonical_track_id,),
        ).fetchone()
        self.assertEqual(row[0], canonical_value)
        self.assertIsNotNone(row[1])
        self.assertIsNone(row[2])
        self.assertIn("Promoted external identifier", self.panel.status_label.text())

    def test_workspace_can_generate_contract_numbers_for_selected_category(self):
        contract_category = self.registry.fetch_category_by_system_key(
            BUILTIN_CATEGORY_CONTRACT_NUMBER
        )
        self.assertIsNotNone(contract_category)
        assert contract_category is not None
        self.registry.update_category(contract_category.id, prefix="CTR")
        self.panel.refresh()
        pump_events(app=self.app, cycles=2)
        self._select_category_row(system_key=BUILTIN_CATEGORY_CONTRACT_NUMBER)

        with mock.patch("isrc_manager.code_registry.workspace.QMessageBox.critical") as critical:
            self.panel._generate_catalog_code()

        critical.assert_not_called()
        latest = self.conn.execute(
            """
            SELECT value
            FROM CodeRegistryEntries
            WHERE category_id=?
            ORDER BY id DESC
            LIMIT 1
            """,
            (contract_category.id,),
        ).fetchone()
        self.assertIsNotNone(latest)
        assert latest is not None
        self.assertTrue(str(latest[0]).startswith("CTR"))
        self.assertIn("generated contract number", self.panel.status_label.text().lower())

    def test_workspace_external_identifiers_tab_shows_shared_usage_counts(self):
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
        self.assertEqual(self.panel.external_table.item(0, 1).text(), "Catalog Number")
        self.assertEqual(self.panel.external_table.item(0, 2).text(), shared_value)
        self.assertEqual(self.panel.external_table.item(0, 3).text(), "2")

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
        self.assertIn("Deleted unlinked registry value", self.panel.status_label.text())

    def test_workspace_disables_generation_and_shows_nudge_when_prefix_missing(self):
        self._select_category_row(system_key=BUILTIN_CATEGORY_CONTRACT_NUMBER)

        self.assertFalse(self.panel.generate_code_button.isEnabled())
        self.assertIn("Configure a prefix/namespace", self.panel.generate_code_button.toolTip())
        self.assertIn("Code Registry > Categories", self.panel.entry_generation_hint_label.text())

    def test_workspace_can_realign_selected_contract_registry_value(self):
        contract_category = self.registry.fetch_category_by_system_key(
            BUILTIN_CATEGORY_CONTRACT_NUMBER
        )
        self.assertIsNotNone(contract_category)
        assert contract_category is not None
        self.registry.update_category(contract_category.id, prefix="CTR")
        first_contract_id = self._create_contract(title="Original Workspace Contract")
        second_contract_id = self._create_contract(title="Replacement Workspace Contract")
        entry = self.contract_service.generate_registry_value_for_contract(
            first_contract_id,
            system_key=BUILTIN_CATEGORY_CONTRACT_NUMBER,
            created_via="test.workspace.realign",
        )
        self.panel.refresh()
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
        self.assertTrue(self.panel.reassign_entry_button.isEnabled())

        with mock.patch(
            "isrc_manager.code_registry.workspace._RegistryOwnerAssignmentDialog"
        ) as dialog_cls:
            dialog = dialog_cls.return_value
            dialog.exec.return_value = QDialog.Accepted
            dialog.assignment.return_value = ("contract", second_contract_id)
            with mock.patch(
                "isrc_manager.code_registry.workspace.QMessageBox.critical"
            ) as critical:
                self.panel._reassign_selected_entry()

        critical.assert_not_called()
        first_contract = self.contract_service.fetch_contract(first_contract_id)
        second_contract = self.contract_service.fetch_contract(second_contract_id)
        self.assertIsNotNone(first_contract)
        self.assertIsNotNone(second_contract)
        assert first_contract is not None
        assert second_contract is not None
        self.assertIsNone(first_contract.contract_registry_entry_id)
        self.assertIsNone(first_contract.contract_number)
        self.assertEqual(second_contract.contract_registry_entry_id, entry.id)
        self.assertEqual(second_contract.contract_number, entry.value)
        self.assertIn("Realigned internal registry value", self.panel.status_label.text())

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

    def test_workspace_category_create_save_delete_failure_and_cancellation_paths(self):
        self.panel.category_table.clearSelection()
        self.panel._reset_category_form()
        self.panel.category_name_edit.setText("Workspace Batch Category")
        self.panel.category_prefix_edit.setText("WBX")
        self.panel.category_active_checkbox.setChecked(False)

        with mock.patch("isrc_manager.code_registry.workspace.QMessageBox.critical") as critical:
            self.panel._create_category()

        critical.assert_not_called()
        self.assertIn("Created a new code-registry category", self.panel.status_label.text())
        self._select_category_row(display_name="Workspace Batch Category")
        selected_category_id = self.panel._selected_row_id(
            self.panel.category_table, self.panel._category_row_ids
        )
        self.assertIsNotNone(selected_category_id)
        assert selected_category_id is not None
        created = self.registry.fetch_category(selected_category_id)
        self.assertIsNotNone(created)
        assert created is not None
        self.assertFalse(created.active_flag)

        self.panel.category_name_edit.setText("Duplicate Batch Category")
        with mock.patch.object(
            self.registry,
            "create_category",
            side_effect=ValueError("category create failed"),
        ):
            with mock.patch(
                "isrc_manager.code_registry.workspace.QMessageBox.critical"
            ) as critical:
                self.panel._create_category()
        critical.assert_called_once()
        self.assertIn("category create failed", critical.call_args.args[2])

        with mock.patch.object(
            self.registry,
            "update_category",
            side_effect=ValueError("category save failed"),
        ):
            with mock.patch(
                "isrc_manager.code_registry.workspace.QMessageBox.critical"
            ) as critical:
                self.panel._save_category()
        critical.assert_called_once()
        self.assertIn("category save failed", critical.call_args.args[2])

        with mock.patch(
            "isrc_manager.code_registry.workspace.QMessageBox.question",
            return_value=QMessageBox.No,
        ) as question:
            self.panel._delete_category()
        question.assert_called_once()
        self.assertIsNotNone(self.registry.fetch_category(selected_category_id))

        with mock.patch.object(
            self.registry,
            "delete_category",
            side_effect=ValueError("category delete failed"),
        ):
            with mock.patch(
                "isrc_manager.code_registry.workspace.QMessageBox.question",
                return_value=QMessageBox.Yes,
            ):
                with mock.patch(
                    "isrc_manager.code_registry.workspace.QMessageBox.critical"
                ) as critical:
                    self.panel._delete_category()
        critical.assert_called_once()
        self.assertIn("category delete failed", critical.call_args.args[2])

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

    def test_workspace_generation_reclassification_and_promotion_failure_paths(self):
        self._select_category_row(system_key=BUILTIN_CATEGORY_REGISTRY_SHA256_KEY)
        with mock.patch("isrc_manager.code_registry.workspace.QMessageBox.critical") as critical:
            self.panel._generate_catalog_code()
        critical.assert_not_called()
        self.assertIn("Registry SHA-256 Key", self.panel.status_label.text())

        with mock.patch.object(self.panel, "_selected_generation_category", return_value=None):
            with mock.patch(
                "isrc_manager.code_registry.workspace.QMessageBox.information"
            ) as information:
                self.panel._generate_catalog_code()
        information.assert_called_once()

        self._select_category_row(system_key=BUILTIN_CATEGORY_CATALOG_NUMBER)
        with mock.patch.object(
            self.registry,
            "generate_next_code",
            side_effect=RuntimeError("generation failed"),
        ):
            with mock.patch(
                "isrc_manager.code_registry.workspace.QMessageBox.critical"
            ) as critical:
                self.panel._generate_catalog_code()
        critical.assert_called_once()
        self.assertIn("generation failed", critical.call_args.args[2])

        with mock.patch.object(
            self.registry,
            "generate_sha256_key",
            side_effect=RuntimeError("hash failed"),
        ):
            with mock.patch(
                "isrc_manager.code_registry.workspace.QMessageBox.critical"
            ) as critical:
                self.panel._generate_registry_hash()
        critical.assert_called_once()
        self.assertIn("hash failed", critical.call_args.args[2])

        self.panel.external_table.clearSelection()
        self.panel._external_row_ids = []
        with mock.patch("isrc_manager.code_registry.workspace.QMessageBox.critical") as critical:
            self.panel._promote_external()
        critical.assert_not_called()

        self._create_external_catalog_identifier("EXT-FAIL-2601")
        with mock.patch.object(
            self.registry,
            "promote_external_code_identifier",
            side_effect=RuntimeError("promotion failed"),
        ):
            with mock.patch(
                "isrc_manager.code_registry.workspace.QMessageBox.critical"
            ) as critical:
                self.panel._promote_external()
        critical.assert_called_once()
        self.assertIn("promotion failed", critical.call_args.args[2])

        with mock.patch.object(
            self.registry,
            "reclassify_external_code_identifiers",
            return_value={"promoted": 1, "retained": 2},
        ) as reclassify:
            with mock.patch(
                "isrc_manager.code_registry.workspace.QMessageBox.critical"
            ) as critical:
                self.panel._reclassify_external()
        critical.assert_not_called()
        reclassify.assert_called_once()
        self.assertIn("promoted=1", self.panel.status_label.text())
        self.assertIn("retained=2", self.panel.status_label.text())

        with mock.patch.object(
            self.registry,
            "reclassify_external_code_identifiers",
            side_effect=RuntimeError("reclassify failed"),
        ):
            with mock.patch(
                "isrc_manager.code_registry.workspace.QMessageBox.critical"
            ) as critical:
                self.panel._reclassify_external()
        critical.assert_called_once()
        self.assertIn("reclassify failed", critical.call_args.args[2])

    def test_workspace_entry_assignment_reassignment_and_delete_failure_paths(self):
        track_id = self._create_track(isrc="NL-TST-26-50110", title="Failure Target")
        entry = self.registry.generate_next_code(
            system_key=BUILTIN_CATEGORY_CATALOG_NUMBER,
            created_via="test.workspace.failure",
        ).entry
        self.panel.refresh_entries()
        pump_events(app=self.app, cycles=2)
        self._select_entry_row(entry.id)

        with mock.patch(
            "isrc_manager.code_registry.workspace._RegistryOwnerAssignmentDialog"
        ) as dialog_cls:
            dialog = dialog_cls.return_value
            dialog.exec.return_value = QDialog.Rejected
            with mock.patch(
                "isrc_manager.code_registry.workspace.QMessageBox.critical"
            ) as critical:
                self.panel._assign_selected_entry()
        critical.assert_not_called()

        with mock.patch(
            "isrc_manager.code_registry.workspace._RegistryOwnerAssignmentDialog"
        ) as dialog_cls:
            dialog = dialog_cls.return_value
            dialog.exec.return_value = QDialog.Accepted
            dialog.assignment.return_value = None
            with mock.patch(
                "isrc_manager.code_registry.workspace.QMessageBox.critical"
            ) as critical:
                self.panel._assign_selected_entry()
        critical.assert_not_called()

        with mock.patch.object(
            self.registry,
            "assign_entry_to_owner",
            side_effect=RuntimeError("assignment failed"),
        ):
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
        critical.assert_called_once()
        self.assertIn("assignment failed", critical.call_args.args[2])

        self.assertIsNone(
            self.conn.execute(
                "SELECT catalog_registry_entry_id FROM Tracks WHERE id=?",
                (track_id,),
            ).fetchone()[0]
        )

        contract_category = self.registry.fetch_category_by_system_key(
            BUILTIN_CATEGORY_CONTRACT_NUMBER
        )
        self.assertIsNotNone(contract_category)
        assert contract_category is not None
        self.registry.update_category(contract_category.id, prefix="CTR")
        source_contract_id = self._create_contract(title="Source Contract")
        destination_contract_id = self._create_contract(title="Destination Contract")
        contract_entry = self.contract_service.generate_registry_value_for_contract(
            source_contract_id,
            system_key=BUILTIN_CATEGORY_CONTRACT_NUMBER,
            created_via="test.workspace.reassign.failure",
        )
        self.panel.refresh()
        pump_events(app=self.app, cycles=2)
        self._select_entry_row(contract_entry.id)

        with mock.patch(
            "isrc_manager.code_registry.workspace._RegistryOwnerAssignmentDialog"
        ) as dialog_cls:
            dialog = dialog_cls.return_value
            dialog.exec.return_value = QDialog.Rejected
            with mock.patch(
                "isrc_manager.code_registry.workspace.QMessageBox.critical"
            ) as critical:
                self.panel._reassign_selected_entry()
        critical.assert_not_called()

        with mock.patch(
            "isrc_manager.code_registry.workspace._RegistryOwnerAssignmentDialog"
        ) as dialog_cls:
            dialog = dialog_cls.return_value
            dialog.exec.return_value = QDialog.Accepted
            dialog.assignment.return_value = None
            with mock.patch(
                "isrc_manager.code_registry.workspace.QMessageBox.critical"
            ) as critical:
                self.panel._reassign_selected_entry()
        critical.assert_not_called()

        with mock.patch.object(
            self.registry,
            "reassign_entry_to_owner",
            side_effect=RuntimeError("realignment failed"),
        ):
            with mock.patch(
                "isrc_manager.code_registry.workspace._RegistryOwnerAssignmentDialog"
            ) as dialog_cls:
                dialog = dialog_cls.return_value
                dialog.exec.return_value = QDialog.Accepted
                dialog.assignment.return_value = ("contract", destination_contract_id)
                with mock.patch(
                    "isrc_manager.code_registry.workspace.QMessageBox.critical"
                ) as critical:
                    self.panel._reassign_selected_entry()
        critical.assert_called_once()
        self.assertIn("realignment failed", critical.call_args.args[2])

        delete_entry = self.registry.generate_sha256_key(
            created_via="test.workspace.delete.failure"
        ).entry
        self.panel.refresh_entries()
        pump_events(app=self.app, cycles=2)
        self._select_entry_row(delete_entry.id)

        with mock.patch(
            "isrc_manager.code_registry.workspace.QMessageBox.question",
            return_value=QMessageBox.No,
        ) as question:
            self.panel._delete_selected_entry()
        question.assert_called_once()
        self.assertIsNotNone(self.registry.fetch_entry(delete_entry.id))

        with mock.patch.object(
            self.registry,
            "delete_entry",
            side_effect=RuntimeError("delete failed"),
        ):
            with mock.patch(
                "isrc_manager.code_registry.workspace.QMessageBox.question",
                return_value=QMessageBox.Yes,
            ):
                with mock.patch(
                    "isrc_manager.code_registry.workspace.QMessageBox.critical"
                ) as critical:
                    self.panel._delete_selected_entry()
        critical.assert_called_once()
        self.assertIn("delete failed", critical.call_args.args[2])


if __name__ == "__main__":
    unittest.main()

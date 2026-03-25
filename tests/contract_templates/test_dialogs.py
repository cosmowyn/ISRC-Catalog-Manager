import sqlite3
import tempfile
import unittest
from pathlib import Path

from isrc_manager.contract_templates.catalog import ContractTemplateCatalogService
from isrc_manager.contract_templates.dialogs import ContractTemplateWorkspacePanel
from isrc_manager.services import CustomFieldDefinitionService, DatabaseSchemaService
from tests.qt_test_helpers import pump_events, require_qapplication


class ContractTemplateWorkspacePanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = require_qapplication()

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.conn = sqlite3.connect(":memory:")
        schema = DatabaseSchemaService(self.conn, data_root=self.root)
        schema.init_db()
        schema.migrate_schema()
        self.custom_fields = CustomFieldDefinitionService(self.conn)
        self.custom_fields.ensure_fields(
            [
                {"name": "Mood", "field_type": "dropdown", "options": "Dark|Bright"},
                {"name": "Session Date", "field_type": "date"},
            ]
        )
        self.catalog_service = ContractTemplateCatalogService(
            self.conn,
            custom_field_definition_service=self.custom_fields,
        )
        self.panel = ContractTemplateWorkspacePanel(
            catalog_service_provider=lambda: self.catalog_service
        )
        self.panel.show()
        pump_events(app=self.app, cycles=3)

    def tearDown(self):
        self.panel.close()
        self.panel.deleteLater()
        pump_events(app=self.app, cycles=2)
        self.conn.close()
        self.tmpdir.cleanup()

    def test_panel_populates_symbol_table_and_detail_panel(self):
        self.assertEqual(self.panel.workspace_tabs.tabText(0), "Symbol Generator")
        self.assertGreater(self.panel.table.rowCount(), 0)
        self.assertTrue(self.panel.selected_symbol_edit.text().startswith("{{db."))
        self.assertIn("Resolver Target:", self.panel.detail_resolver_label.text())
        self.assertIn("Source Kind:", self.panel.detail_source_label.text())

    def test_panel_filters_and_copies_selected_symbol(self):
        self.panel.focus_namespace("contract")
        self.panel.search_edit.setText("signature")
        pump_events(app=self.app, cycles=3)

        self.assertEqual(self.panel.table.rowCount(), 1)
        self.panel.table.selectRow(0)
        pump_events(app=self.app, cycles=2)
        self.panel.copy_selected_symbol()

        self.assertEqual(
            self.app.clipboard().text(),
            "{{db.contract.signature_date}}",
        )

    def test_panel_manual_helper_normalizes_and_copies_symbol(self):
        self.panel.manual_key_edit.setText("License Date")
        pump_events(app=self.app, cycles=2)

        self.assertEqual(
            self.panel.manual_symbol_edit.text(),
            "{{manual.license_date}}",
        )
        self.panel.copy_manual_symbol()
        self.assertEqual(self.app.clipboard().text(), "{{manual.license_date}}")

    def test_panel_shows_custom_fields_as_stable_cf_symbols(self):
        self.panel.focus_namespace("custom")
        self.panel.search_edit.setText("mood")
        pump_events(app=self.app, cycles=3)

        self.assertEqual(self.panel.table.rowCount(), 1)
        self.panel.table.selectRow(0)
        pump_events(app=self.app, cycles=2)
        self.assertTrue(
            self.panel.selected_symbol_edit.text().startswith("{{db.custom.cf_")
        )
        self.assertEqual(self.panel.detail_source_label.text(), "Source Kind: Custom Field")

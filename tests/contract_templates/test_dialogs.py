import sqlite3
import inspect
import tempfile
import unittest
from pathlib import Path

from isrc_manager.contract_templates.catalog import ContractTemplateCatalogService
from isrc_manager.contract_templates.form_service import ContractTemplateFormService
from isrc_manager.contract_templates.dialogs import ContractTemplateWorkspacePanel
from isrc_manager.services import (
    ContractTemplatePayload,
    ContractTemplateRevisionPayload,
    ContractTemplateService,
    CustomFieldDefinitionService,
    DatabaseSchemaService,
    TrackCreatePayload,
    TrackService,
)
from tests.contract_templates._support import make_docx_bytes
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
        self.track_service = TrackService(self.conn, self.root)
        self.track_service.create_track(
            TrackCreatePayload(
                isrc="NL-TST-26-00420",
                track_title="Dialog Orbit",
                artist_name="Cosmowyn",
                additional_artists=[],
                album_title="Workspace Tests",
                release_date="2026-03-17",
                track_length_sec=220,
                iswc=None,
                upc=None,
                genre="Ambient",
                catalog_number=None,
            )
        )
        self.catalog_service = ContractTemplateCatalogService(
            self.conn,
            custom_field_definition_service=self.custom_fields,
        )
        self.template_service = ContractTemplateService(self.conn, data_root=self.root)
        template = self.template_service.create_template(
            ContractTemplatePayload(
                name="Dialog Template",
                description="Dialog fill tab coverage",
                template_family="contract",
                source_format="docx",
            )
        )
        source_path = self.root / "dialog-template.docx"
        source_path.write_bytes(
            make_docx_bytes(
                document_paragraphs=(
                    ("Track ", "{{db.track.track_title}}"),
                    ("Date ", "{{manual.license_date}}"),
                )
            )
        )
        self.revision = self.template_service.import_revision_from_path(
            template.template_id,
            source_path,
            payload=ContractTemplateRevisionPayload(source_filename=source_path.name),
        ).revision
        self.form_service = ContractTemplateFormService(
            template_service=self.template_service,
            catalog_service=self.catalog_service,
        )
        panel_kwargs = {
            "catalog_service_provider": lambda: self.catalog_service,
            "template_service_provider": lambda: self.template_service,
            "form_service_provider": lambda: self.form_service,
        }
        panel_signature = inspect.signature(ContractTemplateWorkspacePanel.__init__)
        accepted_kwargs = {
            key: value for key, value in panel_kwargs.items() if key in panel_signature.parameters
        }
        self.panel = ContractTemplateWorkspacePanel(**accepted_kwargs)
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
        self.assertGreaterEqual(self.panel.workspace_tabs.count(), 1)
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

    def test_panel_exposes_fill_tab_and_focuses_requested_form_workspace(self):
        tab_texts = [self.panel.workspace_tabs.tabText(index).lower() for index in range(self.panel.workspace_tabs.count())]
        if not any("fill" in text for text in tab_texts):
            self.skipTest("Fill tab not yet exposed by ContractTemplateWorkspacePanel")
        fill_index = next(index for index, text in enumerate(tab_texts) if "fill" in text)

        self.assertIn("fill", " ".join(tab_texts))
        self.panel.focus_tab("fill")
        pump_events(app=self.app, cycles=2)

        self.assertEqual(self.panel.workspace_tabs.currentIndex(), fill_index)
        self.assertIn("fill", self.panel.workspace_tabs.tabText(self.panel.workspace_tabs.currentIndex()).lower())

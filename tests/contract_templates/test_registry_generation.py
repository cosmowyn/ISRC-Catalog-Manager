import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from isrc_manager.code_registry import (
    BUILTIN_CATEGORY_CATALOG_NUMBER,
    BUILTIN_CATEGORY_CONTRACT_NUMBER,
    BUILTIN_CATEGORY_LICENSE_NUMBER,
)
from isrc_manager.contract_templates import (
    ContractTemplateCatalogService,
    ContractTemplateExportService,
    ContractTemplateFormService,
    ContractTemplatePayload,
    ContractTemplateRevisionPayload,
    ContractTemplateService,
)
from isrc_manager.contract_templates.dialogs import ContractTemplateWorkspacePanel
from isrc_manager.contracts import ContractPayload, ContractService
from isrc_manager.parties import PartyService
from isrc_manager.releases import ReleasePayload, ReleaseService, ReleaseTrackPlacement
from isrc_manager.services import DatabaseSchemaService, TrackCreatePayload, TrackService
from tests.contract_templates._support import FakeDocxHtmlAdapter, FakePagesAdapter, make_docx_bytes
from tests.qt_test_helpers import pump_events, require_qapplication


class ContractTemplateRegistryGenerationTests(unittest.TestCase):
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
        self.release_service = ReleaseService(self.conn, self.root)
        self.party_service = PartyService(self.conn)
        self.contract_service = ContractService(
            self.conn,
            self.root,
            party_service=self.party_service,
        )
        registry = self.track_service.code_registry_service()
        catalog_category = registry.fetch_category_by_system_key(BUILTIN_CATEGORY_CATALOG_NUMBER)
        contract_category = registry.fetch_category_by_system_key(BUILTIN_CATEGORY_CONTRACT_NUMBER)
        license_category = registry.fetch_category_by_system_key(BUILTIN_CATEGORY_LICENSE_NUMBER)
        assert catalog_category is not None
        assert contract_category is not None
        assert license_category is not None
        registry.update_category(catalog_category.id, prefix="ACR")
        registry.update_category(contract_category.id, prefix="CTR")
        registry.update_category(license_category.id, prefix="LIC")

        self.track_id = self.track_service.create_track(
            TrackCreatePayload(
                isrc="NL-TST-26-70001",
                track_title="Template Track",
                artist_name="Template Artist",
                additional_artists=[],
                album_title="Template Album",
                release_date="2026-04-07",
                track_length_sec=181,
                iswc=None,
                upc=None,
                genre="Ambient",
                catalog_number=None,
            )
        )
        self.release_id = self.release_service.create_release(
            ReleasePayload(
                title="Template Album",
                primary_artist="Template Artist",
                release_date="2026-04-07",
                placements=[ReleaseTrackPlacement(track_id=self.track_id)],
            )
        )
        self.contract_service.create_contract(
            ContractPayload(
                title="Template Contract",
                contract_type="license",
                status="draft",
            )
        )

        self.catalog_service = ContractTemplateCatalogService(self.conn)
        self.template_service = ContractTemplateService(self.conn, data_root=self.root)
        template = self.template_service.create_template(
            ContractTemplatePayload(
                name="Registry Template",
                description="Registry generation coverage",
                template_family="contract",
                source_format="docx",
            )
        )
        source_path = self.root / "registry-template.docx"
        source_path.write_bytes(
            make_docx_bytes(
                document_paragraphs=(
                    ("Track Catalog ", "{{db.track.catalog_number}}"),
                    ("Release Catalog ", "{{db.release.catalog_number}}"),
                    ("Contract Number ", "{{db.contract.contract_number}}"),
                    ("License Number ", "{{db.contract.license_number}}"),
                    ("Registry Key ", "{{db.contract.registry_sha256_key}}"),
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
            release_service=self.release_service,
            contract_service=self.contract_service,
        )
        self.export_service = ContractTemplateExportService(
            template_service=self.template_service,
            catalog_service=self.catalog_service,
            track_service=self.track_service,
            release_service=self.release_service,
            contract_service=self.contract_service,
            html_adapter=FakeDocxHtmlAdapter(),
            pages_adapter=FakePagesAdapter(),
        )
        self.panel = ContractTemplateWorkspacePanel(
            catalog_service_provider=lambda: self.catalog_service,
            template_service_provider=lambda: self.template_service,
            form_service_provider=lambda: self.form_service,
            export_service_provider=lambda: self.export_service,
        )
        self.panel.show()
        pump_events(app=self.app, cycles=3)
        self.panel.focus_tab("fill")
        pump_events(app=self.app, cycles=2)
        self.panel._select_combo_data(self.panel.fill_template_combo, template.template_id)
        self.panel._select_combo_data(self.panel.fill_revision_combo, self.revision.revision_id)
        self.panel.refresh_fill_form()
        pump_events(app=self.app, cycles=3)

    def tearDown(self):
        self.panel.close()
        self.panel.deleteLater()
        pump_events(app=self.app, cycles=2)
        self.conn.close()
        self.tmpdir.cleanup()

    def test_registry_backed_symbols_are_auto_fields_without_record_selectors(self):
        definition = self.form_service.build_form_definition(self.revision.revision_id)
        auto_symbols = {field.canonical_symbol for field in definition.auto_fields}

        self.assertEqual(len(definition.selector_fields), 0)
        self.assertEqual(
            auto_symbols,
            {
                "{{db.track.catalog_number}}",
                "{{db.release.catalog_number}}",
                "{{db.contract.contract_number}}",
                "{{db.contract.license_number}}",
                "{{db.contract.registry_sha256_key}}",
            },
        )
        self.assertEqual(self.panel.selector_widgets, {})
        self.assertFalse(self.panel.fill_auto_empty_label.isVisible())
        self.assertTrue(self.panel.fill_selector_empty_label.isVisible())

    def test_first_saved_draft_generates_and_persists_registry_values(self):
        self.panel.fill_draft_name_edit.setText("Draft Owned Registry Values")
        pump_events(app=self.app, cycles=2)

        self.panel.save_new_draft()
        pump_events(app=self.app, cycles=2)

        drafts = self.template_service.list_drafts(revision_id=self.revision.revision_id)
        self.assertEqual(len(drafts), 1)
        assignments = self.template_service.list_draft_registry_assignments(drafts[0].draft_id)
        self.assertEqual(len(assignments), 5)
        assignment_values = {
            assignment.canonical_symbol: assignment.registry_value for assignment in assignments
        }
        entry_count_before = self.conn.execute(
            "SELECT COUNT(*) FROM CodeRegistryEntries"
        ).fetchone()[0]

        self.panel.save_selected_draft()
        pump_events(app=self.app, cycles=2)

        persisted = self.template_service.list_draft_registry_assignments(drafts[0].draft_id)
        entry_count_after = self.conn.execute(
            "SELECT COUNT(*) FROM CodeRegistryEntries"
        ).fetchone()[0]

        self.assertEqual(entry_count_after, entry_count_before)
        self.assertEqual(
            {assignment.canonical_symbol: assignment.registry_value for assignment in persisted},
            assignment_values,
        )
        self.assertTrue(assignment_values["{{db.track.catalog_number}}"].startswith("ACR"))
        self.assertTrue(assignment_values["{{db.release.catalog_number}}"].startswith("ACR"))
        self.assertTrue(assignment_values["{{db.contract.contract_number}}"].startswith("CTR"))
        self.assertTrue(assignment_values["{{db.contract.license_number}}"].startswith("LIC"))
        self.assertRegex(
            assignment_values["{{db.contract.registry_sha256_key}}"],
            r"^[0-9a-f]{64}$",
        )
        self.assertIn("Saved draft", self.panel.fill_draft_status_label.text())

    def test_draft_registry_generation_is_blocked_when_prefix_is_missing(self):
        registry = self.track_service.code_registry_service()
        contract_category = registry.fetch_category_by_system_key(BUILTIN_CATEGORY_CONTRACT_NUMBER)
        self.assertIsNotNone(contract_category)
        assert contract_category is not None
        registry.update_category(contract_category.id, prefix=None)

        self.panel.refresh_fill_form()
        pump_events(app=self.app, cycles=2)

        self.assertIn("cannot be issued for this draft yet", self.panel.fill_warning_label.text())
        self.assertIn("Configure a prefix/namespace", self.panel.fill_warning_label.text())

        with mock.patch("isrc_manager.contract_templates.dialogs.QMessageBox.warning") as warning:
            self.panel.save_new_draft()

        warning.assert_called_once()
        self.assertEqual(
            self.template_service.list_drafts(revision_id=self.revision.revision_id),
            [],
        )


if __name__ == "__main__":
    unittest.main()

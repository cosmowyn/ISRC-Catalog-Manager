import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PySide6.QtWidgets import QPushButton

from isrc_manager.code_registry import (
    BUILTIN_CATEGORY_CATALOG_NUMBER,
    BUILTIN_CATEGORY_CONTRACT_NUMBER,
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
        assert catalog_category is not None
        assert contract_category is not None
        registry.update_category(catalog_category.id, prefix="ACR")
        registry.update_category(contract_category.id, prefix="CTR")

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
        self.contract_id = self.contract_service.create_contract(
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

    @staticmethod
    def _button(widget, text: str) -> QPushButton:
        for button in widget.findChildren(QPushButton):
            if button.text() == text:
                return button
        raise AssertionError(f"Could not find button {text!r}")

    def test_fill_form_selector_groups_can_generate_registry_backed_values(self):
        track_widget = self.panel.selector_widgets["{{db.track.catalog_number}}"]
        release_widget = self.panel.selector_widgets["{{db.release.catalog_number}}"]
        contract_widget = self.panel.selector_widgets["{{db.contract.contract_number}}"]
        hash_widget = self.panel.selector_widgets["{{db.contract.registry_sha256_key}}"]

        self.assertIs(contract_widget, hash_widget)
        self.assertEqual(
            self._button(hash_widget, "Generate Registry SHA-256 Key").text(),
            "Generate Registry SHA-256 Key",
        )

        self.panel._selector_combo(track_widget).setCurrentIndex(1)
        self.panel._selector_combo(release_widget).setCurrentIndex(1)
        self.panel._selector_combo(contract_widget).setCurrentIndex(1)
        pump_events(app=self.app, cycles=2)

        with (
            mock.patch("isrc_manager.contract_templates.dialogs.QMessageBox.information") as info,
            mock.patch("isrc_manager.contract_templates.dialogs.QMessageBox.warning") as warning,
            mock.patch("isrc_manager.contract_templates.dialogs.QMessageBox.critical") as critical,
        ):
            self._button(track_widget, "Generate Catalog Number").click()
            self._button(release_widget, "Generate Catalog Number").click()
            self._button(contract_widget, "Generate Contract Number").click()
            self._button(hash_widget, "Generate Registry SHA-256 Key").click()

        info.assert_not_called()
        warning.assert_not_called()
        critical.assert_not_called()

        track = self.track_service.fetch_track_snapshot(self.track_id)
        release = self.release_service.fetch_release(self.release_id)
        contract = self.contract_service.fetch_contract(self.contract_id)

        self.assertIsNotNone(track)
        self.assertIsNotNone(release)
        self.assertIsNotNone(contract)
        assert track is not None
        assert release is not None
        assert contract is not None
        self.assertTrue(str(track.catalog_number or "").startswith("ACR"))
        self.assertTrue(str(release.catalog_number or "").startswith("ACR"))
        self.assertTrue(str(contract.contract_number or "").startswith("CTR"))
        self.assertRegex(str(contract.registry_sha256_key or ""), r"^[0-9a-f]{64}$")
        self.assertIsNotNone(track.catalog_registry_entry_id)
        self.assertIsNotNone(release.catalog_registry_entry_id)
        self.assertIsNotNone(contract.contract_registry_entry_id)
        self.assertIsNotNone(contract.registry_sha256_key_entry_id)
        self.assertIn("Generated", self.panel.fill_status_label.text())


if __name__ == "__main__":
    unittest.main()

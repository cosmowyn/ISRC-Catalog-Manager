import inspect
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PySide6.QtCore import QDate, QUrl
from PySide6.QtWidgets import QDockWidget, QPushButton, QScrollArea, QTabBar

from isrc_manager.contract_templates.catalog import ContractTemplateCatalogService
from isrc_manager.contract_templates.dialogs import (
    ContractTemplateWorkspacePanel,
    QWebEnginePage,
    _ContractTemplatePreviewPage,
)
from isrc_manager.contract_templates.form_service import ContractTemplateFormService
from isrc_manager.external_launch import (
    clear_recorded_external_launches,
    get_recorded_external_launches,
)
from isrc_manager.services import (
    ContractTemplateExportService,
    ContractTemplatePayload,
    ContractTemplateRevisionPayload,
    ContractTemplateService,
    CustomFieldDefinitionService,
    DatabaseSchemaService,
    TrackCreatePayload,
    TrackService,
)
from tests.contract_templates._support import (
    FakeDocxHtmlAdapter,
    FakePagesAdapter,
    make_docx_bytes,
)
from tests.qt_test_helpers import pump_events, require_qapplication, wait_for


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
                artist_name="Moonwake",
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
        self.html_adapter = FakeDocxHtmlAdapter()
        self.pages_adapter = FakePagesAdapter()
        self.export_service = ContractTemplateExportService(
            template_service=self.template_service,
            catalog_service=self.catalog_service,
            track_service=self.track_service,
            html_adapter=self.html_adapter,
            pages_adapter=self.pages_adapter,
        )
        panel_kwargs = {
            "catalog_service_provider": lambda: self.catalog_service,
            "template_service_provider": lambda: self.template_service,
            "form_service_provider": lambda: self.form_service,
            "export_service_provider": lambda: self.export_service,
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

    def _focus_symbols(self):
        self.panel.focus_tab("symbols")
        pump_events(app=self.app, cycles=3)

    def _focus_import(self):
        self.panel.focus_tab("import")
        pump_events(app=self.app, cycles=3)

    def _focus_fill(self):
        self.panel.focus_tab("fill")
        pump_events(app=self.app, cycles=3)

    def test_panel_populates_symbol_table_and_detail_panel(self):
        self.assertEqual(
            [
                self.panel.workspace_tabs.tabText(index)
                for index in range(self.panel.workspace_tabs.count())
            ],
            ["Import", "Symbol Generator", "Fill Form"],
        )
        self._focus_symbols()
        self.assertGreater(self.panel.table.rowCount(), 0)
        self.assertTrue(self.panel.selected_symbol_edit.text().startswith("{{db."))
        self.assertIn("Resolver Target:", self.panel.detail_resolver_label.text())
        self.assertIn("Source Kind:", self.panel.detail_source_label.text())

    def test_panel_filters_and_copies_selected_symbol(self):
        self._focus_symbols()
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
        self._focus_symbols()
        self.panel.manual_key_edit.setText("License Date")
        pump_events(app=self.app, cycles=2)

        self.assertEqual(
            self.panel.manual_symbol_edit.text(),
            "{{manual.license_date}}",
        )
        self.panel.copy_manual_symbol()
        self.assertEqual(self.app.clipboard().text(), "{{manual.license_date}}")

    def test_panel_double_click_copies_symbol_to_clipboard(self):
        self._focus_symbols()
        self.panel.focus_namespace("contract")
        self.panel.search_edit.setText("signature")
        pump_events(app=self.app, cycles=3)

        index = self.panel.table.model().index(0, 4)
        self.panel.table.doubleClicked.emit(index)
        pump_events(app=self.app, cycles=2)

        self.assertEqual(self.app.clipboard().text(), "{{db.contract.signature_date}}")

    def test_panel_shows_custom_fields_as_stable_cf_symbols(self):
        self._focus_symbols()
        self.panel.focus_namespace("custom")
        self.panel.search_edit.setText("mood")
        pump_events(app=self.app, cycles=3)

        self.assertEqual(self.panel.table.rowCount(), 1)
        self.panel.table.selectRow(0)
        pump_events(app=self.app, cycles=2)
        self.assertTrue(self.panel.selected_symbol_edit.text().startswith("{{db.custom.cf_"))
        self.assertEqual(self.panel.detail_source_label.text(), "Source Kind: Custom Field")

    def test_panel_exposes_fill_tab_and_focuses_requested_form_workspace(self):
        tab_texts = [
            self.panel.workspace_tabs.tabText(index).lower()
            for index in range(self.panel.workspace_tabs.count())
        ]
        if not any("fill" in text for text in tab_texts):
            self.skipTest("Fill tab not yet exposed by ContractTemplateWorkspacePanel")
        fill_index = next(index for index, text in enumerate(tab_texts) if "fill" in text)

        self.assertIn("fill", " ".join(tab_texts))
        self.panel.focus_tab("fill")
        pump_events(app=self.app, cycles=2)

        self.assertEqual(self.panel.workspace_tabs.currentIndex(), fill_index)
        self.assertIn(
            "fill",
            self.panel.workspace_tabs.tabText(self.panel.workspace_tabs.currentIndex()).lower(),
        )

    def test_import_workspace_exposes_expected_docks_and_primary_title(self):
        self._focus_import()
        host = self.panel._tab_hosts["import"]
        dock_names = [dock.objectName() for dock in host._docks]
        dock_titles = [dock.windowTitle() for dock in host._docks]
        self.assertEqual(
            dock_names,
            [
                "contractTemplateImportAdminDock",
                "contractTemplateRevisionInventoryDock",
                "contractTemplatePlaceholderInventoryDock",
                "contractTemplateDraftArchiveDock",
                "contractTemplateSnapshotsArtifactsDock",
            ],
        )
        self.assertEqual(dock_titles[0], "Import / Admin")
        self.assertTrue(host.isVisible())
        self.assertTrue(all(dock.isVisible() for dock in host._docks))
        self.assertTrue(all(dock.titleBarWidget() is not None for dock in host._docks))
        first_title_bar = host._docks[0].titleBarWidget()
        self.assertIsNotNone(first_title_bar)
        options_button = first_title_bar.findChild(
            QPushButton,
            "contractTemplateImportAdminDockOptionsButton",
        )
        self.assertIsNotNone(options_button)
        action_texts = [
            action.text() for action in options_button.menu().actions() if action.text()
        ]
        self.assertIn("Dock Left", action_texts)
        self.assertIn("Dock Right", action_texts)
        self.assertIn("Dock Top", action_texts)
        self.assertIn("Dock Bottom", action_texts)
        self.assertIn("Move Up In Stack", action_texts)
        self.assertIn("Move Down In Stack", action_texts)

    def test_fill_tab_can_save_and_resume_drafts_across_storage_modes(self):
        self._focus_fill()

        selector = self.panel.selector_widgets["{{db.track.track_title}}"]
        date_widget = self.panel.manual_widgets["{{manual.license_date}}"]
        draft_date = QDate.currentDate().addDays(1)
        updated_date = draft_date.addDays(6)
        selector.setCurrentIndex(1)
        date_widget.setDate(draft_date)
        self.panel.fill_draft_name_edit.setText("Managed Resume Draft")
        self.panel.fill_draft_storage_combo.setCurrentIndex(1)
        pump_events(app=self.app, cycles=2)

        self.panel.save_new_draft()
        pump_events(app=self.app, cycles=2)

        drafts = self.template_service.list_drafts(revision_id=self.revision.revision_id)
        self.assertEqual(len(drafts), 1)
        self.assertEqual(self.panel.fill_draft_combo.count(), 2)
        self.assertEqual(self.panel.fill_draft_combo.currentData(), drafts[0].draft_id)
        self.assertEqual(self.panel.fill_draft_name_edit.text(), "Managed Resume Draft")
        self.assertEqual(self.panel.fill_draft_storage_combo.currentData(), "managed_file")
        self.assertIn("Saved draft", self.panel.fill_draft_status_label.text())
        self.assertEqual(drafts[0].storage_mode, "managed_file")
        self.assertFalse(drafts[0].stored_in_database)
        self.assertEqual(
            self.template_service.fetch_draft_payload(drafts[0].draft_id),
            {
                "revision_id": self.revision.revision_id,
                "db_selections": {"{{db.track.track_title}}": "1"},
                "manual_values": {"{{manual.license_date}}": draft_date.toString("yyyy-MM-dd")},
                "type_overrides": {},
            },
        )

        self.panel.reset_fill_form()
        pump_events(app=self.app, cycles=2)
        self.assertEqual(
            self.panel.current_fill_state(),
            {
                "revision_id": self.revision.revision_id,
                "db_selections": {},
                "manual_values": {},
                "type_overrides": {},
            },
        )

        for index in range(self.panel.fill_draft_combo.count()):
            if self.panel.fill_draft_combo.itemData(index) == drafts[0].draft_id:
                self.panel.fill_draft_combo.setCurrentIndex(index)
                break
        pump_events(app=self.app, cycles=2)

        self.panel.load_selected_draft()
        pump_events(app=self.app, cycles=2)
        self.assertEqual(
            self.panel.current_fill_state(),
            {
                "revision_id": self.revision.revision_id,
                "db_selections": {"{{db.track.track_title}}": "1"},
                "manual_values": {"{{manual.license_date}}": draft_date.toString("yyyy-MM-dd")},
                "type_overrides": {},
            },
        )
        self.assertEqual(self.panel.fill_draft_name_edit.text(), "Managed Resume Draft")
        self.assertEqual(self.panel.fill_draft_storage_combo.currentData(), "managed_file")
        self.assertIn("Loaded draft", self.panel.fill_draft_status_label.text())

        restored_date_widget = self.panel.manual_widgets["{{manual.license_date}}"]
        restored_date_widget.setDate(updated_date)
        self.panel.fill_draft_storage_combo.setCurrentIndex(0)
        pump_events(app=self.app, cycles=2)

        self.panel.save_selected_draft()
        pump_events(app=self.app, cycles=2)

        updated = self.template_service.fetch_draft(drafts[0].draft_id)
        self.assertEqual(
            len(self.template_service.list_drafts(revision_id=self.revision.revision_id)), 1
        )
        self.assertEqual(updated.draft_id, drafts[0].draft_id)
        self.assertEqual(updated.storage_mode, "database")
        self.assertTrue(updated.stored_in_database)
        self.assertEqual(self.panel.fill_draft_combo.currentData(), drafts[0].draft_id)
        self.assertEqual(self.panel.fill_draft_storage_combo.currentData(), "database")
        self.assertIn("Saved draft", self.panel.fill_draft_status_label.text())
        self.assertEqual(
            self.template_service.fetch_draft_payload(drafts[0].draft_id),
            {
                "revision_id": self.revision.revision_id,
                "db_selections": {"{{db.track.track_title}}": "1"},
                "manual_values": {"{{manual.license_date}}": updated_date.toString("yyyy-MM-dd")},
                "type_overrides": {},
            },
        )

    def test_fill_tab_renders_html_draft_preview_in_web_view(self):
        html_template = self.template_service.create_template(
            ContractTemplatePayload(
                name="HTML Dialog Template",
                description="Dialog HTML preview coverage",
                template_family="contract",
                source_format="html",
            )
        )
        html_root = self.root / "dialog-html-template"
        (html_root / "assets").mkdir(parents=True)
        (html_root / "assets" / "logo.png").write_bytes(b"logo")
        html_path = html_root / "preview.html"
        html_path.write_text(
            "<html><body><img src='assets/logo.png'><p>{{manual.license_date}}</p></body></html>",
            encoding="utf-8",
        )
        html_revision = self.template_service.import_revision_from_path(
            html_template.template_id,
            html_path,
            payload=ContractTemplateRevisionPayload(source_filename=html_path.name),
        ).revision
        self.panel.refresh()
        self._focus_fill()

        self.panel._select_combo_data(self.panel.fill_template_combo, html_template.template_id)
        self.panel._select_combo_data(self.panel.fill_revision_combo, html_revision.revision_id)
        self.panel.refresh_fill_form()
        pump_events(app=self.app, cycles=3)

        manual_widget = self.panel.manual_widgets["{{manual.license_date}}"]
        manual_widget.setDate(QDate(2026, 4, 5))
        self.panel.fill_draft_name_edit.setText("HTML Preview Draft")
        pump_events(app=self.app, cycles=2)

        self.panel.refresh_current_html_preview()
        pump_events(app=self.app, cycles=5)

        drafts = self.template_service.list_drafts(revision_id=html_revision.revision_id)
        self.assertEqual(len(drafts), 0)
        self.assertIsNotNone(self.panel.fill_html_preview_view)
        wait_for(
            lambda: bool(self.panel.fill_html_preview_view.url().toLocalFile()),
            timeout_ms=5000,
            app=self.app,
            description="HTML preview URL to load",
        )
        wait_for(
            lambda: "Previewing current HTML draft state"
            in self.panel.fill_preview_status_label.text(),
            timeout_ms=5000,
            app=self.app,
            description="HTML preview status to become current",
        )
        preview_path = Path(self.panel.fill_html_preview_view.url().toLocalFile())
        self.assertTrue(preview_path.exists())
        self.assertTrue((preview_path.parent / "assets" / "logo.png").exists())
        draft_root = self.template_service.draft_store.root_path
        self.assertFalse(draft_root is not None and preview_path.is_relative_to(draft_root))
        self.assertIn(
            "Previewing current HTML draft state", self.panel.fill_preview_status_label.text()
        )

    def test_preview_page_keeps_clear_preview_navigation_internal(self):
        if QWebEnginePage is None:
            self.skipTest("Qt WebEngine is unavailable")
        page = _ContractTemplatePreviewPage()
        try:
            with mock.patch(
                "isrc_manager.contract_templates.dialogs.open_external_url"
            ) as open_url:
                accepted = page.acceptNavigationRequest(
                    QUrl("data:text/html;charset=UTF-8,"),
                    QWebEnginePage.NavigationType.NavigationTypeOther,
                    True,
                )
            self.assertTrue(accepted)
            open_url.assert_not_called()
        finally:
            page.deleteLater()

    def test_preview_page_routes_external_navigation_through_launch_guard(self):
        if QWebEnginePage is None:
            self.skipTest("Qt WebEngine is unavailable")
        clear_recorded_external_launches()
        page = _ContractTemplatePreviewPage()
        try:
            accepted = page.acceptNavigationRequest(
                QUrl("https://example.com/template-preview"),
                QWebEnginePage.NavigationType.NavigationTypeLinkClicked,
                True,
            )
        finally:
            page.deleteLater()

        self.assertFalse(accepted)
        requests = get_recorded_external_launches()
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].source, "ContractTemplatePreviewPage")
        self.assertEqual(requests[0].target, "https://example.com/template-preview")
        self.assertTrue(requests[0].blocked)

    def test_fill_tab_can_export_pdf_and_update_latest_artifact_status(self):
        self._focus_fill()

        selector = self.panel.selector_widgets["{{db.track.track_title}}"]
        date_widget = self.panel.manual_widgets["{{manual.license_date}}"]
        export_date = QDate.currentDate().addDays(4)
        selector.setCurrentIndex(1)
        date_widget.setDate(export_date)
        self.panel.fill_draft_name_edit.setText("Export From Fill Tab")
        pump_events(app=self.app, cycles=2)

        self.panel.export_current_pdf()
        pump_events(app=self.app, cycles=3)

        drafts = self.template_service.list_drafts(revision_id=self.revision.revision_id)
        self.assertEqual(len(drafts), 1)
        updated = self.template_service.fetch_draft(drafts[0].draft_id)
        self.assertIsNotNone(updated.last_resolved_snapshot_id)
        artifacts = self.template_service.list_output_artifacts(
            snapshot_id=updated.last_resolved_snapshot_id
        )
        self.assertEqual(
            sorted(artifact.artifact_type for artifact in artifacts),
            ["pdf", "resolved_docx"],
        )
        pdf_artifact = next(artifact for artifact in artifacts if artifact.artifact_type == "pdf")
        self.assertTrue(Path(pdf_artifact.output_path).exists())
        self.assertEqual(len(self.pages_adapter.pdf_calls), 1)
        self.assertEqual(len(self.html_adapter.calls), 0)
        self.assertIn("Exported PDF", self.panel.fill_export_status_label.text())
        self.assertIn(str(pdf_artifact.output_path), self.panel.fill_export_status_label.text())

    def test_admin_tab_can_import_templates_and_export_selected_draft(self):
        source_path = self.root / "admin-import-template.docx"
        source_path.write_bytes(
            make_docx_bytes(document_paragraphs=(("Imported ", "{{manual.signing_city}}"),))
        )
        with (
            mock.patch(
                "isrc_manager.contract_templates.dialogs.QFileDialog.getOpenFileName",
                return_value=(str(source_path), "Template Documents (*.docx *.pages)"),
            ),
            mock.patch(
                "isrc_manager.contract_templates.dialogs.QInputDialog.getText",
                return_value=("Imported Admin Template", True),
            ),
        ):
            self.panel.import_template_from_file()
        pump_events(app=self.app, cycles=3)

        self._focus_fill()
        self.panel._select_revision_context(self.revision.template_id, self.revision.revision_id)
        pump_events(app=self.app, cycles=2)
        selector = self.panel.selector_widgets["{{db.track.track_title}}"]
        date_widget = self.panel.manual_widgets["{{manual.license_date}}"]
        admin_export_date = QDate.currentDate().addDays(7)
        selector.setCurrentIndex(1)
        date_widget.setDate(admin_export_date)
        self.panel.fill_draft_name_edit.setText("Admin Export Draft")
        self.panel.save_new_draft()
        pump_events(app=self.app, cycles=2)

        self.panel.focus_tab("admin")
        self.panel.refresh_admin_workspace(selected_template_id=self.revision.template_id)
        pump_events(app=self.app, cycles=3)

        self.assertGreaterEqual(self.panel.admin_template_table.rowCount(), 2)
        self.assertGreaterEqual(self.panel.admin_revision_table.rowCount(), 1)
        self.assertGreaterEqual(self.panel.admin_placeholder_table.rowCount(), 1)
        self.assertGreaterEqual(self.panel.admin_draft_table.rowCount(), 1)

        self.panel.export_selected_admin_draft()
        pump_events(app=self.app, cycles=3)

        self.assertGreaterEqual(self.panel.admin_snapshot_table.rowCount(), 1)
        self.assertGreaterEqual(self.panel.admin_artifact_table.rowCount(), 2)
        self.assertIn("Exported draft", self.panel.admin_status_label.text())
        first_artifact_id = self.panel._selected_admin_artifact_id()
        first_artifact = self.template_service.fetch_output_artifact(first_artifact_id)
        self.assertIsNotNone(first_artifact)
        self.assertTrue(Path(first_artifact.output_path).exists())

    def test_fill_tab_restores_explicit_false_and_zero_values_from_draft(self):
        source_path = self.root / "dialog-template-bool-number.docx"
        source_path.write_bytes(
            make_docx_bytes(
                document_paragraphs=(
                    ("Track ", "{{db.track.track_title}}"),
                    ("Exclusive ", "{{manual.is_exclusive}}"),
                    ("Royalty Share ", "{{manual.royalty_share}}"),
                )
            )
        )
        revision = self.template_service.import_revision_from_path(
            self.revision.template_id,
            source_path,
            payload=ContractTemplateRevisionPayload(source_filename=source_path.name),
        ).revision
        self.panel.refresh()
        self._focus_fill()

        for index in range(self.panel.fill_revision_combo.count()):
            if self.panel.fill_revision_combo.itemData(index) == revision.revision_id:
                self.panel.fill_revision_combo.setCurrentIndex(index)
                break
        pump_events(app=self.app, cycles=3)

        selector = self.panel.selector_widgets["{{db.track.track_title}}"]
        is_exclusive = self.panel.manual_widgets["{{manual.is_exclusive}}"]
        royalty_share = self.panel.manual_widgets["{{manual.royalty_share}}"]

        selector.setCurrentIndex(1)
        is_exclusive.setChecked(True)
        is_exclusive.setChecked(False)
        royalty_share.setValue(5.0)
        royalty_share.setValue(0.0)
        self.panel.fill_draft_name_edit.setText("Explicit False Zero")
        pump_events(app=self.app, cycles=2)

        self.panel.save_new_draft()
        pump_events(app=self.app, cycles=2)

        drafts = self.template_service.list_drafts(revision_id=revision.revision_id)
        self.assertEqual(len(drafts), 1)
        self.assertEqual(
            self.template_service.fetch_draft_payload(drafts[0].draft_id),
            {
                "revision_id": revision.revision_id,
                "db_selections": {"{{db.track.track_title}}": "1"},
                "manual_values": {
                    "{{manual.is_exclusive}}": False,
                    "{{manual.royalty_share}}": 0,
                },
                "type_overrides": {},
            },
        )

        self.panel.reset_fill_form()
        pump_events(app=self.app, cycles=2)
        self.assertEqual(is_exclusive.property("has_user_value"), False)
        self.assertEqual(royalty_share.property("has_user_value"), False)

        for index in range(self.panel.fill_draft_combo.count()):
            if self.panel.fill_draft_combo.itemData(index) == drafts[0].draft_id:
                self.panel.fill_draft_combo.setCurrentIndex(index)
                break
        pump_events(app=self.app, cycles=2)

        self.panel.load_selected_draft()
        pump_events(app=self.app, cycles=2)

        restored_exclusive = self.panel.manual_widgets["{{manual.is_exclusive}}"]
        restored_share = self.panel.manual_widgets["{{manual.royalty_share}}"]
        self.assertEqual(
            self.panel.current_fill_state(),
            {
                "revision_id": revision.revision_id,
                "db_selections": {"{{db.track.track_title}}": "1"},
                "manual_values": {
                    "{{manual.is_exclusive}}": False,
                    "{{manual.royalty_share}}": 0,
                },
                "type_overrides": {},
            },
        )
        self.assertFalse(restored_exclusive.isChecked())
        self.assertTrue(bool(restored_exclusive.property("has_user_value")))
        self.assertEqual(restored_share.value(), 0.0)
        self.assertTrue(bool(restored_share.property("has_user_value")))

    def test_fill_workspace_uses_two_column_docks_and_preview_can_float_when_unlocked(self):
        self._focus_fill()
        host = self.panel._tab_hosts["fill"]
        dock_names = [dock.objectName() for dock in host._docks]
        self.assertEqual(
            dock_names,
            [
                "contractTemplateFillRevisionDock",
                "contractTemplateFillDraftWorkspaceDock",
                "contractTemplateFillResolvedExportDock",
                "contractTemplateFillDraftNotesDock",
                "contractTemplateFillAutomaticFieldsDock",
                "contractTemplateFillDatabaseFieldsDock",
                "contractTemplateFillManualFieldsDock",
                "contractTemplateHtmlPreviewDock",
            ],
        )
        self.assertTrue(host.isVisible())
        self.assertTrue(all(dock.isVisible() for dock in host._docks))
        revision_dock = next(
            dock for dock in host._docks if dock.objectName() == "contractTemplateFillRevisionDock"
        )
        automatic_dock = next(
            dock
            for dock in host._docks
            if dock.objectName() == "contractTemplateFillAutomaticFieldsDock"
        )
        selector_dock = next(
            dock
            for dock in host._docks
            if dock.objectName() == "contractTemplateFillDatabaseFieldsDock"
        )
        manual_dock = next(
            dock
            for dock in host._docks
            if dock.objectName() == "contractTemplateFillManualFieldsDock"
        )
        preview_dock = next(
            dock for dock in host._docks if dock.objectName() == "contractTemplateHtmlPreviewDock"
        )
        self.assertIsInstance(revision_dock.widget(), QScrollArea)
        self.assertIsInstance(automatic_dock.widget(), QScrollArea)
        self.assertIsInstance(selector_dock.widget(), QScrollArea)
        self.assertIsInstance(manual_dock.widget(), QScrollArea)
        self.assertNotIsInstance(preview_dock.widget(), QScrollArea)
        self.assertLess(revision_dock.geometry().x(), automatic_dock.geometry().x())
        self.assertLess(automatic_dock.geometry().x(), preview_dock.geometry().x())
        host.set_locked(False)
        pump_events(app=self.app, cycles=2)
        self.assertTrue(
            bool(preview_dock.features() & QDockWidget.DockWidgetFeature.DockWidgetFloatable),
        )
        preview_dock.setFloating(True)
        pump_events(app=self.app, cycles=2)
        self.assertTrue(preview_dock.isFloating())
        preview_dock.setFloating(False)
        host.set_locked(True)

    def test_locked_layout_preserves_tabified_dock_switching(self):
        self._focus_fill()
        host = self.panel._tab_hosts["fill"]
        docks = {dock.objectName(): dock for dock in host._docks}
        revision_dock = docks["contractTemplateFillRevisionDock"]
        draft_dock = docks["contractTemplateFillDraftWorkspaceDock"]

        host.set_locked(False)
        host.main_window.tabifyDockWidget(revision_dock, draft_dock)
        pump_events(app=self.app, cycles=2)

        self.assertIn(draft_dock, host.main_window.tabifiedDockWidgets(revision_dock))

        host.set_locked(True)
        pump_events(app=self.app, cycles=2)
        self.assertEqual(revision_dock.features(), QDockWidget.NoDockWidgetFeatures)
        self.assertEqual(draft_dock.features(), QDockWidget.NoDockWidgetFeatures)
        dock_tab_bar = next(
            (tab_bar for tab_bar in host.main_window.findChildren(QTabBar) if tab_bar.count() >= 2),
            None,
        )
        self.assertIsNotNone(dock_tab_bar)
        self.assertTrue(dock_tab_bar.isEnabled())
        next_index = 1 if dock_tab_bar.currentIndex() == 0 else 0
        dock_tab_bar.setCurrentIndex(next_index)
        pump_events(app=self.app, cycles=2)
        self.assertEqual(dock_tab_bar.currentIndex(), next_index)

    def test_fill_workspace_move_up_in_stack_reorders_left_column(self):
        self._focus_fill()
        host = self.panel._tab_hosts["fill"]
        docks = {dock.objectName(): dock for dock in host._docks}
        draft_dock = docks["contractTemplateFillDraftWorkspaceDock"]
        export_dock = docks["contractTemplateFillResolvedExportDock"]

        host.set_locked(False)
        pump_events(app=self.app, cycles=2)

        self.assertGreater(export_dock.geometry().y(), draft_dock.geometry().y())
        host.move_dock_in_stack(export_dock, -1)
        pump_events(app=self.app, cycles=3)
        self.assertLess(export_dock.geometry().y(), draft_dock.geometry().y())

    def test_reset_layout_restores_default_fill_layout_and_persists_reset_state(self):
        self._focus_fill()
        host = self.panel._tab_hosts["fill"]
        preview_dock = next(
            dock for dock in host._docks if dock.objectName() == "contractTemplateHtmlPreviewDock"
        )

        host.set_locked(False)
        preview_dock.setFloating(True)
        pump_events(app=self.app, cycles=2)
        self.assertTrue(preview_dock.isFloating())

        host.reset_to_default_layout()
        pump_events(app=self.app, cycles=3)
        self.assertTrue(host._locked)
        self.assertFalse(preview_dock.isFloating())

        reset_state = self.panel.capture_layout_state()

        panel_kwargs = {
            "catalog_service_provider": lambda: self.catalog_service,
            "template_service_provider": lambda: self.template_service,
            "form_service_provider": lambda: self.form_service,
            "export_service_provider": lambda: self.export_service,
        }
        panel_signature = inspect.signature(ContractTemplateWorkspacePanel.__init__)
        accepted_kwargs = {
            key: value for key, value in panel_kwargs.items() if key in panel_signature.parameters
        }
        restored_panel = ContractTemplateWorkspacePanel(**accepted_kwargs)
        try:
            restored_panel.show()
            pump_events(app=self.app, cycles=2)
            restored_panel.restore_layout_state(reset_state)
            restored_panel.focus_tab("fill")
            pump_events(app=self.app, cycles=4)
            restored_host = restored_panel._tab_hosts["fill"]
            restored_preview_dock = next(
                dock
                for dock in restored_host._docks
                if dock.objectName() == "contractTemplateHtmlPreviewDock"
            )
            self.assertFalse(restored_preview_dock.isFloating())
            self.assertTrue(restored_host._locked)
        finally:
            restored_panel.close()
            restored_panel.deleteLater()
            pump_events(app=self.app, cycles=2)

    def test_hiding_fill_draft_workspace_compacts_remaining_left_column_space(self):
        self._focus_fill()
        host = self.panel._tab_hosts["fill"]
        revision_dock = next(
            dock for dock in host._docks if dock.objectName() == "contractTemplateFillRevisionDock"
        )
        draft_dock = next(
            dock
            for dock in host._docks
            if dock.objectName() == "contractTemplateFillDraftWorkspaceDock"
        )
        export_dock = next(
            dock
            for dock in host._docks
            if dock.objectName() == "contractTemplateFillResolvedExportDock"
        )
        initial_export_y = export_dock.geometry().y()
        host.set_locked(False)
        pump_events(app=self.app, cycles=2)
        draft_dock.hide()
        pump_events(app=self.app, cycles=4)

        self.assertFalse(draft_dock.isVisible())
        self.assertLess(export_dock.geometry().y(), initial_export_y)
        self.assertLessEqual(export_dock.geometry().y(), revision_dock.geometry().bottom() + 2)

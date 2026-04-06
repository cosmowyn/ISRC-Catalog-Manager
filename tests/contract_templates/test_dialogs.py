import inspect
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PySide6.QtCore import QDate, QEvent, QPoint, QSize, Qt, QUrl
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import QDockWidget, QMainWindow, QPushButton, QScrollArea, QTabBar

from isrc_manager.catalog_workspace import CatalogWorkspaceDock
from isrc_manager.contract_templates.catalog import ContractTemplateCatalogService
from isrc_manager.contract_templates.dialogs import (
    ContractTemplateWorkspacePanel,
    QWebEnginePage,
    QWebEngineView,
    _ContractTemplatePreviewPage,
    _DockableWorkspaceTab,
    _InteractiveHtmlPreviewView,
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

    def _panel_constructor_kwargs(self):
        panel_kwargs = {
            "catalog_service_provider": lambda: self.catalog_service,
            "template_service_provider": lambda: self.template_service,
            "form_service_provider": lambda: self.form_service,
            "export_service_provider": lambda: self.export_service,
        }
        panel_signature = inspect.signature(ContractTemplateWorkspacePanel.__init__)
        return {
            key: value for key, value in panel_kwargs.items() if key in panel_signature.parameters
        }


class _FakeNativeGestureEvent:
    def __init__(self, gesture_type, value=0.0):
        self._gesture_type = gesture_type
        self._value = float(value)
        self.accepted = False

    def type(self):
        return QEvent.NativeGesture

    def gestureType(self):
        return self._gesture_type

    def value(self):
        return self._value

    def accept(self):
        self.accepted = True


class _FakeWheelEvent:
    def __init__(self, *, modifiers=Qt.NoModifier, angle_delta_y=0, pixel_delta_y=0):
        self._modifiers = modifiers
        self._angle_delta = QPoint(0, int(angle_delta_y))
        self._pixel_delta = QPoint(0, int(pixel_delta_y))
        self.accepted = False

    def modifiers(self):
        return self._modifiers

    def angleDelta(self):
        return self._angle_delta

    def pixelDelta(self):
        return self._pixel_delta

    def accept(self):
        self.accepted = True


class ContractTemplateWorkspacePanelBehaviorTests(ContractTemplateWorkspacePanelTests):
    class _OuterWorkspaceWindow(QMainWindow):
        def __init__(self):
            super().__init__()
            self.scheduled_saves = 0

        def _schedule_main_dock_state_save(self):
            self.scheduled_saves += 1

    def _fill_host(self):
        self._focus_fill()
        return self.panel._tab_hosts["fill"]

    def _fill_dock(self, object_name: str):
        host = self.panel._tab_hosts["fill"]
        return next(dock for dock in host._docks if dock.objectName() == object_name)

    @staticmethod
    def _visible_nonfloating_docks(host):
        visible = [dock for dock in host._docks if dock.isVisible() and not dock.isFloating()]
        tabified = {
            peer
            for dock in visible
            for peer in host.main_window.tabifiedDockWidgets(dock)
            if peer.isVisible()
        }
        return [dock for dock in visible if dock not in tabified]

    def _assert_no_visible_dock_overlap(self, host):
        visible_docks = self._visible_nonfloating_docks(host)
        handle_tolerance = 12
        for index, dock in enumerate(visible_docks):
            for peer in visible_docks[index + 1 :]:
                intersection = dock.geometry().intersected(peer.geometry())
                self.assertFalse(
                    intersection.width() > handle_tolerance
                    and intersection.height() > handle_tolerance,
                    msg=(
                        f"{dock.objectName()} overlapped {peer.objectName()} with "
                        f"{intersection.getRect()}"
                    ),
                )

    def _make_outer_workspace_dock(
        self, window: QMainWindow, object_name: str
    ) -> CatalogWorkspaceDock:
        panel_kwargs = self._panel_constructor_kwargs()
        return CatalogWorkspaceDock(
            window,
            dock_title="Contract Template Workspace",
            dock_object_name=object_name,
            panel_factory=lambda outer_dock: ContractTemplateWorkspacePanel(
                parent=outer_dock,
                **panel_kwargs,
            ),
        )

    def _load_live_fill_html_preview(self):
        html_template = self.template_service.create_template(
            ContractTemplatePayload(
                name="HTML Interaction Template",
                description="Preview interaction stability coverage",
                template_family="contract",
                source_format="html",
            )
        )
        html_root = self.root / "dialog-html-interaction-template"
        (html_root / "assets").mkdir(parents=True, exist_ok=True)
        (html_root / "assets" / "logo.png").write_bytes(b"logo")
        html_path = html_root / "preview.html"
        html_path.write_text(
            "<html><body><div style='width:820px; min-height:1800px; background:white;'>"
            "<p>{{manual.license_date}}</p></div></body></html>",
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
        self.panel.refresh_current_html_preview()
        pump_events(app=self.app, cycles=5)
        view = self.panel.fill_html_preview_view
        self.assertIsNotNone(view)
        wait_for(
            lambda: bool(view.url().toLocalFile()),
            timeout_ms=5000,
            app=self.app,
            description="live HTML preview URL to load",
        )
        wait_for(
            lambda: not view._fit_measure_timer.isActive(),
            timeout_ms=5000,
            app=self.app,
            description="live HTML preview fit zoom to settle",
        )
        return view

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

    def test_import_and_symbol_default_layouts_keep_contents_recoverable(self):
        self._focus_import()
        import_host = self.panel._tab_hosts["import"]
        self.assertTrue(import_host.validate_layout_integrity_after_restore())
        self.assertTrue(import_host._visible_scroll_area_contents_ready())

        self._focus_symbols()
        symbols_host = self.panel._tab_hosts["symbols"]
        self.assertTrue(symbols_host.validate_layout_integrity_after_restore())
        self.assertTrue(symbols_host._visible_scroll_area_contents_ready())

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
        wait_for(
            lambda: preview_path.exists(),
            timeout_ms=5000,
            app=self.app,
            description="HTML preview artifact path to exist",
        )
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

    def test_fill_workspace_uses_two_column_docks_and_preview_stays_docked_when_unlocked(self):
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
        self.assertFalse(
            bool(preview_dock.features() & QDockWidget.DockWidgetFeature.DockWidgetFloatable),
        )
        self.assertTrue(
            bool(revision_dock.features() & QDockWidget.DockWidgetFeature.DockWidgetFloatable),
        )
        host.float_dock(preview_dock)
        pump_events(app=self.app, cycles=2)
        self.assertFalse(preview_dock.isFloating())
        host.float_dock(revision_dock)
        pump_events(app=self.app, cycles=2)
        self.assertTrue(revision_dock.isFloating())
        revision_dock.setFloating(False)
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
        for dock in (revision_dock, draft_dock):
            self.assertTrue(
                bool(dock.features() & QDockWidget.DockWidgetClosable),
                msg=f"{dock.objectName()} should remain recoverable while locked",
            )
            self.assertFalse(bool(dock.features() & QDockWidget.DockWidgetMovable))
            self.assertFalse(bool(dock.features() & QDockWidget.DockWidgetFloatable))
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

    def test_fill_workspace_disables_geometry_simulated_stack_reordering(self):
        self._focus_fill()
        host = self.panel._tab_hosts["fill"]
        docks = {dock.objectName(): dock for dock in host._docks}
        draft_dock = docks["contractTemplateFillDraftWorkspaceDock"]
        export_dock = docks["contractTemplateFillResolvedExportDock"]

        host.set_locked(False)
        pump_events(app=self.app, cycles=2)

        self.assertFalse(host.can_move_dock_in_stack(export_dock, -1))
        self.assertGreater(export_dock.geometry().y(), draft_dock.geometry().y())
        before_geometry = export_dock.geometry()
        host.move_dock_in_stack(export_dock, -1)
        pump_events(app=self.app, cycles=3)
        self.assertEqual(export_dock.geometry(), before_geometry)

    def test_reset_layout_restores_default_fill_layout_and_persists_reset_state(self):
        self._focus_fill()
        host = self.panel._tab_hosts["fill"]
        revision_dock = next(
            dock for dock in host._docks if dock.objectName() == "contractTemplateFillRevisionDock"
        )

        host.set_locked(False)
        revision_dock.setFloating(True)
        pump_events(app=self.app, cycles=2)
        self.assertTrue(revision_dock.isFloating())

        host.reset_to_default_layout()
        pump_events(app=self.app, cycles=3)
        self.assertTrue(host._locked)
        self.assertFalse(revision_dock.isFloating())

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
            restored_revision_dock = next(
                dock
                for dock in restored_host._docks
                if dock.objectName() == "contractTemplateFillRevisionDock"
            )
            self.assertFalse(restored_revision_dock.isFloating())
            self.assertTrue(restored_host._locked)
        finally:
            restored_panel.close()
            restored_panel.deleteLater()
            pump_events(app=self.app, cycles=2)

    def test_restore_layout_state_ignores_outdated_fill_dock_topology(self):
        self._focus_fill()
        host = self.panel._tab_hosts["fill"]
        revision_dock = next(
            dock for dock in host._docks if dock.objectName() == "contractTemplateFillRevisionDock"
        )

        host.set_locked(False)
        revision_dock.setFloating(True)
        pump_events(app=self.app, cycles=3)
        self.assertTrue(revision_dock.isFloating())

        saved_state = self.panel.capture_layout_state()
        fill_state = dict(saved_state["tabs"]["fill"])
        fill_state["layout_version"] = 2
        fill_state.pop("dock_object_names", None)
        saved_state["tabs"]["fill"] = fill_state

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
            restored_panel.restore_layout_state(saved_state)
            restored_panel.focus_tab("fill")
            pump_events(app=self.app, cycles=5)

            restored_host = restored_panel._tab_hosts["fill"]
            restored_revision_dock = next(
                dock
                for dock in restored_host._docks
                if dock.objectName() == "contractTemplateFillRevisionDock"
            )
            self.assertFalse(restored_revision_dock.isFloating())
            self.assertTrue(all(dock.isVisible() for dock in restored_host._docks))
        finally:
            restored_panel.close()
            restored_panel.deleteLater()
            pump_events(app=self.app, cycles=2)

    def test_current_fill_layout_round_trip_keeps_controls_visible(self):
        self._focus_fill()
        saved_state = self.panel.capture_layout_state()

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
            restored_panel.restore_layout_state(saved_state)
            restored_panel.focus_tab("fill")
            pump_events(app=self.app, cycles=6)

            restored_host = restored_panel._tab_hosts["fill"]
            self.assertFalse(restored_host._has_exposed_central_canvas())
            self.assertTrue(all(dock.isVisible() for dock in restored_host._docks))
        finally:
            restored_panel.close()
            restored_panel.deleteLater()
            pump_events(app=self.app, cycles=2)

    def test_capture_layout_state_preserves_pending_hidden_host_state_until_tab_activation(self):
        self._focus_fill()
        self.panel.focus_tab("import")
        pump_events(app=self.app, cycles=6)
        saved_state = self.panel.capture_layout_state()

        restored_panel = ContractTemplateWorkspacePanel(**self._panel_constructor_kwargs())
        try:
            restored_panel.show()
            pump_events(app=self.app, cycles=2)
            restored_panel.restore_layout_state(saved_state)
            pump_events(app=self.app, cycles=6)

            fill_host = restored_panel._tab_hosts["fill"]
            self.assertFalse(fill_host.isVisible())
            self.assertIsNotNone(fill_host._pending_state)
            pending_before = dict(fill_host._pending_state or {})

            saved_again = restored_panel.capture_layout_state()
            pending_after = dict(fill_host._pending_state or {})

            self.assertIn("fill", saved_again["tabs"])
            self.assertEqual(saved_again["tabs"]["fill"], pending_before)
            self.assertEqual(pending_after, pending_before)
        finally:
            restored_panel.close()
            restored_panel.deleteLater()
            pump_events(app=self.app, cycles=2)

    def test_capture_layout_state_reuses_stable_snapshot_for_hidden_materialized_host(self):
        self._focus_fill()
        fill_host = self.panel._tab_hosts["fill"]
        stable_state = fill_host.capture_layout_state()

        self.panel.focus_tab("import")
        pump_events(app=self.app, cycles=6)
        self.assertFalse(fill_host.isVisible())

        with mock.patch.object(
            fill_host.main_window,
            "saveState",
            side_effect=AssertionError("hidden host should not be serialized live"),
        ):
            saved_state = self.panel.capture_layout_state()

        self.assertEqual(saved_state["tabs"]["fill"], stable_state)

    def test_restore_layout_state_materializes_import_and_fill_hosts_before_applying_state(self):
        self._focus_fill()
        saved_state = self.panel.capture_layout_state()

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
            restored_panel.restore_layout_state(saved_state)
            pump_events(app=self.app, cycles=6)

            self.assertIn("import", restored_panel._tab_hosts)
            self.assertIn("fill", restored_panel._tab_hosts)
            restored_panel.focus_tab("import")
            pump_events(app=self.app, cycles=3)
            import_host = restored_panel._tab_hosts["import"]
            self.assertTrue(all(dock.isVisible() for dock in import_host._docks))
            fill_host = restored_panel._tab_hosts["fill"]
            restored_panel.focus_tab("fill")
            pump_events(app=self.app, cycles=3)
            self.assertTrue(all(dock.isVisible() for dock in fill_host._docks))
            self.assertTrue(import_host.validate_layout_integrity_after_restore())
            self.assertTrue(import_host._visible_scroll_area_contents_ready())
            self.assertFalse(fill_host._has_exposed_central_canvas())
        finally:
            restored_panel.close()
            restored_panel.deleteLater()
            pump_events(app=self.app, cycles=2)

    def test_restore_layout_state_applies_each_nested_host_state_once(self):
        self._focus_fill()
        saved_state = self.panel.capture_layout_state()

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
        original_restore = _DockableWorkspaceTab.restore_layout_state
        restored_keys: list[str] = []

        def _record_restore(tab, state):
            restored_keys.append(tab.tab_key)
            return original_restore(tab, state)

        try:
            restored_panel.show()
            pump_events(app=self.app, cycles=2)
            with mock.patch.object(
                _DockableWorkspaceTab,
                "restore_layout_state",
                autospec=True,
                side_effect=_record_restore,
            ):
                restored_panel.restore_layout_state(saved_state)
            pump_events(app=self.app, cycles=4)

            self.assertEqual(restored_keys.count("import"), 1)
            self.assertEqual(restored_keys.count("fill"), 1)
            self.assertEqual(restored_keys.count("symbols"), 0)
        finally:
            restored_panel.close()
            restored_panel.deleteLater()
            pump_events(app=self.app, cycles=2)

    def test_outer_restore_visibility_churn_does_not_notify_or_mutate_fill_stable_state(self):
        host = self._fill_host()
        stable_before = dict(host.capture_layout_state())
        host._stable_layout_state = dict(stable_before)
        notify_calls: list[str] = []
        host._layout_changed_handler = lambda: notify_calls.append("called")
        dock = self._fill_dock("contractTemplateFillRevisionDock")
        setattr(self.panel, "_is_restoring_workspace_layout", True)
        try:
            dock.hide()
            pump_events(app=self.app, cycles=2)

            self.assertEqual(notify_calls, [])
            self.assertEqual(host._stable_layout_state, stable_before)
        finally:
            setattr(self.panel, "_is_restoring_workspace_layout", False)
            dock.show()
            pump_events(app=self.app, cycles=2)

    def test_restore_layout_state_preserves_hidden_fill_dock_for_inactive_tab(self):
        host = self._fill_host()
        preview_dock = self._fill_dock("contractTemplateHtmlPreviewDock")

        host.set_locked(False)
        pump_events(app=self.app, cycles=2)
        preview_dock.hide()
        pump_events(app=self.app, cycles=3)
        self.panel.focus_tab("import")
        pump_events(app=self.app, cycles=3)

        saved_state = self.panel.capture_layout_state()
        self.assertIn("dock_visibility", saved_state["tabs"]["fill"])
        self.assertFalse(
            saved_state["tabs"]["fill"]["dock_visibility"]["contractTemplateHtmlPreviewDock"]
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
        restored_panel = ContractTemplateWorkspacePanel(**accepted_kwargs)
        try:
            restored_panel.show()
            pump_events(app=self.app, cycles=2)
            restored_panel.restore_layout_state(saved_state)
            pump_events(app=self.app, cycles=4)

            restored_panel.focus_tab("fill")
            pump_events(app=self.app, cycles=4)
            restored_host = restored_panel._tab_hosts["fill"]
            restored_preview_dock = next(
                dock
                for dock in restored_host._docks
                if dock.objectName() == "contractTemplateHtmlPreviewDock"
            )
            self.assertFalse(restored_preview_dock.isVisible())
        finally:
            restored_panel.close()
            restored_panel.deleteLater()
            pump_events(app=self.app, cycles=2)

    def test_restore_layout_state_defers_hidden_import_restore_until_tab_activation_and_keeps_docks_reopenable(
        self,
    ):
        self._focus_import()
        import_host = self.panel._tab_hosts["import"]
        snapshots_dock = next(
            dock
            for dock in import_host._docks
            if dock.objectName() == "contractTemplateSnapshotsArtifactsDock"
        )

        import_host.set_locked(False)
        pump_events(app=self.app, cycles=2)
        snapshots_dock.hide()
        pump_events(app=self.app, cycles=3)
        import_host.set_locked(True)
        pump_events(app=self.app, cycles=2)
        self.panel.focus_tab("fill")
        pump_events(app=self.app, cycles=3)

        saved_state = self.panel.capture_layout_state()
        restored_panel = ContractTemplateWorkspacePanel(**self._panel_constructor_kwargs())
        try:
            restored_panel.show()
            pump_events(app=self.app, cycles=2)
            restored_panel.restore_layout_state(saved_state)
            pump_events(app=self.app, cycles=4)

            restored_import_host = restored_panel._tab_hosts["import"]

            restored_panel.focus_tab("import")
            pump_events(app=self.app, cycles=6)

            restored_snapshots_dock = next(
                dock
                for dock in restored_import_host._docks
                if dock.objectName() == "contractTemplateSnapshotsArtifactsDock"
            )
            panels_action = restored_import_host.panels_action_for_dock(restored_snapshots_dock)

            self.assertFalse(restored_snapshots_dock.isVisible())
            self.assertIsNotNone(panels_action)
            self.assertTrue(panels_action.isEnabled())
            self.assertTrue(restored_import_host.validate_layout_integrity_after_restore())

            visible_scroll_contents = []
            for dock in restored_import_host._docks:
                if not dock.isVisible():
                    continue
                scroll = dock.widget()
                if isinstance(scroll, QScrollArea) and scroll.widget() is not None:
                    visible_scroll_contents.append(scroll.widget())
            self.assertTrue(visible_scroll_contents)
            self.assertTrue(all(widget.isVisible() for widget in visible_scroll_contents))
            self.assertTrue(
                all(
                    widget.width() > 8 and widget.height() > 8 for widget in visible_scroll_contents
                )
            )

            panels_action.trigger()
            pump_events(app=self.app, cycles=3)
            self.assertTrue(restored_snapshots_dock.isVisible())
        finally:
            restored_panel.close()
            restored_panel.deleteLater()
            pump_events(app=self.app, cycles=2)

    def test_fill_panels_actions_track_current_dock_instances_after_restore(self):
        host = self._fill_host()
        host.set_locked(False)
        pump_events(app=self.app, cycles=2)
        self._fill_dock("contractTemplateHtmlPreviewDock").hide()
        pump_events(app=self.app, cycles=2)
        host.set_locked(True)
        pump_events(app=self.app, cycles=2)
        saved_state = self.panel.capture_layout_state()

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
            restored_panel.restore_layout_state(saved_state)
            restored_panel.focus_tab("fill")
            pump_events(app=self.app, cycles=4)

            restored_host = restored_panel._tab_hosts["fill"]
            menu_actions = set(restored_host.panels_menu.actions())
            for dock in restored_host._docks:
                action = restored_host.panels_action_for_dock(dock)
                self.assertIsNotNone(action)
                self.assertIn(action, menu_actions)
                self.assertEqual(action.text(), dock.windowTitle())
                self.assertIs(action.parent(), dock)
        finally:
            restored_panel.close()
            restored_panel.deleteLater()
            pump_events(app=self.app, cycles=2)

    def test_fill_panels_action_can_reopen_hidden_dock_after_restore_when_locked(self):
        host = self._fill_host()
        preview_dock = self._fill_dock("contractTemplateHtmlPreviewDock")
        host.set_locked(False)
        pump_events(app=self.app, cycles=2)
        preview_dock.hide()
        pump_events(app=self.app, cycles=2)
        host.set_locked(True)
        pump_events(app=self.app, cycles=2)
        saved_state = self.panel.capture_layout_state()

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
            restored_panel.restore_layout_state(saved_state)
            restored_panel.focus_tab("fill")
            pump_events(app=self.app, cycles=4)

            restored_host = restored_panel._tab_hosts["fill"]
            restored_preview_dock = next(
                dock
                for dock in restored_host._docks
                if dock.objectName() == "contractTemplateHtmlPreviewDock"
            )
            panels_action = restored_host.panels_action_for_dock(restored_preview_dock)
            self.assertIsNotNone(panels_action)
            self.assertTrue(restored_host._locked)
            self.assertFalse(restored_preview_dock.isVisible())
            self.assertTrue(panels_action.isEnabled())

            panels_action.trigger()
            pump_events(app=self.app, cycles=4)

            self.assertTrue(restored_preview_dock.isVisible())
            self.assertTrue(panels_action.isChecked())
        finally:
            restored_panel.close()
            restored_panel.deleteLater()
            pump_events(app=self.app, cycles=2)

    def test_fill_panels_action_can_reopen_one_dock_after_all_fill_docks_are_hidden(self):
        host = self._fill_host()
        host.set_locked(False)
        pump_events(app=self.app, cycles=2)
        for dock in host._docks:
            dock.hide()
        pump_events(app=self.app, cycles=3)
        host.set_locked(True)
        pump_events(app=self.app, cycles=2)
        saved_state = self.panel.capture_layout_state()

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
            restored_panel.restore_layout_state(saved_state)
            restored_panel.focus_tab("fill")
            pump_events(app=self.app, cycles=4)

            restored_host = restored_panel._tab_hosts["fill"]
            self.assertFalse(any(dock.isVisible() for dock in restored_host._docks))

            revision_dock = next(
                dock
                for dock in restored_host._docks
                if dock.objectName() == "contractTemplateFillRevisionDock"
            )
            panels_action = restored_host.panels_action_for_dock(revision_dock)
            self.assertIsNotNone(panels_action)

            panels_action.trigger()
            pump_events(app=self.app, cycles=4)

            self.assertTrue(revision_dock.isVisible())
            self.assertTrue(panels_action.isChecked())
        finally:
            restored_panel.close()
            restored_panel.deleteLater()
            pump_events(app=self.app, cycles=2)

    def test_outer_workspace_restore_keeps_hidden_fill_dock_recoverable_when_panel_materializes(
        self,
    ):
        window = self._OuterWorkspaceWindow()
        window.resize(1600, 1100)
        source_dock = self._make_outer_workspace_dock(window, "contractTemplateOuterSourceDock")
        restored_dock = self._make_outer_workspace_dock(window, "contractTemplateOuterRestoreDock")
        try:
            window.addDockWidget(Qt.RightDockWidgetArea, source_dock)
            window.addDockWidget(Qt.RightDockWidgetArea, restored_dock)
            window.show()
            source_dock.show()
            pump_events(app=self.app, cycles=4)

            source_panel = source_dock.panel()
            pump_events(app=self.app, cycles=6)
            source_panel.focus_tab("fill")
            pump_events(app=self.app, cycles=6)
            source_host = source_panel._tab_hosts["fill"]
            source_preview_dock = next(
                dock
                for dock in source_host._docks
                if dock.objectName() == "contractTemplateHtmlPreviewDock"
            )
            source_host.set_locked(False)
            pump_events(app=self.app, cycles=2)
            source_preview_dock.hide()
            pump_events(app=self.app, cycles=3)
            source_host.set_locked(True)
            pump_events(app=self.app, cycles=2)
            saved_state = source_dock.capture_panel_layout_state()

            restored_dock.show()
            pump_events(app=self.app, cycles=4)
            restored_dock.restore_panel_layout_state(saved_state)
            restored_panel = restored_dock.panel()
            pump_events(app=self.app, cycles=8)
            restored_panel.focus_tab("fill")
            pump_events(app=self.app, cycles=6)

            restored_host = restored_panel._tab_hosts["fill"]
            restored_preview_dock = next(
                dock
                for dock in restored_host._docks
                if dock.objectName() == "contractTemplateHtmlPreviewDock"
            )
            panels_action = restored_host.panels_action_for_dock(restored_preview_dock)

            self.assertFalse(restored_dock._pending_panel_layout_state_dirty)
            self.assertTrue(restored_host._locked)
            self.assertFalse(restored_preview_dock.isVisible())
            self.assertIsNotNone(panels_action)
            self.assertTrue(panels_action.isEnabled())

            panels_action.trigger()
            pump_events(app=self.app, cycles=4)

            self.assertTrue(restored_preview_dock.isVisible())
            self.assertEqual(
                restored_host.dockWidgetArea(restored_preview_dock),
                Qt.LeftDockWidgetArea,
            )
        finally:
            restored_dock.close()
            restored_dock.deleteLater()
            source_dock.close()
            source_dock.deleteLater()
            window.close()
            window.deleteLater()
            pump_events(app=self.app, cycles=4)

    def test_outer_workspace_sparse_saved_state_materializes_default_fill_layout_without_orphans(
        self,
    ):
        window = self._OuterWorkspaceWindow()
        window.resize(1600, 1100)
        source_dock = self._make_outer_workspace_dock(
            window, "contractTemplateOuterSparseSourceDock"
        )
        restored_dock = self._make_outer_workspace_dock(
            window, "contractTemplateOuterSparseRestoreDock"
        )
        try:
            window.addDockWidget(Qt.RightDockWidgetArea, source_dock)
            window.addDockWidget(Qt.RightDockWidgetArea, restored_dock)
            window.show()
            source_dock.show()
            pump_events(app=self.app, cycles=4)

            source_dock.panel()
            pump_events(app=self.app, cycles=4)
            saved_state = source_dock.capture_panel_layout_state()
            self.assertNotIn("fill", saved_state["tabs"])

            restored_dock.show()
            pump_events(app=self.app, cycles=4)
            restored_dock.restore_panel_layout_state(saved_state)
            restored_panel = restored_dock.panel()
            pump_events(app=self.app, cycles=8)
            restored_panel.focus_tab("fill")
            pump_events(app=self.app, cycles=6)

            restored_host = restored_panel._tab_hosts["fill"]
            menu_actions = set(restored_host.panels_menu.actions())
            for dock in restored_host._docks:
                self.assertFalse(
                    not dock.isFloating()
                    and restored_host.dockWidgetArea(dock) == Qt.NoDockWidgetArea
                )
                action = restored_host.panels_action_for_dock(dock)
                self.assertIsNotNone(action)
                self.assertIn(action, menu_actions)
        finally:
            restored_dock.close()
            restored_dock.deleteLater()
            source_dock.close()
            source_dock.deleteLater()
            window.close()
            window.deleteLater()
            pump_events(app=self.app, cycles=4)

    def test_outer_hidden_workspace_resave_preserves_pending_nested_fill_state(self):
        window = self._OuterWorkspaceWindow()
        window.resize(1600, 1100)
        source_dock = self._make_outer_workspace_dock(
            window, "contractTemplateOuterHiddenSourceDock"
        )
        restored_dock = self._make_outer_workspace_dock(
            window, "contractTemplateOuterHiddenRestoreDock"
        )
        try:
            window.addDockWidget(Qt.RightDockWidgetArea, source_dock)
            window.addDockWidget(Qt.RightDockWidgetArea, restored_dock)
            window.show()
            source_dock.show()
            restored_dock.hide()
            pump_events(app=self.app, cycles=4)

            source_panel = source_dock.panel()
            pump_events(app=self.app, cycles=6)
            source_panel.focus_tab("fill")
            pump_events(app=self.app, cycles=6)
            source_state = source_dock.capture_panel_layout_state()

            restored_dock.restore_panel_layout_state(source_state)
            pump_events(app=self.app, cycles=4)
            resaved_state = restored_dock.capture_panel_layout_state()
            self.assertEqual(resaved_state, source_state)

            restored_dock.restore_panel_layout_state(resaved_state)
            restored_dock.show()
            pump_events(app=self.app, cycles=6)

            restored_panel = restored_dock.panel()
            pump_events(app=self.app, cycles=8)
            restored_panel.focus_tab("fill")
            pump_events(app=self.app, cycles=6)

            restored_host = restored_panel._tab_hosts["fill"]
            self.assertFalse(restored_dock._pending_panel_layout_state_dirty)
            self.assertTrue(restored_host.validate_layout_integrity_after_restore())
            self.assertEqual(len([dock for dock in restored_host._docks if dock.isVisible()]), 8)
        finally:
            restored_dock.close()
            restored_dock.deleteLater()
            source_dock.close()
            source_dock.deleteLater()
            window.close()
            window.deleteLater()
            pump_events(app=self.app, cycles=4)

    def test_finish_layout_restore_resumes_html_preview_refresh_after_suspension(self):
        if QWebEnginePage is None:
            self.skipTest("Qt WebEngine is unavailable")
        self._load_live_fill_html_preview()
        controller = self.panel._fill_preview_controller
        self.assertIsNotNone(controller)

        request_flags: list[bool] = []
        original_request_refresh = controller.request_refresh

        def _record_request(*args, **kwargs):
            request_flags.append(bool(self.panel._suspend_preview_refresh))
            return original_request_refresh(*args, **kwargs)

        with mock.patch.object(
            controller,
            "request_refresh",
            side_effect=_record_request,
        ):
            self.panel.begin_layout_restore()
            self.panel._sync_html_preview_state(self.panel._selected_fill_revision_id())
            self.panel.finish_layout_restore()
            pump_events(app=self.app, cycles=4)

        self.assertEqual(request_flags, [False])

    def test_outer_workspace_default_import_and_symbol_layouts_keep_contents_recoverable(self):
        window = self._OuterWorkspaceWindow()
        window.resize(1600, 1100)
        dock = self._make_outer_workspace_dock(window, "contractTemplateOuterGeometryDock")
        try:
            window.addDockWidget(Qt.RightDockWidgetArea, dock)
            window.show()
            dock.show()
            pump_events(app=self.app, cycles=4)

            panel = dock.panel()
            pump_events(app=self.app, cycles=8)

            panel.focus_tab("import")
            pump_events(app=self.app, cycles=6)
            import_host = panel._tab_hosts["import"]
            self.assertTrue(import_host.validate_layout_integrity_after_restore())
            self.assertTrue(import_host._visible_scroll_area_contents_ready())

            panel.focus_tab("symbols")
            pump_events(app=self.app, cycles=6)
            symbols_host = panel._tab_hosts["symbols"]
            self.assertTrue(symbols_host.validate_layout_integrity_after_restore())
            self.assertTrue(symbols_host._visible_scroll_area_contents_ready())
        finally:
            dock.close()
            dock.deleteLater()
            window.close()
            window.deleteLater()
            pump_events(app=self.app, cycles=4)

    def test_validate_layout_integrity_after_restore_repairs_hidden_visible_scroll_content(self):
        host = self._fill_host()
        revision_dock = self._fill_dock("contractTemplateFillRevisionDock")
        scroll = revision_dock.widget()
        self.assertIsInstance(scroll, QScrollArea)
        content = scroll.widget()
        self.assertIsNotNone(content)
        content.hide()
        pump_events(app=self.app, cycles=2)

        self.assertFalse(content.isVisible())
        self.assertTrue(host.validate_layout_integrity_after_restore())
        pump_events(app=self.app, cycles=2)

        self.assertTrue(content.isVisible())
        self.assertGreater(content.width(), 8)
        self.assertGreater(content.height(), 8)

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
        self.assertLessEqual(export_dock.geometry().y(), revision_dock.geometry().bottom() + 16)

    def test_fill_workspace_has_no_visible_dock_overlaps_after_unlock_hide_show_move_and_restore(
        self,
    ):
        host = self._fill_host()
        draft_dock = self._fill_dock("contractTemplateFillDraftWorkspaceDock")
        panels_action = host.panels_action_for_dock(draft_dock)

        host.set_locked(False)
        pump_events(app=self.app, cycles=2)
        draft_dock.hide()
        pump_events(app=self.app, cycles=3)
        panels_action.trigger()
        pump_events(app=self.app, cycles=3)
        saved_state = self.panel.capture_layout_state()

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
            restored_panel.restore_layout_state(saved_state)
            restored_panel.focus_tab("fill")
            pump_events(app=self.app, cycles=6)
            restored_host = restored_panel._tab_hosts["fill"]
            self._assert_no_visible_dock_overlap(restored_host)
        finally:
            restored_panel.close()
            restored_panel.deleteLater()
            pump_events(app=self.app, cycles=2)

    def test_html_preview_fit_zoom_stays_stable_across_reloads_and_reset(self):
        if QWebEnginePage is None:
            self.skipTest("Qt WebEngine is unavailable")
        view = _InteractiveHtmlPreviewView()
        try:
            view.resize(760, 920)
            view.show()
            html = """
                <html>
                    <body style="margin:0; padding:24px; background:#d7d7d7;">
                        <div style="width:820px; min-height:1400px; margin:0 auto; background:white;"></div>
                    </body>
                </html>
            """
            fit_percent = None
            for _ in range(3):
                view.setHtml(html, QUrl("about:blank"))
                wait_for(
                    lambda: view.current_zoom_percent() < 100
                    and not view._fit_measure_timer.isActive(),
                    timeout_ms=5000,
                    app=self.app,
                    description="preview fit zoom to settle",
                )
                if fit_percent is None:
                    fit_percent = view.current_zoom_percent()
                self.assertIsNotNone(fit_percent)
                self.assertAlmostEqual(view.current_zoom_percent(), fit_percent, delta=1)
            view.set_zoom_percent(int(fit_percent) + 25, user_initiated=True)
            pump_events(app=self.app, cycles=2)
            self.assertGreater(view.current_zoom_percent(), int(fit_percent))
            view.reset_to_fit()
            wait_for(
                lambda: abs(view.current_zoom_percent() - int(fit_percent)) <= 1,
                timeout_ms=5000,
                app=self.app,
                description="preview reset-to-fit to restore stable fit zoom",
            )
            self.assertAlmostEqual(view.current_zoom_percent(), int(fit_percent), delta=1)
        finally:
            view.close()
            view.deleteLater()
            pump_events(app=self.app, cycles=2)

    def test_fit_view_repeats_stably_after_manual_zoom_reset(self):
        if QWebEnginePage is None:
            self.skipTest("Qt WebEngine is unavailable")
        view = self._load_live_fill_html_preview()

        view.set_zoom_percent(100, user_initiated=True)
        pump_events(app=self.app, cycles=2)
        self.assertEqual(view.current_zoom_percent(), 100)

        view.reset_to_fit()
        wait_for(
            lambda: not view._fit_measure_timer.isActive(),
            timeout_ms=5000,
            app=self.app,
            description="fit view to settle after manual zoom reset",
        )
        view.reset_to_fit()
        wait_for(
            lambda: not view._fit_measure_timer.isActive(),
            timeout_ms=5000,
            app=self.app,
            description="second fit view to settle after manual zoom reset",
        )

        first_fit = view.current_zoom_percent()
        self.assertLessEqual(first_fit, 100)
        for _ in range(4):
            view.reset_to_fit()
            wait_for(
                lambda: not view._fit_measure_timer.isActive(),
                timeout_ms=5000,
                app=self.app,
                description="repeated fit view to settle",
            )
            self.assertAlmostEqual(view.current_zoom_percent(), first_fit, delta=1)

    def test_fit_mode_resize_uses_cached_document_width_without_remeasuring(self):
        if QWebEngineView is None:
            self.skipTest("Qt WebEngine is unavailable")
        view = _InteractiveHtmlPreviewView()
        try:
            view.resize(760, 920)
            view._set_zoom_owner("fit")
            view._document_css_width = 820.0

            apply_calls: list[bool] = []
            schedule_calls: list[int] = []
            original_apply = view._apply_fit_if_needed

            def _record_apply(*, force: bool = False):
                apply_calls.append(bool(force))
                return original_apply(force=force)

            with (
                mock.patch.object(view, "_apply_fit_if_needed", side_effect=_record_apply),
                mock.patch.object(
                    view,
                    "_schedule_fit",
                    side_effect=lambda *, delay_ms=90: schedule_calls.append(int(delay_ms)),
                ),
            ):
                view.resizeEvent(
                    QResizeEvent(
                        QSize(700, 920),
                        QSize(760, 920),
                    )
                )

            self.assertEqual(schedule_calls, [])
            self.assertTrue(apply_calls or view.current_zoom_percent() > 0)
            self.assertGreater(view._document_css_width, 0)
        finally:
            view.close()
            view.deleteLater()
            pump_events(app=self.app, cycles=2)

    def test_fit_measure_cache_does_not_shrink_after_smaller_followup_measurement(self):
        if QWebEngineView is None:
            self.skipTest("Qt WebEngine is unavailable")
        view = _InteractiveHtmlPreviewView()
        try:
            view._set_zoom_owner("fit")
            view._document_css_width = 820.0

            with mock.patch.object(
                view.page(),
                "runJavaScript",
                side_effect=lambda _script, callback: callback(640.0),
            ):
                view._measure_and_apply_fit()

            self.assertEqual(view._document_css_width, 820.0)
        finally:
            view.close()
            view.deleteLater()
            pump_events(app=self.app, cycles=2)

    def test_stale_fit_callback_is_ignored_after_fit_request_is_closed(self):
        if QWebEngineView is None:
            self.skipTest("Qt WebEngine is unavailable")
        view = _InteractiveHtmlPreviewView()
        try:
            view.resize(760, 920)
            view.show()
            pump_events(app=self.app, cycles=2)
            view._set_zoom_owner("fit")
            callback_box: dict[str, object] = {}

            with mock.patch.object(
                view.page(),
                "runJavaScript",
                side_effect=lambda _script, callback: callback_box.setdefault("callback", callback),
            ):
                view._schedule_fit(delay_ms=0)
                view._measure_and_apply_fit()

            self.assertIn("callback", callback_box)
            view._finish_fit_transition()
            frozen_zoom = view.current_zoom_percent()
            callback_box["callback"](820.0)
            pump_events(app=self.app, cycles=2)

            self.assertEqual(view.current_zoom_percent(), frozen_zoom)
            self.assertEqual(view._zoom_owner, "viewport")
            self.assertIsNone(view._pending_fit_request_serial)
        finally:
            view.close()
            view.deleteLater()
            pump_events(app=self.app, cycles=2)

    def test_fill_preview_dock_remains_non_floatable_with_live_html_loaded(self):
        if QWebEnginePage is None:
            self.skipTest("Qt WebEngine is unavailable")
        host = self._fill_host()
        preview_dock = self._fill_dock("contractTemplateHtmlPreviewDock")
        view = self.panel.fill_html_preview_view
        if view is None:
            self.skipTest("Qt WebEngine preview is unavailable")

        view.setHtml(
            """
                <html>
                    <body style="margin:0; padding:24px;">
                        <div style="width:720px; min-height:800px; background:white;"></div>
                    </body>
                </html>
            """,
            QUrl("about:blank"),
        )
        wait_for(
            lambda: not view._fit_measure_timer.isActive(),
            timeout_ms=5000,
            app=self.app,
            description="preview load to settle before floatability check",
        )

        host.set_locked(False)
        pump_events(app=self.app, cycles=3)

        self.assertFalse(
            bool(preview_dock.features() & QDockWidget.DockWidgetFeature.DockWidgetFloatable)
        )
        host.float_dock(preview_dock)
        pump_events(app=self.app, cycles=3)
        self.assertFalse(preview_dock.isFloating())

    def test_plain_wheel_without_modifier_does_not_enter_zoom_path(self):
        if QWebEngineView is None:
            self.skipTest("Qt WebEngine is unavailable")
        self._focus_fill()
        view = self.panel.fill_html_preview_view
        if view is None:
            self.skipTest("Qt WebEngine preview is unavailable")

        view.setZoomFactor(1.0)
        wheel_event = _FakeWheelEvent(angle_delta_y=-120)
        with mock.patch.object(
            QWebEngineView,
            "wheelEvent",
            autospec=True,
            side_effect=lambda widget, _event: QWebEngineView.setZoomFactor(widget, 0.8),
        ):
            view.wheelEvent(wheel_event)
        self.assertEqual(view.current_zoom_percent(), 100)
        self.assertEqual(view._zoom_owner, "viewport")

    def test_plain_wheel_freezes_fit_mode_against_later_resize_drift(self):
        if QWebEngineView is None:
            self.skipTest("Qt WebEngine is unavailable")
        view = _InteractiveHtmlPreviewView()
        try:
            view.resize(760, 920)
            view.setZoomFactor(0.88)
            view._document_css_width = 820.0
            view._fit_measure_timer.start(500)
            with mock.patch.object(
                QWebEngineView,
                "wheelEvent",
                autospec=True,
                side_effect=lambda *_args, **_kwargs: None,
            ):
                view.wheelEvent(_FakeWheelEvent(angle_delta_y=-120))
            pump_events(app=self.app, cycles=2)

            frozen_zoom = view.current_zoom_percent()
            self.assertEqual(view._zoom_owner, "viewport")
            self.assertFalse(view._fit_measure_timer.isActive())

            view.resize(700, 920)
            pump_events(app=self.app, cycles=3)

            self.assertFalse(view._fit_measure_timer.isActive())
            self.assertEqual(view.current_zoom_percent(), frozen_zoom)
        finally:
            view.close()
            view.deleteLater()
            pump_events(app=self.app, cycles=2)

    def test_programmatic_reload_does_not_reenter_fit_after_plain_wheel_navigation(self):
        if QWebEngineView is None:
            self.skipTest("Qt WebEngine is unavailable")
        view = _InteractiveHtmlPreviewView()
        try:
            view.resize(760, 920)
            view.setZoomFactor(0.92)
            with mock.patch.object(
                QWebEngineView,
                "wheelEvent",
                autospec=True,
                side_effect=lambda *_args, **_kwargs: None,
            ):
                view.wheelEvent(_FakeWheelEvent(angle_delta_y=-120))
            pump_events(app=self.app, cycles=2)

            frozen_zoom = view.current_zoom_percent()
            view.mark_programmatic_reload()
            view._on_load_finished(True)
            pump_events(app=self.app, cycles=2)

            self.assertEqual(view._zoom_owner, "viewport")
            self.assertFalse(view._fit_measure_timer.isActive())
            self.assertEqual(view.current_zoom_percent(), frozen_zoom)
        finally:
            view.close()
            view.deleteLater()
            pump_events(app=self.app, cycles=2)

    def test_reset_to_fit_clears_plain_scroll_navigation_lock(self):
        if QWebEngineView is None:
            self.skipTest("Qt WebEngine is unavailable")
        view = _InteractiveHtmlPreviewView()
        try:
            view.resize(760, 920)
            view.setZoomFactor(0.9)
            view._document_css_width = 820.0
            expected_fit = view._fit_zoom_percent()
            with mock.patch.object(
                QWebEngineView,
                "wheelEvent",
                autospec=True,
                side_effect=lambda *_args, **_kwargs: None,
            ):
                view.wheelEvent(_FakeWheelEvent(angle_delta_y=-120))
            pump_events(app=self.app, cycles=2)
            self.assertEqual(view._zoom_owner, "viewport")

            view.reset_to_fit()
            pump_events(app=self.app, cycles=2)

            self.assertFalse(view._fit_measure_timer.isActive())
            self.assertAlmostEqual(view.current_zoom_percent(), expected_fit, delta=1)
        finally:
            view.close()
            view.deleteLater()
            pump_events(app=self.app, cycles=2)

    def test_ctrl_wheel_is_explicit_zoom_path(self):
        if QWebEngineView is None:
            self.skipTest("Qt WebEngine is unavailable")
        self._focus_fill()
        view = self.panel.fill_html_preview_view
        if view is None:
            self.skipTest("Qt WebEngine preview is unavailable")

        view.setZoomFactor(1.0)
        view.wheelEvent(_FakeWheelEvent(modifiers=Qt.ControlModifier, angle_delta_y=120))
        self.assertGreater(view.current_zoom_percent(), 100)
        self.assertEqual(view._zoom_owner, "manual")

    def test_first_plain_wheel_after_real_html_load_preserves_zoom_across_tab_churn(self):
        if QWebEnginePage is None:
            self.skipTest("Qt WebEngine is unavailable")
        view = self._load_live_fill_html_preview()
        starting_zoom = view.current_zoom_percent()
        starting_generation = self.panel._fill_preview_controller._latest_generation
        with mock.patch.object(
            QWebEngineView,
            "wheelEvent",
            autospec=True,
            side_effect=lambda *_args, **_kwargs: None,
        ):
            view.wheelEvent(_FakeWheelEvent(angle_delta_y=-120))
        pump_events(app=self.app, cycles=2)

        self.assertEqual(view._zoom_owner, "viewport")
        self.assertEqual(view.current_zoom_percent(), starting_zoom)

        self.panel.focus_tab("import")
        pump_events(app=self.app, cycles=3)
        self.panel.focus_tab("fill")
        pump_events(app=self.app, cycles=6)

        self.assertEqual(
            self.panel._fill_preview_controller._latest_generation, starting_generation
        )
        self.assertEqual(view.current_zoom_percent(), starting_zoom)
        self.assertEqual(self.panel.fill_preview_zoom_label.text(), f"{starting_zoom}%")

    def test_manual_preview_zoom_survives_layout_and_visibility_churn_without_reload(self):
        if QWebEnginePage is None:
            self.skipTest("Qt WebEngine is unavailable")
        view = self._load_live_fill_html_preview()
        host = self._fill_host()
        notes_dock = self._fill_dock("contractTemplateFillDraftNotesDock")
        starting_generation = self.panel._fill_preview_controller._latest_generation
        view.set_zoom_percent(view.current_zoom_percent() + 25, user_initiated=True)
        pump_events(app=self.app, cycles=2)
        manual_zoom = view.current_zoom_percent()

        host.set_locked(False)
        pump_events(app=self.app, cycles=2)
        notes_dock.hide()
        pump_events(app=self.app, cycles=3)
        notes_dock.show()
        pump_events(app=self.app, cycles=3)
        host.set_locked(True)
        pump_events(app=self.app, cycles=2)
        self.panel.refresh_fill_form()
        pump_events(app=self.app, cycles=4)

        self.assertEqual(view._zoom_owner, "manual")
        self.assertEqual(
            self.panel._fill_preview_controller._latest_generation, starting_generation
        )
        self.assertEqual(view.current_zoom_percent(), manual_zoom)
        self.assertEqual(self.panel.fill_preview_zoom_label.text(), f"{manual_zoom}%")

    def test_fill_preview_zoom_label_tracks_native_pinch_zoom(self):
        if QWebEnginePage is None:
            self.skipTest("Qt WebEngine is unavailable")
        self._focus_fill()
        view = self.panel.fill_html_preview_view
        if view is None:
            self.skipTest("Qt WebEngine preview is unavailable")

        gesture = _FakeNativeGestureEvent(Qt.ZoomNativeGesture, 0.2)
        handled = view.event(gesture)
        pump_events(app=self.app, cycles=2)

        self.assertTrue(handled)
        self.assertTrue(gesture.accepted)
        self.assertEqual(
            self.panel.fill_preview_zoom_label.text(),
            f"{view.current_zoom_percent()}%",
        )

    def test_small_native_zoom_gesture_noise_does_not_regress_preview_zoom(self):
        if QWebEnginePage is None:
            self.skipTest("Qt WebEngine is unavailable")
        self._focus_fill()
        view = self.panel.fill_html_preview_view
        if view is None:
            self.skipTest("Qt WebEngine preview is unavailable")

        starting_zoom = view.current_zoom_percent()
        for _ in range(6):
            gesture = _FakeNativeGestureEvent(Qt.ZoomNativeGesture, -0.02)
            handled = view.event(gesture)
            pump_events(app=self.app, cycles=1)
            self.assertTrue(handled)
            self.assertTrue(gesture.accepted)

        self.assertEqual(view.current_zoom_percent(), starting_zoom)
        self.assertEqual(self.panel.fill_preview_zoom_label.text(), f"{starting_zoom}%")

    def test_small_native_zoom_noise_after_real_pinch_does_not_drift_zoom(self):
        if QWebEnginePage is None:
            self.skipTest("Qt WebEngine is unavailable")
        self._focus_fill()
        view = self.panel.fill_html_preview_view
        if view is None:
            self.skipTest("Qt WebEngine preview is unavailable")

        starting_zoom = view.current_zoom_percent()
        first_gesture = _FakeNativeGestureEvent(Qt.ZoomNativeGesture, 0.18)
        handled = view.event(first_gesture)
        pump_events(app=self.app, cycles=2)
        self.assertTrue(handled)
        self.assertTrue(first_gesture.accepted)
        zoom_after_pinch = view.current_zoom_percent()
        self.assertGreater(zoom_after_pinch, starting_zoom)

        for _ in range(6):
            gesture = _FakeNativeGestureEvent(Qt.ZoomNativeGesture, -0.02)
            handled = view.event(gesture)
            pump_events(app=self.app, cycles=1)
            self.assertTrue(handled)
            self.assertTrue(gesture.accepted)

        self.assertEqual(view.current_zoom_percent(), zoom_after_pinch)
        self.assertEqual(self.panel.fill_preview_zoom_label.text(), f"{zoom_after_pinch}%")

    def test_fill_preview_zoom_label_reports_true_zoom_above_400_percent(self):
        if QWebEnginePage is None:
            self.skipTest("Qt WebEngine is unavailable")
        self._focus_fill()
        view = self.panel.fill_html_preview_view
        if view is None:
            self.skipTest("Qt WebEngine preview is unavailable")

        with mock.patch.object(view, "zoomFactor", return_value=5.25):
            self.assertEqual(view.current_zoom_percent(), 525)
            view._emit_zoom_percent_changed()
            pump_events(app=self.app, cycles=2)

        self.assertEqual(self.panel.fill_preview_zoom_label.text(), "525%")

import inspect
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from PySide6.QtCore import QDate, QEvent, QPoint, QSize, Qt, QUrl
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDockWidget,
    QDoubleSpinBox,
    QLineEdit,
    QMainWindow,
    QScrollArea,
    QTabBar,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QWidget,
)

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
from isrc_manager.contract_templates.models import (
    ContractTemplateCatalogEntry,
    ContractTemplateFormAutoField,
    ContractTemplateFormChoice,
    ContractTemplateFormManualField,
    ContractTemplateFormSelectorField,
    build_contract_template_indexed_selection_key,
)
from isrc_manager.external_launch import (
    clear_recorded_external_launches,
    get_recorded_external_launches,
)
from isrc_manager.services import (
    ContractTemplateDraftPayload,
    ContractTemplateExportService,
    ContractTemplateOutputArtifactPayload,
    ContractTemplatePayload,
    ContractTemplateResolvedSnapshotPayload,
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


class _FakePointF:
    def __init__(self, point):
        self._point = QPoint(point)

    def toPoint(self):
        return QPoint(self._point)


class _FakeDockDragEvent:
    def __init__(self, point, *, button=Qt.NoButton, buttons=Qt.NoButton):
        self._point = QPoint(point)
        self._button = button
        self._buttons = buttons
        self.accepted = False
        self.ignored = False

    def button(self):
        return self._button

    def buttons(self):
        return self._buttons

    def position(self):
        return _FakePointF(self._point)

    def pos(self):
        return QPoint(self._point)

    def accept(self):
        self.accepted = True

    def ignore(self):
        self.ignored = True


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

    def _select_admin_template(self, template_id: int | None = None):
        self._focus_import()
        self.panel.refresh_admin_workspace(selected_template_id=template_id)
        pump_events(app=self.app, cycles=2)
        if template_id is None:
            self.panel.admin_template_table.selectRow(0)
        else:
            for row in range(self.panel.admin_template_table.rowCount()):
                item = self.panel.admin_template_table.item(row, 0)
                if item is not None and int(item.data(Qt.UserRole)) == int(template_id):
                    self.panel.admin_template_table.selectRow(row)
                    break
        pump_events(app=self.app, cycles=2)
        return self.panel._selected_admin_template_record()

    def _create_admin_draft_bundle(self, *, name: str = "Admin Draft"):
        draft = self.template_service.create_draft(
            ContractTemplateDraftPayload(
                revision_id=self.revision.revision_id,
                name=name,
                editable_payload={
                    "revision_id": self.revision.revision_id,
                    "db_selections": {},
                    "manual_values": {},
                    "type_overrides": {},
                },
                storage_mode="database",
            )
        )
        snapshot = self.template_service.create_resolved_snapshot(
            ContractTemplateResolvedSnapshotPayload(
                draft_id=draft.draft_id,
                revision_id=self.revision.revision_id,
                resolved_values={"{{manual.note}}": name},
                preview_payload={"draft": name},
            )
        )
        artifact_path = self.root / f"{name.lower().replace(' ', '-')}.pdf"
        artifact_path.write_bytes(b"%PDF-1.4\n")
        artifact = self.template_service.create_output_artifact(
            ContractTemplateOutputArtifactPayload(
                snapshot_id=snapshot.snapshot_id,
                artifact_type="pdf",
                output_path=str(artifact_path),
                output_filename=artifact_path.name,
                mime_type="application/pdf",
                size_bytes=artifact_path.stat().st_size,
            )
        )
        self.template_service.set_draft_last_resolved_snapshot(
            draft.draft_id,
            snapshot.snapshot_id,
        )
        self._focus_import()
        self.panel.refresh_admin_workspace(
            selected_template_id=self.revision.template_id,
            selected_revision_id=self.revision.revision_id,
            selected_draft_id=draft.draft_id,
            selected_snapshot_id=snapshot.snapshot_id,
            selected_artifact_id=artifact.artifact_id,
        )
        pump_events(app=self.app, cycles=2)
        return draft, snapshot, artifact

    def test_admin_import_and_revision_workflows_cover_cancel_failure_and_success_paths(self):
        self._focus_import()
        starting_templates = len(self.template_service.list_templates())

        with (
            mock.patch.object(self.panel, "_template_service", return_value=None),
            mock.patch("isrc_manager.contract_templates.dialogs.QMessageBox.warning") as warning,
        ):
            self.panel.import_template_from_file()
        warning.assert_called_once()

        with mock.patch.object(self.panel, "_choose_template_source_path", return_value=None):
            self.panel.import_template_from_file()
        self.assertEqual(len(self.template_service.list_templates()), starting_templates)

        source_path = self.root / "cancelled-import.docx"
        source_path.write_bytes(make_docx_bytes(document_paragraphs=(("Cancelled",),)))
        with (
            mock.patch.object(self.panel, "_choose_template_source_path", return_value=source_path),
            mock.patch(
                "isrc_manager.contract_templates.dialogs.QInputDialog.getText",
                return_value=("Cancelled Import", False),
            ),
        ):
            self.panel.import_template_from_file()
        self.assertEqual(len(self.template_service.list_templates()), starting_templates)

        failing_path = self.root / "failing-import.docx"
        failing_path.write_bytes(make_docx_bytes(document_paragraphs=(("Failing",),)))
        with (
            mock.patch.object(
                self.panel, "_choose_template_source_path", return_value=failing_path
            ),
            mock.patch(
                "isrc_manager.contract_templates.dialogs.QInputDialog.getText",
                return_value=("Failing Import", True),
            ),
            mock.patch.object(
                self.template_service,
                "create_template",
                side_effect=RuntimeError("create failed"),
            ),
            mock.patch("isrc_manager.contract_templates.dialogs.QMessageBox.warning") as warning,
        ):
            self.panel.import_template_from_file()
        warning.assert_called_once()
        self.assertIn("Unable to import template", self.panel.admin_status_label.text())

        import_path = self.root / "imported-admin-template.docx"
        import_path.write_bytes(
            make_docx_bytes(document_paragraphs=(("Imported {{manual.note}}",),))
        )
        with (
            mock.patch.object(self.panel, "_choose_template_source_path", return_value=import_path),
            mock.patch(
                "isrc_manager.contract_templates.dialogs.QInputDialog.getText",
                return_value=("Imported Admin Template", True),
            ),
        ):
            self.panel.import_template_from_file()
        self.assertIn("Imported template", self.panel.admin_status_label.text())
        imported = next(
            template
            for template in self.template_service.list_templates(include_archived=True)
            if template.name == "Imported Admin Template"
        )

        self._select_admin_template(imported.template_id)
        selected_revision_count = len(
            self.template_service.list_revisions(template_id=imported.template_id)
        )
        with mock.patch.object(self.panel, "_choose_template_source_path", return_value=None):
            self.panel.add_revision_from_file()
        self.assertEqual(
            len(self.template_service.list_revisions(template_id=imported.template_id)),
            selected_revision_count,
        )

        revision_path = self.root / "failing-revision.docx"
        revision_path.write_bytes(make_docx_bytes(document_paragraphs=(("Revision",),)))
        with (
            mock.patch.object(
                self.panel, "_choose_template_source_path", return_value=revision_path
            ),
            mock.patch.object(
                self.template_service,
                "import_revision_from_path",
                side_effect=RuntimeError("revision failed"),
            ),
            mock.patch("isrc_manager.contract_templates.dialogs.QMessageBox.warning") as warning,
        ):
            self.panel.add_revision_from_file()
        warning.assert_called_once()
        self.assertIn("Unable to add revision", self.panel.admin_status_label.text())

        revision_path = self.root / "successful-revision.docx"
        revision_path.write_bytes(make_docx_bytes(document_paragraphs=(("Revision",),)))
        with mock.patch.object(
            self.panel, "_choose_template_source_path", return_value=revision_path
        ):
            self.panel.add_revision_from_file()
        self.assertIn("Added revision", self.panel.admin_status_label.text())

        with (
            mock.patch.object(self.panel, "_template_service", return_value=self.template_service),
            mock.patch.object(self.panel, "_selected_admin_template_record", return_value=None),
            mock.patch("isrc_manager.contract_templates.dialogs.QMessageBox.information") as info,
        ):
            self.panel.add_revision_from_file()
        info.assert_called_once()

    def test_admin_template_mutation_actions_cover_confirm_archive_duplicate_and_delete_paths(self):
        selected = self._select_admin_template()
        self.assertIsNotNone(selected)
        assert selected is not None

        with (
            mock.patch.object(
                self.template_service,
                "duplicate_template",
                side_effect=RuntimeError("duplicate failed"),
            ),
            mock.patch("isrc_manager.contract_templates.dialogs.QMessageBox.warning") as warning,
        ):
            self.panel.duplicate_selected_template()
        warning.assert_called_once()
        self.assertIn("Unable to duplicate template", self.panel.admin_status_label.text())

        self.panel.duplicate_selected_template()
        self.assertIn("Duplicated template", self.panel.admin_status_label.text())
        duplicated = next(
            template
            for template in self.template_service.list_templates(include_archived=True)
            if template.name.startswith(f"{selected.name} Copy")
        )

        self._select_admin_template(duplicated.template_id)
        with (
            mock.patch.object(
                self.template_service,
                "archive_template",
                side_effect=RuntimeError("archive failed"),
            ),
            mock.patch("isrc_manager.contract_templates.dialogs.QMessageBox.warning") as warning,
        ):
            self.panel.toggle_selected_template_archive()
        warning.assert_called_once()
        self.assertIn(
            "Unable to update template archive state", self.panel.admin_status_label.text()
        )

        self.panel.toggle_selected_template_archive()
        self.assertIn("Archived template", self.panel.admin_status_label.text())
        self.panel.toggle_selected_template_archive()
        self.assertIn("Restored template", self.panel.admin_status_label.text())

        with (
            mock.patch(
                "isrc_manager.contract_templates.dialogs._confirm_destructive_action",
                return_value=False,
            ) as confirm,
            mock.patch.object(self.template_service, "delete_template") as delete_template,
        ):
            self.panel.delete_selected_template_record()
        confirm.assert_called_once()
        delete_template.assert_not_called()

        with (
            mock.patch(
                "isrc_manager.contract_templates.dialogs._confirm_destructive_action",
                return_value=True,
            ),
            mock.patch.object(
                self.template_service,
                "delete_template",
                side_effect=RuntimeError("delete failed"),
            ),
            mock.patch("isrc_manager.contract_templates.dialogs.QMessageBox.warning") as warning,
        ):
            self.panel.delete_selected_template_record()
        warning.assert_called_once()
        self.assertIn("Unable to delete template record", self.panel.admin_status_label.text())

        self._select_admin_template(duplicated.template_id)
        with mock.patch(
            "isrc_manager.contract_templates.dialogs._confirm_destructive_action",
            return_value=True,
        ):
            self.panel.delete_selected_template_with_files()
        self.assertIn("Deleted template", self.panel.admin_status_label.text())
        self.assertIsNone(self.template_service.fetch_template(duplicated.template_id))

        with (
            mock.patch.object(self.panel, "_template_service", return_value=self.template_service),
            mock.patch.object(self.panel, "_selected_admin_template_record", return_value=None),
            mock.patch("isrc_manager.contract_templates.dialogs.QMessageBox.information") as info,
        ):
            self.panel.duplicate_selected_template()
        info.assert_called_once()

    def test_admin_revision_draft_and_artifact_actions_cover_lifecycle_error_paths(self):
        draft, snapshot, artifact = self._create_admin_draft_bundle(name="Admin Lifecycle Draft")

        with (
            mock.patch.object(
                self.template_service,
                "rescan_revision",
                side_effect=RuntimeError("rescan failed"),
            ),
            mock.patch("isrc_manager.contract_templates.dialogs.QMessageBox.warning") as warning,
        ):
            self.panel.rescan_selected_revision()
        warning.assert_called_once()
        self.assertIn("Unable to rescan revision", self.panel.admin_status_label.text())

        self.panel.rescan_selected_revision()
        self.assertIn("Rescanned revision", self.panel.admin_status_label.text())

        with (
            mock.patch.object(
                self.form_service,
                "synchronize_bindings",
                side_effect=RuntimeError("rebind failed"),
            ),
            mock.patch("isrc_manager.contract_templates.dialogs.QMessageBox.warning") as warning,
        ):
            self.panel.rebind_selected_revision()
        warning.assert_called_once()
        self.assertIn("Unable to rebind placeholders", self.panel.admin_status_label.text())

        self.panel.rebind_selected_revision()
        self.assertIn("Rebound", self.panel.admin_status_label.text())

        with (
            mock.patch.object(
                self.template_service,
                "set_active_revision",
                side_effect=RuntimeError("activate failed"),
            ),
            mock.patch("isrc_manager.contract_templates.dialogs.QMessageBox.warning") as warning,
        ):
            self.panel.activate_selected_revision()
        warning.assert_called_once()
        self.assertIn("Unable to activate revision", self.panel.admin_status_label.text())

        self.panel.activate_selected_revision()
        self.assertIn("active revision", self.panel.admin_status_label.text())

        with (
            mock.patch.object(
                self.template_service,
                "fetch_revision",
                return_value=None,
            ),
            mock.patch("isrc_manager.contract_templates.dialogs.QMessageBox.warning") as warning,
        ):
            self.panel.open_selected_draft_in_fill_tab()
        warning.assert_called_once()

        fake_export = SimpleNamespace(
            snapshot=snapshot,
            pdf_artifact=artifact,
        )

        class FailingExportService:
            def export_draft_to_pdf(self, _draft_id):
                raise RuntimeError("export failed")

        with (
            mock.patch.object(self.panel, "_export_service", return_value=FailingExportService()),
            mock.patch("isrc_manager.contract_templates.dialogs.QMessageBox.warning") as warning,
        ):
            self.panel.export_selected_admin_draft()
        warning.assert_called_once()
        self.assertIn("Unable to export draft", self.panel.admin_status_label.text())

        class SuccessfulExportService:
            def export_draft_to_pdf(self, _draft_id):
                return fake_export

        with mock.patch.object(
            self.panel, "_export_service", return_value=SuccessfulExportService()
        ):
            self.panel.export_selected_admin_draft()
        self.assertIn(f"Exported draft #{draft.draft_id}", self.panel.admin_status_label.text())

        with (
            mock.patch.object(
                self.template_service,
                "archive_draft",
                side_effect=RuntimeError("draft archive failed"),
            ),
            mock.patch("isrc_manager.contract_templates.dialogs.QMessageBox.warning") as warning,
        ):
            self.panel.toggle_selected_draft_archive()
        warning.assert_called_once()
        self.assertIn("Unable to update draft archive state", self.panel.admin_status_label.text())

        self.panel.toggle_selected_draft_archive()
        self.assertIn("Archived draft", self.panel.admin_status_label.text())
        self.panel.toggle_selected_draft_archive()
        self.assertIn("Restored draft", self.panel.admin_status_label.text())

        with mock.patch(
            "isrc_manager.contract_templates.dialogs.open_external_path",
            return_value=False,
        ) as open_external_path:
            self.panel.open_selected_artifact()
        open_external_path.assert_called_once_with(
            artifact.output_path,
            source="ContractTemplateWorkspacePanel.open_selected_artifact",
            metadata={"artifact_type": artifact.artifact_type},
        )
        self.assertIn("Could not open artifact", self.panel.admin_status_label.text())

        with (
            mock.patch(
                "isrc_manager.contract_templates.dialogs._confirm_destructive_action",
                return_value=False,
            ) as confirm,
            mock.patch.object(self.template_service, "delete_output_artifact") as delete_artifact,
        ):
            self.panel.delete_selected_artifact_record()
        confirm.assert_called_once()
        delete_artifact.assert_not_called()

        with (
            mock.patch(
                "isrc_manager.contract_templates.dialogs._confirm_destructive_action",
                return_value=True,
            ),
            mock.patch.object(
                self.template_service,
                "delete_output_artifact",
                side_effect=RuntimeError("artifact delete failed"),
            ),
            mock.patch("isrc_manager.contract_templates.dialogs.QMessageBox.warning") as warning,
        ):
            self.panel.delete_selected_artifact_with_file()
        warning.assert_called_once()
        self.assertIn("Unable to delete artifact", self.panel.admin_status_label.text())

        self.panel.refresh_admin_workspace(
            selected_template_id=self.revision.template_id,
            selected_draft_id=draft.draft_id,
            selected_artifact_id=artifact.artifact_id,
        )
        with mock.patch(
            "isrc_manager.contract_templates.dialogs._confirm_destructive_action",
            return_value=True,
        ):
            self.panel.delete_selected_artifact_record()
        self.assertIn("Deleted artifact", self.panel.admin_status_label.text())
        self.assertIsNone(self.template_service.fetch_output_artifact(artifact.artifact_id))

        with (
            mock.patch.object(self.panel, "_selected_admin_artifact_record", return_value=None),
            mock.patch("isrc_manager.contract_templates.dialogs.QMessageBox.information") as info,
        ):
            self.panel.open_selected_artifact()
        info.assert_called_once()

    def test_admin_draft_delete_actions_cover_confirmation_file_and_failure_paths(self):
        draft, _snapshot, _artifact = self._create_admin_draft_bundle(name="Delete Draft")

        with (
            mock.patch(
                "isrc_manager.contract_templates.dialogs._confirm_destructive_action",
                return_value=False,
            ) as confirm,
            mock.patch.object(self.template_service, "delete_draft") as delete_draft,
        ):
            self.panel.delete_selected_draft_record()
        confirm.assert_called_once()
        delete_draft.assert_not_called()

        with (
            mock.patch(
                "isrc_manager.contract_templates.dialogs._confirm_destructive_action",
                return_value=True,
            ),
            mock.patch.object(
                self.template_service,
                "delete_draft",
                side_effect=RuntimeError("draft delete failed"),
            ),
            mock.patch("isrc_manager.contract_templates.dialogs.QMessageBox.warning") as warning,
        ):
            self.panel.delete_selected_draft_record()
        warning.assert_called_once()
        self.assertIn("Unable to delete draft record", self.panel.admin_status_label.text())

        self.panel.refresh_admin_workspace(
            selected_template_id=self.revision.template_id,
            selected_draft_id=draft.draft_id,
        )
        with (
            mock.patch(
                "isrc_manager.contract_templates.dialogs._confirm_destructive_action",
                return_value=True,
            ),
            mock.patch("isrc_manager.contract_templates.dialogs.QMessageBox.warning") as warning,
        ):
            self.panel.delete_selected_draft_with_files()
        warning.assert_called_once()
        self.assertIn("Unable to delete draft and files", self.panel.admin_status_label.text())

        retained_draft, _snapshot, _artifact = self._create_admin_draft_bundle(
            name="Record Delete Draft"
        )
        self.panel.refresh_admin_workspace(
            selected_template_id=self.revision.template_id,
            selected_draft_id=retained_draft.draft_id,
        )
        with (
            mock.patch(
                "isrc_manager.contract_templates.dialogs._confirm_destructive_action",
                return_value=True,
            ),
            mock.patch("isrc_manager.contract_templates.dialogs.QMessageBox.warning") as warning,
        ):
            self.panel.delete_selected_draft_record()
        warning.assert_not_called()
        self.assertIn("Deleted the database record", self.panel.admin_status_label.text())
        self.assertIsNone(self.template_service.fetch_draft(retained_draft.draft_id))

        with (
            mock.patch.object(self.panel, "_template_service", return_value=self.template_service),
            mock.patch.object(self.panel, "_selected_admin_draft_record", return_value=None),
            mock.patch("isrc_manager.contract_templates.dialogs.QMessageBox.information") as info,
        ):
            self.panel.delete_selected_draft_with_files()
        info.assert_called_once()

    def test_admin_actions_cover_profileless_and_no_selection_guardrails(self):
        self._focus_import()

        with (
            mock.patch.object(self.panel, "_template_service", return_value=None),
            mock.patch.object(self.panel, "_form_service", return_value=None),
            mock.patch.object(self.panel, "_export_service", return_value=None),
            mock.patch("isrc_manager.contract_templates.dialogs.QMessageBox.warning") as warning,
            mock.patch(
                "isrc_manager.contract_templates.dialogs.QMessageBox.information"
            ) as information,
        ):
            self.panel.import_template_from_file()
            self.panel.add_revision_from_file()
            self.panel.duplicate_selected_template()
            self.panel.toggle_selected_template_archive()
            self.panel.delete_selected_template_record()
            self.panel.delete_selected_template_with_files()
            self.panel.rescan_selected_revision()
            self.panel.rebind_selected_revision()
            self.panel.activate_selected_revision()
            self.panel.open_selected_draft_in_fill_tab()
            self.panel.export_selected_admin_draft()
            self.panel.toggle_selected_draft_archive()
            self.panel.delete_selected_draft_record()
            self.panel.delete_selected_draft_with_files()
            self.panel.delete_selected_artifact_record()
            self.panel.delete_selected_artifact_with_file()

        self.assertEqual(warning.call_count, 16)
        information.assert_not_called()

        with (
            mock.patch.object(
                self.panel,
                "_selected_admin_template_record",
                return_value=None,
            ),
            mock.patch.object(
                self.panel,
                "_selected_admin_revision_record",
                return_value=None,
            ),
            mock.patch.object(
                self.panel,
                "_selected_admin_draft_record",
                return_value=None,
            ),
            mock.patch.object(
                self.panel,
                "_selected_admin_artifact_record",
                return_value=None,
            ),
            mock.patch("isrc_manager.contract_templates.dialogs.QMessageBox.warning") as warning,
            mock.patch(
                "isrc_manager.contract_templates.dialogs.QMessageBox.information"
            ) as information,
        ):
            self.panel.add_revision_from_file()
            self.panel.duplicate_selected_template()
            self.panel.toggle_selected_template_archive()
            self.panel.delete_selected_template_record()
            self.panel.delete_selected_template_with_files()
            self.panel.rescan_selected_revision()
            self.panel.rebind_selected_revision()
            self.panel.activate_selected_revision()
            self.panel.open_selected_draft_in_fill_tab()
            self.panel.export_selected_admin_draft()
            self.panel.toggle_selected_draft_archive()
            self.panel.delete_selected_draft_record()
            self.panel.delete_selected_draft_with_files()
            self.panel.open_selected_artifact()
            self.panel.delete_selected_artifact_record()
            self.panel.delete_selected_artifact_with_file()

        warning.assert_not_called()
        self.assertEqual(information.call_count, 16)

    def test_fill_registry_generation_and_manual_widget_branches_cover_guardrails(self):
        self._focus_fill()

        class RegistryService:
            def __init__(self, unavailable_reason: str | None = None):
                self.unavailable_reason = unavailable_reason
                self.assigned: list[tuple[str, int, str]] = []

            def generation_unavailable_reason(self, *, system_key: str):
                return self.unavailable_reason

            def generate_and_assign_catalog_entry_to_owner(
                self,
                *,
                owner_kind: str,
                owner_id: int,
                created_via: str,
            ):
                self.assigned.append((owner_kind, owner_id, created_via))
                return SimpleNamespace(value=f"{owner_kind.upper()}-{owner_id}")

        class OwnerService:
            def __init__(self, registry_service):
                self.registry_service = registry_service

            def code_registry_service(self):
                return self.registry_service

        class ContractRegistryService:
            def __init__(self):
                self.generated: list[tuple[int, str, str]] = []

            def code_registry_service(self):
                return RegistryService()

            def generate_registry_value_for_contract(
                self,
                record_id: int,
                *,
                system_key: str,
                created_via: str,
            ):
                self.generated.append((record_id, system_key, created_via))
                return SimpleNamespace(value=f"CONTRACT-{record_id}")

        def selector_widget(scope: str, *, selected: bool = True) -> QWidget:
            container = QWidget(self.panel)
            combo = QComboBox(container)
            combo.addItem("Choose owner", None)
            combo.addItem("Owner 7", 7)
            combo.setCurrentIndex(1 if selected else 0)
            container.setProperty("selector_combo", combo)
            container.setProperty("scope_entity_type", scope)
            return container

        with mock.patch.object(self.panel, "_export_service", return_value=None):
            self.assertIn(
                "Open a profile",
                self.panel._selector_generation_unavailable_reason(
                    scope_entity_type="track",
                    system_key="catalog_number",
                ),
            )

        blocked_registry = RegistryService("blocked by settings")
        with mock.patch.object(
            self.panel,
            "_export_service",
            return_value=SimpleNamespace(
                track_service=OwnerService(blocked_registry),
                release_service=None,
                contract_service=None,
            ),
        ):
            self.assertEqual(
                self.panel._selector_generation_unavailable_reason(
                    scope_entity_type="track",
                    system_key="catalog_number",
                ),
                "blocked by settings",
            )

        with mock.patch.object(
            self.panel,
            "_export_service",
            return_value=SimpleNamespace(
                track_service=None,
                release_service=None,
                contract_service=None,
            ),
        ):
            self.assertIn(
                "Contract service",
                self.panel._selector_generation_unavailable_reason(
                    scope_entity_type="contract",
                    system_key="registry_sha256_key",
                ),
            )
            self.assertIn(
                "Track service",
                self.panel._selector_generation_unavailable_reason(
                    scope_entity_type="track",
                    system_key="catalog_number",
                ),
            )
            self.assertIn(
                "Release service",
                self.panel._selector_generation_unavailable_reason(
                    scope_entity_type="release",
                    system_key="catalog_number",
                ),
            )
            self.assertIn(
                "Code registry service",
                self.panel._selector_generation_unavailable_reason(
                    scope_entity_type="party",
                    system_key="catalog_number",
                ),
            )

        with mock.patch("isrc_manager.contract_templates.dialogs.QMessageBox.information") as info:
            self.panel._generate_selector_registry_value(
                selector_widget("track", selected=False),
                system_key="catalog_number",
            )
        info.assert_called_once()

        with (
            mock.patch.object(self.panel, "_export_service", return_value=None),
            mock.patch("isrc_manager.contract_templates.dialogs.QMessageBox.warning") as warning,
        ):
            self.panel._generate_selector_registry_value(
                selector_widget("track"),
                system_key="catalog_number",
            )
        warning.assert_called_once()

        with (
            mock.patch.object(
                self.panel,
                "_export_service",
                return_value=SimpleNamespace(
                    track_service=OwnerService(blocked_registry),
                    release_service=None,
                    contract_service=None,
                ),
            ),
            mock.patch("isrc_manager.contract_templates.dialogs.QMessageBox.warning") as warning,
        ):
            self.panel._generate_selector_registry_value(
                selector_widget("track"),
                system_key="catalog_number",
            )
        warning.assert_called_once()
        self.assertEqual(self.panel.fill_warning_label.text(), "blocked by settings")

        track_registry = RegistryService()
        with mock.patch.object(
            self.panel,
            "_export_service",
            return_value=SimpleNamespace(
                track_service=OwnerService(track_registry),
                release_service=None,
                contract_service=None,
            ),
        ):
            self.panel._generate_selector_registry_value(
                selector_widget("track"),
                system_key="catalog_number",
            )
        self.assertEqual(
            track_registry.assigned,
            [("track", 7, "contract_template.fill_form.generate")],
        )
        self.assertIn("Generated TRACK-7", self.panel.fill_status_label.text())

        contract_service = ContractRegistryService()
        with mock.patch.object(
            self.panel,
            "_export_service",
            return_value=SimpleNamespace(
                track_service=None,
                release_service=None,
                contract_service=contract_service,
            ),
        ):
            self.panel._generate_selector_registry_value(
                selector_widget("contract"),
                system_key="registry_sha256_key",
            )
        self.assertEqual(
            contract_service.generated,
            [(7, "registry_sha256_key", "contract_template.fill_form.generate")],
        )
        self.assertIn("Generated CONTRACT-7", self.panel.fill_status_label.text())

        release_registry = RegistryService()
        with mock.patch.object(
            self.panel,
            "_export_service",
            return_value=SimpleNamespace(
                track_service=None,
                release_service=OwnerService(release_registry),
                contract_service=None,
            ),
        ):
            self.assertIsNone(
                self.panel._selector_generation_unavailable_reason(
                    scope_entity_type="release",
                    system_key="catalog_number",
                )
            )

        with (
            mock.patch.object(
                self.panel,
                "_selector_generation_unavailable_reason",
                return_value=None,
            ),
            mock.patch.object(
                self.panel,
                "_export_service",
                return_value=SimpleNamespace(),
            ),
            mock.patch("isrc_manager.contract_templates.dialogs.QMessageBox.critical") as critical,
        ):
            self.panel._generate_selector_registry_value(
                selector_widget("party"),
                system_key="catalog_number",
            )
        critical.assert_called_once()

        for scope, unavailable_export_service in (
            (
                "track",
                SimpleNamespace(
                    track_service=None,
                    release_service=None,
                    contract_service=None,
                ),
            ),
            (
                "track",
                SimpleNamespace(
                    track_service=OwnerService(None),
                    release_service=None,
                    contract_service=None,
                ),
            ),
            (
                "contract",
                SimpleNamespace(
                    track_service=None,
                    release_service=None,
                    contract_service=None,
                ),
            ),
        ):
            with (
                mock.patch.object(
                    self.panel,
                    "_selector_generation_unavailable_reason",
                    return_value=None,
                ),
                mock.patch.object(
                    self.panel,
                    "_export_service",
                    return_value=unavailable_export_service,
                ),
                mock.patch(
                    "isrc_manager.contract_templates.dialogs.QMessageBox.critical"
                ) as critical,
            ):
                self.panel._generate_selector_registry_value(
                    selector_widget(scope),
                    system_key="catalog_number",
                )
            critical.assert_called_once()

        selector_field = ContractTemplateFormSelectorField(
            selector_key="track",
            display_label="Track",
            scope_entity_type="track",
            scope_policy=None,
            widget_kind="combo",
            required=True,
            placeholder_symbols=(
                "{{db.track.catalog_number}}",
                "{{db.track.catalog_number}}",
                "{{manual.not_registry}}",
            ),
            choices=(ContractTemplateFormChoice("1", "Track One", "First"),),
            description="Choose a track",
        )
        with mock.patch.object(
            self.panel,
            "_export_service",
            return_value=SimpleNamespace(
                track_service=OwnerService(blocked_registry),
                release_service=None,
                contract_service=None,
            ),
        ):
            selector = self.panel._build_selector_widget(selector_field)
        buttons = selector.findChildren(QToolButton) + selector.findChildren(QComboBox)
        self.assertTrue(buttons)
        self.assertEqual(
            selector.property("generation_warning_lines"),
            ["Generate Catalog Number is unavailable: blocked by settings"],
        )
        with mock.patch.object(self.panel, "_generate_selector_registry_value") as generate:
            self.panel._handle_selector_generate_clicked(selector, "catalog_number")
        generate.assert_called_once_with(selector, system_key="catalog_number")

        auto_field = ContractTemplateFormAutoField(
            canonical_symbol="{{db.track.catalog_number}}",
            display_label="Catalog Number",
            source_label="Track catalog number",
            required=False,
            placeholder_count=1,
            description="Generated when available",
        )
        with mock.patch.object(
            self.panel,
            "_export_service",
            return_value=SimpleNamespace(
                track_service=OwnerService(blocked_registry),
                release_service=None,
                contract_service=None,
            ),
        ):
            auto_widget = self.panel._build_auto_field_widget(auto_field)
        self.assertEqual(auto_widget.text(), "Draft Registry")
        self.assertTrue(auto_widget.property("generation_warning_lines"))

        with mock.patch.object(
            self.panel,
            "_export_service",
            return_value=SimpleNamespace(
                track_service=OwnerService(RegistryService()),
                release_service=None,
                contract_service=None,
            ),
        ):
            available_auto_widget = self.panel._build_auto_field_widget(auto_field)
        self.assertIn("Issued and linked", available_auto_widget.toolTip())

        options_widget = self.panel._build_manual_widget(
            ContractTemplateFormManualField(
                canonical_symbol="{{manual.option}}",
                display_label="Option",
                field_type="text",
                widget_kind="combo",
                required=False,
                placeholder_count=1,
                options=("One", "Two"),
            )
        )
        self.assertIsInstance(options_widget, QComboBox)
        self.assertEqual(options_widget.itemData(2), "Two")

        self.panel._build_manual_widget(
            ContractTemplateFormManualField(
                canonical_symbol="{{manual.date}}",
                display_label="Date",
                field_type="date",
                widget_kind="date",
                required=False,
                placeholder_count=1,
            )
        )
        format_combo = self.panel.manual_date_format_combo_widgets["{{manual.date}}"]
        format_edit = self.panel.manual_date_format_widgets["{{manual.date}}"]
        format_combo.setCurrentIndex(1)
        self.assertEqual(format_edit.text(), format_combo.currentData())

        text_widget = self.panel._build_manual_widget(
            ContractTemplateFormManualField(
                canonical_symbol="{{manual.note}}",
                display_label="Note",
                field_type="text",
                widget_kind="line",
                required=False,
                placeholder_count=1,
            )
        )
        self.assertIsInstance(text_widget, QLineEdit)
        self.assertIn("Note", text_widget.placeholderText())

    def test_duplicate_number_widget_defers_indexed_field_sync(self):
        duplicate_widget = self.panel._build_manual_widget(
            ContractTemplateFormManualField(
                canonical_symbol="{{duplicate.number}}",
                display_label="Duplicate Count",
                field_type="number",
                widget_kind="spin",
                required=False,
                placeholder_count=1,
            )
        )
        self.panel.manual_widgets["{{duplicate.number}}"] = duplicate_widget

        with (
            mock.patch.object(
                self.panel,
                "_sync_indexed_selector_fields_from_duplicate_number",
            ) as sync,
            mock.patch("isrc_manager.contract_templates.dialogs.QTimer.singleShot") as single_shot,
        ):
            duplicate_widget.setValue(2)

        sync.assert_not_called()
        single_shot.assert_called_once()
        delay, callback = single_shot.call_args.args
        self.assertEqual(delay, 0)

        with mock.patch.object(
            self.panel,
            "_sync_indexed_selector_fields_from_duplicate_number",
        ) as sync:
            callback()

        sync.assert_called_once_with()
        self.assertFalse(getattr(self.panel, "_indexed_fields_sync_pending", False))

    def test_fill_draft_selection_export_and_preview_helper_edges(self):
        self._focus_fill()
        draft, snapshot, artifact = self._create_admin_draft_bundle(name="Fill Helper")
        self.panel.open_selected_draft_in_fill_tab()
        self.assertEqual(self.panel._current_tab_key(), "fill")
        self.assertEqual(self.panel._loaded_draft_id, draft.draft_id)
        self._focus_fill()

        for combo_name, selector in (
            ("fill_template_combo", self.panel._selected_fill_template_id),
            ("fill_revision_combo", self.panel._selected_fill_revision_id),
            ("fill_draft_combo", self.panel._selected_fill_draft_id),
        ):
            combo = getattr(self.panel, combo_name)
            delattr(self.panel, combo_name)
            try:
                self.assertIsNone(selector())
            finally:
                setattr(self.panel, combo_name, combo)

            previous_signal_state = combo.blockSignals(True)
            try:
                combo.addItem("Invalid", "not-an-id")
                combo.setCurrentIndex(combo.count() - 1)
                self.assertIsNone(selector())
            finally:
                combo.blockSignals(previous_signal_state)
                combo.removeItem(combo.count() - 1)

        with mock.patch.object(self.panel, "_selected_fill_draft_id", return_value=999_999):
            self.assertIsNone(self.panel._selected_fill_draft_record())
        self.panel._loaded_draft_id = 999_999
        self.assertIsNone(self.panel._loaded_draft_record())

        self.panel.fill_draft_name_edit.clear()
        saved_definition = self.panel._fill_definition
        self.panel._fill_definition = None
        try:
            self.assertEqual(self.panel._draft_name_value(), "Contract Template Draft")
        finally:
            self.panel._fill_definition = saved_definition
        self.assertIn("Dialog Template", self.panel._draft_name_value())

        self.panel.fill_draft_storage_combo.addItem("Invalid", "elsewhere")
        self.panel.fill_draft_storage_combo.setCurrentIndex(
            self.panel.fill_draft_storage_combo.count() - 1
        )
        self.assertEqual(self.panel._selected_storage_mode_value(), "database")
        self.panel._clear_fill_drafts("No drafts remain.")
        self.assertEqual(self.panel._visible_drafts, [])
        self.assertIn("No drafts remain", self.panel.fill_draft_status_label.text())

        self.panel._sync_draft_controls_from_selection(None)
        self.assertTrue(self.panel.fill_draft_name_edit.text())
        self.panel._sync_draft_controls_from_selection(draft)
        self.assertEqual(self.panel.fill_draft_name_edit.text(), draft.name)

        self.panel._sync_fill_export_status(None)
        self.assertIn("Export saves", self.panel.fill_export_status_label.text())
        with mock.patch.object(self.panel, "_latest_pdf_artifact_for_draft", return_value=None):
            self.panel._sync_fill_export_status(draft)
        self.assertIn("has not produced", self.panel.fill_export_status_label.text())
        with mock.patch.object(
            self.panel,
            "_latest_pdf_artifact_for_draft",
            return_value=artifact,
        ):
            self.panel._sync_fill_export_status(draft)
        self.assertIn(str(artifact.output_path), self.panel.fill_export_status_label.text())

        self.assertIsNone(self.panel._latest_pdf_artifact_for_draft(None))
        with mock.patch.object(self.panel, "_template_service", return_value=None):
            self.assertIsNone(self.panel._latest_pdf_artifact_for_draft(draft))
        draft_with_snapshot = SimpleNamespace(
            draft_id=draft.draft_id,
            last_resolved_snapshot_id=snapshot.snapshot_id,
        )
        self.assertEqual(
            self.panel._latest_pdf_artifact_for_draft(draft_with_snapshot).artifact_id,
            artifact.artifact_id,
        )
        self.assertEqual(
            self.panel._latest_pdf_artifact_for_draft(draft).artifact_id,
            artifact.artifact_id,
        )

        with (
            mock.patch.object(self.panel, "_loaded_draft_record", return_value=None),
            mock.patch.object(self.panel, "_selected_fill_draft_record", return_value=None),
            mock.patch.object(self.panel, "_save_draft", return_value=False) as save_draft,
        ):
            self.assertIsNone(self.panel._ensure_export_draft_record())
        save_draft.assert_called_once_with(save_as_new=True)

        with (
            mock.patch.object(
                self.panel,
                "_loaded_draft_record",
                side_effect=(None, draft),
            ),
            mock.patch.object(self.panel, "_selected_fill_draft_record", return_value=None),
            mock.patch.object(self.panel, "_save_draft", return_value=True) as save_draft,
        ):
            self.assertEqual(self.panel._ensure_export_draft_record(), draft)
        save_draft.assert_called_once_with(save_as_new=True)

        self.panel._fill_dirty = True
        with (
            mock.patch.object(self.panel, "_loaded_draft_record", return_value=draft),
            mock.patch.object(self.panel, "_save_draft", return_value=False) as save_draft,
        ):
            self.assertIsNone(self.panel._ensure_export_draft_record())
        save_draft.assert_called_once_with(save_as_new=False)

        self.panel._fill_dirty = True
        with (
            mock.patch.object(self.panel, "_loaded_draft_record", return_value=draft),
            mock.patch.object(self.panel, "_save_draft", return_value=True) as save_draft,
        ):
            self.assertEqual(self.panel._ensure_export_draft_record(), draft)
        save_draft.assert_called_once_with(save_as_new=False)
        self.panel._fill_dirty = False
        with mock.patch.object(self.panel, "_loaded_draft_record", return_value=draft):
            self.assertEqual(self.panel._ensure_export_draft_record(), draft)

        class PreviewController:
            def __init__(self):
                self.contexts: list[int | None] = []
                self.stale: list[str] = []
                self.refreshes: list[tuple[str, int]] = []

            def set_revision_context(self, revision_id):
                self.contexts.append(revision_id)

            def mark_stale(self, message):
                self.stale.append(message)

            def request_refresh(self, *, reason: str, delay_ms: int):
                self.refreshes.append((reason, delay_ms))

            def clear(self):
                self.contexts.append(None)

            def cleanup(self):
                self.contexts.append(None)

        preview_controller = PreviewController()
        self.panel._fill_preview_controller = preview_controller
        self.panel.fill_html_preview_view = QWidget(self.panel)
        with mock.patch.object(
            self.template_service,
            "revision_supports_html_working_draft",
            return_value=False,
        ):
            self.panel._sync_html_preview_state(self.revision.revision_id)
        self.assertIsNone(preview_controller.contexts[-1])

        self.panel._suspend_preview_refresh = True
        with mock.patch.object(
            self.template_service,
            "revision_supports_html_working_draft",
            return_value=True,
        ):
            self.panel._sync_html_preview_state(self.revision.revision_id)
        self.assertEqual(preview_controller.contexts[-1], self.revision.revision_id)
        self.assertTrue(preview_controller.stale)
        self.assertIn("Restoring workspace", self.panel.fill_preview_status_label.text())

        self.panel._suspend_preview_refresh = False
        with mock.patch.object(
            self.template_service,
            "revision_supports_html_working_draft",
            return_value=True,
        ):
            self.panel._sync_html_preview_state(self.revision.revision_id)
        self.assertEqual(
            preview_controller.refreshes[-1],
            ("Previewing current HTML draft state.", 0),
        )
        self.panel._fill_preview_controller = None

    def test_fill_widget_state_symbol_details_and_manual_helper_edges(self):
        self._focus_fill()

        selector = QComboBox(self.panel)
        selector.addItem("Choose", None)
        selector.addItem("Seven", 7)
        selector.setCurrentIndex(1)
        checkbox = QCheckBox(self.panel)
        checkbox.setChecked(True)
        checkbox.setProperty("has_user_value", True)
        spin = QDoubleSpinBox(self.panel)
        spin.setValue(3.5)
        spin.setProperty("has_user_value", True)
        date_edit = QDateEdit(self.panel)
        date_edit.setDate(QDate(2026, 5, 26))
        date_edit.setProperty("has_user_value", True)
        line_edit = QLineEdit("filled", self.panel)
        format_edit = QLineEdit("MM/dd/yyyy", self.panel)
        format_combo = QComboBox(self.panel)
        format_combo.addItem("Default", "d.mmm.yyyy")
        format_combo.addItem("Custom", "__custom__")

        self.panel.selector_widgets = {"{{db.track.id}}": selector}
        self.panel.manual_widgets = {
            "{{manual.check}}": checkbox,
            "{{manual.number}}": spin,
            "{{manual.date}}": date_edit,
            "{{manual.text}}": line_edit,
        }
        self.panel.manual_date_format_widgets = {"{{manual.date}}": format_edit}
        self.panel.manual_date_format_combo_widgets = {"{{manual.date}}": format_combo}
        self.panel._clear_fill_input_values()
        self.assertIsNone(self.panel._read_widget_value(selector))
        self.assertIsNone(self.panel._read_widget_value(checkbox))
        self.assertIsNone(self.panel._read_widget_value(spin))
        self.assertIsNone(self.panel._read_widget_value(date_edit))
        self.assertEqual(self.panel._read_widget_value(line_edit), None)
        self.assertEqual(format_edit.text(), "dd.mmm.yyyy")

        self.assertEqual(
            self.panel._indexed_selector_count_from_manual_values({"{{duplicate.number}}": None}),
            1,
        )
        self.assertEqual(
            self.panel._indexed_selector_count_from_manual_values({"{{duplicate.number}}": "2.5"}),
            1,
        )
        self.assertEqual(
            self.panel._indexed_selector_count_from_manual_values({"{{duplicate.number}}": "500"}),
            200,
        )

        duplicate_widget = QDoubleSpinBox(self.panel)
        duplicate_widget.setRange(0, 200)
        duplicate_widget.setDecimals(0)
        duplicate_widget.setValue(2)
        duplicate_widget.setProperty("has_user_value", True)
        self.panel.manual_widgets["{{duplicate.number}}"] = duplicate_widget
        self.assertEqual(self.panel._current_indexed_selector_count(), 2)
        self.panel.manual_widgets.pop("{{duplicate.number}}")
        self.assertEqual(self.panel._current_indexed_selector_count(), 1)
        self.panel.manual_widgets["{{duplicate.number}}"] = duplicate_widget

        selector_combo = QComboBox(self.panel)
        selector_combo.addItem("Choose", None)
        selector_combo.addItem("Original", "original")
        selector_combo.setCurrentIndex(1)
        self.panel.selector_widgets = {"{{db.track.track_title}}": selector_combo}
        indexed_template = ContractTemplateFormSelectorField(
            selector_key="track",
            display_label="Track",
            scope_entity_type="track",
            scope_policy=None,
            widget_kind="combo",
            required=True,
            placeholder_symbols=("{{db.track.track_title}}",),
            choices=(ContractTemplateFormChoice("original", "Original", None),),
        )
        self.panel._fill_definition = SimpleNamespace(
            indexed_selector_fields=(indexed_template,),
        )
        self.panel._fill_indexed_selector_count = 1
        rebuild_calls: list[tuple[int, dict[str, object]]] = []
        self.panel._fill_definition = None
        self.panel._sync_indexed_selector_fields_from_duplicate_number()
        self.panel._fill_definition = SimpleNamespace(indexed_selector_fields=())
        self.panel._sync_indexed_selector_fields_from_duplicate_number()
        with mock.patch.object(
            self.panel,
            "_rebuild_selector_fields",
            side_effect=lambda _definition, *, indexed_count, preserved_values=None: rebuild_calls.append(
                (indexed_count, dict(preserved_values or {}))
            ),
        ):
            self.panel._fill_definition = SimpleNamespace(
                indexed_selector_fields=(indexed_template,),
            )
            self.panel._fill_indexed_selector_count = 2
            self.panel._sync_indexed_selector_fields_from_duplicate_number()
            self.panel._fill_indexed_selector_count = 1
            self.panel._sync_indexed_selector_fields_from_duplicate_number()
        self.assertEqual(len(rebuild_calls), 1)
        self.assertEqual(rebuild_calls[0][0], 2)
        self.assertEqual(rebuild_calls[0][1]["{{db.track.track_title}}"], "original")
        self.assertIn("{{duplicate.number}}", rebuild_calls[0][1])

        form_definition = SimpleNamespace(
            selector_fields=(
                ContractTemplateFormSelectorField(
                    selector_key="track",
                    display_label="Track",
                    scope_entity_type="track",
                    scope_policy=None,
                    widget_kind="combo",
                    required=True,
                    placeholder_symbols=("{{db.track.catalog_number}}",),
                    choices=(ContractTemplateFormChoice("7", "Seven", None),),
                ),
            ),
            indexed_selector_fields=(),
        )
        self.panel._rebuild_selector_fields(
            form_definition,
            indexed_count=0,
            preserved_values={"{{db.track.catalog_number}}": "7"},
        )
        rebuilt_selector = self.panel.selector_widgets["{{db.track.catalog_number}}"]
        self.assertEqual(self.panel._read_widget_value(rebuilt_selector), "7")

        direct_combo = QComboBox(self.panel)
        direct_combo.addItem("Choose", None)
        direct_combo.addItem("By Data", 11)
        self.panel._write_widget_value(direct_combo, "11", explicit=True)
        self.assertEqual(direct_combo.currentData(), 11)
        direct_combo.addItem("By Text", "text")
        self.panel._write_widget_value(direct_combo, "By Text", explicit=True)
        self.assertEqual(direct_combo.currentText(), "By Text")
        self.panel._select_combo_data(direct_combo, "missing")
        self.assertEqual(direct_combo.currentIndex(), 0)

        checkbox.setProperty("has_user_value", False)
        self.assertIsNone(self.panel._read_widget_value(checkbox))
        self.panel._write_widget_value(checkbox, True, explicit=True)
        self.assertIs(self.panel._read_widget_value(checkbox), True)
        spin.setProperty("has_user_value", False)
        self.assertIsNone(self.panel._read_widget_value(spin))
        self.panel._write_widget_value(spin, 4, explicit=True)
        self.assertEqual(self.panel._read_widget_value(spin), 4)
        self.panel._write_widget_value(spin, 4.5, explicit=True)
        self.assertEqual(self.panel._read_widget_value(spin), 4.5)
        date_edit.setProperty("has_user_value", False)
        self.assertIsNone(self.panel._read_widget_value(date_edit))
        self.panel._write_widget_value(date_edit, "not-a-date", explicit=True)
        self.assertIsNone(self.panel._read_widget_value(date_edit))
        self.panel._write_widget_value(date_edit, "2026-05-26", explicit=True)
        self.assertEqual(self.panel._read_widget_value(date_edit), "2026-05-26")
        self.panel._write_widget_value(line_edit, "  note  ", explicit=True)
        self.assertEqual(self.panel._read_widget_value(line_edit), "note")
        self.assertIsNone(self.panel._read_widget_value(QWidget(self.panel)))

        selector_container = QWidget(self.panel)
        selector_container.setProperty("selector_combo", direct_combo)
        self.assertIs(self.panel._selector_combo(direct_combo), direct_combo)
        self.assertIs(self.panel._selector_combo(None), None)
        self.assertIs(self.panel._selector_combo(selector_container), direct_combo)
        selector_child_container = QWidget(self.panel)
        child_combo = QComboBox(selector_child_container)
        child_combo.setObjectName("contractTemplateSelectorWidget")
        self.assertIs(self.panel._selector_combo(selector_child_container), child_combo)

        self.panel._set_manual_date_format("missing", "yyyy")
        self.panel.manual_date_format_combo_widgets = {}
        self.panel._set_manual_date_format("{{manual.date}}", "yyyy")
        self.panel.manual_date_format_widgets = {"{{manual.date}}": format_edit}
        self.panel.manual_date_format_combo_widgets = {"{{manual.date}}": format_combo}
        self.panel._set_manual_date_format("{{manual.date}}", "custom-format")
        self.assertEqual(format_combo.currentData(), "__custom__")
        self.panel._sync_manual_date_format_combo("missing")
        format_edit.setText("another-custom")
        self.panel._sync_manual_date_format_combo("{{manual.date}}")
        self.assertEqual(format_combo.currentData(), "__custom__")

        class PreviewController:
            def __init__(self):
                self.stale: list[str] = []
                self.refreshes: list[tuple[str, int]] = []

            def mark_stale(self, message):
                self.stale.append(message)

            def request_refresh(self, *, reason: str, delay_ms: int):
                self.refreshes.append((reason, delay_ms))

        preview_controller = PreviewController()
        self.panel._fill_dirty = False
        self.panel._suspend_fill_updates = True
        self.panel._mark_fill_dirty()
        self.assertFalse(self.panel._fill_dirty)
        self.panel._suspend_fill_updates = False
        self.panel._fill_payload_extras = {"_html_draft": {"old": True}}
        self.panel._loaded_draft_id = 44
        self.panel._fill_preview_controller = preview_controller
        self.panel._mark_fill_dirty()
        self.assertTrue(self.panel._fill_dirty)
        self.assertNotIn("_html_draft", self.panel._fill_payload_extras)
        self.assertIn("Draft #44", self.panel.fill_draft_status_label.text())
        self.assertTrue(preview_controller.stale)
        self.assertEqual(
            preview_controller.refreshes[-1],
            ("Previewing current HTML draft state.", 180),
        )
        self.panel._loaded_draft_id = None
        self.panel._fill_dirty = False
        self.panel._fill_preview_controller = None
        self.panel._mark_fill_dirty()
        self.assertIn("Current fill form", self.panel.fill_draft_status_label.text())

        self._focus_symbols()
        original_table = self.panel.table
        table = QTableWidget(1, 5, self.panel)
        self.panel.table = table
        try:
            table.selectRow(0)
            self.assertIsNone(self.panel._selected_symbol())
            item = QTableWidgetItem("Symbol")
            item.setData(Qt.UserRole, "{{manual.symbol}}")
            table.setItem(0, 4, item)
            self.assertEqual(self.panel._selected_symbol(), "{{manual.symbol}}")
            self.panel._restore_selection("missing")
            self.assertEqual(table.selectionModel().selectedRows()[0].row(), 0)
            table.setRowCount(0)
            self.panel._restore_selection(None)
            self.assertEqual(table.selectionModel().selectedRows(), [])
        finally:
            self.panel.table = original_table
            table.deleteLater()

        with mock.patch.object(self.panel, "_selected_symbol", return_value="missing"):
            self.panel._visible_entries = []
            self.assertIsNone(self.panel._selected_entry())

        entry = ContractTemplateCatalogEntry(
            binding_kind="db",
            namespace="track",
            key="mood",
            canonical_symbol="{{db.track.mood}}",
            display_label="Mood",
            field_type="custom_text",
            description="Mood guidance",
            scope_entity_type="track",
            scope_policy="track_context",
            source_table="tracks",
            source_column="mood",
            options=("Dark", "Bright"),
            custom_field_id=12,
            is_custom_field=True,
        )
        with mock.patch.object(self.panel, "_selected_entry", return_value=None):
            self.panel._update_selected_details()
        self.assertEqual(self.panel.selected_label_value.text(), "No symbol selected.")
        with mock.patch.object(self.panel, "_selected_entry", return_value=entry):
            self.panel._update_selected_details()
        self.assertEqual(self.panel.selected_label_value.text(), "Mood")
        self.assertIn("Custom Field ID: 12", self.panel.selected_description_value.text())
        self.assertIn("Options: Dark, Bright", self.panel.selected_description_value.text())
        with mock.patch.object(
            self.panel,
            "_selected_symbol",
            return_value="{{db.track.mood}}",
        ):
            self.panel._visible_entries = [entry]
            self.assertEqual(self.panel._selected_entry(), entry)

        with mock.patch(
            "isrc_manager.contract_templates.dialogs.QApplication.instance",
            return_value=None,
        ):
            self.panel._copy_to_clipboard("nothing")
        with mock.patch(
            "isrc_manager.contract_templates.dialogs.QApplication.instance",
            return_value=SimpleNamespace(clipboard=lambda: None),
        ):
            self.panel._copy_to_clipboard("nothing")

        self.panel.manual_key_edit.setText("License")
        with mock.patch.object(self.panel, "_catalog_service", return_value=None):
            self.panel._refresh_manual_symbol_preview()
        self.assertIn("Open a profile", self.panel.manual_feedback_label.text())

        class ManualService:
            def __init__(self, fail: bool = False):
                self.fail = fail

            def build_manual_symbol(self, raw_value: str):
                if self.fail:
                    raise ValueError("manual key failed")
                return f"{{{{manual.{raw_value.lower()}}}}}"

        self.panel.manual_key_edit.setText("")
        with mock.patch.object(self.panel, "_catalog_service", return_value=ManualService()):
            self.panel._refresh_manual_symbol_preview()
        self.assertIn("canonical Phase 1 grammar", self.panel.manual_feedback_label.text())
        self.panel.manual_key_edit.setText("Bad Key")
        with mock.patch.object(
            self.panel,
            "_catalog_service",
            return_value=ManualService(fail=True),
        ):
            self.panel._refresh_manual_symbol_preview()
        self.assertIn("manual key failed", self.panel.manual_feedback_label.text())

        with mock.patch.object(self.panel, "refresh_fill_form") as refresh_fill_form:
            self.panel._suspend_fill_updates = True
            self.panel._on_fill_template_changed()
            self.panel._on_fill_revision_changed()
            refresh_fill_form.assert_not_called()
            self.panel._suspend_fill_updates = False
            self.panel._on_fill_template_changed()
            self.panel._on_fill_revision_changed()
            self.assertEqual(refresh_fill_form.call_count, 2)

        selected_record = SimpleNamespace(draft_id=77)
        with (
            mock.patch.object(
                self.panel,
                "_selected_fill_draft_record",
                return_value=selected_record,
            ),
            mock.patch.object(self.panel, "_sync_draft_controls_from_selection") as sync_controls,
            mock.patch.object(self.panel, "_sync_fill_export_status") as sync_export,
        ):
            self.panel._suspend_fill_updates = True
            self.panel._on_fill_draft_changed()
            sync_controls.assert_not_called()
            self.panel._suspend_fill_updates = False
            self.panel._on_fill_draft_changed()
            sync_controls.assert_called_once_with(selected_record)
            sync_export.assert_called_once_with(selected_record)

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

    def test_workspace_profileless_services_show_safe_empty_states(self):
        profileless_panel = ContractTemplateWorkspacePanel(
            catalog_service_provider=lambda: None,
            template_service_provider=lambda: None,
            form_service_provider=lambda: None,
            export_service_provider=lambda: None,
        )
        try:
            profileless_panel.show()
            pump_events(app=self.app, cycles=2)

            profileless_panel.focus_tab("symbols")
            pump_events(app=self.app, cycles=2)
            self.assertEqual(profileless_panel.table.rowCount(), 0)
            self.assertEqual(profileless_panel.namespace_combo.count(), 1)
            self.assertIn("Open a profile", profileless_panel.status_label.text())

            profileless_panel.focus_tab("fill")
            pump_events(app=self.app, cycles=2)
            self.assertIsNone(profileless_panel._fill_definition)
            self.assertEqual(
                profileless_panel.current_fill_state(),
                {
                    "revision_id": None,
                    "db_selections": {},
                    "manual_values": {},
                    "type_overrides": {},
                },
            )
            self.assertFalse(profileless_panel._save_draft(save_as_new=True))
            self.assertIn("Choose a revision", profileless_panel.fill_draft_status_label.text())
            profileless_panel.load_selected_draft()
            self.assertIn("Select a draft", profileless_panel.fill_draft_status_label.text())
            profileless_panel.export_current_pdf()
            self.assertIn("Open a profile", profileless_panel.fill_export_status_label.text())
            profileless_panel.refresh_current_html_preview()
            self.assertIn("Open a profile", profileless_panel.fill_preview_status_label.text())

            profileless_panel.focus_tab("import")
            pump_events(app=self.app, cycles=2)
            self.assertEqual(profileless_panel.admin_template_table.rowCount(), 0)
            self.assertEqual(profileless_panel.admin_revision_table.rowCount(), 0)
            self.assertEqual(profileless_panel.admin_draft_table.rowCount(), 0)
            self.assertIn("Open a profile", profileless_panel.admin_status_label.text())
        finally:
            profileless_panel.close()
            profileless_panel.deleteLater()
            pump_events(app=self.app, cycles=2)

    def test_fill_form_refresh_handles_empty_revision_and_corrupted_definition_states(self):
        self.panel.refresh_fill_form()
        self._focus_fill()

        empty_template_service = SimpleNamespace(
            list_templates=lambda: (),
        )
        with mock.patch.object(
            self.panel, "_template_service", return_value=empty_template_service
        ):
            self.panel.refresh_fill_form()
        self.assertIsNone(self.panel._fill_definition)
        self.assertIn("No contract template records", self.panel.fill_status_label.text())
        self.assertIn("Choose a template revision", self.panel.fill_draft_status_label.text())

        empty_template = SimpleNamespace(
            template_id=9001,
            name="Empty Revision Template",
            active_revision_id=None,
        )
        revisionless_service = SimpleNamespace(
            list_templates=lambda: (empty_template,),
            fetch_template=lambda _template_id: empty_template,
            list_revisions=lambda _template_id: (),
        )
        with mock.patch.object(self.panel, "_template_service", return_value=revisionless_service):
            self.panel.refresh_fill_form()
        self.assertIsNone(self.panel._fill_definition)
        self.assertIn("does not have any stored revisions", self.panel.fill_status_label.text())
        self.assertIn("no active revision context", self.panel.fill_draft_status_label.text())

        self.panel.refresh_fill_form()
        self.panel._select_combo_data(self.panel.fill_template_combo, self.revision.template_id)
        self.panel._select_combo_data(self.panel.fill_revision_combo, self.revision.revision_id)
        with mock.patch.object(
            self.form_service,
            "build_form_definition",
            side_effect=RuntimeError("corrupted placeholder map"),
        ):
            self.panel.refresh_fill_form()
        self.assertIsNone(self.panel._fill_definition)
        self.assertIn("Unable to build a fill form", self.panel.fill_status_label.text())
        self.assertIn("corrupted placeholder map", self.panel.fill_warning_label.text())

    def test_fill_draft_save_failure_paths_do_not_persist_invalid_workflow_state(self):
        self._focus_fill()
        self.panel.fill_draft_name_edit.setText("Validation Failure Draft")

        class ValidatingExportService:
            def validate_draft_registry_generation_for_revision(self, _revision_id):
                raise RuntimeError("registry validation failed")

        with (
            mock.patch.object(
                self.panel,
                "_export_service",
                return_value=ValidatingExportService(),
            ),
            mock.patch("isrc_manager.contract_templates.dialogs.QMessageBox.warning") as warning,
        ):
            self.assertFalse(self.panel._save_draft(save_as_new=True))

        warning.assert_called_once()
        self.assertIn("registry validation failed", self.panel.fill_draft_status_label.text())
        self.assertEqual(
            self.template_service.list_drafts(revision_id=self.revision.revision_id), []
        )

        class AssignmentFailingExportService:
            def validate_draft_registry_generation_for_revision(self, _revision_id):
                return None

            def ensure_registry_assignments_for_draft(self, _draft_id):
                raise RuntimeError("registry assignment failed")

        self.panel.fill_draft_name_edit.setText("Rollback Failure Draft")
        with (
            mock.patch.object(
                self.panel,
                "_export_service",
                return_value=AssignmentFailingExportService(),
            ),
            mock.patch.object(
                self.template_service,
                "delete_draft",
                side_effect=RuntimeError("rollback delete failed"),
            ) as delete_draft,
            mock.patch("isrc_manager.contract_templates.dialogs.QMessageBox.warning") as warning,
        ):
            self.assertFalse(self.panel._save_draft(save_as_new=True))

        warning.assert_called_once()
        delete_draft.assert_called_once()
        self.assertIn("registry assignment failed", self.panel.fill_draft_status_label.text())
        retained = self.template_service.list_drafts(revision_id=self.revision.revision_id)
        self.assertEqual(len(retained), 1)
        self.assertEqual(retained[0].name, "Rollback Failure Draft")

    def test_fill_draft_create_and_html_sync_failures_keep_user_in_draft_context(self):
        self._focus_fill()

        class PassingRegistryExportService:
            def validate_draft_registry_generation_for_revision(self, _revision_id):
                return None

            def ensure_registry_assignments_for_draft(self, _draft_id):
                return None

            def synchronize_html_draft(self, _draft_id):
                raise RuntimeError("html copy failed")

        self.panel.fill_draft_name_edit.setText("Create Failure Draft")
        with (
            mock.patch.object(
                self.panel,
                "_export_service",
                return_value=PassingRegistryExportService(),
            ),
            mock.patch.object(
                self.template_service,
                "create_draft",
                side_effect=RuntimeError("database insert failed"),
            ),
            mock.patch("isrc_manager.contract_templates.dialogs.QMessageBox.warning") as warning,
        ):
            self.assertFalse(self.panel._save_draft(save_as_new=True))

        warning.assert_called_once()
        self.assertIn("database insert failed", self.panel.fill_draft_status_label.text())

        self.panel.fill_draft_name_edit.setText("HTML Sync Failure Draft")
        with (
            mock.patch.object(
                self.panel,
                "_export_service",
                return_value=PassingRegistryExportService(),
            ),
            mock.patch.object(
                self.template_service,
                "revision_supports_html_working_draft",
                return_value=True,
            ),
            mock.patch("isrc_manager.contract_templates.dialogs.QMessageBox.warning") as warning,
        ):
            self.assertFalse(self.panel._save_draft(save_as_new=True))

        warning.assert_called_once()
        self.assertIn("HTML preview copy", self.panel.fill_draft_status_label.text())
        drafts = self.template_service.list_drafts(revision_id=self.revision.revision_id)
        self.assertEqual(drafts[-1].name, "HTML Sync Failure Draft")

    def test_fill_draft_load_export_preview_and_open_failure_paths(self):
        self._focus_fill()

        self.panel.load_selected_draft()
        self.assertIn("Select a draft", self.panel.fill_draft_status_label.text())

        self.panel.fill_draft_name_edit.setText("Load Failure Draft")
        self.panel.save_new_draft()
        pump_events(app=self.app, cycles=2)
        draft = self.template_service.list_drafts(revision_id=self.revision.revision_id)[0]
        self.panel._select_combo_data(self.panel.fill_draft_combo, draft.draft_id)

        with (
            mock.patch.object(self.template_service, "fetch_revision", return_value=None),
            mock.patch("isrc_manager.contract_templates.dialogs.QMessageBox.warning") as warning,
        ):
            self.panel.load_selected_draft()

        warning.assert_called_once()
        self.assertIn("Unable to load draft", self.panel.fill_draft_status_label.text())

        with mock.patch.object(self.panel, "_export_service", return_value=None):
            self.panel.export_current_pdf()
        self.assertIn("Open a profile", self.panel.fill_export_status_label.text())

        class FailingPdfExportService:
            def export_draft_to_pdf(self, _draft_id):
                raise RuntimeError("pdf export failed")

        with (
            mock.patch.object(
                self.panel,
                "_export_service",
                return_value=FailingPdfExportService(),
            ),
            mock.patch.object(self.panel, "_ensure_export_draft_record", return_value=draft),
            mock.patch("isrc_manager.contract_templates.dialogs.QMessageBox.warning") as warning,
        ):
            self.panel.export_current_pdf()

        warning.assert_called_once()
        self.assertIn("pdf export failed", self.panel.fill_export_status_label.text())

        fake_pdf_artifact = SimpleNamespace(
            artifact_id=401,
            artifact_type="pdf",
            output_path=str(self.root / "fake-export.pdf"),
        )
        fake_export_result = SimpleNamespace(
            warnings=("watermark missing",),
            pdf_artifact=fake_pdf_artifact,
        )

        class WarningPdfExportService:
            def export_draft_to_pdf(self, _draft_id):
                return fake_export_result

        with (
            mock.patch.object(
                self.panel,
                "_export_service",
                return_value=WarningPdfExportService(),
            ),
            mock.patch.object(self.panel, "_ensure_export_draft_record", return_value=draft),
        ):
            self.panel.export_current_pdf()

        self.assertIn("Warnings: watermark missing", self.panel.fill_export_status_label.text())

        with (
            mock.patch.object(self.panel, "_latest_pdf_artifact_for_draft", return_value=None),
            mock.patch.object(self.panel, "_selected_fill_draft_record", return_value=draft),
        ):
            self.panel.open_latest_pdf_for_current_draft()
        self.assertIn("No retained PDF", self.panel.fill_export_status_label.text())

        with (
            mock.patch.object(
                self.panel,
                "_latest_pdf_artifact_for_draft",
                return_value=fake_pdf_artifact,
            ),
            mock.patch.object(self.panel, "_selected_fill_draft_record", return_value=draft),
            mock.patch(
                "isrc_manager.contract_templates.dialogs.open_external_path",
                return_value=False,
            ) as open_external_path,
        ):
            self.panel.open_latest_pdf_for_current_draft()

        open_external_path.assert_called_once()
        self.assertIn("Could not open", self.panel.fill_export_status_label.text())

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

        self.panel.manual_key_edit.setText("Explicit")
        self.panel.manual_type_combo.setCurrentIndex(self.panel.manual_type_combo.findData("bool"))
        self.panel.manual_options_edit.setText("yes;no;maybe")
        self.panel.manual_indexed_check.setChecked(True)
        pump_events(app=self.app, cycles=2)

        self.assertEqual(
            self.panel.manual_symbol_edit.text(),
            "{{manual.explicit$bool[yes;no;maybe].indexed}}",
        )
        self.panel.copy_manual_symbol()
        self.assertEqual(
            self.app.clipboard().text(),
            "{{manual.explicit$bool[yes;no;maybe].indexed}}",
        )

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

    def test_panel_symbol_generator_exposes_runtime_and_duplicate_cymbols(self):
        self._focus_symbols()
        self.panel.focus_namespace("page")
        self.panel.search_edit.setText("index")
        pump_events(app=self.app, cycles=3)

        page_symbols = {
            self.panel.table.item(row, 4).text() for row in range(self.panel.table.rowCount())
        }
        self.assertIn("{{page.index}}", page_symbols)

        self.panel.search_edit.setText("total")
        pump_events(app=self.app, cycles=3)
        page_total_symbols = {
            self.panel.table.item(row, 4).text() for row in range(self.panel.table.rowCount())
        }
        self.assertIn("{{page.total}}", page_total_symbols)

        self.panel.focus_namespace("current")
        self.panel.search_edit.setText("year")
        pump_events(app=self.app, cycles=3)

        current_symbols = {
            self.panel.table.item(row, 4).text() for row in range(self.panel.table.rowCount())
        }
        self.assertIn("{{current.year}}", current_symbols)

        self.panel.focus_namespace("duplicate")
        self.panel.search_edit.setText("duplicate")
        pump_events(app=self.app, cycles=3)

        duplicate_symbols = {
            self.panel.table.item(row, 4).text() for row in range(self.panel.table.rowCount())
        }
        self.assertTrue(
            {
                "{{duplicate.start}}",
                "{{duplicate.end}}",
                "{{duplicate.number}}",
                "{{db.index}}",
            }
            <= duplicate_symbols
        )

        self.panel.focus_namespace("custom")
        self.panel.search_edit.setText("custom index")
        pump_events(app=self.app, cycles=3)
        custom_symbols = {
            self.panel.table.item(row, 4).text() for row in range(self.panel.table.rowCount())
        }
        self.assertIn("{{custom.index}}", custom_symbols)

    def test_fill_tab_expands_indexed_selectors_from_duplicate_number(self):
        template = self.template_service.create_template(
            ContractTemplatePayload(
                name="Indexed Dialog Template",
                description="Indexed selector dialog coverage",
                template_family="contract",
                source_format="docx",
            )
        )
        source_path = self.root / "indexed-dialog-template.docx"
        source_path.write_bytes(
            make_docx_bytes(
                document_paragraphs=(
                    (
                        "Indexed ",
                        "{{duplicate.start}}",
                        "{{db.index}}",
                        "{{db.track.track_title.indexed}}",
                        "{{duplicate.end}}",
                        "{{duplicate.number}}",
                    ),
                )
            )
        )
        revision = self.template_service.import_revision_from_path(
            template.template_id,
            source_path,
            payload=ContractTemplateRevisionPayload(source_filename=source_path.name),
        ).revision

        self._focus_fill()
        self.panel._select_revision_context(template.template_id, revision.revision_id)
        pump_events(app=self.app, cycles=3)

        title_symbol = "{{db.track.track_title.indexed}}"
        first_key = build_contract_template_indexed_selection_key(title_symbol, 1)
        second_key = build_contract_template_indexed_selection_key(title_symbol, 2)
        self.assertIn(first_key, self.panel.selector_widgets)
        self.assertNotIn(second_key, self.panel.selector_widgets)

        duplicate_widget = self.panel.manual_widgets["{{duplicate.number}}"]
        duplicate_widget.setValue(2)
        pump_events(app=self.app, cycles=3)

        self.assertIn(first_key, self.panel.selector_widgets)
        self.assertIn(second_key, self.panel.selector_widgets)

    def test_fill_tab_expands_indexed_manual_fields_from_duplicate_number(self):
        template = self.template_service.create_template(
            ContractTemplatePayload(
                name="Indexed Manual Dialog Template",
                description="Indexed manual dialog coverage",
                template_family="contract",
                source_format="docx",
            )
        )
        source_path = self.root / "indexed-manual-dialog-template.docx"
        source_path.write_bytes(
            make_docx_bytes(
                document_paragraphs=(
                    (
                        "Indexed ",
                        "{{duplicate.start}}",
                        "{{manual.explicit$bool[yes;no;maybe].indexed}}",
                        "{{duplicate.end}}",
                        "{{duplicate.number}}",
                    ),
                )
            )
        )
        revision = self.template_service.import_revision_from_path(
            template.template_id,
            source_path,
            payload=ContractTemplateRevisionPayload(source_filename=source_path.name),
        ).revision

        self._focus_fill()
        self.panel._select_revision_context(template.template_id, revision.revision_id)
        pump_events(app=self.app, cycles=3)

        explicit_symbol = "{{manual.explicit$bool[yes;no;maybe].indexed}}"
        first_key = build_contract_template_indexed_selection_key(explicit_symbol, 1)
        second_key = build_contract_template_indexed_selection_key(explicit_symbol, 2)
        self.assertIn(first_key, self.panel.manual_widgets)
        self.assertNotIn(second_key, self.panel.manual_widgets)

        duplicate_widget = self.panel.manual_widgets["{{duplicate.number}}"]
        duplicate_widget.setValue(2)
        pump_events(app=self.app, cycles=3)

        self.assertIn(first_key, self.panel.manual_widgets)
        self.assertIn(second_key, self.panel.manual_widgets)
        explicit_widget = self.panel.manual_widgets[first_key]
        self.assertIsInstance(explicit_widget, QComboBox)
        self.assertEqual(
            [explicit_widget.itemData(index) for index in range(1, explicit_widget.count())],
            ["yes", "no", "maybe"],
        )

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
            QToolButton,
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
        selector_combo = self.panel._selector_combo(selector)
        self.assertIsNotNone(selector_combo)
        assert selector_combo is not None
        date_widget = self.panel.manual_widgets["{{manual.license_date}}"]
        draft_date = QDate.currentDate().addDays(1)
        updated_date = draft_date.addDays(6)
        selector_combo.setCurrentIndex(1)
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

    def test_fill_tab_manual_date_supports_custom_output_format(self):
        self._focus_fill()

        date_widget = self.panel.manual_widgets["{{manual.license_date}}"]
        format_widget = self.panel.manual_date_format_widgets["{{manual.license_date}}"]
        date_widget.setDate(QDate(2026, 4, 5))
        format_widget.setText("d.m.yy")
        pump_events(app=self.app, cycles=2)

        self.assertEqual(
            self.panel.current_fill_state(),
            {
                "revision_id": self.revision.revision_id,
                "db_selections": {},
                "manual_values": {"{{manual.license_date}}": "2026-04-05"},
                "type_overrides": {},
                "manual_formats": {"{{manual.license_date}}": "d.m.yy"},
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
        selector_combo = self.panel._selector_combo(selector)
        self.assertIsNotNone(selector_combo)
        assert selector_combo is not None
        date_widget = self.panel.manual_widgets["{{manual.license_date}}"]
        export_date = QDate.currentDate().addDays(4)
        selector_combo.setCurrentIndex(1)
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
            ["pdf", "resolved_docx", "resolved_html"],
        )
        pdf_artifact = next(artifact for artifact in artifacts if artifact.artifact_type == "pdf")
        self.assertTrue(Path(pdf_artifact.output_path).exists())
        self.assertEqual(len(self.pages_adapter.pdf_calls), 0)
        self.assertEqual(len(self.html_adapter.calls), 0)
        self.assertIn("Exported PDF", self.panel.fill_export_status_label.text())
        self.assertIn(str(pdf_artifact.output_path), self.panel.fill_export_status_label.text())

    def test_fill_tab_renders_preview_for_docx_revision_via_html_working_draft(self):
        self._focus_fill()

        selector = self.panel.selector_widgets["{{db.track.track_title}}"]
        selector_combo = self.panel._selector_combo(selector)
        self.assertIsNotNone(selector_combo)
        assert selector_combo is not None
        date_widget = self.panel.manual_widgets["{{manual.license_date}}"]
        selector_combo.setCurrentIndex(1)
        date_widget.setDate(QDate(2026, 4, 6))
        pump_events(app=self.app, cycles=2)

        self.assertTrue(self.panel.fill_preview_button.isEnabled())
        self.panel.refresh_current_html_preview()
        pump_events(app=self.app, cycles=5)

        self.assertIsNotNone(self.panel.fill_html_preview_view)
        wait_for(
            lambda: bool(self.panel.fill_html_preview_view.url().toLocalFile()),
            timeout_ms=5000,
            app=self.app,
            description="DOCX-derived HTML preview URL to load",
        )
        wait_for(
            lambda: "Previewing current HTML draft state"
            in self.panel.fill_preview_status_label.text(),
            timeout_ms=5000,
            app=self.app,
            description="DOCX-derived HTML preview status to settle",
        )

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
        selector_combo = self.panel._selector_combo(selector)
        self.assertIsNotNone(selector_combo)
        assert selector_combo is not None
        date_widget = self.panel.manual_widgets["{{manual.license_date}}"]
        admin_export_date = QDate.currentDate().addDays(7)
        selector_combo.setCurrentIndex(1)
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
        selector_combo = self.panel._selector_combo(selector)
        self.assertIsNotNone(selector_combo)
        assert selector_combo is not None
        is_exclusive = self.panel.manual_widgets["{{manual.is_exclusive}}"]
        royalty_share = self.panel.manual_widgets["{{manual.royalty_share}}"]

        selector_combo.setCurrentIndex(1)
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
        self.assertTrue(
            bool(preview_dock.features() & QDockWidget.DockWidgetFeature.DockWidgetFloatable),
        )
        self.assertTrue(
            bool(revision_dock.features() & QDockWidget.DockWidgetFeature.DockWidgetFloatable),
        )
        host.float_dock(preview_dock)
        pump_events(app=self.app, cycles=2)
        self.assertTrue(preview_dock.isFloating())
        host.move_dock_to_area(preview_dock, Qt.RightDockWidgetArea)
        pump_events(app=self.app, cycles=2)
        self.assertFalse(preview_dock.isFloating())
        host.float_dock(revision_dock)
        pump_events(app=self.app, cycles=2)
        self.assertTrue(revision_dock.isFloating())
        revision_dock.setFloating(False)
        host.set_locked(True)

    def test_fill_workspace_docking_back_left_does_not_leave_empty_right_gap(self):
        self._focus_fill()
        host = self.panel._tab_hosts["fill"]
        preview_dock = next(
            dock for dock in host._docks if dock.objectName() == "contractTemplateHtmlPreviewDock"
        )

        host.set_locked(False)
        pump_events(app=self.app, cycles=2)

        host.move_dock_to_area(preview_dock, Qt.RightDockWidgetArea)
        pump_events(app=self.app, cycles=3)
        host.move_dock_to_area(preview_dock, Qt.LeftDockWidgetArea)
        pump_events(app=self.app, cycles=3)

        self.assertFalse(host._has_exposed_central_canvas())
        self.assertGreaterEqual(
            preview_dock.geometry().right(),
            host.contentsRect().right() - 12,
        )

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

    def test_fill_title_bar_uses_popup_menu_button_and_live_actions_after_unlock(self):
        host = self._fill_host()
        draft_dock = self._fill_dock("contractTemplateFillDraftWorkspaceDock")
        title_bar = draft_dock.titleBarWidget()

        self.assertIsInstance(title_bar.options_button, QToolButton)
        self.assertEqual(title_bar.options_button.popupMode(), QToolButton.InstantPopup)

        host.set_locked(False)
        pump_events(app=self.app, cycles=3)

        start_area = host.dockWidgetArea(draft_dock)
        title_bar._move_right_action.trigger()
        pump_events(app=self.app, cycles=4)
        self.assertNotEqual(host.dockWidgetArea(draft_dock), start_area)

        title_bar._hide_action.trigger()
        pump_events(app=self.app, cycles=4)
        self.assertFalse(draft_dock.isVisible())

        draft_dock.toggleViewAction().trigger()
        pump_events(app=self.app, cycles=4)
        self.assertTrue(draft_dock.isVisible())

    def test_fill_panels_button_uses_themed_dock_control_role(self):
        host = self._fill_host()

        self.assertEqual(host.panels_button.property("role"), "dockControlButton")
        self.assertEqual(host.panels_button.popupMode(), QToolButton.InstantPopup)

    def test_restored_fill_title_bar_actions_stay_bound_to_live_host(self):
        self._focus_fill()
        saved_state = self.panel.capture_layout_state()

        restored_panel = ContractTemplateWorkspacePanel(**self._panel_constructor_kwargs())
        try:
            restored_panel.show()
            pump_events(app=self.app, cycles=3)
            restored_panel.restore_layout_state(saved_state)
            restored_panel.focus_tab("fill")
            pump_events(app=self.app, cycles=8)

            restored_host = restored_panel._tab_hosts["fill"]
            restored_dock = next(
                dock
                for dock in restored_host._docks
                if dock.objectName() == "contractTemplateFillDraftWorkspaceDock"
            )
            title_bar = restored_dock.titleBarWidget()

            restored_host.set_locked(False)
            pump_events(app=self.app, cycles=4)

            start_area = restored_host.dockWidgetArea(restored_dock)
            title_bar._move_right_action.trigger()
            pump_events(app=self.app, cycles=4)
            self.assertNotEqual(restored_host.dockWidgetArea(restored_dock), start_area)

            title_bar._hide_action.trigger()
            pump_events(app=self.app, cycles=4)
            self.assertFalse(restored_dock.isVisible())

            restored_dock.toggleViewAction().trigger()
            pump_events(app=self.app, cycles=4)
            self.assertTrue(restored_dock.isVisible())
        finally:
            restored_panel.close()
            restored_panel.deleteLater()
            pump_events(app=self.app, cycles=2)

    def test_html_preview_fit_zoom_stays_stable_across_reloads(self):
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

    def test_html_preview_fit_fallbacks_measurement_failures_and_scroll_helpers(self):
        if QWebEngineView is None:
            self.skipTest("Qt WebEngine is unavailable")
        view = _InteractiveHtmlPreviewView()

        class BadMeasuredWidth:
            def __float__(self):
                raise TypeError("bad measured width")

        def prime_fit_request() -> None:
            view._set_zoom_owner("fit")
            view._fit_measure_serial += 1
            view._pending_fit_request_serial = view._fit_measure_serial

        try:
            view.resize(760, 920)
            view._set_zoom_owner("not a real owner")
            self.assertEqual(view._zoom_owner, "manual")

            serial = view._fit_measure_serial
            view._schedule_fit(delay_ms=0)
            self.assertEqual(view._fit_measure_serial, serial)
            self.assertIsNone(view._pending_fit_request_serial)

            with mock.patch.object(view._fit_measure_timer, "start") as timer_start:
                with mock.patch.object(view, "_fallback_document_css_width", return_value=0.0):
                    view._document_css_width = 0.0
                    view._last_fit_percent = 0
                    view.reset_to_fit()
            timer_start.assert_called_once_with(0)

            with mock.patch.object(view, "_fallback_document_css_width", return_value=0.0):
                view._document_css_width = 0.0
                self.assertGreaterEqual(view._fit_zoom_percent(), view._MIN_ZOOM_PERCENT)

            view._set_zoom_owner("manual")
            with mock.patch.object(view.page(), "runJavaScript") as run_javascript:
                view._apply_fit_if_needed(force=True)
                view._finish_fit_transition()
                view._measure_and_apply_fit()
            run_javascript.assert_not_called()

            view._set_zoom_owner("fit")
            view._document_css_width = max(1.0, float(view.contentsRect().width() - 40))
            with (
                mock.patch.object(view, "_emit_zoom_percent_changed") as emit_zoom,
                mock.patch.object(view, "_finish_fit_transition") as finish_transition,
            ):
                view._apply_fit_if_needed(force=False, finalize=True)
            emit_zoom.assert_called_once()
            finish_transition.assert_called_once()

            view._document_css_width = 730.0
            prime_fit_request()
            with (
                mock.patch.object(
                    view.page(),
                    "runJavaScript",
                    side_effect=lambda _script, callback: callback(BadMeasuredWidth()),
                ),
                mock.patch.object(view.page(), "contentsSize", side_effect=RuntimeError("gone")),
                mock.patch.object(view, "_apply_fit_if_needed") as apply_fit,
            ):
                view._measure_and_apply_fit()
            apply_fit.assert_called_once_with(force=True)
            self.assertEqual(view._fit_measure_failures, 0)

            for expected_failures in (1, 2):
                view._document_css_width = 0.0
                prime_fit_request()
                view._fit_measure_failures = expected_failures - 1
                with (
                    mock.patch.object(
                        view.page(),
                        "runJavaScript",
                        side_effect=lambda _script, callback: callback(0),
                    ),
                    mock.patch.object(
                        view.page(), "contentsSize", side_effect=RuntimeError("no size")
                    ),
                ):
                    view._measure_and_apply_fit()
                view._fit_measure_timer.stop()
                if expected_failures == 1:
                    self.assertEqual(view._fit_measure_failures, 1)
                    self.assertEqual(view._zoom_owner, "fit")
                else:
                    self.assertEqual(view._zoom_owner, "viewport")
                    self.assertIsNone(view._pending_fit_request_serial)

            self.assertEqual(
                _InteractiveHtmlPreviewView._zoom_steps_from_event(
                    SimpleNamespace(
                        pixelDelta=lambda: QPoint(80, 10),
                        angleDelta=lambda: QPoint(0, 0),
                    )
                ),
                2,
            )
            self.assertEqual(
                _InteractiveHtmlPreviewView._zoom_steps_from_event(
                    SimpleNamespace(
                        pixelDelta=lambda: QPoint(0, 0),
                        angleDelta=lambda: QPoint(-240, 120),
                    )
                ),
                -2,
            )
            self.assertEqual(
                _InteractiveHtmlPreviewView._zoom_steps_from_event(
                    SimpleNamespace(
                        pixelDelta=lambda: QPoint(0, 0),
                        angleDelta=lambda: QPoint(0, 0),
                    )
                ),
                0,
            )

            with mock.patch.object(view.page(), "runJavaScript") as run_javascript:
                view._scroll_by(12.8, -3.2)
            run_javascript.assert_called_once_with("window.scrollBy(12, -3);")
            view._native_zoom_active = True
            view._reset_native_zoom_state()
            self.assertFalse(view._native_zoom_active)
        finally:
            view._fit_measure_timer.stop()
            view._fit_guard_timer.stop()
            view.close()
            view.deleteLater()
            pump_events(app=self.app, cycles=2)

    def test_fill_preview_dock_rebuilds_live_html_surface_when_floated(self):
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

        self.assertTrue(
            bool(preview_dock.features() & QDockWidget.DockWidgetFeature.DockWidgetFloatable)
        )
        view_before_float = self.panel.fill_html_preview_view
        host.float_dock(preview_dock)
        pump_events(app=self.app, cycles=3)
        self.assertTrue(preview_dock.isFloating())
        self.assertIsNotNone(self.panel.fill_html_preview_view)
        self.assertIsNot(self.panel.fill_html_preview_view, view_before_float)

        view_after_float = self.panel.fill_html_preview_view
        host.move_dock_to_area(preview_dock, Qt.RightDockWidgetArea)
        pump_events(app=self.app, cycles=3)
        self.assertFalse(preview_dock.isFloating())
        self.assertIsNotNone(self.panel.fill_html_preview_view)
        self.assertIsNot(self.panel.fill_html_preview_view, view_after_float)

    def test_fill_preview_title_bar_drag_floats_dock_when_unlocked(self):
        host = self._fill_host()
        preview_dock = self._fill_dock("contractTemplateHtmlPreviewDock")
        title_bar = preview_dock.titleBarWidget()
        self.assertIsNotNone(title_bar)

        host.set_locked(False)
        pump_events(app=self.app, cycles=2)

        press_event = _FakeDockDragEvent(
            QPoint(8, 8),
            button=Qt.LeftButton,
            buttons=Qt.LeftButton,
        )
        move_event = _FakeDockDragEvent(
            QPoint(QApplication.startDragDistance() + 24, 8),
            buttons=Qt.LeftButton,
        )
        title_bar.mousePressEvent(press_event)
        title_bar.mouseMoveEvent(move_event)
        pump_events(app=self.app, cycles=3)

        self.assertTrue(press_event.accepted)
        self.assertTrue(move_event.accepted)
        self.assertTrue(preview_dock.isFloating())

    def test_fill_title_bar_menu_and_drag_guard_edges(self):
        host = self._fill_host()
        preview_dock = self._fill_dock("contractTemplateHtmlPreviewDock")
        title_bar = preview_dock.titleBarWidget()
        self.assertIsNotNone(title_bar)

        host.set_locked(True)
        title_bar._refresh_menu_state()
        self.assertFalse(title_bar._move_left_action.isEnabled())
        self.assertFalse(title_bar._float_action.isEnabled())

        host.set_locked(False)
        preview_dock.setProperty("workspaceAllowFloating", False)
        title_bar._refresh_menu_state()
        self.assertTrue(title_bar._move_left_action.isEnabled())
        self.assertFalse(title_bar._float_action.isEnabled())
        self.assertFalse(title_bar._safe_drag_to_float_enabled())

        preview_dock.setProperty("workspaceAllowFloating", True)
        title_bar._refresh_menu_state()
        self.assertTrue(title_bar._safe_drag_to_float_enabled())

        fallback_event = SimpleNamespace(
            position=lambda: (_ for _ in ()).throw(RuntimeError("bad position")),
            pos=lambda: QPoint(9, 10),
        )
        self.assertEqual(title_bar._event_pos(fallback_event), QPoint(9, 10))

        empty_event = SimpleNamespace(
            position=lambda: (_ for _ in ()).throw(RuntimeError("bad position")),
            pos=lambda: (_ for _ in ()).throw(RuntimeError("bad pos")),
        )
        self.assertEqual(title_bar._event_pos(empty_event), QPoint())

        release_event = _FakeDockDragEvent(QPoint(3, 4), button=Qt.LeftButton)
        title_bar.mouseReleaseEvent(release_event)
        self.assertTrue(release_event.ignored)

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

    def test_reset_to_fit_reuses_last_stable_fit_after_spurious_load_cycle(self):
        if QWebEngineView is None:
            self.skipTest("Qt WebEngine is unavailable")
        view = _InteractiveHtmlPreviewView()
        try:
            view.resize(760, 920)
            view._document_css_width = 820.0
            stable_fit = view._fit_zoom_percent()
            view._last_fit_percent = stable_fit
            view._last_fit_viewport_width = view.contentsRect().width()

            view.set_zoom_percent(stable_fit + 25, user_initiated=True)
            pump_events(app=self.app, cycles=2)
            self.assertGreater(view.current_zoom_percent(), stable_fit)

            view._on_load_started()
            view._on_load_finished(True)
            self.assertEqual(view._document_css_width, 0.0)

            view.reset_to_fit()
            pump_events(app=self.app, cycles=2)

            self.assertFalse(view._fit_measure_timer.isActive())
            self.assertFalse(view._fit_guard_timer.isActive())
            self.assertEqual(view._zoom_owner, "viewport")
            self.assertAlmostEqual(view.current_zoom_percent(), stable_fit, delta=1)
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

    def test_workspace_host_layout_integrity_repairs_scroll_boundary_states(self):
        host = self._fill_host()
        host.resize(1000, 800)
        pump_events(app=self.app, cycles=2)

        with mock.patch.object(host, "centralWidget", return_value=object()):
            self.assertFalse(host._has_exposed_central_canvas())

        original_docks = list(host._docks)
        try:
            host._docks = []
            self.assertFalse(host._has_exposed_central_canvas())
        finally:
            host._docks = original_docks

        central = QWidget(host)
        tiny_central = QWidget(host)
        menu_widget = QWidget(host)
        try:
            central.setGeometry(0, 0, 900, 650)
            tiny_central.setGeometry(0, 0, 80, 80)
            menu_widget.setGeometry(0, 0, 100, 32)
            with (
                mock.patch.object(host, "centralWidget", return_value=tiny_central),
                mock.patch.object(host, "menuWidget", return_value=menu_widget),
            ):
                self.assertFalse(host._has_exposed_central_canvas())
            with (
                mock.patch.object(host, "centralWidget", return_value=central),
                mock.patch.object(host, "menuWidget", return_value=menu_widget),
            ):
                self.assertTrue(host._has_exposed_central_canvas())
        finally:
            central.deleteLater()
            tiny_central.deleteLater()
            menu_widget.deleteLater()

        scroll_dock = QDockWidget("Scroll Repair", host)
        scroll_dock.setObjectName("contractTemplateSyntheticScrollRepairDock")
        scroll = QScrollArea(scroll_dock)
        content = QWidget(scroll)
        content.resize(1, 1)
        scroll.setWidget(content)
        scroll_dock.setWidget(scroll)
        host.addDockWidget(Qt.LeftDockWidgetArea, scroll_dock)
        host._docks.append(scroll_dock)
        try:
            scroll_dock.show()
            content.hide()
            pump_events(app=self.app, cycles=2)
            self.assertTrue(host._repair_visible_scroll_area_contents())
            self.assertTrue(content.isVisible())

            with mock.patch.object(content, "isVisible", side_effect=RuntimeError("deleted")):
                self.assertFalse(host._repair_visible_scroll_area_contents())

            scroll.takeWidget()
            self.assertFalse(host._visible_scroll_area_contents_ready())
            self.assertFalse(host._layout_integrity_ok())
        finally:
            if scroll_dock in host._docks:
                host._docks.remove(scroll_dock)
            scroll_dock.close()
            scroll_dock.deleteLater()
            pump_events(app=self.app, cycles=2)

    def test_workspace_host_layout_recovery_edges_cover_pending_and_normalizer_paths(self):
        host = self._fill_host()
        host.resize(900, 700)
        pump_events(app=self.app, cycles=2)

        host._applying_layout_normalization = True
        try:
            self.assertFalse(host.apply_layout_normalization_if_ready(force=True))
        finally:
            host._applying_layout_normalization = False

        host.set_layout_normalizer(lambda: (_ for _ in ()).throw(RuntimeError("normalize failed")))
        host._layout_normalization_pending = True
        self.assertFalse(host.apply_layout_normalization_if_ready(force=True))
        self.assertTrue(host._layout_normalization_pending)

        host.set_layout_normalizer(lambda: None)
        host._layout_normalization_pending = False
        self.assertFalse(host.apply_layout_normalization_if_ready())

        with mock.patch.object(host, "_layout_ready_for_normalization", return_value=False):
            host._layout_normalization_pending = True
            self.assertFalse(host.apply_layout_normalization_if_ready(force=True))

        normalize_calls: list[str] = []
        host.set_layout_normalizer(lambda: normalize_calls.append("normalized"))
        with (
            mock.patch.object(host, "_layout_ready_for_normalization", return_value=True),
            mock.patch.object(host, "_has_exposed_central_canvas", return_value=False),
            mock.patch.object(
                host,
                "_cache_stable_layout_state_if_ready",
                return_value={"dock_state_b64": ""},
            ) as cache_state,
        ):
            host._layout_normalization_pending = True
            self.assertTrue(host.apply_layout_normalization_if_ready())
        self.assertEqual(normalize_calls, ["normalized"])
        self.assertFalse(host._layout_normalization_pending)
        cache_state.assert_called_once()

        pending_state = host.capture_layout_state()
        host._pending_state = dict(pending_state)
        with mock.patch.object(host, "_layout_restore_ready", return_value=False):
            self.assertEqual(host.capture_layout_state(), pending_state)
        host._pending_state = None

        with mock.patch.object(host, "window", side_effect=RuntimeError("deleted")):
            self.assertFalse(host._transient_restore_churn_active())

        original_layout_version = host._layout_version
        try:
            host._layout_version = 2
            host._pending_state = {"layout_version": 0}
            self.assertFalse(host._pending_state_is_compatible())
            host._pending_state = {"layout_version": 99}
            self.assertFalse(host._pending_state_is_compatible())
            host._pending_state = {
                "layout_version": 2,
                "dock_object_names": ["wrongDock"],
            }
            self.assertFalse(host._pending_state_is_compatible())
        finally:
            host._layout_version = original_layout_version
            host._pending_state = None

    def test_workspace_host_apply_pending_state_handles_missing_visibility_and_restore_errors(self):
        host = self._fill_host()
        host.resize(900, 700)
        pump_events(app=self.app, cycles=2)
        saved_state = host.capture_layout_state()
        pending_state = dict(saved_state)
        pending_state.pop("dock_visibility", None)
        pending_state.pop("dock_object_names", None)
        host._pending_state = pending_state

        with (
            mock.patch.object(host, "_layout_restore_ready", return_value=True),
            mock.patch.object(host.main_window, "restoreState", side_effect=RuntimeError("boom")),
        ):
            host._apply_pending_state_if_ready()

        self.assertIsNone(host._pending_state)
        self.assertTrue(all(action.isEnabled() for action in host.panels_menu.actions()))

    def test_workspace_host_compaction_resize_and_panel_runtime_edge_paths(self):
        original_hosts = dict(self.panel._tab_hosts)
        try:
            self.panel._tab_hosts = {
                key: value
                for key, value in original_hosts.items()
                if key not in {self.panel._IMPORT_TAB_KEY, self.panel._SYMBOLS_TAB_KEY}
            }
            with mock.patch.object(self.panel, "_resize_visible_docks") as resize_docks:
                self.panel._reset_import_workspace_layout()
                self.panel._normalize_import_workspace_layout()
                self.panel._reset_symbol_workspace_layout()
                self.panel._normalize_symbol_workspace_layout()
        finally:
            self.panel._tab_hosts = original_hosts
        resize_docks.assert_not_called()

        window = QMainWindow()
        visible_dock = QDockWidget("Visible", window)
        hidden_dock = QDockWidget("Hidden", window)
        floating_dock = QDockWidget("Floating", window)
        try:
            for dock in (visible_dock, hidden_dock, floating_dock):
                dock.setWidget(QWidget(dock))
                window.addDockWidget(Qt.LeftDockWidgetArea, dock)
            window.show()
            visible_dock.show()
            hidden_dock.hide()
            floating_dock.show()
            floating_dock.setFloating(True)
            pump_events(app=self.app, cycles=2)
            with mock.patch.object(window, "resizeDocks") as resize:
                self.panel._resize_visible_docks(
                    window,
                    [object(), hidden_dock, floating_dock],
                    [10, 20, 30],
                    Qt.Horizontal,
                )
                resize.assert_not_called()
                self.panel._resize_visible_docks(
                    window,
                    [visible_dock, hidden_dock, floating_dock],
                    [0, 20, 30],
                    Qt.Horizontal,
                )
                resize.assert_called_once()
                self.assertEqual(resize.call_args.args[0], [visible_dock])
                self.assertEqual(resize.call_args.args[1], [1])

            before_calls: list[bool] = []
            after_calls: list[bool] = []
            floating_dock._workspace_before_floating_change = before_calls.append
            floating_dock._workspace_after_floating_change = after_calls.append
            self.panel._show_docks(floating_dock)
            self.assertEqual(before_calls, [False])
            self.assertEqual(after_calls, [False])
            self.assertFalse(floating_dock.isFloating())
        finally:
            window.close()
            for dock in (visible_dock, hidden_dock, floating_dock):
                dock.deleteLater()
            window.deleteLater()
            pump_events(app=self.app, cycles=2)

        class ExplodingLayout:
            def __init__(self):
                self.calls = 0

            def removeWidget(self, _view):
                self.calls += 1
                raise RuntimeError("remove failed")

        class ExplodingPreview:
            def __init__(self):
                self.hidden = False
                self.parent_cleared = False
                self.deleted = False

            def hide(self):
                self.hidden = True
                raise RuntimeError("hide failed")

            def setParent(self, _parent):
                self.parent_cleared = True
                raise RuntimeError("parent failed")

            def deleteLater(self):
                self.deleted = True

        class PreviewController:
            def __init__(self):
                self.cleaned = False
                self.deleted = False

            def cleanup(self):
                self.cleaned = True

            def deleteLater(self):
                self.deleted = True

        preview = ExplodingPreview()
        layout = ExplodingLayout()
        controller = PreviewController()
        self.panel.fill_html_preview_view = preview
        self.panel._fill_preview_layout = layout
        self.panel._fill_preview_controller = controller

        self.panel._dispose_fill_html_preview_runtime()

        self.assertIsNone(self.panel.fill_html_preview_view)
        self.assertIsNone(self.panel._fill_preview_controller)
        self.assertEqual(layout.calls, 1)
        self.assertTrue(preview.hidden)
        self.assertTrue(preview.parent_cleared)
        self.assertTrue(preview.deleted)
        self.assertTrue(controller.cleaned)
        self.assertTrue(controller.deleted)

        with mock.patch("isrc_manager.contract_templates.dialogs.QWebEngineView", None):
            self.panel._create_fill_html_preview_view()
            self.assertIsNone(self.panel.fill_html_preview_view)
            self.panel._prepare_fill_html_preview_for_window_transition(True)
            self.panel._finalize_fill_html_preview_after_window_transition(False)

        original_layout = self.panel._fill_preview_layout
        try:
            self.panel._fill_preview_layout = None
            self.panel._create_fill_html_preview_view()
            self.assertIsNone(self.panel.fill_html_preview_view)
        finally:
            self.panel._fill_preview_layout = original_layout

        self.panel.fill_html_preview_view = None
        self.panel._step_fill_html_preview_zoom(25)
        self.panel._fill_preview_rebuild_pending = True
        with mock.patch("isrc_manager.contract_templates.dialogs.QTimer.singleShot") as single_shot:
            self.panel._schedule_fill_html_preview_runtime_rebuild()
        single_shot.assert_not_called()
        self.panel._fill_preview_rebuild_pending = False

        original_host = self.panel._fill_preview_host
        try:
            self.panel._fill_preview_host = None
            self.panel._rebuild_fill_html_preview_runtime()
        finally:
            self.panel._fill_preview_host = original_host

    def test_workspace_host_layout_recovery_and_registration_boundaries(self):
        host = self._fill_host()
        docks = {dock.objectName(): dock for dock in host._docks}
        revision_dock = docks["contractTemplateFillRevisionDock"]
        draft_dock = docks["contractTemplateFillDraftWorkspaceDock"]
        export_dock = docks["contractTemplateFillResolvedExportDock"]
        notes_dock = docks["contractTemplateFillDraftNotesDock"]

        self.assertTrue(host._pending_state_is_compatible())

        original_docks = host._docks
        try:
            host._docks = []
            self.assertFalse(host._has_exposed_central_canvas())
        finally:
            host._docks = original_docks

        small_central = QWidget(host)
        small_central.setGeometry(0, 0, 40, 40)
        with mock.patch.object(host, "centralWidget", return_value=small_central):
            self.assertFalse(host._has_exposed_central_canvas())
        small_central.deleteLater()

        hidden_dock = QDockWidget("Hidden Scroll", host.main_window)
        empty_scroll_dock = QDockWidget("Empty Scroll", host.main_window)
        non_scroll_dock = QDockWidget("Plain", host.main_window)
        try:
            hidden_scroll = QScrollArea(hidden_dock)
            hidden_scroll.setWidget(QWidget(hidden_scroll))
            hidden_dock.setWidget(hidden_scroll)
            hidden_dock.hide()
            empty_scroll_dock.setWidget(QScrollArea(empty_scroll_dock))
            empty_scroll_dock.show()
            non_scroll_dock.setWidget(QWidget(non_scroll_dock))
            non_scroll_dock.show()
            host._docks = [hidden_dock, empty_scroll_dock, non_scroll_dock]
            self.assertFalse(host._repair_visible_scroll_area_contents())
            self.assertFalse(host._visible_scroll_area_contents_ready())
        finally:
            host._docks = original_docks
            for dock in (hidden_dock, empty_scroll_dock, non_scroll_dock):
                dock.deleteLater()

        with mock.patch.object(
            host,
            "_dock_is_recoverably_registered",
            side_effect=lambda dock: dock is not revision_dock,
        ):
            self.assertFalse(host._layout_integrity_ok())
        with mock.patch.object(host, "_has_exposed_central_canvas", return_value=True):
            self.assertFalse(host._layout_integrity_ok())

        reset_calls: list[str] = []
        previous_reset_handler = host._reset_handler
        host._reset_handler = lambda: reset_calls.append("reset")
        try:
            with (
                mock.patch.object(
                    host,
                    "_layout_integrity_ok",
                    side_effect=[False, False, False, False],
                ),
                mock.patch.object(
                    host,
                    "apply_layout_normalization_if_ready",
                    return_value=False,
                ),
                mock.patch.object(
                    host,
                    "_repair_visible_scroll_area_contents",
                    return_value=False,
                ),
                mock.patch.object(
                    host,
                    "_dock_is_recoverably_registered",
                    return_value=True,
                ),
            ):
                host._repair_unrecoverable_restore_state(
                    {dock.objectName(): dock.isVisible() for dock in host._docks}
                )
        finally:
            host._reset_handler = previous_reset_handler
        self.assertEqual(reset_calls, ["reset"])

        stray_dock = QDockWidget("Stray", host.main_window)
        try:
            host._set_dock_floating_state(stray_dock, True)
            self.assertFalse(stray_dock.isFloating())
            before_calls: list[bool] = []
            after_calls: list[bool] = []
            revision_dock._workspace_before_floating_change = before_calls.append
            revision_dock._workspace_after_floating_change = after_calls.append
            host._set_dock_floating_state(revision_dock, revision_dock.isFloating())
            self.assertEqual(before_calls, [])
            self.assertEqual(after_calls, [])
        finally:
            stray_dock.deleteLater()

        with (
            mock.patch.object(host, "dockWidgetArea", side_effect=RuntimeError("area lost")),
            mock.patch.object(host, "_debug_layout_log"),
            mock.patch.object(host, "_refresh_dock_order_hints"),
        ):
            host._on_dock_layout_event(revision_dock)
        for attr_name in (
            "_applying_layout_state",
            "_applying_layout_normalization",
            "_compacting_layout",
        ):
            setattr(host, attr_name, True)
            try:
                host._on_dock_layout_event(revision_dock)
            finally:
                setattr(host, attr_name, False)

        host._rebuild_area_groups(Qt.LeftDockWidgetArea, [])
        host.set_locked(False)
        pump_events(app=self.app, cycles=2)
        host._rebuild_area_groups(
            Qt.LeftDockWidgetArea,
            [[revision_dock, draft_dock], [export_dock, notes_dock]],
        )
        pump_events(app=self.app, cycles=2)
        host.set_locked(True)

    def test_workspace_panel_refresh_selection_and_preview_edge_helpers(self):
        self.assertEqual(self.panel._normalize_tab_key("unknown"), self.panel._IMPORT_TAB_KEY)
        original_tab_pages = dict(self.panel._tab_pages)
        try:
            self.panel._tab_pages = {}
            self.assertEqual(self.panel._current_tab_key(), self.panel._IMPORT_TAB_KEY)
        finally:
            self.panel._tab_pages = original_tab_pages

        with (
            mock.patch.object(self.panel, "refresh_symbol_generator") as refresh_symbols,
            mock.patch.object(self.panel, "refresh_fill_form") as refresh_fill,
            mock.patch.object(self.panel, "refresh_admin_workspace") as refresh_admin,
        ):
            self.panel._refresh_workspace_tab(self.panel._SYMBOLS_TAB_KEY, validate=False)
            self.panel._refresh_workspace_tab(self.panel._FILL_TAB_KEY, validate=False)
            self.panel._refresh_workspace_tab(self.panel._IMPORT_TAB_KEY, validate=False)
        refresh_symbols.assert_called_once()
        refresh_fill.assert_called_once()
        refresh_admin.assert_called_once()

        self.panel._on_workspace_tab_changed(-1)
        self.panel._restoring_layout_state = True
        try:
            with mock.patch.object(self.panel, "_refresh_workspace_tab") as refresh_tab:
                self.panel._on_workspace_tab_changed(self.panel.workspace_tabs.currentIndex())
        finally:
            self.panel._restoring_layout_state = False
        refresh_tab.assert_not_called()

        class FailingValidator:
            def validate_layout_integrity_after_restore(self):
                raise RuntimeError("validator failed")

        original_hosts = dict(self.panel._tab_hosts)
        try:
            self.panel._tab_hosts["failing"] = FailingValidator()
            self.panel.stabilize_layout_after_restore()
        finally:
            self.panel._tab_hosts = original_hosts

        with mock.patch.object(self.panel, "window", side_effect=RuntimeError("deleted")):
            self.panel._notify_layout_state_changed()

        original_hosts = dict(self.panel._tab_hosts)
        try:
            self.panel._tab_hosts.pop(self.panel._SYMBOLS_TAB_KEY, None)
            self.panel.refresh_symbol_generator()
            self.panel._tab_hosts.pop(self.panel._FILL_TAB_KEY, None)
            self.panel.refresh_fill_drafts()
        finally:
            self.panel._tab_hosts = original_hosts

        self._focus_fill()
        with mock.patch.object(self.panel, "_template_service", return_value=None):
            self.panel.refresh_fill_drafts()
        self.assertIn("Choose a revision", self.panel.fill_draft_status_label.text())

        draft, _snapshot, _artifact = self._create_admin_draft_bundle(name="Refresh Draft Edge")
        self._focus_fill()
        self.panel._loaded_draft_id = 999_999
        self.panel._fill_type_overrides = {"{{manual.note}}": "text"}
        self.panel._fill_payload_extras = {"extra": True}
        self.panel.refresh_fill_drafts(selected_draft_id=999_999)
        self.assertIsNone(self.panel._loaded_draft_id)
        self.assertEqual(self.panel._fill_type_overrides, {})
        self.assertEqual(self.panel._fill_payload_extras, {})
        self.assertEqual(self.panel.fill_draft_combo.currentData(), draft.draft_id)

        class PreviewController:
            def __init__(self):
                self.refreshes: list[tuple[str, int]] = []
                self.cleared = False

            def request_refresh(self, *, reason: str, delay_ms: int):
                self.refreshes.append((reason, delay_ms))

            def clear(self):
                self.cleared = True

        preview_controller = PreviewController()
        self.panel._fill_preview_controller = preview_controller
        self.panel.apply_editable_payload(
            {
                "revision_id": self.revision.revision_id,
                "db_selections": {"{{db.track.track_title}}": "1"},
                "manual_values": {"{{duplicate.number}}": "2"},
                "manual_formats": {"{{manual.license_date}}": "d.m.yy"},
            },
            refresh_preview=True,
        )
        self.assertEqual(
            preview_controller.refreshes[-1],
            ("Previewing current HTML draft state.", 0),
        )

        class FakePreviewView:
            def __init__(self):
                self.html: str | None = None

            def setHtml(self, html: str):
                self.html = html

            def hide(self):
                return None

            def setParent(self, _parent):
                return None

            def deleteLater(self):
                return None

        self.panel._fill_preview_controller = None
        self.panel.fill_html_preview_view = FakePreviewView()
        self.panel.clear_html_preview()
        self.assertEqual(self.panel.fill_html_preview_view.html, "")
        self.assertIn("HTML preview becomes available", self.panel.fill_preview_status_label.text())

        self.panel._fill_preview_controller = preview_controller
        self.panel.clear_html_preview()
        self.assertTrue(preview_controller.cleared)
        self.panel._fill_preview_controller = None

        with (
            mock.patch.object(self.panel, "_ensure_export_draft_record", return_value=None),
            mock.patch.object(self.panel, "_export_service", return_value=SimpleNamespace()),
        ):
            self.panel.export_current_pdf()
        self.assertIn("Save or select a draft", self.panel.fill_export_status_label.text())

        self.panel._fill_preview_controller = preview_controller
        with mock.patch("isrc_manager.contract_templates.dialogs.QWebEngineView", None):
            self.panel.refresh_current_html_preview()
        self.assertIn("Qt WebEngine is unavailable", self.panel.fill_preview_status_label.text())
        self.panel._fill_preview_controller = None
        self.panel.fill_html_preview_view = None

        self._focus_symbols()
        self.panel.copy_visible_symbols()
        self.panel._visible_entries = []
        self.panel.copy_selected_symbol()
        self.panel.manual_symbol_edit.clear()
        self.panel.copy_manual_symbol()

        stale_table = QTableWidget(1, 1, self.panel)
        try:
            stale_item = QTableWidgetItem("not-an-id")
            stale_item.setData(Qt.UserRole, "not-an-id")
            stale_table.setItem(0, 0, stale_item)
            stale_table.selectRow(0)
            self.assertIsNone(self.panel._selected_table_id(stale_table))
            stale_item.setData(Qt.UserRole, draft.draft_id)
            self.panel._visible_admin_drafts = []
            self.assertIsNone(self.panel._selected_admin_draft_record())
        finally:
            stale_table.deleteLater()

        with mock.patch(
            "isrc_manager.contract_templates.dialogs.QFileDialog.getOpenFileName",
            return_value=("  ", ""),
        ):
            self.assertIsNone(self.panel._choose_template_source_path(title="Blank"))
        chosen_path = self.root / "chosen.docx"
        with mock.patch(
            "isrc_manager.contract_templates.dialogs.QFileDialog.getOpenFileName",
            return_value=(f"  {chosen_path}  ", ""),
        ):
            self.assertEqual(
                self.panel._choose_template_source_path(title="Chosen"),
                chosen_path,
            )

        with mock.patch.object(self.panel, "refresh_admin_workspace") as refresh_admin:
            self.panel._suspend_admin_updates = True
            self.panel._on_admin_template_changed()
            self.panel._on_admin_revision_changed()
            self.panel._on_admin_draft_changed()
            refresh_admin.assert_not_called()
            self.panel._suspend_admin_updates = False
            self.panel._on_admin_template_changed()
            self.panel._on_admin_revision_changed()
        self.assertEqual(refresh_admin.call_count, 2)

    def test_admin_zip_import_revision_and_delete_success_failure_edges(self):
        self._focus_import()

        class ZipImportService:
            def __init__(self):
                self.created_payloads: list[ContractTemplatePayload] = []
                self.imported_packages: list[tuple[int, Path, ContractTemplateRevisionPayload]] = []
                self.imported_revisions: list[Path] = []
                self.next_template_id = 8800
                self.next_revision_id = 9900

            def create_template(self, payload):
                self.created_payloads.append(payload)
                template = SimpleNamespace(
                    template_id=self.next_template_id,
                    name=payload.name,
                    archived=False,
                )
                self.next_template_id += 1
                return template

            def import_html_package_from_path(self, template_id, source_path, *, payload=None):
                self.imported_packages.append((int(template_id), Path(source_path), payload))
                revision = SimpleNamespace(
                    revision_id=self.next_revision_id,
                    source_format="html",
                    scan_status="scan_ready",
                )
                self.next_revision_id += 1
                return SimpleNamespace(
                    revision=revision,
                    scan_result=SimpleNamespace(scan_status="scan_ready"),
                )

            def import_revision_from_path(self, *_args, **_kwargs):
                self.imported_revisions.append(Path(_args[1]))
                raise AssertionError("ZIP dialog path should use import_html_package_from_path")

        zip_service = ZipImportService()
        package_path = self.root / "dialog-package.zip"
        package_path.write_bytes(b"zip bytes are not opened by this dialog-level test")
        with (
            mock.patch.object(self.panel, "_template_service", return_value=zip_service),
            mock.patch.object(
                self.panel, "_choose_template_source_path", return_value=package_path
            ),
            mock.patch(
                "isrc_manager.contract_templates.dialogs.QInputDialog.getText",
                return_value=("ZIP Import Template", True),
            ),
            mock.patch.object(self.panel, "refresh"),
            mock.patch.object(self.panel, "refresh_admin_workspace") as refresh_admin,
        ):
            self.panel.import_template_from_file()
        self.assertIn("Imported template", self.panel.admin_status_label.text())
        self.assertEqual(zip_service.created_payloads[-1].source_format, "html")
        self.assertEqual(zip_service.imported_packages[-1][1], package_path)
        self.assertEqual(zip_service.imported_packages[-1][2].source_format, "html")
        refresh_admin.assert_called_once_with(
            selected_template_id=8800,
            selected_revision_id=9900,
        )

        revision_package_path = self.root / "dialog-revision-package.zip"
        revision_package_path.write_bytes(b"revision zip")
        selected_template = SimpleNamespace(template_id=7777, name="Selected ZIP Template")
        with (
            mock.patch.object(self.panel, "_template_service", return_value=zip_service),
            mock.patch.object(
                self.panel,
                "_selected_admin_template_record",
                return_value=selected_template,
            ),
            mock.patch.object(
                self.panel,
                "_choose_template_source_path",
                return_value=revision_package_path,
            ),
            mock.patch.object(self.panel, "refresh"),
            mock.patch.object(self.panel, "refresh_admin_workspace") as refresh_admin,
        ):
            self.panel.add_revision_from_file()
        self.assertIn("Added revision", self.panel.admin_status_label.text())
        self.assertEqual(zip_service.imported_packages[-1][0], selected_template.template_id)
        self.assertEqual(zip_service.imported_packages[-1][1], revision_package_path)
        refresh_admin.assert_called_once_with(
            selected_template_id=selected_template.template_id,
            selected_revision_id=9901,
        )

        delete_record_template = self.template_service.create_template(
            ContractTemplatePayload(
                name="Record Only Delete",
                template_family="contract",
                source_format="docx",
            )
        )
        self.panel.refresh_admin_workspace(selected_template_id=delete_record_template.template_id)
        self._select_admin_template(delete_record_template.template_id)
        with mock.patch(
            "isrc_manager.contract_templates.dialogs._confirm_destructive_action",
            return_value=True,
        ):
            self.panel.delete_selected_template_record()
        self.assertIn("Deleted the database record", self.panel.admin_status_label.text())
        self.assertIsNone(self.template_service.fetch_template(delete_record_template.template_id))

        imported = self.template_service.create_template(
            ContractTemplatePayload(
                name="Delete With Files Failure",
                template_family="contract",
                source_format="docx",
            )
        )
        self._select_admin_template(imported.template_id)
        with (
            mock.patch(
                "isrc_manager.contract_templates.dialogs._confirm_destructive_action",
                return_value=True,
            ),
            mock.patch.object(
                self.template_service,
                "delete_template",
                side_effect=RuntimeError("managed file cleanup failed"),
            ),
            mock.patch("isrc_manager.contract_templates.dialogs.QMessageBox.warning") as warning,
        ):
            self.panel.delete_selected_template_with_files()
        warning.assert_called_once()
        self.assertIn("Unable to delete template and files", self.panel.admin_status_label.text())

        draft = self.template_service.create_draft(
            ContractTemplateDraftPayload(
                revision_id=self.revision.revision_id,
                name="Delete With Files",
                editable_payload={
                    "revision_id": self.revision.revision_id,
                    "db_selections": {},
                    "manual_values": {},
                    "type_overrides": {},
                },
                storage_mode="database",
            )
        )
        self.panel.refresh_admin_workspace(
            selected_template_id=self.revision.template_id,
            selected_draft_id=draft.draft_id,
        )
        with (
            mock.patch(
                "isrc_manager.contract_templates.dialogs._confirm_destructive_action",
                return_value=True,
            ),
            mock.patch("isrc_manager.contract_templates.dialogs.QMessageBox.warning") as warning,
        ):
            self.panel.delete_selected_draft_with_files()
        warning.assert_not_called()
        self.assertIn("Deleted draft", self.panel.admin_status_label.text())
        self.assertIsNone(self.template_service.fetch_draft(draft.draft_id))

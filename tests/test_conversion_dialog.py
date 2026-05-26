import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

try:
    from PySide6.QtCore import QSettings, Qt
    from PySide6.QtWidgets import (
        QApplication,
        QComboBox,
        QDialog,
        QFileDialog,
        QLineEdit,
        QMessageBox,
        QScrollArea,
    )
except ImportError as exc:  # pragma: no cover - environment-specific fallback
    QApplication = None
    QComboBox = None
    QDialog = None
    QFileDialog = None
    QLineEdit = None
    QMessageBox = None
    QScrollArea = None
    QSettings = None
    Qt = None
    QT_IMPORT_ERROR = exc
else:
    QT_IMPORT_ERROR = None

from isrc_manager.conversion import (
    ConversionService,
    ConversionTemplateStoreService,
    SavedConversionTemplateRecord,
)
from isrc_manager.conversion.dialogs import ConversionDialog
from isrc_manager.conversion.models import (
    MAPPING_KIND_CONSTANT,
    MAPPING_KIND_SOURCE,
    ConversionMappingEntry,
)
from isrc_manager.selection_scope import TrackChoice


class _FakeExchangeService:
    def __init__(self):
        self.calls = []

    def export_rows(self, track_ids):
        normalized = list(track_ids or [])
        self.calls.append(normalized)
        return (
            ["track_id", "track_title", "catalog_number"],
            [
                {
                    "track_id": track_id,
                    "track_title": f"Track {track_id}",
                    "catalog_number": f"CAT-{track_id}",
                }
                for track_id in normalized
            ],
        )


class _FakeSettingsReadService:
    def __init__(self, *, sena_number="", owner_values=None):
        self.sena_number = sena_number
        self.owner_values = dict(owner_values or {})

    def load_sena_number(self):
        return self.sena_number

    def load_owner_party_settings(self):
        return SimpleNamespace(**self.owner_values)


class _FakeTemplateStoreService:
    def __init__(
        self,
        *,
        records=(),
        list_error: Exception | None = None,
        load_result=None,
        load_error: Exception | None = None,
        save_error: Exception | None = None,
    ):
        self.records = tuple(records)
        self.list_error = list_error
        self.load_result = load_result
        self.load_error = load_error
        self.save_error = save_error
        self.save_calls = []

    def list_saved_templates(self):
        if self.list_error is not None:
            raise self.list_error
        return self.records

    def load_saved_template(self, template_id):
        if self.load_error is not None:
            raise self.load_error
        if self.load_result is not None:
            return self.load_result
        raise ValueError(f"missing template {template_id}")

    def save_template(self, **kwargs):
        self.save_calls.append(kwargs)
        if self.save_error is not None:
            raise self.save_error
        return SavedConversionTemplateRecord(
            id=42,
            name=str(kwargs.get("name") or ""),
            filename=kwargs["template_profile"].template_path.name,
            format_name=kwargs["template_profile"].format_name,
        )


class ConversionDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if QApplication is None:
            raise unittest.SkipTest(f"PySide6 QtWidgets unavailable: {QT_IMPORT_ERROR}")
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.settings = QSettings(str(self.root / "conversion.ini"), QSettings.IniFormat)
        self.settings.setFallbacksEnabled(False)

    def tearDown(self):
        self.settings.clear()
        self.settings.sync()
        self.tmpdir.cleanup()

    def _write_csv(self, name: str, text: str) -> Path:
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return path

    def _configure_dialog_with_csv(self, dialog: ConversionDialog) -> None:
        template_path = self._write_csv(
            "template.csv",
            "\nCatalog Number*;Title;Year\nTEMPLATE;Sample;2025\n",
        )
        source_path = self._write_csv(
            "source.csv",
            "catalog_number,title,release_date\nCAT-1,Orbit,2025-04-06\nCAT-2,Signal,2024-01-09\n",
        )
        dialog.template_profile = dialog.service.inspect_template(template_path)
        dialog._template_path = str(template_path)
        dialog.template_path_label.setText(str(template_path))
        dialog._populate_scope_combo(
            dialog.template_scope_combo,
            dialog.template_profile.available_scopes,
        )
        dialog.template_scope_row.setVisible(bool(dialog.template_profile.available_scopes))
        dialog._inspect_source_file(str(source_path))

    def test_dialog_disables_database_mode_without_profile_and_exposes_theme_hooks(self):
        dialog = ConversionDialog(
            service=ConversionService(),
            settings=self.settings,
            export_callback=lambda preview, path: None,
            exports_dir=self.root,
            profile_available=False,
            parent=None,
        )
        try:
            model_item = dialog.source_mode_combo.model().item(1)
            self.assertIsNotNone(model_item)
            self.assertFalse(model_item.isEnabled())
            self.assertEqual(dialog.content_tabs.objectName(), "conversionTabs")
            self.assertEqual(dialog.mapping_table.objectName(), "conversionMappingTable")
            self.assertEqual(dialog.output_table.objectName(), "conversionOutputTable")
            self.assertEqual(dialog.xml_preview_edit.objectName(), "conversionXmlPreview")
            self.assertIsInstance(dialog.main_scroll_area, QScrollArea)
            self.assertIs(dialog.main_scroll_area.widget(), dialog.scroll_content)
            self.assertEqual(dialog.main_scroll_area.property("role"), "workspaceCanvas")
            self.assertEqual(dialog.scroll_content.property("role"), "workspaceCanvas")
            self.assertEqual(dialog.content_tabs.tabText(0), "Setup")
            self.assertEqual(dialog.content_tabs.tabText(1), "Template")
            self.assertEqual(dialog.template_setup_box.title(), "Target Template")
            self.assertEqual(dialog.saved_template_section_box.title(), "Profile Template Library")
            self.assertEqual(dialog.source_setup_box.title(), "Source Data")
            self.assertEqual(
                [
                    dialog.content_tabs.widget(index).property("role")
                    for index in range(dialog.content_tabs.count())
                ],
                [
                    "workspaceCanvas",
                    "workspaceCanvas",
                    "workspaceCanvas",
                    "workspaceCanvas",
                    "workspaceCanvas",
                ],
            )
            self.assertLessEqual(dialog.saved_template_combo.maximumWidth(), 300)
            self.assertLessEqual(dialog.source_mode_combo.maximumWidth(), 300)
            self.assertEqual(
                dialog.saved_template_load_row.maximumWidth(),
                dialog.saved_template_save_row.maximumWidth(),
            )
            self.assertEqual(
                dialog.saved_template_load_row.maximumWidth(),
                dialog.source_mode_control_row.maximumWidth(),
            )
        finally:
            dialog.close()

    def test_dialog_updates_preview_when_source_rows_are_toggled(self):
        captured_exports = []
        dialog = ConversionDialog(
            service=ConversionService(),
            settings=self.settings,
            export_callback=lambda preview, path: captured_exports.append((preview, path)),
            exports_dir=self.root,
            profile_available=False,
            parent=None,
        )
        try:
            self._configure_dialog_with_csv(dialog)
            self.assertIsNotNone(dialog.preview)
            self.assertEqual(dialog.output_table.rowCount(), 2)

            use_item = dialog.source_table.item(1, 0)
            self.assertIsNotNone(use_item)
            use_item.setCheckState(Qt.Unchecked)
            self.app.processEvents()

            self.assertEqual(dialog.output_table.rowCount(), 1)
            self.assertEqual(tuple(dialog.preview.included_row_indices), (0,))
        finally:
            dialog.close()

    def test_dialog_mapping_override_and_export_callback_use_current_preview(self):
        captured_exports = []
        dialog = ConversionDialog(
            service=ConversionService(),
            settings=self.settings,
            export_callback=lambda preview, path: captured_exports.append((preview, path)),
            exports_dir=self.root,
            profile_available=False,
            parent=None,
        )
        try:
            self._configure_dialog_with_csv(dialog)
            year_row = next(
                row
                for row in range(dialog.mapping_table.rowCount())
                if dialog.mapping_table.item(row, 0).text() == "Year"
            )
            map_combo = dialog.mapping_table.cellWidget(year_row, 2)
            constant_edit = dialog.mapping_table.cellWidget(year_row, 3)
            self.assertIsInstance(map_combo, QComboBox)
            self.assertIsInstance(constant_edit, QLineEdit)

            map_combo.setCurrentIndex(map_combo.findData("__conversion_constant__"))
            self.app.processEvents()
            constant_edit = dialog.mapping_table.cellWidget(year_row, 3)
            self.assertIsInstance(constant_edit, QLineEdit)
            constant_edit.setFocus()
            constant_edit.insert("2")
            self.app.processEvents()
            self.assertIs(dialog.mapping_table.cellWidget(year_row, 3), constant_edit)
            constant_edit.insert("030")
            self.app.processEvents()

            self.assertEqual(dialog.output_table.item(0, 2).text(), "2030")

            export_path = self.root / "converted.csv"
            with mock.patch.object(
                QFileDialog,
                "getSaveFileName",
                return_value=("", "CSV Files (*.csv)"),
            ):
                dialog._export_current_preview()
            self.assertEqual(captured_exports, [])

            with mock.patch.object(
                QFileDialog,
                "getSaveFileName",
                return_value=(str(export_path), "CSV Files (*.csv)"),
            ):
                dialog._export_current_preview()

            self.assertEqual(len(captured_exports), 1)
            preview, path = captured_exports[0]
            self.assertEqual(Path(path), export_path)
            self.assertEqual(preview.rendered_rows[0][2], "2030")
        finally:
            dialog.close()

    def test_file_picker_cancel_and_inspection_failures_preserve_dialog_state(self):
        template_path = self._write_csv(
            "picked-template.csv",
            "\nCatalog Number*;Title\nTEMPLATE;Sample\n",
        )
        source_path = self._write_csv("picked-source.csv", "catalog_number,title\nCAT-1,Orbit\n")
        dialog = ConversionDialog(
            service=ConversionService(),
            settings=self.settings,
            export_callback=lambda preview, path: None,
            exports_dir=self.root,
            profile_available=False,
            parent=None,
        )
        try:
            with (
                mock.patch.object(QFileDialog, "getOpenFileName", return_value=("", "")),
                mock.patch.object(
                    dialog.service,
                    "inspect_template",
                    wraps=dialog.service.inspect_template,
                ) as inspect_template,
            ):
                dialog._choose_template()
            inspect_template.assert_not_called()
            self.assertIsNone(dialog.template_profile)
            self.assertEqual(dialog.template_path_label.text(), "No template selected.")

            with (
                mock.patch.object(
                    QFileDialog,
                    "getOpenFileName",
                    return_value=(str(template_path), "CSV Files (*.csv)"),
                ),
                mock.patch.object(
                    dialog.service,
                    "inspect_template",
                    side_effect=ValueError("template cannot be inspected"),
                ),
                mock.patch.object(QMessageBox, "warning", return_value=None) as warning,
            ):
                dialog._choose_template()
            warning.assert_called_once()
            self.assertIn("template cannot be inspected", warning.call_args.args[2])
            self.assertIsNone(dialog.template_profile)

            with mock.patch.object(
                QFileDialog,
                "getOpenFileName",
                return_value=(str(template_path), "CSV Files (*.csv)"),
            ):
                dialog._choose_template()
            self.assertIsNotNone(dialog.template_profile)
            self.assertEqual(dialog.saved_template_name_edit.text(), template_path.stem)
            self.assertEqual(dialog.template_path_label.toolTip(), str(template_path))

            with (
                mock.patch.object(QFileDialog, "getOpenFileName", return_value=("", "")),
                mock.patch.object(dialog, "_inspect_source_file") as inspect_source,
            ):
                dialog._choose_source_file()
            inspect_source.assert_not_called()
            self.assertIsNone(dialog.source_profile)

            with (
                mock.patch.object(
                    QFileDialog,
                    "getOpenFileName",
                    return_value=(str(source_path), "CSV Files (*.csv)"),
                ),
                mock.patch.object(
                    dialog.service,
                    "inspect_source_file",
                    side_effect=ValueError("source cannot be inspected"),
                ),
                mock.patch.object(QMessageBox, "warning", return_value=None) as warning,
            ):
                dialog._choose_source_file()
            warning.assert_called_once()
            self.assertIn("source cannot be inspected", warning.call_args.args[2])
            self.assertIsNone(dialog.source_profile)
        finally:
            dialog.close()

    def test_csv_delimiter_validation_blocks_invalid_custom_values_and_recovers(self):
        dialog = ConversionDialog(
            service=ConversionService(),
            settings=self.settings,
            export_callback=lambda preview, path: None,
            exports_dir=self.root,
            profile_available=False,
            parent=None,
        )
        try:
            self._configure_dialog_with_csv(dialog)
            custom_index = dialog.csv_delimiter_combo.findData("custom")
            self.assertGreaterEqual(custom_index, 0)
            dialog.csv_delimiter_combo.setCurrentIndex(custom_index)

            dialog.csv_custom_delimiter_edit.blockSignals(True)
            dialog.csv_custom_delimiter_edit.setText("||")
            dialog.csv_custom_delimiter_edit.blockSignals(False)
            dialog._on_csv_delimiter_changed()
            self.assertIn("exactly one character", dialog.csv_error_label.text())
            self.assertFalse(dialog.export_button.isEnabled())

            dialog.csv_custom_delimiter_edit.blockSignals(True)
            dialog.csv_custom_delimiter_edit.setText("\t")
            dialog.csv_custom_delimiter_edit.blockSignals(False)
            dialog._on_csv_delimiter_changed()
            self.assertIn("dedicated Tab option", dialog.csv_error_label.text())
            self.assertFalse(dialog.export_button.isEnabled())

            dialog.csv_custom_delimiter_edit.blockSignals(True)
            dialog.csv_custom_delimiter_edit.setText("|")
            dialog.csv_custom_delimiter_edit.blockSignals(False)
            with mock.patch.object(dialog, "_inspect_source_file") as inspect_source:
                dialog._on_csv_delimiter_changed()
            self.assertEqual(dialog.csv_error_label.text(), "")
            inspect_source.assert_called_once_with(dialog._source_path)
        finally:
            dialog.close()

    def test_database_source_noops_failures_and_track_choice_fallbacks_are_safe(self):
        exchange_service = _FakeExchangeService()
        choices = [
            SimpleNamespace(track_id=9, title="", subtitle="Recovered subtitle"),
            SimpleNamespace(track_id=0, title="Ignored", subtitle=""),
        ]
        dialog = ConversionDialog(
            service=ConversionService(exchange_service=exchange_service),
            settings=self.settings,
            export_callback=lambda preview, path: None,
            exports_dir=self.root,
            profile_available=True,
            default_database_track_ids_provider=lambda: (_ for _ in ()).throw(
                RuntimeError("selection unavailable")
            ),
            track_choices_provider=lambda: choices,
            parent=None,
        )
        try:
            self.assertEqual([choice.track_id for choice in dialog._available_track_choices], [9])
            self.assertEqual(dialog._track_title_by_id[9], "Track 9")
            dialog.source_mode_combo.setCurrentIndex(
                dialog.source_mode_combo.findData("database_tracks")
            )
            self.app.processEvents()
            self.assertIsNone(dialog.source_profile)
            self.assertIn("No tracks selected yet", dialog.selection_banner.preview_label.text())

            dialog.default_database_track_ids_provider = lambda: [7]
            with (
                mock.patch.object(
                    dialog.service,
                    "inspect_database_tracks",
                    side_effect=ValueError("database source failed"),
                ),
                mock.patch.object(QMessageBox, "warning", return_value=None) as warning,
            ):
                dialog._load_database_source()
            warning.assert_called_once()
            self.assertIn("database source failed", warning.call_args.args[2])

            chooser_instance = mock.Mock()
            chooser_instance.exec.return_value = QDialog.Rejected
            with mock.patch(
                "isrc_manager.conversion.dialogs.TrackSelectionChooserDialog",
                return_value=chooser_instance,
            ):
                dialog._choose_database_tracks()
            self.assertFalse(dialog._database_override_active)
            chooser_instance.close.assert_called_once_with()
        finally:
            dialog.close()

    def test_database_mode_uses_selection_banner_and_track_chooser_override(self):
        exchange_service = _FakeExchangeService()
        settings_read_service = _FakeSettingsReadService(
            sena_number="SENA-445566",
            owner_values={
                "party_id": 41,
                "legal_name": "Aeon Cosmowyn Records B.V.",
                "company_name": "Cosmowyn Records",
                "display_name": "Cosmowyn Records",
                "email": "hello@cosmowyn.test",
            },
        )
        service = ConversionService(
            exchange_service=exchange_service,
            settings_read_service=settings_read_service,
        )
        choices = [
            TrackChoice(track_id=7, title="Orbit", subtitle="Artist / Album"),
            TrackChoice(track_id=8, title="Signal", subtitle="Artist / Album"),
        ]
        dialog = ConversionDialog(
            service=service,
            settings=self.settings,
            export_callback=lambda preview, path: None,
            exports_dir=self.root,
            profile_available=True,
            default_database_track_ids_provider=lambda: [7],
            track_choices_provider=lambda: choices,
            parent=None,
        )
        try:
            dialog.source_mode_combo.setCurrentIndex(
                dialog.source_mode_combo.findData("database_tracks")
            )
            self.app.processEvents()

            self.assertEqual(exchange_service.calls[0], [7])
            self.assertEqual(dialog.source_table.rowCount(), 1)
            self.assertIn("Orbit", dialog.selection_banner.preview_label.text())
            self.assertIsNotNone(dialog.source_profile)
            self.assertIn("pro_number", dialog.source_profile.headers)
            self.assertIn("owner_legal_name", dialog.source_profile.headers)
            self.assertIn("owner_company_name", dialog.source_profile.headers)
            self.assertEqual(dialog.source_profile.rows[0]["pro_number"], "SENA-445566")
            self.assertEqual(
                dialog.source_profile.rows[0]["owner_legal_name"],
                "Aeon Cosmowyn Records B.V.",
            )
            self.assertEqual(
                dialog.source_profile.rows[0]["owner_company_name"],
                "Cosmowyn Records",
            )

            chooser_instance = mock.Mock()
            chooser_instance.exec.return_value = QDialog.Accepted
            chooser_instance.selected_track_ids.return_value = [8]
            with mock.patch(
                "isrc_manager.conversion.dialogs.TrackSelectionChooserDialog",
                return_value=chooser_instance,
            ):
                dialog._choose_database_tracks()
                self.app.processEvents()

            self.assertEqual(exchange_service.calls[-1], [8])
            self.assertIn("Signal", dialog.selection_banner.preview_label.text())
            chooser_instance.close.assert_called_once_with()
        finally:
            dialog.close()

    def test_database_mode_exposes_owner_fields_in_mapping_dropdown(self):
        exchange_service = _FakeExchangeService()
        settings_read_service = _FakeSettingsReadService(
            sena_number="SENA-445566",
            owner_values={
                "legal_name": "Aeon Cosmowyn Records B.V.",
                "company_name": "Cosmowyn Records",
            },
        )
        dialog = ConversionDialog(
            service=ConversionService(
                exchange_service=exchange_service,
                settings_read_service=settings_read_service,
            ),
            settings=self.settings,
            export_callback=lambda preview, path: None,
            exports_dir=self.root,
            profile_available=True,
            default_database_track_ids_provider=lambda: [7],
            track_choices_provider=lambda: [TrackChoice(track_id=7, title="Orbit")],
            parent=None,
        )
        try:
            template_path = self._write_csv(
                "owner-template.csv",
                "Legal Name,Company Name,Track Title\nSample Legal,Sample Company,Sample Title\n",
            )
            dialog.template_profile = dialog.service.inspect_template(template_path)
            dialog._template_path = str(template_path)
            dialog.template_path_label.setText(str(template_path))
            dialog.source_mode_combo.setCurrentIndex(
                dialog.source_mode_combo.findData("database_tracks")
            )
            self.app.processEvents()

            legal_name_row = next(
                row
                for row in range(dialog.mapping_table.rowCount())
                if dialog.mapping_table.item(row, 0).text() == "Legal Name"
            )
            map_combo = dialog.mapping_table.cellWidget(legal_name_row, 2)
            self.assertIsInstance(map_combo, QComboBox)
            self.assertGreaterEqual(map_combo.findData("owner_legal_name"), 0)
            self.assertGreaterEqual(map_combo.findData("owner_company_name"), 0)
            self.assertEqual(map_combo.currentData(), "owner_legal_name")
        finally:
            dialog.close()

    def test_dialog_map_to_combo_supports_skip_for_optional_fields(self):
        dialog = ConversionDialog(
            service=ConversionService(),
            settings=self.settings,
            export_callback=lambda preview, path: None,
            exports_dir=self.root,
            profile_available=False,
            parent=None,
        )
        try:
            self._configure_dialog_with_csv(dialog)
            year_row = next(
                row
                for row in range(dialog.mapping_table.rowCount())
                if dialog.mapping_table.item(row, 0).text() == "Year"
            )
            map_combo = dialog.mapping_table.cellWidget(year_row, 2)
            self.assertIsInstance(map_combo, QComboBox)
            self.assertGreaterEqual(map_combo.findData("__conversion_skip__"), 0)

            map_combo.setCurrentIndex(map_combo.findData("__conversion_skip__"))
            self.app.processEvents()

            self.assertIsNotNone(dialog.preview)
            self.assertFalse(dialog.preview.blocking_issues)
            self.assertEqual(dialog.preview.mapping_entries[year_row].status, "skipped")
            self.assertNotIn("Year", dialog.output_status_label.text())
        finally:
            dialog.close()

    def test_dialog_can_save_template_to_profile_and_reload_mapping(self):
        conn = sqlite3.connect(":memory:")
        try:
            template_store_service = ConversionTemplateStoreService(conn)
            template_path = self._write_csv(
                "template.csv",
                "\nCatalog Number*;Title;Year\nTEMPLATE;Sample;2025\n",
            )
            source_path = self._write_csv(
                "source.csv",
                "catalog_number,title,release_date\nCAT-1,Orbit,2025-04-06\n",
            )
            dialog = ConversionDialog(
                service=ConversionService(),
                settings=self.settings,
                template_store_service=template_store_service,
                export_callback=lambda preview, path: None,
                exports_dir=self.root,
                profile_available=False,
                parent=None,
            )
            try:
                dialog.template_profile = dialog.service.inspect_template(template_path)
                dialog._template_path = str(template_path)
                dialog.template_path_label.setText(str(template_path))
                dialog._inspect_source_file(str(source_path))
                year_row = next(
                    row
                    for row in range(dialog.mapping_table.rowCount())
                    if dialog.mapping_table.item(row, 0).text() == "Year"
                )
                map_combo = dialog.mapping_table.cellWidget(year_row, 2)
                constant_edit = dialog.mapping_table.cellWidget(year_row, 3)
                self.assertIsInstance(map_combo, QComboBox)
                self.assertIsInstance(constant_edit, QLineEdit)
                map_combo.setCurrentIndex(map_combo.findData("__conversion_constant__"))
                self.app.processEvents()
                constant_edit = dialog.mapping_table.cellWidget(year_row, 3)
                constant_edit.setText("2030")
                dialog.saved_template_name_edit.setText("Producer Export")
                dialog.include_mapping_in_saved_template_checkbox.setChecked(True)
                with mock.patch.object(QMessageBox, "information", return_value=None):
                    dialog._save_template_to_profile()
                self.assertEqual(dialog.saved_template_combo.count(), 1)
            finally:
                dialog.close()

            reload_dialog = ConversionDialog(
                service=ConversionService(),
                settings=self.settings,
                template_store_service=template_store_service,
                export_callback=lambda preview, path: None,
                exports_dir=self.root,
                profile_available=False,
                parent=None,
            )
            try:
                reload_dialog.saved_template_combo.setCurrentIndex(0)
                reload_dialog._load_selected_saved_template()
                self.assertIn("Saved in profile", reload_dialog.template_path_label.text())

                reload_dialog._inspect_source_file(str(source_path))
                self.app.processEvents()

                year_row = next(
                    row
                    for row in range(reload_dialog.mapping_table.rowCount())
                    if reload_dialog.mapping_table.item(row, 0).text() == "Year"
                )
                map_combo = reload_dialog.mapping_table.cellWidget(year_row, 2)
                constant_edit = reload_dialog.mapping_table.cellWidget(year_row, 3)
                self.assertIsInstance(map_combo, QComboBox)
                self.assertIsInstance(constant_edit, QLineEdit)
                self.assertEqual(map_combo.currentData(), "__conversion_constant__")
                self.assertEqual(constant_edit.text(), "2030")
            finally:
                reload_dialog.close()
        finally:
            conn.close()

    def test_saved_template_load_and_save_failures_report_user_visible_messages(self):
        template_path = self._write_csv(
            "profile-template.csv",
            "\nCatalog Number*;Title\nTEMPLATE;Sample\n",
        )
        missing_bytes_record = SavedConversionTemplateRecord(
            id=11,
            name="Broken Profile Template",
            filename="missing-bytes.csv",
            format_name="csv",
            template_bytes=None,
        )
        store = _FakeTemplateStoreService(
            records=(missing_bytes_record,),
            load_result=missing_bytes_record,
            save_error=ValueError("profile database is read-only"),
        )
        dialog = ConversionDialog(
            service=ConversionService(),
            settings=self.settings,
            template_store_service=store,
            export_callback=lambda preview, path: None,
            exports_dir=self.root,
            profile_available=False,
            parent=None,
        )
        try:
            self.assertEqual(dialog.saved_template_combo.count(), 1)
            with mock.patch.object(QMessageBox, "warning", return_value=None) as warning:
                dialog._load_selected_saved_template()
            warning.assert_called_once()
            self.assertIn("missing its stored file bytes", warning.call_args.args[2])
            self.assertIsNone(dialog.template_profile)

            with mock.patch.object(QMessageBox, "information", return_value=None) as information:
                dialog._save_template_to_profile()
            information.assert_called_once()
            self.assertIn("Choose or load a template", information.call_args.args[2])

            dialog.template_profile = dialog.service.inspect_template(template_path)
            with mock.patch.object(QMessageBox, "information", return_value=None) as information:
                dialog._save_template_to_profile()
            information.assert_called_once()
            self.assertIn("Enter a profile template name", information.call_args.args[2])

            dialog.saved_template_name_edit.setText("Read Only Template")
            with mock.patch.object(QMessageBox, "warning", return_value=None) as warning:
                dialog._save_template_to_profile()
            warning.assert_called_once()
            self.assertIn("profile database is read-only", warning.call_args.args[2])
            self.assertEqual(store.save_calls[-1]["name"], "Read Only Template")
        finally:
            dialog.close()

        list_failure_dialog = ConversionDialog(
            service=ConversionService(),
            settings=self.settings,
            template_store_service=_FakeTemplateStoreService(
                list_error=RuntimeError("saved template listing failed")
            ),
            export_callback=lambda preview, path: None,
            exports_dir=self.root,
            profile_available=False,
            parent=None,
        )
        try:
            self.assertEqual(list_failure_dialog.saved_template_combo.count(), 0)
            self.assertFalse(list_failure_dialog.load_saved_template_button.isEnabled())
        finally:
            list_failure_dialog.close()

    def test_mapping_presets_ignore_bad_settings_and_restore_serialized_entries(self):
        dialog = ConversionDialog(
            service=ConversionService(),
            settings=self.settings,
            export_callback=lambda preview, path: None,
            exports_dir=self.root,
            profile_available=False,
            parent=None,
        )
        try:
            self.assertEqual(dialog._preset_payload(), {})
            with mock.patch.object(QMessageBox, "information", return_value=None) as information:
                dialog._save_current_preset()
            information.assert_not_called()

            self._configure_dialog_with_csv(dialog)
            key = dialog._preset_settings_key()
            self.assertIsNotNone(key)
            self.settings.setValue(key, "{")
            self.assertEqual(dialog._preset_payload(), {})
            self.settings.setValue(key, "[]")
            self.assertEqual(dialog._preset_payload(), {})

            with mock.patch.object(QMessageBox, "information", return_value=None) as information:
                dialog._save_current_preset()
            information.assert_called_once()
            self.assertIn("Enter a preset name", information.call_args.args[2])

            year_row = next(
                row
                for row in range(dialog.mapping_table.rowCount())
                if dialog.mapping_table.item(row, 0).text() == "Year"
            )
            map_combo = dialog.mapping_table.cellWidget(year_row, 2)
            constant_edit = dialog.mapping_table.cellWidget(year_row, 3)
            self.assertIsInstance(map_combo, QComboBox)
            self.assertIsInstance(constant_edit, QLineEdit)
            map_combo.setCurrentIndex(map_combo.findData("__conversion_constant__"))
            self.app.processEvents()
            constant_edit = dialog.mapping_table.cellWidget(year_row, 3)
            self.assertIsInstance(constant_edit, QLineEdit)
            constant_edit.setText("2042")
            dialog.preset_name_edit.setText("Constant Year")
            dialog._save_current_preset()
            self.assertEqual(dialog.preset_combo.currentText(), "Constant Year")

            map_combo = dialog.mapping_table.cellWidget(year_row, 2)
            self.assertIsInstance(map_combo, QComboBox)
            map_combo.setCurrentIndex(map_combo.findData("__conversion_skip__"))
            self.app.processEvents()
            self.assertEqual(dialog.preview.mapping_entries[year_row].status, "skipped")

            dialog._load_selected_preset()
            restored_combo = dialog.mapping_table.cellWidget(year_row, 2)
            restored_constant = dialog.mapping_table.cellWidget(year_row, 3)
            self.assertIsInstance(restored_combo, QComboBox)
            self.assertIsInstance(restored_constant, QLineEdit)
            self.assertEqual(restored_combo.currentData(), "__conversion_constant__")
            self.assertEqual(restored_constant.text(), "2042")
        finally:
            dialog.close()

    def test_scope_delimiter_and_database_noop_edges_are_safe(self):
        dialog = ConversionDialog(
            service=ConversionService(),
            settings=self.settings,
            export_callback=lambda preview, path: None,
            exports_dir=self.root,
            profile_available=True,
            parent=None,
        )
        try:
            self.assertEqual(dialog._capture_current_mapping_entries(), {})
            source_entry = ConversionMappingEntry(
                target_field_key="title",
                target_display_name="Title",
                mapping_kind=MAPPING_KIND_SOURCE,
                source_field="title",
            )
            constant_entry = ConversionMappingEntry(
                target_field_key="year",
                target_display_name="Year",
                mapping_kind=MAPPING_KIND_CONSTANT,
                constant_value="2026",
            )
            self.assertFalse(dialog._entry_is_compatible(source_entry))
            self.assertTrue(dialog._entry_is_compatible(constant_entry))

            database_index = dialog.source_mode_combo.findData("database_tracks")
            dialog.source_mode_combo.setCurrentIndex(database_index)
            self.assertIsNone(dialog._requested_csv_delimiter())
            self.assertEqual(dialog._database_default_track_ids(), [])
            self.assertIsNone(dialog.source_profile)

            dialog.profile_available = False
            dialog._load_database_source()
            self.assertIsNone(dialog.source_profile)

            dialog._database_override_active = True
            dialog._database_override_track_ids = [5]
            with mock.patch.object(dialog, "_load_database_source") as load_database_source:
                dialog._clear_database_override()
            self.assertFalse(dialog._database_override_active)
            self.assertEqual(dialog._database_override_track_ids, [])
            load_database_source.assert_called_once_with()

            dialog._populate_scope_combo(dialog.template_scope_combo, (("main", "Main"),))
            self.assertEqual(dialog.template_scope_combo.itemData(0), "main")
            with mock.patch.object(dialog, "_rebuild_session_preview") as rebuild:
                dialog._on_template_scope_changed()
            rebuild.assert_not_called()

            dialog.template_profile = SimpleNamespace(name="template")
            dialog.service.select_template_scope = mock.Mock(
                return_value=SimpleNamespace(name="scoped")
            )
            with mock.patch.object(dialog, "_rebuild_session_preview") as rebuild:
                dialog._on_template_scope_changed()
            dialog.service.select_template_scope.assert_called_once_with(
                dialog.service.select_template_scope.call_args.args[0],
                "main",
            )
            rebuild.assert_called_once_with()

            dialog.source_profile = SimpleNamespace(headers=("title",), available_scopes=())
            dialog.service.select_source_scope = mock.Mock(return_value=SimpleNamespace(rows=[]))
            dialog._populate_scope_combo(dialog.source_scope_combo, (("rows", "Rows"),))
            file_index = dialog.source_mode_combo.findData("file")
            dialog.source_mode_combo.blockSignals(True)
            dialog.source_mode_combo.setCurrentIndex(file_index)
            dialog.source_mode_combo.blockSignals(False)
            dialog.source_profile = SimpleNamespace(headers=("title",), available_scopes=())
            with (
                mock.patch.object(dialog, "_set_default_source_inclusion") as set_default,
                mock.patch.object(dialog, "_rebuild_session_preview") as rebuild,
            ):
                dialog._on_source_scope_changed()
            self.assertIs(dialog._file_source_profile, dialog.source_profile)
            set_default.assert_called_once_with()
            rebuild.assert_called_once_with()

            self.assertEqual(dialog._delimiter_label("\t"), "Tab")
            self.assertEqual(dialog._delimiter_label(";"), "Semicolon (;)")
            self.assertEqual(dialog._delimiter_label("|"), "Pipe (|)")
            self.assertEqual(dialog._delimiter_label(","), "Comma (,)")
            self.assertEqual(dialog._delimiter_label("^"), "^")
        finally:
            dialog.close()

    def test_mapping_feedback_preset_and_export_noops_cover_invalid_table_edges(self):
        callbacks = []
        empty_dialog = ConversionDialog(
            service=ConversionService(),
            settings=self.settings,
            export_callback=lambda preview, path: callbacks.append((preview, path)),
            exports_dir=self.root,
            profile_available=False,
            parent=None,
        )
        try:
            empty_dialog._export_current_preview()
            empty_dialog._apply_suggested_mapping()
            empty_dialog._load_selected_preset()
            self.assertEqual(callbacks, [])
        finally:
            empty_dialog.close()

        dialog = ConversionDialog(
            service=ConversionService(),
            settings=self.settings,
            export_callback=lambda preview, path: callbacks.append((preview, path)),
            exports_dir=self.root,
            profile_available=False,
            parent=None,
        )
        try:
            self._configure_dialog_with_csv(dialog)
            self.assertIsNotNone(dialog.preview)
            self.assertEqual(dialog._preset_payload().get("missing"), None)

            dialog._mapping_table_sync = True
            with mock.patch.object(
                dialog.service, "build_preview", wraps=dialog.service.build_preview
            ) as build:
                dialog._on_mapping_widget_changed("Title")
            build.assert_not_called()
            dialog._mapping_table_sync = False

            year_row = next(
                row
                for row in range(dialog.mapping_table.rowCount())
                if dialog.mapping_table.item(row, 0).text() == "Year"
            )
            map_combo = dialog.mapping_table.cellWidget(year_row, 2)
            self.assertIsInstance(map_combo, QComboBox)
            map_combo.setCurrentIndex(map_combo.findData("__conversion_unmapped__"))
            self.app.processEvents()

            dialog.mapping_table.takeItem(year_row, 5)
            dialog.mapping_table.takeItem(year_row, 6)
            dialog._refresh_mapping_feedback()
            self.assertIsNotNone(dialog.mapping_table.item(year_row, 5))
            self.assertIsNotNone(dialog.mapping_table.item(year_row, 6))

            original_rows = dialog.mapping_table.rowCount()
            dialog.mapping_table.setRowCount(original_rows + 2)
            unknown_item = dialog.mapping_table.item(original_rows + 1, 0)
            if unknown_item is None:
                from PySide6.QtWidgets import QTableWidgetItem

                unknown_item = QTableWidgetItem("Unknown")
                dialog.mapping_table.setItem(original_rows + 1, 0, unknown_item)
            unknown_item.setData(Qt.UserRole, "not-a-target-field")
            collected = dialog._collect_mapping_entries_from_table()
            self.assertTrue(
                all(entry.target_field_key != "not-a-target-field" for entry in collected)
            )
            dialog.mapping_table.setRowCount(original_rows)

            dialog._refresh_mapping_feedback()
            self.assertIsNotNone(dialog.preview)
            dialog._apply_suggested_mapping()
            self.assertIsNotNone(dialog.preview)

            dialog.preset_combo.clear()
            dialog._load_selected_preset()
        finally:
            dialog.close()

    def test_saved_template_load_can_switch_to_database_source_mode_and_return(self):
        template_path = self._write_csv(
            "database-template.csv",
            "Track ID,Title\n1,Sample\n",
        )
        record = SavedConversionTemplateRecord(
            id=31,
            name="Database Template",
            filename=template_path.name,
            format_name="csv",
            template_bytes=template_path.read_bytes(),
            source_mode="database_tracks",
        )
        store = _FakeTemplateStoreService(records=(record,), load_result=record)
        dialog = ConversionDialog(
            service=ConversionService(exchange_service=_FakeExchangeService()),
            settings=self.settings,
            template_store_service=store,
            export_callback=lambda preview, path: None,
            exports_dir=self.root,
            profile_available=True,
            default_database_track_ids_provider=lambda: [7],
            track_choices_provider=lambda: [TrackChoice(track_id=7, title="Orbit")],
            parent=None,
        )
        try:
            self.assertEqual(dialog.source_mode_combo.currentData(), "file")
            dialog._load_selected_saved_template()
            self.assertEqual(dialog.source_mode_combo.currentData(), "database_tracks")
            self.assertEqual(dialog._pending_saved_template_mapping_payload, "")
            self.assertIn("Saved in profile", dialog.template_path_label.text())
        finally:
            dialog.close()


if __name__ == "__main__":
    unittest.main()

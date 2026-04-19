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

from isrc_manager.conversion import ConversionService, ConversionTemplateStoreService
from isrc_manager.conversion.dialogs import ConversionDialog
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
                return_value=(str(export_path), "CSV Files (*.csv)"),
            ):
                dialog._export_current_preview()

            self.assertEqual(len(captured_exports), 1)
            preview, path = captured_exports[0]
            self.assertEqual(Path(path), export_path)
            self.assertEqual(preview.rendered_rows[0][2], "2030")
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


if __name__ == "__main__":
    unittest.main()

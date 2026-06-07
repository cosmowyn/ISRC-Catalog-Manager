import unittest
from unittest import mock

try:
    from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QLabel, QLineEdit, QTabWidget
except ImportError as exc:  # pragma: no cover - environment-specific fallback
    QApplication = None
    QCheckBox = None
    QComboBox = None
    QLabel = None
    QLineEdit = None
    QT_IMPORT_ERROR = exc
else:
    QT_IMPORT_ERROR = None

from isrc_manager.exchange.dialogs import ExchangeImportDialog
from isrc_manager.exchange.models import ExchangeInspection


class _FakeSettings:
    def __init__(self):
        self._values = {}

    def value(self, key, default=None, _type=None):
        return self._values.get(key, default)

    def setValue(self, key, value):
        self._values[key] = value

    def sync(self):
        return None


class ExchangeImportDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if QApplication is None:
            raise unittest.SkipTest(f"PySide6 QtWidgets unavailable: {QT_IMPORT_ERROR}")
        cls.app = QApplication.instance() or QApplication([])

    def test_package_mode_can_default_to_create(self):
        dlg = ExchangeImportDialog(
            inspection=ExchangeInspection(
                file_path="/tmp/catalog.zip",
                format_name="package",
                headers=["track_title", "artist_name"],
                preview_rows=[{"track_title": "Orbit", "artist_name": "Moonwake"}],
                suggested_mapping={"track_title": "track_title", "artist_name": "artist_name"},
            ),
            supported_headers=["track_title", "artist_name"],
            settings=_FakeSettings(),
            initial_mode="create",
        )
        try:
            self.assertEqual(dlg.mode_combo.currentData(), "create")
            self.assertEqual(dlg.import_button.text(), "Import Data")
            self.assertIn("writes rows into the current profile", dlg.mode_hint_label.text())
            self.assertEqual(dlg.property("role"), "panel")
            tabs = dlg.findChild(QTabWidget, "exchangeImportTabs")
            self.assertIsNotNone(tabs)
            self.assertEqual(
                [tabs.tabText(i) for i in range(tabs.count())],
                [
                    "Setup & Mapping",
                    "Source Preview",
                ],
            )
            self.assertEqual(tabs.widget(0).property("role"), "workspaceCanvas")
            self.assertEqual(tabs.widget(1).property("role"), "workspaceCanvas")
            self.assertIsNone(dlg.findChild(QComboBox, "csvDelimiterCombo"))
        finally:
            dlg.close()

    def test_dry_run_mode_uses_validation_label(self):
        dlg = ExchangeImportDialog(
            inspection=ExchangeInspection(
                file_path="/tmp/catalog.json",
                format_name="json",
                headers=["track_title"],
                preview_rows=[{"track_title": "Orbit"}],
                suggested_mapping={"track_title": "track_title"},
            ),
            supported_headers=["track_title"],
            settings=_FakeSettings(),
            initial_mode="dry_run",
        )
        try:
            self.assertEqual(dlg.mode_combo.currentData(), "dry_run")
            self.assertEqual(dlg.import_button.text(), "Run Validation")
            self.assertIn("No rows will be written", dlg.mode_hint_label.text())
            self.assertIsNone(dlg.findChild(QComboBox, "csvDelimiterCombo"))
        finally:
            dlg.close()

    def test_invalid_saved_preferences_and_non_csv_helpers_are_safe(self):
        settings = _FakeSettings()
        settings._values["exchange/import_preferences/json"] = "not json"
        dlg = ExchangeImportDialog(
            inspection=ExchangeInspection(
                file_path="/tmp/catalog.json",
                format_name="json",
                headers=["track_title"],
                preview_rows=[{"track_title": None}],
                suggested_mapping={"track_title": "not_supported"},
            ),
            supported_headers=["track_title"],
            settings=settings,
            initial_mode="not-a-mode",
        )
        try:
            self.assertEqual(dlg.mode_combo.currentData(), "dry_run")
            self.assertEqual(dlg.preview_table.item(0, 0).text(), "")
            self.assertEqual(dlg.resolved_csv_delimiter(), None)
            self.assertEqual(dlg._validate_custom_delimiter(), (None, None))
            self.assertEqual(dlg._requested_csv_delimiter(), (None, None))
            dlg._update_csv_delimiter_widgets()
            dlg._set_csv_delimiter_error("ignored for non-csv")
            self.assertTrue(dlg.import_button.isEnabled())
            self.assertNotIn("csv_delimiter_mode", dlg._current_import_preference_payload())
        finally:
            dlg.close()

        settings._values["exchange/import_preferences/json"] = (
            '{"mode": "not-a-mode", "match_by_internal_id": false, '
            '"match_by_isrc": false, "match_by_upc_title": false, '
            '"heuristic_match": true, "create_missing_custom_fields": false}'
        )
        remembered = ExchangeImportDialog(
            inspection=ExchangeInspection(
                file_path="/tmp/catalog.json",
                format_name="json",
                headers=["track_title"],
                preview_rows=[{"track_title": "Orbit"}],
                suggested_mapping={"track_title": "track_title"},
            ),
            supported_headers=["track_title"],
            settings=settings,
            initial_mode="create",
        )
        try:
            self.assertEqual(remembered.mode_combo.currentData(), "create")
            self.assertFalse(remembered.match_internal_checkbox.isChecked())
            self.assertFalse(remembered.match_isrc_checkbox.isChecked())
            self.assertFalse(remembered.match_upc_title_checkbox.isChecked())
            self.assertTrue(remembered.heuristic_checkbox.isChecked())
            self.assertFalse(remembered.create_custom_checkbox.isChecked())
        finally:
            remembered.close()

    def test_mapping_presets_warn_save_reload_and_ignore_invalid_entries(self):
        settings = _FakeSettings()
        settings._values["exchange/mapping_presets/csv"] = "not json"
        inspection = ExchangeInspection(
            file_path="/tmp/catalog.csv",
            format_name="csv",
            headers=["Source Title", "Source Artist"],
            preview_rows=[{"Source Title": "Orbit", "Source Artist": "Moonwake"}],
            suggested_mapping={"Source Title": "track_title", "Source Artist": "artist_name"},
            resolved_delimiter=",",
        )
        dlg = ExchangeImportDialog(
            inspection=inspection,
            supported_headers=["track_title", "artist_name"],
            settings=settings,
            csv_reinspect_callback=lambda delimiter: inspection,
        )
        try:
            self.assertEqual(dlg.preset_combo.count(), 1)
            with mock.patch("isrc_manager.exchange.dialogs.QMessageBox.warning") as warning:
                dlg._save_preset()
            warning.assert_called_once()

            title_combo = dlg.mapping_table.cellWidget(0, 1)
            artist_combo = dlg.mapping_table.cellWidget(1, 1)
            title_combo.setCurrentIndex(title_combo.findData("artist_name"))
            artist_combo.setCurrentIndex(artist_combo.findData("track_title"))
            dlg.preset_name_edit.setText("Swapped")
            dlg._save_preset()
            self.assertIn('"Swapped"', settings.value("exchange/mapping_presets/csv"))

            title_combo.setCurrentIndex(title_combo.findData("track_title"))
            artist_combo.setCurrentIndex(artist_combo.findData("artist_name"))
            dlg.preset_combo.setCurrentIndex(dlg.preset_combo.findText("Swapped"))
            dlg._load_preset()
            self.assertEqual(dlg.mapping()["Source Title"], "artist_name")
            self.assertEqual(dlg.mapping()["Source Artist"], "track_title")

            settings._values["exchange/mapping_presets/csv"] = '{"Broken": ["not", "a", "dict"]}'
            dlg._reload_presets()
            dlg.preset_combo.setCurrentIndex(dlg.preset_combo.findText("Broken"))
            dlg._load_preset()
            self.assertEqual(dlg.mapping()["Source Title"], "artist_name")

            dlg.preset_combo.setCurrentIndex(0)
            dlg._load_preset()
            self.assertEqual(dlg.mapping()["Source Title"], "artist_name")
        finally:
            dlg.close()

    def test_csv_dialog_refreshes_preview_and_preserves_mapping(self):
        refresh_calls = []
        initial_inspection = ExchangeInspection(
            file_path="/tmp/catalog.csv",
            format_name="csv",
            headers=["source_name"],
            preview_rows=[{"source_name": "Dreamy"}],
            suggested_mapping={"source_name": "custom::Mood"},
            resolved_delimiter=",",
        )

        def _reinspect(delimiter):
            refresh_calls.append(delimiter)
            return ExchangeInspection(
                file_path="/tmp/catalog.csv",
                format_name="csv",
                headers=["source_name", "artist_name"],
                preview_rows=[{"source_name": "Dreamy", "artist_name": "Moonwake"}],
                suggested_mapping={
                    "source_name": "custom::Mood",
                    "artist_name": "artist_name",
                },
                resolved_delimiter=delimiter or ",",
            )

        dlg = ExchangeImportDialog(
            inspection=initial_inspection,
            supported_headers=["track_title", "artist_name", "custom::Mood"],
            settings=_FakeSettings(),
            csv_reinspect_callback=_reinspect,
        )
        try:
            mapping_combo = dlg.mapping_table.cellWidget(0, 1)
            mapping_combo.setCurrentText("custom::Mood")
            delimiter_combo = dlg.findChild(QComboBox, "csvDelimiterCombo")
            self.assertIsNotNone(delimiter_combo)
            delimiter_combo.setCurrentIndex(delimiter_combo.findData(";"))
            self.app.processEvents()

            self.assertEqual(refresh_calls, [";"])
            self.assertEqual(dlg.preview_table.columnCount(), 2)
            self.assertEqual(
                [dlg.preview_table.horizontalHeaderItem(i).text() for i in range(2)],
                ["source_name", "artist_name"],
            )
            self.assertEqual(dlg.mapping()["source_name"], "custom::Mood")
            self.assertEqual(dlg.mapping()["artist_name"], "artist_name")
            self.assertEqual(dlg.resolved_csv_delimiter(), ";")
        finally:
            dlg.close()

    def test_csv_delimiter_paths_without_callback_and_with_callback_errors(self):
        inspection = ExchangeInspection(
            file_path="/tmp/catalog.csv",
            format_name="csv",
            headers=["track_title"],
            preview_rows=[{"track_title": "Orbit"}],
            suggested_mapping={"track_title": "track_title"},
            resolved_delimiter=",",
        )

        no_callback = ExchangeImportDialog(
            inspection=inspection,
            supported_headers=["track_title"],
            settings=_FakeSettings(),
            csv_reinspect_callback=None,
        )
        try:
            delimiter_combo = no_callback.findChild(QComboBox, "csvDelimiterCombo")
            self.assertEqual(no_callback._requested_csv_delimiter(), (None, None))
            self.assertEqual(no_callback._validate_custom_delimiter(), (None, None))
            self.assertEqual(no_callback.resolved_csv_delimiter(), ",")
            delimiter_combo.setCurrentIndex(delimiter_combo.findData("|"))
            self.app.processEvents()
            self.assertTrue(no_callback.import_button.isEnabled())
            self.assertEqual(no_callback.resolved_csv_delimiter(), "|")
            no_callback._set_csv_delimiter_error("  ")
            self.assertTrue(no_callback.import_button.isEnabled())
        finally:
            no_callback.close()

        failing = ExchangeImportDialog(
            inspection=inspection,
            supported_headers=["track_title"],
            settings=_FakeSettings(),
            csv_reinspect_callback=lambda _delimiter: (_ for _ in ()).throw(
                ValueError("delimiter cannot be parsed")
            ),
        )
        try:
            delimiter_combo = failing.findChild(QComboBox, "csvDelimiterCombo")
            error_label = failing.findChild(QLabel, "csvDelimiterErrorLabel")
            delimiter_combo.setCurrentIndex(delimiter_combo.findData(";"))
            self.app.processEvents()
            self.assertFalse(failing.import_button.isEnabled())
            self.assertIn("delimiter cannot be parsed", error_label.text())
        finally:
            failing.close()

    def test_csv_dialog_invalid_custom_delimiter_disables_import(self):
        inspection = ExchangeInspection(
            file_path="/tmp/catalog.csv",
            format_name="csv",
            headers=["track_title", "artist_name"],
            preview_rows=[{"track_title": "Orbit", "artist_name": "Moonwake"}],
            suggested_mapping={"track_title": "track_title", "artist_name": "artist_name"},
            resolved_delimiter=",",
        )

        dlg = ExchangeImportDialog(
            inspection=inspection,
            supported_headers=["track_title", "artist_name", "custom::Mood"],
            settings=_FakeSettings(),
            csv_reinspect_callback=lambda delimiter: inspection,
        )
        try:
            delimiter_combo = dlg.findChild(QComboBox, "csvDelimiterCombo")
            custom_edit = dlg.findChild(QLineEdit, "csvCustomDelimiterEdit")
            error_label = dlg.findChild(QLabel, "csvDelimiterErrorLabel")

            delimiter_combo.setCurrentIndex(delimiter_combo.findData("custom"))
            self.app.processEvents()
            self.assertFalse(dlg.import_button.isEnabled())
            self.assertIn("Enter a custom delimiter", error_label.text())

            custom_edit.setText("||")
            self.app.processEvents()
            self.assertFalse(dlg.import_button.isEnabled())
            self.assertIn("exactly one", error_label.text())

            custom_edit.setText("\t")
            self.app.processEvents()
            self.assertFalse(dlg.import_button.isEnabled())
            self.assertIn("Tab option", error_label.text())

            custom_edit.setText("^")
            self.app.processEvents()
            self.assertTrue(dlg.import_button.isEnabled())
            self.assertEqual(dlg.resolved_csv_delimiter(), "^")
        finally:
            dlg.close()

    def test_csv_dialog_mapping_targets_include_custom_fields_passed_in(self):
        inspection = ExchangeInspection(
            file_path="/tmp/catalog.csv",
            format_name="csv",
            headers=["Mood Source"],
            preview_rows=[{"Mood Source": "Dreamy"}],
            suggested_mapping={"Mood Source": "custom::Mood"},
            resolved_delimiter=",",
        )
        dlg = ExchangeImportDialog(
            inspection=inspection,
            supported_headers=["track_title", "artist_name", "custom::Mood"],
            settings=_FakeSettings(),
            csv_reinspect_callback=lambda delimiter: inspection,
        )
        try:
            delimiter_combo = dlg.findChild(QComboBox, "csvDelimiterCombo")
            self.assertIsNotNone(delimiter_combo)
            mapping_combo = dlg.mapping_table.cellWidget(0, 1)
            items = [mapping_combo.itemText(index) for index in range(mapping_combo.count())]
            self.assertIn("custom::Mood", items)
            self.assertNotIn("custom::Artwork", items)
        finally:
            dlg.close()

    def test_dialog_can_remember_import_choices_per_format(self):
        settings = _FakeSettings()
        inspection = ExchangeInspection(
            file_path="/tmp/catalog.csv",
            format_name="csv",
            headers=["track_title", "artist_name"],
            preview_rows=[{"track_title": "Orbit", "artist_name": "Moonwake"}],
            suggested_mapping={"track_title": "track_title", "artist_name": "artist_name"},
            resolved_delimiter=",",
        )

        def _reinspect(delimiter):
            return ExchangeInspection(
                file_path="/tmp/catalog.csv",
                format_name="csv",
                headers=["track_title", "artist_name"],
                preview_rows=[{"track_title": "Orbit", "artist_name": "Moonwake"}],
                suggested_mapping={
                    "track_title": "track_title",
                    "artist_name": "artist_name",
                },
                resolved_delimiter=delimiter or ",",
            )

        dlg = ExchangeImportDialog(
            inspection=inspection,
            supported_headers=["track_title", "artist_name"],
            settings=settings,
            csv_reinspect_callback=_reinspect,
        )
        try:
            dlg.mode_combo.setCurrentIndex(dlg.mode_combo.findData("merge"))
            dlg.match_internal_checkbox.setChecked(False)
            dlg.match_isrc_checkbox.setChecked(False)
            dlg.heuristic_checkbox.setChecked(True)
            delimiter_combo = dlg.findChild(QComboBox, "csvDelimiterCombo")
            self.assertIsNotNone(delimiter_combo)
            delimiter_combo.setCurrentIndex(delimiter_combo.findData(";"))
            self.app.processEvents()
            dlg.remember_choices_checkbox.setChecked(True)
            dlg.accept()
        finally:
            dlg.close()

        saved = settings.value("exchange/import_preferences/csv")
        self.assertIn('"mode": "merge"', saved)
        self.assertIn('"csv_delimiter_mode": ";"', saved)

        remembered = ExchangeImportDialog(
            inspection=inspection,
            supported_headers=["track_title", "artist_name"],
            settings=settings,
            csv_reinspect_callback=_reinspect,
        )
        try:
            self.assertEqual(remembered.mode_combo.currentData(), "merge")
            self.assertFalse(remembered.match_internal_checkbox.isChecked())
            self.assertFalse(remembered.match_isrc_checkbox.isChecked())
            self.assertTrue(remembered.heuristic_checkbox.isChecked())
            self.assertEqual(remembered.resolved_csv_delimiter(), ";")
        finally:
            remembered.close()

    def test_table_guard_paths_skip_missing_items_and_empty_identifier_values(self):
        inspection = ExchangeInspection(
            file_path="/tmp/catalog.csv",
            format_name="csv",
            headers=["Contract Source", "Ignored Source"],
            preview_rows=[{"Contract Source": "", "Ignored Source": "metadata"}],
            suggested_mapping={
                "Contract Source": "contract_number",
                "Ignored Source": "custom::Ignored",
            },
            resolved_delimiter=",",
        )
        dlg = ExchangeImportDialog(
            inspection=inspection,
            supported_headers=["contract_number", "custom::Ignored"],
            settings=_FakeSettings(),
            csv_reinspect_callback=lambda delimiter: inspection,
        )
        try:
            self.assertEqual(dlg._identifier_review_rows(), [])

            dlg.mapping_table.takeItem(0, 0)
            self.assertNotIn("Contract Source", dlg.mapping())
            self.assertNotIn("Contract Source", dlg.skipped_source_headers())

            assert dlg.identifier_review_table is not None
            dlg.identifier_review_table.setRowCount(1)
            dlg.identifier_review_table.setItem(0, 0, None)
            self.assertEqual(dlg._identifier_overrides(), {})
        finally:
            dlg.close()

    def test_xml_dialog_uses_generic_missing_custom_field_label(self):
        dlg = ExchangeImportDialog(
            inspection=ExchangeInspection(
                file_path="/tmp/catalog.xml",
                format_name="xml",
                headers=["track_title", "artist_name", "custom::Energy"],
                preview_rows=[
                    {
                        "track_title": "Orbit",
                        "artist_name": "Moonwake",
                        "custom::Energy": "High",
                    }
                ],
                suggested_mapping={
                    "track_title": "track_title",
                    "artist_name": "artist_name",
                    "custom::Energy": "custom::Energy",
                },
                warnings=["Detected XML schema: selected."],
            ),
            supported_headers=["track_title", "artist_name", "custom::Energy"],
            settings=_FakeSettings(),
            initial_mode="dry_run",
        )
        try:
            checkbox_texts = [box.text() for box in dlg.findChildren(QCheckBox)]
            self.assertIn("Create missing custom fields", checkbox_texts)
            self.assertNotIn("Create missing text custom fields", checkbox_texts)
        finally:
            dlg.close()

    def test_mapping_can_explicitly_skip_a_source_field(self):
        inspection = ExchangeInspection(
            file_path="/tmp/catalog.csv",
            format_name="csv",
            headers=["track_title", "artist_name", "Mood Source"],
            preview_rows=[
                {
                    "track_title": "Orbit",
                    "artist_name": "Moonwake",
                    "Mood Source": "Dreamy",
                }
            ],
            suggested_mapping={
                "track_title": "track_title",
                "artist_name": "artist_name",
                "Mood Source": "custom::Mood",
            },
            resolved_delimiter=",",
        )
        dlg = ExchangeImportDialog(
            inspection=inspection,
            supported_headers=["track_title", "artist_name", "custom::Mood"],
            settings=_FakeSettings(),
            csv_reinspect_callback=lambda delimiter: inspection,
        )
        try:
            mapping_combo = dlg.mapping_table.cellWidget(2, 1)
            mapping_combo.setCurrentIndex(
                mapping_combo.findData(ExchangeImportDialog.SKIP_MAPPING_TARGET)
            )
            self.assertEqual(
                dlg.mapping(),
                {
                    "track_title": "track_title",
                    "artist_name": "artist_name",
                },
            )
            self.assertEqual(dlg.import_options().skip_targets, ["Mood Source"])
        finally:
            dlg.close()

    def test_identifier_review_tab_collects_staged_override_choices(self):
        inspection = ExchangeInspection(
            file_path="/tmp/catalog.csv",
            format_name="csv",
            headers=["track_title", "artist_name", "Contract Source"],
            preview_rows=[
                {
                    "track_title": "Orbit",
                    "artist_name": "Moonwake",
                    "Contract Source": "CTR-EXTERNAL-9001",
                }
            ],
            suggested_mapping={
                "track_title": "track_title",
                "artist_name": "artist_name",
                "Contract Source": "contract_number",
            },
            resolved_delimiter=",",
        )
        dlg = ExchangeImportDialog(
            inspection=inspection,
            supported_headers=[
                "track_title",
                "artist_name",
                "contract_number",
                "license_number",
                "registry_sha256_key",
            ],
            settings=_FakeSettings(),
            csv_reinspect_callback=lambda delimiter: inspection,
        )
        try:
            tabs = dlg.findChild(QTabWidget, "exchangeImportTabs")
            self.assertIsNotNone(tabs)
            assert tabs is not None
            self.assertIn("Identifier Review", [tabs.tabText(i) for i in range(tabs.count())])
            self.assertIsNotNone(dlg.identifier_review_table)
            assert dlg.identifier_review_table is not None
            self.assertEqual(dlg.identifier_review_table.rowCount(), 1)
            combo = dlg.identifier_review_table.cellWidget(0, 2)
            self.assertIsInstance(combo, QComboBox)
            combo.setCurrentIndex(combo.findData("license_number"))
            overrides = dlg.import_options().identifier_overrides
            self.assertEqual(
                overrides["1|Contract Source|contract_number|CTR-EXTERNAL-9001"],
                "license_number",
            )
        finally:
            dlg.close()


if __name__ == "__main__":
    unittest.main()

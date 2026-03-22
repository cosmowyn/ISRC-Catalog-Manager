import unittest

try:
    from PySide6.QtWidgets import QApplication, QComboBox, QLabel, QLineEdit, QTabWidget
except ImportError as exc:  # pragma: no cover - environment-specific fallback
    QApplication = None
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
                preview_rows=[{"track_title": "Orbit", "artist_name": "Cosmowyn"}],
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
                preview_rows=[{"source_name": "Dreamy", "artist_name": "Cosmowyn"}],
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

    def test_csv_dialog_invalid_custom_delimiter_disables_import(self):
        inspection = ExchangeInspection(
            file_path="/tmp/catalog.csv",
            format_name="csv",
            headers=["track_title", "artist_name"],
            preview_rows=[{"track_title": "Orbit", "artist_name": "Cosmowyn"}],
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
            preview_rows=[{"track_title": "Orbit", "artist_name": "Cosmowyn"}],
            suggested_mapping={"track_title": "track_title", "artist_name": "artist_name"},
            resolved_delimiter=",",
        )

        def _reinspect(delimiter):
            return ExchangeInspection(
                file_path="/tmp/catalog.csv",
                format_name="csv",
                headers=["track_title", "artist_name"],
                preview_rows=[{"track_title": "Orbit", "artist_name": "Cosmowyn"}],
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

    def test_mapping_can_explicitly_skip_a_source_field(self):
        inspection = ExchangeInspection(
            file_path="/tmp/catalog.csv",
            format_name="csv",
            headers=["track_title", "artist_name", "Mood Source"],
            preview_rows=[
                {
                    "track_title": "Orbit",
                    "artist_name": "Cosmowyn",
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


if __name__ == "__main__":
    unittest.main()

import unittest

try:
    from PySide6.QtWidgets import QApplication, QTabWidget
except ImportError as exc:  # pragma: no cover - environment-specific fallback
    QApplication = None
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
            tabs = dlg.findChild(QTabWidget, "exchangeImportTabs")
            self.assertIsNotNone(tabs)
            self.assertEqual(
                [tabs.tabText(i) for i in range(tabs.count())],
                [
                    "Setup & Mapping",
                    "Source Preview",
                ],
            )
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
        finally:
            dlg.close()


if __name__ == "__main__":
    unittest.main()

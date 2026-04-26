import tempfile
import unittest
from pathlib import Path

try:
    from PySide6.QtCore import QSettings
except ImportError as exc:  # pragma: no cover - environment-specific fallback
    QSettings = None
    QT_IMPORT_ERROR = exc
else:
    QT_IMPORT_ERROR = None

from isrc_manager.services.update_preferences import (
    IGNORED_UPDATE_VERSION_KEY,
    UpdatePreferenceService,
)


class UpdatePreferenceServiceTests(unittest.TestCase):
    def setUp(self):
        if QSettings is None:
            raise unittest.SkipTest(f"QSettings unavailable: {QT_IMPORT_ERROR}")
        self.tmpdir = tempfile.TemporaryDirectory()
        self.settings = QSettings(
            str(Path(self.tmpdir.name) / "settings.ini"),
            QSettings.IniFormat,
        )
        self.settings.setFallbacksEnabled(False)
        self.service = UpdatePreferenceService(self.settings)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_ignored_version_round_trip_and_clear(self):
        self.assertEqual(self.service.ignored_version(), "")

        stored = self.service.set_ignored_version("3.2.1")

        self.assertEqual(stored, "3.2.1")
        self.assertEqual(self.service.ignored_version(), "3.2.1")

        self.service.clear_ignored_version()

        self.assertEqual(self.service.ignored_version(), "")

    def test_invalid_stored_version_is_ignored(self):
        self.settings.setValue(IGNORED_UPDATE_VERSION_KEY, "not-a-version")

        self.assertEqual(self.service.ignored_version(), "")


if __name__ == "__main__":
    unittest.main()

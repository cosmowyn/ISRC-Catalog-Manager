import sqlite3
import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import QSettings

from isrc_manager.services import GS1ProfileDefaults, GS1SettingsService


def make_settings_conn():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE app_kv (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """
    )
    return conn


class GS1SettingsServiceTests(unittest.TestCase):
    def setUp(self):
        self.conn = make_settings_conn()
        self.tmpdir = tempfile.TemporaryDirectory()
        self.settings_path = Path(self.tmpdir.name) / "settings.ini"
        self.settings = QSettings(str(self.settings_path), QSettings.IniFormat)
        self.settings.setFallbacksEnabled(False)
        self.service = GS1SettingsService(self.conn, self.settings)

    def tearDown(self):
        self.settings.clear()
        self.conn.close()
        self.tmpdir.cleanup()

    def test_template_path_is_stored_in_qsettings(self):
        saved = self.service.set_template_path("/tmp/official-gs1-template.xlsx")

        self.assertEqual(saved, "/tmp/official-gs1-template.xlsx")
        self.assertEqual(self.service.load_template_path(), "/tmp/official-gs1-template.xlsx")
        self.assertEqual(
            self.settings.value("gs1/template_path", "", str),
            "/tmp/official-gs1-template.xlsx",
        )

    def test_profile_defaults_round_trip_through_app_kv(self):
        saved = self.service.set_profile_defaults(
            GS1ProfileDefaults(
                target_market="Worldwide",
                language="English",
                brand="Orbit Label",
                subbrand="Digital Series",
                packaging_type="Digital file",
                product_classification="Audio",
            )
        )

        self.assertEqual(
            saved,
            GS1ProfileDefaults(
                target_market="Worldwide",
                language="English",
                brand="Orbit Label",
                subbrand="Digital Series",
                packaging_type="Digital file",
                product_classification="Audio",
            ),
        )
        rows = {
            key: value
            for key, value in self.conn.execute("SELECT key, value FROM app_kv").fetchall()
        }
        self.assertEqual(rows["gs1/default_target_market"], "Worldwide")
        self.assertEqual(rows["gs1/default_language"], "English")
        self.assertEqual(rows["gs1/default_brand"], "Orbit Label")
        self.assertEqual(rows["gs1/default_subbrand"], "Digital Series")
        self.assertEqual(rows["gs1/default_packaging_type"], "Digital file")
        self.assertEqual(rows["gs1/default_product_classification"], "Audio")


if __name__ == "__main__":
    unittest.main()

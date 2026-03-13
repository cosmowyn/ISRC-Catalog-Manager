import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import QSettings

from isrc_manager.services import DatabaseSessionService, ProfileKVService


class DatabaseSessionServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.db_path = self.root / "Database" / "library.db"
        self.settings_path = self.root / "settings.ini"
        self.settings = QSettings(str(self.settings_path), QSettings.IniFormat)
        self.settings.setFallbacksEnabled(False)
        self.service = DatabaseSessionService()

    def tearDown(self):
        self.settings.clear()
        self.tmpdir.cleanup()

    def test_open_creates_profile_store_and_applies_pragmas(self):
        session = self.service.open(self.db_path)
        try:
            table_row = session.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='app_kv'"
            ).fetchone()
            foreign_keys = session.conn.execute("PRAGMA foreign_keys").fetchone()[0]
            journal_mode = session.conn.execute("PRAGMA journal_mode").fetchone()[0]

            self.assertEqual(table_row, ("app_kv",))
            self.assertEqual(foreign_keys, 1)
            self.assertEqual(journal_mode.lower(), "wal")
        finally:
            self.service.close(session.conn)

    def test_profile_kv_reads_and_writes_values(self):
        session = self.service.open(self.db_path)
        try:
            kv = ProfileKVService(session.conn)
            kv.set("isrc_artist_code", "42")

            self.assertEqual(kv.get("isrc_artist_code"), "42")
            self.assertEqual(kv.get("missing", "fallback"), "fallback")
        finally:
            self.service.close(session.conn)

    def test_remember_last_path_updates_settings(self):
        self.service.remember_last_path(self.settings, str(self.db_path))

        self.assertEqual(self.settings.value("db/last_path", "", str), str(self.db_path))


if __name__ == "__main__":
    unittest.main()

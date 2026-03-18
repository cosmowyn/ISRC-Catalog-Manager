import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from isrc_manager.services import DatabaseMaintenanceService, ProfileStoreService


def write_sample_db(path: Path, value: str):
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS sample (value TEXT)")
        conn.execute("DELETE FROM sample")
        conn.execute("INSERT INTO sample(value) VALUES (?)", (value,))
        conn.commit()
    finally:
        conn.close()


def read_sample_db(path: Path) -> str:
    conn = sqlite3.connect(str(path))
    try:
        row = conn.execute("SELECT value FROM sample").fetchone()
        return row[0] if row else ""
    finally:
        conn.close()


class ProfileStoreServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.database_dir = Path(self.tmpdir.name) / "Database"
        self.database_dir.mkdir(parents=True, exist_ok=True)
        self.service = ProfileStoreService(self.database_dir)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_build_list_and_delete_profiles(self):
        profile_path = self.service.build_profile_path("My Label")
        other_path = self.service.build_profile_path("second.db")
        profile_path.write_text("a", encoding="utf-8")
        other_path.write_text("b", encoding="utf-8")
        (self.database_dir / "notes.txt").write_text("ignore", encoding="utf-8")

        profiles = self.service.list_profiles()

        self.assertEqual(profile_path.name, "My_Label.db")
        self.assertEqual(profiles, [str(profile_path), str(other_path)])

        self.service.delete_profile(profile_path)
        self.assertFalse(profile_path.exists())
        self.service.delete_profile(profile_path)


class DatabaseMaintenanceServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.backups_dir = self.root / "backups"
        self.service = DatabaseMaintenanceService(self.backups_dir)
        self.current_db = self.root / "current.db"
        write_sample_db(self.current_db, "original")

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_create_backup_and_verify_integrity(self):
        conn = sqlite3.connect(str(self.current_db))
        try:
            result = self.service.create_backup(conn, self.current_db)
        finally:
            conn.close()

        self.assertTrue(result.backup_path.exists())
        self.assertEqual(self.service.verify_integrity(result.backup_path), "ok")
        self.assertEqual(read_sample_db(result.backup_path), "original")

    def test_restore_database_replaces_current_file_and_keeps_safety_copy(self):
        conn = sqlite3.connect(str(self.current_db))
        try:
            result = self.service.create_backup(conn, self.current_db)
        finally:
            conn.close()

        write_sample_db(self.current_db, "changed")
        restore = self.service.restore_database(result.backup_path, self.current_db)

        self.assertEqual(restore.integrity_result, "ok")
        self.assertEqual(read_sample_db(self.current_db), "original")
        self.assertIsNotNone(restore.safety_copy_path)
        self.assertTrue(restore.safety_copy_path.exists())
        self.assertEqual(read_sample_db(restore.safety_copy_path), "changed")

    def test_restore_database_keeps_current_file_when_backup_is_invalid(self):
        invalid_backup = self.backups_dir / "invalid.db"
        invalid_backup.parent.mkdir(parents=True, exist_ok=True)
        invalid_backup.write_text("not a sqlite database", encoding="utf-8")

        with self.assertRaises(RuntimeError):
            self.service.restore_database(invalid_backup, self.current_db)

        self.assertEqual(read_sample_db(self.current_db), "original")

    def test_restore_database_rolls_back_after_post_replace_integrity_failure(self):
        conn = sqlite3.connect(str(self.current_db))
        try:
            result = self.service.create_backup(conn, self.current_db)
        finally:
            conn.close()

        write_sample_db(self.current_db, "changed")

        with patch.object(
            self.service,
            "verify_integrity",
            side_effect=["ok", "ok", "database error: simulated failure"],
        ):
            with self.assertRaises(RuntimeError):
                self.service.restore_database(result.backup_path, self.current_db)

        self.assertEqual(read_sample_db(self.current_db), "changed")


if __name__ == "__main__":
    unittest.main()

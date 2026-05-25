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

    def test_sanitize_profile_names_and_missing_directory_listing(self):
        missing_service = ProfileStoreService(self.database_dir / "missing")

        self.assertEqual(
            ProfileStoreService.sanitize_profile_name("  Weird/Profile Name "),
            "Weird_Profile_Name.db",
        )
        self.assertEqual(ProfileStoreService.sanitize_profile_name("already.db"), "already.db")
        self.assertEqual(ProfileStoreService.sanitize_profile_name(""), "")
        self.assertEqual(missing_service.list_profiles(), [])
        with self.assertRaises(ValueError):
            self.service.build_profile_path("   ")


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

    def test_list_backup_files_returns_recursive_sorted_database_files(self):
        self.assertEqual(self.service.list_backup_files(), [])
        nested = self.backups_dir / "nested"
        nested.mkdir(parents=True)
        second = nested / "second.db"
        first = self.backups_dir / "first.db"
        note = self.backups_dir / "note.txt"
        second.write_text("b", encoding="utf-8")
        first.write_text("a", encoding="utf-8")
        note.write_text("ignore", encoding="utf-8")

        self.assertEqual(self.service.list_backup_files(), [first, second])

    def test_create_backup_requires_existing_source_file(self):
        conn = sqlite3.connect(":memory:")
        try:
            with self.assertRaises(FileNotFoundError):
                self.service.create_backup(conn, self.root / "missing.db")
        finally:
            conn.close()

    def test_create_backup_falls_back_to_file_copy_with_companion_files(self):
        source_wal = self.current_db.with_suffix(".db.wal")
        source_shm = self.current_db.with_suffix(".db.shm")
        source_wal.write_text("wal", encoding="utf-8")
        source_shm.write_text("shm", encoding="utf-8")
        conn = unittest.mock.Mock()
        conn.commit.side_effect = RuntimeError("commit ignored")
        conn.backup.side_effect = sqlite3.DatabaseError("backup unavailable")
        conn.execute.side_effect = sqlite3.OperationalError("vacuum unavailable")
        backup_conn = unittest.mock.Mock()
        close_connection = unittest.mock.Mock()
        reopen_connection = unittest.mock.Mock()

        with patch(
            "isrc_manager.services.database_admin.sqlite3.connect", return_value=backup_conn
        ):
            with patch.object(self.service, "verify_integrity", return_value="ok"):
                result = self.service.create_backup(
                    conn,
                    self.current_db,
                    close_connection=close_connection,
                    reopen_connection=reopen_connection,
                )

        self.assertEqual(result.method, "file_copy")
        self.assertTrue(result.backup_path.exists())
        self.assertEqual(
            result.backup_path.with_suffix(".db.wal").read_text(encoding="utf-8"), "wal"
        )
        self.assertEqual(
            result.backup_path.with_suffix(".db.shm").read_text(encoding="utf-8"), "shm"
        )
        close_connection.assert_called_once_with()
        reopen_connection.assert_called_once_with()
        backup_conn.close.assert_called_once_with()

    def test_create_backup_reports_all_method_failures_without_file_copy_callbacks(self):
        conn = unittest.mock.Mock()
        conn.backup.side_effect = sqlite3.DatabaseError("backup unavailable")
        conn.execute.side_effect = sqlite3.OperationalError("vacuum unavailable")

        with patch(
            "isrc_manager.services.database_admin.sqlite3.connect",
            return_value=unittest.mock.Mock(),
        ):
            with self.assertRaisesRegex(RuntimeError, "Backup failed using backup API"):
                self.service.create_backup(conn, self.current_db)

    def test_create_backup_rejects_corrupt_backup_result(self):
        conn = sqlite3.connect(str(self.current_db))
        try:
            with patch.object(self.service, "verify_integrity", return_value="not ok"):
                with self.assertRaisesRegex(RuntimeError, "Integrity check failed for backup"):
                    self.service.create_backup(conn, self.current_db)
        finally:
            conn.close()

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

    def test_restore_database_requires_existing_backup(self):
        with self.assertRaises(FileNotFoundError):
            self.service.restore_database(self.backups_dir / "missing.db", self.current_db)

    def test_restore_database_uses_copy_fallback_when_staging_backup_api_fails(self):
        backup = self.backups_dir / "fallback.db"
        backup.parent.mkdir(parents=True, exist_ok=True)
        write_sample_db(backup, "fallback")
        write_sample_db(self.current_db, "changed")

        with patch.object(self.service, "verify_integrity", side_effect=["ok", "ok", "ok"]):
            with patch(
                "isrc_manager.services.database_admin.sqlite3.connect",
                side_effect=sqlite3.DatabaseError("backup API unavailable"),
            ):
                restore = self.service.restore_database(backup, self.current_db)

        self.assertEqual(restore.integrity_result, "ok")
        self.assertEqual(read_sample_db(self.current_db), "fallback")
        self.assertFalse(any(self.root.glob("current.db.restore_*.tmp")))

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

    def test_restore_database_rolls_back_companion_files_after_final_integrity_failure(self):
        conn = sqlite3.connect(str(self.current_db))
        try:
            result = self.service.create_backup(conn, self.current_db)
        finally:
            conn.close()

        write_sample_db(self.current_db, "changed")
        current_wal = self.current_db.with_suffix(".db.wal")
        current_shm = self.current_db.with_suffix(".db.shm")
        current_wal.write_text("current wal", encoding="utf-8")
        current_shm.write_text("current shm", encoding="utf-8")

        with patch.object(
            self.service,
            "verify_integrity",
            side_effect=["ok", "ok", "database error: simulated failure"],
        ):
            with self.assertRaises(RuntimeError):
                self.service.restore_database(result.backup_path, self.current_db)

        self.assertEqual(read_sample_db(self.current_db), "changed")
        self.assertEqual(current_wal.read_text(encoding="utf-8"), "current wal")
        self.assertEqual(current_shm.read_text(encoding="utf-8"), "current shm")


if __name__ == "__main__":
    unittest.main()

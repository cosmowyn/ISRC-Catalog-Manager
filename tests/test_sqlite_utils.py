import sqlite3
import tempfile
import unittest
from pathlib import Path

from isrc_manager.services.sqlite_utils import safe_wal_checkpoint


class SafeWalCheckpointTests(unittest.TestCase):
    def test_checkpoint_returns_true_when_connection_is_idle(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "catalog.db"
            conn = sqlite3.connect(db_path)
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("CREATE TABLE sample (value INTEGER)")
                conn.commit()

                self.assertTrue(safe_wal_checkpoint(conn))
            finally:
                conn.close()

    def test_checkpoint_returns_false_when_connection_is_in_transaction(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "catalog.db"
            conn = sqlite3.connect(db_path)
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("CREATE TABLE sample (value INTEGER)")
                conn.commit()

                conn.execute("BEGIN")
                conn.execute("INSERT INTO sample(value) VALUES (1)")

                self.assertFalse(safe_wal_checkpoint(conn))
                conn.rollback()
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()

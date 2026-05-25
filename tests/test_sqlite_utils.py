import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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

    def test_checkpoint_returns_false_and_logs_when_transaction_and_logger_provided(self):
        conn = mock.Mock()
        conn.in_transaction = True
        logger = mock.Mock()

        result = safe_wal_checkpoint(conn, logger=logger)

        self.assertFalse(result)
        logger.warning.assert_called_once_with(
            "Skipping WAL checkpoint (%s) because the connection is still in a transaction.",
            "TRUNCATE",
        )

    def test_checkpoint_raises_for_invalid_mode(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "catalog.db"
            conn = sqlite3.connect(db_path)
            try:
                with self.assertRaises(ValueError):
                    safe_wal_checkpoint(conn, mode="INVALID")
            finally:
                conn.close()

    def test_checkpoint_returns_false_when_no_connection(self):
        self.assertEqual(safe_wal_checkpoint(None), False)

    def test_checkpoint_logs_and_returns_false_when_connection_is_busy(self):
        conn = mock.Mock()
        conn.in_transaction = False
        conn.execute.side_effect = sqlite3.OperationalError("database is locked")
        logger = mock.Mock()

        result = safe_wal_checkpoint(conn, mode="FULL", logger=logger)

        self.assertFalse(result)
        logger.warning.assert_called()

    def test_checkpoint_reraises_non_busy_operational_error(self):
        conn = mock.Mock()
        conn.in_transaction = False
        conn.execute.side_effect = sqlite3.OperationalError("database is malformed")

        with self.assertRaises(sqlite3.OperationalError):
            safe_wal_checkpoint(conn)

    def test_checkpoint_returns_false_when_checkpoint_reports_busy(self):
        cursor = mock.Mock()
        cursor.fetchone.return_value = (1, 0, 0)
        conn = mock.Mock()
        conn.in_transaction = False
        conn.execute.return_value = cursor
        logger = mock.Mock()

        result = safe_wal_checkpoint(conn, logger=logger)

        self.assertFalse(result)
        logger.warning.assert_called_once()

    def test_checkpoint_reports_busy_branch_with_logger_for_non_zero_result(self):
        cursor = mock.Mock()
        cursor.fetchone.return_value = (2, 0, 0)
        conn = mock.Mock()
        conn.in_transaction = False
        conn.execute.return_value = cursor
        logger = mock.Mock()

        result = safe_wal_checkpoint(conn, mode="FULL", logger=logger)

        self.assertFalse(result)
        logger.warning.assert_called_once()

    def test_checkpoint_returns_false_when_mode_is_invalid_and_logger_is_ignored(self):
        conn = mock.Mock()
        conn.in_transaction = False
        logger = mock.Mock()
        conn.execute = mock.Mock()

        with self.assertRaises(ValueError):
            safe_wal_checkpoint(conn, mode="bogus", logger=logger)
        conn.execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()

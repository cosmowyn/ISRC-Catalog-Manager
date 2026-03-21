import tempfile
import threading
import unittest
from pathlib import Path

from isrc_manager.services.db_access import (
    DatabaseWriteCoordinator,
    SQLiteConnectionFactory,
    is_lock_error,
)
from tests.qt_test_helpers import join_thread_or_fail


class SQLiteConnectionFactoryTests(unittest.TestCase):
    def test_open_applies_sqlite_pragmas(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "catalog.db"
            factory = SQLiteConnectionFactory(timeout_seconds=5.0, busy_timeout_ms=1500)
            conn = factory.open(db_path)
            try:
                journal_mode = str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower()
                foreign_keys = int(conn.execute("PRAGMA foreign_keys").fetchone()[0])
                busy_timeout = int(conn.execute("PRAGMA busy_timeout").fetchone()[0])

                self.assertEqual(journal_mode, "wal")
                self.assertEqual(foreign_keys, 1)
                self.assertEqual(busy_timeout, 1500)
            finally:
                conn.close()

    def test_lock_error_helper_detects_common_sqlite_messages(self):
        self.assertTrue(is_lock_error(RuntimeError("database table is locked")))
        self.assertTrue(is_lock_error(RuntimeError("database is busy")))
        self.assertFalse(is_lock_error(RuntimeError("some other failure")))


class DatabaseWriteCoordinatorTests(unittest.TestCase):
    def test_same_database_path_serializes_access(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "catalog.db"
            coordinator_a = DatabaseWriteCoordinator.for_path(db_path)
            coordinator_b = DatabaseWriteCoordinator.for_path(db_path)
            order: list[str] = []
            first_entered = threading.Event()
            release_first = threading.Event()
            second_entered = threading.Event()

            def worker(prefix: str, coordinator):
                with coordinator.acquire():
                    order.append(f"{prefix}-start")
                    if prefix == "first":
                        first_entered.set()
                        release_first.wait(timeout=1)
                    else:
                        second_entered.set()
                    order.append(f"{prefix}-end")

            first = threading.Thread(target=worker, args=("first", coordinator_a))
            second = threading.Thread(target=worker, args=("second", coordinator_b))

            first.start()
            self.assertTrue(first_entered.wait(timeout=1))
            second.start()
            self.assertFalse(second_entered.wait(timeout=0.1))
            release_first.set()
            self.assertTrue(second_entered.wait(timeout=1))
            join_thread_or_fail(
                first, timeout_seconds=1.0, description="first database write worker"
            )
            join_thread_or_fail(
                second, timeout_seconds=1.0, description="second database write worker"
            )

            self.assertEqual(order, ["first-start", "first-end", "second-start", "second-end"])


if __name__ == "__main__":
    unittest.main()

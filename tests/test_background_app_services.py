import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

try:
    from PySide6.QtCore import QEventLoop, QSettings, QTimer
    from PySide6.QtWidgets import QApplication
except ImportError as exc:  # pragma: no cover - environment-specific fallback
    QApplication = None
    QEventLoop = None
    QSettings = None
    QTimer = None
    QT_IMPORT_ERROR = exc
else:
    QT_IMPORT_ERROR = None

from isrc_manager.services import DatabaseSchemaService
from isrc_manager.services.db_access import DatabaseWriteCoordinator, SQLiteConnectionFactory
from isrc_manager.tasks.app_services import BackgroundAppServiceFactory
from isrc_manager.tasks.manager import BackgroundTaskManager


class BackgroundAppServiceIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if QApplication is None or QEventLoop is None or QTimer is None or QSettings is None:
            raise unittest.SkipTest(f"PySide6 Qt unavailable: {QT_IMPORT_ERROR}")
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.data_root = self.root / "data"
        self.history_root = self.root / "history"
        self.backups_root = self.root / "backups"
        self.db_path = self.root / "Database" / "catalog.db"
        self.settings_path = self.root / "settings.ini"
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.history_root.mkdir(parents=True, exist_ok=True)
        self.backups_root.mkdir(parents=True, exist_ok=True)

        bootstrap_conn = SQLiteConnectionFactory().open(self.db_path)
        try:
            schema = DatabaseSchemaService(bootstrap_conn, data_root=self.data_root)
            schema.init_db()
            schema.migrate_schema()
        finally:
            bootstrap_conn.close()

        settings = QSettings(str(self.settings_path), QSettings.IniFormat)
        settings.setFallbacksEnabled(False)
        settings.sync()

        self.factory = BackgroundAppServiceFactory(
            connection_factory=SQLiteConnectionFactory(),
            data_root=self.data_root,
            history_dir=self.history_root,
            backups_dir=self.backups_root,
            settings_path=self.settings_path,
            db_path=self.db_path,
        )
        self.manager = BackgroundTaskManager(self.app)

    def tearDown(self):
        self.manager.deleteLater()
        self.app.processEvents()
        self.tmpdir.cleanup()

    def test_background_bundle_task_persists_changes_and_reports_progress(self):
        loop = QEventLoop()
        captured = {"progress": []}

        def _task(ctx):
            with self.factory.open_bundle() as bundle:
                ctx.report_progress(0, 2, message="Starting")
                bundle.conn.execute("INSERT INTO Artists(name) VALUES ('Background Artist')")
                ctx.report_progress(2, 2, message="Finished")
                return "done"

        self.manager.submit(
            title="Background Insert",
            description="Insert a row via the background bundle.",
            task_fn=_task,
            kind="write",
            show_dialog=False,
            on_progress=lambda update: captured["progress"].append(
                (update.value, update.maximum, update.message)
            ),
            on_success=lambda result: captured.setdefault("result", result),
            on_finished=loop.quit,
        )
        QTimer.singleShot(3000, loop.quit)
        loop.exec()

        self.assertEqual(captured.get("result"), "done")
        self.assertEqual(
            captured["progress"],
            [(0, 2, "Starting"), (2, 2, "Finished")],
        )

        verify_conn = sqlite3.connect(str(self.db_path))
        try:
            count = verify_conn.execute("SELECT COUNT(*) FROM Artists").fetchone()[0]
        finally:
            verify_conn.close()
        self.assertEqual(count, 1)

    def test_background_bundle_failure_rolls_back_uncommitted_changes(self):
        loop = QEventLoop()
        captured = {}

        def _task(_ctx):
            with self.factory.open_bundle() as bundle:
                bundle.conn.execute("INSERT INTO Artists(name) VALUES ('Rolled Back')")
                raise RuntimeError("explode")

        self.manager.submit(
            title="Rollback Task",
            description="Exercise bundle rollback.",
            task_fn=_task,
            kind="write",
            show_dialog=False,
            on_error=lambda failure: captured.setdefault("message", failure.message),
            on_finished=loop.quit,
        )
        QTimer.singleShot(3000, loop.quit)
        loop.exec()

        self.assertEqual(captured.get("message"), "explode")
        verify_conn = sqlite3.connect(str(self.db_path))
        try:
            count = verify_conn.execute("SELECT COUNT(*) FROM Artists").fetchone()[0]
        finally:
            verify_conn.close()
        self.assertEqual(count, 0)

    def test_write_coordinator_serializes_overlapping_writes_for_same_profile(self):
        coordinator = DatabaseWriteCoordinator.for_path(self.db_path)
        order = []
        first_entered = threading.Event()
        second_attempting = threading.Event()
        second_entered = threading.Event()
        release_first = threading.Event()

        def _first():
            with coordinator.acquire():
                order.append("first")
                first_entered.set()
                release_first.wait(timeout=2)

        def _second():
            first_entered.wait(timeout=2)
            second_attempting.set()
            with DatabaseWriteCoordinator.for_path(self.db_path).acquire():
                order.append("second")
                second_entered.set()

        first_thread = threading.Thread(target=_first)
        second_thread = threading.Thread(target=_second)
        first_thread.start()
        second_thread.start()

        self.assertTrue(first_entered.wait(timeout=2))
        self.assertTrue(second_attempting.wait(timeout=2))
        self.assertFalse(second_entered.is_set())

        release_first.set()
        self.assertTrue(second_entered.wait(timeout=2))

        first_thread.join(timeout=2)
        second_thread.join(timeout=2)
        self.assertEqual(order, ["first", "second"])


if __name__ == "__main__":
    unittest.main()

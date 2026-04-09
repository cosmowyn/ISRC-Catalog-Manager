import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

try:
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
except ImportError as exc:  # pragma: no cover - environment-specific fallback
    QApplication = None
    QSettings = None
    QT_IMPORT_ERROR = exc
else:
    QT_IMPORT_ERROR = None

from isrc_manager.services import DatabaseSchemaService
from isrc_manager.services.db_access import DatabaseWriteCoordinator, SQLiteConnectionFactory
from isrc_manager.tasks.app_services import BackgroundAppServiceFactory
from isrc_manager.tasks.manager import BackgroundTaskManager
from tests.qt_test_helpers import join_thread_or_fail, pump_events, wait_for


class BackgroundAppServiceIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if QApplication is None or QSettings is None:
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
        for record in list(self.manager._tasks.values()):
            record.context.cancel()
        if self.manager.has_running_tasks():
            wait_for(
                lambda: not self.manager.has_running_tasks(),
                timeout_ms=1500,
                interval_ms=10,
                app=self.app,
                description="background-app-service teardown cleanup",
            )
        self.manager.deleteLater()
        pump_events(app=self.app)
        self.tmpdir.cleanup()

    def _wait_for_task_completion(self, finished: threading.Event, *, description: str) -> None:
        wait_for(
            finished.is_set,
            timeout_ms=1500,
            interval_ms=10,
            app=self.app,
            description=description,
        )

    def test_background_bundle_task_persists_changes_and_reports_progress(self):
        captured = {"progress": []}
        finished = threading.Event()

        def _task(ctx):
            with self.factory.open_bundle() as bundle:
                ctx.report_progress(0, 2, message="Starting")
                bundle.conn.execute(
                    """
                    INSERT INTO Parties(legal_name, display_name, artist_name, party_type)
                    VALUES (?, ?, ?, 'artist')
                    """,
                    ("Background Artist", "Background Artist", "Background Artist"),
                )
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
            on_finished=finished.set,
        )
        self._wait_for_task_completion(
            finished,
            description="background bundle task completion",
        )

        self.assertEqual(captured.get("result"), "done")
        self.assertEqual(
            captured["progress"],
            [(0, 2, "Starting"), (2, 2, "Finished")],
        )

        verify_conn = sqlite3.connect(str(self.db_path))
        try:
            count = verify_conn.execute(
                """
                SELECT COUNT(*)
                FROM Parties
                WHERE lower(trim(coalesce(artist_name, display_name, legal_name, ''))) = lower(?)
                """,
                ("Background Artist",),
            ).fetchone()[0]
        finally:
            verify_conn.close()
        self.assertEqual(count, 1)

    def test_background_bundle_failure_rolls_back_uncommitted_changes(self):
        captured = {}
        finished = threading.Event()

        def _task(_ctx):
            with self.factory.open_bundle() as bundle:
                bundle.conn.execute(
                    """
                    INSERT INTO Parties(legal_name, display_name, artist_name, party_type)
                    VALUES (?, ?, ?, 'artist')
                    """,
                    ("Rolled Back", "Rolled Back", "Rolled Back"),
                )
                raise RuntimeError("explode")

        self.manager.submit(
            title="Rollback Task",
            description="Exercise bundle rollback.",
            task_fn=_task,
            kind="write",
            show_dialog=False,
            on_error=lambda failure: captured.setdefault("message", failure.message),
            on_finished=finished.set,
        )
        self._wait_for_task_completion(
            finished,
            description="background rollback task completion",
        )

        self.assertEqual(captured.get("message"), "explode")
        verify_conn = sqlite3.connect(str(self.db_path))
        try:
            count = verify_conn.execute(
                """
                SELECT COUNT(*)
                FROM Parties
                WHERE lower(trim(coalesce(artist_name, display_name, legal_name, ''))) = lower(?)
                """,
                ("Rolled Back",),
            ).fetchone()[0]
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

        join_thread_or_fail(first_thread, timeout_seconds=2.0, description="first write thread")
        join_thread_or_fail(second_thread, timeout_seconds=2.0, description="second write thread")
        self.assertEqual(order, ["first", "second"])

    def test_background_bundle_exposes_authenticity_services(self):
        with self.factory.open_bundle() as bundle:
            record = bundle.authenticity_key_service.generate_keypair(signer_label="Background")

            self.assertIsNotNone(bundle.code_registry_service)
            self.assertIsNotNone(bundle.authenticity_manifest_service)
            self.assertIsNotNone(bundle.audio_watermark_service)
            self.assertIsNotNone(bundle.audio_authenticity_service)
            self.assertIsNotNone(bundle.forensic_watermark_service)
            self.assertIsNotNone(bundle.forensic_export_service)
            self.assertEqual(bundle.authenticity_key_service.default_key_id(), record.key_id)
            self.assertTrue(
                bundle.authenticity_key_service.private_key_path(record.key_id).exists()
            )


if __name__ == "__main__":
    unittest.main()

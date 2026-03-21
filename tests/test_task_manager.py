import threading
import time
import unittest

try:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
except ImportError as exc:  # pragma: no cover - environment-specific fallback
    QApplication = None
    QTimer = None
    QT_IMPORT_ERROR = exc
else:
    QT_IMPORT_ERROR = None

from isrc_manager.tasks.manager import BackgroundTaskManager
from tests.qt_test_helpers import pump_events, wait_for


class BackgroundTaskManagerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if QApplication is None or QTimer is None:
            raise unittest.SkipTest(f"PySide6 QtWidgets unavailable: {QT_IMPORT_ERROR}")
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.manager = BackgroundTaskManager(self.app)

    def tearDown(self):
        for record in list(self.manager._tasks.values()):
            record.context.cancel()
        if self.manager.has_running_tasks():
            self._wait_for_task_completion(
                lambda: not self.manager.has_running_tasks(),
                description="background-task teardown cleanup",
            )
        self.manager.deleteLater()
        pump_events(app=self.app)

    def _wait_for_task_completion(self, predicate, *, description: str, timeout_ms: int = 1500):
        wait_for(
            predicate, timeout_ms=timeout_ms, interval_ms=10, app=self.app, description=description
        )

    def test_submit_success_invokes_success_callback(self):
        captured = {}
        finished = threading.Event()

        self.manager.submit(
            title="Success Task",
            description="Testing success callback.",
            task_fn=lambda _ctx: 42,
            show_dialog=False,
            on_success=lambda result: captured.setdefault("result", result),
            on_finished=finished.set,
        )
        self._wait_for_task_completion(
            finished.is_set,
            description="success task completion",
        )

        self.assertEqual(captured.get("result"), 42)
        self.assertFalse(self.manager.has_running_tasks())

    def test_success_callback_runs_on_application_thread(self):
        captured = {}
        finished = threading.Event()
        main_thread_id = threading.get_ident()

        self.manager.submit(
            title="Thread Affinity Task",
            description="Ensure callbacks return to the UI thread.",
            task_fn=lambda _ctx: threading.get_ident(),
            show_dialog=False,
            on_success=lambda result: captured.update(
                {
                    "worker_thread": result,
                    "callback_thread": threading.get_ident(),
                }
            ),
            on_finished=finished.set,
        )
        self._wait_for_task_completion(
            finished.is_set,
            description="thread-affinity task completion",
        )

        self.assertIsNotNone(captured.get("worker_thread"))
        self.assertNotEqual(captured.get("worker_thread"), main_thread_id)
        self.assertEqual(captured.get("callback_thread"), main_thread_id)
        self.assertFalse(self.manager.has_running_tasks())

    def test_submit_failure_invokes_error_callback(self):
        captured = {}
        finished = threading.Event()

        def _fail(_ctx):
            raise ValueError("boom")

        self.manager.submit(
            title="Failure Task",
            description="Testing error callback.",
            task_fn=_fail,
            show_dialog=False,
            on_error=lambda failure: captured.setdefault("message", failure.message),
            on_finished=finished.set,
        )
        self._wait_for_task_completion(
            finished.is_set,
            description="failing task completion",
        )

        self.assertEqual(captured.get("message"), "boom")
        self.assertFalse(self.manager.has_running_tasks())

    def test_submit_cancellation_invokes_cancelled_callback(self):
        captured = {}
        finished = threading.Event()

        def _long_running(ctx):
            while True:
                ctx.raise_if_cancelled()
                time.sleep(0.01)

        task_id = self.manager.submit(
            title="Cancelled Task",
            description="Testing cancellation.",
            task_fn=_long_running,
            show_dialog=False,
            cancellable=True,
            on_cancelled=lambda: captured.setdefault("cancelled", True),
            on_finished=finished.set,
        )
        self.assertIsNotNone(task_id)

        QTimer.singleShot(50, lambda: self.manager._tasks[task_id].context.cancel())
        self._wait_for_task_completion(
            finished.is_set,
            description="cancelled task completion",
        )

        self.assertTrue(captured.get("cancelled"))
        self.assertFalse(self.manager.has_running_tasks())

    def test_duplicate_unique_key_is_rejected(self):
        captured = {}
        finished = threading.Event()

        def _long_running(ctx):
            while not ctx.is_cancelled():
                time.sleep(0.01)
            ctx.raise_if_cancelled()

        task_id = self.manager.submit(
            title="First Task",
            description="First task.",
            task_fn=_long_running,
            show_dialog=False,
            unique_key="same-task",
            on_finished=finished.set,
        )
        self.assertIsNotNone(task_id)

        rejected = self.manager.submit(
            title="Second Task",
            description="Second task.",
            task_fn=lambda _ctx: None,
            show_dialog=False,
            unique_key="same-task",
            on_error=lambda failure: captured.setdefault("message", failure.message),
        )
        self.assertIsNone(rejected)
        self.assertIn("already running", captured.get("message", ""))

        QTimer.singleShot(50, lambda: self.manager._tasks[task_id].context.cancel())
        self._wait_for_task_completion(
            finished.is_set,
            description="duplicate-key cancellation completion",
        )


if __name__ == "__main__":
    unittest.main()

import threading
import time
import unittest

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from isrc_manager.tasks.manager import BackgroundTaskManager


class BackgroundTaskManagerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.manager = BackgroundTaskManager(self.app)

    def tearDown(self):
        self.manager.deleteLater()
        self.app.processEvents()

    def test_submit_success_invokes_success_callback(self):
        loop = QEventLoop()
        captured = {}

        self.manager.submit(
            title="Success Task",
            description="Testing success callback.",
            task_fn=lambda _ctx: 42,
            show_dialog=False,
            on_success=lambda result: captured.setdefault("result", result),
            on_finished=loop.quit,
        )
        QTimer.singleShot(3000, loop.quit)
        loop.exec()

        self.assertEqual(captured.get("result"), 42)
        self.assertFalse(self.manager.has_running_tasks())

    def test_success_callback_runs_on_application_thread(self):
        loop = QEventLoop()
        captured = {}
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
            on_finished=loop.quit,
        )
        QTimer.singleShot(3000, loop.quit)
        loop.exec()

        self.assertIsNotNone(captured.get("worker_thread"))
        self.assertNotEqual(captured.get("worker_thread"), main_thread_id)
        self.assertEqual(captured.get("callback_thread"), main_thread_id)
        self.assertFalse(self.manager.has_running_tasks())

    def test_submit_failure_invokes_error_callback(self):
        loop = QEventLoop()
        captured = {}

        def _fail(_ctx):
            raise ValueError("boom")

        self.manager.submit(
            title="Failure Task",
            description="Testing error callback.",
            task_fn=_fail,
            show_dialog=False,
            on_error=lambda failure: captured.setdefault("message", failure.message),
            on_finished=loop.quit,
        )
        QTimer.singleShot(3000, loop.quit)
        loop.exec()

        self.assertEqual(captured.get("message"), "boom")
        self.assertFalse(self.manager.has_running_tasks())

    def test_submit_cancellation_invokes_cancelled_callback(self):
        loop = QEventLoop()
        captured = {}

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
            on_finished=loop.quit,
        )
        self.assertIsNotNone(task_id)

        QTimer.singleShot(50, lambda: self.manager._tasks[task_id].context.cancel())
        QTimer.singleShot(3000, loop.quit)
        loop.exec()

        self.assertTrue(captured.get("cancelled"))
        self.assertFalse(self.manager.has_running_tasks())

    def test_duplicate_unique_key_is_rejected(self):
        loop = QEventLoop()
        captured = {}

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
            on_finished=loop.quit,
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
        QTimer.singleShot(3000, loop.quit)
        loop.exec()


if __name__ == "__main__":
    unittest.main()

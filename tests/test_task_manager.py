import threading
import time
import unittest

try:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QLabel, QProgressBar, QPushButton
except ImportError as exc:  # pragma: no cover - environment-specific fallback
    QApplication = None
    QLabel = None
    QProgressBar = None
    QPushButton = None
    QTimer = None
    QT_IMPORT_ERROR = exc
else:
    QT_IMPORT_ERROR = None

from isrc_manager.tasks.manager import BackgroundTaskManager, _format_progress_dialog_message
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

    def test_progress_dialog_uses_compact_width_constraints(self):
        finished = threading.Event()
        release = threading.Event()

        def _long_running(ctx):
            ctx.report_progress(
                value=1,
                maximum=4,
                message=(
                    "Preparing an intentionally long progress message so the dialog has to wrap "
                    "instead of stretching across the full window width."
                ),
            )
            while not release.is_set():
                time.sleep(0.01)
            return "done"

        task_id = self.manager.submit(
            title="Compact Progress Task",
            description="Testing compact progress dialog sizing.",
            task_fn=_long_running,
            show_dialog=True,
            cancellable=True,
            on_finished=finished.set,
        )
        self.assertIsNotNone(task_id)
        record = self.manager._tasks[task_id]
        dialog = record.dialog
        self.assertIsNotNone(dialog)
        assert dialog is not None

        self._wait_for_task_completion(
            lambda: dialog.isVisible(),
            description="progress dialog visibility",
        )
        pump_events(app=self.app)

        self.assertEqual(dialog.minimumWidth(), 360)
        self.assertEqual(dialog.maximumWidth(), 480)
        self.assertGreaterEqual(dialog.width(), 360)
        self.assertLessEqual(dialog.width(), 480)
        self.assertGreaterEqual(dialog.height(), 118)
        self.assertLessEqual(dialog.height(), 220)

        labels = dialog.findChildren(QLabel)
        self.assertTrue(labels)
        self.assertTrue(all(label.wordWrap() for label in labels))
        self.assertTrue(all(label.maximumWidth() <= dialog.width() for label in labels))

        progress_bars = dialog.findChildren(QProgressBar)
        self.assertTrue(progress_bars)
        self.assertTrue(all(bar.maximumWidth() < dialog.width() for bar in progress_bars))

        buttons = dialog.findChildren(QPushButton)
        self.assertTrue(buttons)
        self.assertTrue(all(button.maximumWidth() <= 110 for button in buttons))
        self.assertTrue(all(dialog.rect().contains(button.geometry()) for button in buttons))

        release.set()
        self._wait_for_task_completion(
            finished.is_set,
            description="compact progress dialog completion",
        )

    def test_progress_dialog_keeps_width_stable_and_buttons_visible_during_updates(self):
        finished = threading.Event()
        allow_second_update = threading.Event()
        second_update_emitted = threading.Event()
        allow_finish = threading.Event()

        def _long_running(ctx):
            ctx.report_progress(
                value=1,
                maximum=3,
                message="Preparing the export task with a long status message for layout checks.",
            )
            while not allow_second_update.is_set():
                time.sleep(0.01)
            ctx.report_progress(
                value=2,
                maximum=3,
                message=(
                    "Writing metadata tags for a deliberately long filename so the dialog keeps "
                    "its width stable and the Cancel button stays visible."
                ),
            )
            second_update_emitted.set()
            while not allow_finish.is_set():
                time.sleep(0.01)
            return "done"

        task_id = self.manager.submit(
            title="Stable Progress Task",
            description="Testing progress dialog geometry stability.",
            task_fn=_long_running,
            show_dialog=True,
            cancellable=True,
            on_finished=finished.set,
        )
        self.assertIsNotNone(task_id)
        record = self.manager._tasks[task_id]
        dialog = record.dialog
        self.assertIsNotNone(dialog)
        assert dialog is not None

        self._wait_for_task_completion(
            lambda: dialog.isVisible(),
            description="stable progress dialog visibility",
        )
        pump_events(app=self.app)

        first_width = dialog.width()
        buttons = [button for button in dialog.findChildren(QPushButton) if not button.isHidden()]
        self.assertTrue(buttons)
        self.assertTrue(all(button.isVisible() for button in buttons))
        self.assertTrue(all(dialog.rect().contains(button.geometry()) for button in buttons))

        allow_second_update.set()
        self._wait_for_task_completion(
            lambda: second_update_emitted.is_set(),
            description="second progress update emission",
        )
        pump_events(app=self.app)

        self.assertEqual(dialog.width(), first_width)
        self.assertTrue(all(button.isVisible() for button in buttons))
        self.assertTrue(all(dialog.rect().contains(button.geometry()) for button in buttons))

        allow_finish.set()
        self._wait_for_task_completion(
            lambda: finished.is_set(),
            description="stable progress dialog completion",
        )

    def test_progress_dialog_message_format_abbreviates_only_long_dynamic_suffixes(self):
        short_message = "Converting 1 of 1: Short Title"
        long_title = (
            "This is a deliberately long export title that should keep its useful start and end"
        )
        formatted_short = _format_progress_dialog_message(short_message)
        formatted_long = _format_progress_dialog_message(f"Converting 1 of 1: {long_title}")

        self.assertEqual(formatted_short, short_message)
        self.assertEqual(
            formatted_long,
            "Converting 1 of 1: This is a deliberate... its useful start and end",
        )

    def test_progress_dialog_wraps_long_status_updates_with_bounded_height(self):
        finished = threading.Event()
        allow_second_update = threading.Event()
        second_update_emitted = threading.Event()

        def _long_running(ctx):
            ctx.set_status("Starting export.")
            while not allow_second_update.is_set():
                time.sleep(0.01)
            ctx.set_status("Writing metadata tags for a moderately long export status message.")
            second_update_emitted.set()
            return "done"

        task_id = self.manager.submit(
            title="Wrapped Status Task",
            description="Testing wrapped status geometry.",
            task_fn=_long_running,
            show_dialog=True,
            cancellable=True,
            on_finished=finished.set,
        )
        self.assertIsNotNone(task_id)
        dialog = self.manager._tasks[task_id].dialog
        self.assertIsNotNone(dialog)
        assert dialog is not None

        self._wait_for_task_completion(
            lambda: dialog.isVisible(),
            description="wrapped status dialog visibility",
        )
        pump_events(app=self.app)
        first_height = dialog.height()

        allow_second_update.set()
        self._wait_for_task_completion(
            lambda: second_update_emitted.is_set(),
            description="wrapped status second update emission",
        )
        pump_events(app=self.app)

        self.assertGreaterEqual(dialog.height(), first_height)
        self.assertLessEqual(dialog.height(), 220)

        self._wait_for_task_completion(
            lambda: finished.is_set(),
            description="wrapped status dialog completion",
        )


if __name__ == "__main__":
    unittest.main()

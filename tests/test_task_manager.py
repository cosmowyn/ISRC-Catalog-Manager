import threading
import time
import unittest
from unittest.mock import patch

try:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QLabel, QProgressBar, QPushButton, QWidget
except ImportError as exc:  # pragma: no cover - environment-specific fallback
    QApplication = None
    QLabel = None
    QProgressBar = None
    QPushButton = None
    QTimer = None
    QWidget = None
    QT_IMPORT_ERROR = exc
else:
    QT_IMPORT_ERROR = None

from isrc_manager.tasks.manager import (
    BackgroundTaskContext,
    BackgroundTaskManager,
    _format_progress_dialog_message,
)
from isrc_manager.tasks.models import TaskProgressUpdate
from isrc_manager.theme_builder import effective_theme_settings
from tests.qt_test_helpers import pump_events, wait_for


class _ThemedProgressOwner(QWidget):
    def __init__(self, theme_values):
        super().__init__()
        self._theme_values = effective_theme_settings(theme_values)

    def _effective_theme_settings(self):
        return dict(self._theme_values)


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

        self.assertEqual(dialog.objectName(), "backgroundTaskProgressDialog")
        self.assertTrue(bool(dialog.styleSheet().strip()))
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
        self.assertTrue(
            all(label.objectName() == "backgroundTaskProgressLabel" for label in labels)
        )

        progress_bars = dialog.findChildren(QProgressBar)
        self.assertTrue(progress_bars)
        self.assertTrue(all(bar.maximumWidth() < dialog.width() for bar in progress_bars))
        self.assertTrue(
            all(bar.objectName() == "backgroundTaskProgressBar" for bar in progress_bars)
        )
        self.assertTrue(all(not bar.isTextVisible() for bar in progress_bars))

        buttons = dialog.findChildren(QPushButton)
        self.assertTrue(buttons)
        self.assertTrue(all(button.maximumWidth() <= 110 for button in buttons))
        self.assertTrue(all(dialog.rect().contains(button.geometry()) for button in buttons))
        self.assertTrue(
            all(button.objectName() == "backgroundTaskProgressButton" for button in buttons)
        )
        primary_label = labels[0]
        primary_bar = progress_bars[0]
        primary_button = buttons[0]
        self.assertLess(primary_label.geometry().bottom(), primary_bar.geometry().top())
        self.assertLess(primary_bar.geometry().bottom(), primary_button.geometry().top())
        self.assertLessEqual(
            abs(primary_label.geometry().center().x() - dialog.rect().center().x()),
            2,
        )
        self.assertLessEqual(
            abs(primary_button.geometry().center().x() - dialog.rect().center().x()),
            2,
        )
        bottom_padding = dialog.rect().bottom() - primary_button.geometry().bottom()
        self.assertGreaterEqual(bottom_padding, 10)
        self.assertLessEqual(bottom_padding, 20)

        release.set()
        self._wait_for_task_completion(
            finished.is_set,
            description="compact progress dialog completion",
        )

    def test_progress_dialog_chrome_uses_owner_theme_colors(self):
        finished = threading.Event()
        release = threading.Event()
        owner = _ThemedProgressOwner(
            {
                "window_bg": "#0F172A",
                "window_fg": "#E2E8F0",
                "panel_bg": "#112233",
                "panel_alt_bg": "#1A2B3C",
                "menu_border": "#445566",
                "accent": "#33AAFF",
            }
        )

        def _long_running(ctx):
            ctx.set_status("Applying themed progress dialog chrome.")
            while not release.is_set():
                time.sleep(0.01)
            return "done"

        try:
            task_id = self.manager.submit(
                title="Themed Progress Task",
                description="Verifying themed progress dialog chrome.",
                task_fn=_long_running,
                owner=owner,
                show_dialog=True,
                cancellable=False,
                on_finished=finished.set,
            )
            self.assertIsNotNone(task_id)
            dialog = self.manager._tasks[task_id].dialog
            self.assertIsNotNone(dialog)
            assert dialog is not None

            self._wait_for_task_completion(
                lambda: dialog.isVisible(),
                description="themed progress dialog visibility",
            )
            pump_events(app=self.app)

            stylesheet = dialog.styleSheet()
            self.assertIn("rgba(17, 34, 51, 246)", stylesheet)
            self.assertIn("rgba(26, 43, 60, 252)", stylesheet)
            self.assertIn("#E2E8F0", stylesheet)
            self.assertNotIn("rgba(18, 34, 54, 244)", stylesheet)
            self.assertNotIn("#ffbf5a", stylesheet.lower())
        finally:
            release.set()
            self._wait_for_task_completion(
                lambda: finished.is_set(),
                description="themed progress dialog completion",
            )
            owner.close()

    def test_progress_dialog_assigns_child_object_names_before_chrome_application(self):
        finished = threading.Event()
        release = threading.Event()
        recorded: dict[str, list[str]] = {}
        original = None

        def _long_running(ctx):
            ctx.set_status("Preparing themed progress dialog chrome.")
            while not release.is_set():
                time.sleep(0.01)
            return "done"

        from isrc_manager.tasks import manager as task_manager_module

        original = task_manager_module._apply_progress_dialog_chrome

        def _recording_apply(dialog):
            recorded["labels"] = [label.objectName() for label in dialog.findChildren(QLabel)]
            recorded["bars"] = [bar.objectName() for bar in dialog.findChildren(QProgressBar)]
            recorded["buttons"] = [
                button.objectName()
                for button in dialog.findChildren(QPushButton)
                if not button.isHidden()
            ]
            return original(dialog)

        with patch(
            "isrc_manager.tasks.manager._apply_progress_dialog_chrome",
            side_effect=_recording_apply,
        ):
            task_id = self.manager.submit(
                title="Progress Chrome Ordering Task",
                description="Testing progress dialog chrome ordering.",
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
                description="progress chrome ordering visibility",
            )
            pump_events(app=self.app)
            self.assertTrue(recorded.get("labels"))
            self.assertTrue(recorded.get("bars"))
            self.assertTrue(recorded.get("buttons"))
            self.assertTrue(
                all(name == "backgroundTaskProgressLabel" for name in recorded["labels"])
            )
            self.assertTrue(all(name == "backgroundTaskProgressBar" for name in recorded["bars"]))
            self.assertTrue(
                all(name == "backgroundTaskProgressButton" for name in recorded["buttons"])
            )

        release.set()
        self._wait_for_task_completion(
            lambda: finished.is_set(),
            description="progress chrome ordering completion",
        )

    def test_refresh_active_progress_dialogs_rebuilds_theme_from_owner(self):
        finished = threading.Event()
        release = threading.Event()
        owner = _ThemedProgressOwner(
            {
                "window_bg": "#0F172A",
                "window_fg": "#E2E8F0",
                "panel_bg": "#112233",
                "panel_alt_bg": "#1A2B3C",
                "menu_border": "#445566",
                "accent": "#33AAFF",
            }
        )

        def _long_running(ctx):
            ctx.set_status("Refreshing themed progress dialog chrome.")
            while not release.is_set():
                time.sleep(0.01)
            return "done"

        try:
            task_id = self.manager.submit(
                title="Refreshable Progress Task",
                description="Testing live progress dialog theme refresh.",
                task_fn=_long_running,
                owner=owner,
                show_dialog=True,
                cancellable=False,
                on_finished=finished.set,
            )
            self.assertIsNotNone(task_id)
            dialog = self.manager._tasks[task_id].dialog
            self.assertIsNotNone(dialog)
            assert dialog is not None

            self._wait_for_task_completion(
                lambda: dialog.isVisible(),
                description="refreshable progress dialog visibility",
            )
            pump_events(app=self.app)

            self.assertIn("rgba(17, 34, 51, 246)", dialog.styleSheet())

            owner._theme_values = effective_theme_settings(
                {
                    "window_bg": "#E5EEF7",
                    "window_fg": "#102033",
                    "panel_bg": "#F4F8FC",
                    "panel_alt_bg": "#E2EBF5",
                    "menu_border": "#8AA0B8",
                    "accent": "#2F6BFF",
                }
            )
            self.manager.refresh_active_progress_dialogs()
            pump_events(app=self.app)

            stylesheet = dialog.styleSheet()
            self.assertIn("rgba(244, 248, 252, 246)", stylesheet)
            self.assertIn("rgba(226, 235, 245, 252)", stylesheet)
            self.assertIn("#102033", stylesheet)
            self.assertNotIn("rgba(17, 34, 51, 246)", stylesheet)
        finally:
            release.set()
            self._wait_for_task_completion(
                lambda: finished.is_set(),
                description="refreshable progress dialog completion",
            )
            owner.close()

    def test_non_cancellable_progress_dialog_uses_full_width_progress_surface(self):
        finished = threading.Event()
        release = threading.Event()

        def _long_running(ctx):
            ctx.set_status("Applying governed work metadata during a background save.")
            while not release.is_set():
                time.sleep(0.01)
            return "done"

        task_id = self.manager.submit(
            title="Non-cancellable Progress Task",
            description="Testing non-cancellable progress dialog layout.",
            task_fn=_long_running,
            show_dialog=True,
            cancellable=False,
            on_finished=finished.set,
        )
        self.assertIsNotNone(task_id)
        dialog = self.manager._tasks[task_id].dialog
        self.assertIsNotNone(dialog)
        assert dialog is not None

        self._wait_for_task_completion(
            lambda: dialog.isVisible(),
            description="non-cancellable dialog visibility",
        )
        pump_events(app=self.app)

        progress_bars = dialog.findChildren(QProgressBar)
        self.assertTrue(progress_bars)
        self.assertTrue(all(not bar.isTextVisible() for bar in progress_bars))
        self.assertGreaterEqual(progress_bars[0].maximumWidth(), dialog.width() - 56)
        labels = dialog.findChildren(QLabel)
        self.assertTrue(labels)
        self.assertLess(labels[0].geometry().bottom(), progress_bars[0].geometry().top())
        self.assertLessEqual(
            abs(labels[0].geometry().center().x() - dialog.rect().center().x()),
            2,
        )

        visible_buttons = [
            button for button in dialog.findChildren(QPushButton) if button.isVisible()
        ]
        self.assertFalse(visible_buttons)

        release.set()
        self._wait_for_task_completion(
            lambda: finished.is_set(),
            description="non-cancellable dialog completion",
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

    def test_background_task_context_accepts_positional_progress_message(self):
        updates = []
        context = BackgroundTaskContext()
        context.bind_callbacks(progress_callback=updates.append, status_callback=lambda _msg: None)

        context.report_progress(5, 10, "Reading package manifest...")

        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0].value, 5)
        self.assertEqual(updates[0].maximum, 10)
        self.assertEqual(updates[0].message, "Reading package manifest...")

    def test_success_after_cleanup_runs_only_after_dialog_cleanup(self):
        finished = threading.Event()
        callback_order: list[str] = []
        captured: dict[str, object] = {}
        task_id_holder: dict[str, str] = {}

        def _task(ctx):
            ctx.report_progress(90, 100, "Worker work complete.")
            time.sleep(0.05)
            return "done"

        def _before_cleanup(result, ui_progress):
            callback_order.append("before_cleanup")
            dialog = self.manager._tasks[task_id_holder["task_id"]].dialog
            captured["before_result"] = result
            captured["before_running"] = self.manager.has_running_tasks()
            captured["before_dialog_visible"] = bool(dialog is not None and dialog.isVisible())
            captured["dialog"] = dialog
            ui_progress.report_progress(99, 100, "Applying final UI state...")

        def _after_cleanup(result):
            callback_order.append("after_cleanup")
            dialog = captured.get("dialog")
            captured["after_result"] = result
            captured["after_running"] = self.manager.has_running_tasks()
            captured["after_dialog_visible"] = bool(dialog is not None and dialog.isVisible())

        def _finished():
            callback_order.append("finished")
            finished.set()

        task_id = self.manager.submit(
            title="Cleanup Ordering Task",
            description="Testing truthful cleanup ordering.",
            task_fn=_task,
            show_dialog=True,
            cancellable=False,
            on_success_before_cleanup=_before_cleanup,
            on_success_after_cleanup=_after_cleanup,
            on_finished=_finished,
        )
        self.assertIsNotNone(task_id)
        task_id_holder["task_id"] = str(task_id)
        dialog = self.manager._tasks[str(task_id)].dialog
        self.assertIsNotNone(dialog)
        assert dialog is not None

        self._wait_for_task_completion(
            lambda: dialog.isVisible(),
            description="cleanup-ordering dialog visibility",
        )
        self._wait_for_task_completion(
            finished.is_set,
            description="cleanup-ordering task completion",
        )

        self.assertEqual(callback_order, ["before_cleanup", "after_cleanup", "finished"])
        self.assertEqual(captured.get("before_result"), "done")
        self.assertEqual(captured.get("after_result"), "done")
        self.assertTrue(captured.get("before_running"))
        self.assertFalse(captured.get("after_running"))
        self.assertTrue(captured.get("before_dialog_visible"))
        self.assertFalse(captured.get("after_dialog_visible"))

    def test_late_progress_updates_after_dialog_cleanup_are_ignored(self):
        finished = threading.Event()
        progress_messages: list[str] = []
        status_messages: list[str] = []
        relay_holder: dict[str, object] = {}
        dialog_holder: dict[str, object] = {}

        def _task(ctx):
            ctx.report_progress(1, 3, "Importing contracts bundle...")
            ctx.set_status("Applying inspected contract rows.")
            return "done"

        def _after_cleanup(_result):
            dialog = dialog_holder.get("dialog")
            self.assertFalse(bool(dialog is not None and dialog.isVisible()))
            relay = relay_holder["relay"]
            relay.handle_progress(
                TaskProgressUpdate(
                    value=3,
                    maximum=3,
                    message="Late worker progress after dialog cleanup.",
                )
            )
            relay.handle_status("Late worker status after dialog cleanup.")

        task_id = self.manager.submit(
            title="Late Progress Guard Task",
            description="Testing late queued progress after cleanup.",
            task_fn=_task,
            show_dialog=True,
            cancellable=False,
            on_success_after_cleanup=_after_cleanup,
            on_finished=finished.set,
            on_progress=lambda update: progress_messages.append(str(update.message or "")),
            on_status=lambda message: status_messages.append(str(message or "")),
        )
        self.assertIsNotNone(task_id)
        record = self.manager._tasks[str(task_id)]
        relay_holder["relay"] = record.relay
        dialog_holder["dialog"] = record.dialog

        self._wait_for_task_completion(
            finished.is_set,
            description="late-progress cleanup task completion",
        )
        pump_events(app=self.app)

        self.assertEqual(progress_messages, ["Importing contracts bundle..."])
        self.assertEqual(status_messages, ["Applying inspected contract rows."])
        self.assertFalse(self.manager.has_running_tasks())

    def test_progress_updates_ignore_destroyed_progress_surface_widgets(self):
        finished = threading.Event()
        allow_finish = threading.Event()
        progress_messages: list[str] = []
        status_messages: list[str] = []

        def _task(ctx):
            ctx.report_progress(1, 3, "Preparing export surface...")
            ctx.set_status("Waiting for release.")
            while not allow_finish.is_set():
                time.sleep(0.01)
            return "done"

        task_id = self.manager.submit(
            title="Destroyed Surface Guard Task",
            description="Testing partially destroyed progress surfaces.",
            task_fn=_task,
            show_dialog=True,
            cancellable=False,
            on_finished=finished.set,
            on_progress=lambda update: progress_messages.append(str(update.message or "")),
            on_status=lambda message: status_messages.append(str(message or "")),
        )
        self.assertIsNotNone(task_id)
        record = self.manager._tasks[str(task_id)]
        dialog = record.dialog
        self.assertIsNotNone(dialog)
        assert dialog is not None

        self._wait_for_task_completion(
            lambda: dialog.isVisible(),
            description="destroyed-surface dialog visibility",
        )
        pump_events(app=self.app)

        labels = dialog.findChildren(QLabel)
        progress_bars = dialog.findChildren(QProgressBar)
        self.assertTrue(labels)
        self.assertTrue(progress_bars)
        label = labels[0]
        progress_bar = progress_bars[0]

        def _patched_is_valid(obj):
            if obj is progress_bar or obj is label:
                return False
            return True

        with patch("isrc_manager.tasks.manager._qt_object_is_valid", side_effect=_patched_is_valid):
            record.relay.handle_progress(
                TaskProgressUpdate(
                    value=2,
                    maximum=3,
                    message="Late progress after progress bar teardown.",
                )
            )
            record.relay.handle_status("Late status after label teardown.")
        pump_events(app=self.app)

        allow_finish.set()
        self._wait_for_task_completion(
            finished.is_set,
            description="destroyed-surface task completion",
        )
        pump_events(app=self.app)

        self.assertEqual(
            progress_messages,
            [
                "Preparing export surface...",
                "Late progress after progress bar teardown.",
            ],
        )
        self.assertEqual(
            status_messages,
            [
                "Waiting for release.",
                "Late status after label teardown.",
            ],
        )
        self.assertFalse(self.manager.has_running_tasks())

    def test_progress_dialog_wraps_long_status_updates_with_bounded_height(self):
        finished = threading.Event()
        allow_second_update = threading.Event()
        second_update_emitted = threading.Event()
        allow_finish = threading.Event()

        def _long_running(ctx):
            ctx.set_status("Starting export.")
            while not allow_second_update.is_set():
                time.sleep(0.01)
            ctx.set_status("Writing metadata tags for a moderately long export status message.")
            second_update_emitted.set()
            while not allow_finish.is_set():
                time.sleep(0.01)
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

        allow_finish.set()
        self._wait_for_task_completion(
            lambda: finished.is_set(),
            description="wrapped status dialog completion",
        )


if __name__ == "__main__":
    unittest.main()

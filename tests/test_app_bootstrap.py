import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.qt_test_helpers import require_qapplication

try:
    from isrc_manager import settings as app_settings
    from isrc_manager.app_bootstrap import get_or_create_application, run_desktop_application
    from isrc_manager.constants import SETTINGS_BASENAME
    from isrc_manager.startup_progress import StartupPhase, startup_phase_label
except Exception as exc:  # pragma: no cover - environment-specific fallback
    app_settings = None
    get_or_create_application = None
    run_desktop_application = None
    SETTINGS_BASENAME = None
    StartupPhase = None
    startup_phase_label = None
    BOOTSTRAP_IMPORT_ERROR = exc
else:
    BOOTSTRAP_IMPORT_ERROR = None

try:
    import ISRC_manager as app_module
except Exception as exc:  # pragma: no cover - environment-specific fallback
    app_module = None
    APP_IMPORT_ERROR = exc
else:
    APP_IMPORT_ERROR = None


class _FakeApplication:
    _instance = None

    def __init__(self, argv):
        self.argv = list(argv)
        self.exec_calls = 0
        self.process_events_calls = 0
        self._single_instance_lock = None
        self._emit_ready_on_process_events = None
        type(self)._instance = self

    @classmethod
    def instance(cls):
        return cls._instance

    def processEvents(self):
        self.process_events_calls += 1
        emit_ready = self._emit_ready_on_process_events
        if callable(emit_ready):
            self._emit_ready_on_process_events = None
            emit_ready()

    def exec(self):
        self.exec_calls += 1
        return 42


class _FakeWindow:
    def __init__(self, *, startup_feedback=None):
        self.show_calls = 0
        self._startup_feedback = startup_feedback

    def showMaximized(self):
        self.show_calls += 1

    def complete_startup_feedback(self):
        controller = self._startup_feedback
        if controller is None:
            return
        self._startup_feedback = None
        controller.finish(self)


class _FakeSignal:
    def __init__(self):
        self._callbacks = []

    def connect(self, callback):
        self._callbacks.append(callback)

    def emit(self):
        for callback in list(self._callbacks):
            callback()


class _FakeReadyWindow(_FakeWindow):
    def __init__(self, app, call_order, *, startup_feedback=None):
        super().__init__(startup_feedback=startup_feedback)
        self.startupReady = _FakeSignal()
        self._app = app
        self._call_order = call_order
        self.startupReady.connect(self.complete_startup_feedback)

    def showMaximized(self):
        self._call_order.append("show")
        super().showMaximized()
        self._app._emit_ready_on_process_events = self.startupReady.emit


class _FakeSplashController:
    def __init__(self, call_order):
        self.call_order = call_order
        self.phase_updates = []
        self.progress_updates = []
        self.messages = []
        self.finish_calls = []
        self.suspend_calls = 0
        self.resume_calls = 0
        self._finished = False

    def show(self):
        self.call_order.append("splash.show")

    def set_phase(self, phase, message_override=None):
        message = str(message_override or startup_phase_label(StartupPhase(phase)))
        self.phase_updates.append((phase, message))
        self.messages.append(message)
        self.call_order.append(("splash.phase", phase, message))

    def report_progress(self, progress, message_override=None, *, phase=None):
        message = str(message_override or "")
        self.progress_updates.append((int(progress), phase, message))
        self.call_order.append(("splash.progress", int(progress), phase, message))

    def suspend(self):
        self.suspend_calls += 1

    def resume(self):
        self.resume_calls += 1

    def finish(self, window):
        if self._finished:
            return
        self._finished = True
        self.finish_calls.append(window)
        self.call_order.append("splash.finish")


class _FakeBackgroundTasks:
    def __init__(self, titles=None):
        self._titles = list(titles or [])

    def has_running_tasks(self):
        return bool(self._titles)

    def active_task_titles(self):
        return list(self._titles)


class _FailingStatusLookupHost:
    def __init__(self, titles=None):
        self.background_tasks = _FakeBackgroundTasks(titles)
        self.find_children_calls = []

    def findChildren(self, widget_type, name=None, options=None):
        self.find_children_calls.append((widget_type, options))
        return []

    def statusBar(self):
        raise AssertionError("statusBar() should not be created during background task updates")


class AppBootstrapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if BOOTSTRAP_IMPORT_ERROR is not None:
            raise unittest.SkipTest(f"Bootstrap helpers unavailable: {BOOTSTRAP_IMPORT_ERROR}")

    def setUp(self):
        _FakeApplication._instance = None

    def tearDown(self):
        _FakeApplication._instance = None

    def test_get_or_create_application_reuses_existing_instance(self):
        existing = _FakeApplication(["existing"])

        app = get_or_create_application(["ignored"], application_factory=_FakeApplication)

        self.assertIs(app, existing)
        self.assertEqual(existing.argv, ["existing"])

    def test_run_desktop_application_initializes_lock_window_and_exec(self):
        window = _FakeWindow()
        message_box = mock.Mock()
        call_order = []

        result = run_desktop_application(
            argv=["catalog"],
            init_settings=lambda: call_order.append("settings"),
            install_qt_message_filter=lambda: call_order.append("filter"),
            enforce_single_instance=lambda timeout: call_order.append(("lock", timeout))
            or object(),
            window_factory=lambda startup_feedback=None: call_order.append("window") or window,
            application_factory=_FakeApplication,
            message_box=message_box,
            splash_factory=lambda _app: None,
        )

        app = _FakeApplication.instance()
        self.assertEqual(result, 42)
        self.assertEqual(call_order, ["settings", "filter", ("lock", 60000), "window"])
        self.assertIsNotNone(app)
        self.assertEqual(app.argv, ["catalog"])
        self.assertEqual(app.exec_calls, 1)
        self.assertIsNotNone(app._single_instance_lock)
        self.assertEqual(window.show_calls, 1)
        message_box.warning.assert_not_called()

    def test_run_desktop_application_warns_when_lock_is_unavailable(self):
        message_box = mock.Mock()
        window_factory = mock.Mock()
        splash_factory = mock.Mock()

        result = run_desktop_application(
            argv=["catalog"],
            init_settings=lambda: None,
            install_qt_message_filter=lambda: None,
            enforce_single_instance=lambda _timeout: None,
            window_factory=window_factory,
            application_factory=_FakeApplication,
            message_box=message_box,
            splash_factory=splash_factory,
        )

        self.assertEqual(result, 0)
        message_box.warning.assert_called_once()
        window_factory.assert_not_called()
        splash_factory.assert_not_called()

    def test_run_desktop_application_shows_and_finishes_splash_around_ready_signal(self):
        call_order = []
        app = _FakeApplication(["catalog"])
        splash = _FakeSplashController(call_order)
        window_holder = {}

        result = run_desktop_application(
            argv=["catalog"],
            init_settings=lambda: call_order.append("settings"),
            install_qt_message_filter=lambda: call_order.append("filter"),
            enforce_single_instance=lambda timeout: call_order.append(("lock", timeout))
            or object(),
            window_factory=lambda startup_feedback=None: call_order.append("window")
            or window_holder.setdefault(
                "window",
                _FakeReadyWindow(app, call_order, startup_feedback=startup_feedback),
            ),
            application_factory=_FakeApplication,
            message_box=mock.Mock(),
            splash_factory=lambda current_app: call_order.append("splash.factory") or splash,
        )
        window = window_holder["window"]

        self.assertEqual(result, 42)
        self.assertEqual(
            call_order,
            [
                "settings",
                "filter",
                ("lock", 60000),
                "splash.factory",
                "splash.show",
                ("splash.phase", StartupPhase.STARTING, "Starting application…"),
                "window",
                "show",
                "splash.finish",
            ],
        )
        self.assertEqual(
            splash.phase_updates,
            [(StartupPhase.STARTING, "Starting application…")],
        )
        self.assertEqual(splash.finish_calls, [window])


class SettingsIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if BOOTSTRAP_IMPORT_ERROR is not None:
            raise unittest.SkipTest(f"Settings helpers unavailable: {BOOTSTRAP_IMPORT_ERROR}")
        cls.app = require_qapplication()

    def test_init_settings_creates_and_preserves_profile_defaults(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_root = Path(tmpdir) / "qt-settings"
            preferred_root = Path(tmpdir) / "qt-local"
            with (
                mock.patch.object(
                    app_settings,
                    "settings_path",
                    return_value=settings_root / SETTINGS_BASENAME,
                ),
                mock.patch.object(
                    app_settings,
                    "preferred_data_root",
                    return_value=preferred_root,
                ),
            ):
                settings = app_settings.init_settings()
                self.assertTrue((settings_root / SETTINGS_BASENAME).exists())
                self.assertTrue(settings.value("app/initialized", False, type=bool))
                self.assertEqual(settings.value("ui/theme"), "system")
                settings.setValue("ui/theme", "dark")
                settings.sync()

                reopened = app_settings.init_settings()

        self.assertEqual(reopened.value("ui/theme"), "dark")

    def test_enforce_single_instance_returns_none_while_lock_is_held(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_root = Path(tmpdir) / "qt-settings"
            with mock.patch.object(
                app_settings,
                "lock_path",
                return_value=lock_root / "ISRCManager.lock",
            ):
                lock = app_settings.enforce_single_instance(timeout_ms=10)
                self.assertIsNotNone(lock)
                try:
                    self.assertIsNone(app_settings.enforce_single_instance(timeout_ms=10))
                finally:
                    lock.unlock()


class EntryPointDelegationTests(unittest.TestCase):
    def test_main_delegates_to_bootstrap_helper(self):
        if app_module is None:
            raise unittest.SkipTest(f"ISRC_manager import unavailable: {APP_IMPORT_ERROR}")

        with mock.patch.object(app_module, "run_desktop_application", return_value=9) as run:
            result = app_module.main()

        self.assertEqual(result, 9)
        self.assertEqual(run.call_count, 1)
        kwargs = run.call_args.kwargs
        self.assertEqual(kwargs["argv"], app_module.sys.argv)
        self.assertIs(kwargs["init_settings"], app_module.init_settings)
        self.assertIs(kwargs["install_qt_message_filter"], app_module._install_qt_message_filter)
        self.assertIs(kwargs["enforce_single_instance"], app_module.enforce_single_instance)
        self.assertIs(kwargs["window_factory"], app_module.App)


class AppWindowStatusTests(unittest.TestCase):
    def test_background_task_state_change_does_not_create_status_bar_early(self):
        if app_module is None:
            raise unittest.SkipTest(f"ISRC_manager import unavailable: {APP_IMPORT_ERROR}")

        host = _FailingStatusLookupHost(["Preparing profile database"])

        app_module.App._on_background_task_state_changed(host)

        self.assertEqual(len(host.find_children_calls), 1)


if __name__ == "__main__":
    unittest.main()

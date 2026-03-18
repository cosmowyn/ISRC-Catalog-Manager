import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.qt_test_helpers import require_qapplication

try:
    from isrc_manager import settings as app_settings
    from isrc_manager.app_bootstrap import get_or_create_application, run_desktop_application
    from isrc_manager.constants import SETTINGS_BASENAME
except Exception as exc:  # pragma: no cover - environment-specific fallback
    app_settings = None
    get_or_create_application = None
    run_desktop_application = None
    SETTINGS_BASENAME = None
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
        self._single_instance_lock = None
        type(self)._instance = self

    @classmethod
    def instance(cls):
        return cls._instance

    def exec(self):
        self.exec_calls += 1
        return 42


class _FakeWindow:
    def __init__(self):
        self.show_calls = 0

    def showMaximized(self):
        self.show_calls += 1


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
            window_factory=lambda: call_order.append("window") or window,
            application_factory=_FakeApplication,
            message_box=message_box,
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

        result = run_desktop_application(
            argv=["catalog"],
            init_settings=lambda: None,
            install_qt_message_filter=lambda: None,
            enforce_single_instance=lambda _timeout: None,
            window_factory=window_factory,
            application_factory=_FakeApplication,
            message_box=message_box,
        )

        self.assertEqual(result, 0)
        message_box.warning.assert_called_once()
        window_factory.assert_not_called()


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
            with mock.patch.object(
                app_settings,
                "settings_path",
                return_value=settings_root / SETTINGS_BASENAME,
            ), mock.patch.object(
                app_settings,
                "preferred_data_root",
                return_value=preferred_root,
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


if __name__ == "__main__":
    unittest.main()

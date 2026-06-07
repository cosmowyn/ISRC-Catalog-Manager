import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests.qt_test_helpers import join_thread_or_fail, require_qapplication, wait_for

try:
    from PySide6.QtGui import QColor, QImage, QPixmap
    from PySide6.QtWidgets import QWidget

    from isrc_manager import startup_splash
    from isrc_manager.startup_progress import StartupPhase
except Exception as exc:  # pragma: no cover - environment-specific fallback
    QColor = None
    QImage = None
    QPixmap = None
    QWidget = None
    startup_splash = None
    StartupPhase = None
    STARTUP_SPLASH_IMPORT_ERROR = exc
else:
    STARTUP_SPLASH_IMPORT_ERROR = None


class _FakeApplication:
    def __init__(self):
        self.process_events_calls = 0

    def processEvents(self):
        self.process_events_calls += 1


class _FakeSignal:
    def __init__(self):
        self.emissions = []

    def emit(self, *args):
        self.emissions.append(args)


class _FakeBridge:
    def __init__(self):
        self.request_show = _FakeSignal()
        self.request_phase = _FakeSignal()
        self.request_status = _FakeSignal()
        self.request_progress = _FakeSignal()
        self.request_suspend = _FakeSignal()
        self.request_resume = _FakeSignal()
        self.request_finish = _FakeSignal()


class _FakeSplash:
    def __init__(self, *, finish_error=None, supports_progress=True):
        self.finish_error = finish_error
        self.show_calls = 0
        self.hide_calls = 0
        self.close_calls = 0
        self.finish_calls = []
        self.messages = []
        self.clear_calls = 0
        self.progress_values = []
        if not supports_progress:
            self.set_progress = None

    def thread(self):
        return None

    def show(self):
        self.show_calls += 1

    def hide(self):
        self.hide_calls += 1

    def close(self):
        self.close_calls += 1

    def finish(self, window):
        self.finish_calls.append(window)
        if self.finish_error is not None:
            raise self.finish_error

    def showMessage(self, *args):
        self.messages.append(args)

    def clearMessage(self):
        self.clear_calls += 1

    def set_progress(self, value):
        self.progress_values.append(value)


class StartupSplashHelperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if STARTUP_SPLASH_IMPORT_ERROR is not None:
            raise unittest.SkipTest(
                f"Startup splash helpers unavailable: {STARTUP_SPLASH_IMPORT_ERROR}"
            )
        cls.app = require_qapplication()

    def _dispose_splash(self, splash):
        splash.close()
        splash.deleteLater()
        self.app.processEvents()

    def test_resolve_runtime_splash_asset_prefers_png(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            assets_dir = root / "build_assets"
            assets_dir.mkdir(parents=True, exist_ok=True)
            (assets_dir / "splash.jpg").write_bytes(b"jpg")
            png = assets_dir / "splash.png"
            png.write_bytes(b"png")

            resolved = startup_splash.resolve_runtime_splash_asset(resource_root=root)

        self.assertEqual(resolved, png)

    def test_create_startup_splash_controller_returns_none_without_asset(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)

            controller = startup_splash.create_startup_splash_controller(
                self.app,
                resource_root=root,
            )

        self.assertIsNone(controller)

    def test_create_startup_splash_controller_returns_none_for_invalid_image(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            assets_dir = root / "build_assets"
            assets_dir.mkdir(parents=True, exist_ok=True)
            (assets_dir / "splash.png").write_bytes(b"not-a-real-image")

            controller = startup_splash.create_startup_splash_controller(
                self.app,
                resource_root=root,
            )

        self.assertIsNone(controller)

    def test_create_startup_splash_controller_wraps_valid_image(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            assets_dir = root / "build_assets"
            assets_dir.mkdir(parents=True, exist_ok=True)
            image_path = assets_dir / "splash.png"

            image = QImage(32, 18, QImage.Format_ARGB32)
            image.fill(QColor("#204b6f"))
            self.assertTrue(image.save(str(image_path), "PNG"))

            controller = startup_splash.create_startup_splash_controller(
                self.app,
                resource_root=root,
            )
            self.assertIsNotNone(controller)

            window = QWidget()
            try:
                controller.show()
                controller.set_phase(StartupPhase.LOADING_SERVICES)
                controller.finish(window)
            finally:
                window.close()
                window.deleteLater()
                self._dispose_splash(controller._splash)
                self.app.processEvents()

    def test_controller_processes_events_after_show_phase_and_finish(self):
        fake_app = _FakeApplication()
        pixmap = QPixmap(32, 18)
        pixmap.fill(QColor("#204b6f"))
        splash = startup_splash._ReadableSplashScreen(pixmap)
        controller = startup_splash.StartupSplashController(fake_app, splash)
        window = QWidget()
        try:
            controller.show()
            controller.set_phase(StartupPhase.LOADING_SERVICES)
            controller.finish(window)
        finally:
            window.close()
            window.deleteLater()
            self._dispose_splash(splash)
        self.assertEqual(fake_app.process_events_calls, 3)

    def test_readable_splash_overlay_panel_is_inset_and_contains_progress_track(self):
        pixmap = QPixmap(900, 600)
        pixmap.fill(QColor("#204b6f"))
        splash = startup_splash._ReadableSplashScreen(pixmap)

        try:
            panel_rect = splash._overlay_panel_rect()
            progress_rect = splash._progress_rect(panel_rect)

            self.assertGreater(panel_rect.left(), 0)
            self.assertLess(panel_rect.right(), splash.width())
            self.assertLess(panel_rect.bottom(), splash.height())
            self.assertGreater(progress_rect.left(), panel_rect.left())
            self.assertLess(progress_rect.right(), panel_rect.right())
            self.assertGreater(progress_rect.top(), panel_rect.top())
        finally:
            self._dispose_splash(splash)

    def test_finish_is_idempotent_and_closes_without_window_handle(self):
        fake_app = _FakeApplication()
        pixmap = QPixmap(32, 18)
        pixmap.fill(QColor("#204b6f"))
        splash = startup_splash._ReadableSplashScreen(pixmap)
        controller = startup_splash.StartupSplashController(fake_app, splash)
        try:
            controller.show()
            controller.set_phase(StartupPhase.PREPARING_DATABASE)
            controller.finish(object())
            controller.finish(object())
            self.assertEqual(controller.current_phase, StartupPhase.READY)
            self.assertEqual(controller.current_progress, 100)
            self.assertGreaterEqual(fake_app.process_events_calls, 3)
        finally:
            self._dispose_splash(splash)

    def test_suspend_resume_preserves_current_phase(self):
        fake_app = _FakeApplication()
        pixmap = QPixmap(32, 18)
        pixmap.fill(QColor("#204b6f"))
        splash = startup_splash._ReadableSplashScreen(pixmap)
        controller = startup_splash.StartupSplashController(fake_app, splash)
        try:
            controller.show()
            controller.set_phase(StartupPhase.RESOLVING_STORAGE, "Waiting for migration decision…")
            controller.report_progress(
                42,
                "Waiting for migration decision…",
                phase=StartupPhase.RESOLVING_STORAGE,
            )
            controller.suspend()
            controller.resume()
            self.assertEqual(controller.current_phase, StartupPhase.RESOLVING_STORAGE)
            self.assertEqual(controller.current_message, "Waiting for migration decision…")
            self.assertEqual(controller.current_progress, 42)
        finally:
            self._dispose_splash(splash)

    def test_report_progress_is_monotonic_and_keeps_latest_phase_message(self):
        fake_app = _FakeApplication()
        pixmap = QPixmap(32, 18)
        pixmap.fill(QColor("#204b6f"))
        splash = startup_splash._ReadableSplashScreen(pixmap)
        controller = startup_splash.StartupSplashController(fake_app, splash)
        try:
            controller.show()

            controller.set_phase(StartupPhase.LOADING_CATALOG, "Loading catalog rows…")
            controller.report_progress(
                64, "Loaded catalog rows.", phase=StartupPhase.LOADING_CATALOG
            )
            controller.report_progress(
                61, "Older progress should not win.", phase=StartupPhase.LOADING_CATALOG
            )

            self.assertEqual(controller.current_phase, StartupPhase.LOADING_CATALOG)
            self.assertEqual(controller.current_progress, 64)
            self.assertEqual(controller.current_message, "Older progress should not win.")
        finally:
            self._dispose_splash(splash)

    def test_controller_queues_background_thread_updates_to_splash_thread(self):
        pixmap = QPixmap(32, 18)
        pixmap.fill(QColor("#204b6f"))
        splash = startup_splash._ReadableSplashScreen(pixmap)
        controller = startup_splash.StartupSplashController(self.app, splash)
        window = QWidget()
        try:
            controller.show()

            worker = threading.Thread(
                target=lambda: (
                    controller.set_phase(
                        StartupPhase.LOADING_CATALOG,
                        "Loading catalog rows from a worker thread…",
                    ),
                    controller.report_progress(
                        42,
                        "Worker-thread splash update delivered.",
                        phase=StartupPhase.LOADING_CATALOG,
                    ),
                )
            )
            worker.start()
            join_thread_or_fail(worker, description="startup splash worker thread")

            wait_for(
                lambda: controller.current_progress == 42,
                timeout_ms=1000,
                interval_ms=10,
                app=self.app,
                description="worker-thread splash progress propagation",
            )

            self.assertEqual(controller.current_phase, StartupPhase.LOADING_CATALOG)
            self.assertEqual(controller.current_message, "Worker-thread splash update delivered.")

            controller.finish(window)
        finally:
            window.close()
            window.deleteLater()
            self._dispose_splash(splash)
            self.app.processEvents()

    def test_bridge_handlers_dispatch_to_controller_slots(self):
        controller = mock.Mock()
        bridge = startup_splash._SplashThreadBridge(controller, None)
        try:
            bridge._handle_show()
            bridge._handle_phase(StartupPhase.LOADING_CATALOG, "Loading catalog…")
            bridge._handle_status("Starting")
            bridge._handle_progress(33, "One third", StartupPhase.PREPARING_DATABASE)
            bridge._handle_suspend()
            bridge._handle_resume()
            bridge._handle_finish("window")
        finally:
            bridge.deleteLater()
            self.app.processEvents()

        controller._show_now.assert_called_once_with()
        controller._set_phase_now.assert_called_once_with(
            StartupPhase.LOADING_CATALOG,
            "Loading catalog…",
        )
        controller._set_status_now.assert_called_once_with("Starting")
        controller._report_progress_now.assert_called_once_with(
            33,
            message_override="One third",
            phase=StartupPhase.PREPARING_DATABASE,
        )
        controller._suspend_now.assert_called_once_with()
        controller._resume_now.assert_called_once_with()
        controller._finish_now.assert_called_once_with("window")

    def test_public_methods_emit_bridge_requests_off_splash_thread(self):
        controller = startup_splash.StartupSplashController(
            _FakeApplication(),
            _FakeSplash(),
        )
        bridge = _FakeBridge()
        controller._bridge = bridge

        with mock.patch.object(controller, "_is_splash_thread", return_value=False):
            controller.show()
            controller.set_phase(StartupPhase.LOADING_CATALOG, "Loading catalog…")
            controller.set_status("Bootstrapping")
            controller.report_progress(
                72,
                "Almost ready",
                phase=StartupPhase.LOADING_SERVICES,
            )
            controller.suspend()
            controller.resume()
            controller.finish("window")

        self.assertEqual(bridge.request_show.emissions, [()])
        self.assertEqual(
            bridge.request_phase.emissions,
            [(StartupPhase.LOADING_CATALOG, "Loading catalog…")],
        )
        self.assertEqual(bridge.request_status.emissions, [("Bootstrapping",)])
        self.assertEqual(
            bridge.request_progress.emissions,
            [(72, "Almost ready", StartupPhase.LOADING_SERVICES)],
        )
        self.assertEqual(bridge.request_suspend.emissions, [()])
        self.assertEqual(bridge.request_resume.emissions, [()])
        self.assertEqual(bridge.request_finish.emissions, [("window",)])

    def test_now_methods_respect_finished_and_suspended_guardrails(self):
        splash = _FakeSplash()
        controller = startup_splash.StartupSplashController(_FakeApplication(), splash)

        controller._finished = True
        controller._show_now()
        controller._set_phase_now(StartupPhase.LOADING_CATALOG)
        controller._set_status_now("Ignored")
        controller._report_progress_now(10, "Ignored")
        controller._suspend_now()
        controller._resume_now()
        controller._finish_now("window")
        self.assertEqual(splash.show_calls, 0)
        self.assertEqual(controller.current_message, "")

        suspended_controller = startup_splash.StartupSplashController(
            _FakeApplication(),
            _FakeSplash(),
        )
        suspended_controller._suspended = True
        suspended_controller._show_now()
        self.assertTrue(suspended_controller._shown)
        self.assertEqual(suspended_controller._splash.show_calls, 0)

        hidden_controller = startup_splash.StartupSplashController(
            _FakeApplication(),
            _FakeSplash(),
        )
        hidden_controller._suspend_now()
        hidden_controller._resume_now()
        self.assertEqual(hidden_controller._splash.hide_calls, 0)
        self.assertEqual(hidden_controller._splash.show_calls, 0)

    def test_report_progress_uses_phase_label_when_no_message_is_set(self):
        controller = startup_splash.StartupSplashController(_FakeApplication(), _FakeSplash())

        controller._report_progress_now(25, phase=StartupPhase.LOADING_CATALOG)

        self.assertEqual(controller.current_phase, StartupPhase.LOADING_CATALOG)
        self.assertEqual(controller.current_progress, 25)
        self.assertEqual(
            controller.current_message,
            "Loading catalog…",
        )

    def test_finish_closes_splash_when_finish_raises(self):
        splash = _FakeSplash(finish_error=RuntimeError("finish failed"))
        controller = startup_splash.StartupSplashController(_FakeApplication(), splash)
        window = SimpleNamespace(windowHandle=lambda: object())

        controller.finish(window)

        self.assertEqual(splash.finish_calls, [window])
        self.assertEqual(splash.close_calls, 1)
        self.assertEqual(controller.current_phase, StartupPhase.READY)

    def test_render_and_process_event_edges_without_progress_or_app_hook(self):
        fake_app = _FakeApplication()
        splash = _FakeSplash(supports_progress=False)
        controller = startup_splash.StartupSplashController(fake_app, splash)

        controller._render_current_state()
        self.assertEqual(splash.clear_calls, 1)
        self.assertEqual(fake_app.process_events_calls, 1)

        with mock.patch.object(controller, "_is_splash_thread", return_value=False):
            controller._process_events()
        self.assertEqual(fake_app.process_events_calls, 1)

        no_hook_controller = startup_splash.StartupSplashController(
            SimpleNamespace(),
            _FakeSplash(),
        )
        no_hook_controller._process_events()


if __name__ == "__main__":
    unittest.main()

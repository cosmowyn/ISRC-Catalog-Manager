import threading
import tempfile
import unittest
from pathlib import Path

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


class StartupSplashHelperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if STARTUP_SPLASH_IMPORT_ERROR is not None:
            raise unittest.SkipTest(
                f"Startup splash helpers unavailable: {STARTUP_SPLASH_IMPORT_ERROR}"
            )
        cls.app = require_qapplication()

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
            splash.close()
        self.assertEqual(fake_app.process_events_calls, 3)

    def test_finish_is_idempotent_and_closes_without_window_handle(self):
        fake_app = _FakeApplication()
        pixmap = QPixmap(32, 18)
        pixmap.fill(QColor("#204b6f"))
        splash = startup_splash._ReadableSplashScreen(pixmap)
        controller = startup_splash.StartupSplashController(fake_app, splash)
        controller.show()
        controller.set_phase(StartupPhase.PREPARING_DATABASE)
        controller.finish(object())
        controller.finish(object())
        self.assertEqual(controller.current_phase, StartupPhase.READY)
        self.assertEqual(controller.current_progress, 100)
        self.assertGreaterEqual(fake_app.process_events_calls, 3)

    def test_suspend_resume_preserves_current_phase(self):
        fake_app = _FakeApplication()
        pixmap = QPixmap(32, 18)
        pixmap.fill(QColor("#204b6f"))
        splash = startup_splash._ReadableSplashScreen(pixmap)
        controller = startup_splash.StartupSplashController(fake_app, splash)
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

    def test_report_progress_is_monotonic_and_keeps_latest_phase_message(self):
        fake_app = _FakeApplication()
        pixmap = QPixmap(32, 18)
        pixmap.fill(QColor("#204b6f"))
        splash = startup_splash._ReadableSplashScreen(pixmap)
        controller = startup_splash.StartupSplashController(fake_app, splash)
        controller.show()

        controller.set_phase(StartupPhase.LOADING_CATALOG, "Loading catalog rows…")
        controller.report_progress(64, "Loaded catalog rows.", phase=StartupPhase.LOADING_CATALOG)
        controller.report_progress(
            61, "Older progress should not win.", phase=StartupPhase.LOADING_CATALOG
        )

        self.assertEqual(controller.current_phase, StartupPhase.LOADING_CATALOG)
        self.assertEqual(controller.current_progress, 64)
        self.assertEqual(controller.current_message, "Older progress should not win.")

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
            splash.close()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()

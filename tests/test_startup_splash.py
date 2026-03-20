import tempfile
import unittest
from pathlib import Path

from tests.qt_test_helpers import require_qapplication

try:
    from PySide6.QtGui import QColor, QImage
    from PySide6.QtWidgets import QWidget

    from isrc_manager import startup_splash
except Exception as exc:  # pragma: no cover - environment-specific fallback
    QColor = None
    QImage = None
    QWidget = None
    startup_splash = None
    STARTUP_SPLASH_IMPORT_ERROR = exc
else:
    STARTUP_SPLASH_IMPORT_ERROR = None


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
                controller.set_status("Loading services…")
                controller.finish(window)
            finally:
                window.close()
                window.deleteLater()
                self.app.processEvents()


if __name__ == "__main__":
    unittest.main()

"""Qt-native startup splash helpers."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QSplashScreen

from .paths import RES_DIR

SPLASH_BASENAME = "splash"
SPLASH_EXTENSIONS = (".png", ".jpg", ".jpeg", ".bmp", ".gif")
STARTUP_SPLASH_CONTROLLER_ATTR = "_startup_splash_controller"


def resolve_runtime_splash_asset(*, resource_root: str | Path | None = None) -> Path | None:
    """Return the bundled startup splash asset when one is available."""
    root = Path(resource_root) if resource_root is not None else RES_DIR()
    for ext in SPLASH_EXTENSIONS:
        candidate = root / "build_assets" / f"{SPLASH_BASENAME}{ext}"
        if candidate.exists():
            return candidate
    return None


class _ReadableSplashScreen(QSplashScreen):
    """Small QSplashScreen variant that improves text readability."""

    _BAND_HEIGHT = 58
    _TEXT_MARGIN = 18
    _BOTTOM_PADDING = 12

    def drawContents(self, painter: QPainter) -> None:
        message = self.message()
        if not message:
            return

        painter.save()
        band_rect = QRect(0, self.height() - self._BAND_HEIGHT, self.width(), self._BAND_HEIGHT)
        painter.fillRect(band_rect, QColor(0, 0, 0, 152))

        text_rect = band_rect.adjusted(
            self._TEXT_MARGIN,
            0,
            -self._TEXT_MARGIN,
            -self._BOTTOM_PADDING,
        )
        font = painter.font()
        font.setPointSizeF(max(font.pointSizeF(), 10.5))
        painter.setFont(font)
        painter.setPen(QColor("#f7f7f7"))
        painter.drawText(
            text_rect,
            int(Qt.AlignLeft | Qt.AlignBottom | Qt.TextSingleLine),
            message,
        )
        painter.restore()


class StartupSplashController:
    """Thin controller around QSplashScreen for pre-event-loop startup."""

    def __init__(self, app: QApplication, splash: QSplashScreen):
        self._app = app
        self._splash = splash
        self._finished = False

    def show(self) -> None:
        if self._finished:
            return
        self._splash.show()
        self._process_events()

    def set_status(self, message: str) -> None:
        if self._finished:
            return
        self._splash.showMessage(
            str(message),
            int(Qt.AlignLeft | Qt.AlignBottom),
            QColor("#f7f7f7"),
        )
        self._process_events()

    def finish(self, window) -> None:
        if self._finished:
            return
        self._finished = True
        if window is not None and hasattr(window, "windowHandle"):
            self._splash.finish(window)
        else:
            self._splash.close()
        self._process_events()

    def _process_events(self) -> None:
        process_events = getattr(self._app, "processEvents", None)
        if callable(process_events):
            process_events()


def create_startup_splash_controller(
    app: QApplication,
    *,
    resource_root: str | Path | None = None,
) -> StartupSplashController | None:
    """Create a splash controller when a readable runtime splash asset is available."""
    asset_path = resolve_runtime_splash_asset(resource_root=resource_root)
    if asset_path is None:
        return None

    pixmap = QPixmap(str(asset_path))
    if pixmap.isNull():
        return None

    return StartupSplashController(app, _ReadableSplashScreen(pixmap))

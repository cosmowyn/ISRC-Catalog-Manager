"""Qt-native startup splash helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QSplashScreen

from .paths import RES_DIR
from .startup_progress import StartupPhase, startup_phase_label

SPLASH_BASENAME = "splash"
SPLASH_EXTENSIONS = (".png", ".jpg", ".jpeg", ".bmp", ".gif")


class StartupFeedbackProtocol(Protocol):
    """Minimal feedback contract shared by bootstrap and direct App() callers."""

    def show(self) -> None: ...

    def set_status(self, message: str) -> None: ...

    def report_progress(
        self,
        progress: int,
        message_override: str | None = None,
        *,
        phase: StartupPhase | None = None,
    ) -> None: ...

    def set_phase(
        self,
        phase: StartupPhase,
        message_override: str | None = None,
    ) -> None: ...

    def suspend(self) -> None: ...

    def resume(self) -> None: ...

    def finish(self, window) -> None: ...


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

    _BAND_HEIGHT = 78
    _TEXT_MARGIN = 18
    _TOP_PADDING = 10
    _BOTTOM_PADDING = 12
    _PROGRESS_HEIGHT = 10
    _PROGRESS_MARGIN_TOP = 9
    _PROGRESS_RADIUS = 5

    def __init__(self, pixmap: QPixmap):
        super().__init__(pixmap)
        self._progress = 0

    def set_progress(self, value: int) -> None:
        self._progress = max(0, min(100, int(value)))
        self.repaint()

    def drawContents(self, painter: QPainter) -> None:
        message = self.message()
        if not message and self._progress <= 0:
            return

        painter.save()
        band_rect = QRect(0, self.height() - self._BAND_HEIGHT, self.width(), self._BAND_HEIGHT)
        painter.fillRect(band_rect, QColor(0, 0, 0, 152))

        text_rect = band_rect.adjusted(
            self._TEXT_MARGIN,
            self._TOP_PADDING,
            -self._TEXT_MARGIN,
            -(self._BOTTOM_PADDING + self._PROGRESS_HEIGHT + self._PROGRESS_MARGIN_TOP),
        )
        font = painter.font()
        font.setPointSizeF(max(font.pointSizeF(), 10.5))
        painter.setFont(font)
        painter.setPen(QColor("#f7f7f7"))
        progress_text = f"{self._progress}%"
        reserved_width = painter.fontMetrics().horizontalAdvance(progress_text) + 24
        message_width = max(120, text_rect.width() - reserved_width)
        rendered_message = painter.fontMetrics().elidedText(
            message,
            Qt.ElideRight,
            message_width,
        )
        painter.drawText(
            text_rect,
            int(Qt.AlignLeft | Qt.AlignVCenter | Qt.TextSingleLine),
            rendered_message,
        )
        painter.drawText(
            text_rect,
            int(Qt.AlignRight | Qt.AlignVCenter | Qt.TextSingleLine),
            progress_text,
        )

        progress_rect = QRect(
            band_rect.left() + self._TEXT_MARGIN,
            band_rect.bottom() - self._BOTTOM_PADDING - self._PROGRESS_HEIGHT + 1,
            band_rect.width() - (self._TEXT_MARGIN * 2),
            self._PROGRESS_HEIGHT,
        )
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#1f1f1f"))
        painter.drawRoundedRect(
            progress_rect,
            self._PROGRESS_RADIUS,
            self._PROGRESS_RADIUS,
        )
        if self._progress > 0:
            chunk_width = max(
                self._PROGRESS_RADIUS * 2,
                round(progress_rect.width() * (self._progress / 100.0)),
            )
            chunk_rect = QRect(
                progress_rect.left(),
                progress_rect.top(),
                min(progress_rect.width(), chunk_width),
                progress_rect.height(),
            )
            painter.setBrush(QColor("#f0b35c"))
            painter.drawRoundedRect(
                chunk_rect,
                self._PROGRESS_RADIUS,
                self._PROGRESS_RADIUS,
            )
        painter.restore()


class StartupSplashController:
    """Thin controller around QSplashScreen for pre-event-loop startup."""

    def __init__(self, app: QApplication, splash: QSplashScreen):
        self._app = app
        self._splash = splash
        self._finished = False
        self._shown = False
        self._suspended = False
        self._phase: StartupPhase | None = None
        self._message = ""
        self._progress = 0

    @property
    def current_phase(self) -> StartupPhase | None:
        return self._phase

    @property
    def current_message(self) -> str:
        return self._message

    @property
    def current_progress(self) -> int:
        return self._progress

    def show(self) -> None:
        if self._finished:
            return
        self._shown = True
        if self._suspended:
            return
        self._splash.show()
        self._render_current_state(process_events=False)
        self._process_events()

    def set_phase(
        self,
        phase: StartupPhase,
        message_override: str | None = None,
    ) -> None:
        if self._finished:
            return
        self._phase = StartupPhase(phase)
        self._message = str(message_override or startup_phase_label(self._phase))
        self._render_current_state()

    def set_status(self, message: str) -> None:
        if self._finished:
            return
        self._message = str(message)
        self._render_current_state()

    def report_progress(
        self,
        progress: int,
        message_override: str | None = None,
        *,
        phase: StartupPhase | None = None,
    ) -> None:
        if self._finished:
            return
        if phase is not None:
            self._phase = StartupPhase(phase)
        self._progress = max(self._progress, max(0, min(100, int(progress))))
        if message_override is not None:
            self._message = str(message_override)
        elif self._phase is not None and not self._message:
            self._message = startup_phase_label(self._phase)
        self._render_current_state()

    def suspend(self) -> None:
        if self._finished or self._suspended:
            return
        self._suspended = True
        if self._shown:
            self._splash.hide()
        self._process_events()

    def resume(self) -> None:
        if self._finished or not self._suspended:
            return
        self._suspended = False
        if self._shown:
            self._splash.show()
            self._render_current_state(process_events=False)
        self._process_events()

    def finish(self, window) -> None:
        if self._finished:
            return
        self._finished = True
        self._suspended = False
        self._phase = StartupPhase.READY
        self._progress = 100
        self._message = startup_phase_label(StartupPhase.READY)
        self._render_current_state(process_events=False)
        if window is not None and hasattr(window, "windowHandle"):
            try:
                self._splash.finish(window)
            except Exception:
                self._splash.close()
        else:
            self._splash.close()
        self._process_events()

    def _render_current_state(self, *, process_events: bool = True) -> None:
        set_progress = getattr(self._splash, "set_progress", None)
        if callable(set_progress):
            set_progress(self._progress)
        if self._message:
            self._splash.showMessage(
                self._message,
                int(Qt.AlignLeft | Qt.AlignBottom),
                QColor("#f7f7f7"),
            )
        else:
            self._splash.clearMessage()
        if process_events and not self._suspended:
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

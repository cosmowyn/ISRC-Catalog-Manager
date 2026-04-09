"""Qt-native startup splash helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from PySide6.QtCore import QObject, QRect, Qt, QThread, Signal, Slot
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
        self.update()

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


class _SplashThreadBridge(QObject):
    """Marshals splash updates back onto the splash object's GUI thread."""

    request_show = Signal()
    request_phase = Signal(object, object)
    request_status = Signal(str)
    request_progress = Signal(int, object, object)
    request_suspend = Signal()
    request_resume = Signal()
    request_finish = Signal(object)

    def __init__(self, controller: "StartupSplashController", target_thread: QThread | None):
        super().__init__()
        self._controller = controller
        if target_thread is not None:
            self.moveToThread(target_thread)
        self.request_show.connect(self._handle_show, Qt.QueuedConnection)
        self.request_phase.connect(self._handle_phase, Qt.QueuedConnection)
        self.request_status.connect(self._handle_status, Qt.QueuedConnection)
        self.request_progress.connect(self._handle_progress, Qt.QueuedConnection)
        self.request_suspend.connect(self._handle_suspend, Qt.QueuedConnection)
        self.request_resume.connect(self._handle_resume, Qt.QueuedConnection)
        self.request_finish.connect(self._handle_finish, Qt.QueuedConnection)

    @Slot()
    def _handle_show(self) -> None:
        self._controller._show_now()

    @Slot(object, object)
    def _handle_phase(self, phase: object, message_override: object) -> None:
        self._controller._set_phase_now(phase, message_override)

    @Slot(str)
    def _handle_status(self, message: str) -> None:
        self._controller._set_status_now(message)

    @Slot(int, object, object)
    def _handle_progress(
        self,
        progress: int,
        message_override: object,
        phase: object,
    ) -> None:
        self._controller._report_progress_now(
            progress,
            message_override=message_override,
            phase=phase,
        )

    @Slot()
    def _handle_suspend(self) -> None:
        self._controller._suspend_now()

    @Slot()
    def _handle_resume(self) -> None:
        self._controller._resume_now()

    @Slot(object)
    def _handle_finish(self, window: object) -> None:
        self._controller._finish_now(window)

class StartupSplashController:
    """Thin controller around QSplashScreen for pre-event-loop startup."""

    def __init__(self, app: QApplication, splash: QSplashScreen):
        self._app = app
        self._splash = splash
        self._bridge = _SplashThreadBridge(self, splash.thread())
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
        if not self._is_splash_thread():
            self._bridge.request_show.emit()
            return
        self._show_now()

    def _show_now(self) -> None:
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
        if not self._is_splash_thread():
            self._bridge.request_phase.emit(StartupPhase(phase), message_override)
            return
        self._set_phase_now(phase, message_override)

    def _set_phase_now(
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
        if not self._is_splash_thread():
            self._bridge.request_status.emit(str(message or ""))
            return
        self._set_status_now(message)

    def _set_status_now(self, message: str) -> None:
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
        if not self._is_splash_thread():
            self._bridge.request_progress.emit(
                int(progress),
                message_override,
                StartupPhase(phase) if phase is not None else None,
            )
            return
        self._report_progress_now(progress, message_override=message_override, phase=phase)

    def _report_progress_now(
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
        if not self._is_splash_thread():
            self._bridge.request_suspend.emit()
            return
        self._suspend_now()

    def _suspend_now(self) -> None:
        if self._finished or self._suspended:
            return
        self._suspended = True
        if self._shown:
            self._splash.hide()
        self._process_events()

    def resume(self) -> None:
        if not self._is_splash_thread():
            self._bridge.request_resume.emit()
            return
        self._resume_now()

    def _resume_now(self) -> None:
        if self._finished or not self._suspended:
            return
        self._suspended = False
        if self._shown:
            self._splash.show()
            self._render_current_state(process_events=False)
        self._process_events()

    def finish(self, window) -> None:
        if not self._is_splash_thread():
            self._bridge.request_finish.emit(window)
            return
        self._finish_now(window)

    def _finish_now(self, window) -> None:
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
        if not self._is_splash_thread():
            return
        process_events = getattr(self._app, "processEvents", None)
        if callable(process_events):
            process_events()

    def _is_splash_thread(self) -> bool:
        splash_thread = self._splash.thread()
        current_thread = QThread.currentThread()
        return splash_thread is None or current_thread == splash_thread


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

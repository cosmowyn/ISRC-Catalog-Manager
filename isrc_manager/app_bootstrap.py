"""Application bootstrap helpers for the desktop shell."""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence

from PySide6.QtWidgets import QApplication, QMessageBox

from .constants import APP_NAME
from .paths import configure_qt_application_identity
from .startup_splash import (
    STARTUP_SPLASH_CONTROLLER_ATTR,
    create_startup_splash_controller,
)


def get_or_create_application(
    argv: Sequence[str] | None = None,
    *,
    application_factory=QApplication,
):
    """Return the current QApplication instance or create one."""
    app = application_factory.instance()
    if app is not None:
        configure_qt_application_identity(app)
        return app
    app = application_factory(list(sys.argv if argv is None else argv))
    configure_qt_application_identity(app)
    return app


def run_desktop_application(
    *,
    argv: Sequence[str] | None = None,
    init_settings: Callable[[], object],
    install_qt_message_filter: Callable[[], None],
    enforce_single_instance: Callable[[int], object | None],
    window_factory: Callable[[], object],
    application_factory=QApplication,
    message_box=QMessageBox,
    splash_factory: Callable[[QApplication], object | None] = create_startup_splash_controller,
    show_method_name: str = "showMaximized",
    lock_timeout_ms: int = 60000,
) -> int:
    """Bootstrap the desktop shell while keeping the entry point thin and testable."""
    init_settings()
    install_qt_message_filter()

    app = get_or_create_application(argv, application_factory=application_factory)
    lock = enforce_single_instance(lock_timeout_ms)
    if lock is None:
        message_box.warning(None, "Already running", f"{APP_NAME} is already running.")
        return 0

    app._single_instance_lock = lock
    splash = splash_factory(app)
    if splash is not None:
        setattr(app, STARTUP_SPLASH_CONTROLLER_ATTR, splash)
        splash.show()
        splash.set_status("Starting application…")

    window = window_factory()
    ready_signal = getattr(window, "startupReady", None)
    splash_finished = False

    def _finish_startup_splash() -> None:
        nonlocal splash_finished
        if splash is None or splash_finished:
            return
        splash_finished = True
        try:
            splash.finish(window)
        finally:
            if getattr(app, STARTUP_SPLASH_CONTROLLER_ATTR, None) is splash:
                delattr(app, STARTUP_SPLASH_CONTROLLER_ATTR)

    if splash is not None and callable(getattr(ready_signal, "connect", None)):
        ready_signal.connect(_finish_startup_splash)

    getattr(window, show_method_name)()
    process_events = getattr(app, "processEvents", None)
    if callable(process_events):
        process_events()

    if splash is not None and not callable(getattr(ready_signal, "connect", None)):
        _finish_startup_splash()

    try:
        return app.exec()
    finally:
        _finish_startup_splash()

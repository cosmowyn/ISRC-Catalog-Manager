"""Application bootstrap helpers for the desktop shell."""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence
from inspect import Parameter, signature

from PySide6.QtWidgets import QApplication, QMessageBox

from .constants import APP_NAME
from .paths import configure_qt_application_identity
from .startup_progress import StartupPhase
from .startup_splash import StartupFeedbackProtocol, create_startup_splash_controller


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


def _window_factory_supports_startup_feedback(window_factory: Callable[..., object]) -> bool:
    try:
        params = signature(window_factory).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(
        parameter.kind == Parameter.VAR_KEYWORD or parameter.name == "startup_feedback"
        for parameter in params
    )


def run_desktop_application(
    *,
    argv: Sequence[str] | None = None,
    init_settings: Callable[[], object],
    install_qt_message_filter: Callable[[], None],
    enforce_single_instance: Callable[[int], object | None],
    window_factory: Callable[..., object],
    application_factory=QApplication,
    message_box=QMessageBox,
    splash_factory: Callable[[QApplication], StartupFeedbackProtocol | None] = (
        create_startup_splash_controller
    ),
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
        splash.show()
        splash.set_phase(StartupPhase.STARTING)

    if _window_factory_supports_startup_feedback(window_factory):
        window = window_factory(startup_feedback=splash)
    else:
        window = window_factory()

    getattr(window, show_method_name)()
    process_events = getattr(app, "processEvents", None)
    if callable(process_events):
        process_events()

    try:
        return app.exec()
    finally:
        if splash is not None:
            splash.finish(window)

"""Application bootstrap helpers for the desktop shell."""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence

from PySide6.QtWidgets import QApplication, QMessageBox

from .constants import APP_NAME
from .paths import configure_qt_application_identity


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

    window = window_factory()
    getattr(window, show_method_name)()
    return app.exec()

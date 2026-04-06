"""Shared Qt test helpers for headless-safe dialog and app-shell coverage."""

from __future__ import annotations

import threading
import time
import unittest
from typing import Callable

from isrc_manager.external_launch import install_test_external_launch_guard

try:
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication
except ImportError as exc:  # pragma: no cover - environment-specific fallback
    QCoreApplication = None
    QEvent = None
    QApplication = None
    QT_IMPORT_ERROR = exc
else:
    QT_IMPORT_ERROR = None


def require_qapplication():
    """Return a QApplication for tests or skip cleanly when Qt is unavailable."""
    install_test_external_launch_guard()
    if QApplication is None:
        raise unittest.SkipTest(f"PySide6 QtWidgets unavailable: {QT_IMPORT_ERROR}")
    return QApplication.instance() or QApplication([])


def pump_events(*, app: QApplication | None = None, cycles: int = 1) -> None:
    """Process the Qt event queue a bounded number of times."""
    qt_app = app or require_qapplication()
    for _ in range(max(1, cycles)):
        qt_app.processEvents()
        if QCoreApplication is not None and QEvent is not None:
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            qt_app.processEvents()


def wait_for(
    predicate: Callable[[], bool],
    *,
    timeout_ms: int = 1000,
    interval_ms: int = 10,
    app: QApplication | None = None,
    description: str = "condition",
) -> None:
    """Poll a condition with optional Qt event pumping and fail explicitly on timeout."""
    deadline = time.monotonic() + (timeout_ms / 1000.0)
    interval_seconds = max(interval_ms, 1) / 1000.0

    while time.monotonic() < deadline:
        if predicate():
            return
        if app is not None:
            pump_events(app=app)
        time.sleep(interval_seconds)

    if app is not None:
        pump_events(app=app)
    if predicate():
        return
    raise AssertionError(f"Timed out after {timeout_ms} ms waiting for {description}.")


def join_thread_or_fail(
    thread: threading.Thread,
    *,
    timeout_seconds: float = 1.0,
    description: str = "thread",
) -> None:
    """Join a worker thread with a hard bound and fail clearly if it stalls."""
    thread.join(timeout=timeout_seconds)
    if thread.is_alive():
        raise AssertionError(
            f"Timed out after {timeout_seconds:.2f}s waiting for {description} to finish."
        )

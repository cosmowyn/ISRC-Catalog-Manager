"""Shared Qt test helpers for headless-safe dialog and app-shell coverage."""

from __future__ import annotations

import unittest

try:
    from PySide6.QtWidgets import QApplication
except ImportError as exc:  # pragma: no cover - environment-specific fallback
    QApplication = None
    QT_IMPORT_ERROR = exc
else:
    QT_IMPORT_ERROR = None


def require_qapplication():
    """Return a QApplication for tests or skip cleanly when Qt is unavailable."""
    if QApplication is None:
        raise unittest.SkipTest(f"PySide6 QtWidgets unavailable: {QT_IMPORT_ERROR}")
    return QApplication.instance() or QApplication([])

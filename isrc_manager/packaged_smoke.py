"""Packaged application smoke-test entry point."""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence
from typing import TextIO

from PySide6.QtWidgets import QApplication

from .app_bootstrap import get_or_create_application
from .constants import APP_NAME
from .settings import init_settings
from .version import current_app_version

PACKAGED_SMOKE_TEST_ARGUMENT = "--packaged-smoke-test"


def _filtered_smoke_argv(argv: Sequence[str] | None) -> list[str]:
    values = list(sys.argv if argv is None else argv)
    filtered = [str(value) for value in values if value != PACKAGED_SMOKE_TEST_ARGUMENT]
    return filtered or [APP_NAME]


def run_packaged_smoke_test(
    argv: Sequence[str] | None = None,
    *,
    application_factory=QApplication,
    install_qt_message_filter: Callable[[], None] | None = None,
    output: TextIO | None = None,
) -> int:
    """Create the real Qt application object and exit without showing the UI."""
    init_settings()
    if install_qt_message_filter is not None:
        install_qt_message_filter()

    app = get_or_create_application(
        _filtered_smoke_argv(argv),
        application_factory=application_factory,
    )
    process_events = getattr(app, "processEvents", None)
    if callable(process_events):
        process_events()

    stream = output if output is not None else getattr(sys, "stdout", None)
    if stream is not None:
        print(
            f"{APP_NAME} packaged smoke test OK ({current_app_version()})",
            file=stream,
            flush=True,
        )

    quit_app = getattr(app, "quit", None)
    if callable(quit_app):
        quit_app()
    return 0

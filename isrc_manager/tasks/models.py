"""Shared task dataclasses for background execution."""

from __future__ import annotations

from dataclasses import dataclass


class TaskCancelledError(RuntimeError):
    """Raised when a cancellable background task is aborted cooperatively."""


@dataclass(slots=True)
class TaskProgressUpdate:
    value: int | None = None
    maximum: int | None = None
    message: str | None = None


@dataclass(slots=True)
class TaskFailure:
    message: str
    traceback_text: str

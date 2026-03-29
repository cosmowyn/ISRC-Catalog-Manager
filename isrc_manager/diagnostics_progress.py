"""Truthful diagnostics-startup progress helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

ProgressCallback = Callable[[int, int, str], None]
StatusCallback = Callable[[str], None]


class DiagnosticsProgressTracker:
    """Tracks completed diagnostics work units and emits truthful progress."""

    def __init__(
        self,
        *,
        total_units: int,
        progress_callback: ProgressCallback | None = None,
        status_callback: StatusCallback | None = None,
    ) -> None:
        self.total_units = max(1, int(total_units or 1))
        self.progress_callback = progress_callback
        self.status_callback = status_callback
        self.completed_units = 0
        self.current_message = ""
        self._last_signature: tuple[int, int, str] | None = None

    def set_status(self, message: str) -> None:
        self._emit(self.completed_units, str(message or ""))

    def set_message(self, message: str) -> None:
        self.set_status(message)

    def advance(self, units: int = 1, *, message: str | None = None) -> None:
        increment = max(0, int(units or 0))
        self.report_absolute(
            self.completed_units + increment,
            message=message or self.current_message,
        )

    def complete(self, message: str, *, units: int = 1) -> None:
        self.advance(units=units, message=message)

    def report_absolute(self, completed_units: int, *, message: str | None = None) -> None:
        clean_units = max(self.completed_units, min(self.total_units, int(completed_units or 0)))
        self._emit(clean_units, str(message or self.current_message or ""))

    def finish(self, message: str) -> None:
        self.report_absolute(self.total_units, message=message)

    def report_nested(
        self,
        *,
        start_units: int,
        span_units: int,
        value: int,
        maximum: int,
        message: str,
    ) -> None:
        clean_span = max(1, int(span_units or 1))
        clean_maximum = max(1, int(maximum or 1))
        ratio = max(0.0, min(1.0, float(int(value or 0)) / float(clean_maximum)))
        scaled_units = int(start_units or 0) + int(round(clean_span * ratio))
        self.report_absolute(scaled_units, message=message)

    def segment(self, total_units: int) -> "DiagnosticsProgressSegment":
        return DiagnosticsProgressSegment(
            tracker=self,
            start_units=self.completed_units,
            total_units=max(1, int(total_units or 1)),
        )

    def _emit(self, completed_units: int, message: str) -> None:
        clean_units = max(self.completed_units, min(self.total_units, int(completed_units or 0)))
        clean_message = str(message or "")
        signature = (clean_units, self.total_units, clean_message)
        if signature == self._last_signature:
            return
        if self.status_callback is not None and clean_message:
            self.status_callback(clean_message)
        if self.progress_callback is not None:
            self.progress_callback(clean_units, self.total_units, clean_message)
        self.completed_units = clean_units
        self.current_message = clean_message
        self._last_signature = signature


@dataclass(slots=True)
class DiagnosticsProgressSegment:
    """One reserved subrange inside a diagnostics startup progress run."""

    tracker: DiagnosticsProgressTracker
    start_units: int
    total_units: int

    @property
    def completed_units(self) -> int:
        return max(0, self.tracker.completed_units - self.start_units)

    @property
    def remaining_units(self) -> int:
        return max(0, self.total_units - self.completed_units)

    def set_status(self, message: str) -> None:
        self.tracker.set_status(message)

    def advance(self, units: int = 1, *, message: str | None = None) -> None:
        increment = min(self.remaining_units, max(0, int(units or 0)))
        self.tracker.report_absolute(
            self.start_units + self.completed_units + increment,
            message=message or self.tracker.current_message,
        )

    def fill_remaining(self, *, message: str | None = None) -> None:
        if self.remaining_units <= 0:
            return
        self.advance(self.remaining_units, message=message or self.tracker.current_message)

    def progress_callback(self) -> ProgressCallback:
        def _report(value: int, maximum: int, message: str) -> None:
            clean_maximum = max(1, int(maximum or 1))
            ratio = max(0.0, min(1.0, float(int(value or 0)) / float(clean_maximum)))
            scaled_units = self.start_units + int(round(self.total_units * ratio))
            self.tracker.report_absolute(scaled_units, message=message)

        return _report

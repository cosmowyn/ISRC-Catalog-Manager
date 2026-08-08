"""Truthful completed-phase progress for profile history replay."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from .models import HistoryEntry

HistoryReplayProgressCallback = Callable[[int, int, str], None]

SNAPSHOT_REPLAY_PHASES = 8
INVERSE_REPLAY_PHASES = 2


def replay_phase_count(entries: Iterable[HistoryEntry]) -> int:
    """Return the number of concrete replay phases in an entry plan."""

    return sum(
        SNAPSHOT_REPLAY_PHASES if entry.strategy == "snapshot" else INVERSE_REPLAY_PHASES
        for entry in entries
    )


@dataclass(slots=True)
class HistoryReplayProgress:
    """Emit monotonic progress only after concrete replay phases complete."""

    callback: HistoryReplayProgressCallback | None
    operation: str
    maximum: int
    value: int = 0

    @classmethod
    def for_plan(
        cls,
        callback: HistoryReplayProgressCallback | None,
        *,
        operation: str,
        entries: Iterable[HistoryEntry],
    ) -> "HistoryReplayProgress":
        plan = tuple(entries)
        tracker = cls(
            callback=callback,
            operation=str(operation).strip().title(),
            maximum=max(1, replay_phase_count(plan)),
        )
        tracker.report(f"Preparing {tracker.operation.lower()} replay...")
        return tracker

    def report(self, message: str) -> None:
        """Update status without claiming that another phase is complete."""

        if self.callback is None:
            return
        try:
            self.callback(int(self.value), int(self.maximum), str(message or ""))
        except Exception:
            # Progress is observational and must never compromise a recovery operation.
            return

    def advance(self, message: str) -> None:
        """Mark exactly one completed replay phase."""

        self.value = min(self.maximum, self.value + 1)
        self.report(message)

    def finish(self) -> None:
        """Report terminal replay completion without affecting data recovery."""

        self.value = self.maximum
        self.report(f"{self.operation} replay completed.")

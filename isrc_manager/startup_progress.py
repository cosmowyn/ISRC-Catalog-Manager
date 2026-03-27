"""Shared startup phase metadata and truthful lifecycle progress helpers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Callable, Iterable


class StartupPhase(IntEnum):
    STARTING = 0
    RESOLVING_STORAGE = 1
    INITIALIZING_SETTINGS = 2
    OPENING_PROFILE_DB = 3
    LOADING_SERVICES = 4
    PREPARING_DATABASE = 5
    FINALIZING_INTERFACE = 6
    RESTORING_WORKSPACE = 7
    LOADING_CATALOG = 8
    READY = 9


STARTUP_PHASE_LABELS: dict[StartupPhase, str] = {
    StartupPhase.STARTING: "Starting application…",
    StartupPhase.RESOLVING_STORAGE: "Resolving storage layout…",
    StartupPhase.INITIALIZING_SETTINGS: "Initializing settings…",
    StartupPhase.OPENING_PROFILE_DB: "Opening profile database…",
    StartupPhase.LOADING_SERVICES: "Loading services…",
    StartupPhase.PREPARING_DATABASE: "Preparing database…",
    StartupPhase.FINALIZING_INTERFACE: "Finalizing interface…",
    StartupPhase.RESTORING_WORKSPACE: "Restoring workspace…",
    StartupPhase.LOADING_CATALOG: "Loading catalog…",
    StartupPhase.READY: "Ready",
}


def startup_phase_label(phase: StartupPhase) -> str:
    """Return the default label for a startup phase."""
    return STARTUP_PHASE_LABELS[StartupPhase(phase)]


@dataclass(frozen=True, slots=True)
class StartupProgressSection:
    """One major startup/profile task bucket with a truthful weighted range."""

    phase: StartupPhase
    weight: int


STARTUP_PROGRESS_PLAN: tuple[StartupProgressSection, ...] = (
    StartupProgressSection(StartupPhase.RESOLVING_STORAGE, 2),
    StartupProgressSection(StartupPhase.INITIALIZING_SETTINGS, 3),
    StartupProgressSection(StartupPhase.OPENING_PROFILE_DB, 1),
    StartupProgressSection(StartupPhase.PREPARING_DATABASE, 4),
    StartupProgressSection(StartupPhase.LOADING_SERVICES, 7),
    StartupProgressSection(StartupPhase.FINALIZING_INTERFACE, 5),
    StartupProgressSection(StartupPhase.RESTORING_WORKSPACE, 8),
    StartupProgressSection(StartupPhase.LOADING_CATALOG, 16),
)


PROFILE_LOADING_PROGRESS_PLAN: tuple[StartupProgressSection, ...] = (
    StartupProgressSection(StartupPhase.OPENING_PROFILE_DB, 1),
    StartupProgressSection(StartupPhase.PREPARING_DATABASE, 4),
    StartupProgressSection(StartupPhase.LOADING_SERVICES, 7),
    StartupProgressSection(StartupPhase.FINALIZING_INTERFACE, 3),
    StartupProgressSection(StartupPhase.LOADING_CATALOG, 16),
)


ProgressReporter = Callable[..., None]


class StartupProgressTracker:
    """Maps real task/subtask completion into a truthful monotonic splash percentage."""

    def __init__(
        self,
        feedback,
        sections: Iterable[StartupProgressSection],
    ) -> None:
        self._feedback = feedback
        self._progress = 0
        self._phase: StartupPhase | None = None
        self._ranges: dict[StartupPhase, tuple[float, float]] = {}
        normalized_sections = tuple(
            StartupProgressSection(StartupPhase(section.phase), max(1, int(section.weight)))
            for section in sections
        )
        total_weight = sum(section.weight for section in normalized_sections) or 1
        completed_weight = 0
        for section in normalized_sections:
            start_ratio = completed_weight / total_weight
            completed_weight += section.weight
            end_ratio = completed_weight / total_weight
            self._ranges[section.phase] = (start_ratio * 100.0, end_ratio * 100.0)

    @classmethod
    def for_startup(cls, feedback) -> "StartupProgressTracker":
        return cls(feedback, STARTUP_PROGRESS_PLAN)

    @classmethod
    def for_profile_loading(cls, feedback) -> "StartupProgressTracker":
        return cls(feedback, PROFILE_LOADING_PROGRESS_PLAN)

    @property
    def current_progress(self) -> int:
        return self._progress

    @property
    def current_phase(self) -> StartupPhase | None:
        return self._phase

    def set_phase(
        self,
        phase: StartupPhase,
        message_override: str | None = None,
    ) -> None:
        self._emit(
            progress=self._progress,
            phase=StartupPhase(phase),
            message=str(message_override or startup_phase_label(StartupPhase(phase))),
        )

    def set_status(self, message: str) -> None:
        self._emit(progress=self._progress, phase=self._phase, message=str(message or ""))

    def progress_callback(self, phase: StartupPhase) -> ProgressReporter:
        active_phase = StartupPhase(phase)

        def _report(value=None, maximum=None, message=None):
            self.report_progress(
                active_phase,
                value=value,
                maximum=maximum,
                message=message,
            )

        return _report

    def complete_phase(
        self,
        phase: StartupPhase,
        message_override: str | None = None,
    ) -> None:
        self.report_progress(
            phase,
            value=1,
            maximum=1,
            message=message_override,
        )

    def report_progress(
        self,
        phase: StartupPhase,
        *,
        value: int | float | None = None,
        maximum: int | float | None = None,
        message: str | None = None,
    ) -> None:
        active_phase = StartupPhase(phase)
        start, end = self._ranges.get(active_phase, (float(self._progress), float(self._progress)))
        progress = self._progress
        if value is not None:
            if maximum in (None, 0):
                ratio = 1.0
            else:
                try:
                    ratio = float(value) / float(maximum)
                except Exception:
                    ratio = 0.0
            ratio = min(max(ratio, 0.0), 1.0)
            progress = int(round(start + ((end - start) * ratio)))
        progress = max(self._progress, min(99, progress))
        self._emit(
            progress=progress,
            phase=active_phase,
            message=str(message or startup_phase_label(active_phase)),
        )

    def finish(self, message_override: str | None = None) -> None:
        self._emit(
            progress=100,
            phase=StartupPhase.READY,
            message=str(message_override or startup_phase_label(StartupPhase.READY)),
        )

    def _emit(
        self,
        *,
        progress: int,
        phase: StartupPhase | None,
        message: str,
    ) -> None:
        if self._feedback is None:
            return
        clean_progress = max(self._progress, max(0, min(100, int(progress))))
        clean_phase = StartupPhase(phase) if phase is not None else self._phase
        clean_message = str(message or "")
        report_progress = getattr(self._feedback, "report_progress", None)
        reported = False
        if callable(report_progress):
            try:
                report_progress(clean_progress, clean_message, phase=clean_phase)
                reported = True
            except Exception:
                reported = False
        if not reported:
            set_phase = getattr(self._feedback, "set_phase", None)
            if callable(set_phase) and clean_phase is not None:
                try:
                    set_phase(clean_phase, clean_message)
                except Exception:
                    pass
            else:
                set_status = getattr(self._feedback, "set_status", None)
                if callable(set_status):
                    try:
                        set_status(clean_message)
                    except Exception:
                        pass
        self._progress = clean_progress
        self._phase = clean_phase

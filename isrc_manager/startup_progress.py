"""Shared startup phase metadata for runtime splash feedback."""

from __future__ import annotations

from enum import IntEnum


class StartupPhase(IntEnum):
    STARTING = 5
    RESOLVING_STORAGE = 15
    INITIALIZING_SETTINGS = 30
    OPENING_PROFILE_DB = 45
    LOADING_SERVICES = 55
    PREPARING_DATABASE = 70
    FINALIZING_INTERFACE = 85
    RESTORING_WORKSPACE = 95
    READY = 100


STARTUP_PHASE_LABELS: dict[StartupPhase, str] = {
    StartupPhase.STARTING: "Starting application…",
    StartupPhase.RESOLVING_STORAGE: "Resolving storage layout…",
    StartupPhase.INITIALIZING_SETTINGS: "Initializing settings…",
    StartupPhase.OPENING_PROFILE_DB: "Opening profile database…",
    StartupPhase.LOADING_SERVICES: "Loading services…",
    StartupPhase.PREPARING_DATABASE: "Preparing database…",
    StartupPhase.FINALIZING_INTERFACE: "Finalizing interface…",
    StartupPhase.RESTORING_WORKSPACE: "Restoring workspace…",
    StartupPhase.READY: "Ready",
}


def startup_phase_label(phase: StartupPhase) -> str:
    """Return the default label for a startup milestone."""
    return STARTUP_PHASE_LABELS[StartupPhase(phase)]

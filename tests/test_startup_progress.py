from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

from isrc_manager.startup_progress import (
    StartupPhase,
    StartupProgressSection,
    StartupProgressTracker,
    startup_phase_label,
)


def test_startup_progress_tracker_reports_status_and_progress_mapping():
    feedback = SimpleNamespace(report_progress=mock.Mock())
    tracker = StartupProgressTracker.for_profile_loading(feedback)

    assert tracker.current_progress == 0
    assert tracker.current_phase is None

    tracker.set_phase(StartupPhase.OPENING_PROFILE_DB, "Opening")
    assert tracker.current_progress == 0
    assert tracker.current_phase == StartupPhase.OPENING_PROFILE_DB
    feedback.report_progress.assert_called_with(
        0,
        "Opening",
        phase=StartupPhase.OPENING_PROFILE_DB,
    )

    tracker.set_status("Still opening")
    feedback.report_progress.assert_called_with(
        0,
        "Still opening",
        phase=StartupPhase.OPENING_PROFILE_DB,
    )

    tracker.report_progress(
        StartupPhase.PREPARING_DATABASE,
        value=1,
        maximum=None,
        message="Prepared",
    )
    assert tracker.current_progress > 0
    assert tracker.current_phase == StartupPhase.PREPARING_DATABASE

    progress_before_bad_ratio = tracker.current_progress
    tracker.report_progress(
        StartupPhase.LOADING_SERVICES,
        value=object(),
        maximum=10,
        message="Bad ratio",
    )
    assert tracker.current_progress >= progress_before_bad_ratio

    callback = tracker.progress_callback(StartupPhase.LOADING_CATALOG)
    callback(3, 6, "Half catalog")
    assert tracker.current_phase == StartupPhase.LOADING_CATALOG

    tracker.complete_phase(StartupPhase.LOADING_CATALOG, "Catalog complete")
    assert tracker.current_progress == 99

    tracker.finish()
    assert tracker.current_progress == 100
    assert tracker.current_phase == StartupPhase.READY
    feedback.report_progress.assert_called_with(
        100,
        startup_phase_label(StartupPhase.READY),
        phase=StartupPhase.READY,
    )


def test_startup_progress_tracker_handles_empty_sections_and_missing_feedback():
    tracker = StartupProgressTracker(None, [])

    tracker.set_phase(StartupPhase.STARTING)
    tracker.report_progress(StartupPhase.STARTING, value=1, maximum=0)
    tracker.finish("Done")

    assert tracker.current_progress == 0
    assert tracker.current_phase is None

    feedback = SimpleNamespace(report_progress=mock.Mock())
    tracker = StartupProgressTracker(
        feedback,
        [StartupProgressSection(StartupPhase.STARTING, 0)],
    )
    tracker.report_progress(StartupPhase.STARTING, value=1, maximum=1, message="Weighted")
    assert tracker.current_progress == 99


def test_startup_progress_tracker_falls_back_from_report_progress_to_set_phase():
    feedback = SimpleNamespace(
        report_progress=mock.Mock(side_effect=RuntimeError("report failed")),
        set_phase=mock.Mock(),
    )
    tracker = StartupProgressTracker.for_startup(feedback)

    tracker.set_phase(StartupPhase.RESOLVING_STORAGE, "Resolving")

    feedback.report_progress.assert_called_once()
    feedback.set_phase.assert_called_once_with(
        StartupPhase.RESOLVING_STORAGE,
        "Resolving",
    )
    assert tracker.current_phase == StartupPhase.RESOLVING_STORAGE


def test_startup_progress_tracker_ignores_set_phase_failures():
    feedback = SimpleNamespace(set_phase=mock.Mock(side_effect=RuntimeError("phase failed")))
    tracker = StartupProgressTracker.for_startup(feedback)

    tracker.set_phase(StartupPhase.RESOLVING_STORAGE, "Resolving")

    feedback.set_phase.assert_called_once()
    assert tracker.current_phase == StartupPhase.RESOLVING_STORAGE


def test_startup_progress_tracker_falls_back_to_set_status_and_ignores_failures():
    feedback = SimpleNamespace(set_phase=mock.Mock(), set_status=mock.Mock())
    tracker = StartupProgressTracker.for_startup(feedback)

    tracker.set_status("Waiting")

    feedback.set_phase.assert_not_called()
    feedback.set_status.assert_called_once_with("Waiting")
    assert tracker.current_phase is None

    failing_feedback = SimpleNamespace(
        set_status=mock.Mock(side_effect=RuntimeError("status failed"))
    )
    failing_tracker = StartupProgressTracker.for_startup(failing_feedback)

    failing_tracker.set_status("Waiting")

    failing_feedback.set_status.assert_called_once_with("Waiting")
    assert failing_tracker.current_progress == 0

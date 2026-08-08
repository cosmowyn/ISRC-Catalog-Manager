import pytest

from isrc_manager.qa.assertions import require_evidence_status

pytestmark = pytest.mark.ui_pq


def test_ui_pq_history_replay_is_backgrounded_and_reports_truthful_progress(ui_pq_harness):
    require_evidence_status(ui_pq_harness.evidence.events, "UI-PQ-HIST-001")
    event = next(
        event for event in ui_pq_harness.evidence.events if event.test_id == "UI-PQ-HIST-001"
    )

    assert event.data["undo_restored_original_title"] is True
    assert event.data["redo_restored_edited_title"] is True
    assert event.data["task_count"] == 2
    assert event.data["task_kind"] == "exclusive"
    assert event.data["task_unique_key"] == "history.replay"
    assert event.data["tasks_non_cancellable"] is True
    assert event.data["progress_dialog_requested"] is True
    assert event.data["worker_progress_stops_before_100"] is True
    assert event.data["ui_refresh_reaches_100"] is True
    assert all(
        values == sorted(values) and max(values) < 100
        for values in event.data["worker_progress_values"]
    )
    assert all(
        values == sorted(values) and values[-1] == 100
        for values in event.data["ui_progress_values"]
    )
    assert not any(
        deviation.test_id == "UI-PQ-HIST-001" for deviation in ui_pq_harness.deviations.deviations
    )

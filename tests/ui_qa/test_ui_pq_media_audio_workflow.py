import pytest

from isrc_manager.qa.assertions import require_evidence_status, require_inventory_area

pytestmark = pytest.mark.ui_pq


def test_ui_pq_media_audio_workflow(ui_pq_harness):
    require_inventory_area(ui_pq_harness.inventory, "media_audio")
    require_evidence_status(ui_pq_harness.evidence.events, "UI-PQ-MEDIA-001")
    event = next(
        event for event in ui_pq_harness.evidence.events if event.test_id == "UI-PQ-MEDIA-001"
    )
    assert event.data["workflow_status"] == "fully_automated_local_fixture"
    assert event.data["attached_audio_size"] > 0
    assert event.data["media_player_track_id"] == event.data["track_id"]
    assert event.data["derivative_kind"] == "lossy_derivative"
    assert event.data["authenticity_basis"] == "catalog_lineage_only"
    assert event.data["ledger_derivative"]["output_format"] == "mp3"
    assert event.data["conversion_calls"]
    assert set(event.data["visual_evidence"]) == {
        "bulk_audio_attach_dialog",
        "media_player_dialog",
        "derivative_ledger_panel",
    }
    assert not any(
        deviation.test_id == "UI-PQ-MEDIA-001" for deviation in ui_pq_harness.deviations.deviations
    )

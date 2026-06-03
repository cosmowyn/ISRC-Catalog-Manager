import pytest

from isrc_manager.qa.assertions import require_evidence_status, require_inventory_area

pytestmark = pytest.mark.ui_pq


def test_ui_pq_authenticity_workflow(ui_pq_harness):
    require_inventory_area(ui_pq_harness.inventory, "authenticity")
    require_evidence_status(ui_pq_harness.evidence.events, "UI-PQ-AUTH-001")
    event = next(
        event for event in ui_pq_harness.evidence.events if event.test_id == "UI-PQ-AUTH-001"
    )
    assert event.data["workflow_status"] == "fully_automated_local_fixture"
    assert event.data["signature_valid"] is True
    assert event.data["verification_status"] == "verified_authentic"
    assert event.data["forensic_inspection_status"] == "forensic_match_found"
    assert set(event.data["visual_evidence"]) == {
        "authenticity_export_preview",
        "authenticity_verification_dialog",
        "forensic_export_dialog",
        "forensic_inspection_dialog",
    }
    assert not any(
        deviation.test_id == "UI-PQ-AUTH-001" for deviation in ui_pq_harness.deviations.deviations
    )

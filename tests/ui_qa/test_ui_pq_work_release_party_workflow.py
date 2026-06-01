import pytest

from isrc_manager.qa.assertions import require_evidence_status, require_inventory_area

pytestmark = pytest.mark.ui_pq


def test_ui_pq_work_release_party_workflow(ui_pq_harness):
    require_inventory_area(ui_pq_harness.inventory, "works_releases_parties")
    require_evidence_status(ui_pq_harness.evidence.events, "UI-PQ-REL-001")
    assert ui_pq_harness.qa_data["party_id"] > 0
    assert ui_pq_harness.qa_data["work_id"] > 0
    assert ui_pq_harness.qa_data["release_id"] > 0
    event = next(
        event for event in ui_pq_harness.evidence.events if event.test_id == "UI-PQ-REL-001"
    )
    assert event.data["party_visible"] is True
    assert event.data["work_visible"] is True
    assert event.data["release_visible"] is True
    assert event.data["party_dialog_visual"]["comparison_passed"] is True
    assert event.data["work_dialog_visual"]["comparison_passed"] is True
    assert event.data["release_panel_visual"]["comparison_passed"] is True

import pytest

from isrc_manager.qa.assertions import require_evidence_status, require_inventory_area

pytestmark = pytest.mark.ui_pq


def test_ui_pq_contract_workflow(ui_pq_harness):
    require_inventory_area(ui_pq_harness.inventory, "contracts_rights")
    require_evidence_status(ui_pq_harness.evidence.events, "UI-PQ-CON-001")
    assert ui_pq_harness.qa_data["contract_id"] > 0
    assert ui_pq_harness.qa_data["right_id"] > 0
    event = next(
        event for event in ui_pq_harness.evidence.events if event.test_id == "UI-PQ-CON-001"
    )
    assert event.data["contract_visible"] is True
    assert event.data["right_visible"] is True
    assert event.data["contract_dialog_visual"]["comparison_passed"] is True
    assert event.data["right_dialog_visual"]["comparison_passed"] is True

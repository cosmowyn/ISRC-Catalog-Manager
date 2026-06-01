import pytest

from isrc_manager.qa.assertions import require_inventory_area

pytestmark = pytest.mark.ui_pq


def test_ui_pq_authenticity_workflow(ui_pq_harness):
    require_inventory_area(ui_pq_harness.inventory, "authenticity")
    assert any(event.test_id == "UI-PQ-AUTH-001" for event in ui_pq_harness.evidence.events)
    assert any(
        deviation.test_id == "UI-PQ-AUTH-001" for deviation in ui_pq_harness.deviations.deviations
    )

import pytest

from isrc_manager.qa.assertions import require_evidence_status

pytestmark = pytest.mark.ui_pq


def test_ui_pq_menus_actions(ui_pq_harness):
    require_evidence_status(ui_pq_harness.evidence.events, "UI-PQ-MENU-001")
    assert any(item.kind == "action" for item in ui_pq_harness.inventory)
    assert any(item.kind == "menu" for item in ui_pq_harness.inventory)

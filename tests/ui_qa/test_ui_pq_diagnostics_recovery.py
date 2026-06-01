import pytest

from isrc_manager.qa.assertions import require_inventory_area

pytestmark = pytest.mark.ui_pq


def test_ui_pq_diagnostics_recovery(ui_pq_harness):
    require_inventory_area(ui_pq_harness.inventory, "diagnostics")
    assert any(
        item.ui_area in {"diagnostics", "recovery", "history_recovery"}
        for item in ui_pq_harness.inventory
    )
    event = next(
        event for event in ui_pq_harness.evidence.events if event.test_id == "UI-PQ-DIAG-001"
    )
    assert event.status == "passed"
    assert event.data["backup_method"]
    assert event.data["backup_integrity"] == "ok"
    assert event.data["restore_integrity"] == "ok"
    assert event.data["diagnostics_check_statuses"]["SQLite integrity"] == "ok"
    assert event.data["diagnostics_check_statuses"]["Foreign-key consistency"] == "ok"
    assert not any(
        deviation.test_id == "UI-PQ-DIAG-001" for deviation in ui_pq_harness.deviations.deviations
    )

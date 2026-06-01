import pytest

from isrc_manager.qa.assertions import require_evidence_status, require_inventory_area

pytestmark = pytest.mark.ui_pq


def test_ui_pq_catalog_workflow(ui_pq_harness):
    require_inventory_area(ui_pq_harness.inventory, "catalog")
    require_evidence_status(ui_pq_harness.evidence.events, "UI-PQ-CAT-001")
    assert ui_pq_harness.qa_data["track_id"] > 0
    event = next(
        event for event in ui_pq_harness.evidence.events if event.test_id == "UI-PQ-CAT-001"
    )
    assert event.data["creation_method"] == "add_track_panel.save_button.click"
    assert event.data["edit_method"] == "track_editor_dialog.save_changes"
    assert event.data["add_track_visual"]["comparison_passed"] is True
    assert event.data["edit_track_visual"]["comparison_passed"] is True

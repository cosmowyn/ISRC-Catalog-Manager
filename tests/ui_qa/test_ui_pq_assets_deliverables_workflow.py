import pytest

from isrc_manager.qa.assertions import require_evidence_status, require_inventory_area

pytestmark = pytest.mark.ui_pq


def test_ui_pq_assets_deliverables_workflow(ui_pq_harness):
    require_inventory_area(ui_pq_harness.inventory, "assets_deliverables")
    require_evidence_status(ui_pq_harness.evidence.events, "UI-PQ-ASSET-001")
    event = next(
        event for event in ui_pq_harness.evidence.events if event.test_id == "UI-PQ-ASSET-001"
    )
    assert event.data["asset_id"] > 0
    assert event.data["asset_primary_flag"] is True
    assert event.data["asset_delete_handler_injected"] is True
    assert event.data["asset_delete_action_type"] == "asset.delete"
    assert event.data["asset_delete_action_label"] == (
        "Delete Asset: ui-pq-asset-history-master.wav"
    )
    assert event.data["asset_delete_removed"] is True
    assert event.data["asset_delete_managed_file_removed"] is True
    assert event.data["asset_delete_undo_restored"] is True
    assert event.data["asset_delete_undo_managed_file_restored"] is True
    assert event.data["asset_delete_redo_removed"] is True
    assert event.data["asset_delete_redo_managed_file_removed"] is True
    assert event.data["asset_delete_external_reference_preserved"] is True
    assert event.data["asset_delete_seeded_asset_preserved"] is True
    assert str(event.data["asset_delete_managed_path"]).startswith("asset_registry/")
    assert event.data["asset_delete_external_reference_filename"] == (
        "ui-pq-asset-history-source.wav"
    )
    assert not any(
        deviation.test_id == "UI-PQ-ASSET-001" for deviation in ui_pq_harness.deviations.deviations
    )

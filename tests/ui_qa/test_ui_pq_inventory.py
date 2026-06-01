from pathlib import Path

import pytest

from isrc_manager.qa.assertions import require_artifact, require_evidence_status

pytestmark = pytest.mark.ui_pq


def test_ui_pq_inventory(ui_pq_harness):
    assert len(ui_pq_harness.inventory) > 0
    require_evidence_status(ui_pq_harness.evidence.events, "UI-PQ-INV-001")
    require_artifact(Path("artifacts/ui_pq/ui_inventory.json"))


def test_ui_pq_inventory_has_no_stable_object_name_gaps(ui_pq_harness):
    gaps = [
        deviation
        for deviation in ui_pq_harness.deviations.deviations
        if deviation.coverage_status == "object_name_gap"
    ]
    assert gaps == []

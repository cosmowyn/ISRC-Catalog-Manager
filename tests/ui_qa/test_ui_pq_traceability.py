from pathlib import Path

import pytest

from isrc_manager.qa.assertions import require_artifact

pytestmark = pytest.mark.ui_pq


def test_ui_pq_traceability(ui_pq_harness):
    assert len(ui_pq_harness.traceability_rows) == len(ui_pq_harness.inventory)
    assert any(row.coverage_status == "pending_manual" for row in ui_pq_harness.traceability_rows)
    major_business_rows = [
        row
        for row in ui_pq_harness.traceability_rows
        if row.test_id
        in {
            "UI-PQ-CAT-001",
            "UI-PQ-REL-001",
            "UI-PQ-CON-001",
            "UI-PQ-ACC-001",
            "UI-PQ-SC-001",
            "UI-PQ-AUTH-001",
            "UI-PQ-MEDIA-001",
        }
    ]
    assert major_business_rows
    assert all(row.automation_status == "automated" for row in major_business_rows)
    assert all(row.coverage_status == "covered" for row in major_business_rows)
    architectural_constraint_rows = [
        row
        for row in ui_pq_harness.traceability_rows
        if row.automation_status in {"automated_plus_pending", "mocked_pending"}
    ]
    assert architectural_constraint_rows == []
    pending_rows = [
        row for row in ui_pq_harness.traceability_rows if row.coverage_status == "pending_manual"
    ]
    assert len(pending_rows) <= len(ui_pq_harness.traceability_rows) // 2
    require_artifact(Path("artifacts/ui_pq/traceability_matrix.csv"))
    require_artifact(Path("artifacts/ui_pq/deviations.csv"))
    require_artifact(Path("artifacts/ui_pq/evidence.json"))
    require_artifact(Path("artifacts/ui_pq/summary.md"))

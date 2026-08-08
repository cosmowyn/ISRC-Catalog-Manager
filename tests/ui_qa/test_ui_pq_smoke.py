import pytest

from isrc_manager.qa.assertions import require_evidence_status

pytestmark = pytest.mark.ui_pq


def test_ui_pq_smoke(ui_pq_harness):
    require_evidence_status(ui_pq_harness.evidence.events, "UI-PQ-SMOKE-001")
    assert ui_pq_harness.database_path
    assert ui_pq_harness.evidence.evidence_path == ui_pq_harness.artifact_dir / "evidence.json"

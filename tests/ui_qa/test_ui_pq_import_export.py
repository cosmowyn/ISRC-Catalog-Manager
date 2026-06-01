from pathlib import Path

import pytest

from isrc_manager.qa.assertions import require_artifact, require_inventory_area

pytestmark = pytest.mark.ui_pq


def test_ui_pq_import_export(ui_pq_harness):
    require_inventory_area(ui_pq_harness.inventory, "import_export")
    event = next(
        event for event in ui_pq_harness.evidence.events if event.test_id == "UI-PQ-IMP-001"
    )
    assert event.status == "passed"
    assert event.data["pdf_profile"]["valid"] is True
    assert event.data["pdf_comparison"]["passed"] is True
    assert event.data["report_comparison"]["passed"] is True
    assert event.data["html_comparison"]["passed"] is True
    require_artifact(Path(event.data["manifest_path"]))
    require_artifact(Path(event.data["pdf_path"]))
    assert not any(
        deviation.test_id == "UI-PQ-IMP-001" for deviation in ui_pq_harness.deviations.deviations
    )

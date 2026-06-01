from pathlib import Path

import pytest

from isrc_manager.qa.assertions import require_artifact

pytestmark = pytest.mark.ui_pq


def test_ui_pq_visual_framework_artifacts(ui_pq_harness):
    visual_event = next(
        event for event in ui_pq_harness.evidence.events if event.test_id == "UI-PQ-SET-001"
    )
    output_event = next(
        event for event in ui_pq_harness.evidence.events if event.test_id == "UI-PQ-IMP-001"
    )
    require_artifact(Path(visual_event.data["manifest_path"]))
    require_artifact(Path(output_event.data["manifest_path"]))
    assert all(
        comparison["passed"]
        for comparison in (
            visual_event.data["main_window_comparison"],
            visual_event.data["theme_comparison"],
            output_event.data["report_comparison"],
            output_event.data["html_comparison"],
            output_event.data["csv_comparison"],
            output_event.data["pdf_comparison"],
        )
    )

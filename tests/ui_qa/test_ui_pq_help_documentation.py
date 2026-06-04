import json
from pathlib import Path

import pytest

from isrc_manager.qa import UIQualificationHarness
from isrc_manager.qa.assertions import require_artifact


@pytest.fixture(scope="module")
def help_pq_harness():
    with UIQualificationHarness() as harness:
        harness.run_help_documentation_qualification()
        yield harness


def test_ui_pq_help_documentation_is_fully_validated(help_pq_harness):
    event = next(
        event for event in help_pq_harness.evidence.events if event.test_id == "UI-PQ-HELP-001"
    )
    assert event.status == "passed"
    assert event.data["finding_count"] == 0
    assert event.data["coverage_percent"] == 100.0
    assert event.data["workflow_example_count"] >= 7
    assert event.data["chapter_screenshot_exempt_count"] == 3
    assert event.data["chapter_screenshot_count"] == event.data["chapter_screenshot_required_count"]
    assert (
        event.data["chapter_screenshot_required_count"]
        + event.data["chapter_screenshot_exempt_count"]
        == event.data["chapter_count"]
    )
    assert (
        event.data["refreshed_chapter_screenshot_count"]
        == event.data["chapter_screenshot_required_count"]
    )
    assert event.data["screenshot_count"] == event.data["chapter_screenshot_required_count"]
    assert event.data["unique_screenshot_hash_count"] == event.data["screenshot_count"]
    assert event.data["duplicate_screenshot_hash_count"] == 0
    report_path = Path(event.data["report_path"])
    validated_help_path = Path(event.data["validated_help_manual_path"])
    require_artifact(report_path)
    require_artifact(validated_help_path)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["chapter_screenshot_exempt_ids"] == [
        "overview",
        "main-window",
        "keyboard-shortcuts",
    ]
    assert report["chapter_screenshot_count"] == report["chapter_screenshot_required_count"]
    assert report["unique_screenshot_hash_count"] == report["screenshot_count"]
    assert not report["duplicate_screenshot_hashes"]
    assert not report["findings"]
    help_html = validated_help_path.read_text(encoding="utf-8")
    for chapter_id in report["chapter_screenshot_required_ids"]:
        assert f"screenshots/chapter_{chapter_id}.png" in help_html
    for chapter_id in report["chapter_screenshot_exempt_ids"]:
        assert f"screenshots/chapter_{chapter_id}.png" not in help_html
    assert "Visual UI Reference" not in help_html
    assert "Back to Table of Contents" in help_html
    assert not any(
        deviation.test_id == "UI-PQ-HELP-001" for deviation in help_pq_harness.deviations.deviations
    )

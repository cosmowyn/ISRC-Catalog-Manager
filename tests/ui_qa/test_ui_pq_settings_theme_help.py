from pathlib import Path

import pytest

from isrc_manager.qa.assertions import require_artifact, require_inventory_area

pytestmark = pytest.mark.ui_pq


def test_ui_pq_settings_theme_help(ui_pq_harness):
    require_inventory_area(ui_pq_harness.inventory, "settings_theme_help")
    event = next(
        event for event in ui_pq_harness.evidence.events if event.test_id == "UI-PQ-SET-001"
    )
    assert event.status == "passed"
    assert event.data["screenshot_count"] >= 32
    assert event.data["comparison_count"] >= 33
    assert event.data["main_window_comparison"]["passed"] is True
    assert event.data["theme_comparison"]["passed"] is True
    dialog_surfaces = {dialog["surface"] for dialog in event.data["dialogs"]}
    assert {"about_dialog", "help_contents_dialog"}.issubset(dialog_surfaces)
    help_surfaces = {surface["surface"] for surface in event.data["help_screenshot_surfaces"]}
    assert {"add_album_dialog", "invoice_workspace", "soundcloud_publish_dialog"}.issubset(
        help_surfaces
    )
    require_artifact(Path(event.data["manifest_path"]))
    assert not any(
        deviation.test_id == "UI-PQ-SET-001" for deviation in ui_pq_harness.deviations.deviations
    )

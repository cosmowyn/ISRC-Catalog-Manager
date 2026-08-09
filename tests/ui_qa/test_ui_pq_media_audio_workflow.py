import hashlib
from pathlib import Path

import pytest

from isrc_manager.qa.assertions import (
    require_artifact,
    require_evidence_status,
    require_inventory_area,
)

pytestmark = pytest.mark.ui_pq


def test_ui_pq_media_audio_workflow(ui_pq_harness):
    require_inventory_area(ui_pq_harness.inventory, "media_audio")
    require_evidence_status(ui_pq_harness.evidence.events, "UI-PQ-MEDIA-001")
    event = next(
        event for event in ui_pq_harness.evidence.events if event.test_id == "UI-PQ-MEDIA-001"
    )
    assert event.data["workflow_status"] == "fully_automated_local_fixture"
    assert event.data["attached_audio_size"] > 0
    assert event.data["media_player_track_id"] == event.data["track_id"]
    assert event.data["derivative_kind"] == "lossy_derivative"
    assert event.data["authenticity_basis"] == "catalog_lineage_only"
    assert event.data["ledger_derivative"]["output_format"] == "mp3"
    assert event.data["conversion_calls"]
    image_export = event.data["image_preview_export"]
    source_path = Path(image_export["source_path"])
    output_path = Path(image_export["output_path"])
    require_artifact(source_path)
    require_artifact(output_path)
    source_bytes = source_path.read_bytes()
    output_bytes = output_path.read_bytes()
    assert image_export["output_exists"] is True
    assert image_export["source_size"] == len(source_bytes) > 0
    assert image_export["output_size"] == len(output_bytes) == len(source_bytes)
    assert image_export["source_sha256"] == hashlib.sha256(source_bytes).hexdigest()
    assert image_export["output_sha256"] == hashlib.sha256(output_bytes).hexdigest()
    assert image_export["output_sha256"] == image_export["source_sha256"]
    assert image_export["bytes_match"] is True
    assert output_bytes == source_bytes
    assert image_export["history_action_type"] == "file.export_image_preview"
    assert image_export["history_action_count"] == 1
    assert image_export["success_message_count"] == 1
    assert image_export["error_message_count"] == 0
    assert set(event.data["visual_evidence"]) == {
        "bulk_audio_attach_dialog",
        "media_player_dialog",
        "image_preview_dialog",
        "derivative_ledger_panel",
    }
    assert not any(
        deviation.test_id == "UI-PQ-MEDIA-001" for deviation in ui_pq_harness.deviations.deviations
    )

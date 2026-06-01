import pytest

pytestmark = pytest.mark.ui_pq


def test_ui_pq_soundcloud_mock_workflow(ui_pq_harness):
    event = next(
        event for event in ui_pq_harness.evidence.events if event.test_id == "UI-PQ-SC-001"
    )
    assert event.status == "passed"
    assert event.data["workflow_status"] == "fully_ui_led"
    assert event.data["account_public_profile"]["permalink_url"].startswith(
        "https://soundcloud.com/"
    )
    assert event.data["would_upload_audio"] is True
    assert event.data["watermarked_audio_path"].endswith("-watermarked-upload.wav")
    assert event.data["artwork_path"].endswith(".jpg")
    assert set(event.data["visual_evidence"]) >= {
        "soundcloud_preflight_ui",
        "soundcloud_progress_ui",
        "soundcloud_completion_ui",
    }
    assert not any(
        deviation.test_id == "UI-PQ-SC-001" and deviation.ui_area == "soundcloud"
        for deviation in ui_pq_harness.deviations.deviations
    )

import json

from isrc_manager.reporting.crash_detection import SessionMarkerStore


def test_unclean_previous_session_is_reported_on_next_start(tmp_path) -> None:
    marker = SessionMarkerStore(tmp_path / "session.json")

    assert marker.start_session(app_version="1.0") is None
    marker.record_event(event="workflow.open", message="Opened workflow")

    crash = SessionMarkerStore(tmp_path / "session.json").start_session(app_version="1.0")

    assert crash is not None
    assert crash.last_event == "workflow.open"
    assert crash.last_message == "Opened workflow"


def test_clean_shutdown_prevents_crash_prompt(tmp_path) -> None:
    marker = SessionMarkerStore(tmp_path / "session.json")
    assert marker.start_session(app_version="1.0") is None

    marker.mark_clean_shutdown()

    assert SessionMarkerStore(tmp_path / "session.json").start_session(app_version="1.0") is None


def test_corrupt_marker_is_ignored_and_replaced(tmp_path) -> None:
    marker_path = tmp_path / "session.json"
    marker_path.write_text("{not json", encoding="utf-8")

    marker = SessionMarkerStore(marker_path)

    assert marker.start_session(app_version="2.0") is None
    payload = json.loads(marker_path.read_text(encoding="utf-8"))
    assert payload["app_version"] == "2.0"
    assert payload["clean_shutdown"] is False

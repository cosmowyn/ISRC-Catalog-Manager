from __future__ import annotations

import sqlite3
from types import SimpleNamespace
from unittest import mock

from isrc_manager.diagnostics import report
from isrc_manager.services import HistoryRetentionSettings


def test_history_snapshot_summary_handles_missing_empty_latest_and_errors():
    app = SimpleNamespace(conn=None)
    assert report._history_snapshot_summary(app) == "History unavailable"

    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE HistorySnapshots(id INTEGER PRIMARY KEY, label TEXT, created_at TEXT)"
    )
    assert report._history_snapshot_summary(app, conn=conn) == "0 snapshot(s)"
    conn.execute(
        "INSERT INTO HistorySnapshots(label, created_at) VALUES (?, ?)",
        ("Before import", "2026-05-25T10:00:00"),
    )
    assert (
        report._history_snapshot_summary(app, conn=conn)
        == "1 snapshot(s), latest: Before import @ 2026-05-25T10:00:00"
    )
    conn.close()

    broken = sqlite3.connect(":memory:")
    assert report._history_snapshot_summary(app, conn=broken) == "Snapshot history unavailable"
    broken.close()


def test_custom_field_column_and_orphan_count_support_legacy_and_current_columns():
    conn = sqlite3.connect(":memory:")
    app = SimpleNamespace(
        conn=conn,
        _custom_value_field_column_name=lambda **kwargs: report._custom_value_field_column_name(
            app, **kwargs
        ),
    )
    assert report._custom_value_field_column_name(app) is None
    assert report._count_orphaned_custom_values(app) == 0

    conn.execute("CREATE TABLE CustomFieldDefs(id INTEGER PRIMARY KEY)")
    conn.execute("CREATE TABLE Tracks(id INTEGER PRIMARY KEY)")
    conn.execute(
        "CREATE TABLE CustomFieldValues(track_id INTEGER, field_def_id INTEGER, value TEXT)"
    )
    conn.execute("INSERT INTO CustomFieldDefs(id) VALUES (1)")
    conn.execute("INSERT INTO Tracks(id) VALUES (1)")
    conn.executemany(
        "INSERT INTO CustomFieldValues(track_id, field_def_id, value) VALUES (?, ?, ?)",
        [(1, 1, "ok"), (99, 1, "missing track"), (1, 99, "missing field")],
    )

    assert report._custom_value_field_column_name(app) == "field_def_id"
    assert report._count_orphaned_custom_values(app) == 2
    conn.close()

    legacy = sqlite3.connect(":memory:")
    legacy.execute("CREATE TABLE CustomFieldValues(track_id INTEGER, custom_field_id INTEGER)")
    assert report._custom_value_field_column_name(SimpleNamespace(conn=legacy)) == "custom_field_id"
    legacy.close()


def test_managed_file_scan_counts_return_zero_for_missing_tables_and_count_refs():
    app = SimpleNamespace(conn=None)
    assert report._diagnostics_managed_file_scan_counts(app) == {
        "audio_file_refs": 0,
        "album_art_refs": 0,
        "license_file_refs": 0,
    }

    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE Tracks(audio_file_path TEXT)")
    conn.execute("CREATE TABLE Albums(album_art_path TEXT)")
    conn.execute("CREATE TABLE Licenses(file_path TEXT)")
    conn.executemany("INSERT INTO Tracks(audio_file_path) VALUES (?)", [("audio.wav",), ("",)])
    conn.executemany("INSERT INTO Albums(album_art_path) VALUES (?)", [("cover.png",), (None,)])
    conn.executemany("INSERT INTO Licenses(file_path) VALUES (?)", [("license.pdf",), (" ",)])

    assert report._diagnostics_managed_file_scan_counts(app, conn=conn) == {
        "audio_file_refs": 1,
        "album_art_refs": 1,
        "license_file_refs": 1,
    }
    conn.close()


def test_build_diagnostics_progress_plan_sums_managed_and_storage_units():
    app = SimpleNamespace(
        _diagnostics_managed_file_scan_counts=mock.Mock(
            return_value={"audio_file_refs": 2, "album_art_refs": 3, "license_file_refs": 4}
        ),
        _application_storage_admin_service=mock.Mock(
            return_value=SimpleNamespace(inspect_progress_total=mock.Mock(return_value=7))
        ),
    )

    plan = report._build_diagnostics_progress_plan(app, current_db_path="/profile.sqlite")

    assert plan["managed_file_units"] == 9
    assert plan["core_units"] == 10
    assert plan["history_units"] == 5
    assert plan["application_storage_units"] == 7
    assert plan["worker_total_units"] == 31
    assert plan["overall_total_units"] == 32

    app._application_storage_admin_service.side_effect = RuntimeError("no storage")
    assert report._build_diagnostics_progress_plan(app)["application_storage_units"] == 1


def test_application_storage_summary_payload_describes_empty_and_nonempty_audits():
    app = SimpleNamespace(
        _human_size=lambda value: f"{int(value)} B",
        _history_retention_settings_for_storage_summary=mock.Mock(
            return_value=HistoryRetentionSettings(auto_snapshot_keep_latest=3)
        ),
    )
    empty_audit = SimpleNamespace(
        summary=SimpleNamespace(
            total_app_bytes=0,
            total_items=0,
            reclaimable_items=0,
            reclaimable_bytes=0,
            current_profile_name="",
            current_profile_bytes=0,
            deleted_profile_bytes=0,
            orphaned_bytes=0,
            warning_bytes=0,
            warning_items=0,
        )
    )
    empty_payload = report._application_storage_summary_payload(app, empty_audit)
    assert empty_payload["safe_budget_text"] == "Not available"
    assert empty_payload["current_profile_text"] == "No active profile"

    audit = SimpleNamespace(
        summary=SimpleNamespace(
            total_app_bytes=4096,
            total_items=8,
            reclaimable_items=2,
            reclaimable_bytes=512,
            current_profile_name="Demo",
            current_profile_bytes=1024,
            deleted_profile_bytes=256,
            orphaned_bytes=128,
            warning_bytes=64,
            warning_items=1,
        )
    )
    payload = report._application_storage_summary_payload(app, audit)
    assert payload["available"] is True
    assert "4096 B" in payload["summary"]
    assert "Demo" in payload["summary"]
    assert payload["current_profile_text"] == "1024 B"
    assert payload["safe_budget_text"] != "Not available"


def test_application_storage_item_payload_limits_reference_text_and_normalizes_fields():
    app = SimpleNamespace(_human_size=lambda value: f"{int(value)} B")
    item = SimpleNamespace(
        item_key="item-1",
        status_key="warning",
        status_label="Warning",
        category_key="history",
        category_label="History",
        label="Snapshot",
        path="/tmp/snapshot",
        bytes_on_disk=123,
        profile_name="Demo",
        profile_path="/profiles/demo.sqlite",
        reason="orphan",
        recommended=True,
        warning_required=True,
        warning="Check first",
        references=[SimpleNamespace(owner_label=f"Owner {index}") for index in range(10)],
    )

    payload = report._application_storage_item_payload(app, item)

    assert payload["item_key"] == "item-1"
    assert payload["bytes_on_disk"] == 123
    assert payload["size_text"] == "123 B"
    assert payload["recommended"] is True
    assert payload["warning_required"] is True
    assert "Owner 0" in payload["references_text"]
    assert "Owner 8" not in payload["references_text"]


def test_build_application_storage_audit_payload_calls_inspector_and_payload_helpers():
    item = SimpleNamespace(label="item")
    audit = SimpleNamespace(summary=SimpleNamespace(total_app_bytes=1), items=[item])
    service = SimpleNamespace(inspect=mock.Mock(return_value=audit))
    app = SimpleNamespace(
        current_db_path="/current.sqlite",
        _application_storage_admin_service=mock.Mock(return_value=service),
        _application_storage_summary_payload=mock.Mock(return_value={"summary": "ok"}),
        _application_storage_item_payload=mock.Mock(return_value={"item": "ok"}),
    )

    payload = report._build_application_storage_audit_payload(
        app,
        status_callback="status",
        progress_callback="progress",
    )

    service.inspect.assert_called_once_with(
        current_db_path="/current.sqlite",
        status_callback="status",
        progress_callback="progress",
    )
    assert payload == {"summary": {"summary": "ok"}, "items": [{"item": "ok"}]}


def test_legacy_promoted_candidates_and_repair_helpers_handle_missing_connection(monkeypatch):
    assert report._legacy_promoted_field_repair_candidates(SimpleNamespace(conn=None)) == []

    candidates = ["candidate"]

    class FakeRepairService:
        def __init__(self, connection):
            self.connection = connection

        def inspect_candidates(self):
            return candidates

    conn = sqlite3.connect(":memory:")
    monkeypatch.setattr(report, "LegacyPromotedFieldRepairService", FakeRepairService)
    assert report._legacy_promoted_field_repair_candidates(SimpleNamespace(conn=conn)) == candidates
    conn.close()

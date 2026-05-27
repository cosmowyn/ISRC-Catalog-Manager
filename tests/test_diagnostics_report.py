from __future__ import annotations

import sqlite3
from pathlib import Path
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


def _checks_by_title(payload: dict[str, object]) -> dict[str, dict[str, object]]:
    return {str(check["title"]): check for check in payload["checks"]}


def _diagnostics_connection(tmp_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute(
        """
        CREATE TABLE Tracks(
            id INTEGER PRIMARY KEY,
            track_title TEXT,
            audio_file_path TEXT
        )
        """
    )
    conn.execute("CREATE TABLE Albums(id INTEGER PRIMARY KEY, title TEXT, album_art_path TEXT)")
    conn.execute("CREATE TABLE Licenses(id INTEGER PRIMARY KEY, filename TEXT, file_path TEXT)")
    conn.execute(
        "CREATE TABLE HistorySnapshots(id INTEGER PRIMARY KEY, label TEXT, created_at TEXT)"
    )
    conn.execute(
        "INSERT INTO Tracks(id, track_title, audio_file_path) VALUES (1, 'Song', ?)",
        ("missing.wav",),
    )
    conn.execute(
        "INSERT INTO Albums(id, title, album_art_path) VALUES (1, 'Album', ?)", ("cover.png",)
    )
    conn.execute(
        "INSERT INTO Licenses(id, filename, file_path) VALUES (1, 'Deal.pdf', ?)", ("deal.pdf",)
    )
    conn.execute(
        "INSERT INTO HistorySnapshots(label, created_at) VALUES ('Before import', '2026-05-26')"
    )
    conn.execute("CREATE TABLE Parent(id INTEGER PRIMARY KEY)")
    conn.execute("CREATE TABLE Child(parent_id INTEGER REFERENCES Parent(id))")
    conn.execute("INSERT INTO Child(parent_id) VALUES (99)")
    return conn


def test_build_diagnostics_report_surfaces_warning_and_repair_paths(
    monkeypatch,
    tmp_path: Path,
) -> None:
    conn = _diagnostics_connection(tmp_path)

    class _FakeWaveformCacheService:
        def __init__(self, connection) -> None:
            self.connection = connection

        def inspect_invalid_caches(self, track_service):
            assert track_service is not None
            return SimpleNamespace(
                issue_count=2,
                valid_rows=1,
                total_rows=3,
                details=["orphan waveform row", "stale source fingerprint"],
            )

    class _FakeCleanupService:
        def __init__(self, history_manager) -> None:
            self.history_manager = history_manager

        def preview_storage_budget(self, retention_settings):
            assert retention_settings.auto_cleanup_enabled is True
            return SimpleNamespace(
                total_bytes=8192,
                budget_bytes=1024,
                over_budget_bytes=4096,
                candidate_items=[SimpleNamespace(bytes_on_disk=512)],
                protected_over_budget_items=[],
                auto_cleanup_enabled=True,
            )

    class _FakeSettingsReadService:
        def __init__(self, connection) -> None:
            self.connection = connection

        def load_history_retention_settings(self) -> HistoryRetentionSettings:
            return HistoryRetentionSettings(
                retention_mode="balanced",
                auto_cleanup_enabled=True,
                storage_budget_mb=1,
                auto_snapshot_keep_latest=2,
                prune_pre_restore_copies_after_days=0,
            )

    monkeypatch.setattr(report, "AudioWaveformCacheService", _FakeWaveformCacheService)
    monkeypatch.setattr(report, "HistoryStorageCleanupService", _FakeCleanupService)
    monkeypatch.setattr(report, "SettingsReadService", _FakeSettingsReadService)

    history_issues = [
        SimpleNamespace(
            issue_type="missing_snapshot_artifact",
            message="Snapshot artifact missing",
            path=tmp_path / "snapshot.zip",
            details="registered but absent",
        ),
        SimpleNamespace(
            issue_type="missing_backup_file",
            message="Backup file missing",
            path=tmp_path / "backup.sqlite",
            details="",
        ),
        SimpleNamespace(
            issue_type="stale_current_head",
            message="History head points to a removed entry",
            path=None,
            details="",
        ),
    ]
    history_manager = SimpleNamespace(
        inspect_recovery_state=lambda: history_issues,
        list_snapshots=lambda limit=0: [object(), object()],
        list_backups=lambda limit=0: [object()],
    )
    storage_service = SimpleNamespace(
        layout=SimpleNamespace(
            portable=False,
            active_data_root=tmp_path / "legacy",
            preferred_data_root=tmp_path / "preferred",
        ),
        inspect=lambda: SimpleNamespace(
            legacy_root=tmp_path / "legacy",
            legacy_items=["profiles", "history"],
            preferred_items=["profiles"],
            preferred_state=report.PREFERRED_STATE_CONFLICT,
            conflict_items=["profiles/demo.sqlite"],
        ),
    )
    app_storage_service = SimpleNamespace(
        inspect=lambda **_kwargs: SimpleNamespace(summary=SimpleNamespace(total_app_bytes=1))
    )
    candidate = SimpleNamespace(
        eligible=True,
        field_name="Legacy ISWC",
        custom_field_type="text",
        default_field_type="text",
        non_empty_value_count=3,
        blank_target_count=2,
        conflicting_track_ids=[],
    )
    app = SimpleNamespace(
        conn=conn,
        data_root=tmp_path / "data",
        logs_dir=tmp_path / "logs",
        track_service=SimpleNamespace(resolve_media_path=lambda value: tmp_path / str(value)),
        license_service=SimpleNamespace(resolve_path=lambda value: tmp_path / str(value)),
        history_manager=history_manager,
        database_maintenance=SimpleNamespace(
            verify_integrity=lambda _path: "database disk image is malformed"
        ),
        storage_migration_service=storage_service,
        _app_version_text=lambda: "test-version",
        _history_snapshot_summary=lambda **kwargs: report._history_snapshot_summary(app, **kwargs),
        _count_orphaned_custom_values=lambda **_kwargs: 4,
        _legacy_promoted_field_repair_candidates=lambda **_kwargs: [candidate],
        _application_storage_admin_service=lambda: app_storage_service,
        _application_storage_summary_payload=lambda _audit, **_kwargs: {
            "available": True,
            "summary": "Application storage checked",
        },
        _human_size=lambda value: f"{int(value)} B",
        _build_diagnostics_progress_plan=lambda **_kwargs: {
            "overall_total_units": 24,
            "managed_file_units": 3,
            "application_storage_units": 2,
            "history_units": 5,
        },
    )
    progress_messages: list[str] = []

    payload = report._build_diagnostics_report(
        app,
        current_db_path=tmp_path / "profile.sqlite",
        status_callback=progress_messages.append,
        progress_callback=lambda *_args: None,
    )

    checks = _checks_by_title(payload)
    assert payload["environment"]["Restore points"].startswith("1 snapshot(s)")
    assert checks["Storage layout"]["status"] == "error"
    assert checks["Schema version"]["status"] == "warning"
    assert checks["Schema layout"]["status"] == "error"
    assert checks["SQLite integrity"]["status"] == "error"
    assert checks["Foreign-key consistency"]["status"] == "error"
    assert checks["Custom-value integrity"]["orphan_count"] == 4
    assert checks["Audio waveform cache"]["issue_count"] == 2
    assert checks["Legacy default-column custom fields"]["safe_candidate_count"] == 1
    assert checks["Managed files"]["summary"] == "3 missing managed file(s) detected."
    assert checks["History snapshots"]["orphan_count"] == 1
    assert checks["Backup artifacts"]["orphan_count"] == 1
    assert checks["History invariants"]["orphan_count"] == 1
    assert checks["History storage budget"]["status"] == "warning"
    assert payload["history_storage_budget"]["available"] is True
    assert payload["history_storage_budget"]["within_budget"] is False
    assert payload["application_storage"]["summary"] == "Application storage checked"
    assert any(message.startswith("Inspecting storage layout") for message in progress_messages)
    conn.close()


def test_build_diagnostics_report_records_unavailable_service_errors(tmp_path: Path) -> None:
    app = SimpleNamespace(
        conn=None,
        data_root=tmp_path / "data",
        logs_dir=tmp_path / "logs",
        track_service=None,
        license_service=None,
        history_manager=None,
        database_maintenance=None,
        storage_migration_service=SimpleNamespace(
            inspect=lambda: (_ for _ in ()).throw(RuntimeError("layout unavailable")),
        ),
        _app_version_text=lambda: "test-version",
        _history_snapshot_summary=lambda **_kwargs: "History unavailable",
        _count_orphaned_custom_values=lambda **_kwargs: (_ for _ in ()).throw(
            RuntimeError("custom values unavailable")
        ),
        _legacy_promoted_field_repair_candidates=lambda **_kwargs: (_ for _ in ()).throw(
            RuntimeError("legacy field inspection unavailable")
        ),
        _application_storage_admin_service=lambda: (_ for _ in ()).throw(
            RuntimeError("app storage unavailable")
        ),
        _human_size=lambda value: f"{int(value)} B",
        _build_diagnostics_progress_plan=lambda **_kwargs: {
            "overall_total_units": 16,
            "managed_file_units": 0,
            "application_storage_units": 1,
            "history_units": 5,
        },
    )
    schema_service = SimpleNamespace(
        get_db_version=lambda: (_ for _ in ()).throw(RuntimeError("schema unavailable"))
    )

    payload = report._build_diagnostics_report(
        app,
        schema_service=schema_service,
        current_db_path="",
        progress_callback=lambda *_args: None,
    )

    checks = _checks_by_title(payload)
    assert checks["Storage layout"]["summary"] == "Storage layout could not be inspected."
    assert checks["Schema version"]["summary"].startswith(f"Expected schema {report.SCHEMA_TARGET}")
    assert checks["SQLite integrity"]["summary"] == "Integrity check failed to run."
    assert checks["Audio waveform cache"]["summary"] == "Cached waveform validation failed to run."
    assert checks["Custom-value integrity"]["summary"] == "Custom-value validation failed to run."
    assert checks["Legacy default-column custom fields"]["summary"] == (
        "Legacy custom/default overlap inspection failed."
    )
    assert checks["Managed files"]["status"] == "ok"
    assert checks["History snapshots"]["status"] == "error"
    assert payload["history_storage_budget"]["available"] is False
    assert payload["application_storage"]["available"] is False

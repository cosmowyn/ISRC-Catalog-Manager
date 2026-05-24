"""Diagnostics report and application storage payload assembly."""

from __future__ import annotations

import platform
import sqlite3
import sys
from pathlib import Path

from isrc_manager.application_settings_dialog import ApplicationSettingsDialog
from isrc_manager.constants import SCHEMA_TARGET
from isrc_manager.diagnostics_progress import DiagnosticsProgressTracker
from isrc_manager.history import HistoryStorageCleanupService
from isrc_manager.media.waveform_cache import AudioWaveformCacheService
from isrc_manager.services import (
    DatabaseSchemaService,
    HistoryRetentionSettings,
    LegacyPromotedFieldRepairService,
    SettingsReadService,
)
from isrc_manager.storage_admin import ApplicationStorageAdminService
from isrc_manager.storage_migration import (
    PREFERRED_STATE_CONFLICT,
    PREFERRED_STATE_RESUMABLE_STAGE,
    PREFERRED_STATE_VALID_COMPLETE,
)
from isrc_manager.storage_sizes import format_budget_megabytes
from isrc_manager.update_installer import resolve_installed_target_path


def _history_snapshot_summary(app, conn=None) -> str:
    connection = conn if conn is not None else app.conn
    if connection is None:
        return "History unavailable"
    try:
        count_row = connection.execute("SELECT COUNT(*) FROM HistorySnapshots").fetchone()
        total = int(count_row[0] or 0) if count_row else 0
        latest = connection.execute(
            "SELECT label, created_at FROM HistorySnapshots ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if not latest:
            return "0 snapshot(s)"
        latest_label = latest[0] or "Unnamed snapshot"
        latest_time = latest[1] or "unknown time"
        return f"{total} snapshot(s), latest: {latest_label} @ {latest_time}"
    except Exception:
        return "Snapshot history unavailable"


def _custom_value_field_column_name(app, conn=None) -> str | None:
    connection = conn if conn is not None else app.conn
    if connection is None:
        return None
    try:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(CustomFieldValues)").fetchall()
        }
    except Exception:
        return None
    if "field_def_id" in columns:
        return "field_def_id"
    if "custom_field_id" in columns:
        return "custom_field_id"
    return None


def _count_orphaned_custom_values(app, conn=None) -> int:
    connection = conn if conn is not None else app.conn
    if connection is None:
        return 0
    field_column = app._custom_value_field_column_name(conn=connection)
    if field_column is None:
        return 0
    row = connection.execute(
        f"""
        SELECT COUNT(*)
        FROM CustomFieldValues cfv
        LEFT JOIN CustomFieldDefs cfd ON cfd.id = cfv.{field_column}
        LEFT JOIN Tracks t ON t.id = cfv.track_id
        WHERE cfd.id IS NULL OR t.id IS NULL
        """
    ).fetchone()
    return int(row[0] or 0) if row else 0


def _legacy_promoted_field_repair_candidates(app, conn=None):
    connection = conn if conn is not None else app.conn
    if connection is None:
        return []
    return LegacyPromotedFieldRepairService(connection).inspect_candidates()


def _diagnostics_managed_file_scan_counts(app, conn=None) -> dict[str, int]:
    connection = conn if conn is not None else app.conn
    if connection is None:
        return {
            "audio_file_refs": 0,
            "album_art_refs": 0,
            "license_file_refs": 0,
        }

    def _count(query: str) -> int:
        try:
            row = connection.execute(query).fetchone()
        except Exception:
            return 0
        return int(row[0] or 0) if row else 0

    return {
        "audio_file_refs": _count(
            """
            SELECT COUNT(*)
            FROM Tracks
            WHERE COALESCE(trim(audio_file_path), '') != ''
            """
        ),
        "album_art_refs": _count(
            """
            SELECT COUNT(*)
            FROM Albums
            WHERE COALESCE(trim(album_art_path), '') != ''
            """
        ),
        "license_file_refs": _count(
            """
            SELECT COUNT(*)
            FROM Licenses
            WHERE COALESCE(trim(file_path), '') != ''
            """
        ),
    }


def _build_diagnostics_progress_plan(
    app,
    *,
    conn=None,
    current_db_path: str | Path | None = None,
) -> dict[str, int]:
    managed_counts = app._diagnostics_managed_file_scan_counts(conn=conn)
    managed_file_units = sum(int(value or 0) for value in managed_counts.values()) or 1
    core_units = 10
    history_units = 5
    try:
        application_storage_units = int(
            app._application_storage_admin_service().inspect_progress_total(
                current_db_path=current_db_path
            )
        )
    except Exception:
        application_storage_units = 1
    ui_finalize_units = 1
    worker_total_units = core_units + managed_file_units + history_units + application_storage_units
    return {
        **managed_counts,
        "managed_file_units": int(managed_file_units),
        "core_units": int(core_units),
        "history_units": int(history_units),
        "application_storage_units": int(application_storage_units),
        "ui_finalize_units": int(ui_finalize_units),
        "worker_total_units": int(worker_total_units),
        "overall_total_units": int(worker_total_units + ui_finalize_units),
    }


def _application_storage_admin_service(app) -> ApplicationStorageAdminService:
    installed_update_target = None
    if getattr(sys, "frozen", False):
        try:
            installed_update_target = resolve_installed_target_path()
        except Exception:
            installed_update_target = None
    return ApplicationStorageAdminService(
        app.storage_layout,
        update_root=app.storage_layout.preferred_data_root / "updates",
        installed_update_target_path=installed_update_target,
    )


def _history_retention_settings_for_storage_summary(
    app,
    current_db_path: str | Path | None,
) -> HistoryRetentionSettings:
    if current_db_path:
        try:
            profile_path = Path(current_db_path).expanduser().resolve()
        except Exception:
            profile_path = None
        if profile_path is not None and profile_path.exists():
            try:
                connection = sqlite3.connect(str(profile_path))
                try:
                    settings = SettingsReadService(connection).load_history_retention_settings()
                    settings.storage_budget_mb = app._application_history_storage_budget_mb(
                        default=settings.storage_budget_mb
                    )
                    return settings
                finally:
                    connection.close()
            except Exception:
                settings = HistoryRetentionSettings()
                settings.storage_budget_mb = app._application_history_storage_budget_mb(
                    default=settings.storage_budget_mb
                )
                return settings
    return app._current_history_retention_settings()


def _application_storage_summary_payload(
    app,
    audit,
    *,
    current_db_path: str | Path | None = None,
) -> dict[str, object]:
    summary = audit.summary
    current_profile_text = (
        f"{app._human_size(summary.current_profile_bytes)}"
        if summary.current_profile_name
        else "No active profile"
    )
    headline = (
        f"The application is using {app._human_size(summary.total_app_bytes)} in {summary.total_items} tracked storage item(s). "
        f"{summary.reclaimable_items} item(s) appear reclaimable now, covering {app._human_size(summary.reclaimable_bytes)}."
    )
    if summary.current_profile_name:
        headline += (
            f" The active profile {summary.current_profile_name} currently accounts for about "
            f"{app._human_size(summary.current_profile_bytes)} across database, history, and managed files."
        )
    safe_budget_text = "Not available"
    safe_budget_detail = "Application storage has not been inspected yet."
    if int(summary.total_app_bytes or 0) > 0:
        retention_settings = app._history_retention_settings_for_storage_summary(current_db_path)
        retained_snapshots = int(retention_settings.auto_snapshot_keep_latest or 1)
        transient_snapshots = max(
            0,
            int(ApplicationSettingsDialog.SMART_HISTORY_BUDGET_TRANSIENT_SNAPSHOT_COUNT),
        )
        margin_percent = int(ApplicationSettingsDialog.SMART_HISTORY_BUDGET_MARGIN_PERCENT)
        safe_budget_mb = ApplicationSettingsDialog._smart_history_budget_mb_from_profile_footprint(
            int(summary.total_app_bytes or 0),
            retained_snapshots,
        )
        safe_budget_text = format_budget_megabytes(safe_budget_mb)
        safe_budget_detail = (
            f"{safe_budget_text} for application-wide tracked storage + {retained_snapshots} retained "
            f"snapshot(s) + {transient_snapshots} temporary snapshot slot(s) + "
            f"{margin_percent}% margin."
        )
    return {
        "available": True,
        "summary": headline,
        "total_bytes": int(summary.total_app_bytes),
        "current_profile_bytes": int(summary.current_profile_bytes),
        "reclaimable_bytes": int(summary.reclaimable_bytes),
        "deleted_profile_bytes": int(summary.deleted_profile_bytes),
        "orphaned_bytes": int(summary.orphaned_bytes),
        "warning_bytes": int(summary.warning_bytes),
        "total_text": app._human_size(summary.total_app_bytes),
        "current_profile_text": current_profile_text,
        "reclaimable_text": app._human_size(summary.reclaimable_bytes),
        "deleted_profile_text": app._human_size(summary.deleted_profile_bytes),
        "orphaned_text": app._human_size(summary.orphaned_bytes),
        "warning_text": app._human_size(summary.warning_bytes),
        "safe_budget_text": safe_budget_text,
        "safe_budget_detail": safe_budget_detail,
        "warning_items": int(summary.warning_items),
        "reclaimable_items": int(summary.reclaimable_items),
        "total_items": int(summary.total_items),
        "current_profile_name": summary.current_profile_name,
    }


def _application_storage_item_payload(app, item) -> dict[str, object]:
    references_text = "\n".join(reference.owner_label for reference in item.references[:8])
    return {
        "item_key": str(item.item_key),
        "status_key": str(item.status_key),
        "status_label": str(item.status_label),
        "category_key": str(item.category_key),
        "category_label": str(item.category_label),
        "label": str(item.label),
        "path": str(item.path),
        "bytes_on_disk": int(item.bytes_on_disk or 0),
        "size_text": app._human_size(item.bytes_on_disk),
        "profile_name": str(item.profile_name or ""),
        "profile_path": str(item.profile_path or ""),
        "reason": str(item.reason or ""),
        "recommended": bool(item.recommended),
        "warning_required": bool(item.warning_required),
        "warning": str(item.warning or ""),
        "references_text": references_text,
    }


def _build_application_storage_audit_payload(
    app,
    *,
    current_db_path: str | Path | None = None,
    status_callback=None,
    progress_callback=None,
) -> dict[str, object]:
    audit = app._application_storage_admin_service().inspect(
        current_db_path=(current_db_path if current_db_path is not None else app.current_db_path),
        status_callback=status_callback,
        progress_callback=progress_callback,
    )
    return {
        "summary": app._application_storage_summary_payload(
            audit,
            current_db_path=(
                current_db_path if current_db_path is not None else app.current_db_path
            ),
        ),
        "items": [app._application_storage_item_payload(item) for item in audit.items],
    }


def _build_diagnostics_report(
    app,
    *,
    conn=None,
    schema_service=None,
    current_db_path: str | Path | None = None,
    data_root: str | Path | None = None,
    logs_dir: str | Path | None = None,
    track_service=None,
    license_service=None,
    history_manager=None,
    database_maintenance=None,
    storage_migration_service=None,
    app_version: str | None = None,
    status_callback=None,
    progress_callback=None,
) -> dict[str, object]:
    connection = conn if conn is not None else app.conn
    current_path = str(
        current_db_path if current_db_path is not None else getattr(app, "current_db_path", "")
    ).strip()
    current_data_root = Path(data_root if data_root is not None else app.data_root)
    current_logs_dir = Path(logs_dir if logs_dir is not None else app.logs_dir)
    active_track_service = track_service if track_service is not None else app.track_service
    active_license_service = license_service if license_service is not None else app.license_service
    active_history_manager = history_manager if history_manager is not None else app.history_manager
    active_database_maintenance = (
        database_maintenance if database_maintenance is not None else app.database_maintenance
    )
    active_storage_migration_service = (
        storage_migration_service
        if storage_migration_service is not None
        else app.storage_migration_service
    )
    active_schema_service = schema_service
    if active_schema_service is None and connection is not None:
        active_schema_service = DatabaseSchemaService(connection, data_root=current_data_root)

    progress_plan = app._build_diagnostics_progress_plan(
        conn=connection,
        current_db_path=current_path or None,
    )
    progress = DiagnosticsProgressTracker(
        total_units=int(progress_plan["overall_total_units"]),
        progress_callback=progress_callback,
        status_callback=status_callback,
    )
    progress.set_message("Collecting environment details...")

    db_version = 0
    schema_version_text = "Unknown"
    if active_schema_service is not None:
        try:
            db_version = int(active_schema_service.get_db_version())
            schema_version_text = str(db_version)
        except Exception:
            db_version = 0

    environment = {
        "App version": str(app_version or app._app_version_text()),
        "Schema version": schema_version_text,
        "Current profile": Path(current_path).name if current_path else "(none)",
        "Database path": current_path or "(none)",
        "Data folder": str(current_data_root),
        "Log folder": str(current_logs_dir),
        "Restore points": app._history_snapshot_summary(conn=connection),
        "Platform": f"{platform.system()} {platform.release()}",
        "Python": platform.python_version(),
    }
    progress.complete("Collected environment details.")

    checks = []
    history_storage_budget_summary: dict[str, object] = {
        "available": False,
        "usage_text": "Not available",
        "budget_text": "Not available",
        "over_budget_text": "Not available",
        "reclaimable_text": "Not available",
        "retention_mode_label": "",
        "auto_cleanup_text": "",
        "candidate_count": 0,
        "summary": "History storage information is not available for the current profile.",
        "within_budget": True,
    }
    application_storage_summary: dict[str, object] = {
        "available": False,
        "summary": "Application-wide storage information is not available.",
        "total_text": "Not available",
        "current_profile_text": "Not available",
        "reclaimable_text": "Not available",
        "deleted_profile_text": "Not available",
        "orphaned_text": "Not available",
        "warning_text": "Not available",
    }

    def add_check(
        title: str,
        status: str,
        summary: str,
        details: str,
        *,
        repair_key: str | None = None,
        repair_label: str | None = None,
        orphan_count: int | None = None,
        **extra,
    ) -> None:
        checks.append(
            {
                "title": title,
                "status": status,
                "summary": summary,
                "details": details,
                "repair_key": repair_key,
                "repair_label": repair_label,
                "orphan_count": orphan_count,
                **extra,
            }
        )

    progress.set_message("Inspecting storage layout...")
    try:
        storage_inspection = active_storage_migration_service.inspect()
        active_layout = active_storage_migration_service.layout
        if active_layout.portable:
            add_check(
                "Storage layout",
                "ok",
                "Portable mode is active.",
                "Portable mode keeps app-owned data beside the executable, so no app-data migration is required.",
            )
        elif storage_inspection.legacy_root is None or not storage_inspection.legacy_items:
            add_check(
                "Storage layout",
                "ok",
                "App-owned data already uses the preferred app folder layout.",
                f"Active data root: {active_layout.active_data_root}\nPreferred data root: {active_layout.preferred_data_root}",
            )
        else:
            current_root = active_layout.active_data_root
            preferred_state_text = (
                ", ".join(storage_inspection.preferred_items)
                if storage_inspection.preferred_items
                else "(empty)"
            )
            summary = "Legacy app-owned storage was detected."
            status = "warning"
            if storage_inspection.preferred_state == PREFERRED_STATE_VALID_COMPLETE:
                summary = "Verified app-owned data already exists in the preferred app folder."
            elif storage_inspection.preferred_state == PREFERRED_STATE_RESUMABLE_STAGE:
                summary = "A staged app-data migration can be resumed."
            elif storage_inspection.preferred_state == PREFERRED_STATE_CONFLICT:
                summary = "The preferred app folder contains conflicting managed content."
                status = "error"
            add_check(
                "Storage layout",
                status,
                summary,
                "\n".join(
                    [
                        f"Legacy root: {storage_inspection.legacy_root}",
                        f"Active root: {current_root}",
                        f"Preferred root: {active_layout.preferred_data_root}",
                        f"Legacy items: {', '.join(storage_inspection.legacy_items)}",
                        f"Preferred state: {storage_inspection.preferred_state}",
                        f"Preferred-root contents: {preferred_state_text}",
                        (
                            "Conflict items: " + ", ".join(storage_inspection.conflict_items[:10])
                            if storage_inspection.conflict_items
                            else ""
                        ),
                        "",
                        "Use the migration action to collect managed app data into the preferred app folder without deleting the legacy copy.",
                    ]
                ),
                repair_key="storage_layout_migrate",
                repair_label="Migrate App Data",
            )
    except Exception as exc:
        add_check(
            "Storage layout",
            "error",
            "Storage layout could not be inspected.",
            f"An exception occurred while checking the app-data layout:\n{exc}",
            repair_key="storage_layout_migrate",
            repair_label="Migrate App Data",
        )
    progress.complete("Inspected storage layout.")

    progress.set_message("Checking schema version...")
    if db_version == SCHEMA_TARGET:
        add_check(
            "Schema version",
            "ok",
            f"Database is at schema {db_version}.",
            f"Current user_version: {db_version}\nExpected schema target: {SCHEMA_TARGET}\n\nThe active profile matches the current app schema target.",
        )
    else:
        level = "warning" if db_version < SCHEMA_TARGET else "error"
        add_check(
            "Schema version",
            level,
            f"Expected schema {SCHEMA_TARGET}, found {db_version}.",
            f"Current user_version: {db_version}\nExpected schema target: {SCHEMA_TARGET}\n\nThis profile should be migrated before relying on the latest features.",
            repair_key="schema_migrate",
            repair_label="Run Schema Migration",
        )
    progress.complete("Checked schema version.")

    progress.set_message("Inspecting schema layout...")
    schema_layout_start = progress.completed_units
    try:
        progress.set_message("Checking required database tables...")
        table_names = (
            {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if connection is not None
            else set()
        )
        required_tables = {
            "Tracks",
            "Parties",
            "Albums",
            "TrackArtists",
            "CustomFieldDefs",
            "CustomFieldValues",
            "Licenses",
            "Licensees",
            "HistoryEntries",
            "HistoryHead",
            "HistoryBackups",
            "HistorySnapshots",
            "PromoCodeSheets",
            "PromoCodes",
            "app_kv",
        }
        missing_tables = sorted(required_tables - table_names)
        progress.complete("Checked required database tables.")

        progress.set_message("Checking required track columns...")
        track_columns = (
            {row[1] for row in connection.execute("PRAGMA table_info(Tracks)").fetchall()}
            if connection is not None and "Tracks" in table_names
            else set()
        )
        required_track_columns = {
            "id",
            "isrc",
            "isrc_compact",
            "db_entry_date",
            "audio_file_path",
            "audio_file_mime_type",
            "audio_file_size_bytes",
            "track_title",
            "catalog_number",
            "album_art_path",
            "album_art_mime_type",
            "album_art_size_bytes",
            "main_artist_party_id",
            "buma_work_number",
            "album_id",
            "release_date",
            "track_length_sec",
            "iswc",
            "upc",
            "genre",
        }
        missing_columns = sorted(required_track_columns - track_columns)
        progress.complete("Checked required track columns.")

        if not missing_tables and not missing_columns:
            add_check(
                "Schema layout",
                "ok",
                "Required tables and promoted columns are present.",
                "All expected core tables exist, and the Tracks table includes the current promoted standard columns and media fields.",
            )
        else:
            details = [
                "The current database layout is missing expected schema elements.",
                "",
                f"Missing tables: {', '.join(missing_tables) if missing_tables else '(none)'}",
                f"Missing Tracks columns: {', '.join(missing_columns) if missing_columns else '(none)'}",
            ]
            add_check(
                "Schema layout",
                "error",
                "Database layout is incomplete for the current app version.",
                "\n".join(details),
                repair_key="schema_migrate",
                repair_label="Repair Schema Layout",
            )
    except Exception as exc:
        add_check(
            "Schema layout",
            "error",
            "Schema layout could not be inspected.",
            f"An exception occurred while reading table metadata:\n{exc}",
        )
        progress.complete(
            "Schema layout inspection failed.",
            units=max(0, 2 - (progress.completed_units - schema_layout_start)),
        )

    progress.set_message("Running SQLite integrity checks...")
    try:
        if active_database_maintenance is None or not current_path:
            raise RuntimeError("No active profile is open.")
        result = active_database_maintenance.verify_integrity(current_path)
        status = "ok" if str(result).strip().lower() == "ok" else "error"
        add_check(
            "SQLite integrity",
            status,
            str(result),
            f"PRAGMA integrity_check returned:\n{result}",
        )
    except Exception as exc:
        add_check(
            "SQLite integrity",
            "error",
            "Integrity check failed to run.",
            f"An exception occurred while running PRAGMA integrity_check:\n{exc}",
        )
    progress.complete("Finished SQLite integrity checks.")

    progress.set_message("Checking foreign-key consistency...")
    try:
        fk_rows = (
            connection.execute("PRAGMA foreign_key_check").fetchall()
            if connection is not None
            else []
        )
        if not fk_rows:
            add_check(
                "Foreign-key consistency",
                "ok",
                "0 issue(s) detected.",
                "PRAGMA foreign_key_check returned no rows.",
            )
        else:
            preview = "\n".join(
                f"table={row[0]}, rowid={row[1]}, parent={row[2]}, fk_index={row[3]}"
                for row in fk_rows[:25]
            )
            add_check(
                "Foreign-key consistency",
                "error",
                f"{len(fk_rows)} issue(s) detected.",
                f"PRAGMA foreign_key_check returned {len(fk_rows)} row(s).\n\n{preview}",
            )
    except Exception as exc:
        add_check(
            "Foreign-key consistency",
            "error",
            "Foreign-key validation failed to run.",
            f"An exception occurred while running PRAGMA foreign_key_check:\n{exc}",
        )
    progress.complete("Checked foreign-key consistency.")

    progress.set_message("Checking custom-value integrity...")
    try:
        orphan_count = app._count_orphaned_custom_values(conn=connection)
        if orphan_count == 0:
            add_check(
                "Custom-value integrity",
                "ok",
                "0 orphaned custom value row(s) detected.",
                "Every CustomFieldValues row points to an existing field definition and track.",
            )
        else:
            add_check(
                "Custom-value integrity",
                "warning",
                f"{orphan_count} orphaned custom value row(s) detected.",
                "Some CustomFieldValues rows reference a deleted track or custom field definition.",
                repair_key="custom_value_cleanup",
                repair_label="Delete Orphaned Custom Values",
                orphan_count=orphan_count,
            )
    except Exception as exc:
        add_check(
            "Custom-value integrity",
            "error",
            "Custom-value validation failed to run.",
            f"An exception occurred while checking CustomFieldValues:\n{exc}",
            repair_key="custom_value_cleanup",
            repair_label="Delete Orphaned Custom Values",
        )
    progress.complete("Checked custom-value integrity.")

    progress.set_message("Checking cached waveform previews...")
    try:
        if connection is None or active_track_service is None:
            raise RuntimeError("No active track service is available.")
        cache_service = AudioWaveformCacheService(connection)
        cache_inspection = cache_service.inspect_invalid_caches(active_track_service)
        if cache_inspection.issue_count == 0:
            add_check(
                "Audio waveform cache",
                "ok",
                f"{cache_inspection.valid_rows} cached waveform row(s) valid.",
                (
                    "Cached waveform preview rows point to existing tracks and match their current primary audio. "
                    f"Total cache rows: {cache_inspection.total_rows}."
                ),
            )
        else:
            details = "\n".join(cache_inspection.details[:25])
            add_check(
                "Audio waveform cache",
                "warning",
                f"{cache_inspection.issue_count} stale or orphaned cached waveform row(s) detected.",
                details
                or "Some cached waveform previews no longer match a live primary audio source.",
                repair_key="waveform_cache_cleanup",
                repair_label="Clean Waveform Cache",
                orphan_count=cache_inspection.issue_count,
                issue_count=cache_inspection.issue_count,
            )
    except Exception as exc:
        add_check(
            "Audio waveform cache",
            "error",
            "Cached waveform validation failed to run.",
            f"An exception occurred while checking cached waveform previews:\n{exc}",
            repair_key="waveform_cache_cleanup",
            repair_label="Clean Waveform Cache",
        )
    progress.complete("Checked cached waveform previews.")

    progress.set_message("Checking legacy default-column custom fields...")
    try:
        legacy_candidates = app._legacy_promoted_field_repair_candidates(conn=connection)
        if not legacy_candidates:
            add_check(
                "Legacy default-column custom fields",
                "ok",
                "0 legacy custom/default overlaps detected.",
                "No legacy custom field definitions currently overlap promoted default columns.",
            )
        else:
            details = []
            safe_count = 0
            for candidate in legacy_candidates:
                if candidate.eligible:
                    safe_count += 1
                details.append(
                    (
                        f"{candidate.field_name} "
                        f"(custom {candidate.custom_field_type} -> default {candidate.default_field_type}): "
                        f"{candidate.non_empty_value_count} stored value(s), "
                        f"{candidate.blank_target_count} blank target row(s), "
                        f"{len(candidate.conflicting_track_ids)} conflicting track(s)"
                    )
                )
            details.append("")
            details.append(
                "The repair action merges safe values into the promoted default column first and removes the redundant custom field only when no conflicting default-column data would be overwritten."
            )
            add_check(
                "Legacy default-column custom fields",
                "warning",
                f"{len(legacy_candidates)} legacy custom/default overlap(s) detected.",
                "\n".join(details),
                repair_key="legacy_promoted_field_repair",
                repair_label="Merge Into Default Columns",
                safe_candidate_count=safe_count,
                conflict_candidate_count=len(legacy_candidates) - safe_count,
            )
    except Exception as exc:
        add_check(
            "Legacy default-column custom fields",
            "error",
            "Legacy custom/default overlap inspection failed.",
            f"An exception occurred while checking for redundant promoted custom fields:\n{exc}",
            repair_key="legacy_promoted_field_repair",
            repair_label="Merge Into Default Columns",
        )
    progress.complete("Checked legacy default-column custom fields.")

    progress.set_message("Checking managed files...")
    managed_file_total = int(progress_plan["managed_file_units"])
    managed_file_completed = 0
    try:
        missing_files = []

        if connection is not None:
            media_rows = connection.execute(
                """
                SELECT id, track_title, audio_file_path
                FROM Tracks
                WHERE audio_file_path IS NOT NULL AND trim(audio_file_path) != ''
                ORDER BY id
                """
            ).fetchall()
            managed_file_start = progress.completed_units
            for track_id, track_title, audio_path in media_rows:
                resolved = (
                    active_track_service.resolve_media_path(audio_path)
                    if active_track_service
                    else Path(audio_path)
                )
                if resolved is not None and not resolved.exists():
                    missing_files.append(
                        f"Track #{track_id} '{track_title}': missing audio file -> {resolved}"
                    )
                managed_file_completed += 1
                progress.report_nested(
                    start_units=managed_file_start,
                    span_units=managed_file_total,
                    value=managed_file_completed,
                    maximum=managed_file_total,
                    message=(
                        f"Checking managed audio references ({managed_file_completed}/{managed_file_total})..."
                    ),
                )

            progress.set_message("Checking managed album artwork references...")
            album_art_rows = connection.execute(
                """
                SELECT id, title, album_art_path
                FROM Albums
                WHERE album_art_path IS NOT NULL AND album_art_path != ''
                ORDER BY id
                """
            ).fetchall()
            for album_id, album_title, art_path in album_art_rows:
                resolved = (
                    active_track_service.resolve_media_path(art_path)
                    if active_track_service
                    else Path(art_path)
                )
                if resolved is not None and not resolved.exists():
                    missing_files.append(
                        f"Album #{album_id} '{album_title or 'Untitled Album'}': missing album art -> {resolved}"
                    )
                managed_file_completed += 1
                progress.report_nested(
                    start_units=managed_file_start,
                    span_units=managed_file_total,
                    value=managed_file_completed,
                    maximum=managed_file_total,
                    message=(
                        f"Checking managed artwork references ({managed_file_completed}/{managed_file_total})..."
                    ),
                )

            progress.set_message("Checking managed license files...")
            license_rows = connection.execute(
                """
                SELECT id, filename, file_path
                FROM Licenses
                WHERE file_path IS NOT NULL AND trim(file_path) != ''
                ORDER BY id
                """
            ).fetchall()
            for record_id, filename, file_path in license_rows:
                resolved = (
                    active_license_service.resolve_path(file_path)
                    if active_license_service
                    else Path(file_path)
                )
                if not resolved.exists():
                    missing_files.append(
                        f"License #{record_id} '{filename or 'unnamed'}': missing file -> {resolved}"
                    )
                managed_file_completed += 1
                progress.report_nested(
                    start_units=managed_file_start,
                    span_units=managed_file_total,
                    value=managed_file_completed,
                    maximum=managed_file_total,
                    message=(
                        f"Checking managed license files ({managed_file_completed}/{managed_file_total})..."
                    ),
                )
        else:
            progress.complete("Checked managed files.")

        if not missing_files:
            add_check(
                "Managed files",
                "ok",
                "0 missing managed file(s) detected.",
                "All tracked audio files, album art files, and license PDFs that are referenced in the database are present on disk.",
            )
        else:
            preview = "\n".join(missing_files[:25])
            add_check(
                "Managed files",
                "warning",
                f"{len(missing_files)} missing managed file(s) detected.",
                f"Some database rows point to files that are no longer present on disk.\n\n{preview}",
            )
    except Exception as exc:
        add_check(
            "Managed files",
            "error",
            "Managed file validation failed to run.",
            f"An exception occurred while checking managed media and license files:\n{exc}",
        )
    if connection is not None:
        progress.complete(
            "Checked managed files.",
            units=max(0, managed_file_total - managed_file_completed),
        )

    progress.set_message("Inspecting history snapshots and backups...")
    history_start = progress.completed_units
    try:
        if active_history_manager is None:
            raise RuntimeError("No active history manager")
        recovery_issues = active_history_manager.inspect_recovery_state()
        progress.complete("Collected history recovery-state issues.")

        snapshot_issues = [
            issue
            for issue in recovery_issues
            if issue.issue_type
            in {
                "missing_snapshot_artifact",
                "missing_snapshot_archive",
                "orphan_snapshot_file",
                "dangling_snapshot_reference",
            }
        ]
        snapshot_details = "\n\n".join(
            "\n".join(
                [issue.message]
                + ([str(issue.path)] if issue.path else [])
                + ([f"Details: {issue.details}"] if issue.details else [])
            )
            for issue in snapshot_issues[:20]
        )
        snapshot_total = len(active_history_manager.list_snapshots(limit=10_000))
        if not snapshot_issues:
            add_check(
                "History snapshots",
                "ok",
                f"{snapshot_total} snapshot record(s) available.",
                "Snapshot records and their registered artifacts are internally consistent.",
            )
        else:
            add_check(
                "History snapshots",
                "warning",
                f"{len(snapshot_issues)} snapshot issue(s) detected.",
                snapshot_details,
                repair_key="history_reconcile",
                repair_label="Repair History Artifacts",
                orphan_count=len(snapshot_issues),
            )
        progress.complete("Evaluated history snapshot artifacts.")

        backup_issues = [
            issue
            for issue in recovery_issues
            if issue.issue_type
            in {
                "missing_backup_file",
                "missing_backup_history_artifact",
                "orphan_backup_file",
            }
        ]
        backup_details = "\n\n".join(
            "\n".join([issue.message] + ([str(issue.path)] if issue.path else []))
            for issue in backup_issues[:20]
        )
        backup_total = len(active_history_manager.list_backups(limit=10_000))
        if not backup_issues:
            add_check(
                "Backup artifacts",
                "ok",
                f"{backup_total} backup record(s) tracked.",
                "Registered backup files and on-disk backup artifacts are internally consistent.",
            )
        else:
            add_check(
                "Backup artifacts",
                "warning",
                f"{len(backup_issues)} backup issue(s) detected.",
                backup_details,
                repair_key="history_reconcile",
                repair_label="Repair History Artifacts",
                orphan_count=len(backup_issues),
            )
        progress.complete("Evaluated backup artifacts.")

        invariant_issues = [
            issue for issue in recovery_issues if issue.issue_type == "stale_current_head"
        ]
        invariant_details = "\n\n".join(issue.message for issue in invariant_issues[:20])
        if not invariant_issues:
            add_check(
                "History invariants",
                "ok",
                "History head and entry references are coherent.",
                "The current history pointer resolves to a valid entry, and no repair is needed.",
            )
        else:
            add_check(
                "History invariants",
                "warning",
                f"{len(invariant_issues)} history invariant issue(s) detected.",
                invariant_details,
                repair_key="history_reconcile",
                repair_label="Repair History Artifacts",
                orphan_count=len(invariant_issues),
            )
        progress.complete("Evaluated history invariants.")

        total_history_issues = len(snapshot_issues) + len(backup_issues) + len(invariant_issues)
        if total_history_issues:
            for check in checks[-3:]:
                check["issue_count"] = total_history_issues

        cleanup_service = HistoryStorageCleanupService(active_history_manager)
        retention_settings = (
            SettingsReadService(connection).load_history_retention_settings()
            if connection is not None
            else HistoryRetentionSettings()
        )
        budget_preview = cleanup_service.preview_storage_budget(retention_settings)
        mode_labels = {
            mode_key: label
            for mode_key, label, _description in ApplicationSettingsDialog.HISTORY_RETENTION_MODE_SPECS
        }
        reclaimable_bytes = sum(
            int(item.bytes_on_disk or 0) for item in budget_preview.candidate_items
        )
        history_storage_budget_summary = {
            "available": True,
            "total_bytes": int(budget_preview.total_bytes or 0),
            "budget_bytes": int(budget_preview.budget_bytes or 0),
            "over_budget_bytes": int(budget_preview.over_budget_bytes or 0),
            "reclaimable_bytes": int(reclaimable_bytes or 0),
            "candidate_count": len(budget_preview.candidate_items),
            "retention_mode_label": mode_labels.get(
                retention_settings.retention_mode,
                str(retention_settings.retention_mode or ""),
            ),
            "auto_cleanup_enabled": bool(retention_settings.auto_cleanup_enabled),
            "auto_cleanup_text": (
                "Enabled" if retention_settings.auto_cleanup_enabled else "Disabled"
            ),
            "usage_text": app._human_size(budget_preview.total_bytes),
            "budget_text": format_budget_megabytes(retention_settings.storage_budget_mb),
            "over_budget_text": app._human_size(budget_preview.over_budget_bytes),
            "reclaimable_text": app._human_size(reclaimable_bytes),
            "within_budget": budget_preview.over_budget_bytes <= 0,
        }
        budget_details = [
            f"Retention level: {mode_labels.get(retention_settings.retention_mode, retention_settings.retention_mode)}",
            (
                "Automatic cleanup: enabled"
                if retention_settings.auto_cleanup_enabled
                else "Automatic cleanup: disabled"
            ),
            f"Storage budget: {format_budget_megabytes(retention_settings.storage_budget_mb)}",
            f"Current usage: {app._human_size(budget_preview.total_bytes)}",
            f"Keep latest snapshots: {retention_settings.auto_snapshot_keep_latest}",
            (
                "Prune pre-restore safety copies: never"
                if retention_settings.prune_pre_restore_copies_after_days <= 0
                else (
                    "Prune pre-restore safety copies after "
                    f"{retention_settings.prune_pre_restore_copies_after_days} day(s)"
                )
            ),
            f"Current safe cleanup candidates: {len(budget_preview.candidate_items)}",
            f"Safe reclaimable space: {app._human_size(reclaimable_bytes)}",
        ]
        if budget_preview.over_budget_bytes <= 0:
            add_check(
                "History storage budget",
                "ok",
                "History storage is within the configured budget.",
                "\n".join(budget_details),
            )
            history_storage_budget_summary["summary"] = (
                f"History storage is using {app._human_size(budget_preview.total_bytes)} "
                f"of a {format_budget_megabytes(retention_settings.storage_budget_mb)} budget."
            )
        else:
            warning_summary = f"History storage is over budget by {app._human_size(budget_preview.over_budget_bytes)}."
            if budget_preview.auto_cleanup_enabled and budget_preview.candidate_items:
                warning_summary += " Safe cleanup candidates are available."
            elif budget_preview.protected_over_budget_items:
                warning_summary += " Remaining space is still needed by the current undo boundary or retained recovery artifacts."
            budget_details.extend(
                [
                    "",
                    f"Over budget by: {app._human_size(budget_preview.over_budget_bytes)}",
                ]
            )
            add_check(
                "History storage budget",
                "warning",
                warning_summary,
                "\n".join(budget_details),
            )
            history_storage_budget_summary["summary"] = (
                f"History storage is using {app._human_size(budget_preview.total_bytes)} "
                f"of a {format_budget_megabytes(retention_settings.storage_budget_mb)} budget and is over budget by "
                f"{app._human_size(budget_preview.over_budget_bytes)}."
            )
        progress.complete("Evaluated history storage budget.")
    except Exception as exc:
        add_check(
            "History snapshots",
            "error",
            "Snapshot storage could not be inspected.",
            f"An exception occurred while checking history artifacts:\n{exc}",
            repair_key="history_reconcile",
            repair_label="Repair History Artifacts",
            orphan_count=0,
        )
        history_storage_budget_summary = {
            **history_storage_budget_summary,
            "available": False,
            "summary": f"History storage information could not be inspected: {exc}",
        }
        progress.complete(
            "History diagnostics could not be completed cleanly.",
            units=max(
                0,
                int(progress_plan["history_units"]) - (progress.completed_units - history_start),
            ),
        )

    progress.set_message("Inspecting application-wide storage...")
    application_storage_start = progress.completed_units
    application_storage_units = int(progress_plan["application_storage_units"])
    try:
        application_storage_audit = app._application_storage_admin_service().inspect(
            current_db_path=current_path or None,
            status_callback=None,
            progress_callback=lambda value, maximum, message: progress.report_nested(
                start_units=application_storage_start,
                span_units=application_storage_units,
                value=value,
                maximum=maximum,
                message=message,
            ),
        )
        application_storage_summary = app._application_storage_summary_payload(
            application_storage_audit,
            current_db_path=current_path or None,
        )
        progress.complete(
            "Inspected application-wide storage.",
            units=max(
                0,
                application_storage_units - (progress.completed_units - application_storage_start),
            ),
        )
    except Exception as exc:
        application_storage_summary = {
            **application_storage_summary,
            "available": False,
            "summary": f"Application-wide storage information could not be inspected: {exc}",
        }
        progress.complete(
            "Application-wide storage inspection failed.",
            units=int(progress_plan["application_storage_units"]),
        )

    return {
        "environment": environment,
        "checks": checks,
        "history_storage_budget": history_storage_budget_summary,
        "application_storage": application_storage_summary,
        "_diagnostics_progress_total": int(progress_plan["overall_total_units"]),
    }

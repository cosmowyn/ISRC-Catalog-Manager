"""Diagnostics repair and application storage controller orchestration."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QWidget

from isrc_manager.media.waveform_cache import AudioWaveformCacheService
from isrc_manager.services import DatabaseSchemaService, LegacyPromotedFieldRepairService
from isrc_manager.storage_migration import (
    PREFERRED_STATE_CONFLICT,
    PREFERRED_STATE_RESUMABLE_STAGE,
    PREFERRED_STATE_VALID_COMPLETE,
    StorageMigrationService,
)


def _preview_diagnostics_repair(app, repair_key: str, check: dict | None = None) -> str:
    if repair_key == "storage_layout_migrate":
        inspection = app.storage_migration_service.inspect()
        if inspection.legacy_root is None and inspection.preferred_state not in (
            PREFERRED_STATE_VALID_COMPLETE,
            PREFERRED_STATE_RESUMABLE_STAGE,
        ):
            return "No legacy app-owned storage was detected, so no migration is needed."
        if inspection.preferred_state == PREFERRED_STATE_VALID_COMPLETE:
            return (
                "This will adopt the verified app-owned data already present in the preferred app folder "
                "and refresh startup settings to use it automatically."
            )
        if inspection.preferred_state == PREFERRED_STATE_RESUMABLE_STAGE:
            return (
                "This will resume the preserved staged app-data migration, verify the staged databases, "
                "and promote the staged root into the preferred app folder."
            )
        if inspection.preferred_state == PREFERRED_STATE_CONFLICT:
            conflict_text = (
                "\n".join(f"- {item}" for item in inspection.conflict_items[:10]) or "- (unknown)"
            )
            return (
                "The preferred app folder contains conflicting managed content that cannot be overwritten "
                "automatically.\n\n"
                f"Conflicting items:\n{conflict_text}"
            )
        return (
            "This will copy app-owned storage into the preferred app folder, rewrite known internal "
            "history and snapshot paths, verify copied databases, and keep the legacy folder intact.\n\n"
            f"Legacy folder: {inspection.legacy_root}\n"
            f"Preferred folder: {app.storage_layout.preferred_data_root}\n"
            f"Items to migrate: {', '.join(inspection.legacy_items)}"
        )
    if repair_key == "schema_migrate":
        return "This will re-run the schema bootstrap and migrations for the current profile."
    if repair_key == "custom_value_cleanup":
        count = None
        if check is not None:
            count = check.get("orphan_count")
        if count is None:
            count = app._count_orphaned_custom_values()
        return (
            f"This will delete {int(count)} orphaned custom value row(s) that no longer point to a valid "
            "track or custom field definition."
        )
    if repair_key == "waveform_cache_cleanup":
        count = 0
        if check is not None:
            count = int(check.get("issue_count") or check.get("orphan_count") or 0)
        return (
            f"This will delete {int(count)} stale or orphaned cached waveform row(s). "
            "The next startup cache pass or audio playback can regenerate valid previews from the current audio."
        )
    if repair_key == "legacy_promoted_field_repair":
        candidates = app._legacy_promoted_field_repair_candidates()
        if not candidates:
            return "No legacy custom fields currently overlap promoted default columns."
        eligible = [candidate for candidate in candidates if candidate.eligible]
        blocked = [candidate for candidate in candidates if not candidate.eligible]
        lines = [
            (
                f"- {candidate.field_name}: "
                f"{candidate.non_empty_value_count} stored value(s), "
                f"{candidate.blank_target_count} blank target row(s), "
                f"{len(candidate.conflicting_track_ids)} conflicting track(s)"
            )
            for candidate in candidates[:10]
        ]
        summary = [
            "This will merge safe legacy custom-field values into their promoted default columns, then remove the redundant custom field definitions and values.",
            "",
            f"Safe candidates: {len(eligible)}",
            f"Blocked by conflicting values: {len(blocked)}",
        ]
        if lines:
            summary.extend(["", "Fields:", *lines])
        if blocked:
            summary.extend(
                [
                    "",
                    "Fields with conflicting values will be skipped so no existing default-column data is overwritten silently.",
                ]
            )
        return "\n".join(summary)
    if repair_key == "history_reconcile":
        issue_count = 0
        if check is not None:
            issue_count = int(check.get("issue_count") or 0)
        return (
            f"This will reconcile {issue_count} history and recovery issue(s), repair stale current pointers, "
            "restore missing snapshots and backups from archived history artifacts when possible, re-register "
            "orphaned snapshot or backup files that still have metadata, and rebuild missing backup artifacts "
            "from live files when the current data is intact. Irrecoverable references will be left in place "
            "and reported as unresolved so the history trail is not silently erased."
        )
    raise ValueError(f"Unknown diagnostics repair: {repair_key}")


def _run_diagnostics_repair(app, repair_key: str, check: dict | None = None) -> str:
    if repair_key == "storage_layout_migrate":
        result = app._run_storage_layout_migration()
        return (
            f"App-owned data was {result.action} into the preferred storage layout.\n\n"
            f"Source: {result.source_root}\n"
            f"Target: {result.target_root}\n"
            f"Items: {', '.join(result.copied_items)}"
        )

    if repair_key == "schema_migrate":
        app.init_db()
        app.migrate_schema()
        app.active_custom_fields = app.load_active_custom_fields()
        app.refresh_table_preserve_view()
        app.populate_all_comboboxes()
        app._audit("REPAIR", "Schema", ref_id=app.current_db_path, details="schema_migrate")
        app._audit_commit()
        app._log_event(
            "diagnostics.repair.schema_migrate",
            "Diagnostics repair applied",
            repair_key=repair_key,
            status="ok",
        )
        return "Schema bootstrap and migration completed successfully."

    if repair_key == "custom_value_cleanup":
        field_column = app._custom_value_field_column_name()
        if field_column is None:
            raise RuntimeError("Could not determine the custom field reference column.")
        before_count = app._count_orphaned_custom_values()
        with app.conn:
            app.conn.execute(
                f"""
                DELETE FROM CustomFieldValues
                WHERE NOT EXISTS (
                    SELECT 1 FROM CustomFieldDefs cfd WHERE cfd.id = CustomFieldValues.{field_column}
                )
                OR NOT EXISTS (
                    SELECT 1 FROM Tracks t WHERE t.id = CustomFieldValues.track_id
                )
                """
            )
        after_count = app._count_orphaned_custom_values()
        removed = max(0, before_count - after_count)
        app._audit(
            "REPAIR",
            "CustomFieldValues",
            ref_id="orphans",
            details=f"removed={removed}; remaining={after_count}",
        )
        app._audit_commit()
        app._log_event(
            "diagnostics.repair.custom_value_cleanup",
            "Diagnostics repair applied",
            repair_key=repair_key,
            removed=removed,
            remaining=after_count,
        )
        return f"Removed {removed} orphaned custom value row(s)."

    if repair_key == "waveform_cache_cleanup":
        if app.conn is None or app.track_service is None:
            raise RuntimeError("Open a profile first.")
        cache_service = AudioWaveformCacheService(app.conn)
        removed = cache_service.cleanup_invalid_caches(app.track_service)
        app._audit(
            "REPAIR",
            "TrackAudioWaveformCache",
            ref_id="stale-or-orphaned",
            details=f"removed={removed}",
        )
        app._audit_commit()
        app._log_event(
            "diagnostics.repair.waveform_cache_cleanup",
            "Diagnostics repair applied",
            repair_key=repair_key,
            removed=removed,
        )
        return f"Removed {removed} stale or orphaned cached waveform row(s)."

    if repair_key == "legacy_promoted_field_repair":
        if app.conn is None:
            raise RuntimeError("Open a profile first.")
        result = LegacyPromotedFieldRepairService(app.conn).repair_candidates()
        app.active_custom_fields = app.load_active_custom_fields()
        app.refresh_table_preserve_view()
        app.populate_all_comboboxes()
        app._audit(
            "REPAIR",
            "CustomFieldDefs",
            ref_id="legacy_promoted_field_repair",
            details=(
                f"repaired={len(result.repaired_field_names)};"
                f" skipped={len(result.skipped_field_names)};"
                f" merged_values={result.merged_value_count}"
            ),
        )
        app._audit_commit()
        app._log_event(
            "diagnostics.repair.legacy_promoted_field_repair",
            "Diagnostics repair applied",
            repair_key=repair_key,
            repaired=len(result.repaired_field_names),
            skipped=len(result.skipped_field_names),
            merged_values=result.merged_value_count,
        )
        summary_parts = []
        if result.repaired_field_names:
            summary_parts.append(
                "Repaired fields:\n" + "\n".join(sorted(result.repaired_field_names))
            )
        else:
            summary_parts.append("No safe legacy default-column custom fields required repair.")
        if result.skipped_field_names:
            summary_parts.append(
                "Skipped because conflicting default-column values already exist:\n"
                + "\n".join(sorted(result.skipped_field_names))
            )
        summary_parts.append(
            f"Merged {result.merged_value_count} blank default-column value(s) and removed "
            f"{result.removed_field_count} redundant custom field definition(s)."
        )
        return "\n\n".join(summary_parts)

    if repair_key == "history_reconcile":
        if app.history_manager is None:
            raise RuntimeError("Open a profile first.")
        result = app.history_manager.repair_recovery_state()
        app._refresh_history_actions()
        app._audit("REPAIR", "History", ref_id=app.current_db_path, details="history_reconcile")
        app._audit_commit()
        app._log_event(
            "diagnostics.repair.history_reconcile",
            "History diagnostics repair applied",
            repair_key=repair_key,
            changes=len(result.changes),
            unresolved=len(result.unresolved),
        )
        summary_parts = []
        if result.changes:
            summary_parts.append("\n".join(result.changes))
        else:
            summary_parts.append("No registry changes were needed.")
        if result.unresolved:
            summary_parts.append("Unresolved:\n" + "\n".join(result.unresolved))
        return "\n\n".join(summary_parts)

    raise ValueError(f"Unknown diagnostics repair: {repair_key}")


def _load_application_storage_audit_async(
    app,
    *,
    owner: QWidget | None = None,
    on_success=None,
    on_error=None,
    on_cancelled=None,
    on_finished=None,
    on_status=None,
):
    current_path = str(getattr(app, "current_db_path", "") or "").strip()

    def _task(ctx):
        ctx.set_status("Inspecting application-wide storage...")
        return app._build_application_storage_audit_payload(
            current_db_path=current_path or None,
            status_callback=ctx.set_status,
            progress_callback=lambda value, maximum, message: ctx.report_progress(
                value=int(value),
                maximum=int(maximum),
                message=str(message or ""),
            ),
        )

    return app._submit_background_task(
        title="Application Storage Admin",
        description="Inspecting application-wide storage...",
        task_fn=_task,
        kind="read",
        unique_key="storage_admin.audit",
        requires_profile=False,
        show_dialog=False,
        owner=owner or app,
        on_success=on_success,
        on_error=on_error,
        on_cancelled=on_cancelled,
        on_finished=on_finished,
        on_status=on_status,
    )


def _run_application_storage_cleanup_async(
    app,
    item_keys: list[str] | tuple[str, ...],
    *,
    allow_warning_deletes: bool = False,
    owner: QWidget | None = None,
    on_success=None,
    on_error=None,
    on_cancelled=None,
    on_finished=None,
    on_status=None,
):
    current_path = str(getattr(app, "current_db_path", "") or "").strip()

    def _task(ctx):
        ctx.set_status("Deleting selected application storage items...")
        result = app._application_storage_admin_service().cleanup_selected(
            item_keys,
            current_db_path=current_path or None,
            allow_warning_deletes=allow_warning_deletes,
            status_callback=ctx.set_status,
            progress_callback=lambda value, maximum, message: ctx.report_progress(
                value=int(value),
                maximum=int(maximum),
                message=str(message or ""),
            ),
        )
        return {
            "removed_count": len(result.removed_item_keys),
            "removed_text": app._human_size(result.removed_bytes),
            "removed_bytes": int(result.removed_bytes),
            "removed_history_entry_count": len(result.removed_history_entry_ids),
            "removed_session_entry_count": len(result.removed_session_entry_ids),
            "skipped_count": len(result.skipped_item_keys),
        }

    return app._submit_background_task(
        title="Application Storage Cleanup",
        description="Deleting selected application storage items...",
        task_fn=_task,
        kind="write",
        unique_key="storage_admin.cleanup",
        requires_profile=False,
        show_dialog=True,
        owner=owner or app,
        on_success=on_success,
        on_error=on_error,
        on_cancelled=on_cancelled,
        on_finished=on_finished,
        on_status=on_status,
    )


def _load_diagnostics_report_async(
    app,
    *,
    owner: QWidget | None = None,
    on_success=None,
    on_error=None,
    on_cancelled=None,
    on_finished=None,
    on_progress=None,
    on_status=None,
):
    current_path = str(getattr(app, "current_db_path", "") or "").strip()

    app_version = app._app_version_text()
    data_root = app.data_root
    logs_dir = app.logs_dir
    storage_layout = app.storage_layout

    def _handle_success_before_cleanup(result, ui_progress) -> None:
        if on_success is not None:
            on_success(result)
        total_units = max(1, int((result or {}).get("_diagnostics_progress_total") or 1))
        ui_progress.report_progress(total_units, total_units, "Diagnostics ready.")

    if not current_path:

        def _task(ctx):
            ctx.set_status("Loading diagnostics...")
            return app._build_diagnostics_report(
                current_db_path=current_path or None,
                data_root=data_root,
                logs_dir=logs_dir,
                storage_migration_service=StorageMigrationService(
                    storage_layout,
                    settings=app.settings,
                ),
                app_version=app_version,
                status_callback=ctx.set_status,
                progress_callback=lambda value, maximum, message: ctx.report_progress(
                    value=int(value),
                    maximum=int(maximum),
                    message=str(message or ""),
                ),
            )

        return app._submit_background_task(
            title="Diagnostics",
            description="Loading diagnostics...",
            task_fn=_task,
            kind="read",
            unique_key="diagnostics.report",
            requires_profile=False,
            show_dialog=False,
            owner=owner or app,
            on_success_before_cleanup=_handle_success_before_cleanup,
            on_error=on_error,
            on_cancelled=on_cancelled,
            on_finished=on_finished,
            on_progress=on_progress,
            on_status=on_status,
        )

    def _task(bundle, ctx):
        ctx.set_status("Loading diagnostics...")
        storage_service = StorageMigrationService(storage_layout, settings=bundle.settings)
        schema_service = DatabaseSchemaService(bundle.conn, data_root=data_root)
        return app._build_diagnostics_report(
            conn=bundle.conn,
            schema_service=schema_service,
            current_db_path=current_path,
            data_root=data_root,
            logs_dir=logs_dir,
            track_service=bundle.track_service,
            license_service=bundle.license_service,
            history_manager=bundle.history_manager,
            database_maintenance=bundle.database_maintenance,
            storage_migration_service=storage_service,
            app_version=app_version,
            status_callback=ctx.set_status,
            progress_callback=lambda value, maximum, message: ctx.report_progress(
                value=int(value),
                maximum=int(maximum),
                message=str(message or ""),
            ),
        )

    return app._submit_background_bundle_task(
        title="Diagnostics",
        description="Loading diagnostics...",
        task_fn=_task,
        kind="read",
        unique_key="diagnostics.report",
        show_dialog=False,
        owner=owner or app,
        on_success_before_cleanup=_handle_success_before_cleanup,
        on_error=on_error,
        on_cancelled=on_cancelled,
        on_finished=on_finished,
        on_progress=on_progress,
        on_status=on_status,
    )


def _run_bundle_diagnostics_repair(
    app,
    repair_key: str,
    check: dict | None = None,
    *,
    bundle,
    current_db_path: str,
    data_root: str | Path,
    status_callback=None,
) -> dict[str, object]:
    def _set_status(message: str) -> None:
        if callable(status_callback):
            status_callback(str(message))

    if repair_key == "schema_migrate":
        _set_status("Applying schema migration...")
        schema_service = DatabaseSchemaService(bundle.conn, data_root=data_root)
        schema_service.init_db()
        schema_service.migrate_schema()
        return {
            "result_text": "Schema bootstrap and migration completed successfully.",
            "post_action": "refresh_schema",
            "audit_entity": "Schema",
            "audit_ref_id": current_db_path,
            "audit_details": "schema_migrate",
            "log_event": "diagnostics.repair.schema_migrate",
            "log_message": "Diagnostics repair applied",
            "log_fields": {
                "repair_key": repair_key,
                "status": "ok",
            },
        }

    if repair_key == "custom_value_cleanup":
        _set_status("Deleting orphaned custom values...")
        field_column = app._custom_value_field_column_name(conn=bundle.conn)
        if field_column is None:
            raise RuntimeError("Could not determine the custom field reference column.")
        before_count = app._count_orphaned_custom_values(conn=bundle.conn)
        with bundle.conn:
            bundle.conn.execute(
                f"""
                DELETE FROM CustomFieldValues
                WHERE NOT EXISTS (
                    SELECT 1 FROM CustomFieldDefs cfd WHERE cfd.id = CustomFieldValues.{field_column}
                )
                OR NOT EXISTS (
                    SELECT 1 FROM Tracks t WHERE t.id = CustomFieldValues.track_id
                )
                """
            )
        after_count = app._count_orphaned_custom_values(conn=bundle.conn)
        removed = max(0, before_count - after_count)
        return {
            "result_text": f"Removed {removed} orphaned custom value row(s).",
            "audit_entity": "CustomFieldValues",
            "audit_ref_id": "orphans",
            "audit_details": f"removed={removed}; remaining={after_count}",
            "log_event": "diagnostics.repair.custom_value_cleanup",
            "log_message": "Diagnostics repair applied",
            "log_fields": {
                "repair_key": repair_key,
                "removed": removed,
                "remaining": after_count,
            },
        }

    if repair_key == "waveform_cache_cleanup":
        _set_status("Deleting stale cached waveforms...")
        cache_service = AudioWaveformCacheService(bundle.conn)
        removed = cache_service.cleanup_invalid_caches(bundle.track_service)
        return {
            "result_text": f"Removed {removed} stale or orphaned cached waveform row(s).",
            "audit_entity": "TrackAudioWaveformCache",
            "audit_ref_id": "stale-or-orphaned",
            "audit_details": f"removed={removed}",
            "log_event": "diagnostics.repair.waveform_cache_cleanup",
            "log_message": "Diagnostics repair applied",
            "log_fields": {
                "repair_key": repair_key,
                "removed": removed,
            },
        }

    if repair_key == "legacy_promoted_field_repair":
        _set_status("Merging legacy custom fields into default columns...")
        result = LegacyPromotedFieldRepairService(bundle.conn).repair_candidates()
        summary_parts = []
        if result.repaired_field_names:
            summary_parts.append(
                "Repaired fields:\n" + "\n".join(sorted(result.repaired_field_names))
            )
        else:
            summary_parts.append("No safe legacy default-column custom fields required repair.")
        if result.skipped_field_names:
            summary_parts.append(
                "Skipped because conflicting default-column values already exist:\n"
                + "\n".join(sorted(result.skipped_field_names))
            )
        summary_parts.append(
            f"Merged {result.merged_value_count} blank default-column value(s) and removed "
            f"{result.removed_field_count} redundant custom field definition(s)."
        )
        return {
            "result_text": "\n\n".join(summary_parts),
            "post_action": "refresh_schema",
            "audit_entity": "CustomFieldDefs",
            "audit_ref_id": "legacy_promoted_field_repair",
            "audit_details": (
                f"repaired={len(result.repaired_field_names)};"
                f" skipped={len(result.skipped_field_names)};"
                f" merged_values={result.merged_value_count}"
            ),
            "log_event": "diagnostics.repair.legacy_promoted_field_repair",
            "log_message": "Diagnostics repair applied",
            "log_fields": {
                "repair_key": repair_key,
                "repaired": len(result.repaired_field_names),
                "skipped": len(result.skipped_field_names),
                "merged_values": result.merged_value_count,
            },
        }

    if repair_key == "history_reconcile":
        if bundle.history_manager is None:
            raise RuntimeError("Open a profile first.")
        _set_status("Reconciling history artifacts...")
        result = bundle.history_manager.repair_recovery_state()
        summary_parts = []
        if result.changes:
            summary_parts.append("\n".join(result.changes))
        else:
            summary_parts.append("No registry changes were needed.")
        if result.unresolved:
            summary_parts.append("Unresolved:\n" + "\n".join(result.unresolved))
        return {
            "result_text": "\n\n".join(summary_parts),
            "post_action": "refresh_history",
            "audit_entity": "History",
            "audit_ref_id": current_db_path,
            "audit_details": "history_reconcile",
            "log_event": "diagnostics.repair.history_reconcile",
            "log_message": "History diagnostics repair applied",
            "log_fields": {
                "repair_key": repair_key,
                "changes": len(result.changes),
                "unresolved": len(result.unresolved),
            },
        }

    raise ValueError(f"Unknown diagnostics repair: {repair_key}")


def _apply_diagnostics_repair_result(app, repair_key: str, result: dict[str, object] | None) -> str:
    payload = dict(result or {})
    post_action = str(payload.get("post_action") or "").strip()
    if post_action == "refresh_schema":
        if app.conn is not None:
            try:
                app.conn.commit()
            except Exception:
                pass
        app.active_custom_fields = app.load_active_custom_fields()
        app.refresh_table_preserve_view()
        app.populate_all_comboboxes()
    elif post_action == "refresh_history":
        app._refresh_history_actions()
        if app.history_dialog is not None and app.history_dialog.isVisible():
            app.history_dialog.refresh_data()

    audit_entity = str(payload.get("audit_entity") or "").strip()
    if audit_entity:
        app._audit(
            "REPAIR",
            audit_entity,
            ref_id=payload.get("audit_ref_id"),
            details=(
                str(payload.get("audit_details"))
                if payload.get("audit_details") is not None
                else None
            ),
        )
        app._audit_commit()

    event_name = str(payload.get("log_event") or "").strip()
    if event_name:
        log_fields = dict(payload.get("log_fields") or {})
        app._log_event(
            event_name,
            str(payload.get("log_message") or "Diagnostics repair applied"),
            **log_fields,
        )

    return str(payload.get("result_text") or "")


def _run_diagnostics_repair_async(
    app,
    repair_key: str,
    check: dict | None = None,
    *,
    owner: QWidget | None = None,
    on_success=None,
    on_error=None,
    on_cancelled=None,
    on_finished=None,
    on_status=None,
):
    current_path = str(getattr(app, "current_db_path", "") or "").strip()

    def _handle_success(result: dict[str, object]) -> None:
        result_text = app._apply_diagnostics_repair_result(repair_key, result)
        if on_success is not None:
            on_success(result_text)

    def _task(bundle, ctx):
        return app._run_bundle_diagnostics_repair(
            repair_key,
            check,
            bundle=bundle,
            current_db_path=current_path,
            data_root=app.data_root,
            status_callback=ctx.set_status,
        )

    return app._submit_background_bundle_task(
        title="Diagnostics Repair",
        description=(str((check or {}).get("repair_label") or "Applying diagnostics repair...")),
        task_fn=_task,
        kind="write",
        unique_key=f"diagnostics.repair.{repair_key}",
        show_dialog=False,
        owner=owner or app,
        on_success=_handle_success,
        on_error=on_error,
        on_cancelled=on_cancelled,
        on_finished=on_finished,
        on_status=on_status,
    )

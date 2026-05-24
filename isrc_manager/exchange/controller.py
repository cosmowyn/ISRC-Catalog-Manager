"""Core catalog exchange import/export orchestration for the application shell."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtWidgets import QDialog, QFileDialog, QMessageBox

from isrc_manager.exchange import ExchangeImportOptions, ExchangeImportReport, ExchangeInspection
from isrc_manager.exchange.dialogs import ExchangeImportDialog
from isrc_manager.import_review_dialog import ImportReviewDialog
from isrc_manager.tasks.history_helpers import run_file_history_action, run_snapshot_history_action


def _root_attr(name: str, fallback):
    main_window_module = sys.modules.get("isrc_manager.main_window")
    return (
        getattr(main_window_module, name, fallback) if main_window_module is not None else fallback
    )


def _message_box():
    return _root_attr("QMessageBox", QMessageBox)


def _file_dialog():
    return _root_attr("QFileDialog", QFileDialog)


def _open_import_review_dialog(
    app,
    *,
    title: str,
    subtitle: str,
    summary_lines: list[str],
    warnings: list[str] | None = None,
    preview_rows: list[dict[str, object]] | None = None,
    preview_headers: list[str] | None = None,
    preview_title: str = "Preview",
    confirm_label: str = "Apply Import",
) -> bool:
    dialog = _root_attr("ImportReviewDialog", ImportReviewDialog)(
        title=title,
        subtitle=subtitle,
        summary_lines=summary_lines,
        warnings=warnings,
        preview_title=preview_title,
        preview_rows=preview_rows,
        preview_headers=preview_headers,
        confirm_label=confirm_label,
        parent=app,
    )
    return dialog.exec() == QDialog.Accepted


def _exchange_import_review_summary(report: ExchangeImportReport) -> list[str]:
    evaluated_mode = str(report.evaluated_mode or report.mode or "dry_run")
    lines = [
        f"Planned mode: {evaluated_mode}",
        f"Rows ready: {report.passed}",
        f"Rows blocked: {report.failed}",
        f"Rows skipped: {report.skipped}",
    ]
    if report.would_create_tracks:
        lines.append(f"Would create tracks: {report.would_create_tracks}")
    if report.would_update_tracks:
        lines.append(f"Would update tracks: {report.would_update_tracks}")
    identifier_labels = {
        "catalog_number": "Catalog Number",
        "contract_number": "Contract Number",
        "license_number": "License Number",
        "registry_sha256_key": "Registry SHA-256 Key",
    }
    for system_key in (
        "catalog_number",
        "contract_number",
        "license_number",
        "registry_sha256_key",
    ):
        counts = report.identifier_totals.get(system_key) or {}
        parts: list[str] = []
        if counts.get("internal"):
            parts.append(f"internal {int(counts['internal'])}")
        if counts.get("external"):
            parts.append(f"external {int(counts['external'])}")
        if counts.get("mismatch"):
            parts.append(f"mismatch {int(counts['mismatch'])}")
        if counts.get("merged"):
            parts.append(f"merged/skipped {int(counts['merged'])}")
        if counts.get("skipped"):
            parts.append(f"skipped {int(counts['skipped'])}")
        if counts.get("conflicted"):
            parts.append(f"conflicted {int(counts['conflicted'])}")
        if parts:
            lines.append(f"{identifier_labels[system_key]}: " + ", ".join(parts))
    if report.duplicates:
        lines.append(f"Duplicate-safe skips: {len(report.duplicates)}")
    if report.unknown_fields:
        lines.append("Unknown fields: " + ", ".join(report.unknown_fields[:8]))
    return lines


def import_exchange_file(app, format_name: str):
    if app.exchange_service is None:
        _message_box().warning(app, "Import Exchange", "Open a profile first.")
        return
    normalized_format = str(format_name or "").strip().lower()
    filters = {
        "csv": "CSV Files (*.csv)",
        "xlsx": "Excel Workbook (*.xlsx)",
        "json": "JSON Files (*.json)",
        "package": "ZIP Packages (*.zip)",
        "xml": "XML Files (*.xml)",
    }
    path, _ = _file_dialog().getOpenFileName(
        app,
        f"Import {normalized_format.upper()}",
        "",
        filters.get(normalized_format, "All files (*)"),
    )
    if not path:
        return

    def _inspection_worker(bundle, ctx):
        inspection_progress = app._scaled_progress_callback(ctx.report_progress, start=0, end=90)
        ctx.report_progress(
            value=0,
            maximum=100,
            message=f"Inspecting {normalized_format.upper()} source file...",
        )
        if normalized_format == "csv":
            return bundle.exchange_service.inspect_csv(
                path,
                progress_callback=inspection_progress,
                cancel_callback=ctx.raise_if_cancelled,
            )
        if normalized_format == "xlsx":
            return bundle.exchange_service.inspect_xlsx(
                path,
                progress_callback=inspection_progress,
                cancel_callback=ctx.raise_if_cancelled,
            )
        if normalized_format == "json":
            return bundle.exchange_service.inspect_json(
                path,
                progress_callback=inspection_progress,
                cancel_callback=ctx.raise_if_cancelled,
            )
        if normalized_format == "package":
            return bundle.exchange_service.inspect_package(
                path,
                progress_callback=inspection_progress,
                cancel_callback=ctx.raise_if_cancelled,
            )
        if normalized_format == "xml":
            xml_inspection, exchange_inspection = (
                bundle.xml_import_service.build_exchange_inspection(path)
            )
            inspection_progress(
                value=90,
                maximum=100,
                message="Building exchange import preview...",
            )
            return {
                "xml_inspection": xml_inspection,
                "exchange_inspection": exchange_inspection,
            }
        raise ValueError(f"Unsupported exchange format: {normalized_format}")

    def _inspection_success(inspection):
        supported_headers = app.exchange_service.supported_import_targets()
        inspection_payload = inspection
        if normalized_format == "xml":
            inspection_payload = inspection if isinstance(inspection, dict) else {}
            xml_inspection = inspection_payload.get("xml_inspection")
            if xml_inspection is None:
                raise ValueError("XML inspection did not return the expected preflight data.")
            if xml_inspection.conflicting_custom_fields:
                msg = "Custom columns already exist with a different type:\n" + "\n".join(
                    f"- {name} : XML={import_type}, profile={existing_type}"
                    for name, import_type, existing_type in xml_inspection.conflicting_custom_fields
                )
                _message_box().critical(app, "Import XML", msg + "\n\nNo changes were made.")
                return
            for field_name, _field_type in xml_inspection.missing_custom_fields:
                target_name = f"custom::{field_name}"
                if target_name not in supported_headers:
                    supported_headers.append(target_name)
            inspection = inspection_payload.get("exchange_inspection")
            if inspection is None:
                raise ValueError("XML exchange inspection did not return preview data.")

        def _csv_reinspect(delimiter: str | None) -> ExchangeInspection:
            return app.exchange_service.inspect_csv(path, delimiter=delimiter)

        dlg = _root_attr("ExchangeImportDialog", ExchangeImportDialog)(
            inspection=inspection,
            supported_headers=supported_headers,
            settings=app.settings,
            initial_mode=("create" if normalized_format == "package" else "dry_run"),
            csv_reinspect_callback=(_csv_reinspect if normalized_format == "csv" else None),
            parent=app,
        )
        if dlg.exec() != QDialog.Accepted:
            return

        mapping = dlg.mapping()
        options = dlg.import_options()
        selected_csv_delimiter = dlg.resolved_csv_delimiter()

        def _submit_import_task(active_options: ExchangeImportOptions) -> None:
            def _import_worker(bundle, ctx):
                import_progress = app._scaled_progress_callback(
                    ctx.report_progress,
                    start=0,
                    end=(90 if active_options.mode != "dry_run" else 96),
                )
                ctx.report_progress(
                    value=0,
                    maximum=100,
                    message=f"Importing {normalized_format.upper()} exchange data...",
                )

                def _mutation():
                    if normalized_format == "csv":
                        return bundle.exchange_service.import_csv(
                            path,
                            mapping=mapping,
                            options=active_options,
                            delimiter=selected_csv_delimiter,
                            progress_callback=import_progress,
                            cancel_callback=ctx.raise_if_cancelled,
                        )
                    if normalized_format == "xlsx":
                        return bundle.exchange_service.import_xlsx(
                            path,
                            mapping=mapping,
                            options=active_options,
                            progress_callback=import_progress,
                            cancel_callback=ctx.raise_if_cancelled,
                        )
                    if normalized_format == "package":
                        return bundle.exchange_service.import_package(
                            path,
                            mapping=mapping,
                            options=active_options,
                            progress_callback=import_progress,
                            cancel_callback=ctx.raise_if_cancelled,
                        )
                    if normalized_format == "xml":
                        return bundle.exchange_service.import_xml(
                            path,
                            mapping=mapping,
                            options=active_options,
                            progress_callback=import_progress,
                            cancel_callback=ctx.raise_if_cancelled,
                        )
                    return bundle.exchange_service.import_json(
                        path,
                        mapping=mapping,
                        options=active_options,
                        progress_callback=import_progress,
                        cancel_callback=ctx.raise_if_cancelled,
                    )

                if active_options.mode == "dry_run":
                    return _mutation()

                return _root_attr("run_snapshot_history_action", run_snapshot_history_action)(
                    history_manager=bundle.history_manager,
                    action_label=f"Import {normalized_format.upper()}: {Path(path).name}",
                    action_type=f"import.{normalized_format}",
                    entity_type="Import",
                    entity_id=path,
                    payload={"path": path, "mode": active_options.mode},
                    mutation=_mutation,
                    progress_callback=ctx.report_progress,
                    post_mutation_progress=(92, "Capturing import history snapshot..."),
                    record_progress=(94, "Recording import history..."),
                    logger=app.logger,
                )

            def _import_before_cleanup(report: ExchangeImportReport, ui_progress) -> None:
                if active_options.mode == "dry_run":
                    app._advance_task_ui_progress(
                        ui_progress,
                        value=100,
                        message="Exchange import validation complete.",
                    )
                    return
                app._advance_task_ui_progress(
                    ui_progress,
                    value=97,
                    message="Applying imported identifier changes...",
                )
                try:
                    app.conn.commit()
                except Exception:
                    pass
                app._advance_task_ui_progress(
                    ui_progress,
                    value=99,
                    message="Refreshing catalog views and history...",
                )
                app.refresh_table_preserve_view(
                    focus_id=(report.created_tracks or report.updated_tracks or [None])[0]
                )
                app._refresh_history_actions()
                app.populate_all_comboboxes()
                app._advance_task_ui_progress(
                    ui_progress,
                    value=100,
                    message="Exchange import complete.",
                )

            def _import_success(report: ExchangeImportReport):
                app._log_event(
                    f"import.{normalized_format}",
                    f"Imported {normalized_format.upper()} exchange data",
                    path=path,
                    mode=active_options.mode,
                    passed=report.passed,
                    failed=report.failed,
                    skipped=report.skipped,
                    warnings=report.warnings,
                    duplicates=report.duplicates,
                    unknown_fields=report.unknown_fields,
                    repair_queue_entry_ids=report.repair_queue_entry_ids,
                )
                app._audit(
                    "IMPORT",
                    normalized_format.upper(),
                    ref_id=path,
                    details=(
                        f"mode={active_options.mode}; passed={report.passed}; failed={report.failed}; "
                        f"skipped={report.skipped}; duplicates={len(report.duplicates)}; "
                        f"repair_queue={len(report.repair_queue_entry_ids)}"
                    ),
                )
                app._audit_commit()
                app._show_exchange_import_report(path, report)

            app._submit_background_bundle_task(
                title=f"Import {normalized_format.upper()}",
                description=f"Importing {normalized_format.upper()} data into the current profile...",
                task_fn=_import_worker,
                kind=("read" if active_options.mode == "dry_run" else "write"),
                unique_key=f"exchange.import.{normalized_format}",
                worker_completion_progress=(
                    (96, "Finalizing background import transaction...")
                    if active_options.mode != "dry_run"
                    else (100, "Exchange import validation complete.")
                ),
                on_success_before_cleanup=_import_before_cleanup,
                on_success_after_cleanup=_import_success,
                on_error=lambda failure: app._show_background_task_error(
                    "Import Exchange",
                    failure,
                    user_message="Could not complete the exchange import:",
                ),
            )

        def _run_preflight_review() -> None:
            preview_options = ExchangeImportOptions(
                mode="dry_run",
                match_by_internal_id=options.match_by_internal_id,
                match_by_isrc=options.match_by_isrc,
                match_by_upc_title=options.match_by_upc_title,
                heuristic_match=options.heuristic_match,
                create_missing_custom_fields=options.create_missing_custom_fields,
                skip_targets=list(options.skip_targets),
                preview_apply_mode=options.mode,
            )

            def _preview_worker(bundle, ctx):
                preview_progress = app._scaled_progress_callback(
                    ctx.report_progress,
                    start=0,
                    end=96,
                )
                ctx.report_progress(
                    value=0,
                    maximum=100,
                    message="Running exchange import dry-run review...",
                )
                if normalized_format == "csv":
                    return bundle.exchange_service.import_csv(
                        path,
                        mapping=mapping,
                        options=preview_options,
                        delimiter=selected_csv_delimiter,
                        progress_callback=preview_progress,
                        cancel_callback=ctx.raise_if_cancelled,
                    )
                if normalized_format == "xlsx":
                    return bundle.exchange_service.import_xlsx(
                        path,
                        mapping=mapping,
                        options=preview_options,
                        progress_callback=preview_progress,
                        cancel_callback=ctx.raise_if_cancelled,
                    )
                if normalized_format == "package":
                    return bundle.exchange_service.import_package(
                        path,
                        mapping=mapping,
                        options=preview_options,
                        progress_callback=preview_progress,
                        cancel_callback=ctx.raise_if_cancelled,
                    )
                if normalized_format == "xml":
                    return bundle.exchange_service.import_xml(
                        path,
                        mapping=mapping,
                        options=preview_options,
                        progress_callback=preview_progress,
                        cancel_callback=ctx.raise_if_cancelled,
                    )
                return bundle.exchange_service.import_json(
                    path,
                    mapping=mapping,
                    options=preview_options,
                    progress_callback=preview_progress,
                    cancel_callback=ctx.raise_if_cancelled,
                )

            def _preview_success(report: ExchangeImportReport) -> None:
                accepted = app._open_import_review_dialog(
                    title=f"Review {normalized_format.upper()} Import",
                    subtitle=(
                        "Dry run completed. Review the planned identifier changes before anything is written to the current profile."
                    ),
                    summary_lines=app._exchange_import_review_summary(report),
                    warnings=report.warnings,
                    preview_rows=inspection.preview_rows,
                    preview_headers=inspection.headers,
                    preview_title="Source Preview",
                    confirm_label="Apply Import",
                )
                if accepted:
                    _submit_import_task(options)

            app._submit_background_bundle_task(
                title=f"Review {normalized_format.upper()}",
                description="Running a dry-run review of the selected import...",
                task_fn=_preview_worker,
                kind="read",
                unique_key=f"exchange.review.{normalized_format}",
                worker_completion_progress=(100, "Import review ready."),
                on_success_after_cleanup=_preview_success,
                on_error=lambda failure: app._show_background_task_error(
                    "Import Exchange",
                    failure,
                    user_message="Could not review the import before apply:",
                ),
            )

        if options.mode == "dry_run":
            _submit_import_task(options)
        else:
            _run_preflight_review()

    app._submit_background_bundle_task(
        title=f"Inspect {normalized_format.upper()}",
        description=f"Inspecting the selected {normalized_format.upper()} source...",
        task_fn=_inspection_worker,
        kind="read",
        unique_key=f"exchange.inspect.{normalized_format}",
        worker_completion_progress=(100, "Exchange import inspection complete."),
        on_success_after_cleanup=_inspection_success,
        on_error=lambda failure: app._show_background_task_error(
            "Import Exchange",
            failure,
            user_message="Could not inspect the selected file:",
        ),
    )


def reset_saved_exchange_import_choices(app) -> None:
    if (
        _message_box().question(
            app,
            "Reset Saved Import Choices",
            "Clear the remembered import choices for XML, CSV, XLSX, JSON, and ZIP package imports?",
            _message_box().Yes | _message_box().No,
            _message_box().No,
        )
        != _message_box().Yes
    ):
        return
    app.settings.remove("exchange/import_preferences")
    app.settings.sync()
    _message_box().information(
        app,
        "Reset Saved Import Choices",
        "Saved exchange import choices were cleared.",
    )


def _show_exchange_import_report(app, path: str, report: ExchangeImportReport) -> None:
    lines = [
        f"Format: {report.format_name.upper()}",
        f"Mode: {report.mode}",
        f"Passed: {report.passed}",
        f"Failed: {report.failed}",
        f"Skipped: {report.skipped}",
    ]
    if report.mode == "dry_run":
        lines.append("")
        lines.append("No database changes were made because this run used Dry run validation mode.")
        if report.would_create_tracks:
            lines.append(f"Would create tracks: {report.would_create_tracks}")
        if report.would_update_tracks:
            lines.append(f"Would update tracks: {report.would_update_tracks}")
    identifier_labels = {
        "catalog_number": "Catalog Number",
        "contract_number": "Contract Number",
        "license_number": "License Number",
        "registry_sha256_key": "Registry SHA-256 Key",
    }
    for system_key in (
        "catalog_number",
        "contract_number",
        "license_number",
        "registry_sha256_key",
    ):
        counts = report.identifier_totals.get(system_key) or {}
        if not counts:
            continue
        parts: list[str] = []
        if counts.get("internal"):
            parts.append(f"internal {int(counts['internal'])}")
        if counts.get("external"):
            parts.append(f"external {int(counts['external'])}")
        if counts.get("mismatch"):
            parts.append(f"mismatch {int(counts['mismatch'])}")
        if counts.get("merged"):
            parts.append(f"merged/skipped {int(counts['merged'])}")
        if counts.get("skipped"):
            parts.append(f"skipped {int(counts['skipped'])}")
        if counts.get("conflicted"):
            parts.append(f"conflicted {int(counts['conflicted'])}")
        if parts:
            lines.append(f"{identifier_labels[system_key]}: " + ", ".join(parts))
    if report.duplicates:
        lines.append(f"Duplicates: {len(report.duplicates)}")
    if report.repair_queue_entry_ids:
        lines.append(f"Repair queue: {len(report.repair_queue_entry_ids)}")
    if report.unknown_fields:
        lines.append("Unknown fields: " + ", ".join(report.unknown_fields[:8]))
    if report.warnings:
        lines.append("")
        lines.append("Warnings:")
        lines.extend(f"- {warning}" for warning in report.warnings[:12])
    message_box = QMessageBox(app)
    message_box.setIcon(_message_box().Information)
    message_box.setWindowTitle(f"Import {report.format_name.upper()}")
    message_box.setText("\n".join(lines) + f"\n\nSource:\n{path}")
    open_queue_button = None
    if report.repair_queue_entry_ids:
        open_queue_button = message_box.addButton(
            "Open Repair Queue",
            _message_box().ActionRole,
        )
    message_box.addButton(_message_box().Ok)
    message_box.exec()
    if open_queue_button is not None and message_box.clickedButton() is open_queue_button:
        focus_entry_id = report.repair_queue_entry_ids[0] if report.repair_queue_entry_ids else None
        app.open_track_import_repair_queue(focus_entry_id=focus_entry_id)


def export_exchange_file(app, format_name: str, *, selected_only: bool):
    if app.exchange_service is None:
        _message_box().warning(app, "Export Exchange", "Open a profile first.")
        return
    normalized_format = str(format_name or "").strip().lower()
    track_ids = (
        list(app._catalog_table_controller().selected_or_visible_track_ids())
        if selected_only
        else None
    )
    if selected_only and not track_ids:
        _message_box().information(
            app,
            "Export Exchange",
            "Select one or more rows or apply a filter first.",
        )
        return

    extension_map = {
        "csv": ("CSV Files (*.csv)", ".csv"),
        "xlsx": ("Excel Workbooks (*.xlsx)", ".xlsx"),
        "json": ("JSON Files (*.json)", ".json"),
        "package": ("ZIP Packages (*.zip)", ".zip"),
    }
    file_filter, suffix = extension_map.get(normalized_format, ("All files (*)", ""))
    default_name = f"{'selected' if selected_only else 'full'}_{normalized_format}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{suffix}"
    path, _ = _file_dialog().getSaveFileName(
        app,
        f"Export {normalized_format.upper()}",
        str(app.exports_dir / default_name),
        file_filter,
    )
    if not path:
        return
    try:
        resolved_path = app._resolve_file_export_target(path, default_filename=default_name)
    except ValueError as exc:
        _message_box().warning(app, "Export Exchange", str(exc))
        return

    def _worker(bundle, ctx):
        export_progress = app._scaled_progress_callback(ctx.report_progress, start=0, end=94)

        def mutation():
            if normalized_format == "csv":
                return bundle.exchange_service.export_csv(
                    resolved_path, track_ids, progress_callback=export_progress
                )
            if normalized_format == "xlsx":
                return bundle.exchange_service.export_xlsx(
                    resolved_path, track_ids, progress_callback=export_progress
                )
            if normalized_format == "json":
                return bundle.exchange_service.export_json(
                    resolved_path, track_ids, progress_callback=export_progress
                )
            if normalized_format == "package":
                return bundle.exchange_service.export_package(
                    resolved_path, track_ids, progress_callback=export_progress
                )
            raise ValueError(f"Unsupported exchange format: {normalized_format}")

        return _root_attr("run_file_history_action", run_file_history_action)(
            history_manager=bundle.history_manager,
            action_label=lambda count: f"Export {normalized_format.upper()}: {count} rows",
            action_type=f"file.export_{normalized_format}",
            target_path=resolved_path,
            mutation=mutation,
            entity_type="Export",
            entity_id=str(resolved_path),
            payload=lambda count: {
                "path": str(resolved_path),
                "format": normalized_format,
                "selected_only": bool(selected_only),
                "count": count,
            },
            progress_callback=ctx.report_progress,
            post_mutation_progress=(96, "Capturing exchange export history..."),
            record_progress=(98, "Recording exchange export history..."),
            logger=app.logger,
        )

    def _success(exported):
        app._refresh_history_actions()
        app._log_event(
            f"export.{normalized_format}",
            f"Exported {normalized_format.upper()} exchange data",
            path=str(resolved_path),
            exported=exported,
            selected_only=selected_only,
        )
        app._audit(
            "EXPORT",
            normalized_format.upper(),
            ref_id=str(resolved_path),
            details=f"count={exported}; selected_only={int(bool(selected_only))}",
        )
        app._audit_commit()
        _message_box().information(
            app,
            "Export Exchange",
            f"Exported {exported} row{'s' if exported != 1 else ''} to:\n{resolved_path}",
        )

    app._submit_background_bundle_task(
        title=f"Export {normalized_format.upper()}",
        description=f"Exporting {normalized_format.upper()} exchange data...",
        task_fn=_worker,
        kind="read",
        unique_key=f"exchange.export.{normalized_format}",
        worker_completion_progress=(100, "Exchange export complete."),
        on_success_after_cleanup=_success,
        on_error=lambda failure: app._show_background_task_error(
            "Export Exchange",
            failure,
            user_message="Could not export the selected data:",
        ),
    )

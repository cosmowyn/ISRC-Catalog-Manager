"""Repertoire exchange workflow orchestration for the application shell."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QMessageBox

from isrc_manager.exchange import RepertoireImportInspection
from isrc_manager.tasks.history_helpers import run_file_history_action, run_snapshot_history_action


def _root_attr(name: str, fallback):
    main_window_module = sys.modules.get("isrc_manager.main_window")
    return (
        getattr(main_window_module, name, fallback)
        if main_window_module is not None
        else fallback
    )


def _message_box():
    return _root_attr("QMessageBox", QMessageBox)


def _file_dialog():
    return _root_attr("QFileDialog", QFileDialog)


def export_repertoire_exchange(app, format_name: str):
    if app.repertoire_exchange_service is None:
        _message_box().warning(app, "Repertoire Exchange", "Open a profile first.")
        return
    normalized = str(format_name or "").strip().lower()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if normalized == "json":
        default_name = f"contracts_and_rights_json_{timestamp}.json"
        path, _ = _file_dialog().getSaveFileName(
            app,
            "Export Repertoire JSON",
            str(app.exports_dir / default_name),
            "JSON Files (*.json)",
        )
        if not path:
            return
        try:
            resolved_path = app._resolve_file_export_target(
                path,
                default_filename=default_name,
            )
        except ValueError as exc:
            _message_box().warning(app, "Repertoire Exchange", str(exc))
            return
    elif normalized == "xlsx":
        default_name = f"contracts_and_rights_xlsx_{timestamp}.xlsx"
        path, _ = _file_dialog().getSaveFileName(
            app,
            "Export Repertoire XLSX",
            str(app.exports_dir / default_name),
            "Excel Files (*.xlsx)",
        )
        if not path:
            return
        try:
            resolved_path = app._resolve_file_export_target(
                path,
                default_filename=default_name,
            )
        except ValueError as exc:
            _message_box().warning(app, "Repertoire Exchange", str(exc))
            return
    elif normalized == "csv":
        default_name = f"contracts_and_rights_csv_bundle_{timestamp}"
        path = _file_dialog().getExistingDirectory(
            app,
            "Export Repertoire CSV Bundle",
            str(app.exports_dir),
        )
        if not path:
            return
        try:
            resolved_path = app._resolve_directory_export_target(
                path,
                default_name=default_name,
            )
        except ValueError as exc:
            _message_box().warning(app, "Repertoire Exchange", str(exc))
            return
    elif normalized == "package":
        default_name = f"contracts_and_rights_zip_{timestamp}.zip"
        path, _ = _file_dialog().getSaveFileName(
            app,
            "Export Repertoire ZIP Package",
            str(app.exports_dir / default_name),
            "ZIP Files (*.zip)",
        )
        if not path:
            return
        try:
            resolved_path = app._resolve_file_export_target(
                path,
                default_filename=default_name,
            )
        except ValueError as exc:
            _message_box().warning(app, "Repertoire Exchange", str(exc))
            return
    else:
        return

    def _worker(bundle, ctx):
        export_progress = app._scaled_progress_callback(ctx.report_progress, start=0, end=94)

        def _mutation():
            if normalized == "json":
                bundle.repertoire_exchange_service.export_json(
                    resolved_path,
                    progress_callback=export_progress,
                )
            elif normalized == "xlsx":
                bundle.repertoire_exchange_service.export_xlsx(
                    resolved_path,
                    progress_callback=export_progress,
                )
            elif normalized == "csv":
                bundle.repertoire_exchange_service.export_csv_bundle(
                    resolved_path,
                    progress_callback=export_progress,
                )
            else:
                bundle.repertoire_exchange_service.export_package(
                    resolved_path,
                    progress_callback=export_progress,
                )
            return str(resolved_path)

        if normalized == "csv":
            return _root_attr("run_snapshot_history_action", run_snapshot_history_action)(
                history_manager=bundle.history_manager,
                action_label="Export Contracts and Rights CSV Bundle",
                action_type="repertoire.export_csv_bundle",
                mutation=_mutation,
                entity_type="RepertoireExport",
                entity_id=str(resolved_path),
                payload={"path": str(resolved_path), "format": normalized},
                progress_callback=ctx.report_progress,
                post_mutation_progress=(96, "Capturing repertoire export history..."),
                record_progress=(98, "Recording repertoire export history..."),
                logger=app.logger,
            )
        return _root_attr("run_file_history_action", run_file_history_action)(
            history_manager=bundle.history_manager,
            action_label="Export Contracts and Rights",
            action_type=f"file.repertoire_export_{normalized}",
            target_path=resolved_path,
            mutation=_mutation,
            entity_type="RepertoireExport",
            entity_id=str(resolved_path),
            payload={"path": str(resolved_path), "format": normalized},
            progress_callback=ctx.report_progress,
            post_mutation_progress=(96, "Capturing repertoire export history..."),
            record_progress=(98, "Recording repertoire export history..."),
            logger=app.logger,
        )

    def _success(_path: str) -> None:
        if app.statusBar() is not None:
            app.statusBar().showMessage("Repertoire export complete.", 5000)

    app._submit_background_bundle_task(
        title=f"Export Contracts and Rights {normalized.upper()}",
        description=f"Exporting {normalized.upper()} Contracts and Rights data from the current profile...",
        task_fn=_worker,
        kind="read",
        unique_key=f"repertoire.export.{normalized}",
        worker_completion_progress=(100, "Contracts and Rights export complete."),
        on_success_after_cleanup=_success,
        on_error=lambda failure: app._show_background_task_error(
            "Repertoire Exchange",
            failure,
            user_message="Could not complete the Contracts and Rights export:",
        ),
    )


def import_repertoire_exchange(app, format_name: str):
    if app.repertoire_exchange_service is None:
        _message_box().warning(app, "Repertoire Exchange", "Open a profile first.")
        return
    normalized = str(format_name or "").strip().lower()
    if normalized == "json":
        path, _ = _file_dialog().getOpenFileName(
            app, "Import Repertoire JSON", "", "JSON Files (*.json)"
        )
    elif normalized == "xlsx":
        path, _ = _file_dialog().getOpenFileName(
            app, "Import Repertoire XLSX", "", "Excel Files (*.xlsx)"
        )
    elif normalized == "csv":
        path = _file_dialog().getExistingDirectory(app, "Import Repertoire CSV Bundle")
    elif normalized == "package":
        path, _ = _file_dialog().getOpenFileName(
            app, "Import Repertoire ZIP Package", "", "ZIP Files (*.zip)"
        )
    else:
        return
    if not path:
        return

    def _submit_import_task() -> None:
        def _worker(bundle, ctx):
            import_progress = app._scaled_progress_callback(
                ctx.report_progress, start=0, end=90
            )
            ctx.report_progress(
                value=0,
                maximum=100,
                message=f"Importing {normalized.upper()} Contracts and Rights data...",
            )

            def _mutation():
                if normalized == "json":
                    return bundle.repertoire_exchange_service.import_json(
                        path,
                        progress_callback=import_progress,
                        cancel_callback=ctx.raise_if_cancelled,
                    )
                if normalized == "xlsx":
                    return bundle.repertoire_exchange_service.import_xlsx(
                        path,
                        progress_callback=import_progress,
                        cancel_callback=ctx.raise_if_cancelled,
                    )
                if normalized == "csv":
                    return bundle.repertoire_exchange_service.import_csv_bundle(
                        path,
                        progress_callback=import_progress,
                        cancel_callback=ctx.raise_if_cancelled,
                    )
                return bundle.repertoire_exchange_service.import_package(
                    path,
                    progress_callback=import_progress,
                    cancel_callback=ctx.raise_if_cancelled,
                )

            return _root_attr("run_snapshot_history_action", run_snapshot_history_action)(
                history_manager=bundle.history_manager,
                action_label=f"Import Contracts and Rights {normalized.upper()}: {Path(path).name}",
                action_type=f"repertoire.import.{normalized}",
                entity_type="RepertoireImport",
                entity_id=path,
                payload={"path": path, "format": normalized},
                mutation=_mutation,
                progress_callback=ctx.report_progress,
                post_mutation_progress=(92, "Capturing import history snapshot..."),
                record_progress=(94, "Recording import history..."),
                logger=app.logger,
            )

        def _before_cleanup(_result, ui_progress) -> None:
            app._advance_task_ui_progress(
                ui_progress,
                value=97,
                message="Applying imported Contracts and Rights changes...",
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
            app.refresh_table_preserve_view()
            app.populate_all_comboboxes()
            app._refresh_catalog_workspace_docks()
            app._refresh_history_actions()
            app._advance_task_ui_progress(
                ui_progress,
                value=100,
                message="Contracts and Rights import complete.",
            )

        def _success(_result) -> None:
            if app.statusBar() is not None:
                app.statusBar().showMessage("Repertoire import complete.", 5000)

        app._submit_background_bundle_task(
            title=f"Import Contracts and Rights {normalized.upper()}",
            description=f"Importing {normalized.upper()} Contracts and Rights data into the current profile...",
            task_fn=_worker,
            kind="write",
            unique_key=f"repertoire.import.{normalized}",
            worker_completion_progress=(96, "Finalizing background import transaction..."),
            on_success_before_cleanup=_before_cleanup,
            on_success_after_cleanup=_success,
            on_error=lambda failure: app._show_background_task_error(
                "Repertoire Exchange",
                failure,
                user_message="Could not complete the Contracts and Rights import:",
            ),
        )

    def _inspection_worker(bundle, ctx):
        inspection_progress = app._scaled_progress_callback(
            ctx.report_progress, start=0, end=96
        )
        ctx.report_progress(
            value=0,
            maximum=100,
            message=f"Inspecting {normalized.upper()} Contracts and Rights source...",
        )
        if normalized == "json":
            return bundle.repertoire_exchange_service.inspect_json(
                path,
                progress_callback=inspection_progress,
                cancel_callback=ctx.raise_if_cancelled,
            )
        if normalized == "xlsx":
            return bundle.repertoire_exchange_service.inspect_xlsx(
                path,
                progress_callback=inspection_progress,
                cancel_callback=ctx.raise_if_cancelled,
            )
        if normalized == "csv":
            return bundle.repertoire_exchange_service.inspect_csv_bundle(
                path,
                progress_callback=inspection_progress,
                cancel_callback=ctx.raise_if_cancelled,
            )
        return bundle.repertoire_exchange_service.inspect_package(
            path,
            progress_callback=inspection_progress,
            cancel_callback=ctx.raise_if_cancelled,
        )

    def _inspection_success(inspection: RepertoireImportInspection) -> None:
        accepted = app._open_import_review_dialog(
            title=f"Review Contracts and Rights {normalized.upper()} Import",
            subtitle=(
                "Inspection completed. Review the parsed Contracts and Rights data before anything is written to the current profile."
            ),
            summary_lines=app._repertoire_import_review_summary(inspection),
            warnings=inspection.warnings,
            preview_rows=inspection.preview_rows,
            preview_headers=["Entity", "Action", "Label", "Notes"],
            preview_title="Import Preview",
            confirm_label="Apply Contracts and Rights Import",
        )
        if accepted:
            _submit_import_task()

    app._submit_background_bundle_task(
        title=f"Inspect Contracts and Rights {normalized.upper()}",
        description=f"Inspecting the selected {normalized.upper()} Contracts and Rights source...",
        task_fn=_inspection_worker,
        kind="read",
        unique_key=f"repertoire.inspect.{normalized}",
        worker_completion_progress=(100, "Contracts and Rights import review ready."),
        on_success_after_cleanup=_inspection_success,
        on_error=lambda failure: app._show_background_task_error(
            "Repertoire Exchange",
            failure,
            user_message="Could not inspect the Contracts and Rights import source:",
        ),
    )


def _repertoire_import_review_summary(inspection: RepertoireImportInspection) -> list[str]:
    counts = inspection.entity_counts
    lines = [
        f"Parties found: {int(counts.get('parties') or 0)}",
        f"Works found: {int(counts.get('works') or 0)}",
        f"Contracts found: {int(counts.get('contracts') or 0)}",
        f"Rights found: {int(counts.get('rights') or 0)}",
        f"Assets found: {int(counts.get('assets') or 0)}",
    ]
    if inspection.new_parties:
        lines.append(f"Would create Parties: {inspection.new_parties}")
    if inspection.existing_parties:
        lines.append(f"Would reuse existing Parties: {inspection.existing_parties}")
    return lines

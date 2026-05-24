"""Catalog XML import/export workflow orchestration for the application shell."""

from __future__ import annotations

import sys
from datetime import datetime

from PySide6.QtWidgets import QFileDialog, QMessageBox

from isrc_manager.tasks.history_helpers import run_file_history_action


def _root_attr(name: str, fallback):
    main_window_module = sys.modules.get("isrc_manager.main_window")
    return (
        getattr(main_window_module, name, fallback) if main_window_module is not None else fallback
    )


def _message_box():
    return _root_attr("QMessageBox", QMessageBox)


def _file_dialog():
    return _root_attr("QFileDialog", QFileDialog)


def export_full_to_xml(app):
    default_name = f"full_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xml"
    default_path = str(app.exports_dir / default_name)
    path, _ = _file_dialog().getSaveFileName(
        app, "Export All to XML", default_path, "XML Files (*.xml)"
    )
    if not path:
        return
    try:
        resolved_path = app._resolve_file_export_target(path, default_filename=default_name)
    except ValueError as exc:
        _message_box().warning(app, "Export", str(exc))
        return

    if resolved_path.exists():
        if (
            _message_box().question(
                app,
                "Overwrite?",
                f"File exists:\n{resolved_path}\n\nOverwrite?",
                _message_box().Yes | _message_box().No,
            )
            != _message_box().Yes
        ):
            return

    def _worker(bundle, ctx):
        export_progress = app._scaled_progress_callback(ctx.report_progress, start=0, end=94)
        return _root_attr("run_file_history_action", run_file_history_action)(
            history_manager=bundle.history_manager,
            action_label=lambda count: f"Export XML: {count} tracks",
            action_type="file.export_xml_all",
            target_path=resolved_path,
            mutation=lambda: bundle.xml_export_service.export_all(
                resolved_path,
                progress_callback=export_progress,
            ),
            entity_type="Export",
            entity_id=str(resolved_path),
            payload=lambda count: {"path": str(resolved_path), "count": count},
            progress_callback=ctx.report_progress,
            post_mutation_progress=(96, "Capturing XML export history..."),
            record_progress=(98, "Recording XML export history..."),
            logger=app.logger,
        )

    def _success(exported):
        app._refresh_history_actions()
        _message_box().information(app, "Export", f"All data exported:\n{resolved_path}")
        app._log_event(
            "export.xml.all",
            "Exported full library to XML",
            path=str(resolved_path),
            exported=exported,
        )
        app._audit(
            "EXPORT",
            "Tracks",
            ref_id=str(resolved_path),
            details=f"all rows incl. duration+customs count={exported}",
        )
        app._audit_commit()

    app._submit_background_bundle_task(
        title="Export XML",
        description="Exporting the full catalog to XML...",
        task_fn=_worker,
        kind="read",
        unique_key="export.xml.all",
        worker_completion_progress=(100, "XML export complete."),
        on_success_after_cleanup=_success,
        on_error=lambda failure: app._show_background_task_error(
            "Export Error",
            failure,
            user_message="Failed to export the library to XML:",
        ),
    )


def export_selected_to_xml(app):
    """Export visible rows if a filter is active; otherwise export explicitly selected rows."""
    track_ids = list(app._catalog_table_controller().selected_or_visible_track_ids())
    if not track_ids:
        _message_box().information(
            app, "Export Selected", "Select one or more rows (or apply a filter) first."
        )
        return

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    default_name = f"Selected_Tracks_{ts}.xml"
    out_path, _ = _file_dialog().getSaveFileName(
        app,
        "Export Selected to XML",
        str(app.exports_dir / default_name),
        "XML Files (*.xml)",
    )
    if not out_path:
        return
    try:
        resolved_out_path = app._resolve_file_export_target(
            out_path,
            default_filename=default_name,
        )
    except ValueError as exc:
        _message_box().warning(app, "Export Selected", str(exc))
        return

    def _worker(bundle, ctx):
        export_progress = app._scaled_progress_callback(ctx.report_progress, start=0, end=94)
        return _root_attr("run_file_history_action", run_file_history_action)(
            history_manager=bundle.history_manager,
            action_label=lambda count: f"Export Selected XML: {count} tracks",
            action_type="file.export_xml_selected",
            target_path=resolved_out_path,
            mutation=lambda: bundle.xml_export_service.export_selected(
                resolved_out_path,
                track_ids,
                current_db_path=str(app.current_db_path),
                progress_callback=export_progress,
            ),
            entity_type="Export",
            entity_id=str(resolved_out_path),
            payload=lambda count: {
                "path": str(resolved_out_path),
                "count": count,
                "track_ids": track_ids,
            },
            progress_callback=ctx.report_progress,
            post_mutation_progress=(96, "Capturing XML export history..."),
            record_progress=(98, "Recording XML export history..."),
            logger=app.logger,
        )

    def _success(exported):
        app._refresh_history_actions()
        app._log_event(
            "export.xml.selected",
            "Exported selected tracks to XML",
            path=str(resolved_out_path),
            exported=exported,
            track_ids=track_ids,
        )
        _message_box().information(app, "Export Complete", f"Saved:\n{resolved_out_path}")

    app._submit_background_bundle_task(
        title="Export Selected XML",
        description="Exporting the selected tracks to XML...",
        task_fn=_worker,
        kind="read",
        unique_key="export.xml.selected",
        worker_completion_progress=(100, "Selected XML export complete."),
        on_success_after_cleanup=_success,
        on_error=lambda failure: app._show_background_task_error(
            "Export Error",
            failure,
            user_message="Could not write the selected XML export:",
        ),
    )


def import_from_xml(app):
    app.import_exchange_file("xml")

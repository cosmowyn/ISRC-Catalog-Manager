"""Track import repair queue workflow orchestration for the application shell."""

from __future__ import annotations

import sys
from dataclasses import fields as dataclass_fields

from PySide6.QtWidgets import QDialog, QMessageBox

from isrc_manager.exchange import ExchangeImportOptions, ExchangeImportReport
from isrc_manager.exchange.repair_dialogs import (
    TrackImportRepairEntryDialog,
    TrackImportRepairQueueDialog,
)


def _root_attr(name: str, fallback):
    main_window_module = sys.modules.get("isrc_manager.main_window")
    return (
        getattr(main_window_module, name, fallback) if main_window_module is not None else fallback
    )


def _message_box():
    return _root_attr("QMessageBox", QMessageBox)


def _track_import_repair_entries(app, *, include_resolved: bool = False):
    if app.track_import_repair_queue_service is None:
        return []
    status = None if include_resolved else "pending"
    return app.track_import_repair_queue_service.list_entries(status=status)


def _track_import_repair_work_choices(app) -> list[tuple[int, str]]:
    if app.work_service is None:
        return []
    choices: list[tuple[int, str]] = []
    for record in app.work_service.list_works():
        title = str(record.title or "").strip() or f"Work #{int(record.id)}"
        if record.iswc:
            title = f"{title} ({record.iswc})"
        choices.append((int(record.id), title))
    return choices


def _refresh_track_import_repair_queue_dialog(app) -> None:
    dialog = getattr(app, "track_import_repair_queue_dialog", None)
    if isinstance(dialog, TrackImportRepairQueueDialog) and dialog.isVisible():
        dialog.refresh_entries()


def _delete_track_import_repair_entries(app, entry_ids: list[int]) -> None:
    if app.track_import_repair_queue_service is None:
        return
    normalized_ids = sorted({int(entry_id) for entry_id in entry_ids if int(entry_id) > 0})
    if not normalized_ids:
        return
    if (
        _message_box().question(
            app,
            "Track Import Repair Queue",
            "Delete the selected repair queue row(s)?",
            _message_box().Yes | _message_box().No,
            _message_box().No,
        )
        != _message_box().Yes
    ):
        return
    deleted = app.track_import_repair_queue_service.delete_entries(normalized_ids)
    try:
        app.conn.commit()
    except Exception:
        pass
    app._refresh_track_import_repair_queue_dialog()
    if app.statusBar() is not None:
        app.statusBar().showMessage(
            f"Deleted {deleted} import repair row(s).",
            5000,
        )


def _repair_track_import_queue_entry(app, entry_id: int) -> None:
    if app.track_import_repair_queue_service is None or app.exchange_service is None:
        _message_box().warning(app, "Track Import Repair Queue", "Open a profile first.")
        return
    entry = app.track_import_repair_queue_service.fetch_entry(int(entry_id))
    if entry is None:
        _message_box().information(
            app,
            "Track Import Repair Queue",
            "The selected repair row no longer exists.",
        )
        app._refresh_track_import_repair_queue_dialog()
        return
    dialog = _root_attr("TrackImportRepairEntryDialog", TrackImportRepairEntryDialog)(
        entry=entry,
        work_choices=app._track_import_repair_work_choices(),
        parent=app,
    )
    if dialog.exec() != QDialog.Accepted:
        return
    edited_row = dialog.edited_row()
    repair_override = dialog.repair_override()
    allowed_option_fields = {field.name for field in dataclass_fields(ExchangeImportOptions)}
    option_values = {
        key: value
        for key, value in dict(entry.options or {}).items()
        if key in allowed_option_fields
    }
    options = ExchangeImportOptions(**option_values) if option_values else ExchangeImportOptions()
    if options.mode == "dry_run":
        options.mode = "create"

    def _worker(bundle, ctx):
        repair_progress = app._scaled_progress_callback(ctx.report_progress, start=0, end=90)
        ctx.report_progress(
            value=0,
            maximum=100,
            message="Reapplying repaired import row...",
        )
        return bundle.exchange_service.import_prepared_rows(
            [edited_row],
            mapping=entry.mapping,
            options=options,
            format_name=entry.source_format,
            source_path=entry.source_path,
            progress_callback=repair_progress,
            cancel_callback=ctx.raise_if_cancelled,
            repair_entry_id=int(entry.id),
            repair_override=repair_override,
        )

    def _before_cleanup(report: ExchangeImportReport, ui_progress) -> None:
        app._advance_task_ui_progress(
            ui_progress,
            value=97,
            message="Applying repaired import changes...",
        )
        try:
            app.conn.commit()
        except Exception:
            pass
        if report.created_tracks or report.updated_tracks:
            focus_id = (report.created_tracks or report.updated_tracks)[0]
            app.refresh_table_preserve_view(focus_id=focus_id)
            app.populate_all_comboboxes()
        app._advance_task_ui_progress(
            ui_progress,
            value=99,
            message="Refreshing repair queue state...",
        )
        app._refresh_track_import_repair_queue_dialog()
        app._advance_task_ui_progress(
            ui_progress,
            value=100,
            message="Import repair row complete.",
        )

    def _success(report: ExchangeImportReport) -> None:
        if report.passed:
            if app.statusBar() is not None:
                app.statusBar().showMessage("Import repair row applied.", 5000)
            return
        details = (
            "\n".join(report.warnings[:12]) if report.warnings else "The row still needs repair."
        )
        _message_box().warning(
            app,
            "Track Import Repair Queue",
            details,
        )

    app._submit_background_bundle_task(
        title="Reapply Import Repair Row",
        description="Repairing and reapplying the queued import row...",
        task_fn=_worker,
        kind="write",
        unique_key=f"track.import.repair.{int(entry.id)}",
        worker_completion_progress=(96, "Finalizing repaired import transaction..."),
        on_success_before_cleanup=_before_cleanup,
        on_success_after_cleanup=_success,
        on_error=lambda failure: app._show_background_task_error(
            "Track Import Repair Queue",
            failure,
            user_message="Could not reapply the queued import row:",
        ),
    )


def open_track_import_repair_queue(app, focus_entry_id: int | None = None):
    if app.track_import_repair_queue_service is None:
        _message_box().warning(app, "Track Import Repair Queue", "Open a profile first.")
        return
    dialog = _root_attr("TrackImportRepairQueueDialog", TrackImportRepairQueueDialog)(
        entries_provider=lambda include_resolved: app._track_import_repair_entries(
            include_resolved=include_resolved
        ),
        repair_selected_handler=app._repair_track_import_queue_entry,
        delete_selected_handler=app._delete_track_import_repair_entries,
        parent=app,
    )
    app.track_import_repair_queue_dialog = dialog
    if focus_entry_id is not None:
        dialog.refresh_entries()
        for row in range(dialog.table.rowCount()):
            item = dialog.table.item(row, 0)
            if item is None:
                continue
            try:
                current_id = int(item.text())
            except Exception:
                continue
            if current_id == int(focus_entry_id):
                dialog.table.selectRow(row)
                break
    dialog.exec()

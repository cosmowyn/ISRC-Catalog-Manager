"""Master transfer workflow orchestration for the application shell."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtWidgets import QDialog, QFileDialog, QMessageBox

from isrc_manager.app_dialogs import MasterTransferExportDialog
from isrc_manager.exchange.master_transfer import MasterTransferService
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


def _create_master_transfer_service_for_ui(app) -> MasterTransferService | None:
    if app.exchange_service is None or app.repertoire_exchange_service is None:
        return None
    return MasterTransferService(
        exchange_service=app.exchange_service,
        repertoire_exchange_service=app.repertoire_exchange_service,
        license_service=app.license_service,
        contract_template_service=app.contract_template_service,
    )


def _open_master_transfer_export_preview_dialog(app, preview) -> list[str] | None:
    dialog = _root_attr("MasterTransferExportDialog", MasterTransferExportDialog)(
        list(getattr(preview, "sections", []) or []),
        parent=app,
    )
    if dialog.exec() != QDialog.Accepted:
        return None
    selected_section_ids = list(dialog.selected_section_ids())
    return selected_section_ids if selected_section_ids else None


def _master_transfer_export_issue_prompt_lines(issues: list[object]) -> list[str]:
    lines = [
        ("Some items cannot be read and would make the master catalog transfer export " "fail."),
        "",
        "Proceed anyway and omit these items from the ZIP?",
        "",
    ]
    for issue in issues[:10]:
        section = str(
            getattr(issue, "section_label", "") or getattr(issue, "section_id", "") or "Export item"
        ).strip()
        label = str(
            getattr(issue, "label", "") or getattr(issue, "item_id", "") or "Unnamed item"
        ).strip()
        reason = str(getattr(issue, "reason", "") or "").strip()
        lines.append(f"- {section}: {label} ({reason})")
    if len(issues) > 10:
        lines.append(f"- ...and {len(issues) - 10} more")
    lines.extend(
        [
            "",
            "A troubleshooting log will be written inside the ZIP as export_omissions.log.",
        ]
    )
    return lines


def export_master_transfer_package(app) -> None:
    if app.exchange_service is None or app.repertoire_exchange_service is None:
        _message_box().warning(app, "Master Catalog Transfer", "Open a profile first.")
        return
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    default_name = f"master_catalog_transfer_{timestamp}.zip"
    path, _ = _file_dialog().getSaveFileName(
        app,
        "Export Master Catalog Transfer",
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
        _message_box().warning(app, "Master Catalog Transfer", str(exc))
        return
    preview_service = app._create_master_transfer_service_for_ui()
    if preview_service is None:
        _message_box().warning(app, "Master Catalog Transfer", "Open a profile first.")
        return
    try:
        preview = preview_service.preview_export()
        selected_section_ids = app._open_master_transfer_export_preview_dialog(preview)
        if not selected_section_ids:
            return
        selected_section_ids = preview_service.validate_export_section_selection(
            selected_section_ids
        )
        export_issues = preview_service.preflight_export(include_sections=selected_section_ids)
    except ValueError as exc:
        _message_box().warning(app, "Master Catalog Transfer", str(exc))
        return
    except Exception as exc:
        _message_box().warning(
            app,
            "Master Catalog Transfer",
            f"Could not prepare the export preflight:\n{exc}",
        )
        return

    continue_on_item_errors = False
    if export_issues:
        answer = _message_box().question(
            app,
            "Master Catalog Transfer",
            "\n".join(app._master_transfer_export_issue_prompt_lines(export_issues)),
            _message_box().Yes | _message_box().No,
            _message_box().No,
        )
        if answer != _message_box().Yes:
            return
        continue_on_item_errors = True

    def _worker(bundle, ctx):
        export_progress = app._scaled_progress_callback(ctx.report_progress, start=0, end=94)

        def _mutation():
            return bundle.master_transfer_service.export_package(
                resolved_path,
                include_sections=selected_section_ids,
                progress_callback=export_progress,
                cancel_callback=ctx.raise_if_cancelled,
                continue_on_item_errors=continue_on_item_errors,
            )

        return _root_attr("run_file_history_action", run_file_history_action)(
            history_manager=bundle.history_manager,
            action_label="Export Master Catalog Transfer",
            action_type="file.master_transfer_export",
            target_path=resolved_path,
            mutation=_mutation,
            entity_type="MasterTransferExport",
            entity_id=str(resolved_path),
            payload=lambda result: {
                "path": str(resolved_path),
                "format": "master_transfer",
                "section_ids": [section.section_id for section in result.sections],
                "warnings": list(result.warnings),
                "omitted_items": [
                    issue.to_dict() for issue in getattr(result, "omitted_items", []) or []
                ],
            },
            progress_callback=ctx.report_progress,
            post_mutation_progress=(96, "Capturing master transfer export history..."),
            record_progress=(98, "Recording master transfer export history..."),
            logger=app.logger,
        )

    def _success(result) -> None:
        app._refresh_history_actions()
        app._log_event(
            "master_transfer.export",
            "Exported master catalog transfer package",
            path=str(resolved_path),
            app_version=result.app_version,
            exported_at=result.exported_at,
            warnings=result.warnings,
            sections={
                section.section_id: dict(section.entity_counts) for section in result.sections
            },
        )
        app._audit(
            "EXPORT",
            "MasterTransfer",
            ref_id=str(resolved_path),
            details=(
                "sections="
                + ",".join(section.section_id for section in result.sections)
                + f"; warnings={len(result.warnings)}"
            ),
        )
        app._audit_commit()
        message_lines = [
            f"Master catalog transfer package written to:\n{resolved_path}",
            "",
            "Included sections:",
        ]
        message_lines.extend(
            f"- {section.label}: {', '.join(f'{key}={value}' for key, value in section.entity_counts.items())}"
            for section in result.sections
        )
        omitted_export_sections = list(
            (
                (result.manifest.get("export_selection") or {}).get("omitted_sections")
                if isinstance(result.manifest, dict)
                else []
            )
            or []
        )
        if omitted_export_sections:
            message_lines.extend(
                [
                    "",
                    "Omitted sections:",
                    *[
                        "- "
                        + (
                            str(section.get("label") or section.get("section_id") or "").strip()
                            or "Unnamed Section"
                        )
                        for section in omitted_export_sections
                        if str(section.get("label") or section.get("section_id") or "").strip()
                    ],
                ]
            )
        if result.warnings:
            message_lines.extend(
                [
                    "",
                    "Warnings:",
                    *[f"- {warning}" for warning in result.warnings[:12]],
                ]
            )
        _message_box().information(
            app,
            "Master Catalog Transfer",
            "\n".join(message_lines),
        )

    app._submit_background_bundle_task(
        title="Export Master Catalog Transfer",
        description="Building a versioned logical transfer package for the current profile...",
        task_fn=_worker,
        kind="read",
        unique_key="master_transfer.export",
        worker_completion_progress=(100, "Master transfer export complete."),
        on_success_after_cleanup=_success,
        on_error=lambda failure: app._show_background_task_error(
            "Master Catalog Transfer",
            failure,
            user_message="Could not export the master transfer package:",
        ),
    )


def import_master_transfer_package(app) -> None:
    if app.exchange_service is None or app.repertoire_exchange_service is None:
        _message_box().warning(app, "Master Catalog Transfer", "Open a profile first.")
        return
    path, _ = _file_dialog().getOpenFileName(
        app,
        "Import Master Catalog Transfer",
        "",
        "ZIP Files (*.zip)",
    )
    if not path:
        return

    def _submit_import_task() -> None:
        def _worker(bundle, ctx):
            import_progress = app._scaled_progress_callback(
                ctx.report_progress,
                start=0,
                end=90,
            )
            ctx.report_progress(
                value=0,
                maximum=100,
                message="Importing the master catalog transfer package...",
            )

            def _mutation():
                return bundle.master_transfer_service.import_package(
                    path,
                    progress_callback=import_progress,
                    cancel_callback=ctx.raise_if_cancelled,
                )

            return _root_attr("run_snapshot_history_action", run_snapshot_history_action)(
                history_manager=bundle.history_manager,
                action_label=f"Import Master Transfer: {Path(path).name}",
                action_type="master_transfer.import",
                entity_type="MasterTransferImport",
                entity_id=path,
                payload={"path": path, "format": "master_transfer"},
                mutation=_mutation,
                progress_callback=ctx.report_progress,
                post_mutation_progress=(92, "Capturing master transfer history snapshot..."),
                record_progress=(94, "Recording master transfer history..."),
                logger=app.logger,
            )

        def _before_cleanup(result, ui_progress) -> None:
            catalog_report = getattr(result, "catalog_report", None)
            focus_track_id = (
                []
                if catalog_report is None
                else (catalog_report.created_tracks or catalog_report.updated_tracks)
            )
            focus_track_id = (focus_track_id or [None])[0]
            app._advance_task_ui_progress(
                ui_progress,
                value=97,
                message="Applying imported master transfer changes...",
            )
            try:
                app.conn.commit()
            except Exception:
                pass
            app._advance_task_ui_progress(
                ui_progress,
                value=99,
                message="Refreshing catalog views, workspace panels, and history...",
            )
            app.refresh_table_preserve_view(focus_id=focus_track_id)
            app.populate_all_comboboxes()
            app._refresh_catalog_workspace_docks()
            app._refresh_history_actions()
            app._advance_task_ui_progress(
                ui_progress,
                value=100,
                message="Master transfer import complete.",
            )

        def _success(result) -> None:
            catalog_report = getattr(result, "catalog_report", None)
            repertoire_party_phase = getattr(result, "repertoire_party_phase", None)
            repertoire_report = getattr(result, "repertoire_report", None)
            included_section_ids = app._master_transfer_manifest_included_section_ids(
                getattr(result, "manifest", {})
            )
            app._log_event(
                "master_transfer.import",
                "Imported master catalog transfer package",
                path=path,
                exported_at=result.exported_at,
                source_app_version=result.app_version,
                included_sections=included_section_ids,
                seeded_parties=(
                    0 if repertoire_party_phase is None else repertoire_party_phase.imported_parties
                ),
                reused_parties=(
                    0
                    if repertoire_party_phase is None
                    else repertoire_party_phase.reused_existing_parties
                ),
                created_tracks=(
                    0 if catalog_report is None else len(catalog_report.created_tracks)
                ),
                updated_tracks=(
                    0 if catalog_report is None else len(catalog_report.updated_tracks)
                ),
                imported_licenses=result.imported_licenses,
                imported_works=(
                    0 if repertoire_report is None else repertoire_report.imported_works
                ),
                imported_contracts=(
                    0 if repertoire_report is None else repertoire_report.imported_contracts
                ),
                imported_rights=(
                    0 if repertoire_report is None else repertoire_report.imported_rights
                ),
                imported_assets=(
                    0 if repertoire_report is None else repertoire_report.imported_assets
                ),
                imported_templates=result.imported_contract_templates,
                imported_template_revisions=result.imported_template_revisions,
                warnings=result.warnings,
            )
            app._audit(
                "IMPORT",
                "MasterTransfer",
                ref_id=path,
                details=(
                    f"sections={','.join(included_section_ids)}; "
                    f"tracks_created={0 if catalog_report is None else len(catalog_report.created_tracks)}; "
                    f"parties_seeded={0 if repertoire_party_phase is None else repertoire_party_phase.imported_parties}; "
                    f"licenses={result.imported_licenses}; "
                    f"works={0 if repertoire_report is None else repertoire_report.imported_works}; "
                    f"contracts={0 if repertoire_report is None else repertoire_report.imported_contracts}; "
                    f"rights={0 if repertoire_report is None else repertoire_report.imported_rights}; "
                    f"assets={0 if repertoire_report is None else repertoire_report.imported_assets}; "
                    f"templates={result.imported_contract_templates}; "
                    f"template_revisions={result.imported_template_revisions}"
                ),
            )
            app._audit_commit()
            app._show_master_transfer_import_report(path, result)

        app._submit_background_bundle_task(
            title="Import Master Catalog Transfer",
            description="Rehydrating a versioned master transfer package through the app's current import logic...",
            task_fn=_worker,
            kind="write",
            unique_key="master_transfer.import",
            worker_completion_progress=(96, "Finalizing master transfer import transaction..."),
            on_success_before_cleanup=_before_cleanup,
            on_success_after_cleanup=_success,
            on_error=lambda failure: app._show_background_task_error(
                "Master Catalog Transfer",
                failure,
                user_message="Could not import the master transfer package:",
            ),
        )

    def _inspection_worker(bundle, ctx):
        inspection_progress = app._scaled_progress_callback(
            ctx.report_progress,
            start=0,
            end=96,
        )
        ctx.report_progress(
            value=0,
            maximum=100,
            message="Inspecting the master catalog transfer package...",
        )
        return bundle.master_transfer_service.inspect_package(
            path,
            progress_callback=inspection_progress,
            cancel_callback=ctx.raise_if_cancelled,
        )

    def _inspection_success(inspection) -> None:
        accepted = app._open_import_review_dialog(
            title="Review Master Catalog Transfer Import",
            subtitle=(
                "Inspection completed. Review the staged logical transfer before anything is written to the current profile."
            ),
            summary_lines=app._master_transfer_review_summary(inspection),
            warnings=inspection.warnings,
            preview_rows=inspection.preview_rows,
            preview_headers=["Section", "Entity", "Action", "Label", "Notes"],
            preview_title="Transfer Preview",
            confirm_label="Apply Master Transfer",
        )
        if accepted:
            _submit_import_task()

    app._submit_background_bundle_task(
        title="Inspect Master Catalog Transfer",
        description="Inspecting the selected master transfer package...",
        task_fn=_inspection_worker,
        kind="read",
        unique_key="master_transfer.inspect",
        worker_completion_progress=(100, "Master transfer inspection complete."),
        on_success_after_cleanup=_inspection_success,
        on_error=lambda failure: app._show_background_task_error(
            "Master Catalog Transfer",
            failure,
            user_message="Could not inspect the master transfer package:",
        ),
    )


def _master_transfer_manifest_included_section_ids(manifest: dict[str, object]) -> list[str]:
    selection = manifest.get("export_selection") if isinstance(manifest, dict) else None
    included = []
    seen: set[str] = set()
    if isinstance(selection, dict):
        for section_id in selection.get("included_section_ids") or []:
            clean_id = str(section_id or "").strip()
            if not clean_id or clean_id in seen:
                continue
            seen.add(clean_id)
            included.append(clean_id)
    if included:
        return included
    if not isinstance(manifest, dict):
        return []
    return [
        str(section.get("section_id") or "").strip()
        for section in list(manifest.get("sections") or [])
        if str(section.get("section_id") or "").strip()
    ]


def _master_transfer_manifest_omitted_section_labels(manifest: dict[str, object]) -> list[str]:
    if not isinstance(manifest, dict):
        return []
    selection = manifest.get("export_selection")
    if not isinstance(selection, dict):
        return []
    labels: list[str] = []
    for raw_section in selection.get("omitted_sections") or []:
        section = dict(raw_section)
        label = str(section.get("label") or section.get("section_id") or "").strip()
        if label:
            labels.append(label)
    return labels


def _master_transfer_review_summary(inspection) -> list[str]:
    lines = list(getattr(inspection, "summary_lines", []) or [])
    catalog_dry_run = getattr(inspection, "catalog_dry_run", None)
    if catalog_dry_run is not None:
        lines.append(
            "Catalog dry run: "
            f"would create {int(getattr(catalog_dry_run, 'would_create_tracks', 0) or 0)}, "
            f"would update {int(getattr(catalog_dry_run, 'would_update_tracks', 0) or 0)}, "
            f"blocked {int(getattr(catalog_dry_run, 'failed', 0) or 0)}"
        )
    repertoire_inspection = getattr(inspection, "repertoire_inspection", None)
    if repertoire_inspection is not None:
        lines.append(
            "Repertoire preview: "
            f"would reuse {int(getattr(repertoire_inspection, 'existing_parties', 0) or 0)} "
            "existing Parties and "
            f"would create {int(getattr(repertoire_inspection, 'new_parties', 0) or 0)}."
        )
    return lines


def _show_master_transfer_import_report(app, path: str, result) -> None:
    included_section_ids = set(
        app._master_transfer_manifest_included_section_ids(getattr(result, "manifest", {}))
    )
    omitted_labels = app._master_transfer_manifest_omitted_section_labels(
        getattr(result, "manifest", {})
    )
    catalog_report = getattr(result, "catalog_report", None)
    repertoire_party_phase = getattr(result, "repertoire_party_phase", None)
    repertoire_report = getattr(result, "repertoire_report", None)
    lines = [
        f"Source package: {Path(path).name}",
        f"Source app version: {result.app_version or 'Unknown'}",
        f"Exported at: {result.exported_at or 'Unknown'}",
        "",
        "Applied sections:",
    ]
    if "catalog" in included_section_ids:
        lines.append(
            "Catalog: "
            f"created {0 if catalog_report is None else len(catalog_report.created_tracks)}, "
            f"updated {0 if catalog_report is None else len(catalog_report.updated_tracks)}"
        )
    if "repertoire" in included_section_ids:
        lines.append(
            "Contracts and Rights Party phase: "
            f"created {0 if repertoire_party_phase is None else int(repertoire_party_phase.imported_parties or 0)}, "
            f"reused {0 if repertoire_party_phase is None else int(repertoire_party_phase.reused_existing_parties or 0)}"
        )
    if "licenses" in included_section_ids:
        lines.append(f"License Archive: imported {int(result.imported_licenses or 0)}")
    if "repertoire" in included_section_ids:
        lines.append(
            "Contracts and Rights: "
            f"works {0 if repertoire_report is None else int(repertoire_report.imported_works or 0)}, "
            f"contracts {0 if repertoire_report is None else int(repertoire_report.imported_contracts or 0)}, "
            f"rights {0 if repertoire_report is None else int(repertoire_report.imported_rights or 0)}, "
            f"assets {0 if repertoire_report is None else int(repertoire_report.imported_assets or 0)}"
        )
    if "contract_templates" in included_section_ids:
        lines.append(
            "Contract Templates: "
            f"templates {int(result.imported_contract_templates or 0)}, "
            f"revisions {int(result.imported_template_revisions or 0)}"
        )
    if omitted_labels:
        lines.extend(
            [
                "",
                "Intentionally omitted sections:",
                *[f"- {label}" for label in omitted_labels],
            ]
        )
    if result.warnings:
        lines.extend(
            [
                "",
                "Warnings:",
                *[f"- {warning}" for warning in list(result.warnings)[:12]],
            ]
        )
    _message_box().information(
        app,
        "Master Catalog Transfer",
        "\n".join(lines),
    )

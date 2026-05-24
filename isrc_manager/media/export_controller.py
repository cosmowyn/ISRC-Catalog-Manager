"""Media and catalog audio export orchestration for the application shell."""

from __future__ import annotations

import mimetypes
import sys
from dataclasses import fields as dataclass_fields
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QFileDialog, QMessageBox

from isrc_manager.catalog_table import ColumnKeyRole
from isrc_manager.file_storage import (
    STORAGE_MODE_DATABASE,
    normalize_storage_mode,
    resolve_directory_export_target,
    resolve_file_export_target,
    sanitize_export_basename,
)
from isrc_manager.tags import TAGGED_AUDIO_EXPORT_STAGE_COUNT, write_catalog_export_tags
from isrc_manager.tags.dialogs import TagPreviewDialog
from isrc_manager.tags.models import AudioTagData, TaggedAudioExportItem, TaggedAudioExportPlanItem
from isrc_manager.tasks.history_helpers import run_file_history_action

if TYPE_CHECKING:
    from isrc_manager.releases import ReleaseService
    from isrc_manager.services.tracks import TrackService


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


def _run_file_history_action(*args, **kwargs):
    return _root_attr("run_file_history_action", run_file_history_action)(*args, **kwargs)


def _iter_audio_tag_preview_fields(tag_data: AudioTagData) -> list[tuple[str, object]]:
    return [
        (field.name, getattr(tag_data, field.name))
        for field in dataclass_fields(AudioTagData)
        if field.name not in {"raw_fields", "warnings"}
    ]


def _build_tagged_audio_export_preview_rows(
    self,
    *,
    track_title: str,
    source_label: str,
    tag_data: AudioTagData,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for field_name, value in self._iter_audio_tag_preview_fields(tag_data):
        if value in (None, "", [], {}, ()):
            continue
        rows.append(
            {
                "track": track_title,
                "field": field_name.replace("_", " ").title(),
                "database": self._display_tag_value(value),
                "file": "",
                "chosen": self._display_tag_value(value),
                "source": source_label,
            }
        )
    return rows


def _tagged_audio_export_name(track_id: int, track_title: str | None) -> str:
    return sanitize_export_basename(track_title or f"track_{track_id}", default_stem="track")


def _prepare_tagged_audio_export_preview(
    self,
    track_ids: list[int],
    *,
    track_service: TrackService | None = None,
    release_service: ReleaseService | None = None,
    progress_callback=None,
) -> dict[str, object]:
    active_track_service = track_service or self.track_service
    active_release_service = release_service or self.release_service
    if active_track_service is None:
        raise ValueError("Track service is not available.")

    normalized_ids = self._normalize_track_ids(track_ids)
    prepared: list[TaggedAudioExportPlanItem] = []
    preview_rows: list[dict[str, object]] = []
    warnings: list[str] = []
    total = max(1, len(normalized_ids))
    for index, track_id in enumerate(normalized_ids, start=1):
        if callable(progress_callback):
            progress_callback(
                index - 1,
                total,
                f"Preparing catalog audio copy preview for track {index} of {total}...",
            )
        snapshot = active_track_service.fetch_track_snapshot(
            track_id,
            include_media_blobs=False,
        )
        if snapshot is None:
            warnings.append(f"Track {track_id} could not be loaded.")
            continue

        source_suffix = self._audio_export_source_suffix(snapshot)
        resolved = active_track_service.resolve_media_path(snapshot.audio_file_path)
        if resolved is not None and resolved.exists():
            source_label = str(resolved)
        elif (
            normalize_storage_mode(snapshot.audio_file_storage_mode, default=None)
            == STORAGE_MODE_DATABASE
        ):
            source_label = self._audio_export_source_label(snapshot)
        else:
            warnings.append(f"{snapshot.track_title}: no exportable audio file is attached.")
            continue

        tag_data = self._catalog_tag_data_for_track(
            track_id,
            snapshot=snapshot,
            track_service=active_track_service,
            release_service=active_release_service,
            include_artwork_bytes=False,
        )
        prepared.append(
            TaggedAudioExportPlanItem(
                track_id=int(track_id),
                track_title=str(snapshot.track_title or ""),
                suggested_name=self._tagged_audio_export_name(track_id, snapshot.track_title),
                source_suffix=source_suffix,
                source_label=source_label,
                album_title=str(snapshot.album_title or "").strip() or None,
            )
        )
        preview_rows.extend(
            self._build_tagged_audio_export_preview_rows(
                track_title=str(snapshot.track_title or ""),
                source_label=source_label,
                tag_data=tag_data,
            )
        )

    if callable(progress_callback):
        progress_callback(total, total, "Catalog audio copy export preview ready.")

    return {
        "prepared": prepared,
        "rows": preview_rows,
        "warnings": warnings,
    }


def _build_tagged_audio_export_items(
    self,
    plan_items: list[TaggedAudioExportPlanItem],
    *,
    track_service: TrackService | None = None,
    release_service: ReleaseService | None = None,
    progress_callback=None,
    is_cancelled=None,
) -> tuple[list[TaggedAudioExportItem], list[str]]:
    active_track_service = track_service or self.track_service
    active_release_service = release_service or self.release_service
    if active_track_service is None:
        raise ValueError("Track service is not available.")

    exports: list[TaggedAudioExportItem] = []
    warnings: list[str] = []
    total = max(1, len(plan_items))
    for index, plan_item in enumerate(plan_items, start=1):
        if callable(is_cancelled) and is_cancelled():
            raise InterruptedError("Catalog audio copy export cancelled.")
        if callable(progress_callback):
            progress_callback(
                index - 1,
                total,
                f"Preparing exported audio copy {index} of {total}: {plan_item.suggested_name}",
            )
        snapshot = active_track_service.fetch_track_snapshot(
            plan_item.track_id,
            include_media_blobs=False,
        )
        if snapshot is None:
            warnings.append(f"Track {plan_item.track_id} could not be loaded.")
            continue
        tag_data = self._catalog_tag_data_for_track(
            plan_item.track_id,
            snapshot=snapshot,
            track_service=active_track_service,
            release_service=active_release_service,
            include_artwork_bytes=True,
        )
        resolved = active_track_service.resolve_media_path(snapshot.audio_file_path)
        if resolved is not None and resolved.exists():
            exports.append(
                TaggedAudioExportItem(
                    suggested_name=plan_item.suggested_name,
                    tag_data=tag_data,
                    source_path=resolved,
                    source_suffix=plan_item.source_suffix,
                    album_title=plan_item.album_title,
                )
            )
            continue
        try:
            audio_bytes, _mime_type = active_track_service.fetch_media_bytes(
                plan_item.track_id,
                "audio_file",
            )
        except Exception:
            warnings.append(f"{plan_item.track_title}: no exportable audio file is attached.")
            continue
        exports.append(
            TaggedAudioExportItem(
                suggested_name=plan_item.suggested_name,
                tag_data=tag_data,
                source_bytes=audio_bytes,
                source_suffix=plan_item.source_suffix,
                album_title=plan_item.album_title,
            )
        )

    if callable(progress_callback):
        progress_callback(total, total, "Catalog audio copy export sources are ready.")

    return exports, warnings


def export_catalog_audio_copies(self, track_ids: list[int] | None = None):
    title = "Export Catalog Audio Copies"
    if self.tagged_audio_export_service is None or self.track_service is None:
        _message_box().warning(self, title, "Open a profile first.")
        return
    selected_ids = self._normalize_track_ids(
        track_ids or self._catalog_table_controller().selected_or_visible_track_ids()
    )
    if not selected_ids:
        _message_box().information(
            self,
            title,
            "Select one or more tracks or apply a filter first.",
        )
        return

    def _preview_worker(bundle, ctx):
        return self._prepare_tagged_audio_export_preview(
            selected_ids,
            track_service=bundle.track_service,
            release_service=bundle.release_service,
            progress_callback=lambda value, maximum, message: ctx.report_progress(
                value=value,
                maximum=maximum,
                message=message,
            ),
        )

    def _preview_success(result: dict[str, object]):
        prepared = list(result.get("prepared") or [])
        preview_rows = list(result.get("rows") or [])
        warnings = list(result.get("warnings") or [])
        if not prepared:
            _message_box().information(
                self,
                title,
                "No exportable audio files were available for the selected tracks."
                + ("\n\nWarnings:\n- " + "\n- ".join(warnings[:12]) if warnings else ""),
            )
            return

        dlg = _root_attr("TagPreviewDialog", TagPreviewDialog)(
            title=title,
            intro=(
                "Preview the catalog metadata that will be embedded into exported catalog "
                "audio copies. The original stored audio stays untouched."
            ),
            rows=preview_rows,
            initial_policy="prefer_database",
            allow_policy_change=False,
            parent=self,
        )
        if dlg.exec() != QDialog.Accepted:
            return

        output_dir = _file_dialog().getExistingDirectory(
            self,
            "Choose Export Folder for Catalog Audio Copies",
            str(self.exports_dir / "catalog_audio_copies"),
        )
        if not output_dir:
            return

        def _worker(bundle, ctx):
            export_progress = self._scaled_progress_callback(ctx.report_progress, start=0, end=96)
            build_stage_total = max(1, len(prepared))
            export_stage_total = max(1, len(prepared) * TAGGED_AUDIO_EXPORT_STAGE_COUNT)
            overall_total = build_stage_total + export_stage_total
            exports, prepare_warnings = self._build_tagged_audio_export_items(
                prepared,
                track_service=bundle.track_service,
                release_service=bundle.release_service,
                progress_callback=lambda value, maximum, message: export_progress(
                    value=value,
                    maximum=overall_total,
                    message=message,
                ),
                is_cancelled=ctx.is_cancelled,
            )
            result = bundle.tagged_audio_export_service.export_copies(
                output_dir=output_dir,
                exports=exports,
                progress_callback=lambda value, maximum, message: export_progress(
                    value=build_stage_total + int(value or 0),
                    maximum=overall_total,
                    message=message,
                ),
                is_cancelled=ctx.is_cancelled,
            )
            return {
                "result": result,
                "warnings": prepare_warnings,
            }

        def _before_cleanup(payload: dict[str, object], ui_progress) -> None:
            export_result = payload.get("result")
            if export_result is None:
                raise ValueError("Catalog audio copy export did not return a result.")
            result = export_result
            all_warnings = warnings + list(payload.get("warnings") or []) + list(result.warnings)

            self._advance_task_ui_progress(
                ui_progress,
                value=97,
                message="Recording catalog audio copy export results...",
            )
            self._log_event(
                "audio.export_catalog_copies",
                "Exported catalog audio copies",
                output_dir=output_dir,
                exported=result.exported,
                skipped=result.skipped,
                warnings=all_warnings,
            )
            self._audit(
                "EXPORT",
                "CatalogAudioCopy",
                ref_id=output_dir,
                details=f"exported={result.exported}; skipped={result.skipped}",
            )
            self._audit_commit()

            self._advance_task_ui_progress(
                ui_progress,
                value=100,
                message="Catalog audio copy export complete.",
            )

        def _success(payload: dict[str, object]):
            export_result = payload.get("result")
            if export_result is None:
                raise ValueError("Catalog audio copy export did not return a result.")
            result = export_result
            all_warnings = warnings + list(payload.get("warnings") or []) + list(result.warnings)
            _message_box().information(
                self,
                title,
                f"Exported {result.exported} catalog audio cop{'y' if result.exported == 1 else 'ies'} to:\n{output_dir}"
                "\n\nThese copies preserve the current source format and automatically "
                "embed trustworthy catalog metadata when it is available."
                f"\n\nSkipped: {result.skipped}"
                + ("\n\nWarnings:\n- " + "\n- ".join(all_warnings[:12]) if all_warnings else ""),
            )

        self._submit_background_bundle_task(
            title=title,
            description=(
                "Copying selected catalog audio in its current source format and embedding "
                "catalog metadata when it is available..."
            ),
            task_fn=_worker,
            kind="read",
            unique_key="audio.export_catalog_copies",
            cancellable=True,
            worker_completion_progress=(96, "Finalizing catalog audio copy export results..."),
            on_success_before_cleanup=_before_cleanup,
            on_success_after_cleanup=_success,
            on_cancelled=lambda: self.statusBar().showMessage(
                "Catalog audio copy export cancelled.", 5000
            ),
            on_error=lambda failure: self._show_background_task_error(
                title,
                failure,
                user_message="Could not export catalog audio copies:",
            ),
        )

    self._submit_background_bundle_task(
        title=title,
        description="Preparing the catalog audio copy export preview...",
        task_fn=_preview_worker,
        kind="read",
        unique_key="audio.export_catalog_copies.preview",
        cancellable=False,
        on_success_after_cleanup=_preview_success,
        on_error=lambda failure: self._show_background_task_error(
            title,
            failure,
            user_message="Could not prepare the catalog audio copy export preview:",
        ),
    )


def write_tags_to_exported_audio(self, track_ids: list[int] | None = None):
    self.export_catalog_audio_copies(track_ids)


def _export_bytes_with_picker(
    self,
    data,
    *,
    mime: str,
    suggested_basename: str,
    catalog_track_id: int | None = None,
    parent_widget=None,
    action_label: str,
    action_type: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
    payload: dict | None = None,
    dialog_title: str = "Export file",
) -> None:
    if isinstance(data, memoryview):
        data = data.tobytes()
    elif isinstance(data, bytearray):
        data = bytes(data)
    default_filename = self._default_export_filename(suggested_basename, mime or "")
    dest_path, _ = _file_dialog().getSaveFileName(
        parent_widget or self, dialog_title, default_filename, "All files (*)"
    )
    if not dest_path:
        return
    try:
        resolved_dest_path = self._resolve_file_export_target(
            dest_path,
            default_filename=default_filename,
        )
    except ValueError as exc:
        _message_box().warning(parent_widget or self, "Export", str(exc))
        return

    metadata_warning: str | None = None

    try:

        def _mutation():
            nonlocal metadata_warning
            resolved_dest_path.parent.mkdir(parents=True, exist_ok=True)
            resolved_dest_path.write_bytes(data)
            if catalog_track_id is not None:
                metadata_warning = self._attempt_catalog_audio_export_metadata(
                    resolved_dest_path,
                    track_id=int(catalog_track_id),
                )

        self.__run_file_history_action(
            action_label=action_label.format(filename=resolved_dest_path.name),
            action_type=action_type,
            target_path=resolved_dest_path,
            mutation=_mutation,
            entity_type=entity_type,
            entity_id=entity_id,
            payload={"path": str(resolved_dest_path), **(payload or {})},
        )
        message = f"Saved:\n{resolved_dest_path}"
        if metadata_warning:
            message += f"\n\nMetadata embedding skipped: {metadata_warning}."
        _message_box().information(parent_widget or self, "Export", message)
    except Exception as e:
        _message_box().critical(parent_widget or self, "Export failed", str(e))


def _coerce_export_bytes(data) -> bytes:
    if isinstance(data, memoryview):
        return data.tobytes()
    if isinstance(data, bytearray):
        return bytes(data)
    return bytes(data)


def _submit_background_audio_file_export(
    self,
    *,
    task_title: str,
    task_description: str,
    dialog_title: str,
    resolved_dest_path: Path,
    action_label: str,
    action_type: str,
    entity_type: str | None,
    entity_id: str | None,
    payload: dict | None,
    load_source,
    metadata_track_id: int | None = None,
    parent_widget=None,
) -> None:
    def _worker(bundle, ctx):
        total_steps = 4
        ctx.report_progress(
            value=0,
            maximum=total_steps,
            message=f"Loading source audio: {resolved_dest_path.name}",
        )
        data, _mime_type = load_source(bundle)
        export_bytes = self._coerce_export_bytes(data)

        def _mutation():
            ctx.report_progress(
                value=1,
                maximum=total_steps,
                message=f"Writing exported audio: {resolved_dest_path.name}",
            )
            resolved_dest_path.parent.mkdir(parents=True, exist_ok=True)
            resolved_dest_path.write_bytes(export_bytes)
            if metadata_track_id is not None:
                ctx.report_progress(
                    value=2,
                    maximum=total_steps,
                    message=f"Writing catalog metadata: {resolved_dest_path.name}",
                )
                _metadata_embedded, metadata_warning = write_catalog_export_tags(
                    resolved_dest_path,
                    track_id=int(metadata_track_id),
                    track_service=bundle.track_service,
                    release_service=bundle.release_service,
                    tag_service=bundle.audio_tag_service,
                    include_artwork_bytes=True,
                )
                return metadata_warning
            ctx.report_progress(
                value=2,
                maximum=total_steps,
                message=f"Finalizing exported audio: {resolved_dest_path.name}",
            )
            return None

        metadata_warning = _run_file_history_action(
            history_manager=bundle.history_manager,
            action_label=action_label.format(filename=resolved_dest_path.name),
            action_type=action_type,
            target_path=resolved_dest_path,
            mutation=_mutation,
            entity_type=entity_type,
            entity_id=entity_id,
            payload={"path": str(resolved_dest_path), **(payload or {})},
            progress_callback=ctx.report_progress,
            record_progress=(3, f"Recording export history: {resolved_dest_path.name}"),
            logger=self.logger,
        )
        if bundle.history_manager is None:
            ctx.report_progress(
                value=3,
                maximum=total_steps,
                message=f"Finalizing exported audio: {resolved_dest_path.name}",
            )
        return {
            "path": str(resolved_dest_path),
            "metadata_warning": metadata_warning,
        }

    def _success(result: dict[str, object]):
        self._refresh_history_actions()
        message = f"Saved:\n{result.get('path') or resolved_dest_path}"
        metadata_warning = str(result.get("metadata_warning") or "").strip()
        if metadata_warning:
            message += f"\n\nMetadata embedding skipped: {metadata_warning}."
        _message_box().information(parent_widget or self, dialog_title, message)

    self._submit_background_bundle_task(
        title=task_title,
        description=task_description,
        task_fn=_worker,
        kind="read",
        unique_key=action_type,
        cancellable=True,
        worker_completion_progress=(100, f"{dialog_title} complete."),
        on_success_after_cleanup=_success,
        on_cancelled=lambda: self.statusBar().showMessage(f"{dialog_title} cancelled.", 5000),
        on_error=lambda failure: self._show_background_task_error(
            dialog_title,
            failure,
            user_message="Could not export the selected audio:",
        ),
    )


def _submit_background_audio_column_export(
    self,
    *,
    spec: dict[str, object],
    track_ids: list[int],
    output_root: Path,
) -> None:
    title = f"Export {spec['column_label']}"
    is_standard_audio = (
        str(spec.get("kind") or "") == "standard"
        and str(spec.get("media_key") or "") == "audio_file"
    )
    column_label = str(spec.get("column_label") or "Audio")

    def _worker(bundle, ctx):
        exported = 0
        skipped: list[str] = []
        metadata_skipped: list[str] = []
        track_total = len(track_ids)
        per_item_steps = 4 if is_standard_audio else 3
        total_steps = max(1, track_total * per_item_steps)
        completed_steps = 0

        for index, track_id in enumerate(track_ids, start=1):
            if ctx.is_cancelled():
                raise InterruptedError(f"{title} cancelled.")
            track_label = f"track_{track_id}"
            try:
                track_snapshot = bundle.track_service.fetch_track_snapshot(
                    int(track_id),
                    include_media_blobs=False,
                )
                track_label = str(
                    (track_snapshot.track_title if track_snapshot is not None else None)
                    or f"track_{track_id}"
                ).strip()
                if is_standard_audio:
                    ctx.report_progress(
                        value=completed_steps,
                        maximum=total_steps,
                        message=f"Loading audio {index} of {track_total}: {track_label}",
                    )
                    data, mime = bundle.track_service.fetch_media_bytes(int(track_id), "audio_file")
                    suggested_basename = track_label or f"track_{track_id}"
                    payload = {
                        "track_id": int(track_id),
                        "media_key": "audio_file",
                        "column_label": column_label,
                    }
                    entity_id = str(track_id)
                else:
                    field_id = int(spec["field_id"])
                    ctx.report_progress(
                        value=completed_steps,
                        maximum=total_steps,
                        message=f"Loading audio {index} of {track_total}: {track_label}",
                    )
                    data, mime = bundle.custom_field_values.fetch_blob(int(track_id), field_id)
                    field_name = str(spec.get("field_name") or "").strip()
                    suggested_basename = (
                        f"{track_label} - {field_name}" if field_name else track_label
                    )
                    payload = {
                        "track_id": int(track_id),
                        "field_id": field_id,
                        "column_label": column_label,
                    }
                    entity_id = f"{track_id}:{field_id}"

                export_bytes = self._coerce_export_bytes(data)
                destination = self._deduplicate_export_destination(
                    output_root,
                    self._default_export_filename(suggested_basename, mime or ""),
                )

                def _mutation():
                    ctx.report_progress(
                        value=completed_steps + 1,
                        maximum=total_steps,
                        message=f"Writing audio {index} of {track_total}: {destination.name}",
                    )
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(export_bytes)
                    if is_standard_audio:
                        ctx.report_progress(
                            value=completed_steps + 2,
                            maximum=total_steps,
                            message=(
                                f"Writing catalog metadata {index} of {track_total}: "
                                f"{destination.name}"
                            ),
                        )
                        _metadata_embedded, metadata_warning = write_catalog_export_tags(
                            destination,
                            track_id=int(track_id),
                            track_service=bundle.track_service,
                            release_service=bundle.release_service,
                            tag_service=bundle.audio_tag_service,
                            include_artwork_bytes=True,
                        )
                        return metadata_warning
                    ctx.report_progress(
                        value=completed_steps + 2,
                        maximum=total_steps,
                        message=f"Finalizing audio {index} of {track_total}: {destination.name}",
                    )
                    return None

                metadata_warning = _run_file_history_action(
                    history_manager=bundle.history_manager,
                    action_label=f"Export {column_label}: {destination.name}",
                    action_type="file.export_bulk_media",
                    target_path=destination,
                    mutation=_mutation,
                    entity_type="Export",
                    entity_id=entity_id,
                    payload={"path": str(destination), **payload},
                    progress_callback=ctx.report_progress,
                    record_progress=(
                        completed_steps + per_item_steps - 1,
                        f"Recording export history {index} of {track_total}: {destination.name}",
                    ),
                    logger=self.logger,
                )
                if bundle.history_manager is None:
                    ctx.report_progress(
                        value=completed_steps + per_item_steps - 1,
                        maximum=total_steps,
                        message=f"Finalizing audio {index} of {track_total}: {destination.name}",
                    )
                if metadata_warning:
                    metadata_skipped.append(f"{destination.name}: {metadata_warning}")
                exported += 1
            except Exception as exc:
                skipped.append(f"{track_label}: {exc}")
            finally:
                completed_steps += per_item_steps

        return {
            "exported": exported,
            "skipped": skipped,
            "metadata_skipped": metadata_skipped,
        }

    def _success(result: dict[str, object]):
        self._refresh_history_actions()
        exported = int(result.get("exported") or 0)
        skipped = list(result.get("skipped") or [])
        metadata_skipped = list(result.get("metadata_skipped") or [])
        if not exported:
            _message_box().warning(
                self,
                title,
                "No files were exported."
                + ("\n\nSkipped:\n" + "\n".join(skipped[:10]) if skipped else ""),
            )
            return
        message_lines = [
            f"Exported {exported} file{'s' if exported != 1 else ''} to:",
            str(output_root),
        ]
        if skipped:
            message_lines.append("")
            message_lines.append(f"Skipped {len(skipped)} row{'s' if len(skipped) != 1 else ''}:")
            message_lines.extend(skipped[:10])
        if metadata_skipped:
            message_lines.append("")
            message_lines.append(
                "Metadata skipped for "
                f"{len(metadata_skipped)} export{'s' if len(metadata_skipped) != 1 else ''}:"
            )
            message_lines.extend(metadata_skipped[:10])
        _message_box().information(self, title, "\n".join(message_lines))

    self._submit_background_bundle_task(
        title=title,
        description=(
            "Exporting stored audio files, writing catalog metadata when available, "
            "and recording export history..."
            if is_standard_audio
            else "Exporting stored custom audio files and recording export history..."
        ),
        task_fn=_worker,
        kind="read",
        unique_key=f"audio.export_column.{str(spec.get('kind') or 'unknown')}",
        cancellable=True,
        worker_completion_progress=(100, f"{title} complete."),
        on_success_after_cleanup=_success,
        on_cancelled=lambda: self.statusBar().showMessage(f"{title} cancelled.", 5000),
        on_error=lambda failure: self._show_background_task_error(
            title,
            failure,
            user_message="Could not export the selected audio files:",
        ),
    )


def _export_standard_media_for_track(
    self, track_id: int, media_key: str, suggested_basename: str | None = None
):
    if media_key == "audio_file":
        mime = str(self.track_media_meta(track_id, media_key).get("mime_type") or "")
        default_basename = suggested_basename or self._media_export_basename_for_track(
            track_id,
            media_key,
        )
        default_filename = self._default_export_filename(default_basename, mime)
        dest_path, _ = _file_dialog().getSaveFileName(
            self,
            "Export file",
            default_filename,
            "All files (*)",
        )
        if not dest_path:
            return
        try:
            resolved_dest_path = self._resolve_file_export_target(
                dest_path,
                default_filename=default_filename,
            )
        except ValueError as exc:
            _message_box().warning(self, "Export", str(exc))
            return

        self._submit_background_audio_file_export(
            task_title="Export Audio File",
            task_description=(
                "Exporting stored audio, writing catalog metadata, and recording export history..."
            ),
            dialog_title="Export",
            resolved_dest_path=resolved_dest_path,
            action_label=f"Export {media_key.replace('_', ' ').title()}: {{filename}}",
            action_type=f"file.export_{media_key}",
            entity_type="Track",
            entity_id=str(track_id),
            payload={"track_id": track_id, "media_key": media_key},
            load_source=lambda bundle: bundle.track_service.fetch_media_bytes(
                int(track_id),
                media_key,
            ),
            metadata_track_id=int(track_id),
            parent_widget=self,
        )
        return

    try:
        data, mime = self.track_fetch_media(track_id, media_key)
    except Exception as e:
        _message_box().critical(self, "Export failed", str(e))
        return
    default_basename = suggested_basename or self._media_export_basename_for_track(
        track_id,
        media_key,
    )
    self._export_bytes_with_picker(
        data,
        mime=mime or "",
        suggested_basename=default_basename,
        catalog_track_id=(track_id if media_key == "audio_file" else None),
        parent_widget=self,
        action_label=f"Export {media_key.replace('_', ' ').title()}: {{filename}}",
        action_type=f"file.export_{media_key}",
        entity_type="Track",
        entity_id=str(track_id),
        payload={"track_id": track_id, "media_key": media_key},
    )


def _export_extension_for_mime(mime: str) -> str:
    ext = mimetypes.guess_extension(mime or "")
    if ext == ".jpe":
        ext = ".jpg"
    if not ext:
        if str(mime or "").startswith("image/"):
            return ".png"
        if str(mime or "").startswith("audio/"):
            return ".wav"
        return ".bin"
    return ext


def _default_export_filename(self, suggested_basename: str | None, mime: str) -> str:
    return f"{sanitize_export_basename(suggested_basename)}{self._export_extension_for_mime(mime)}"


def _resolve_file_export_target(target_path: str | Path, *, default_filename: str) -> Path:
    return resolve_file_export_target(target_path, default_name=default_filename)


def _resolve_directory_export_target(target_path: str | Path, *, default_name: str) -> Path:
    return resolve_directory_export_target(target_path, default_name=default_name)


def _deduplicate_export_destination(output_dir: Path, filename: str) -> Path:
    candidate = output_dir / filename
    if not candidate.exists():
        return candidate
    stem = candidate.stem
    suffix = candidate.suffix
    index = 2
    while True:
        deduplicated = output_dir / f"{stem} ({index}){suffix}"
        if not deduplicated.exists():
            return deduplicated
        index += 1


def _media_export_basename_for_track(self, track_id: int, media_key: str) -> str:
    snapshot = None
    if self.track_service is not None:
        snapshot = self.track_service.fetch_track_snapshot(track_id, cursor=self.cursor)
    track_title = ""
    if snapshot is not None:
        track_title = str(snapshot.track_title or "").strip()
    if not track_title:
        try:
            track_title = self._get_track_title(track_id)
        except Exception:
            track_title = ""
    if media_key == "album_art" and snapshot is not None:
        album_title = str(snapshot.album_title or "").strip()
        if album_title and album_title.casefold() != "single":
            return album_title
    return track_title or f"track_{track_id}"


def _custom_blob_export_basename(self, track_id: int, field_def_id: int) -> str:
    track_title = self._media_export_basename_for_track(track_id, "audio_file")
    field_name = self.custom_field_definitions.get_field_name(field_def_id)
    clean_field_name = str(field_name or "").strip()
    if clean_field_name:
        return f"{track_title} - {clean_field_name}"
    return track_title


def _focused_media_export_spec(self, column: int) -> dict[str, object] | None:
    model = self.table.model() if hasattr(self, "table") else None
    header_text = ""
    column_key = None
    if model is not None and 0 <= int(column) < model.columnCount():
        header_text = str(model.headerData(int(column), Qt.Horizontal, Qt.DisplayRole) or "")
        column_key = str(model.headerData(int(column), Qt.Horizontal, ColumnKeyRole) or "")
    media_key = self._standard_media_key_for_column_key(
        column_key,
    ) or self._standard_media_key_for_header(header_text)
    if media_key:
        return {
            "kind": "standard",
            "column": int(column),
            "column_key": column_key or self._standard_media_column_key(media_key),
            "column_label": header_text or media_key.replace("_", " ").title(),
            "media_key": media_key,
        }
    if column < len(self.BASE_HEADERS):
        return None
    field_index = column - len(self.BASE_HEADERS)
    field = self._custom_field_for_column_key(column_key)
    if field is None and 0 <= field_index < len(self.active_custom_fields):
        field = self.active_custom_fields[field_index]
    if field is None:
        return None
    field_type = str(field.get("field_type") or "").strip()
    if field_type not in {"blob_audio", "blob_image"}:
        return None
    return {
        "kind": "custom_blob",
        "column": int(column),
        "column_key": column_key or self._custom_field_column_key(int(field["id"])),
        "column_label": header_text or str(field.get("name") or "File"),
        "field_id": int(field["id"]),
        "field_name": str(field.get("name") or "").strip(),
        "field_type": field_type,
    }


def _media_cell_has_payload_for_export_spec(self, index, spec: dict[str, object]) -> bool:
    if str(spec.get("kind") or "") == "standard":
        return self._media_cell_has_payload(index, media_key=str(spec.get("media_key") or ""))
    try:
        field_id = int(spec.get("field_id") or 0)
    except (TypeError, ValueError):
        return False
    return self._media_cell_has_payload(index, field_id=field_id)


def _proxy_ordered_track_ids(
    self,
    track_ids,
    *,
    media_spec: dict[str, object] | None = None,
    require_media_payload: bool = False,
) -> list[int]:
    requested = set(self._normalize_track_ids(track_ids or []))
    controller = self._catalog_table_controller()
    column = 0
    if media_spec is not None:
        try:
            column = int(media_spec.get("column"))
        except (TypeError, ValueError):
            column_key = str(media_spec.get("column_key") or "")
            resolved_column = controller.column_for_key(column_key)
            column = resolved_column if resolved_column is not None else -1
    ordered: list[int] = []
    indexes = controller.visible_indexes(column=column if column >= 0 else 0)
    for index in indexes:
        if (
            require_media_payload
            and media_spec is not None
            and column >= 0
            and not self._media_cell_has_payload_for_export_spec(index, media_spec)
        ):
            continue
        track_id = controller.track_id_for_index(index)
        if track_id is None:
            continue
        if requested and int(track_id) not in requested:
            continue
        ordered.append(int(track_id))
    if ordered or self._catalog_proxy_model() is not None:
        return self._normalize_track_ids(ordered)
    return self._normalize_track_ids(track_ids or [])


def _export_focused_media_column(
    self,
    column: int,
    *,
    track_ids: list[int] | None = None,
) -> None:
    spec = self._focused_media_export_spec(column)
    if spec is None:
        _message_box().warning(
            self,
            "Export Files",
            "Focus a stored audio, album art, or blob media column first.",
        )
        return
    selected_ids = self._proxy_ordered_track_ids(
        track_ids or self._catalog_table_controller().selected_track_ids(),
        media_spec=spec,
    )
    if not selected_ids:
        _message_box().information(
            self,
            "Export Files",
            "Select one or more rows before exporting the focused column.",
        )
        return
    output_dir = _file_dialog().getExistingDirectory(
        self,
        f"Export {spec['column_label']} Files",
    )
    if not output_dir:
        return
    output_root = Path(output_dir)
    if (
        str(spec.get("kind") or "") == "standard"
        and str(spec.get("media_key") or "") == "audio_file"
    ) or (
        str(spec.get("kind") or "") == "custom_blob"
        and str(spec.get("field_type") or "") == "blob_audio"
    ):
        self._submit_background_audio_column_export(
            spec=spec,
            track_ids=selected_ids,
            output_root=output_root,
        )
        return
    exported = 0
    skipped: list[str] = []
    metadata_skipped: list[str] = []
    history_changed = False
    for track_id in selected_ids:
        try:
            if spec["kind"] == "standard":
                media_key = str(spec["media_key"])
                if not self.track_has_media(track_id, media_key):
                    raise FileNotFoundError(
                        f"No stored {str(spec['column_label']).lower()} is available."
                    )
                data, mime = self.track_fetch_media(track_id, media_key)
                suggested_basename = self._media_export_basename_for_track(track_id, media_key)
                payload = {
                    "track_id": track_id,
                    "media_key": media_key,
                    "column_label": spec["column_label"],
                }
                entity_id = str(track_id)
            else:
                field_id = int(spec["field_id"])
                if not self.cf_has_blob(track_id, field_id):
                    raise FileNotFoundError(
                        f"No stored file is available in {spec['column_label']}."
                    )
                data, mime = self.cf_fetch_blob(track_id, field_id)
                suggested_basename = self._custom_blob_export_basename(track_id, field_id)
                payload = {
                    "track_id": track_id,
                    "field_id": field_id,
                    "column_label": spec["column_label"],
                }
                entity_id = f"{track_id}:{field_id}"
            if isinstance(data, memoryview):
                data = data.tobytes()
            elif isinstance(data, bytearray):
                data = bytes(data)
            dest_path = self._deduplicate_export_destination(
                output_root,
                self._default_export_filename(suggested_basename, mime or ""),
            )
            if self.history_manager is None:
                dest_path.write_bytes(data)
            else:
                _run_file_history_action(
                    history_manager=self.history_manager,
                    action_label=f"Export {spec['column_label']}: {dest_path.name}",
                    action_type="file.export_bulk_media",
                    target_path=dest_path,
                    mutation=lambda data=data, dest_path=dest_path: dest_path.write_bytes(data),
                    entity_type="Export",
                    entity_id=entity_id,
                    payload={"path": str(dest_path), **payload},
                    logger=self.logger,
                )
                history_changed = True
            if spec["kind"] == "standard" and str(spec["media_key"]) == "audio_file":
                metadata_warning = self._attempt_catalog_audio_export_metadata(
                    dest_path,
                    track_id=track_id,
                )
                if metadata_warning:
                    metadata_skipped.append(f"{dest_path.name}: {metadata_warning}")
            exported += 1
        except Exception as exc:
            try:
                track_label = self._get_track_title(track_id) or f"track_{track_id}"
            except Exception:
                track_label = f"track_{track_id}"
            skipped.append(f"{track_label}: {exc}")
    if history_changed:
        self._refresh_history_actions()
    if not exported:
        _message_box().warning(
            self,
            f"Export {spec['column_label']}",
            "No files were exported."
            + ("\n\nSkipped:\n" + "\n".join(skipped[:10]) if skipped else ""),
        )
        return
    message_lines = [
        f"Exported {exported} file{'s' if exported != 1 else ''} to:",
        str(output_root),
    ]
    if skipped:
        message_lines.append("")
        message_lines.append(f"Skipped {len(skipped)} row{'s' if len(skipped) != 1 else ''}:")
        message_lines.extend(skipped[:10])
    if metadata_skipped:
        message_lines.append("")
        message_lines.append(
            f"Metadata skipped for {len(metadata_skipped)} export{'s' if len(metadata_skipped) != 1 else ''}:"
        )
        message_lines.extend(metadata_skipped[:10])
    _message_box().information(
        self,
        f"Export {spec['column_label']}",
        "\n".join(message_lines),
    )

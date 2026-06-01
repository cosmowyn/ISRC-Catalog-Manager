"""Audio conversion and derivative export orchestration for the application shell."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QFileDialog, QMessageBox

from isrc_manager.app_services import configure_foreground_exchange_services
from isrc_manager.conversion import ConversionService
from isrc_manager.conversion.dialogs import ConversionDialog
from isrc_manager.file_storage import STORAGE_MODE_DATABASE, normalize_storage_mode
from isrc_manager.media import AudioConversionService
from isrc_manager.media.derivatives import (
    MANAGED_DERIVATIVE_KIND_LOSSY,
    MANAGED_DERIVATIVE_KIND_WATERMARK_AUTHENTIC,
    ExternalAudioConversionCoordinator,
    ExternalAudioConversionRequest,
    ExternalAudioConversionResult,
    ManagedDerivativeExportCoordinator,
    ManagedDerivativeExportRequest,
    ManagedDerivativeExportResult,
)
from isrc_manager.tasks.history_helpers import run_file_history_action
from isrc_manager.ui_common import _prompt_compact_choice_dialog

if TYPE_CHECKING:
    from isrc_manager.services.tracks import TrackSnapshot


def _root_attr(name: str, fallback):
    main_window_module = sys.modules.get("isrc_manager.main_window")
    return (
        getattr(main_window_module, name, fallback) if main_window_module is not None else fallback
    )


def _message_box():
    return _root_attr("QMessageBox", QMessageBox)


def _file_dialog():
    return _root_attr("QFileDialog", QFileDialog)


def _run_file_history_action(*args, **kwargs):
    return _root_attr("run_file_history_action", run_file_history_action)(*args, **kwargs)


def _compact_choice_dialog(*args, **kwargs):
    return _root_attr("_prompt_compact_choice_dialog", _prompt_compact_choice_dialog)(
        *args, **kwargs
    )


def _refresh_audio_conversion_action_states(self) -> None:
    conversion_available = bool(
        self.audio_conversion_service is not None and self.audio_conversion_service.is_available()
    )
    capabilities = (
        self.audio_conversion_service.capabilities()
        if conversion_available and self.audio_conversion_service is not None
        else None
    )
    managed_authentic_available = bool(
        self.track_service is not None
        and self.audio_authenticity_service is not None
        and capabilities is not None
        and capabilities.managed_targets
    )
    managed_lossy_available = bool(
        self.track_service is not None
        and capabilities is not None
        and capabilities.managed_lossy_targets
    )
    forensic_available = bool(
        self.track_service is not None
        and self.forensic_export_service is not None
        and capabilities is not None
        and capabilities.managed_forensic_targets
    )
    managed_available = bool(managed_authentic_available or managed_lossy_available)
    external_available = bool(
        conversion_available and capabilities is not None and capabilities.external_targets
    )
    if managed_available and self.audio_authenticity_service is not None:
        managed_message = (
            "Export managed audio derivatives. Lossless outputs stay on the "
            "watermark-authentic path; lossy outputs become tagged managed derivatives "
            "with derivative lineage."
        )
    elif managed_available:
        managed_message = (
            "Export managed lossy derivatives with catalog tags and derivative "
            "lineage. Lossless outputs stay unavailable until authenticity "
            "services are available in the open profile."
        )
    elif conversion_available and self.track_service is not None:
        managed_message = (
            "No supported managed derivative targets are available in this ffmpeg build."
        )
    else:
        managed_message = self._audio_conversion_unavailable_message() or "Open a profile first."
    external_message = (
        "Utility conversion only: no catalog metadata, no watermarking, and no managed derivative registration."
        if external_available
        else "External audio conversion requires ffmpeg."
    )
    forensic_message = (
        "Export recipient-specific forensic delivery copies for leak tracing. This stays separate from signed authenticity master exports."
        if forensic_available
        else (
            "Forensic watermark export requires an open profile, available conversion targets, and a local authenticity key."
            if self.track_service is not None
            else "Open a profile first."
        )
    )
    soundcloud_forensic_message = (
        "Export SoundCloud-ready forensic upload copies with recipient fixed to SoundCloud and public profile trace metadata."
        if forensic_available
        else forensic_message
    )
    forensic_inspect_message = (
        "Inspect a suspicious file and attempt forensic watermark resolution against the open profile's export ledger."
        if self.forensic_export_service is not None
        else "Open a profile with forensic watermark services available first."
    )
    for attr_name, enabled, status_tip in (
        ("convert_selected_audio_action", managed_available, managed_message),
        ("convert_external_audio_files_action", external_available, external_message),
        ("export_forensic_watermarked_audio_action", forensic_available, forensic_message),
        ("soundcloud_forensic_export_action", forensic_available, soundcloud_forensic_message),
        (
            "inspect_forensic_watermark_action",
            self.forensic_export_service is not None,
            forensic_inspect_message,
        ),
    ):
        action = getattr(self, attr_name, None)
        if action is None:
            continue
        action.setEnabled(enabled)
        action.setStatusTip(status_tip)
        action.setToolTip(status_tip)
    configure_foreground_exchange_services(self)


def open_conversion_dialog(self) -> None:
    dialog = _root_attr("ConversionDialog", ConversionDialog)(
        service=self.conversion_service
        or ConversionService(
            exchange_service=self.exchange_service,
            settings_read_service=self.settings_reads,
        ),
        settings=self.settings,
        template_store_service=self.conversion_template_store_service,
        export_callback=self._start_conversion_export,
        exports_dir=self.exports_dir,
        profile_available=bool(self.conn is not None and self.exchange_service is not None),
        default_database_track_ids_provider=lambda: list(
            self._catalog_table_controller().default_conversion_track_ids()
        ),
        track_choices_provider=self._all_catalog_track_choices,
        parent=self,
    )
    try:
        dialog.exec()
    finally:
        dialog.close()


def _start_conversion_export(self, preview, output_path: str | Path) -> None:
    format_name = str(preview.template_profile.format_name or "").strip().lower() or "conversion"
    default_name = Path(str(output_path or "")).name or (
        f"conversion_output{preview.template_profile.output_suffix or f'.{format_name}'}"
    )
    try:
        resolved_path = self._resolve_file_export_target(
            output_path,
            default_filename=default_name,
        )
    except ValueError as exc:
        _message_box().warning(self, "Template Conversion", str(exc))
        return
    expected_suffix = str(preview.template_profile.output_suffix or "").strip()
    if expected_suffix and resolved_path.suffix.lower() != expected_suffix.lower():
        resolved_path = resolved_path.with_suffix(expected_suffix)
    if (
        preview.template_profile.template_bytes is None
        and resolved_path.resolve() == preview.template_profile.template_path.resolve()
    ):
        _message_box().warning(
            self,
            "Template Conversion",
            "Choose a new output file. Conversion export never overwrites the source template.",
        )
        return

    use_history = (
        self.history_manager is not None
        and str(getattr(self, "current_db_path", "") or "").strip()
        and self.background_service_factory is not None
    )

    def _worker(bundle, ctx):
        export_progress = self._scaled_progress_callback(ctx.report_progress, start=0, end=92)

        def _mutation():
            return bundle.conversion_service.export_preview(
                preview,
                resolved_path,
                progress_callback=export_progress,
            )

        return _run_file_history_action(
            history_manager=bundle.history_manager,
            action_label=lambda result: (
                f"Export Conversion {result.target_format.upper()}: {result.exported_row_count} rows"
            ),
            action_type="file.conversion_export",
            target_path=resolved_path,
            mutation=_mutation,
            entity_type="ConversionExport",
            entity_id=str(resolved_path),
            payload=lambda result: {
                "path": str(resolved_path),
                "format": result.target_format,
                "row_count": result.exported_row_count,
                "template_path": str(preview.template_profile.template_path),
                "source_mode": preview.source_profile.source_mode,
            },
            progress_callback=ctx.report_progress,
            post_mutation_progress=(95, "Capturing conversion export history..."),
            record_progress=(97, "Recording conversion export history..."),
            logger=self.logger,
        )

    def _direct_worker(ctx):
        export_progress = self._scaled_progress_callback(ctx.report_progress, start=0, end=96)
        return self.conversion_service.export_preview(
            preview,
            resolved_path,
            progress_callback=export_progress,
        )

    def _success(result) -> None:
        if self.history_manager is not None:
            self._refresh_history_actions()
        self._log_event(
            "conversion.export",
            "Exported template conversion output",
            path=str(resolved_path),
            format=result.target_format,
            exported_rows=result.exported_row_count,
            template_path=str(preview.template_profile.template_path),
            source_mode=preview.source_profile.source_mode,
        )
        if self.conn is not None:
            self._audit(
                "EXPORT",
                "ConversionExport",
                ref_id=str(resolved_path),
                details=(
                    f"format={result.target_format}; rows={result.exported_row_count}; "
                    f"template={preview.template_profile.template_path.name}"
                ),
            )
            self._audit_commit()
        message_lines = [
            f"Converted output written to:\n{resolved_path}",
            "",
            f"Format: {result.target_format.upper()}",
            f"Rows written: {result.exported_row_count}",
        ]
        if result.summary_lines:
            message_lines.extend(["", *result.summary_lines])
        _message_box().information(self, "Template Conversion", "\n".join(message_lines))

    submit_kwargs = {
        "title": f"Export Conversion {format_name.upper()}",
        "description": "Rendering the converted output from the compiled template preview...",
        "kind": "read",
        "unique_key": f"conversion.export.{format_name}",
        "worker_completion_progress": (100, "Conversion export complete."),
        "on_success_after_cleanup": _success,
        "on_error": lambda failure: self._show_background_task_error(
            "Template Conversion",
            failure,
            user_message="Could not export the converted output:",
        ),
    }
    if use_history:
        self._submit_background_bundle_task(
            task_fn=_worker,
            **submit_kwargs,
        )
    else:
        self._submit_background_task(
            task_fn=_direct_worker,
            requires_profile=False,
            **submit_kwargs,
        )


def open_derivative_ledger(self, batch_id: str | None = None):
    if self.asset_service is None:
        _message_box().warning(self, "Derivative Ledger", "Open a profile first.")
        return
    return self._show_workspace_panel(
        self._ensure_asset_registry_dock,
        panel_attr="asset_registry_panel",
        legacy_attr="asset_browser_dialog",
        configure=lambda panel: panel.focus_derivative_batch(batch_id),
    )


def _audio_export_source_suffix(self, snapshot: TrackSnapshot) -> str:
    filename = str(snapshot.audio_file_filename or "").strip()
    if filename:
        suffix = Path(filename).suffix.strip()
        if suffix:
            return suffix
    return self._export_extension_for_mime(str(snapshot.audio_file_mime_type or ""))


def _audio_export_source_label(snapshot: TrackSnapshot) -> str:
    filename = str(snapshot.audio_file_filename or "").strip()
    storage_mode = normalize_storage_mode(snapshot.audio_file_storage_mode, default=None)
    if storage_mode == STORAGE_MODE_DATABASE or snapshot.audio_file_blob_b64:
        if filename:
            return f"{filename} (stored in database)"
        return "Stored in database"
    return filename


def _audio_conversion_unavailable_message(self) -> str:
    if self.audio_conversion_service is None or not self.audio_conversion_service.is_available():
        return (
            "Managed audio derivative export requires ffmpeg. "
            "Install ffmpeg or add it to PATH to enable derivative export and the external conversion utility."
        )
    if self.track_service is None:
        return "Managed audio derivative export requires an open profile."
    return ""


def _prompt_audio_conversion_format(
    self,
    *,
    title: str,
    prompt: str,
    capability_group: str,
) -> str | None:
    if self.audio_conversion_service is None:
        return None
    capabilities = self.audio_conversion_service.capabilities()
    if capability_group == "managed_authenticity":
        profiles = capabilities.managed_targets
    elif capability_group == "managed_forensic":
        profiles = capabilities.managed_forensic_targets
    elif capability_group == "managed_lossy":
        profiles = capabilities.managed_lossy_targets
    elif capability_group in {"managed", "managed_any"}:
        profiles = tuple(
            list(capabilities.managed_targets)
            + [
                profile
                for profile in capabilities.managed_lossy_targets
                if all(existing.id != profile.id for existing in capabilities.managed_targets)
            ]
        )
    else:
        profiles = capabilities.external_targets
    if not profiles:
        return None
    return _compact_choice_dialog(
        self,
        title=title,
        prompt=prompt,
        choices=[(profile.id, profile.label) for profile in profiles],
        ok_text="Export",
    )


def _selected_track_ids_with_audio(self, track_ids: list[int] | None = None) -> list[int]:
    if self.track_service is None:
        return []
    selected_ids = self._normalize_track_ids(
        track_ids or self._catalog_table_controller().selected_or_visible_track_ids()
    )
    return [
        track_id
        for track_id in selected_ids
        if self.track_service.has_media(track_id, "audio_file")
    ]


def convert_selected_audio(self, track_ids: list[int] | None = None):
    title = "Export Audio Derivatives"
    if self.track_service is None:
        _message_box().warning(self, title, "Open a profile first.")
        return
    unavailable_message = self._audio_conversion_unavailable_message()
    if unavailable_message:
        _message_box().warning(self, title, unavailable_message)
        return
    selected_ids = self._selected_track_ids_with_audio(track_ids)
    if not selected_ids:
        _message_box().information(
            self,
            title,
            "Select one or more tracks with attached primary audio first.",
        )
        return
    output_format = self._prompt_audio_conversion_format(
        title=title,
        prompt=(
            "Choose the managed derivative output format. "
            "Lossless targets stay on the watermark-authentic path; "
            "lossy targets export as tagged managed derivatives without recipient-specific forensic watermarking. "
            "Use Convert External Audio Files when you do not want catalog metadata or derivative tracking."
        ),
        capability_group="managed_any",
    )
    if not output_format:
        return
    authenticity_required = (
        self.audio_conversion_service is not None
        and self.audio_conversion_service.is_supported_target(
            output_format,
            capability_group="managed_authenticity",
        )
    )
    if authenticity_required and self.audio_authenticity_service is None:
        _message_box().warning(
            self,
            title,
            "Lossless managed exports require an open profile with audio authenticity services. Choose a lossy output format or use the watermark-authentic master export workflow.",
        )
        return
    output_dir = _file_dialog().getExistingDirectory(
        self,
        "Choose Export Folder for Audio Derivatives",
        str(self.exports_dir / "managed_audio_derivatives"),
    )
    if not output_dir:
        return

    def _worker(bundle, ctx):
        export_progress = self._scaled_progress_callback(ctx.report_progress, start=0, end=96)
        coordinator = ManagedDerivativeExportCoordinator(
            conn=bundle.conn,
            track_service=bundle.track_service,
            release_service=bundle.release_service,
            tag_service=bundle.audio_tag_service,
            authenticity_service=bundle.audio_authenticity_service,
            conversion_service=AudioConversionService(),
        )
        request = ManagedDerivativeExportRequest(
            track_ids=selected_ids,
            output_dir=output_dir,
            output_format=output_format,
            derivative_kind=(
                MANAGED_DERIVATIVE_KIND_WATERMARK_AUTHENTIC
                if authenticity_required
                else MANAGED_DERIVATIVE_KIND_LOSSY
            ),
            profile_name=self._current_profile_name(),
        )
        return coordinator.export(
            request,
            progress_callback=export_progress,
            is_cancelled=ctx.is_cancelled,
        )

    def _before_cleanup(result: ManagedDerivativeExportResult, ui_progress) -> None:
        self._advance_task_ui_progress(
            ui_progress,
            value=97,
            message="Recording managed derivative export results...",
        )
        self._log_event(
            "audio.derivative_export",
            "Exported managed catalog derivatives",
            output_dir=output_dir,
            output_format=output_format,
            derivative_kind=result.derivative_kind,
            authenticity_basis=result.authenticity_basis,
            exported=result.exported,
            skipped=result.skipped,
            batch_public_id=result.batch_public_id,
            zip_path=result.zip_path,
            warnings=result.warnings,
        )
        self._audit(
            "EXPORT",
            "TrackAudioDerivative",
            ref_id=result.batch_public_id,
            details=(
                f"exported={result.exported}; skipped={result.skipped}; format={output_format}; "
                f"derivative_kind={result.derivative_kind}; authenticity_basis={result.authenticity_basis}"
            ),
        )
        self._audit_commit()

        self._advance_task_ui_progress(
            ui_progress,
            value=100,
            message="Audio derivative export complete.",
        )

    def _success(result: ManagedDerivativeExportResult):
        target_text = result.zip_path or "\n".join(result.written_paths[:3]) or output_dir
        _message_box().information(
            self,
            title,
            f"Exported {result.exported} managed audio derivative file{'s' if result.exported != 1 else ''}."
            f"\n\nOutput:\n{target_text}"
            + (
                "\n\nThese exports were finalized on the watermark-authentic path."
                if result.watermark_applied
                else "\n\nThese exports are managed lossy derivatives with catalog metadata and derivative lineage."
            )
            + f"\n\nSkipped: {result.skipped}"
            + ("\n\nWarnings:\n- " + "\n- ".join(result.warnings[:12]) if result.warnings else ""),
        )

    self._submit_background_bundle_task(
        title=title,
        description=(
            "Converting selected catalog audio, writing tags, branching into watermark-authentic or lossy managed derivative finalization, and registering derivatives..."
        ),
        task_fn=_worker,
        kind="write",
        unique_key="audio.derivative_export",
        cancellable=True,
        worker_completion_progress=(96, "Finalizing managed derivative export results..."),
        on_success_before_cleanup=_before_cleanup,
        on_success_after_cleanup=_success,
        on_cancelled=lambda: self.statusBar().showMessage(
            "Audio derivative export cancelled.", 5000
        ),
        on_error=lambda failure: self._show_background_task_error(
            title,
            failure,
            user_message="Could not export audio derivatives:",
        ),
    )


def convert_external_audio_files(self):
    title = "Convert External Audio Files"
    if self.audio_conversion_service is None or not self.audio_conversion_service.is_available():
        _message_box().warning(
            self,
            title,
            "External audio conversion requires ffmpeg. "
            "Install ffmpeg or add it to PATH to enable plain file conversion.",
        )
        return
    chosen_files, _selected_filter = _file_dialog().getOpenFileNames(
        self,
        "Choose External Audio Files to Convert",
        "",
        "Audio Files (*.wav *.aif *.aiff *.mp3 *.flac *.m4a *.aac *.ogg *.oga *.opus *.mp4);;All Files (*)",
    )
    input_paths = [str(Path(path)) for path in dict.fromkeys(chosen_files) if str(path).strip()]
    if not input_paths:
        return
    output_format = self._prompt_audio_conversion_format(
        title=title,
        prompt=(
            "Choose the utility conversion output format. "
            "This strips inherited source metadata and does not use catalog metadata, "
            "watermarking, or derivative registration."
        ),
        capability_group="external",
    )
    if not output_format:
        return
    output_dir = _file_dialog().getExistingDirectory(
        self,
        "Choose Output Folder for External Audio Conversion",
        str(self.exports_dir / "external_audio_conversions"),
    )
    if not output_dir:
        return

    def _worker(ctx):
        export_progress = self._scaled_progress_callback(ctx.report_progress, start=0, end=96)
        coordinator = ExternalAudioConversionCoordinator(
            conversion_service=AudioConversionService()
        )
        request = ExternalAudioConversionRequest(
            input_paths=input_paths,
            output_dir=output_dir,
            output_format=output_format,
        )
        return coordinator.export(
            request,
            progress_callback=export_progress,
            is_cancelled=ctx.is_cancelled,
        )

    def _before_cleanup(result: ExternalAudioConversionResult, ui_progress) -> None:
        self._advance_task_ui_progress(
            ui_progress,
            value=97,
            message="Recording external audio conversion results...",
        )
        self._log_event(
            "audio.external_convert",
            "Converted external audio files",
            output_dir=output_dir,
            output_format=output_format,
            exported=result.exported,
            skipped=result.skipped,
            batch_public_id=result.batch_public_id,
            zip_path=result.zip_path,
            warnings=result.warnings,
        )

        self._advance_task_ui_progress(
            ui_progress,
            value=100,
            message="External audio conversion complete.",
        )

    def _success(result: ExternalAudioConversionResult):
        target_text = result.zip_path or "\n".join(result.written_paths[:3]) or output_dir
        _message_box().information(
            self,
            title,
            f"Converted {result.exported} external audio file{'s' if result.exported != 1 else ''} with the plain conversion workflow."
            f"\n\nOutput:\n{target_text}"
            "\n\nInherited source metadata was stripped. No catalog metadata, watermarking, or managed derivative registration was applied."
            f"\n\nSkipped: {result.skipped}"
            + ("\n\nWarnings:\n- " + "\n- ".join(result.warnings[:12]) if result.warnings else ""),
        )

    self._submit_background_task(
        title=title,
        description=(
            "Converting external audio files with the plain conversion workflow only. "
            "Inherited source metadata is stripped, and no catalog metadata, "
            "watermarking, or managed derivative registration is applied..."
        ),
        task_fn=_worker,
        kind="read",
        unique_key="audio.external_convert",
        requires_profile=False,
        cancellable=True,
        worker_completion_progress=(96, "Finalizing external audio conversion results..."),
        on_success_before_cleanup=_before_cleanup,
        on_success_after_cleanup=_success,
        on_cancelled=lambda: self.statusBar().showMessage(
            "External audio conversion cancelled.", 5000
        ),
        on_error=lambda failure: self._show_background_task_error(
            title,
            failure,
            user_message="Could not convert the selected external audio files:",
        ),
    )

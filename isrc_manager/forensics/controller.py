"""Forensic watermark workflow orchestration for the application shell."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QDialog, QFileDialog, QMessageBox

from isrc_manager.forensics import (
    ForensicExportDialog,
    ForensicExportRequest,
    ForensicExportResult,
    ForensicInspectionDialog,
    ForensicInspectionReport,
)

SOUNDCLOUD_FORENSIC_RECIPIENT_LABEL = "SoundCloud"


def _root_attr(name: str, fallback):
    main_window_module = sys.modules.get("isrc_manager.main_window")
    return (
        getattr(main_window_module, name, fallback) if main_window_module is not None else fallback
    )


def _message_box():
    return _root_attr("QMessageBox", QMessageBox)


def _file_dialog():
    return _root_attr("QFileDialog", QFileDialog)


def _format_label_choices(self) -> list[tuple[str, str]]:
    return [
        (
            profile.id,
            (
                f"{profile.label} (lossy forensic delivery copy)"
                if profile.lossy
                else f"{profile.label} (lossless forensic copy)"
            ),
        )
        for profile in self.audio_conversion_service.capabilities().managed_forensic_targets
    ]


def _soundcloud_account_public_profile(self) -> dict[str, str]:
    conn = getattr(self, "conn", None)
    if conn is None:
        return {}
    try:
        from isrc_manager.integrations.soundcloud.persistence import SoundCloudSQLiteRepository

        account = SoundCloudSQLiteRepository(conn).active_account()
    except Exception:
        return {}
    if account is None:
        return {}
    profile: dict[str, str] = {}
    for key, value in (
        ("user_id", getattr(account, "soundcloud_user_id", None)),
        ("username", getattr(account, "username", None)),
        ("profile_url", getattr(account, "permalink_url", None)),
        ("avatar_url", getattr(account, "avatar_url", None)),
    ):
        text = str(value or "").strip()
        if text:
            profile[key] = text
    return profile


def _soundcloud_forensic_share_label(
    *, public_profile: dict[str, str], upload_label: str | None = None
) -> str:
    parts = ["SoundCloud upload"]
    upload_text = str(upload_label or "").strip()
    if upload_text:
        parts.append(f"label={upload_text}")
    if public_profile:
        for key in ("username", "user_id", "profile_url", "avatar_url"):
            value = str(public_profile.get(key) or "").strip()
            if value:
                parts.append(f"{key}={value}")
    else:
        parts.append("public_profile=unavailable")
    return "; ".join(parts)


def export_forensic_watermarked_audio(self, track_ids: list[int] | None = None):
    title = "Export Forensic Watermarked Audio"
    if self.track_service is None:
        _message_box().warning(self, title, "Open a profile first.")
        return
    if self.forensic_export_service is None or self.audio_conversion_service is None:
        _message_box().warning(
            self,
            title,
            "Forensic watermark export requires an open profile, a local authenticity key, and managed conversion support.",
        )
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
    format_labels = _format_label_choices(self)
    if not format_labels:
        _message_box().warning(
            self,
            title,
            "No forensic watermark export targets are available in this runtime.",
        )
        return
    if ForensicExportDialog is None:
        output_format = self._prompt_audio_conversion_format(
            title=title,
            prompt=(
                "Choose the forensic delivery output format. "
                "These exports are recipient-specific leak-tracing copies, not signed authenticity masters."
            ),
            capability_group="managed_forensic",
        )
        recipient_label = None
        share_label = None
    else:
        export_dialog = _root_attr("ForensicExportDialog", ForensicExportDialog)(
            format_labels=format_labels, parent=self
        )
        if export_dialog.exec() != QDialog.Accepted:
            return
        output_format = export_dialog.selected_format_id()
        recipient_label = export_dialog.recipient_label()
        share_label = export_dialog.share_label()
    if not output_format:
        return
    output_dir = _file_dialog().getExistingDirectory(
        self,
        "Choose Export Folder for Forensic Watermarked Audio",
        str(self.exports_dir / "forensic_audio"),
    )
    if not output_dir:
        return

    def _worker(bundle, ctx):
        export_progress = self._scaled_progress_callback(ctx.report_progress, start=0, end=96)
        return bundle.forensic_export_service.export(
            ForensicExportRequest(
                track_ids=selected_ids,
                output_dir=output_dir,
                output_format=output_format,
                recipient_label=recipient_label,
                share_label=share_label,
                profile_name=self._current_profile_name(),
            ),
            progress_callback=export_progress,
            is_cancelled=ctx.is_cancelled,
        )

    def _before_cleanup(result: ForensicExportResult, ui_progress) -> None:
        self._advance_task_ui_progress(
            ui_progress,
            value=97,
            message="Recording forensic watermark export results...",
        )
        self._log_event(
            "forensics.export_audio",
            "Exported forensic watermarked audio copies",
            output_dir=output_dir,
            output_format=output_format,
            recipient_label=recipient_label,
            share_label=share_label,
            exported=result.exported,
            skipped=result.skipped,
            batch_public_id=result.batch_public_id,
            zip_path=result.zip_path,
            warnings=result.warnings,
        )
        self._audit(
            "EXPORT",
            "ForensicAudio",
            ref_id=result.batch_public_id,
            details=(
                f"exported={result.exported}; skipped={result.skipped}; "
                f"format={output_format}; recipient={recipient_label or ''}; share={share_label or ''}"
            ),
        )
        self._audit_commit()

        self._advance_task_ui_progress(
            ui_progress,
            value=100,
            message="Forensic watermark export complete.",
        )

    def _success(result: ForensicExportResult):
        target_text = result.zip_path or "\n".join(result.written_paths[:3]) or output_dir
        _message_box().information(
            self,
            title,
            f"Exported {result.exported} forensic watermarked cop{'y' if result.exported == 1 else 'ies'}."
            f"\n\nOutput:\n{target_text}"
            f"\n\nThese are recipient-specific {output_format.upper()} leak-tracing derivatives. They remain distinct from direct authenticity master exports."
            f"\n\nSkipped: {result.skipped}"
            + ("\n\nWarnings:\n- " + "\n- ".join(result.warnings[:12]) if result.warnings else ""),
        )

    self._submit_background_bundle_task(
        title=title,
        description=(
            "Converting selected catalog audio into delivery copies, writing tags, embedding recipient-specific forensic watermarks, hashing final files, and registering forensic export lineage..."
        ),
        task_fn=_worker,
        kind="write",
        unique_key="forensics.export_audio",
        cancellable=True,
        worker_completion_progress=(96, "Finalizing forensic watermark export results..."),
        on_success_before_cleanup=_before_cleanup,
        on_success_after_cleanup=_success,
        on_cancelled=lambda: self.statusBar().showMessage(
            "Forensic watermark export cancelled.", 5000
        ),
        on_error=lambda failure: self._show_background_task_error(
            title,
            failure,
            user_message="Could not export forensic watermarked audio:",
        ),
    )


def export_soundcloud_forensic_watermarked_audio(self, track_ids: list[int] | None = None):
    title = "Export SoundCloud Forensic Upload Audio"
    if self.track_service is None:
        _message_box().warning(self, title, "Open a profile first.")
        return
    if self.forensic_export_service is None or self.audio_conversion_service is None:
        _message_box().warning(
            self,
            title,
            "SoundCloud forensic export requires an open profile, a local authenticity key, and managed conversion support.",
        )
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
    format_labels = _format_label_choices(self)
    if not format_labels:
        _message_box().warning(
            self,
            title,
            "No forensic watermark export targets are available in this runtime.",
        )
        return
    public_profile = _soundcloud_account_public_profile(self)
    upload_label = None
    if ForensicExportDialog is None:
        output_format = self._prompt_audio_conversion_format(
            title=title,
            prompt=(
                "Choose the SoundCloud forensic upload format. WAV is recommended when "
                "SoundCloud will perform its own streaming conversions."
            ),
            capability_group="managed_forensic",
        )
    else:
        export_dialog = _root_attr("ForensicExportDialog", ForensicExportDialog)(
            format_labels=format_labels,
            fixed_recipient_label=SOUNDCLOUD_FORENSIC_RECIPIENT_LABEL,
            share_label_caption="SoundCloud Label",
            share_label_placeholder="Optional upload, campaign, or release label",
            parent=self,
        )
        if export_dialog.exec() != QDialog.Accepted:
            return
        output_format = export_dialog.selected_format_id()
        upload_label = export_dialog.share_label()
    if not output_format:
        return
    share_label = _soundcloud_forensic_share_label(
        public_profile=public_profile,
        upload_label=upload_label,
    )
    output_dir = _file_dialog().getExistingDirectory(
        self,
        "Choose Export Folder for SoundCloud Forensic Upload Audio",
        str(self.exports_dir / "soundcloud_forensic_audio"),
    )
    if not output_dir:
        return

    def _worker(bundle, ctx):
        export_progress = self._scaled_progress_callback(ctx.report_progress, start=0, end=96)
        return bundle.forensic_export_service.export(
            ForensicExportRequest(
                track_ids=selected_ids,
                output_dir=output_dir,
                output_format=output_format,
                recipient_label=SOUNDCLOUD_FORENSIC_RECIPIENT_LABEL,
                share_label=share_label,
                profile_name=self._current_profile_name(),
                embed_trace_metadata=True,
            ),
            progress_callback=export_progress,
            is_cancelled=ctx.is_cancelled,
        )

    def _before_cleanup(result: ForensicExportResult, ui_progress) -> None:
        self._advance_task_ui_progress(
            ui_progress,
            value=97,
            message="Recording SoundCloud forensic export results...",
        )
        self._log_event(
            "forensics.export_soundcloud_audio",
            "Exported SoundCloud forensic watermarked audio copies",
            output_dir=output_dir,
            output_format=output_format,
            recipient_label=SOUNDCLOUD_FORENSIC_RECIPIENT_LABEL,
            share_label=share_label,
            exported=result.exported,
            skipped=result.skipped,
            batch_public_id=result.batch_public_id,
            zip_path=result.zip_path,
            warnings=result.warnings,
        )
        self._audit(
            "EXPORT",
            "SoundCloudForensicAudio",
            ref_id=result.batch_public_id,
            details=(
                f"exported={result.exported}; skipped={result.skipped}; "
                f"format={output_format}; recipient={SOUNDCLOUD_FORENSIC_RECIPIENT_LABEL}; "
                f"share={share_label}"
            ),
        )
        self._audit_commit()

        self._advance_task_ui_progress(
            ui_progress,
            value=100,
            message="SoundCloud forensic export complete.",
        )

    def _success(result: ForensicExportResult):
        target_text = result.zip_path or "\n".join(result.written_paths[:3]) or output_dir
        profile_text = (
            "\n\nPublic SoundCloud trace:\n" + share_label
            if share_label
            else "\n\nPublic SoundCloud trace: unavailable"
        )
        _message_box().information(
            self,
            title,
            f"Exported {result.exported} SoundCloud forensic upload cop{'y' if result.exported == 1 else 'ies'}."
            f"\n\nOutput:\n{target_text}"
            f"\n\nRecipient is fixed to SoundCloud. The forensic token binding and embedded metadata include the public SoundCloud trace where available."
            f"{profile_text}"
            f"\n\nSkipped: {result.skipped}"
            + ("\n\nWarnings:\n- " + "\n- ".join(result.warnings[:12]) if result.warnings else ""),
        )

    self._submit_background_bundle_task(
        title=title,
        description=(
            "Preparing SoundCloud forensic upload copies, embedding SoundCloud trace metadata, hashing final files, and registering forensic export lineage..."
        ),
        task_fn=_worker,
        kind="write",
        unique_key="forensics.export_soundcloud_audio",
        cancellable=True,
        worker_completion_progress=(96, "Finalizing SoundCloud forensic export results..."),
        on_success_before_cleanup=_before_cleanup,
        on_success_after_cleanup=_success,
        on_cancelled=lambda: self.statusBar().showMessage(
            "SoundCloud forensic export cancelled.", 5000
        ),
        on_error=lambda failure: self._show_background_task_error(
            title,
            failure,
            user_message="Could not export SoundCloud forensic upload audio:",
        ),
    )


def inspect_forensic_watermark(self):
    title = "Inspect Forensic Watermark"
    if self.forensic_export_service is None:
        _message_box().warning(
            self,
            title,
            "Open a profile with forensic export services available first.",
        )
        return
    verification_path, _selected_filter = _file_dialog().getOpenFileName(
        self,
        "Choose Audio File to Inspect for Forensic Watermarking",
        "",
        "Audio Files (*.wav *.flac *.aif *.aiff *.mp3 *.ogg *.oga *.opus *.m4a *.mp4 *.aac);;All Files (*)",
    )
    if not verification_path:
        return

    def _worker(bundle, ctx):
        return bundle.forensic_export_service.inspect_file(
            verification_path,
            progress_callback=lambda value, maximum, message: ctx.report_progress(
                value=value,
                maximum=maximum,
                message=message,
            ),
            is_cancelled=ctx.is_cancelled,
        )

    def _success(report: ForensicInspectionReport):
        self._log_event(
            "forensics.inspect_audio",
            "Inspected audio for forensic watermarking",
            inspected_path=verification_path,
            status=report.status,
            forensic_export_id=report.forensic_export_id,
            batch_id=report.batch_id,
            track_id=report.track_id,
            resolution_basis=report.resolution_basis,
        )
        if ForensicInspectionDialog is not None:
            _root_attr("ForensicInspectionDialog", ForensicInspectionDialog)(
                report=report, parent=self
            ).exec()
        else:
            _message_box().information(
                self,
                title,
                f"{report.message}\n\nStatus: {report.status}\nPath: {report.inspected_path}",
            )

    self._submit_background_bundle_task(
        title=title,
        description=(
            "Inspecting the selected audio file, attempting forensic token extraction, and resolving any matches against the export ledger..."
        ),
        task_fn=_worker,
        kind="read",
        unique_key="forensics.inspect_audio",
        cancellable=True,
        on_success=_success,
        on_cancelled=lambda: self.statusBar().showMessage(
            "Forensic watermark inspection cancelled.", 5000
        ),
        on_error=lambda failure: self._show_background_task_error(
            title,
            failure,
            user_message="Could not inspect the selected file for forensic watermarking:",
        ),
    )

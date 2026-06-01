"""Audio authenticity and provenance workflow orchestration for the application shell."""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

from PySide6.QtWidgets import QDialog, QFileDialog, QMessageBox

from isrc_manager.authenticity import (
    AUTHENTICITY_FEATURE_AVAILABLE,
    VERIFICATION_INPUT_SUFFIXES,
    AuthenticityExportPreviewDialog,
    AuthenticityKeysDialog,
    AuthenticityVerificationDialog,
    authenticity_unavailable_message,
)


def _root_attr(name: str, fallback):
    main_window_module = sys.modules.get("isrc_manager.main_window")
    return (
        getattr(main_window_module, name, fallback) if main_window_module is not None else fallback
    )


def _message_box():
    return _root_attr("QMessageBox", QMessageBox)


def _file_dialog():
    return _root_attr("QFileDialog", QFileDialog)


def _default_authenticity_signer_label(self) -> str | None:
    record = self._current_owner_party_record()
    if record is None:
        return None
    return self._party_identity_primary_label(record)


def _authenticity_signer_party_choices(self) -> list[tuple[int, str]]:
    if self.party_service is None:
        return []
    choices: list[tuple[int, str]] = []
    for record in self.party_service.list_parties():
        choices.append((int(record.id), self._party_identity_primary_label(record)))
    return choices


def open_audio_authenticity_keys_dialog(self):
    if not AUTHENTICITY_FEATURE_AVAILABLE:
        _message_box().warning(
            self,
            "Audio Authenticity Keys",
            authenticity_unavailable_message(),
        )
        return
    if self.authenticity_key_service is None:
        _message_box().warning(self, "Audio Authenticity Keys", "Open a profile first.")
        return
    _root_attr("AuthenticityKeysDialog", AuthenticityKeysDialog)(
        key_service=self.authenticity_key_service,
        default_signer_label_provider=self._default_authenticity_signer_label,
        signer_party_choices_provider=self._authenticity_signer_party_choices,
        parent=self,
    ).exec()


def export_authenticity_watermarked_audio(self, track_ids: list[int] | None = None):
    title = "Export Authentic Masters"
    if not AUTHENTICITY_FEATURE_AVAILABLE:
        _message_box().warning(
            self,
            title,
            authenticity_unavailable_message(),
        )
        return
    if self.audio_authenticity_service is None:
        _message_box().warning(
            self,
            title,
            "Open a profile first.",
        )
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
        return bundle.audio_authenticity_service.build_export_plan(
            selected_ids,
            profile_name=self._current_profile_name(),
            progress_callback=lambda value, maximum, message: ctx.report_progress(
                value=value,
                maximum=maximum,
                message=message,
            ),
        )

    def _preview_success(plan):
        ready_items = plan.ready_items()
        if not ready_items:
            _message_box().information(
                self,
                title,
                "No supported WAV, FLAC, or AIFF master audio was available for the selected tracks."
                + ("\n\nWarnings:\n- " + "\n- ".join(plan.warnings[:12]) if plan.warnings else ""),
            )
            return
        preview_dialog = _root_attr(
            "AuthenticityExportPreviewDialog", AuthenticityExportPreviewDialog
        )(plan=plan, parent=self)
        if preview_dialog.exec() != QDialog.Accepted:
            return
        output_dir = _file_dialog().getExistingDirectory(
            self,
            "Choose Export Folder for Authentic Masters",
            str(self.exports_dir / "authenticity_audio"),
        )
        if not output_dir:
            return

        def _worker(bundle, ctx):
            export_progress = self._scaled_progress_callback(ctx.report_progress, start=0, end=96)
            return bundle.audio_authenticity_service.export_watermarked_audio(
                output_dir=output_dir,
                track_ids=[item.track_id for item in ready_items],
                key_id=plan.key_id,
                profile_name=self._current_profile_name(),
                progress_callback=export_progress,
                is_cancelled=ctx.is_cancelled,
            )

        def _before_cleanup(result, ui_progress) -> None:
            all_warnings = list(result.warnings)
            self._advance_task_ui_progress(
                ui_progress,
                value=97,
                message="Recording authentic master export results...",
            )
            self._log_event(
                "authenticity.export_audio",
                "Exported authenticity-watermarked audio",
                output_dir=output_dir,
                exported=result.exported,
                skipped=result.skipped,
                warnings=all_warnings,
            )
            self._audit(
                "EXPORT",
                "AudioAuthenticity",
                ref_id=output_dir,
                details=f"exported={result.exported}; skipped={result.skipped}",
            )
            self._audit_commit()

            self._advance_task_ui_progress(
                ui_progress,
                value=100,
                message="Authentic master export complete.",
            )

        def _success(result):
            all_warnings = list(result.warnings)
            _message_box().information(
                self,
                title,
                f"Exported {result.exported} watermark-authentic master cop{'y' if result.exported == 1 else 'ies'} to:\n{output_dir}"
                "\n\nThese are direct-watermark master exports, not managed lossy derivatives."
                f"\n\nSkipped: {result.skipped}"
                + ("\n\nWarnings:\n- " + "\n- ".join(all_warnings[:12]) if all_warnings else ""),
            )

        self._submit_background_bundle_task(
            title=title,
            description="Embedding direct watermarks and writing signed authenticity sidecars for master exports...",
            task_fn=_worker,
            kind="write",
            unique_key="authenticity.export_audio",
            cancellable=True,
            worker_completion_progress=(96, "Finalizing authentic master export results..."),
            on_success_before_cleanup=_before_cleanup,
            on_success_after_cleanup=_success,
            on_cancelled=lambda: self.statusBar().showMessage(
                "Authentic master export cancelled.", 5000
            ),
            on_error=lambda failure: self._show_background_task_error(
                title,
                failure,
                user_message="Could not export watermark-authentic masters:",
            ),
        )

    self._submit_background_bundle_task(
        title=title,
        description="Preparing the direct-watermark master export preview...",
        task_fn=_preview_worker,
        kind="read",
        unique_key="authenticity.export_audio.preview",
        on_success_after_cleanup=_preview_success,
        on_error=lambda failure: self._show_background_task_error(
            title,
            failure,
            user_message="Could not prepare the watermark-authentic master export preview:",
        ),
    )


def export_authenticity_provenance_audio(self, track_ids: list[int] | None = None):
    title = "Export Provenance Copies"
    if not AUTHENTICITY_FEATURE_AVAILABLE:
        _message_box().warning(
            self,
            title,
            authenticity_unavailable_message(),
        )
        return
    if self.audio_authenticity_service is None:
        _message_box().warning(
            self,
            title,
            "Open a profile first.",
        )
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
        return bundle.audio_authenticity_service.build_provenance_export_plan(
            selected_ids,
            profile_name=self._current_profile_name(),
            progress_callback=lambda value, maximum, message: ctx.report_progress(
                value=value,
                maximum=maximum,
                message=message,
            ),
        )

    def _preview_success(plan):
        ready_items = plan.ready_items()
        if not ready_items:
            _message_box().information(
                self,
                title,
                "No supported provenance-only attached audio was available for the selected tracks."
                + ("\n\nWarnings:\n- " + "\n- ".join(plan.warnings[:12]) if plan.warnings else ""),
            )
            return
        preview_dialog = _root_attr(
            "AuthenticityExportPreviewDialog", AuthenticityExportPreviewDialog
        )(
            plan=plan,
            title=title,
            subtitle=(
                "This workflow copies lossy audio as-is, writes catalog tags, and saves a signed lineage sidecar that points back to a verified watermark-authentic master. It does not create managed derivative records."
            ),
            parent=self,
        )
        if preview_dialog.exec() != QDialog.Accepted:
            return
        output_dir = _file_dialog().getExistingDirectory(
            self,
            "Choose Export Folder for Provenance Copies",
            str(self.exports_dir / "authenticity_lineage"),
        )
        if not output_dir:
            return

        def _worker(bundle, ctx):
            export_progress = self._scaled_progress_callback(ctx.report_progress, start=0, end=96)
            return bundle.audio_authenticity_service.export_provenance_audio(
                output_dir=output_dir,
                track_ids=[item.track_id for item in ready_items],
                key_id=plan.key_id,
                profile_name=self._current_profile_name(),
                progress_callback=export_progress,
                is_cancelled=ctx.is_cancelled,
            )

        def _before_cleanup(result, ui_progress) -> None:
            all_warnings = list(result.warnings)
            self._advance_task_ui_progress(
                ui_progress,
                value=97,
                message="Recording provenance export results...",
            )
            self._log_event(
                "authenticity.export_provenance_audio",
                "Exported authenticity provenance audio",
                output_dir=output_dir,
                exported=result.exported,
                skipped=result.skipped,
                warnings=all_warnings,
            )
            self._audit(
                "EXPORT",
                "AudioAuthenticityLineage",
                ref_id=output_dir,
                details=f"exported={result.exported}; skipped={result.skipped}",
            )
            self._audit_commit()

            self._advance_task_ui_progress(
                ui_progress,
                value=100,
                message="Provenance audio export complete.",
            )

        def _success(result):
            all_warnings = list(result.warnings)
            _message_box().information(
                self,
                title,
                f"Exported {result.exported} provenance-linked lossy cop{'y' if result.exported == 1 else 'ies'} to:\n{output_dir}"
                "\n\nThese copies keep signed lineage sidecars, but they are not managed derivatives."
                f"\n\nSkipped: {result.skipped}"
                + ("\n\nWarnings:\n- " + "\n- ".join(all_warnings[:12]) if all_warnings else ""),
            )

        self._submit_background_bundle_task(
            title=title,
            description="Writing lossy copies and signed provenance sidecars that point back to watermark-authentic masters...",
            task_fn=_worker,
            kind="write",
            unique_key="authenticity.export_provenance_audio",
            cancellable=True,
            worker_completion_progress=(96, "Finalizing provenance export results..."),
            on_success_before_cleanup=_before_cleanup,
            on_success_after_cleanup=_success,
            on_cancelled=lambda: self.statusBar().showMessage("Provenance export cancelled.", 5000),
            on_error=lambda failure: self._show_background_task_error(
                title,
                failure,
                user_message="Could not export provenance-linked lossy copies:",
            ),
        )

    self._submit_background_bundle_task(
        title=title,
        description="Preparing the provenance-linked lossy export preview...",
        task_fn=_preview_worker,
        kind="read",
        unique_key="authenticity.export_provenance_audio.preview",
        on_success_after_cleanup=_preview_success,
        on_error=lambda failure: self._show_background_task_error(
            title,
            failure,
            user_message="Could not prepare the provenance-linked lossy export preview:",
        ),
    )


def _selected_track_audio_verification_option(self):
    if self.track_service is None:
        return None
    selected_ids = self._normalize_track_ids(self._catalog_table_controller().selected_track_ids())
    if len(selected_ids) != 1:
        return None
    track_id = selected_ids[0]
    snapshot = self.track_service.fetch_track_snapshot(track_id)
    if snapshot is None or not self.track_service.has_media(track_id, "audio_file"):
        return None
    suffix = Path(snapshot.audio_file_filename or snapshot.audio_file_path or "").suffix.lower()
    if suffix not in VERIFICATION_INPUT_SUFFIXES:
        return None
    return int(track_id), str(snapshot.track_title or f"Track {track_id}")


def _selected_track_audio_verification_candidate(self, track_id: int | None = None):
    if self.track_service is None:
        return None, None
    if track_id is None:
        selected_option = self._selected_track_audio_verification_option()
        if selected_option is None:
            return None, None
        track_id = int(selected_option[0])
    snapshot = self.track_service.fetch_track_snapshot(track_id)
    if snapshot is None or not self.track_service.has_media(track_id, "audio_file"):
        return None, None
    suffix = Path(snapshot.audio_file_filename or snapshot.audio_file_path or "").suffix.lower()
    if suffix not in VERIFICATION_INPUT_SUFFIXES:
        return None, None
    resolved = self.track_service.resolve_media_path(snapshot.audio_file_path)
    if resolved is not None and resolved.exists():
        return resolved, None
    try:
        audio_bytes, _mime_type = self.track_service.fetch_media_bytes(track_id, "audio_file")
    except Exception:
        return None, None
    temp_root = Path(tempfile.mkdtemp(prefix="isrcm-auth-verify-"))
    temp_path = temp_root / (snapshot.audio_file_filename or f"track-{track_id}{suffix}")
    temp_path.write_bytes(audio_bytes)
    return temp_path, temp_root


def _prompt_audio_authenticity_verification_source(self, track_label: str) -> str | None:
    chooser = _message_box()(self)
    chooser.setWindowTitle("Verify Audio Authenticity")
    chooser.setIcon(_message_box().Question)
    chooser.setText("Choose which audio you want to verify.")
    chooser.setInformativeText(
        "Verify the selected catalog audio for "
        f"'{track_label}', or choose an external direct/provenance-supported file."
    )
    selected_button = chooser.addButton("Selected Track Audio", _message_box().AcceptRole)
    external_button = chooser.addButton("Choose External File…", _message_box().ActionRole)
    chooser.addButton("Cancel", _message_box().RejectRole)
    chooser.setDefaultButton(selected_button)
    chooser.exec()
    clicked = chooser.clickedButton()
    if clicked is selected_button:
        return "selected"
    if clicked is external_button:
        return "external"
    return None


def _pick_audio_authenticity_verification_file(self) -> Path | None:
    chosen_path, _selected_filter = _file_dialog().getOpenFileName(
        self,
        "Choose Audio File to Verify",
        "",
        "Audio Files (*.wav *.flac *.aif *.aiff *.mp3 *.ogg *.oga *.opus *.m4a *.mp4 *.aac);;All Files (*)",
    )
    if not chosen_path:
        return None
    return Path(chosen_path).resolve()


def verify_audio_authenticity(self, path: str | None = None):
    if not AUTHENTICITY_FEATURE_AVAILABLE:
        _message_box().warning(
            self,
            "Verify Audio Authenticity",
            authenticity_unavailable_message(),
        )
        return
    if self.audio_authenticity_service is None:
        _message_box().warning(self, "Verify Audio Authenticity", "Open a profile first.")
        return
    verification_path = Path(path).resolve() if path else None
    cleanup_root = None
    if verification_path is None:
        selected_option = self._selected_track_audio_verification_option()
        if selected_option is not None:
            selected_track_id, selected_track_label = selected_option
            choice = self._prompt_audio_authenticity_verification_source(selected_track_label)
            if choice is None:
                return
            if choice == "selected":
                verification_path, cleanup_root = self._selected_track_audio_verification_candidate(
                    selected_track_id
                )
                if verification_path is None:
                    _message_box().warning(
                        self,
                        "Verify Audio Authenticity",
                        "The selected track no longer has a supported direct or provenance audio file. Choose an external file instead.",
                    )
                    verification_path = self._pick_audio_authenticity_verification_file()
            else:
                verification_path = self._pick_audio_authenticity_verification_file()
        else:
            verification_path = self._pick_audio_authenticity_verification_file()
    if verification_path is None:
        return

    def _worker(bundle, _ctx):
        return bundle.audio_authenticity_service.verify_file(verification_path)

    def _finished():
        if cleanup_root is not None:
            shutil.rmtree(cleanup_root, ignore_errors=True)

    def _success(report):
        self._log_event(
            "authenticity.verify_audio",
            "Verified audio authenticity",
            path=str(verification_path),
            status=report.status,
            manifest_id=report.manifest_id,
            key_id=report.key_id,
        )
        self._audit(
            "VERIFY",
            "AudioAuthenticity",
            ref_id=str(verification_path),
            details=report.status,
        )
        self._audit_commit()
        _root_attr("AuthenticityVerificationDialog", AuthenticityVerificationDialog)(
            report=report, parent=self
        ).exec()

    self._submit_background_bundle_task(
        title="Verify Audio Authenticity",
        description="Verifying the direct watermark path or signed provenance lineage...",
        task_fn=_worker,
        kind="read",
        unique_key="authenticity.verify_audio",
        on_success=_success,
        on_finished=_finished,
        on_error=lambda failure: self._show_background_task_error(
            "Verify Audio Authenticity",
            failure,
            user_message="Could not verify audio authenticity:",
        ),
    )

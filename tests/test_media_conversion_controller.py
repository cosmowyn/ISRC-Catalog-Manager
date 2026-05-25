from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from isrc_manager.file_storage import STORAGE_MODE_DATABASE, STORAGE_MODE_MANAGED_FILE
from isrc_manager.media import conversion_controller as conversion


class _Action:
    def __init__(self):
        self.enabled = None
        self.status_tip = ""
        self.tool_tip = ""

    def setEnabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled)

    def setStatusTip(self, text: str) -> None:
        self.status_tip = text

    def setToolTip(self, text: str) -> None:
        self.tool_tip = text


class _StatusBar:
    def __init__(self):
        self.messages: list[tuple[str, int]] = []

    def showMessage(self, text: str, timeout: int) -> None:
        self.messages.append((text, timeout))


def _profile(profile_id: str, label: str | None = None):
    return SimpleNamespace(id=profile_id, label=label or profile_id.upper())


def test_refresh_audio_conversion_action_states_sets_tooltips_and_foreground_services(monkeypatch):
    configured = []
    capabilities = SimpleNamespace(
        managed_targets=(_profile("flac", "FLAC"),),
        managed_lossy_targets=(_profile("mp3", "MP3"),),
        managed_forensic_targets=(_profile("mp3-forensic", "MP3 Forensic"),),
        external_targets=(_profile("wav", "WAV"),),
    )
    app = SimpleNamespace(
        audio_conversion_service=SimpleNamespace(
            is_available=mock.Mock(return_value=True),
            capabilities=mock.Mock(return_value=capabilities),
        ),
        track_service=object(),
        audio_authenticity_service=object(),
        forensic_export_service=object(),
        convert_selected_audio_action=_Action(),
        convert_external_audio_files_action=_Action(),
        export_forensic_watermarked_audio_action=_Action(),
        inspect_forensic_watermark_action=_Action(),
    )
    monkeypatch.setattr(
        conversion,
        "configure_foreground_exchange_services",
        lambda shell: configured.append(shell),
    )

    conversion._refresh_audio_conversion_action_states(app)

    assert app.convert_selected_audio_action.enabled is True
    assert "watermark-authentic path" in app.convert_selected_audio_action.status_tip
    assert app.convert_external_audio_files_action.enabled is True
    assert "Utility conversion only" in app.convert_external_audio_files_action.tool_tip
    assert app.export_forensic_watermarked_audio_action.enabled is True
    assert "leak tracing" in app.export_forensic_watermarked_audio_action.status_tip
    assert app.inspect_forensic_watermark_action.enabled is True
    assert configured == [app]

    unavailable = SimpleNamespace(
        audio_conversion_service=None,
        track_service=None,
        audio_authenticity_service=None,
        forensic_export_service=None,
        convert_selected_audio_action=_Action(),
        convert_external_audio_files_action=_Action(),
        export_forensic_watermarked_audio_action=_Action(),
        inspect_forensic_watermark_action=_Action(),
        _audio_conversion_unavailable_message=lambda: "ffmpeg is missing",
    )
    conversion._refresh_audio_conversion_action_states(unavailable)
    assert unavailable.convert_selected_audio_action.enabled is False
    assert unavailable.convert_selected_audio_action.status_tip == "ffmpeg is missing"
    assert unavailable.inspect_forensic_watermark_action.enabled is False


def test_audio_source_label_suffix_and_unavailable_message_helpers():
    app = SimpleNamespace(
        audio_conversion_service=None,
        track_service=None,
        _export_extension_for_mime=mock.Mock(return_value=".wav"),
    )
    snapshot = SimpleNamespace(
        audio_file_filename="master.flac",
        audio_file_mime_type="audio/flac",
        audio_file_storage_mode=STORAGE_MODE_MANAGED_FILE,
        audio_file_blob_b64="",
    )

    assert conversion._audio_export_source_suffix(app, snapshot) == ".flac"
    assert conversion._audio_export_source_label(snapshot) == "master.flac"
    assert "requires ffmpeg" in conversion._audio_conversion_unavailable_message(app)

    blob_snapshot = SimpleNamespace(
        audio_file_filename="database.wav",
        audio_file_mime_type="audio/wav",
        audio_file_storage_mode=STORAGE_MODE_DATABASE,
        audio_file_blob_b64="abc",
    )
    assert (
        conversion._audio_export_source_label(blob_snapshot) == "database.wav (stored in database)"
    )

    no_filename = SimpleNamespace(
        audio_file_filename="",
        audio_file_mime_type="audio/wav",
        audio_file_storage_mode=STORAGE_MODE_DATABASE,
        audio_file_blob_b64="abc",
    )
    assert conversion._audio_export_source_label(no_filename) == "Stored in database"
    assert conversion._audio_export_source_suffix(app, no_filename) == ".wav"
    app.audio_conversion_service = SimpleNamespace(is_available=mock.Mock(return_value=True))
    assert (
        conversion._audio_conversion_unavailable_message(app)
        == "Managed audio derivative export requires an open profile."
    )
    app.track_service = object()
    assert conversion._audio_conversion_unavailable_message(app) == ""


def test_prompt_audio_conversion_format_merges_managed_targets_without_duplicates(monkeypatch):
    chosen = []
    capabilities = SimpleNamespace(
        managed_targets=(_profile("flac", "FLAC"), _profile("wav", "WAV")),
        managed_lossy_targets=(_profile("mp3", "MP3"), _profile("flac", "FLAC duplicate")),
        managed_forensic_targets=(_profile("forensic", "Forensic"),),
        external_targets=(_profile("aac", "AAC"),),
    )
    app = SimpleNamespace(
        audio_conversion_service=SimpleNamespace(capabilities=mock.Mock(return_value=capabilities))
    )

    def fake_choice_dialog(*args, **kwargs):
        chosen.append(kwargs)
        return "mp3"

    monkeypatch.setattr(conversion, "_compact_choice_dialog", fake_choice_dialog)

    assert (
        conversion._prompt_audio_conversion_format(
            app,
            title="Export",
            prompt="Choose",
            capability_group="managed_any",
        )
        == "mp3"
    )
    assert chosen[0]["choices"] == [("flac", "FLAC"), ("wav", "WAV"), ("mp3", "MP3")]

    capabilities.external_targets = ()
    assert (
        conversion._prompt_audio_conversion_format(
            app,
            title="External",
            prompt="Choose",
            capability_group="external",
        )
        is None
    )


def test_start_conversion_export_uses_direct_worker_and_reports_success(monkeypatch, tmp_path):
    submitted = {}
    messages = []
    template_path = tmp_path / "template.xlsx"
    template_path.write_bytes(b"template")
    output_path = tmp_path / "output"
    resolved_path = output_path.with_suffix(".csv")
    preview = SimpleNamespace(
        template_profile=SimpleNamespace(
            format_name="csv",
            output_suffix=".csv",
            template_bytes=b"compiled-template",
            template_path=template_path,
        ),
        source_profile=SimpleNamespace(source_mode="catalog"),
    )
    result = SimpleNamespace(
        target_format="csv",
        exported_row_count=12,
        summary_lines=["Skipped 1 optional field"],
    )
    conversion_service = mock.Mock()
    conversion_service.export_preview.return_value = result
    app = SimpleNamespace(
        history_manager=None,
        current_db_path="",
        background_service_factory=None,
        conversion_service=conversion_service,
        conn=object(),
        logger=mock.Mock(),
        _resolve_file_export_target=lambda path, **kwargs: Path(path),
        _scaled_progress_callback=lambda callback, **kwargs: "progress",
        _submit_background_task=lambda **kwargs: submitted.update(kwargs),
        _show_background_task_error=mock.Mock(),
        _refresh_history_actions=mock.Mock(),
        _log_event=mock.Mock(),
        _audit=mock.Mock(),
        _audit_commit=mock.Mock(),
    )

    class FakeMessageBox:
        @classmethod
        def information(cls, *args):
            messages.append(args)

        @classmethod
        def warning(cls, *args):
            messages.append(args)

    monkeypatch.setattr(conversion, "_message_box", lambda: FakeMessageBox)

    conversion._start_conversion_export(app, preview, output_path)

    ctx = SimpleNamespace(report_progress=mock.Mock())
    assert submitted["task_fn"](ctx) is result
    conversion_service.export_preview.assert_called_once_with(
        preview,
        resolved_path,
        progress_callback="progress",
    )
    submitted["on_success_after_cleanup"](result)
    app._log_event.assert_called_once()
    app._audit.assert_called_once()
    app._audit_commit.assert_called_once()
    assert "Rows written: 12" in messages[-1][2]


def test_start_conversion_export_rejects_source_template_overwrite(monkeypatch, tmp_path):
    messages = []
    template_path = tmp_path / "template.csv"
    template_path.write_text("source", encoding="utf-8")
    preview = SimpleNamespace(
        template_profile=SimpleNamespace(
            format_name="csv",
            output_suffix=".csv",
            template_bytes=None,
            template_path=template_path,
        ),
        source_profile=SimpleNamespace(source_mode="catalog"),
    )
    app = SimpleNamespace(
        _resolve_file_export_target=lambda path, **kwargs: Path(path),
    )

    class FakeMessageBox:
        @classmethod
        def warning(cls, *args):
            messages.append(args)

    monkeypatch.setattr(conversion, "_message_box", lambda: FakeMessageBox)

    conversion._start_conversion_export(app, preview, template_path)

    assert "never overwrites the source template" in messages[0][2]


def test_convert_external_audio_files_deduplicates_inputs_and_runs_worker(monkeypatch, tmp_path):
    submitted = {}
    messages = []
    coordinator_requests = []
    input_one = tmp_path / "one.wav"
    input_two = tmp_path / "two.wav"
    output_dir = tmp_path / "converted"
    result = SimpleNamespace(
        exported=2,
        skipped=1,
        batch_public_id="external-batch",
        zip_path=str(output_dir / "converted.zip"),
        written_paths=[str(output_dir / "one.mp3")],
        warnings=["one skipped"],
    )

    class FakeCoordinator:
        def __init__(self, *, conversion_service):
            self.conversion_service = conversion_service

        def export(self, request, *, progress_callback, is_cancelled):
            coordinator_requests.append((request, progress_callback, is_cancelled))
            return result

    class FakeFileDialog:
        @classmethod
        def getOpenFileNames(cls, *args):
            return ([str(input_one), str(input_two), str(input_one), ""], "")

        @classmethod
        def getExistingDirectory(cls, *args):
            return str(output_dir)

    class FakeMessageBox:
        @classmethod
        def information(cls, *args):
            messages.append(args)

        @classmethod
        def warning(cls, *args):
            messages.append(args)

    app = SimpleNamespace(
        audio_conversion_service=SimpleNamespace(is_available=mock.Mock(return_value=True)),
        exports_dir=tmp_path,
        _prompt_audio_conversion_format=mock.Mock(return_value="mp3"),
        _scaled_progress_callback=lambda callback, **kwargs: "external-progress",
        _submit_background_task=lambda **kwargs: submitted.update(kwargs),
        _advance_task_ui_progress=mock.Mock(),
        _log_event=mock.Mock(),
        _show_background_task_error=mock.Mock(),
        statusBar=lambda: _StatusBar(),
    )
    monkeypatch.setattr(conversion, "ExternalAudioConversionCoordinator", FakeCoordinator)
    monkeypatch.setattr(conversion, "_file_dialog", lambda: FakeFileDialog)
    monkeypatch.setattr(conversion, "_message_box", lambda: FakeMessageBox)

    conversion.convert_external_audio_files(app)

    ctx = SimpleNamespace(report_progress=mock.Mock(), is_cancelled=mock.Mock(return_value=False))
    assert submitted["task_fn"](ctx) is result
    request, progress_callback, is_cancelled = coordinator_requests[0]
    assert request.input_paths == [str(input_one), str(input_two)]
    assert request.output_dir == str(output_dir)
    assert request.output_format == "mp3"
    assert progress_callback == "external-progress"
    assert is_cancelled is ctx.is_cancelled

    submitted["on_success_before_cleanup"](result, "ui-progress")
    submitted["on_success_after_cleanup"](result)
    app._advance_task_ui_progress.assert_any_call(
        "ui-progress",
        value=97,
        message="Recording external audio conversion results...",
    )
    app._log_event.assert_called_once()
    assert "Converted 2 external audio files" in messages[-1][2]


def test_convert_selected_audio_runs_managed_lossy_export_worker(monkeypatch, tmp_path):
    submitted = {}
    messages = []
    coordinator_requests = []
    output_dir = tmp_path / "managed"
    result = SimpleNamespace(
        derivative_kind="lossy_derivative",
        authenticity_basis="none",
        exported=3,
        skipped=1,
        batch_public_id="managed-batch",
        zip_path="",
        written_paths=[str(output_dir / "one.mp3")],
        warnings=["low bitrate"],
        watermark_applied=False,
    )

    class FakeCoordinator:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def export(self, request, *, progress_callback, is_cancelled):
            coordinator_requests.append((request, progress_callback, is_cancelled))
            return result

    class FakeFileDialog:
        @classmethod
        def getExistingDirectory(cls, *args):
            return str(output_dir)

    class FakeMessageBox:
        @classmethod
        def information(cls, *args):
            messages.append(args)

        @classmethod
        def warning(cls, *args):
            messages.append(args)

    app = SimpleNamespace(
        track_service=object(),
        audio_conversion_service=SimpleNamespace(is_supported_target=mock.Mock(return_value=False)),
        audio_authenticity_service=None,
        release_service=object(),
        audio_tag_service=object(),
        conn=object(),
        exports_dir=tmp_path,
        _audio_conversion_unavailable_message=mock.Mock(return_value=""),
        _selected_track_ids_with_audio=mock.Mock(return_value=[1, 2, 3]),
        _prompt_audio_conversion_format=mock.Mock(return_value="mp3"),
        _scaled_progress_callback=lambda callback, **kwargs: "managed-progress",
        _current_profile_name=mock.Mock(return_value="Profile"),
        _submit_background_bundle_task=lambda **kwargs: submitted.update(kwargs),
        _advance_task_ui_progress=mock.Mock(),
        _log_event=mock.Mock(),
        _audit=mock.Mock(),
        _audit_commit=mock.Mock(),
        _show_background_task_error=mock.Mock(),
        statusBar=lambda: _StatusBar(),
    )
    monkeypatch.setattr(conversion, "ManagedDerivativeExportCoordinator", FakeCoordinator)
    monkeypatch.setattr(conversion, "_file_dialog", lambda: FakeFileDialog)
    monkeypatch.setattr(conversion, "_message_box", lambda: FakeMessageBox)

    conversion.convert_selected_audio(app)

    bundle = SimpleNamespace(
        conn=app.conn,
        track_service=app.track_service,
        release_service=app.release_service,
        audio_tag_service=app.audio_tag_service,
        audio_authenticity_service=app.audio_authenticity_service,
    )
    ctx = SimpleNamespace(report_progress=mock.Mock(), is_cancelled=mock.Mock(return_value=False))
    assert submitted["task_fn"](bundle, ctx) is result
    request, progress_callback, is_cancelled = coordinator_requests[0]
    assert request.track_ids == [1, 2, 3]
    assert request.output_dir == str(output_dir)
    assert request.output_format == "mp3"
    assert request.derivative_kind == conversion.MANAGED_DERIVATIVE_KIND_LOSSY
    assert progress_callback == "managed-progress"
    assert is_cancelled is ctx.is_cancelled

    submitted["on_success_before_cleanup"](result, "ui-progress")
    submitted["on_success_after_cleanup"](result)
    app._log_event.assert_called_once()
    app._audit.assert_called_once()
    app._audit_commit.assert_called_once()
    assert "managed lossy derivatives" in messages[-1][2]


def test_convert_selected_audio_reports_early_blockers(monkeypatch):
    messages = []

    class FakeMessageBox:
        @classmethod
        def warning(cls, *args):
            messages.append(("warning", args))

        @classmethod
        def information(cls, *args):
            messages.append(("information", args))

    monkeypatch.setattr(conversion, "_message_box", lambda: FakeMessageBox)

    conversion.convert_selected_audio(SimpleNamespace(track_service=None))
    assert messages[-1][0] == "warning"

    app = SimpleNamespace(
        track_service=object(),
        _audio_conversion_unavailable_message=mock.Mock(return_value="ffmpeg missing"),
    )
    conversion.convert_selected_audio(app)
    assert "ffmpeg missing" in messages[-1][1][2]

    app._audio_conversion_unavailable_message.return_value = ""
    app._selected_track_ids_with_audio = mock.Mock(return_value=[])
    conversion.convert_selected_audio(app)
    assert messages[-1][0] == "information"

    app._selected_track_ids_with_audio.return_value = [1]
    app._prompt_audio_conversion_format = mock.Mock(return_value="flac")
    app.audio_conversion_service = SimpleNamespace(is_supported_target=mock.Mock(return_value=True))
    app.audio_authenticity_service = None
    conversion.convert_selected_audio(app)
    assert "Lossless managed exports require" in messages[-1][1][2]

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from isrc_manager.file_storage import STORAGE_MODE_DATABASE
from isrc_manager.media import export_controller
from isrc_manager.tags.models import (
    AudioTagData,
    TaggedAudioExportPlanItem,
    TaggedAudioExportResult,
)


class _TrackService:
    def __init__(
        self,
        snapshots: dict[int, SimpleNamespace | None],
        *,
        media_bytes: dict[int, bytes] | None = None,
        byte_failures: set[int] | None = None,
    ) -> None:
        self.snapshots = snapshots
        self.media_bytes = media_bytes or {}
        self.byte_failures = byte_failures or set()
        self.snapshot_calls: list[tuple[int, bool]] = []
        self.byte_calls: list[tuple[int, str]] = []

    def fetch_track_snapshot(self, track_id: int, *, include_media_blobs: bool):
        self.snapshot_calls.append((track_id, include_media_blobs))
        return self.snapshots.get(track_id)

    def resolve_media_path(self, value: str | None):
        return Path(value) if value else None

    def fetch_media_bytes(self, track_id: int, media_key: str):
        self.byte_calls.append((track_id, media_key))
        if track_id in self.byte_failures:
            raise FileNotFoundError("missing media")
        return self.media_bytes[track_id], "audio/wav"


class _Harness:
    def __init__(self, track_service: _TrackService | None = None) -> None:
        self.track_service = track_service
        self.release_service = object()
        self.tag_calls: list[tuple[int, bool]] = []

    def _iter_audio_tag_preview_fields(self, tag_data: AudioTagData):
        return export_controller._iter_audio_tag_preview_fields(tag_data)

    def _display_tag_value(self, value: object) -> str:
        return f"display:{value}"

    def _normalize_track_ids(self, track_ids):
        return [int(track_id) for track_id in track_ids if track_id]

    def _audio_export_source_suffix(self, snapshot: SimpleNamespace) -> str:
        path = str(snapshot.audio_file_path or "")
        return Path(path).suffix or ".wav"

    def _audio_export_source_label(self, snapshot: SimpleNamespace) -> str:
        return f"database:{snapshot.track_title}"

    def _catalog_tag_data_for_track(
        self,
        track_id: int,
        *,
        snapshot: SimpleNamespace,
        track_service: _TrackService,
        release_service: object,
        include_artwork_bytes: bool,
    ) -> AudioTagData:
        assert track_service is self.track_service
        assert release_service is self.release_service
        self.tag_calls.append((track_id, include_artwork_bytes))
        return AudioTagData(
            title=snapshot.track_title,
            artist="Catalog Artist",
            album=snapshot.album_title,
            track_number=track_id,
        )

    def _build_tagged_audio_export_preview_rows(
        self,
        *,
        track_title: str,
        source_label: str,
        tag_data: AudioTagData,
    ):
        return export_controller._build_tagged_audio_export_preview_rows(
            self,
            track_title=track_title,
            source_label=source_label,
            tag_data=tag_data,
        )

    def _tagged_audio_export_name(self, track_id: int, track_title: str | None) -> str:
        return export_controller._tagged_audio_export_name(track_id, track_title)


def _snapshot(
    title: str,
    *,
    album: str = "",
    path: str | None = None,
    storage_mode: str = "",
) -> SimpleNamespace:
    return SimpleNamespace(
        track_title=title,
        album_title=album,
        audio_file_path=path,
        audio_file_storage_mode=storage_mode,
    )


def _install_export_dialog_fakes(
    monkeypatch: pytest.MonkeyPatch,
    *,
    save_path: str = "",
    directory: str = "",
):
    class _Messages:
        def __init__(self) -> None:
            self.information_calls: list[tuple[str, str]] = []
            self.warning_calls: list[tuple[str, str]] = []
            self.critical_calls: list[tuple[str, str]] = []

        def information(self, _parent, title: str, message: str) -> None:
            self.information_calls.append((title, message))

        def warning(self, _parent, title: str, message: str) -> None:
            self.warning_calls.append((title, message))

        def critical(self, _parent, title: str, message: str) -> None:
            self.critical_calls.append((title, message))

    class _FileDialog:
        def __init__(self) -> None:
            self.save_path = save_path
            self.directory = directory
            self.save_calls: list[tuple[str, str]] = []
            self.directory_calls: list[str] = []

        def getSaveFileName(self, _parent, title: str, default: str, _filter: str):
            self.save_calls.append((title, default))
            return self.save_path, ""

        def getExistingDirectory(self, _parent, title: str, *_args):
            self.directory_calls.append(title)
            return self.directory

    messages = _Messages()
    file_dialog = _FileDialog()
    monkeypatch.setattr(export_controller, "_message_box", lambda: messages)
    monkeypatch.setattr(export_controller, "_file_dialog", lambda: file_dialog)
    return messages, file_dialog


def _export_app() -> SimpleNamespace:
    app = SimpleNamespace(
        errors=[],
        history_refreshes=0,
        logger=SimpleNamespace(
            exception=lambda *_args, **_kwargs: None,
            warning=lambda *_args, **_kwargs: None,
        ),
        status_messages=[],
    )
    app._coerce_export_bytes = export_controller._coerce_export_bytes
    app._deduplicate_export_destination = export_controller._deduplicate_export_destination
    app._export_extension_for_mime = export_controller._export_extension_for_mime
    app._default_export_filename = (
        lambda basename, mime: export_controller._default_export_filename(
            app,
            basename,
            mime,
        )
    )
    app._resolve_file_export_target = export_controller._resolve_file_export_target
    app._submit_background_bundle_task = lambda **kwargs: app.submitted_tasks.append(kwargs)
    app._refresh_history_actions = lambda: setattr(
        app,
        "history_refreshes",
        app.history_refreshes + 1,
    )
    app._show_background_task_error = lambda title, failure, **kwargs: app.errors.append(
        (title, failure, kwargs)
    )
    app.statusBar = lambda: SimpleNamespace(
        showMessage=lambda message, timeout=0: app.status_messages.append((message, timeout))
    )
    app.submitted_tasks = []
    return app


class _ExportContext:
    def __init__(self, *, cancelled: bool = False) -> None:
        self.cancelled = cancelled
        self.progress: list[tuple[int, int, str]] = []

    def report_progress(self, *, value: int, maximum: int, message: str) -> None:
        self.progress.append((value, maximum, message))

    def is_cancelled(self) -> bool:
        return self.cancelled


def test_tag_preview_rows_skip_empty_fields_and_preserve_source() -> None:
    harness = _Harness()
    tag_data = AudioTagData(
        title="Song",
        artist="Artist",
        album="",
        comments=None,
        track_number=3,
        warnings=["ignored"],
        raw_fields={"ignored": True},
    )

    fields = export_controller._iter_audio_tag_preview_fields(tag_data)
    rows = export_controller._build_tagged_audio_export_preview_rows(
        harness,
        track_title="Song",
        source_label="source.wav",
        tag_data=tag_data,
    )

    assert "raw_fields" not in {name for name, _value in fields}
    assert "warnings" not in {name for name, _value in fields}
    assert rows == [
        {
            "track": "Song",
            "field": "Title",
            "database": "display:Song",
            "file": "",
            "chosen": "display:Song",
            "source": "source.wav",
        },
        {
            "track": "Song",
            "field": "Artist",
            "database": "display:Artist",
            "file": "",
            "chosen": "display:Artist",
            "source": "source.wav",
        },
        {
            "track": "Song",
            "field": "Track Number",
            "database": "display:3",
            "file": "",
            "chosen": "display:3",
            "source": "source.wav",
        },
    ]


@pytest.mark.parametrize(
    ("track_id", "title", "expected"),
    [
        (7, "Clean Title", "Clean Title"),
        (8, "bad/name:demo", "bad_name_demo"),
        (9, None, "track_9"),
    ],
)
def test_tagged_audio_export_name_uses_safe_track_stems(
    track_id: int,
    title: str | None,
    expected: str,
) -> None:
    assert export_controller._tagged_audio_export_name(track_id, title) == expected


def test_root_hooks_and_export_filename_destination_helpers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root_history_calls = []
    root_module = SimpleNamespace(
        QMessageBox="root-message-box",
        QFileDialog="root-file-dialog",
        run_file_history_action=lambda *args, **kwargs: root_history_calls.append((args, kwargs))
        or "history-result",
    )
    monkeypatch.setitem(sys.modules, "isrc_manager.main_window", root_module)

    assert export_controller._message_box() == "root-message-box"
    assert export_controller._file_dialog() == "root-file-dialog"
    assert export_controller._run_file_history_action("arg", key="value") == "history-result"
    assert root_history_calls == [(("arg",), {"key": "value"})]

    monkeypatch.setattr(export_controller.mimetypes, "guess_extension", lambda _mime: ".jpe")
    assert export_controller._export_extension_for_mime("image/jpeg") == ".jpg"
    monkeypatch.setattr(export_controller.mimetypes, "guess_extension", lambda _mime: None)
    assert export_controller._export_extension_for_mime("image/custom") == ".png"
    assert export_controller._export_extension_for_mime("audio/custom") == ".wav"
    assert export_controller._export_extension_for_mime("application/custom") == ".bin"

    app = SimpleNamespace(_export_extension_for_mime=export_controller._export_extension_for_mime)
    assert export_controller._default_export_filename(app, "bad/name", "audio/custom") == (
        "bad_name.wav"
    )
    assert (
        export_controller._resolve_directory_export_target(
            tmp_path / "folder",
            default_name="fallback",
        )
        == tmp_path / "folder"
    )

    (tmp_path / "song.wav").write_bytes(b"one")
    (tmp_path / "song (2).wav").write_bytes(b"two")
    assert export_controller._deduplicate_export_destination(tmp_path, "song.wav") == (
        tmp_path / "song (3).wav"
    )


def test_prepare_tagged_audio_export_preview_collects_rows_and_warnings(tmp_path: Path) -> None:
    source = tmp_path / "song.wav"
    source.write_bytes(b"audio")
    track_service = _TrackService(
        {
            1: _snapshot("File Song", album="Album A", path=str(source)),
            2: _snapshot(
                "Database Song",
                album="Album B",
                path=str(tmp_path / "missing.wav"),
                storage_mode=STORAGE_MODE_DATABASE,
            ),
            3: None,
            4: _snapshot("Detached Song", path=str(tmp_path / "detached.wav")),
        }
    )
    harness = _Harness(track_service)
    progress: list[tuple[int, int, str]] = []

    result = export_controller._prepare_tagged_audio_export_preview(
        harness,
        [1, 2, 3, 4],
        progress_callback=lambda *args: progress.append(args),
    )

    prepared = result["prepared"]
    assert [(item.track_id, item.source_label) for item in prepared] == [
        (1, str(source)),
        (2, "database:Database Song"),
    ]
    assert [item.album_title for item in prepared] == ["Album A", "Album B"]
    assert result["warnings"] == [
        "Track 3 could not be loaded.",
        "Detached Song: no exportable audio file is attached.",
    ]
    assert {row["track"] for row in result["rows"]} == {"File Song", "Database Song"}
    assert harness.tag_calls == [(1, False), (2, False)]
    assert progress[0][:2] == (0, 4)
    assert progress[-1] == (4, 4, "Catalog audio copy export preview ready.")
    assert track_service.snapshot_calls == [(1, False), (2, False), (3, False), (4, False)]


def test_prepare_tagged_audio_export_preview_requires_track_service() -> None:
    with pytest.raises(ValueError, match="Track service is not available"):
        export_controller._prepare_tagged_audio_export_preview(_Harness(None), [1])


def test_build_tagged_audio_export_items_uses_file_and_database_sources(tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    source.write_bytes(b"audio")
    track_service = _TrackService(
        {
            1: _snapshot("File Song", album="Album A", path=str(source)),
            2: _snapshot("Database Song", album="Album B", storage_mode=STORAGE_MODE_DATABASE),
            3: None,
            4: _snapshot("Missing Bytes", storage_mode=STORAGE_MODE_DATABASE),
        },
        media_bytes={2: b"database-audio"},
        byte_failures={4},
    )
    harness = _Harness(track_service)
    plan_items = [
        TaggedAudioExportPlanItem(1, "File Song", "file-song", ".wav", str(source), "Album A"),
        TaggedAudioExportPlanItem(
            2, "Database Song", "database-song", ".mp3", "database", "Album B"
        ),
        TaggedAudioExportPlanItem(3, "Missing", "missing", ".wav", "missing", None),
        TaggedAudioExportPlanItem(4, "Missing Bytes", "missing-bytes", ".wav", "database", None),
    ]
    progress: list[tuple[int, int, str]] = []

    exports, warnings = export_controller._build_tagged_audio_export_items(
        harness,
        plan_items,
        progress_callback=lambda *args: progress.append(args),
        is_cancelled=lambda: False,
    )

    assert len(exports) == 2
    assert exports[0].source_path == source
    assert exports[0].source_bytes is None
    assert exports[0].tag_data.title == "File Song"
    assert exports[1].source_path is None
    assert exports[1].source_bytes == b"database-audio"
    assert exports[1].album_title == "Album B"
    assert warnings == [
        "Track 3 could not be loaded.",
        "Missing Bytes: no exportable audio file is attached.",
    ]
    assert harness.tag_calls == [(1, True), (2, True), (4, True)]
    assert track_service.byte_calls == [(2, "audio_file"), (4, "audio_file")]
    assert progress[-1] == (4, 4, "Catalog audio copy export sources are ready.")


def test_build_tagged_audio_export_items_can_cancel_before_io(tmp_path: Path) -> None:
    track_service = _TrackService({1: _snapshot("Song", path=str(tmp_path / "song.wav"))})
    harness = _Harness(track_service)
    plan_items = [TaggedAudioExportPlanItem(1, "Song", "song", ".wav", "source", None)]

    with pytest.raises(InterruptedError, match="cancelled"):
        export_controller._build_tagged_audio_export_items(
            harness,
            plan_items,
            is_cancelled=lambda: True,
        )

    assert track_service.snapshot_calls == []


def test_export_bytes_with_picker_handles_cancel_validation_success_and_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    messages, file_dialog = _install_export_dialog_fakes(monkeypatch)
    app = _export_app()
    app._attempt_catalog_audio_export_metadata = lambda _path, *, track_id: "tag service offline"
    history_actions: list[dict[str, object]] = []

    def run_history_action(**kwargs):
        history_actions.append(kwargs)
        return kwargs["mutation"]()

    setattr(app, "__run_file_history_action", run_history_action)

    export_controller._export_bytes_with_picker(
        app,
        b"audio",
        mime="audio/wav",
        suggested_basename="Demo Song",
        action_label="Export: {filename}",
        action_type="file.export",
    )
    assert messages.information_calls == []
    assert history_actions == []

    file_dialog.save_path = str(tmp_path / "bad-target")
    app._resolve_file_export_target = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        ValueError("unsafe export target")
    )
    export_controller._export_bytes_with_picker(
        app,
        b"audio",
        mime="audio/wav",
        suggested_basename="Demo Song",
        action_label="Export: {filename}",
        action_type="file.export",
    )
    assert messages.warning_calls[-1] == ("Export", "unsafe export target")

    dest = tmp_path / "nested" / "song.wav"
    file_dialog.save_path = str(dest)
    app._resolve_file_export_target = export_controller._resolve_file_export_target
    export_controller._export_bytes_with_picker(
        app,
        bytearray(b"audio"),
        mime="audio/wav",
        suggested_basename="Demo Song",
        catalog_track_id=17,
        action_label="Export: {filename}",
        action_type="file.export",
        entity_type="Track",
        entity_id="17",
        payload={"track_id": 17},
    )
    assert dest.read_bytes() == b"audio"
    assert history_actions[-1]["action_label"] == "Export: song.wav"
    assert "Metadata embedding skipped: tag service offline." in messages.information_calls[-1][1]

    def failing_history_action(**_kwargs):
        raise RuntimeError("disk full")

    setattr(app, "__run_file_history_action", failing_history_action)
    file_dialog.save_path = str(tmp_path / "failure.wav")
    export_controller._export_bytes_with_picker(
        app,
        memoryview(b"audio"),
        mime="audio/wav",
        suggested_basename="Failure",
        action_label="Export: {filename}",
        action_type="file.export",
    )
    assert messages.critical_calls[-1] == ("Export failed", "disk full")


def test_background_audio_file_export_writes_bytes_and_reports_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    messages, _file_dialog = _install_export_dialog_fakes(monkeypatch)
    app = _export_app()
    dest = tmp_path / "exports" / "song.wav"

    monkeypatch.setattr(
        export_controller,
        "write_catalog_export_tags",
        lambda *_args, **_kwargs: (False, "tags unavailable"),
    )
    monkeypatch.setattr(
        export_controller,
        "_run_file_history_action",
        lambda **kwargs: kwargs["mutation"](),
    )

    export_controller._submit_background_audio_file_export(
        app,
        task_title="Export Audio File",
        task_description="Exporting audio...",
        dialog_title="Export",
        resolved_dest_path=dest,
        action_label="Export Audio: {filename}",
        action_type="file.export_audio_file",
        entity_type="Track",
        entity_id="5",
        payload={"track_id": 5},
        load_source=lambda _bundle: (memoryview(b"catalog-audio"), "audio/wav"),
        metadata_track_id=5,
    )
    task = app.submitted_tasks[-1]
    ctx = _ExportContext()
    bundle = SimpleNamespace(
        track_service=object(),
        release_service=object(),
        audio_tag_service=object(),
        history_manager=None,
    )

    result = task["task_fn"](bundle, ctx)
    assert dest.read_bytes() == b"catalog-audio"
    assert result == {"path": str(dest), "metadata_warning": "tags unavailable"}
    assert ctx.progress[0][2].startswith("Loading source audio")
    assert ctx.progress[-1][2].startswith("Finalizing exported audio")

    task["on_success_after_cleanup"](result)
    assert app.history_refreshes == 1
    assert "Metadata embedding skipped: tags unavailable." in messages.information_calls[-1][1]

    task["on_cancelled"]()
    assert app.status_messages[-1] == ("Export cancelled.", 5000)
    task["on_error"](RuntimeError("boom"))
    assert app.errors[-1][0] == "Export"


def test_export_catalog_audio_copies_guardrails_and_callback_flow(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    messages, file_dialog = _install_export_dialog_fakes(monkeypatch)
    app = _export_app()
    app.track_service = object()
    app.tagged_audio_export_service = None
    app._normalize_track_ids = lambda ids: list(ids or [])
    app._catalog_table_controller = lambda: SimpleNamespace(
        selected_or_visible_track_ids=lambda: []
    )

    export_controller.export_catalog_audio_copies(app, [1])
    assert messages.warning_calls[-1] == ("Export Catalog Audio Copies", "Open a profile first.")

    app.tagged_audio_export_service = object()
    app.track_service = object()
    export_controller.export_catalog_audio_copies(app)
    assert messages.information_calls[-1][1].startswith("Select one or more tracks")

    class FakeTagPreviewDialog:
        next_result = export_controller.QDialog.Accepted
        instances: list["FakeTagPreviewDialog"] = []

        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs
            type(self).instances.append(self)

        def exec(self):
            return type(self).next_result

    monkeypatch.setitem(
        sys.modules,
        "isrc_manager.main_window",
        SimpleNamespace(TagPreviewDialog=FakeTagPreviewDialog),
    )

    app.exports_dir = tmp_path
    app.release_service = object()
    app._normalize_track_ids = lambda ids: [int(track_id) for track_id in ids]
    prepared = [TaggedAudioExportPlanItem(1, "Song", "song", ".wav", "database", None)]

    def prepare_preview(selected_ids, *, track_service, release_service, progress_callback):
        assert selected_ids == [1]
        assert track_service == "bundle-track-service"
        assert release_service == "bundle-release-service"
        progress_callback(0, 1, "preparing")
        return {
            "prepared": prepared,
            "rows": [{"track": "Song", "field": "Title"}],
            "warnings": ["preview warning"],
        }

    app._prepare_tagged_audio_export_preview = prepare_preview

    export_controller.export_catalog_audio_copies(app, [1])
    preview_task = app.submitted_tasks[-1]
    ctx = _ExportContext()
    result = preview_task["task_fn"](
        SimpleNamespace(
            track_service="bundle-track-service",
            release_service="bundle-release-service",
        ),
        ctx,
    )
    assert result["prepared"] == prepared
    assert ctx.progress == [(0, 1, "preparing")]

    preview_task["on_success_after_cleanup"](
        {"prepared": [], "rows": [], "warnings": ["nothing attached"]}
    )
    assert "No exportable audio files" in messages.information_calls[-1][1]

    FakeTagPreviewDialog.next_result = export_controller.QDialog.Rejected
    submitted_before = len(app.submitted_tasks)
    preview_task["on_success_after_cleanup"](result)
    assert len(app.submitted_tasks) == submitted_before

    FakeTagPreviewDialog.next_result = export_controller.QDialog.Accepted
    file_dialog.directory = ""
    preview_task["on_success_after_cleanup"](result)
    assert len(app.submitted_tasks) == submitted_before

    file_dialog.directory = str(tmp_path / "copies")
    app.progress_events = []
    app.events = []
    app.audits = []
    app.audit_commits = 0
    app._scaled_progress_callback = lambda callback, **_kwargs: (
        lambda *, value, maximum, message: callback(
            value=value,
            maximum=maximum,
            message=message,
        )
    )
    app._build_tagged_audio_export_items = lambda plan_items, **_kwargs: (
        ["export-item"],
        ["build warning"],
    )
    app._advance_task_ui_progress = lambda _ui_progress, **kwargs: app.progress_events.append(
        kwargs
    )
    app._log_event = lambda *args, **kwargs: app.events.append((args, kwargs))
    app._audit = lambda *args, **kwargs: app.audits.append((args, kwargs))
    app._audit_commit = lambda: setattr(app, "audit_commits", app.audit_commits + 1)
    export_result = TaggedAudioExportResult(
        requested=1,
        exported=1,
        skipped=1,
        warnings=["export warning"],
        written_paths=[str(tmp_path / "copies" / "song.wav")],
    )
    export_service = SimpleNamespace(
        export_copies=lambda **kwargs: export_result,
    )
    preview_task["on_success_after_cleanup"](result)
    export_task = app.submitted_tasks[-1]
    export_payload = export_task["task_fn"](
        SimpleNamespace(
            track_service=object(),
            release_service=object(),
            tagged_audio_export_service=export_service,
        ),
        _ExportContext(),
    )
    assert export_payload == {"result": export_result, "warnings": ["build warning"]}

    with pytest.raises(ValueError, match="did not return"):
        export_task["on_success_before_cleanup"]({}, None)
    export_task["on_success_before_cleanup"](export_payload, None)
    assert app.events[-1][0][0] == "audio.export_catalog_copies"
    assert app.audits[-1][0][:2] == ("EXPORT", "CatalogAudioCopy")
    assert app.audit_commits == 1

    with pytest.raises(ValueError, match="did not return"):
        export_task["on_success_after_cleanup"]({})
    export_task["on_success_after_cleanup"](export_payload)
    assert "Exported 1 catalog audio copy" in messages.information_calls[-1][1]
    assert "build warning" in messages.information_calls[-1][1]
    assert "export warning" in messages.information_calls[-1][1]

    export_task["on_cancelled"]()
    assert app.status_messages[-1] == ("Catalog audio copy export cancelled.", 5000)
    export_task["on_error"](RuntimeError("copy failed"))
    assert app.errors[-1][0] == "Export Catalog Audio Copies"


def test_background_audio_column_export_covers_standard_custom_skip_and_cancel_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    messages, _file_dialog = _install_export_dialog_fakes(monkeypatch)
    app = _export_app()

    monkeypatch.setattr(
        export_controller,
        "write_catalog_export_tags",
        lambda *_args, **_kwargs: (False, "tag writer offline"),
    )
    monkeypatch.setattr(
        export_controller,
        "_run_file_history_action",
        lambda **kwargs: kwargs["mutation"](),
    )

    standard_spec = {
        "kind": "standard",
        "media_key": "audio_file",
        "column_label": "Audio File",
    }
    track_service = _TrackService(
        {
            1: _snapshot("Alpha"),
            2: _snapshot("Beta"),
            3: None,
        },
        media_bytes={1: b"one"},
        byte_failures={2, 3},
    )
    bundle = SimpleNamespace(
        track_service=track_service,
        release_service=object(),
        audio_tag_service=object(),
        custom_field_values=None,
        history_manager=None,
    )

    export_controller._submit_background_audio_column_export(
        app,
        spec=standard_spec,
        track_ids=[1, 2, 3],
        output_root=tmp_path,
    )
    standard_task = app.submitted_tasks[-1]
    standard_result = standard_task["task_fn"](bundle, _ExportContext())

    assert standard_result["exported"] == 1
    assert (tmp_path / "Alpha.wav").read_bytes() == b"one"
    assert standard_result["metadata_skipped"] == ["Alpha.wav: tag writer offline"]
    assert len(standard_result["skipped"]) == 2

    standard_task["on_success_after_cleanup"](standard_result)
    assert app.history_refreshes == 1
    assert "Skipped 2 rows" in messages.information_calls[-1][1]
    assert "Metadata skipped for 1 export" in messages.information_calls[-1][1]

    with pytest.raises(InterruptedError, match="cancelled"):
        standard_task["task_fn"](bundle, _ExportContext(cancelled=True))
    standard_task["on_success_after_cleanup"]({"exported": 0, "skipped": ["Alpha: missing"]})
    assert "No files were exported." in messages.warning_calls[-1][1]
    standard_task["on_cancelled"]()
    assert app.status_messages[-1] == ("Export Audio File cancelled.", 5000)

    class _CustomValues:
        def fetch_blob(self, track_id: int, field_id: int):
            if track_id == 5:
                raise FileNotFoundError("missing custom audio")
            assert field_id == 9
            return bytearray(b"custom"), "audio/flac"

    custom_bundle = SimpleNamespace(
        track_service=_TrackService({4: _snapshot("Delta"), 5: _snapshot("Echo")}),
        custom_field_values=_CustomValues(),
        history_manager=None,
    )
    custom_spec = {
        "kind": "custom_blob",
        "column_label": "Demo Stem",
        "field_id": 9,
        "field_name": "Stem",
        "field_type": "blob_audio",
    }

    export_controller._submit_background_audio_column_export(
        app,
        spec=custom_spec,
        track_ids=[4, 5],
        output_root=tmp_path,
    )
    custom_task = app.submitted_tasks[-1]
    custom_result = custom_task["task_fn"](custom_bundle, _ExportContext())

    assert custom_result["exported"] == 1
    assert (tmp_path / "Delta - Stem.flac").read_bytes() == b"custom"
    assert custom_result["metadata_skipped"] == []
    assert custom_result["skipped"] == ["Echo: missing custom audio"]


def test_standard_media_export_routes_audio_and_non_audio_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    messages, file_dialog = _install_export_dialog_fakes(monkeypatch)
    app = _export_app()
    app.track_media_meta = lambda _track_id, _media_key: {"mime_type": "audio/wav"}
    app._media_export_basename_for_track = lambda track_id, media_key: f"{media_key}_{track_id}"
    app._resolve_file_export_target = lambda target_path, **_kwargs: Path(target_path)
    app._submit_background_audio_file_export = lambda **kwargs: app.submitted_tasks.append(kwargs)
    app.track_fetch_media = lambda _track_id, _media_key: (_ for _ in ()).throw(
        RuntimeError("missing image")
    )
    app._export_bytes_with_picker = lambda *args, **kwargs: app.submitted_tasks.append(
        {"args": args, "kwargs": kwargs}
    )

    export_controller._export_standard_media_for_track(app, 9, "audio_file")
    assert app.submitted_tasks == []

    file_dialog.save_path = str(tmp_path / "audio.wav")
    export_controller._export_standard_media_for_track(app, 9, "audio_file")
    assert app.submitted_tasks[-1]["resolved_dest_path"] == tmp_path / "audio.wav"
    assert app.submitted_tasks[-1]["metadata_track_id"] == 9

    app.track_fetch_media = lambda _track_id, _media_key: (_ for _ in ()).throw(
        RuntimeError("missing image")
    )
    export_controller._export_standard_media_for_track(app, 9, "album_art")
    assert messages.critical_calls[-1] == ("Export failed", "missing image")

    app.track_fetch_media = lambda _track_id, _media_key: (memoryview(b"png"), "image/png")
    export_controller._export_standard_media_for_track(app, 9, "album_art", "Cover Art")
    assert app.submitted_tasks[-1]["kwargs"]["suggested_basename"] == "Cover Art"
    assert app.submitted_tasks[-1]["kwargs"]["catalog_track_id"] is None


def test_focused_media_export_helpers_and_bulk_image_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    messages, file_dialog = _install_export_dialog_fakes(monkeypatch, directory=str(tmp_path))
    app = _export_app()
    app.BASE_HEADERS = ["Title", "Artist", "Audio"]
    app.active_custom_fields = [{"id": 7, "name": "Artwork", "field_type": "blob_image"}]
    app._standard_media_column_key = lambda media_key: f"media:{media_key}"
    app._standard_media_key_for_column_key = lambda column_key: (
        "album_art" if column_key == "media:album_art" else None
    )
    app._standard_media_key_for_header = lambda header_text: (
        "audio_file" if header_text == "Audio" else None
    )
    app._custom_field_column_key = lambda field_id: f"custom:{field_id}"
    app._custom_field_for_column_key = lambda column_key: (
        {"id": 8, "name": "Stem", "field_type": "blob_audio"} if column_key == "custom:8" else None
    )

    class _Model:
        def columnCount(self) -> int:
            return 5

        def headerData(self, column: int, _orientation, role: int):
            values = {
                (0, export_controller.Qt.DisplayRole): "Title",
                (1, export_controller.Qt.DisplayRole): "Cover",
                (1, export_controller.ColumnKeyRole): "media:album_art",
                (2, export_controller.Qt.DisplayRole): "Audio",
                (2, export_controller.ColumnKeyRole): "",
                (3, export_controller.Qt.DisplayRole): "Artwork",
                (3, export_controller.ColumnKeyRole): "",
                (4, export_controller.Qt.DisplayRole): "Stem",
                (4, export_controller.ColumnKeyRole): "custom:8",
            }
            return values.get((column, role), "")

    app.table = SimpleNamespace(model=lambda: _Model())
    assert export_controller._focused_media_export_spec(app, 1)["media_key"] == "album_art"
    assert export_controller._focused_media_export_spec(app, 2)["media_key"] == "audio_file"
    assert export_controller._focused_media_export_spec(app, 3)["field_id"] == 7
    assert export_controller._focused_media_export_spec(app, 4)["field_type"] == "blob_audio"
    assert export_controller._focused_media_export_spec(app, 99) is None

    app._focused_media_export_spec = lambda _column: None
    export_controller._export_focused_media_column(app, 0, track_ids=[1])
    assert messages.warning_calls[-1][1].startswith("Focus a stored audio")

    audio_spec = {
        "kind": "standard",
        "column": 2,
        "column_label": "Audio",
        "media_key": "audio_file",
    }
    app._focused_media_export_spec = lambda _column: audio_spec
    app._catalog_table_controller = lambda: SimpleNamespace(selected_track_ids=lambda: [])
    app._proxy_ordered_track_ids = lambda _ids, **_kwargs: []
    export_controller._export_focused_media_column(app, 2)
    assert messages.information_calls[-1][1].startswith("Select one or more rows")

    app._proxy_ordered_track_ids = lambda ids, **_kwargs: list(ids or [1, 2])
    delegated: list[dict[str, object]] = []
    app._submit_background_audio_column_export = lambda **kwargs: delegated.append(kwargs)
    export_controller._export_focused_media_column(app, 2, track_ids=[1])
    assert delegated[-1]["spec"] is audio_spec

    image_spec = {
        "kind": "standard",
        "column": 1,
        "column_label": "Album Art",
        "media_key": "album_art",
    }
    app._focused_media_export_spec = lambda _column: image_spec
    app.track_has_media = lambda track_id, _media_key: track_id == 1
    app.track_fetch_media = lambda _track_id, _media_key: (bytearray(b"png"), "image/png")
    app._media_export_basename_for_track = lambda track_id, _media_key: f"Cover {track_id}"
    app._get_track_title = lambda track_id: f"Track {track_id}"
    app._attempt_catalog_audio_export_metadata = lambda _path, *, track_id: None
    app.history_manager = object()
    monkeypatch.setattr(
        export_controller,
        "_run_file_history_action",
        lambda **kwargs: kwargs["mutation"](),
    )

    export_controller._export_focused_media_column(app, 1, track_ids=[1, 2])
    assert (tmp_path / "Cover 1.png").read_bytes() == b"png"
    assert app.history_refreshes == 1
    assert "Skipped 1 row" in messages.information_calls[-1][1]

    custom_spec = {
        "kind": "custom_blob",
        "column": 3,
        "column_label": "Artwork",
        "field_id": 7,
        "field_type": "blob_image",
    }
    (tmp_path / "custom").mkdir()
    file_dialog.directory = str(tmp_path / "custom")
    app.history_manager = None
    app._focused_media_export_spec = lambda _column: custom_spec
    app.cf_has_blob = lambda track_id, _field_id: track_id == 4
    app.cf_fetch_blob = lambda _track_id, _field_id: (memoryview(b"custom-png"), "image/png")
    app._custom_blob_export_basename = (
        lambda track_id, field_id: f"Track {track_id} Field {field_id}"
    )
    export_controller._export_focused_media_column(app, 3, track_ids=[4])
    assert (tmp_path / "custom" / "Track 4 Field 7.png").read_bytes() == b"custom-png"


def test_media_export_basename_focus_and_proxy_ordering_edges(tmp_path: Path) -> None:
    snapshot_service = SimpleNamespace(
        fetch_track_snapshot=lambda track_id, cursor=None: {
            1: SimpleNamespace(track_title="Song Title", album_title="Album Title"),
            2: SimpleNamespace(track_title="", album_title="Single"),
            3: None,
        }[track_id]
    )
    app = SimpleNamespace(
        cursor=object(),
        track_service=snapshot_service,
        _get_track_title=lambda track_id: "Fallback Title" if track_id == 2 else "",
        custom_field_definitions=SimpleNamespace(get_field_name=lambda field_id: "Stem"),
        _media_export_basename_for_track=lambda track_id, media_key: export_controller._media_export_basename_for_track(
            app,
            track_id,
            media_key,
        ),
    )

    assert export_controller._media_export_basename_for_track(app, 1, "album_art") == "Album Title"
    assert export_controller._media_export_basename_for_track(app, 1, "audio_file") == "Song Title"
    assert export_controller._media_export_basename_for_track(app, 2, "album_art") == (
        "Fallback Title"
    )
    assert export_controller._media_export_basename_for_track(app, 3, "audio_file") == "track_3"
    assert export_controller._custom_blob_export_basename(app, 1, 8) == "Song Title - Stem"

    app.custom_field_definitions = SimpleNamespace(get_field_name=lambda _field_id: "")
    assert export_controller._custom_blob_export_basename(app, 1, 8) == "Song Title"

    model = SimpleNamespace(
        columnCount=lambda: 2,
        headerData=lambda *_args: "",
    )
    focus_app = SimpleNamespace(
        table=SimpleNamespace(model=lambda: model),
        BASE_HEADERS=["Title", "Artist"],
        active_custom_fields=[],
        _standard_media_key_for_column_key=lambda _key: None,
        _standard_media_key_for_header=lambda _header: None,
        _standard_media_column_key=lambda media_key: f"media:{media_key}",
        _custom_field_for_column_key=lambda _key: None,
        _custom_field_column_key=lambda field_id: f"custom:{field_id}",
    )
    assert export_controller._focused_media_export_spec(focus_app, 1) is None
    assert export_controller._focused_media_export_spec(focus_app, 4) is None

    focus_app.active_custom_fields = [{"id": 9, "name": "Text Field", "field_type": "text"}]
    assert export_controller._focused_media_export_spec(focus_app, 2) is None

    payload_calls = []
    payload_app = SimpleNamespace(
        _media_cell_has_payload=lambda *args, **kwargs: payload_calls.append((args, kwargs)) or True
    )
    assert export_controller._media_cell_has_payload_for_export_spec(
        payload_app,
        "index",
        {"kind": "standard", "media_key": "album_art"},
    )
    assert payload_calls[-1] == (("index",), {"media_key": "album_art"})
    assert not export_controller._media_cell_has_payload_for_export_spec(
        payload_app,
        "index",
        {"kind": "custom_blob", "field_id": "bad"},
    )

    controller = SimpleNamespace(
        column_for_key=lambda key: 2 if key == "media:audio" else None,
        visible_indexes=lambda column: ["row-1", "row-2", "row-3", "row-4"],
        track_id_for_index=lambda index: {
            "row-1": 10,
            "row-2": None,
            "row-3": 11,
            "row-4": 12,
        }[index],
    )
    ordered_app = SimpleNamespace(
        _normalize_track_ids=lambda values: list(dict.fromkeys(int(value) for value in values)),
        _catalog_table_controller=lambda: controller,
        _catalog_proxy_model=lambda: object(),
        _media_cell_has_payload_for_export_spec=lambda index, spec: index != "row-1",
    )
    assert export_controller._proxy_ordered_track_ids(
        ordered_app,
        [10, 11, 12],
        media_spec={"column": "bad", "column_key": "media:audio"},
        require_media_payload=True,
    ) == [11, 12]

    ordered_app._catalog_proxy_model = lambda: None
    ordered_app._media_cell_has_payload_for_export_spec = lambda _index, _spec: False
    assert export_controller._proxy_ordered_track_ids(
        ordered_app,
        [12, 10],
        media_spec={"column": 2},
        require_media_payload=True,
    ) == [12, 10]


def test_export_focused_media_column_cancel_and_no_export_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    messages, file_dialog = _install_export_dialog_fakes(monkeypatch, directory="")
    app = _export_app()
    image_spec = {
        "kind": "standard",
        "column": 1,
        "column_label": "Album Art",
        "media_key": "album_art",
    }
    app._focused_media_export_spec = lambda _column: image_spec
    app._catalog_table_controller = lambda: SimpleNamespace(selected_track_ids=lambda: [6])
    app._proxy_ordered_track_ids = lambda ids, **_kwargs: list(ids)

    export_controller._export_focused_media_column(app, 1, track_ids=[6])
    assert messages.warning_calls == []
    assert messages.information_calls == []

    file_dialog.directory = str(tmp_path)
    app.track_has_media = lambda _track_id, _media_key: False
    app._get_track_title = lambda _track_id: (_ for _ in ()).throw(RuntimeError("title down"))
    export_controller._export_focused_media_column(app, 1, track_ids=[6])
    assert "No files were exported." in messages.warning_calls[-1][1]
    assert "track_6: No stored album art is available." in messages.warning_calls[-1][1]

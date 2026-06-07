from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

from isrc_manager.catalog_table import RawValueRole, media_routing
from isrc_manager.file_storage import STORAGE_MODE_DATABASE, STORAGE_MODE_MANAGED_FILE


class _MessageBox:
    Yes = 1
    No = 2

    messages: list[tuple[str, tuple]] = []

    @classmethod
    def information(cls, *args):
        cls.messages.append(("information", args))

    @classmethod
    def warning(cls, *args):
        cls.messages.append(("warning", args))

    @classmethod
    def critical(cls, *args):
        cls.messages.append(("critical", args))

    @classmethod
    def question(cls, *args):
        cls.messages.append(("question", args))
        return cls.Yes


def _root_attr(name, fallback):
    if name == "QMessageBox":
        return _MessageBox
    if name == "_prompt_storage_mode_choice":
        return lambda *args, **kwargs: STORAGE_MODE_DATABASE
    if name == "run_snapshot_history_action":
        return lambda **kwargs: kwargs["mutation"]()
    return fallback


def test_source_specs_column_keys_and_custom_field_lookup():
    media_specs = media_routing.standard_media_specs_by_label()
    audio_label = next(
        label for label, spec in media_specs.items() if spec.media_key == "audio_file"
    )
    audio_key = media_specs[audio_label].key
    app = SimpleNamespace(
        BASE_HEADERS=[audio_label, "Other"],
        active_custom_fields=[{"id": 4, "name": "Stem"}],
        _standard_media_header_map=lambda: {audio_label: "audio_file", "Legacy": "album_art"},
        _fallback_header_column_key=lambda label, **kwargs: f"fallback:{label}",
    )

    assert media_routing._audio_preview_source_spec_for_standard_media("") == {
        "kind": "standard",
        "media_key": "audio_file",
    }
    assert media_routing._audio_preview_source_spec_for_custom_field(4, field_name=" Stem ") == {
        "kind": "custom",
        "field_id": 4,
        "field_name": "Stem",
    }
    assert media_routing._standard_media_column_key(app, "audio_file") == f"base:{audio_key}"
    assert (
        media_routing._standard_media_key_for_column_key(app, f"base:{audio_key}") == "audio_file"
    )
    assert media_routing._custom_field_column_key(4) == "custom:4"
    assert media_routing._custom_field_for_column_key(app, "custom:4") == {"id": 4, "name": "Stem"}
    assert media_routing._custom_field_for_column_key(app, "custom:bad") is None


def test_model_data_media_payload_and_source_spec_column_resolution():
    index = mock.Mock()
    index.isValid.return_value = True
    index.model.return_value.data.return_value = (7, "audio_file")
    controller = SimpleNamespace(
        track_id_for_index=mock.Mock(return_value=7),
        column_for_key=mock.Mock(side_effect=lambda key: {"base:audio": 2, "custom:9": 5}.get(key)),
    )
    app = SimpleNamespace(
        _model_data_for_index=lambda idx, role: media_routing._model_data_for_index(app, idx, role),
        _catalog_table_controller=mock.Mock(return_value=controller),
        _standard_media_column_key=mock.Mock(return_value="base:audio"),
        _custom_field_column_key=lambda field_id: media_routing._custom_field_column_key(field_id),
        _media_cell_has_payload=lambda idx, **kwargs: media_routing._media_cell_has_payload(
            app, idx, **kwargs
        ),
    )

    assert media_routing._model_data_for_index(app, index, RawValueRole) == (7, "audio_file")
    assert media_routing._media_cell_has_payload(app, index, media_key="audio_file") is True
    assert media_routing._media_cell_has_payload(app, index, media_key="album_art") is False
    assert (
        media_routing._media_column_for_audio_source_spec(
            app,
            {"kind": "standard", "media_key": "audio_file"},
        )
        == 2
    )
    assert (
        media_routing._media_column_for_audio_source_spec(
            app,
            {"kind": "custom", "field_id": 9},
        )
        == 5
    )
    assert (
        media_routing._media_cell_has_payload_for_source_spec(
            app,
            index,
            {"kind": "standard", "media_key": "audio_file"},
        )
        is True
    )
    controller.track_id_for_index.return_value = 8
    assert media_routing._media_cell_has_payload(app, index, media_key="audio_file") is False


def test_column_payload_and_source_spec_edge_cases():
    app = SimpleNamespace(
        BASE_HEADERS=["Audio File"],
        active_custom_fields=[{"id": 4, "name": "Stem"}],
        _standard_media_header_map=lambda: {
            "Audio File": "audio_file",
            "Legacy Artwork": "album_art",
        },
        _fallback_header_column_key=lambda label, **kwargs: f"{kwargs['prefix']}:{label}:{kwargs['logical_index']}",
    )

    assert media_routing._standard_media_column_key(app, "album_art") == "base:Legacy Artwork:0"
    assert media_routing._standard_media_column_key(app, "missing") is None
    assert media_routing._standard_media_key_for_column_key(app, None) is None
    assert media_routing._standard_media_key_for_column_key(app, "base:missing") is None
    assert media_routing._custom_field_for_column_key(app, "base:title") is None

    invalid_index = SimpleNamespace(isValid=lambda: False)
    assert media_routing._model_data_for_index(app, invalid_index, RawValueRole) is None

    model = SimpleNamespace(data=mock.Mock(return_value=("bad-track", "audio_file")))
    index = SimpleNamespace(isValid=lambda: True, model=lambda: model)
    controller = SimpleNamespace(track_id_for_index=mock.Mock(return_value=7))
    app._model_data_for_index = lambda idx, role: media_routing._model_data_for_index(
        app, idx, role
    )
    app._catalog_table_controller = mock.Mock(return_value=controller)
    assert media_routing._media_cell_has_payload(app, index) is True

    model.data.return_value = (7, "bad-field")
    assert media_routing._media_cell_has_payload(app, index, field_id=4) is False

    controller.column_for_key = mock.Mock()
    app._catalog_table_controller = mock.Mock(return_value=controller)
    app._custom_field_column_key = lambda field_id: media_routing._custom_field_column_key(field_id)
    assert media_routing._media_column_for_audio_source_spec(app, None) is None
    assert (
        media_routing._media_column_for_audio_source_spec(
            app,
            {"kind": "custom", "field_id": "bad"},
        )
        is None
    )
    assert (
        media_routing._media_column_for_audio_source_spec(
            app,
            {"kind": "custom", "field_id": 0},
        )
        is None
    )

    app._media_cell_has_payload = lambda idx, **kwargs: media_routing._media_cell_has_payload(
        app, idx, **kwargs
    )
    assert media_routing._media_cell_has_payload_for_source_spec(app, index, None) is True
    assert (
        media_routing._media_cell_has_payload_for_source_spec(
            app,
            index,
            {"kind": "custom", "field_id": "bad"},
        )
        is False
    )
    model.data.return_value = (7, 4)
    assert (
        media_routing._media_cell_has_payload_for_source_spec(
            app,
            index,
            {"kind": "custom", "field_id": 4},
        )
        is True
    )


def test_drop_event_partition_and_route_paths(monkeypatch):
    _MessageBox.messages = []
    monkeypatch.setattr(media_routing, "_root_attr", _root_attr)

    class Url:
        def __init__(self, path, local=True):
            self.path = path
            self.local = local

        def isLocalFile(self):
            return self.local

        def toLocalFile(self):
            return self.path

    event = SimpleNamespace(
        mimeData=lambda: SimpleNamespace(
            urls=lambda: [
                Url("/tmp/a.wav"),
                Url("/tmp/a.wav"),
                Url("/tmp/b.png"),
                Url("https://example.test/audio.wav", local=False),
            ]
        )
    )
    app = SimpleNamespace(
        _is_supported_media_attach_path=mock.Mock(
            side_effect=lambda path, key: (key == "audio_file" and path.endswith(".wav"))
            or (key == "album_art" and path.endswith(".png"))
        ),
        _partition_dropped_media_paths=lambda paths: media_routing._partition_dropped_media_paths(
            app, paths
        ),
        bulk_attach_audio_files=mock.Mock(),
        attach_album_art_file_to_catalog=mock.Mock(),
    )

    assert media_routing._drop_event_local_file_paths(app, event) == ["/tmp/a.wav", "/tmp/b.png"]
    assert media_routing._partition_dropped_media_paths(
        app,
        ["/tmp/a.wav", "/tmp/b.png", "/tmp/readme.txt"],
    ) == (["/tmp/a.wav"], ["/tmp/b.png"], ["/tmp/readme.txt"])

    assert media_routing._route_dropped_media_paths(app, ["/tmp/a.wav", "/tmp/b.png"]) is True
    app.bulk_attach_audio_files.assert_called_once_with(
        file_paths=["/tmp/a.wav", "/tmp/b.png"],
        title="Attach Dropped Audio Files",
    )
    assert media_routing._route_dropped_media_paths(app, ["/tmp/b.png"]) is True
    app.attach_album_art_file_to_catalog.assert_called_once_with(
        file_paths=["/tmp/b.png"],
        title="Attach Dropped Album Art",
    )
    assert media_routing._route_dropped_media_paths(app, ["/tmp/readme.txt"]) is True
    assert _MessageBox.messages[-1][0] == "information"


def test_drop_event_and_routing_edge_cases(monkeypatch):
    _MessageBox.messages = []
    monkeypatch.setattr(media_routing, "_root_attr", _root_attr)

    assert (
        media_routing._drop_event_local_file_paths(
            SimpleNamespace(mimeData=lambda: None),
            object(),
        )
        == []
    )

    class RaisingLocalUrl:
        def isLocalFile(self):
            raise RuntimeError("local check failed")

    class RaisingPathUrl:
        def isLocalFile(self):
            return True

        def toLocalFile(self):
            raise RuntimeError("path failed")

    event = SimpleNamespace(
        mimeData=lambda: SimpleNamespace(urls=lambda: [RaisingLocalUrl(), RaisingPathUrl()])
    )
    assert media_routing._drop_event_local_file_paths(SimpleNamespace(), event) == []

    app = SimpleNamespace(
        _partition_dropped_media_paths=lambda paths: media_routing._partition_dropped_media_paths(
            app, paths
        ),
        _is_supported_media_attach_path=mock.Mock(
            side_effect=lambda path, key: (key == "album_art" and path.endswith(".png"))
        ),
        bulk_attach_audio_files=mock.Mock(),
        attach_album_art_file_to_catalog=mock.Mock(),
    )

    assert media_routing._route_dropped_media_paths(app, ["/tmp/a.png", "/tmp/b.png"]) is True
    assert "Only audio files" in _MessageBox.messages[-1][1][2]
    assert (
        media_routing._route_dropped_media_paths(app, ["/tmp/readme.txt", "/tmp/doc.pdf"]) is True
    )
    assert "not supported" in _MessageBox.messages[-1][1][2]
    assert media_routing._route_dropped_media_paths(app, []) is False


def test_track_media_proxy_methods_delegate_to_track_service():
    service = SimpleNamespace(
        get_media_meta=mock.Mock(return_value={"filename": "audio.wav"}),
        has_media=mock.Mock(return_value=True),
        fetch_media_bytes=mock.Mock(return_value=(b"data", "audio/wav")),
        set_media_path=mock.Mock(return_value={"updated": True}),
        clear_media=mock.Mock(),
        convert_media_storage_mode=mock.Mock(return_value={"mode": "database"}),
    )
    app = SimpleNamespace(track_service=service, cursor=object())

    assert media_routing.track_media_meta(app, 1, "audio_file") == {"filename": "audio.wav"}
    assert media_routing.track_has_media(app, 1, "audio_file") is True
    assert media_routing.track_fetch_media(app, 1, "audio_file") == (b"data", "audio/wav")
    assert media_routing.track_set_media(app, 1, "audio_file", "/tmp/audio.wav") == {
        "updated": True
    }
    media_routing.track_clear_media(app, 1, "audio_file")
    assert media_routing.track_convert_media_storage_mode(app, 1, "audio_file", "database") == {
        "mode": "database"
    }


def test_choose_storage_modes_prompts_for_present_sources_and_honors_cancel(monkeypatch):
    prompts = []

    def prompt(*args, **kwargs):
        prompts.append(kwargs)
        return None if kwargs["subject"] == "the artwork file" else STORAGE_MODE_DATABASE

    monkeypatch.setattr(
        media_routing,
        "_root_attr",
        lambda name, fallback: prompt if name == "_prompt_storage_mode_choice" else fallback,
    )

    assert (
        media_routing._choose_track_media_storage_modes(
            SimpleNamespace(),
            audio_source_path="/tmp/audio.wav",
            album_art_source_path="/tmp/cover.png",
            audio_default=STORAGE_MODE_MANAGED_FILE,
            album_art_default=STORAGE_MODE_MANAGED_FILE,
        )
        is None
    )
    assert prompts[0]["subject"] == "the audio file"
    assert prompts[1]["subject"] == "the artwork file"
    assert media_routing._choose_track_media_storage_modes(
        SimpleNamespace(),
        audio_default=STORAGE_MODE_MANAGED_FILE,
        album_art_default=STORAGE_MODE_DATABASE,
    ) == (STORAGE_MODE_MANAGED_FILE, STORAGE_MODE_DATABASE)

    monkeypatch.setattr(
        media_routing,
        "_root_attr",
        lambda name, fallback: (
            (lambda *args, **kwargs: None) if name == "_prompt_storage_mode_choice" else fallback
        ),
    )
    assert (
        media_routing._choose_track_media_storage_modes(
            SimpleNamespace(),
            audio_source_path="/tmp/audio.wav",
            audio_default=STORAGE_MODE_DATABASE,
        )
        is None
    )


def test_attach_standard_media_submits_background_worker_and_success_callbacks(monkeypatch):
    submitted = {}
    status_messages = []
    monkeypatch.setattr(media_routing, "_root_attr", _root_attr)
    app = SimpleNamespace(
        _browse_track_media_file=mock.Mock(return_value="/tmp/audio.wav"),
        _confirm_lossy_primary_audio_selection=mock.Mock(return_value=True),
        _capture_catalog_refresh_request=mock.Mock(return_value={"focus_id": 4}),
        _scaled_progress_callback=mock.Mock(return_value="attach-progress"),
        _scaled_ui_progress_callback=mock.Mock(return_value="ui-progress"),
        _load_catalog_ui_dataset_from_bundle=mock.Mock(return_value={"rows": [4]}),
        _apply_catalog_refresh_request=mock.Mock(),
        _advance_task_ui_progress=mock.Mock(),
        _refresh_history_actions=mock.Mock(),
        _show_background_task_error=mock.Mock(),
        _submit_background_bundle_task=lambda **kwargs: submitted.update(kwargs),
        logger=mock.Mock(),
        conn=SimpleNamespace(commit=mock.Mock(), rollback=mock.Mock()),
        statusBar=lambda: SimpleNamespace(
            showMessage=lambda text, timeout: status_messages.append((text, timeout))
        ),
    )

    media_routing._attach_standard_media_for_track(app, 4, "audio_file")

    class FakeConnection:
        def __init__(self):
            self.cursor = mock.Mock(return_value="cursor")

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    bundle = SimpleNamespace(
        conn=FakeConnection(),
        track_service=SimpleNamespace(set_media_path=mock.Mock()),
        history_manager=object(),
    )
    ctx = SimpleNamespace(report_progress=mock.Mock())
    result = submitted["task_fn"](bundle, ctx)
    bundle.track_service.set_media_path.assert_called_once_with(
        4,
        "audio_file",
        "/tmp/audio.wav",
        storage_mode=STORAGE_MODE_DATABASE,
        progress_callback="attach-progress",
        cursor="cursor",
    )
    assert result["dataset"] == {"rows": [4]}
    submitted["on_success_before_cleanup"](result, "ui")
    submitted["on_success_after_cleanup"](result)
    app._apply_catalog_refresh_request.assert_called_once()
    app._refresh_history_actions.assert_called_once()
    assert "Attached audio file" in status_messages[-1][0]


def test_attach_standard_media_cancel_and_failure_paths(monkeypatch):
    _MessageBox.messages = []

    app = SimpleNamespace(_browse_track_media_file=mock.Mock(return_value=""))
    media_routing._attach_standard_media_for_track(app, 4, "audio_file")
    app._browse_track_media_file.assert_called_once_with("audio_file")

    monkeypatch.setattr(
        media_routing,
        "_root_attr",
        lambda name, fallback: (
            (lambda *args, **kwargs: None)
            if name == "_prompt_storage_mode_choice"
            else _MessageBox if name == "QMessageBox" else fallback
        ),
    )
    app = SimpleNamespace(
        _browse_track_media_file=mock.Mock(return_value="/tmp/audio.wav"),
        _confirm_lossy_primary_audio_selection=mock.Mock(),
    )
    media_routing._attach_standard_media_for_track(app, 4, "audio_file")
    app._confirm_lossy_primary_audio_selection.assert_not_called()

    monkeypatch.setattr(media_routing, "_root_attr", _root_attr)
    app = SimpleNamespace(
        _browse_track_media_file=mock.Mock(return_value="/tmp/audio.wav"),
        _confirm_lossy_primary_audio_selection=mock.Mock(return_value=False),
    )
    media_routing._attach_standard_media_for_track(app, 4, "audio_file")
    app._confirm_lossy_primary_audio_selection.assert_called_once()

    app = SimpleNamespace(
        _browse_track_media_file=mock.Mock(return_value="/tmp/cover.png"),
        _capture_catalog_refresh_request=mock.Mock(return_value={"focus_id": 4}),
        _submit_background_bundle_task=mock.Mock(side_effect=RuntimeError("submit failed")),
        conn=SimpleNamespace(rollback=mock.Mock()),
        logger=mock.Mock(),
    )
    media_routing._attach_standard_media_for_track(app, 4, "album_art")
    app.conn.rollback.assert_called_once_with()
    app.logger.exception.assert_called_once()
    assert _MessageBox.messages[-1][0] == "critical"


def test_delete_and_preview_standard_media_paths(monkeypatch):
    _MessageBox.messages = []
    monkeypatch.setattr(media_routing, "_root_attr", _root_attr)
    root_history = mock.Mock(side_effect=lambda **kwargs: kwargs["mutation"]())
    app = SimpleNamespace(
        __root_attr=mock.Mock(return_value=root_history),
        track_service=SimpleNamespace(list_album_group_track_ids=mock.Mock(return_value=[1, 2])),
        cursor=object(),
        track_clear_media=mock.Mock(),
        refresh_table_preserve_view=mock.Mock(),
        conn=SimpleNamespace(rollback=mock.Mock()),
        logger=mock.Mock(),
        track_has_media=mock.Mock(return_value=False),
        _open_audio_preview_for_track=mock.Mock(),
        _audio_preview_source_spec_for_standard_media=mock.Mock(return_value={"kind": "standard"}),
        track_fetch_media=mock.Mock(return_value=(b"image", "image/png")),
        _get_track_title=mock.Mock(return_value="Song"),
        _open_image_preview=mock.Mock(),
    )

    media_routing._delete_standard_media_for_track(app, 1, "album_art")
    app.track_clear_media.assert_called_once_with(1, "album_art")
    app.refresh_table_preserve_view.assert_called_once_with(focus_id=1)

    media_routing._preview_standard_media_for_track(app, 1, "audio_file")
    assert _MessageBox.messages[-1][0] == "information"

    app.track_has_media.return_value = True
    media_routing._preview_standard_media_for_track(app, 1, "audio_file")
    app._open_audio_preview_for_track.assert_called_once_with(
        1,
        {"kind": "standard"},
        autoplay=True,
    )

    media_routing._preview_standard_media_for_track(app, 1, "album_art")
    app._open_image_preview.assert_called_once_with(b"image", "Song")


def test_delete_and_preview_standard_media_cancel_and_error_paths(monkeypatch):
    _MessageBox.messages = []

    class NoMessageBox(_MessageBox):
        @classmethod
        def question(cls, *args):
            cls.messages.append(("question", args))
            return cls.No

    monkeypatch.setattr(
        media_routing,
        "_root_attr",
        lambda name, fallback: NoMessageBox if name == "QMessageBox" else fallback,
    )
    app = SimpleNamespace(
        track_service=None,
        track_clear_media=mock.Mock(),
        refresh_table_preserve_view=mock.Mock(),
    )
    media_routing._delete_standard_media_for_track(app, 1, "audio_file")
    app.track_clear_media.assert_not_called()

    monkeypatch.setattr(media_routing, "_root_attr", _root_attr)
    app = SimpleNamespace(
        __root_attr=mock.Mock(return_value=mock.Mock(side_effect=RuntimeError("history failed"))),
        track_service=None,
        track_clear_media=mock.Mock(),
        refresh_table_preserve_view=mock.Mock(),
        conn=SimpleNamespace(rollback=mock.Mock()),
        logger=mock.Mock(),
    )
    media_routing._delete_standard_media_for_track(app, 1, "audio_file")
    app.conn.rollback.assert_called_once_with()
    app.logger.exception.assert_called_once()
    assert _MessageBox.messages[-1][0] == "critical"

    app = SimpleNamespace(
        track_has_media=mock.Mock(return_value=True),
        track_fetch_media=mock.Mock(side_effect=FileNotFoundError("missing")),
        conn=SimpleNamespace(rollback=mock.Mock()),
        logger=mock.Mock(),
    )
    media_routing._preview_standard_media_for_track(app, 1, "album_art")
    app.logger.warning.assert_called_once()
    assert _MessageBox.messages[-1][0] == "information"

    app = SimpleNamespace(
        track_has_media=mock.Mock(side_effect=RuntimeError("preview failed")),
        conn=SimpleNamespace(rollback=mock.Mock()),
        logger=mock.Mock(),
    )
    media_routing._preview_standard_media_for_track(app, 1, "audio_file")
    app.conn.rollback.assert_called_once_with()
    app.logger.exception.assert_called_once()
    assert _MessageBox.messages[-1][0] == "critical"

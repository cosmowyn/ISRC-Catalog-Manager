from __future__ import annotations

import sqlite3
import sys
from types import SimpleNamespace
from unittest import mock

from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QColor, QImage

from isrc_manager.media import player_controller


class _EnabledAction:
    def __init__(self, enabled: bool):
        self._enabled = enabled

    def isEnabled(self) -> bool:
        return self._enabled


def _one_pixel_png() -> bytes:
    image = QImage(1, 1, QImage.Format_ARGB32)
    image.fill(QColor("#ff0000"))
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(data)


def test_detect_mime_identifies_common_image_and_audio_headers():
    app = SimpleNamespace()

    assert player_controller._detect_mime(app, b"\x89PNG\r\n\x1a\nrest") == "image/png"
    assert player_controller._detect_mime(app, b"\xff\xd8rest") == "image/jpeg"
    assert player_controller._detect_mime(app, b"GIF89arest") == "image/gif"
    assert player_controller._detect_mime(app, b"RIFFxxxxWEBPrest") == "image/webp"
    assert player_controller._detect_mime(app, b"RIFFxxxxWAVErest") == "audio/wav"
    assert player_controller._detect_mime(app, b"fLaCrest") == "audio/flac"
    assert (
        player_controller._detect_mime(app, b"OggS" + b"OpusHead".rjust(60, b"x")) == "audio/opus"
    )
    assert player_controller._detect_mime(app, b"OggSrest") == "audio/ogg"
    assert player_controller._detect_mime(app, b"ID3rest") == "audio/mpeg"
    assert player_controller._detect_mime(app, bytes([0xFF, 0xE3])) == "audio/mpeg"
    assert player_controller._detect_mime(app, b"unknown") == ""


def test_preview_blob_bytes_routes_images_and_audio_payloads():
    image_calls = []
    audio_calls = []
    app = SimpleNamespace(
        _detect_mime=lambda data: player_controller._detect_mime(SimpleNamespace(), data),
        _open_image_preview=lambda data, title: image_calls.append((data, title)),
        _open_audio_preview=lambda data, mime, title: audio_calls.append((data, mime, title)),
    )
    png_bytes = _one_pixel_png()

    player_controller._preview_blob_bytes(
        app, (memoryview(png_bytes), "application/octet-stream"), "Cover"
    )
    player_controller._preview_blob_bytes(app, (b"ID3audio", "audio/mpeg"), "Audio")
    player_controller._preview_blob_bytes(app, b"raw bytes", "Fallback")

    assert image_calls == [(png_bytes, "Cover")]
    assert audio_calls[0] == (b"ID3audio", "audio/mpeg", "Audio")
    assert audio_calls[1] == (b"raw bytes", "audio/wav", "Fallback")


def test_media_player_icon_and_preview_blob_error_fallbacks(monkeypatch, tmp_path):
    missing_icon_app = SimpleNamespace(_media_player_icon_path=lambda: tmp_path / "missing.svg")
    assert player_controller._media_player_action_icon(missing_icon_app).isNull()

    audio_calls = []
    app = SimpleNamespace(
        _detect_mime=lambda data: "",
        _open_image_preview=lambda data, title: (_ for _ in ()).throw(RuntimeError("image fail")),
        _open_audio_preview=lambda data, mime, title: audio_calls.append((data, mime, title)),
    )
    monkeypatch.setattr(
        player_controller,
        "QImage",
        SimpleNamespace(fromData=mock.Mock(side_effect=RuntimeError("decode boom"))),
    )

    player_controller._preview_blob_bytes(app, b"not-image", "Fallback Audio")

    assert audio_calls == [(b"not-image", "audio/wav", "Fallback Audio")]


def test_media_player_root_helpers_configure_action_icon(monkeypatch):
    icon_calls = []
    visibility_calls = []
    action = SimpleNamespace(
        setIcon=lambda icon: icon_calls.append(icon),
        setIconVisibleInMenu=lambda visible: visibility_calls.append(visible),
    )
    app = SimpleNamespace(
        font=lambda: "font",
        media_player_action=action,
        _media_player_action_icon=lambda: "configured-icon",
    )

    with mock.patch.dict(
        sys.modules,
        {"isrc_manager.main_window": SimpleNamespace(QMessageBox="root-box")},
    ):
        assert player_controller._message_box() == "root-box"

    assert str(player_controller._media_player_icon_path(SimpleNamespace())).endswith(
        "icons/music-player-fill.svg"
    )

    monkeypatch.setattr(
        player_controller,
        "QFontMetrics",
        lambda font: SimpleNamespace(height=lambda: 30),
    )
    assert player_controller._text_scaled_icon_extent(app) == 10

    player_controller._configure_media_player_action_icon(app)
    assert icon_calls == ["configured-icon"]
    assert visibility_calls == [True]

    player_controller._configure_media_player_action_icon(SimpleNamespace(media_player_action=None))


def test_audio_preview_navigation_uses_media_column_and_fallback_sources():
    controller = SimpleNamespace(
        visible_indexes=mock.Mock(return_value=["row-a", "row-b", "row-c"]),
        track_id_for_index=mock.Mock(
            side_effect=lambda index: {"row-a": 1, "row-b": None, "row-c": 3}[index]
        ),
        visible_track_ids=mock.Mock(return_value=[]),
        selected_track_ids=mock.Mock(return_value=[4, 5, 6]),
    )
    app = SimpleNamespace(
        _catalog_table_controller=mock.Mock(return_value=controller),
        _media_column_for_audio_source_spec=mock.Mock(return_value=2),
        _media_cell_has_payload_for_source_spec=mock.Mock(
            side_effect=lambda index, spec: index != "row-b"
        ),
        _normalize_track_ids=lambda values: list(dict.fromkeys(int(value) for value in values)),
    )

    assert player_controller._audio_preview_navigation_track_ids(app, {"kind": "standard"}) == [
        1,
        3,
    ]
    app._media_column_for_audio_source_spec.return_value = None
    controller.visible_track_ids.return_value = [9, 10]
    assert player_controller._audio_preview_navigation_track_ids(app, None) == [9, 10]

    controller.visible_track_ids.return_value = []
    app.catalog_reads = SimpleNamespace(list_tracks=mock.Mock(return_value=[(7, "Seven")]))
    app.cf_has_blob = mock.Mock(side_effect=lambda track_id, field_id: track_id in {5, 7})
    app.track_has_media = mock.Mock(side_effect=lambda track_id, media_key: track_id == 6)
    assert player_controller._audio_preview_navigation_track_ids(
        app,
        {"kind": "custom", "field_id": 9},
    ) == [5]
    controller.visible_track_ids.return_value = [6, 7]
    assert player_controller._audio_preview_navigation_track_ids(
        app,
        {"kind": "standard", "media_key": "audio_file"},
    ) == [6]
    controller.visible_track_ids.return_value = []
    controller.selected_track_ids.return_value = []
    app.catalog_reads.list_tracks.side_effect = RuntimeError("catalog unavailable")
    assert (
        player_controller._audio_preview_navigation_track_ids(
            app,
            {"kind": "custom", "field_id": 9},
        )
        == []
    )
    controller.visible_track_ids.return_value = [8]
    app.cf_has_blob.side_effect = RuntimeError("blob lookup failed")
    assert (
        player_controller._audio_preview_navigation_track_ids(
            app,
            {"kind": "custom", "field_id": 9},
        )
        == []
    )


def test_audio_preview_album_titles_and_track_ids_use_database_order_and_payload_filter():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE Albums(id INTEGER PRIMARY KEY, title TEXT)")
    conn.execute(
        "CREATE TABLE Tracks(id INTEGER PRIMARY KEY, album_id INTEGER, track_number INTEGER)"
    )
    conn.executemany(
        "INSERT INTO Albums(id, title) VALUES (?, ?)",
        [(1, " Album "), (2, "album"), (3, "Other")],
    )
    conn.executemany(
        "INSERT INTO Tracks(id, album_id, track_number) VALUES (?, ?, ?)",
        [(10, 1, 2), (11, 1, 1), (12, 1, None), (13, 3, 1)],
    )
    app = SimpleNamespace(
        conn=conn,
        _normalize_track_ids=lambda values: list(dict.fromkeys(int(value) for value in values)),
        _audio_preview_track_has_source_payload=mock.Mock(
            side_effect=lambda track_id, spec: track_id != 10
        ),
    )

    assert player_controller._audio_preview_album_titles(app) == ["Album", "Other"]
    assert player_controller._audio_preview_album_track_ids(app, "Album", {"kind": "standard"}) == [
        11,
        12,
    ]
    assert player_controller._audio_preview_album_track_ids(app, "", None) == []

    conn.close()

    assert player_controller._audio_preview_album_titles(SimpleNamespace(conn=None)) == []
    broken_app = SimpleNamespace(
        conn=SimpleNamespace(execute=mock.Mock(side_effect=RuntimeError("db down")))
    )
    assert player_controller._audio_preview_album_titles(broken_app) == []


def test_audio_preview_album_track_ids_fallback_queries_and_errors():
    fallback_conn = sqlite3.connect(":memory:")
    fallback_conn.execute("CREATE TABLE Albums(id INTEGER PRIMARY KEY, title TEXT)")
    fallback_conn.execute("CREATE TABLE Tracks(id INTEGER PRIMARY KEY, album_id INTEGER)")
    fallback_conn.execute("INSERT INTO Albums(id, title) VALUES (1, 'Legacy')")
    fallback_conn.executemany(
        "INSERT INTO Tracks(id, album_id) VALUES (?, 1)",
        [(3,), (1,), (2,)],
    )
    fallback_app = SimpleNamespace(
        conn=fallback_conn,
        _normalize_track_ids=lambda values: list(dict.fromkeys(int(value) for value in values)),
        _audio_preview_track_has_source_payload=mock.Mock(return_value=True),
    )

    assert player_controller._audio_preview_album_track_ids(fallback_app, "Legacy") == [1, 2, 3]
    fallback_conn.close()

    broken_app = SimpleNamespace(
        conn=SimpleNamespace(execute=mock.Mock(side_effect=RuntimeError("db down")))
    )
    assert player_controller._audio_preview_album_track_ids(broken_app, "Any") == []


def test_audio_preview_export_actions_call_custom_and_standard_handlers():
    called = []
    app = SimpleNamespace(
        _get_track_title=mock.Mock(return_value="Song"),
        cf_export_blob=lambda *args, **kwargs: called.append(("custom", args, kwargs)),
        _export_standard_media_for_track=lambda *args: called.append(("standard", args)),
        write_tags_to_exported_audio_action=_EnabledAction(True),
        convert_selected_audio_action=_EnabledAction(True),
        export_authenticity_watermarked_audio_action=_EnabledAction(False),
        export_authenticity_provenance_audio_action=_EnabledAction(True),
        export_forensic_watermarked_audio_action=_EnabledAction(True),
        export_catalog_audio_copies=lambda ids: called.append(("catalog", ids)),
        convert_selected_audio=lambda ids: called.append(("convert", ids)),
        export_authenticity_watermarked_audio=lambda ids: called.append(("auth", ids)),
        export_authenticity_provenance_audio=lambda ids: called.append(("provenance", ids)),
        export_forensic_watermarked_audio=lambda ids: called.append(("forensic", ids)),
    )

    custom_actions = player_controller._audio_preview_export_actions_for_track(
        app,
        4,
        {"kind": "custom", "field_id": 8, "field_name": "Stem"},
    )
    assert [action["text"] for action in custom_actions] == ["Export Current Audio…"]
    custom_actions[0]["handler"]()
    assert called[-1][0] == "custom"
    assert called[-1][1][:2] == (4, 8)
    assert called[-1][2]["suggested_basename"] == "Song - Stem"

    standard_actions = player_controller._audio_preview_export_actions_for_track(
        app,
        4,
        {"kind": "standard", "media_key": "audio_file"},
    )
    assert [action["text"] for action in standard_actions] == [
        "Export Current Audio…",
        "Export Catalog Audio Copies…",
        "Export Audio Derivatives…",
        "Export Provenance Copies…",
        "Export Forensic Watermarked Audio…",
    ]
    for action in standard_actions:
        action["handler"]()
    assert ("standard", (4, "audio_file")) in called
    assert ("catalog", [4]) in called
    assert ("convert", [4]) in called
    assert ("provenance", [4]) in called
    assert ("forensic", [4]) in called
    assert player_controller._audio_preview_export_actions_for_track(app, 4, None) == []
    assert (
        player_controller._audio_preview_export_actions_for_track(
            app,
            4,
            {"kind": "custom", "field_id": 0},
        )
        == []
    )


def test_audio_preview_queue_and_track_state_include_metadata_payload_and_exports():
    snapshot = SimpleNamespace(
        track_title="Snapshot Song", album_title="Album", artist_name="Artist"
    )
    app = SimpleNamespace(
        _normalize_track_ids=lambda values: list(dict.fromkeys(int(value) for value in values)),
        track_service=SimpleNamespace(fetch_track_snapshot=mock.Mock(return_value=snapshot)),
        _get_track_title=mock.Mock(return_value="Fallback"),
        _effective_artwork_payload_for_track=mock.Mock(return_value="artwork"),
        track_fetch_media=mock.Mock(return_value=(b"RIFFxxxxWAVEaudio", "audio/wav")),
        _coerce_export_bytes=mock.Mock(side_effect=lambda data: bytes(data)),
        _audio_preview_navigation_track_ids=mock.Mock(return_value=[2, 3]),
        _audio_preview_track_queue_items=mock.Mock(return_value=[{"track_id": 2}]),
        _audio_preview_export_actions_for_track=mock.Mock(return_value=[{"text": "Export"}]),
    )

    queue = player_controller._audio_preview_track_queue_items(app, [2, 2, 3])
    assert queue == [
        {
            "track_id": 2,
            "title": "Snapshot Song",
            "label": "Snapshot Song",
            "album": "Album",
            "position": 1,
        },
        {
            "track_id": 3,
            "title": "Snapshot Song",
            "label": "Snapshot Song",
            "album": "Album",
            "position": 2,
        },
    ]

    state = player_controller._audio_preview_state_for_track(
        app,
        5,
        {"kind": "standard", "media_key": "audio_file"},
    )
    assert state["track_id"] == 5
    assert state["track_order"] == [5, 2, 3]
    assert state["title"] == "Snapshot Song"
    assert state["artist"] == "Artist"
    assert state["album"] == "Album"
    assert state["audio_bytes"] == b"RIFFxxxxWAVEaudio"
    assert state["audio_mime"] == "audio/wav"
    assert state["artwork_payload"] == "artwork"
    assert state["window_title"] == "Audio Player — Snapshot Song"
    assert state["export_actions"] == [{"text": "Export"}]


def test_audio_preview_queue_and_track_state_fallbacks_and_prepared_media():
    app = SimpleNamespace(
        _normalize_track_ids=lambda values: list(dict.fromkeys(int(value) for value in values)),
        track_service=SimpleNamespace(fetch_track_snapshot=mock.Mock(return_value=None)),
        _get_track_title=mock.Mock(return_value=""),
        _effective_artwork_payload_for_track=mock.Mock(return_value=None),
        cf_fetch_blob=mock.Mock(return_value=(memoryview(b"ID3custom"), "audio/mpeg")),
        track_fetch_media=mock.Mock(return_value=(b"RIFFxxxxWAVEaudio", "")),
        _coerce_export_bytes=mock.Mock(side_effect=lambda data: bytes(data)),
        _audio_preview_navigation_track_ids=mock.Mock(return_value=[10, 11]),
        _audio_preview_track_queue_items=mock.Mock(return_value=[]),
        _audio_preview_export_actions_for_track=mock.Mock(return_value=[]),
    )

    queue = player_controller._audio_preview_track_queue_items(app, [7])
    assert queue[0]["title"] == "Track 7"

    app.track_service.fetch_track_snapshot.side_effect = RuntimeError("snapshot gone")
    queue = player_controller._audio_preview_track_queue_items(app, [8])
    assert queue[0]["title"] == "Track 8"

    custom_state = player_controller._audio_preview_state_for_track(
        app,
        9,
        {"kind": "custom", "field_id": 5},
    )
    assert custom_state["title"] == "Track 9"
    assert custom_state["audio_bytes"] == b"ID3custom"
    assert custom_state["audio_mime"] == "audio/mpeg"

    prepared_state = player_controller._audio_preview_state_for_track(
        app,
        10,
        {"kind": "standard", "media_key": "audio_file"},
        prepared_media=SimpleNamespace(audio_mime="audio/flac"),
    )
    assert prepared_state["audio_bytes"] == b""
    assert prepared_state["audio_mime"] == "audio/flac"

    prepared_custom_state = player_controller._audio_preview_state_for_track(
        app,
        11,
        {"kind": "custom", "field_id": 5},
        prepared_media=SimpleNamespace(audio_mime="audio/opus"),
    )
    assert prepared_custom_state["audio_mime"] == "audio/opus"

    no_service_app = SimpleNamespace(
        _normalize_track_ids=lambda values: list(dict.fromkeys(int(value) for value in values)),
        track_service=None,
        _get_track_title=mock.Mock(return_value="Manual Title"),
        _effective_artwork_payload_for_track=mock.Mock(return_value=None),
        track_fetch_media=mock.Mock(return_value=(b"ID3standard", "")),
        _coerce_export_bytes=mock.Mock(side_effect=lambda data: bytes(data)),
        _detect_mime=mock.Mock(return_value="audio/mpeg"),
        _audio_preview_navigation_track_ids=mock.Mock(return_value=[]),
        _audio_preview_track_queue_items=mock.Mock(return_value=[]),
        _audio_preview_export_actions_for_track=mock.Mock(return_value=[]),
    )
    no_service_queue = player_controller._audio_preview_track_queue_items(no_service_app, [12])
    assert no_service_queue[0]["title"] == "Manual Title"

    no_service_state = player_controller._audio_preview_state_for_track(
        no_service_app,
        12,
        {"kind": "standard", "media_key": "audio_file"},
    )
    assert no_service_state["title"] == "Manual Title"
    assert no_service_state["artist"] == ""
    assert no_service_state["album"] == ""
    assert no_service_state["audio_mime"] == "audio/mpeg"


def test_audio_preview_state_for_raw_bytes_builds_export_handler():
    calls = []
    app = SimpleNamespace(
        _coerce_export_bytes=lambda data: bytes(data),
        _detect_mime=lambda data: "audio/mpeg",
        _sanitize_filename=lambda title: title.lower().replace(" ", "-"),
        _export_bytes_with_picker=lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    state = player_controller._audio_preview_state_for_raw_bytes(
        app,
        memoryview(b"ID3audio"),
        "",
        "Raw Song",
    )

    assert state["track_id"] is None
    assert state["audio_bytes"] == b"ID3audio"
    assert state["audio_mime"] == "audio/mpeg"
    assert state["window_title"] == "Audio Player — Raw Song"
    state["export_actions"][0]["handler"]()
    assert calls[0][0][0] == b"ID3audio"
    assert calls[0][1]["suggested_basename"] == "Raw Song"
    assert calls[0][1]["entity_id"] == "raw-song"


def test_open_media_player_handles_existing_dialog_missing_profile_and_default_track(monkeypatch):
    messages = []
    brought_to_front = []

    class FakeMessageBox:
        @classmethod
        def warning(cls, *args):
            messages.append(("warning", args))

        @classmethod
        def information(cls, *args):
            messages.append(("information", args))

    monkeypatch.setattr(player_controller, "_message_box", lambda: FakeMessageBox)

    existing = SimpleNamespace(isVisible=mock.Mock(return_value=True))
    app = SimpleNamespace(
        audio_preview_dialog=existing,
        _bring_media_window_to_front=lambda dialog: brought_to_front.append(dialog),
    )
    player_controller.open_media_player(app)
    assert brought_to_front == [existing]

    app = SimpleNamespace(audio_preview_dialog=None, track_service=None)
    player_controller.open_media_player(app)
    assert messages[-1][0] == "warning"

    app = SimpleNamespace(
        audio_preview_dialog=None,
        track_service=object(),
        _media_player_default_track_id=mock.Mock(return_value=None),
    )
    player_controller.open_media_player(app)
    assert messages[-1][0] == "information"

    opened = []
    app._media_player_default_track_id.return_value = 9
    app._audio_preview_source_spec_for_standard_media = mock.Mock(return_value={"kind": "standard"})
    app._open_audio_preview_for_track = lambda *args, **kwargs: opened.append((args, kwargs))
    player_controller.open_media_player(app)
    assert opened == [((9, {"kind": "standard"}), {"autoplay": False})]


def test_open_image_and_audio_preview_dialogs_use_root_dialogs_and_error_messages(monkeypatch):
    messages = []
    fronts = []

    class FakeImageDialog:
        def __init__(self, app, parent=None):
            self.calls = []

        def set_preview(self, data, title):
            self.calls.append((data, title))

    class FailingAudioDialog:
        def __init__(self, app, parent=None):
            pass

        def open_raw_preview(self, *args, **kwargs):
            raise RuntimeError("decode failed")

    class FakeMessageBox:
        @classmethod
        def warning(cls, *args):
            messages.append(("warning", args))

        @classmethod
        def critical(cls, *args):
            messages.append(("critical", args))

    def fake_root_attr(name, fallback):
        if name == "_ImagePreviewDialog":
            return FakeImageDialog
        if name == "_AudioPreviewDialog":
            return FailingAudioDialog
        return fallback

    app = SimpleNamespace(
        image_preview_dialog=None,
        audio_preview_dialog=None,
        _bring_media_window_to_front=lambda dialog: fronts.append(dialog),
        logger=mock.Mock(),
    )
    monkeypatch.setattr(player_controller, "_root_attr", fake_root_attr)
    monkeypatch.setattr(player_controller, "_message_box", lambda: FakeMessageBox)

    player_controller._open_image_preview(app, b"image", "Cover")
    assert app.image_preview_dialog.calls == [(b"image", "Cover")]
    assert fronts == [app.image_preview_dialog]

    player_controller._open_audio_preview(app, b"bad", "audio/wav", "Broken")
    assert messages[-1][0] == "critical"
    app.logger.exception.assert_called_once()

    class FailingImageDialog(FakeImageDialog):
        def set_preview(self, data, title):
            raise ValueError("not an image")

    app.image_preview_dialog = None
    monkeypatch.setattr(
        player_controller,
        "_root_attr",
        lambda name, fallback: FailingImageDialog if name == "_ImagePreviewDialog" else fallback,
    )
    player_controller._open_image_preview(app, b"bad image", "Broken Cover")
    assert messages[-1][0] == "warning"


def test_open_audio_preview_success_uses_raw_dialog_and_front(monkeypatch):
    fronts = []

    class FakeAudioDialog:
        def __init__(self, app, parent=None):
            self.calls = []

        def open_raw_preview(self, *args, **kwargs):
            self.calls.append((args, kwargs))

    app = SimpleNamespace(
        audio_preview_dialog=None,
        _bring_media_window_to_front=lambda dialog: fronts.append(dialog),
        logger=mock.Mock(),
    )
    monkeypatch.setattr(
        player_controller,
        "_root_attr",
        lambda name, fallback: FakeAudioDialog if name == "_AudioPreviewDialog" else fallback,
    )

    player_controller._open_audio_preview(app, b"ID3audio", "audio/mpeg", "Raw")

    assert app.audio_preview_dialog.calls == [
        ((b"ID3audio", "audio/mpeg", "Raw"), {"autoplay": True})
    ]
    assert fronts == [app.audio_preview_dialog]


def test_existing_preview_dialog_instances_are_reused():
    fronts = []

    class ExistingImageDialog:
        def __init__(self):
            self.calls = []

        def set_preview(self, data, title):
            self.calls.append((data, title))

    class ExistingAudioDialog:
        def __init__(self):
            self.track_calls = []
            self.raw_calls = []

        def open_track_preview(self, *args, **kwargs):
            self.track_calls.append((args, kwargs))

        def open_raw_preview(self, *args, **kwargs):
            self.raw_calls.append((args, kwargs))

    image_dialog = ExistingImageDialog()
    audio_dialog = ExistingAudioDialog()
    app = SimpleNamespace(
        image_preview_dialog=image_dialog,
        audio_preview_dialog=audio_dialog,
        _bring_media_window_to_front=lambda dialog: fronts.append(dialog),
        logger=mock.Mock(),
    )

    player_controller._open_image_preview(app, b"image", "Cover")
    player_controller._open_audio_preview_for_track(app, 4, {"kind": "standard"})
    player_controller._open_audio_preview(app, b"ID3audio", "audio/mpeg", "Raw")

    assert image_dialog.calls == [(b"image", "Cover")]
    assert audio_dialog.track_calls == [((4, {"kind": "standard"}), {"autoplay": True})]
    assert audio_dialog.raw_calls == [((b"ID3audio", "audio/mpeg", "Raw"), {"autoplay": True})]
    assert fronts == [image_dialog, audio_dialog, audio_dialog]


def test_media_player_default_track_and_track_payload_helpers_cover_fallbacks():
    controller = SimpleNamespace(
        selected_track_ids=mock.Mock(return_value=[4, 2]),
        current_track_id=mock.Mock(return_value=3),
        visible_track_ids=mock.Mock(return_value=[5, 6]),
    )
    app = SimpleNamespace(
        _audio_preview_source_spec_for_standard_media=mock.Mock(return_value={"kind": "standard"}),
        _audio_preview_navigation_track_ids=mock.Mock(return_value=[1, 2, 3]),
        _catalog_table_controller=mock.Mock(return_value=controller),
        _normalize_track_ids=lambda values: list(dict.fromkeys(int(value) for value in values)),
        track_has_media=mock.Mock(return_value=True),
        cf_has_blob=mock.Mock(
            side_effect=lambda track_id, field_id: track_id == 8 and field_id == 9
        ),
    )

    assert player_controller._media_player_default_track_id(app) == 2
    controller.selected_track_ids.return_value = []
    controller.current_track_id.return_value = 3
    assert player_controller._media_player_default_track_id(app) == 3
    controller.current_track_id.return_value = 99
    assert player_controller._media_player_default_track_id(app) == 1
    app._audio_preview_navigation_track_ids.return_value = []
    controller.selected_track_ids.return_value = [4]
    controller.current_track_id.return_value = 5
    app.track_has_media.side_effect = [RuntimeError("stale"), False, True]
    assert player_controller._media_player_default_track_id(app) == 6

    app.track_has_media.side_effect = None
    app.track_has_media.return_value = True
    assert player_controller._audio_preview_track_has_source_payload(
        app,
        6,
        {"kind": "standard", "media_key": "audio_file"},
    )
    app.track_has_media.side_effect = RuntimeError("missing media")
    assert not player_controller._audio_preview_track_has_source_payload(
        app,
        6,
        {"kind": "standard", "media_key": "audio_file"},
    )
    app.track_has_media.side_effect = None
    app.track_has_media.return_value = True
    assert player_controller._audio_preview_track_has_source_payload(
        app,
        8,
        {"kind": "custom", "field_id": 9},
    )
    assert not player_controller._audio_preview_track_has_source_payload(
        app,
        8,
        {"kind": "custom", "field_id": "bad"},
    )
    assert player_controller._audio_preview_track_has_source_payload(app, 5, None)
    app._audio_preview_navigation_track_ids.return_value = []
    controller.selected_track_ids.return_value = []
    controller.current_track_id.return_value = None
    controller.visible_track_ids.return_value = [7]
    app.track_has_media.return_value = False
    assert player_controller._media_player_default_track_id(app) is None


def test_open_audio_preview_for_track_handles_success_and_failure(monkeypatch):
    fronts = []
    messages = []

    class FakeAudioDialog:
        def __init__(self, app, parent=None):
            self.opened = []

        def open_track_preview(self, *args, **kwargs):
            self.opened.append((args, kwargs))

    class FailingAudioDialog(FakeAudioDialog):
        def open_track_preview(self, *args, **kwargs):
            raise RuntimeError("cannot open")

    class FakeMessageBox:
        @classmethod
        def critical(cls, *args):
            messages.append(args)

    def fake_root_attr(name, fallback):
        if name == "_AudioPreviewDialog":
            return FakeAudioDialog
        return fallback

    app = SimpleNamespace(
        audio_preview_dialog=None,
        _bring_media_window_to_front=lambda dialog: fronts.append(dialog),
        logger=mock.Mock(),
    )
    monkeypatch.setattr(player_controller, "_root_attr", fake_root_attr)
    monkeypatch.setattr(player_controller, "_message_box", lambda: FakeMessageBox)

    player_controller._open_audio_preview_for_track(app, 7, {"kind": "standard"}, autoplay=False)
    assert app.audio_preview_dialog.opened == [((7, {"kind": "standard"}), {"autoplay": False})]
    assert fronts == [app.audio_preview_dialog]

    app.audio_preview_dialog = None
    monkeypatch.setattr(
        player_controller,
        "_root_attr",
        lambda name, fallback: FailingAudioDialog if name == "_AudioPreviewDialog" else fallback,
    )
    player_controller._open_audio_preview_for_track(app, 8, {"kind": "standard"})
    assert "Could not open the audio player" in messages[-1][2]
    app.logger.exception.assert_called_once()


def test_bring_media_window_to_front_handles_window_state_and_activation():
    calls = []
    handle = SimpleNamespace(requestActivate=lambda: calls.append("requestActivate"))
    window = SimpleNamespace(
        parentWidget=mock.Mock(return_value=object()),
        windowFlags=mock.Mock(return_value=0),
        setParent=lambda *args: calls.append(("setParent", args)),
        setWindowFlag=lambda *args: calls.append(("setWindowFlag", args)),
        setWindowModality=lambda modality: calls.append(("modality", modality)),
        setModal=lambda modal: calls.append(("modal", modal)),
        isMinimized=mock.Mock(return_value=True),
        showNormal=lambda: calls.append("showNormal"),
        show=lambda: calls.append("show"),
        raise_=lambda: calls.append("raise"),
        activateWindow=lambda: calls.append("activate"),
        windowHandle=lambda: handle,
    )

    player_controller._bring_media_window_to_front(SimpleNamespace(), None)
    player_controller._bring_media_window_to_front(SimpleNamespace(), window)

    assert "showNormal" in calls
    assert "raise" in calls
    assert "activate" in calls
    assert "requestActivate" in calls


def test_bring_media_window_to_front_ignores_window_activation_errors():
    calls = []

    class RaisingWindow:
        def parentWidget(self):
            return object()

        def windowFlags(self):
            return 0

        def setParent(self, *args):
            raise RuntimeError("cannot detach")

        def setWindowFlag(self, *args):
            calls.append("setWindowFlag")

        def setWindowModality(self, modality):
            calls.append("modality")

        def setModal(self, modal):
            calls.append("modal")

        def isMinimized(self):
            return False

        def show(self):
            calls.append("show")

        def raise_(self):
            raise RuntimeError("raise failed")

        def activateWindow(self):
            raise RuntimeError("activate failed")

        def windowHandle(self):
            return SimpleNamespace(
                requestActivate=lambda: (_ for _ in ()).throw(RuntimeError("request failed"))
            )

    player_controller._bring_media_window_to_front(SimpleNamespace(), RaisingWindow())

    assert calls == ["show"]

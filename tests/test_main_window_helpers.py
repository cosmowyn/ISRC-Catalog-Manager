from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QFont, QKeySequence
from PySide6.QtWidgets import QComboBox, QDialog, QToolBar, QWidget

from isrc_manager import main_window
from isrc_manager.main_window import App
from isrc_manager.selection_scope import TrackChoice
from tests.qt_test_helpers import require_qapplication


def _app() -> App:
    return App.__new__(App)


def _raise(error: Exception):
    raise error


class _Settings:
    def __init__(self, values: dict[str, object] | None = None) -> None:
        self.values = dict(values or {})
        self.synced = False
        self.removed: list[str] = []

    def contains(self, key: str) -> bool:
        return key in self.values

    def value(self, key: str, default=None, *_args):
        return self.values.get(key, default)

    def setValue(self, key: str, value: object) -> None:
        self.values[key] = value

    def remove(self, key: str) -> None:
        self.removed.append(key)
        self.values.pop(key, None)

    def sync(self) -> None:
        self.synced = True


class _ProfileKv:
    def __init__(self, values: dict[str, object] | None = None) -> None:
        self.values = dict(values or {})
        self.set_calls: list[tuple[str, object]] = []

    def get(self, key: str, default=None):
        return self.values.get(key, default)

    def set(self, key: str, value: object) -> None:
        self.values[key] = value
        self.set_calls.append((key, value))


def test_help_file_and_log_viewer_helpers_cover_refresh_jsonl_and_error_paths(
    tmp_path: Path,
) -> None:
    app = _app()
    app.help_dir = tmp_path / "help"
    app.help_file_path = app.help_dir / "index.html"
    app._help_html = lambda: "<html>fresh</html>"

    assert app._ensure_help_file() == app.help_file_path
    assert app.help_file_path.read_text(encoding="utf-8") == "<html>fresh</html>"
    app._help_html = lambda: "<html>fresh</html>"
    assert app._ensure_help_file() == app.help_file_path
    app._help_html = lambda: "<html>new</html>"
    app._ensure_help_file()
    assert app.help_file_path.read_text(encoding="utf-8") == "<html>new</html>"

    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    (logs_dir / "trace.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2026-05-25T12:00:00",
                        "level": "warning",
                        "event": "startup",
                        "message": "Started",
                        "extra": 3,
                    }
                ),
                "",
                "{not json}",
            ]
        ),
        encoding="utf-8",
    )
    (logs_dir / "plain.log").write_text("plain text", encoding="utf-8")
    (logs_dir / "ignored.txt").write_text("ignore", encoding="utf-8")
    app.logs_dir = tmp_path / "missing-logs"
    assert app._available_log_files() == []
    app.logs_dir = logs_dir
    assert [path.name for path in app._available_log_files()] == ["plain.log", "trace.jsonl"]

    rendered = app._read_log_for_viewer(logs_dir / "trace.jsonl")
    assert "[2026-05-25T12:00:00] WARNING startup" in rendered
    assert "  Started" in rendered
    assert "  extra: 3" in rendered
    assert "{not json}" in rendered
    assert app._read_log_for_viewer(logs_dir / "plain.log") == "plain text"
    assert "Could not read log file" in app._read_log_for_viewer(logs_dir / "missing.log")

    empty_jsonl = logs_dir / "empty.jsonl"
    empty_jsonl.write_text("\n\n", encoding="utf-8")
    assert app._read_log_for_viewer(empty_jsonl) == "(No trace entries found.)"


def test_help_dialog_local_path_widget_and_artist_code_paths(monkeypatch, tmp_path: Path) -> None:
    require_qapplication()
    app = _app()
    app.help_dir = tmp_path / "help"
    app.help_file_path = app.help_dir / "index.html"
    app._help_html = lambda: "<html>help</html>"
    app.help_dialog = None

    dialog_events: list[tuple[str, object]] = []

    class FakeHelpDialog:
        def __init__(self, _app, parent=None) -> None:
            self.parent = parent
            dialog_events.append(("init", parent))

        def setWindowModality(self, modality) -> None:
            dialog_events.append(("modality", modality))

        def refresh_help_source(self) -> None:
            dialog_events.append(("refresh", None))

        def open_topic(self, topic_id, *, focus_search: bool) -> None:
            dialog_events.append(("topic", (topic_id, focus_search)))

        def exec(self) -> None:
            dialog_events.append(("exec", None))

        def show(self) -> None:
            dialog_events.append(("show", None))

        def raise_(self) -> None:
            dialog_events.append(("raise", None))

        def activateWindow(self) -> None:
            dialog_events.append(("activate", None))

    monkeypatch.setattr(main_window, "HelpContentsDialog", FakeHelpDialog)
    modal_parent = QDialog()
    try:
        modal_parent.setModal(True)
        app.open_help_dialog("advanced", parent=modal_parent)
        assert ("modality", Qt.WindowModal) in dialog_events
        assert ("topic", ("advanced", False)) in dialog_events
        assert ("exec", None) in dialog_events

        dialog_events.clear()
        app.open_help_dialog()
        app.open_help_dialog("history")
        assert [event for event in dialog_events if event[0] == "init"] == [("init", app)]
        assert ("topic", ("overview", False)) in dialog_events
        assert ("topic", ("history", False)) in dialog_events
        assert dialog_events.count(("show", None)) == 2
    finally:
        modal_parent.deleteLater()

    warnings: list[tuple[str, str]] = []
    monkeypatch.setattr(
        main_window.QMessageBox,
        "warning",
        lambda _parent, title, message: warnings.append((title, message)),
    )
    missing_path = tmp_path / "missing"
    assert app._open_local_path(missing_path, "Inspect") is False
    assert warnings[-1][0] == "Inspect"
    assert "Path does not exist" in warnings[-1][1]

    existing_path = tmp_path / "existing.txt"
    existing_path.write_text("open me", encoding="utf-8")
    opened: list[Path] = []
    monkeypatch.setattr(
        main_window,
        "open_external_path",
        lambda path, **_kwargs: opened.append(Path(path)) or True,
    )
    assert app._open_local_path(existing_path, "Inspect") is True
    assert opened == [existing_path]
    monkeypatch.setattr(main_window, "open_external_path", lambda _path, **_kwargs: False)
    assert app._open_local_path(existing_path, "Inspect") is False
    assert "Could not open" in warnings[-1][1]

    widget = QWidget()
    toolbar = QToolBar()
    try:
        assert app._root_object_name(widget) == "qWidget"
        assert widget.objectName() == "qWidget"
        widget.setObjectName("alreadyNamed")
        assert app._root_object_name(widget) == "alreadyNamed"
        app.toolbar = object()
        app._apply_top_chrome_boundary()
        app.toolbar = toolbar
        app._apply_top_chrome_boundary()
        assert toolbar.contentsMargins().bottom() == app.TOP_CHROME_DOCK_GAP
    finally:
        widget.deleteLater()
        toolbar.deleteLater()

    app.profile_kv = _ProfileKv()
    app.settings = _Settings({"isrc/artist_code": "07"})
    app.logger = SimpleNamespace(info=lambda *_args, **_kwargs: None)
    app._migrate_artist_code_from_qsettings_if_needed()
    assert app.profile_kv.values["isrc_artist_code"] == "07"
    app.profile_kv = _ProfileKv()
    app.settings = _Settings({"isrc/artist_code": "bad"})
    app._migrate_artist_code_from_qsettings_if_needed()
    assert app.profile_kv.values["isrc_artist_code"] == "00"
    app.profile_kv = _ProfileKv({"isrc_artist_code": "42"})
    app._migrate_artist_code_from_qsettings_if_needed()
    assert app.profile_kv.set_calls == []

    app.profile_kv = _ProfileKv({"isrc_artist_code": "x"})
    assert app.load_artist_code() == "00"
    assert app.profile_kv.values["isrc_artist_code"] == "00"
    focused: list[str | None] = []
    app.open_settings_dialog = lambda initial_focus=None: focused.append(initial_focus)
    app.set_artist_code()
    assert focused == ["artist_code"]
    app._apply_single_setting_value = lambda field_name, value: app.profile_kv.set(
        field_name, value
    )
    app.artist_edit = SimpleNamespace(
        text="", setText=lambda value: setattr(app.artist_edit, "text", value)
    )
    app.set_artist_code("12")
    assert app.profile_kv.values["artist_code"] == "12"
    assert app.artist_edit.text == "12"
    app.set_artist_code("not-digits")
    assert warnings[-1][0] == "Invalid artist code"


def test_track_id_scope_and_first_value_helpers_use_selection_visible_and_all_fallbacks() -> None:
    app = _app()
    assert App._normalize_track_ids([1, "2", 2, 0, -1, "bad", None, 3]) == [1, 2, 3]
    assert App._first_non_blank("", "  ", [], {"a": 1}) == {"a": 1}
    assert App._first_non_blank("", None, " value ") == "value"

    app.current_db_path = "/tmp/profile.db"
    assert app._current_profile_name() == "profile.db"
    app.current_db_path = ""
    assert app._current_profile_name() is None

    class Controller:
        def __init__(self) -> None:
            self.selected = []
            self.visible = []

        def selected_track_ids(self):
            return self.selected

        def visible_track_ids(self):
            return self.visible

    controller = Controller()
    app._catalog_table_controller = lambda: controller
    app._all_catalog_track_choices = lambda: [
        TrackChoice(5, "Five"),
        TrackChoice(6, "Six"),
        TrackChoice(5, "Duplicate"),
    ]

    assert app._bulk_audio_attach_scope_track_ids([9, "10", "bad"]) == (
        [9, 10],
        "selected tracks",
    )
    controller.selected = [2, 2, "3"]
    assert app._bulk_audio_attach_scope_track_ids() == ([2, 3], "current selection")
    controller.selected = []
    controller.visible = [4, "bad"]
    assert app._bulk_audio_attach_scope_track_ids() == ([4, "bad"], "visible catalog rows")
    controller.visible = []
    assert app._bulk_audio_attach_scope_track_ids() == ([5, 6], "entire catalog")


def test_main_window_media_attach_helpers_cover_validation_matching_and_artwork_payloads(
    monkeypatch,
    tmp_path: Path,
) -> None:
    app = _app()
    information: list[tuple[str, str]] = []
    warnings: list[tuple[str, str]] = []

    class FakeMessageBox:
        @classmethod
        def information(cls, _parent, title, message) -> None:
            information.append((title, message))

        @classmethod
        def warning(cls, _parent, title, message) -> None:
            warnings.append((title, message))

    monkeypatch.setattr(main_window, "QMessageBox", FakeMessageBox)

    class DurationWidget:
        def __init__(self) -> None:
            self.value: int | None = None
            self.blocked: list[bool] = []

        def blockSignals(self, blocked: bool) -> bool:
            self.blocked.append(blocked)
            return False

        def setValue(self, value: int) -> None:
            self.value = value

    hours = DurationWidget()
    minutes = DurationWidget()
    seconds = DurationWidget()

    app.track_service = None
    assert (
        app._apply_audio_duration_to_widgets(
            tmp_path / "missing.mp3",
            hours_widget=hours,
            minutes_widget=minutes,
            seconds_widget=seconds,
        )
        is None
    )

    class FakeTrackService:
        def __init__(self) -> None:
            self.duration = None
            self.conflict_calls: list[tuple[str, int, object, object]] = []
            self.conflicts: dict[int, list[tuple[int, str]]] = {}
            self.snapshots: dict[int, object] = {}
            self.album_art_states: dict[int, object] = {}
            self.media_bytes: tuple[bytes, str | None] = (b"image", None)
            self.raise_media = False

        def derive_audio_duration_seconds(self, source_path):
            assert source_path
            return self.duration

        def list_album_track_number_conflicts(
            self,
            album_title,
            track_number,
            *,
            exclude_track_ids=None,
            cursor=None,
        ):
            self.conflict_calls.append((album_title, track_number, exclude_track_ids, cursor))
            return self.conflicts.get(int(track_number), [])

        def fetch_track_snapshot(self, track_id, **_kwargs):
            return self.snapshots.get(int(track_id))

        def describe_album_art_edit_state(self, track_id):
            if int(track_id) == 3:
                raise RuntimeError("cannot inspect artwork")
            return self.album_art_states.get(
                int(track_id), SimpleNamespace(can_replace_directly=False)
            )

        def fetch_media_bytes(self, track_id, media_key):
            assert int(track_id) == 8
            assert media_key == "album_art"
            if self.raise_media:
                raise RuntimeError("media fetch failed")
            return self.media_bytes

    track_service = FakeTrackService()
    app.track_service = track_service
    assert (
        app._apply_audio_duration_to_widgets(
            tmp_path / "missing.mp3",
            hours_widget=hours,
            minutes_widget=minutes,
            seconds_widget=seconds,
        )
        is None
    )
    track_service.duration = 3661
    assert (
        app._apply_audio_duration_to_widgets(
            tmp_path / "song.mp3",
            hours_widget=hours,
            minutes_widget=minutes,
            seconds_widget=seconds,
        )
        == 3661
    )
    assert (hours.value, minutes.value, seconds.value) == (1, 1, 1)
    track_service.duration = 400000
    app._apply_audio_duration_to_widgets(
        tmp_path / "long.mp3",
        hours_widget=hours,
        minutes_widget=minutes,
        seconds_widget=seconds,
    )
    assert hours.value == 99

    class FakeLineEdit:
        def __init__(self) -> None:
            self.text_value = ""

        def setText(self, value: str) -> None:
            self.text_value = value

    line_edit = FakeLineEdit()
    refreshes: list[str] = []
    duration_paths: list[str] = []
    app._refresh_line_edit_lossy_audio_warning = lambda widget: refreshes.append(widget.text_value)
    app._apply_audio_duration_to_widgets = (
        lambda source_path, **_kwargs: duration_paths.append(str(source_path)) or 123
    )
    app._browse_track_media_file = lambda _media_key, **_kwargs: ""
    app._choose_media_into_line_edit("audio_file", line_edit)
    assert line_edit.text_value == ""
    app._browse_track_media_file = lambda _media_key, **_kwargs: str(tmp_path / "song.mp3")
    app._choose_media_into_line_edit(
        "audio_file",
        line_edit,
        hours_widget=hours,
        minutes_widget=minutes,
        seconds_widget=seconds,
    )
    assert refreshes == [str(tmp_path / "song.mp3")]
    assert duration_paths == [str(tmp_path / "song.mp3")]
    app._choose_media_into_line_edit("album_art", line_edit)
    assert line_edit.text_value == str(tmp_path / "song.mp3")

    app.track_service = None
    app._warn_duplicate_track_numbers(album_title="Album", planned_rows=[(1, "One")])
    assert warnings == []
    app.track_service = track_service
    app._warn_duplicate_track_numbers(album_title="", planned_rows=[(1, "One")])
    app._warn_duplicate_track_numbers(album_title="Single", planned_rows=[(1, "One")])
    app._warn_duplicate_track_numbers(album_title="Album", planned_rows=[(0, "Zero"), ("bad", "")])
    assert warnings == []
    track_service.conflicts = {}
    app._warn_duplicate_track_numbers(album_title="Album", planned_rows=[(1, "Only")])
    assert warnings == []
    track_service.conflicts = {
        2: [
            (11, "Existing"),
            (12, ""),
            (13, "Third"),
            (14, "Fourth"),
            (15, "Fifth"),
        ]
    }
    app._warn_duplicate_track_numbers(
        album_title=" Album ",
        planned_rows=[(1, "One"), (1, ""), (2, "Two"), (2, "Two Again")],
        exclude_track_ids=[99],
        cursor="cursor",
        title="Duplicates",
    )
    assert len([call for call in track_service.conflict_calls if call[1] == 1]) >= 1
    assert warnings[-1][0] == "Duplicates"
    assert "This save contains duplicates" in warnings[-1][1]
    assert "- Track 1: One, Track 2" in warnings[-1][1]
    assert "Existing tracks on this album already use these numbers" in warnings[-1][1]
    assert ", and 1 more" in warnings[-1][1]

    snapshot_one = SimpleNamespace(
        track_id=1,
        track_title="Song",
        artist_name="Artist",
        album_title="Album",
        isrc="NL-AAA-26-00001",
    )
    track_service.snapshots = {1: snapshot_one, 2: None}
    assert app._media_attach_track_candidates([1, 2, "bad"], track_service=track_service) == [
        main_window.BulkAudioAttachTrackCandidate(
            track_id=1,
            title="Song",
            artist="Artist",
            album="Album",
            isrc="NL-AAA-26-00001",
        )
    ]
    assert app._media_attach_track_candidates([1], track_service=None)
    app.track_service = None
    assert app._media_attach_track_candidates([1]) == []

    track_service.album_art_states = {
        1: SimpleNamespace(can_replace_directly=True),
        2: SimpleNamespace(can_replace_directly=False),
    }
    assert app._album_art_attach_track_ids([1, 2, 3], track_service=track_service) == [1]
    assert app._album_art_attach_track_ids([1], track_service=None) == []

    audio_path = tmp_path / "Audio File.MP3"
    image_path = tmp_path / "Cover.JPG"
    image_path_2 = tmp_path / "Back.png"
    text_path = tmp_path / "notes.txt"
    missing_path = tmp_path / "missing.wav"
    for path in (audio_path, image_path, image_path_2, text_path):
        path.write_text("x", encoding="utf-8")
    assert app._prepare_media_attach_paths(
        "audio_file",
        ["", audio_path, audio_path, text_path, missing_path],
        title="Attach",
        allow_multiple=True,
        ignored_message="Unsupported files ignored.",
    ) == [str(audio_path)]
    assert information[-1][0] == "Attach"
    assert "notes.txt" in information[-1][1]
    assert (
        app._prepare_media_attach_paths(
            "album_art",
            [audio_path],
            title="Art",
            allow_multiple=False,
        )
        == []
    )
    assert information[-1] == ("Art", "No supported files were selected.")
    assert (
        app._prepare_media_attach_paths(
            "album_art",
            [image_path, image_path_2],
            title="Art",
            allow_multiple=False,
        )
        == []
    )
    assert information[-1] == ("Art", "Only a single image file can be attached at a time.")

    app.track_service = track_service
    add_track_events: list[tuple[str, str]] = []
    app.open_add_track_entry = lambda: add_track_events.append(("open", ""))
    app.audio_file_field = FakeLineEdit()
    app.album_art_field = FakeLineEdit()
    app.track_title_field = SimpleNamespace(setFocus=lambda: add_track_events.append(("focus", "")))
    app._refresh_line_edit_lossy_audio_warning = lambda widget: add_track_events.append(
        ("lossy", widget.text_value)
    )
    app._apply_audio_duration_to_widgets = lambda source_path, **_kwargs: add_track_events.append(
        ("duration", str(source_path))
    )
    app.track_len_h = hours
    app.track_len_m = minutes
    app.track_len_s = seconds
    app._open_add_track_with_media_source("audio_file", str(audio_path))
    app._open_add_track_with_media_source("album_art", str(image_path))
    assert ("lossy", str(audio_path)) in add_track_events
    assert ("duration", str(audio_path)) in add_track_events
    assert app.album_art_field.text_value == str(image_path)

    tracks = [
        main_window.BulkAudioAttachTrackCandidate(1, "Song", artist="Artist", album="Album"),
        main_window.BulkAudioAttachTrackCandidate(2, "Other", artist="Artist", album="Album"),
    ]
    matched, warning = app._build_album_art_attach_item(tmp_path / "Artist - Song.jpg", tracks)
    assert warning is None
    assert matched["status"] == "matched"
    assert matched["matched_track_id"] == 1
    assert matched["match_basis"] == "Filename track title + artist"
    ambiguous, _warning = app._build_album_art_attach_item(tmp_path / "Artist - Album.jpg", tracks)
    assert ambiguous["status"] == "ambiguous"
    assert ambiguous["candidate_track_ids"] == [1, 2]
    unmatched, _warning = app._build_album_art_attach_item(tmp_path / "Unknown.jpg", tracks)
    assert unmatched["status"] == "unmatched"
    progress: list[tuple[int, int, str]] = []
    items, plan_warnings = app._build_album_art_attach_plan(
        file_paths=[str(tmp_path / "Unknown.jpg")],
        tracks=tracks,
        progress_callback=lambda value, maximum, message: progress.append(
            (value, maximum, message)
        ),
    )
    assert items[0]["status"] == "unmatched"
    assert plan_warnings == []
    assert progress[-1] == (1, 1, "Album art matching finished.")

    app.track_service = None
    assert app._effective_artwork_payload_for_track(8) is None
    no_art_snapshot = SimpleNamespace(
        album_art_path="",
        album_art_blob_b64="",
        album_art_filename="",
        album_art_size_bytes=0,
        album_art_mime_type="",
    )
    assert (
        app._effective_artwork_payload_for_track(
            8,
            snapshot=no_art_snapshot,
            track_service=track_service,
        )
        is None
    )
    art_snapshot = SimpleNamespace(
        album_art_path="",
        album_art_blob_b64="",
        album_art_filename="cover.jpg",
        album_art_size_bytes=0,
        album_art_mime_type="",
    )
    payload = app._effective_artwork_payload_for_track(
        8,
        snapshot=art_snapshot,
        track_service=track_service,
        load_bytes=False,
    )
    assert payload is not None
    assert payload.data == b""
    assert payload.mime_type == "image/jpeg"
    track_service.media_bytes = (b"png", None)
    payload = app._effective_artwork_payload_for_track(
        8,
        snapshot=art_snapshot,
        track_service=track_service,
    )
    assert payload is not None
    assert payload.data == b"png"
    assert payload.mime_type == "image/jpeg"
    track_service.raise_media = True
    assert (
        app._effective_artwork_payload_for_track(
            8,
            snapshot=art_snapshot,
            track_service=track_service,
        )
        is None
    )


def test_main_window_clipboard_helper_covers_empty_select_all_headers_and_sparse_cells() -> None:
    require_qapplication()
    app = _app()
    clipboard = main_window.QApplication.clipboard()
    clipboard.setText("stale")

    app.table = SimpleNamespace(selectionModel=lambda: None, model=lambda: object())
    app._copy_selection_to_clipboard()
    assert clipboard.text() == ""

    class FakeIndex:
        def __init__(self, row: int, column: int) -> None:
            self._row = row
            self._column = column

        def row(self) -> int:
            return self._row

        def column(self) -> int:
            return self._column

    class FakeSelectionModel:
        def __init__(self) -> None:
            self.selection: list[FakeIndex] = []

        def hasSelection(self) -> bool:
            return bool(self.selection)

        def selectedIndexes(self):
            return list(self.selection)

    class FakeModel:
        def headerData(self, column: int, orientation):
            assert orientation == Qt.Horizontal
            return {0: "Title", 1: "Artist", 2: None}[column]

        def data(self, index: FakeIndex, role):
            assert role == Qt.DisplayRole
            return {
                (0, 0): "Song",
                (0, 2): "Album",
                (1, 1): "Artist",
            }.get((index.row(), index.column()))

    selection = FakeSelectionModel()

    class FakeTable:
        def __init__(self) -> None:
            self.select_all_calls = 0

        def selectionModel(self):
            return selection

        def model(self):
            return FakeModel()

        def selectAll(self) -> None:
            self.select_all_calls += 1
            selection.selection = [
                FakeIndex(0, 0),
                FakeIndex(0, 2),
                FakeIndex(1, 1),
            ]

    table = FakeTable()
    app.table = table
    app._copy_selection_to_clipboard(include_headers=True)
    assert table.select_all_calls == 1
    assert clipboard.text() == "Title\tArtist\t\nSong\t\tAlbum\n\tArtist\t"

    selection.selection = []
    table.selectAll = lambda: None
    app._copy_selection_to_clipboard()
    assert clipboard.text() == ""


def test_hidden_column_settings_parse_defaults_lists_and_invalid_payloads() -> None:
    app = _app()
    app._table_settings_prefix = lambda: "table/profile"
    app.settings = _Settings()
    defaults = app._load_hidden_columns_payload()
    assert all(occurrence == 0 for _name, occurrence in defaults)
    assert sorted(name for name, _occurrence in defaults) == sorted(
        main_window.DEFAULT_HIDDEN_CUSTOM_COLUMN_NAMES
    )

    key = app._hidden_columns_setting_key()
    app.settings = _Settings(
        {
            key: json.dumps(
                [
                    {"label": "Audio", "occurrence": "2"},
                    {"label": "", "occurrence": 1},
                    {"label": "Bad", "occurrence": "nope"},
                    ["ignored"],
                ]
            )
        }
    )
    assert app._load_hidden_columns_payload() == [("Audio", 2), ("Bad", 0)]

    app.settings = _Settings({key: {"not": "a list"}})
    assert app._load_hidden_columns_payload() == []
    app.settings = _Settings({key: "not json"})
    assert app._load_hidden_columns_payload() == []


def test_hidden_column_capture_write_clear_and_header_reorder_helpers() -> None:
    app = _app()
    app._table_settings_prefix = lambda: "table/profile"
    app._table_settings_prefix_for_path = lambda path: f"table/{Path(path).stem}"
    app.settings = _Settings()

    class Table:
        def __init__(self) -> None:
            self.hidden = {1, 3}

        def isColumnHidden(self, index: int) -> bool:
            return index in self.hidden

    app.table = Table()
    app._header_labels = lambda: ["Title", "Artist", "Title", "Hidden"]
    assert app._capture_hidden_columns_payload() == [
        {"label": "Artist", "occurrence": 0},
        {"label": "Hidden", "occurrence": 0},
    ]
    app._write_hidden_columns_setting()
    assert json.loads(app.settings.values[app._hidden_columns_setting_key()]) == [
        {"label": "Artist", "occurrence": 0},
        {"label": "Hidden", "occurrence": 0},
    ]
    assert app.settings.synced is True

    app._capture_hidden_columns_payload = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    app._write_hidden_columns_setting(sync=False)
    assert app.settings.values[app._hidden_columns_setting_key()] == "[]"

    app._clear_table_settings_for_path("/tmp/profile.db")
    assert "table/profile/header_state" in app.settings.removed
    assert "table/profile/hidden_column_keys_json" in app.settings.removed

    class Header:
        def __init__(self) -> None:
            self.order = [0, 1, 2]
            self.moves: list[tuple[int, int]] = []

        def visualIndex(self, logical_index: int) -> int:
            return self.order.index(logical_index)

        def moveSection(self, current_visual: int, target_visual: int) -> None:
            self.moves.append((current_visual, target_visual))
            logical = self.order.pop(current_visual)
            self.order.insert(target_visual, logical)

    header = Header()
    app.table = SimpleNamespace(horizontalHeader=lambda: header)
    app._catalog_view_column_count = lambda: 3
    app._catalog_header_text_for_column = lambda index: ["Title", "Artist", "Title"][index]
    app._apply_header_label_order(["Title", "Title", "Missing"])
    assert header.moves == [(2, 1)]
    assert header.order == [0, 2, 1]


def test_main_window_key_and_drop_event_routing_cover_handled_paths(monkeypatch) -> None:
    require_qapplication()
    app = _app()
    calls: list[str] = []

    class KeyEvent:
        def __init__(self, key: int) -> None:
            self._key = key

        def key(self) -> int:
            return self._key

    app.delete_entry = lambda: calls.append("delete")
    app.reset_search = lambda: calls.append("reset")
    app.save = lambda: calls.append("save")
    app.add_data_action = SimpleNamespace(isChecked=lambda: True)
    app._form_has_focus = lambda: True

    app.keyPressEvent(KeyEvent(Qt.Key_Delete))
    app.keyPressEvent(KeyEvent(Qt.Key_Escape))
    app.keyPressEvent(KeyEvent(Qt.Key_Return))
    app.add_data_action = SimpleNamespace(isChecked=lambda: False)
    app.keyPressEvent(KeyEvent(Qt.Key_Enter))
    assert calls == ["delete", "reset", "save"]

    zoom_event = SimpleNamespace(type=lambda: main_window.QEvent.User)
    app._handle_catalog_zoom_event = lambda _source, _event: True
    assert app.eventFilter(object(), zoom_event) is True

    class DropEvent:
        def __init__(self, event_type) -> None:
            self._event_type = event_type
            self.accepted = False

        def type(self):
            return self._event_type

        def acceptProposedAction(self) -> None:
            self.accepted = True

    source = QWidget()
    app._handle_catalog_zoom_event = lambda _source, _event: False
    app.isAncestorOf = lambda _source: True
    app._drop_event_local_file_paths = lambda _event: ["song.wav", "cover.png"]
    app._partition_dropped_media_paths = lambda paths: ([paths[0]], [paths[1]], [])
    drag_event = DropEvent(main_window.QEvent.DragEnter)
    assert app.eventFilter(source, drag_event) is True
    assert drag_event.accepted is True

    routed: list[list[str]] = []
    app._route_dropped_media_paths = lambda paths: routed.append(list(paths)) or True
    drop_event = DropEvent(main_window.QEvent.Drop)
    assert app.eventFilter(source, drop_event) is True
    assert drop_event.accepted is True
    assert routed == [["song.wav", "cover.png"]]

    class ValidIndex:
        def isValid(self) -> bool:
            return True

        def row(self) -> int:
            return 4

        def column(self) -> int:
            return 7

    class SpaceEvent:
        accepted = False

        def type(self):
            return main_window.QEvent.KeyPress

        def key(self):
            return Qt.Key_Space

        def accept(self) -> None:
            self.accepted = True

    previews: list[tuple[int, int]] = []
    app.table = SimpleNamespace(currentIndex=lambda: ValidIndex())
    app._preview_catalog_blob_for_cell = lambda row, column: previews.append((row, column))
    space_event = SpaceEvent()
    assert app.eventFilter(app.table, space_event) is True
    assert space_event.accepted is True
    assert previews == [(4, 7)]


def test_main_window_storage_conversion_blob_export_and_badge_workflows(
    monkeypatch,
    tmp_path: Path,
) -> None:
    require_qapplication()
    app = _app()
    database = main_window.STORAGE_MODE_DATABASE
    managed = main_window.STORAGE_MODE_MANAGED_FILE
    warnings: list[tuple[str, str]] = []
    information: list[tuple[str, str]] = []
    criticals: list[tuple[str, str]] = []
    exports: list[dict[str, object]] = []
    audio_exports: list[dict[str, object]] = []
    attached: list[dict[str, object]] = []
    refreshes: list[int | None] = []
    rollbacks: list[str] = []
    logged: list[tuple[str, dict[str, object]]] = []
    ui_progress: list[str] = []
    background_errors: list[tuple[str, str]] = []

    monkeypatch.setattr(
        main_window.QMessageBox,
        "warning",
        lambda _parent, title, message: warnings.append((title, message)),
    )
    monkeypatch.setattr(
        main_window.QMessageBox,
        "information",
        lambda _parent, title, message: information.append((title, message)),
    )
    monkeypatch.setattr(
        main_window.QMessageBox,
        "critical",
        lambda _parent, title, message: criticals.append((title, message)),
    )

    class FakeLogger:
        def exception(self, message: str, *args) -> None:
            logged.append(("exception", {"message": message, "args": args}))

        def warning(self, message: str, *args) -> None:
            logged.append(("warning", {"message": message, "args": args}))

    class FakeConn:
        def __init__(self) -> None:
            self.commit_calls = 0
            self.rollback_calls = 0
            self.raise_commit = False

        def cursor(self):
            return self

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def commit(self) -> None:
            self.commit_calls += 1
            if self.raise_commit:
                raise RuntimeError("commit failed")

        def rollback(self) -> None:
            self.rollback_calls += 1
            rollbacks.append("rollback")

    class FakeFieldDefinitions:
        def get_field_type(self, field_id: int) -> str:
            return {10: "blob_audio", 20: "blob_image"}.get(int(field_id), "blob_image")

        def get_field_name(self, field_id: int) -> str:
            return {10: "Session Audio", 20: "Artwork"}.get(int(field_id), "Unknown")

    class FakeCustomValues:
        fetch_raises = False

        def __init__(self) -> None:
            self.saved: list[dict[str, object]] = []
            self.deleted: list[tuple[int, int]] = []
            self.converted: list[tuple[int, int, str]] = []

        def save_value(self, track_id: int, field_id: int, **kwargs) -> None:
            self.saved.append({"track_id": track_id, "field_id": field_id, **kwargs})

        def convert_storage_mode(self, track_id: int, field_id: int, target_mode: str) -> None:
            self.converted.append((track_id, field_id, target_mode))

        def get_value_meta(self, track_id: int, field_id: int, **kwargs):
            assert kwargs.get("include_storage_details") is True
            if track_id == 8:
                return {"has_blob": True, "storage_mode": database, "mime_type": "audio/wav"}
            if track_id == 9:
                return {"has_blob": True, "storage_mode": database, "mime_type": "image/png"}
            return {"has_blob": False}

        def has_blob(self, track_id: int, field_id: int) -> bool:
            return track_id == 8 and field_id == 10

        def blob_size(self, track_id: int, field_id: int) -> int:
            return 2048 if (track_id, field_id) == (8, 10) else 0

        def fetch_blob(self, track_id: int, field_id: int):
            if self.fetch_raises:
                raise RuntimeError("blob missing")
            return b"blob-bytes", "image/png"

        def delete_blob(self, track_id: int, field_id: int) -> None:
            self.deleted.append((track_id, field_id))

    app.logger = FakeLogger()
    app.conn = FakeConn()
    app.custom_field_definitions = FakeFieldDefinitions()
    custom_values = FakeCustomValues()
    app.custom_field_values = custom_values
    app.refresh_table_preserve_view = lambda focus_id=None: refreshes.append(focus_id)
    app._export_bytes_with_picker = lambda *args, **kwargs: exports.append(kwargs)
    app._submit_background_audio_file_export = lambda **kwargs: audio_exports.append(kwargs)
    app._default_export_filename = lambda basename, mime: f"{basename}.{mime.split('/')[-1]}"
    app._resolve_file_export_target = lambda path, **_kwargs: (
        (_ for _ in ()).throw(ValueError("bad export target"))
        if str(path).endswith("bad.wav")
        else Path(path)
    )

    assert app.cf_has_blob(8, 10) is True
    assert app.cf_blob_size(8, 10) == 2048
    assert app.cf_fetch_blob(8, 10) == (b"blob-bytes", "image/png")
    app.cf_convert_blob_storage_mode(8, 10, managed)
    app.cf_delete_blob(8, 10)
    assert custom_values.converted == [(8, 10, managed)]
    assert custom_values.deleted == [(8, 10)]

    save_paths = iter(
        [
            ("", ""),
            (str(tmp_path / "bad.wav"), ""),
            (str(tmp_path / "good.wav"), ""),
        ]
    )
    monkeypatch.setattr(
        main_window.QFileDialog,
        "getSaveFileName",
        lambda *_args, **_kwargs: next(save_paths),
    )
    app.cf_export_blob(8, 10)
    assert audio_exports == []
    app.cf_export_blob(8, 10)
    assert warnings[-1] == ("Export", "bad export target")
    app.cf_export_blob(8, 10)
    assert audio_exports[-1]["resolved_dest_path"] == tmp_path / "good.wav"
    assert audio_exports[-1]["load_source"](SimpleNamespace(custom_field_values=custom_values)) == (
        b"blob-bytes",
        "image/png",
    )

    custom_values.fetch_raises = True
    app.cf_export_blob(8, 20, parent_widget="parent")
    assert criticals[-1] == ("Export failed", "blob missing")
    custom_values.fetch_raises = False
    app.cf_export_blob(8, 20, suggested_basename="Manual Name")
    assert exports[-1]["suggested_basename"] == "Manual Name"
    assert exports[-1]["payload"] == {"track_id": 8, "field_id": 20}

    open_paths = iter(["", str(tmp_path / "image.png"), str(tmp_path / "audio.wav")])
    monkeypatch.setattr(
        main_window.QFileDialog,
        "getOpenFileName",
        lambda *_args, **_kwargs: (next(open_paths), ""),
    )
    prompt_modes = iter([None, database])
    monkeypatch.setattr(
        main_window,
        "_prompt_storage_mode_choice",
        lambda *_args, **_kwargs: next(prompt_modes),
    )

    app._attach_blob_for_cell(8, 20, "blob_image", "Artwork")
    app._attach_blob_for_cell(8, 20, "blob_image", "Artwork")

    def run_history_action(**kwargs):
        attached.append(kwargs)
        kwargs["mutation"]()

    app._run_snapshot_history_action = run_history_action
    app._attach_blob_for_cell(8, 10, "blob_audio", "Session Audio")
    assert attached[-1]["payload"]["storage_mode"] == database
    assert custom_values.saved[-1]["blob_path"] == str(tmp_path / "audio.wav")
    assert refreshes[-1] == 8

    monkeypatch.setattr(
        main_window.QFileDialog,
        "getOpenFileName",
        lambda *_args, **_kwargs: (str(tmp_path / "again.wav"), ""),
    )
    monkeypatch.setattr(
        main_window,
        "_prompt_storage_mode_choice",
        lambda *_args, **_kwargs: database,
    )
    app._run_snapshot_history_action = lambda **_kwargs: (_ for _ in ()).throw(
        RuntimeError("history failed")
    )
    app._attach_blob_for_cell(8, 10, "blob_audio", "Session Audio")
    assert rollbacks == ["rollback"]
    assert criticals[-1][0] == "Custom Field Error"

    def meta_loader(track_id: int):
        if track_id == 4:
            raise RuntimeError("meta read failed")
        return {
            1: {"has_media": True, "storage_mode": managed},
            2: {"has_blob": True, "storage_mode": database},
            3: {"has_media": False, "storage_mode": managed},
        }.get(track_id)

    scope = app._classify_storage_conversion_scope([1, "2", "bad", 3, 4], meta_loader=meta_loader)
    assert scope["available_track_ids"] == [1, 2]
    assert scope["missing_track_ids"] == [3, 4]
    assert scope["allowed_targets"] == [managed, database]
    assert scope["targets"][database]["convert_track_ids"] == [1]
    assert scope["targets"][database]["skip_track_ids"] == [2]
    app.track_service = None
    app.custom_field_values = None
    assert app._standard_media_storage_conversion_scope([1], "audio_file")["scope_track_ids"] == []
    assert app._custom_blob_storage_conversion_scope([1], 20)["scope_track_ids"] == []
    app.custom_field_values = custom_values

    assert App._storage_conversion_action_label(database, selection_count=1) == "Store in Database"
    assert App._storage_conversion_action_label(managed, selection_count=2) == (
        "Store selection as managed file"
    )
    assert App._storage_conversion_target_label(database) == "database storage"
    assert App._storage_conversion_target_label(managed) == "managed-file storage"

    no_change_lines = app._storage_conversion_summary_lines(
        {
            "column_label": "Audio File",
            "target_mode": managed,
            "converted_track_ids": [],
            "skipped_track_ids": [1],
            "missing_track_ids": [2, 3],
            "failed": [{"track_id": 4, "label": "", "message": ""}],
        }
    )
    assert no_change_lines[0] == "No selected tracks required conversion for 'Audio File'."
    assert "Track 4: Unknown error" in no_change_lines[-1]

    class FakeTrackService:
        def get_media_meta(self, track_id: int, media_key: str, **_kwargs):
            assert media_key == "audio_file"
            return {
                1: {"has_media": True, "storage_mode": managed},
                2: {"has_media": True, "storage_mode": managed},
                3: {"has_media": True, "storage_mode": database},
                4: {"has_media": False, "storage_mode": managed},
            }[track_id]

        def convert_media_storage_mode(
            self, track_id: int, media_key: str, target_mode: str, **_kwargs
        ) -> None:
            if track_id == 2:
                raise RuntimeError("cannot convert")

        def fetch_track_snapshot(self, track_id: int, **_kwargs):
            return SimpleNamespace(track_title="" if track_id == 2 else f"Track {track_id}")

    class FakeContext:
        def __init__(self) -> None:
            self.progress: list[str] = []

        def report_progress(self, **kwargs) -> None:
            self.progress.append(str(kwargs.get("message", "")))

        def raise_if_cancelled(self) -> None:
            return None

    app._scaled_progress_callback = lambda callback, *, start, end: lambda **kwargs: callback(
        value=start + int(kwargs.get("value", 0)),
        maximum=end,
        message=kwargs.get("message", ""),
    )
    app._advance_task_ui_progress = lambda progress, **kwargs: progress(**kwargs)
    app._refresh_history_actions = lambda: refreshes.append(None)
    app._log_event = lambda name, _message, **kwargs: logged.append((name, kwargs))
    app._show_background_task_error = (
        lambda title, _failure, *, user_message: background_errors.append((title, user_message))
    )
    app.conn.raise_commit = True

    def run_snapshot_history_action(**kwargs):
        return kwargs["mutation"]()

    monkeypatch.setattr(main_window, "run_snapshot_history_action", run_snapshot_history_action)

    def submit_standard_task(**kwargs):
        ctx = FakeContext()
        result = kwargs["task_fn"](
            SimpleNamespace(
                conn=app.conn,
                track_service=FakeTrackService(),
                history_manager=object(),
            ),
            ctx,
        )
        kwargs["on_success_before_cleanup"](
            result,
            lambda **progress: ui_progress.append(str(progress.get("message", ""))),
        )
        kwargs["on_success_after_cleanup"](result)
        kwargs["on_error"](SimpleNamespace(message="background failed"))

    app._submit_background_bundle_task = submit_standard_task
    app._submit_storage_conversion_task(
        track_ids=[1, 2, 3, 4],
        target_mode=database,
        scope_kind="standard",
        column_label="Audio File",
        media_key="audio_file",
    )
    assert 1 in refreshes
    assert logged[-1][0] == "storage.convert"
    assert len(logged[-1][1]["converted_track_ids"]) == 1
    assert logged[-1][1]["failures"][0]["track_id"] == 2
    assert warnings[-1][0] == "Convert Audio File Storage"
    assert "Converted 1 selected track to database storage" in warnings[-1][1]
    assert "Failures (1 track):" in warnings[-1][1]
    assert background_errors[-1] == (
        "Convert Audio File Storage",
        "Could not convert storage mode:",
    )
    assert "Storage conversion complete." in ui_progress

    class FakeTable:
        def __init__(self) -> None:
            self.updated = False

        def viewport(self):
            return self

        def update(self) -> None:
            self.updated = True

    app.table = FakeTable()
    app.conn.raise_commit = False

    def submit_custom_task(**kwargs):
        result = kwargs["task_fn"](
            SimpleNamespace(
                conn=app.conn,
                custom_field_values=custom_values,
                history_manager=object(),
            ),
            FakeContext(),
        )
        kwargs["on_success_before_cleanup"](
            result,
            lambda **progress: ui_progress.append(str(progress.get("message", ""))),
        )
        kwargs["on_success_after_cleanup"](result)

    app._submit_background_bundle_task = submit_custom_task
    app._convert_custom_blob_storage_mode(9, 20, database)
    assert app.table.updated is True
    assert information[-1][0] == "Convert Artwork Storage"
    assert "No selected tracks required conversion" in information[-1][1]

    assert app._human_size(1536) == "1.5 KB"
    assert app._format_blob_badge("ignored/type", 1024) == "1 KB"
    assert App._storage_mode_badge_label(managed) == "Managed-file storage"
    assert App._blob_icon_kind_for_storage("audio", storage_mode=managed) == "audio_managed"
    assert (
        App._blob_icon_kind_for_storage("audio", storage_mode=database, is_lossy=True)
        == "audio_lossy_database"
    )
    assert App._blob_icon_kind_for_standard_media("album_art", meta={}) == "image_database"
    assert "Lossy primary audio" in app._standard_media_badge_tooltip(
        "audio_file",
        {"storage_mode": database, "is_lossy": True, "format_label": "MP3"},
        "3 MB",
    )
    assert (
        app._standard_media_badge_tooltip(
            "album_art",
            {"storage_mode": managed},
            "12 KB",
        )
        == "Managed-file storage\nStored size: 12 KB"
    )

    app.blob_icon_settings = main_window.default_blob_icon_settings()
    assert app._blob_icon_spec_for_standard_media("audio_file", meta={"storage_mode": database})
    assert app._blob_icon_spec_for_custom_field_with_meta(
        {"field_type": "blob_audio", "blob_icon_payload": {"mode": "inherit"}},
        meta={"storage_mode": managed},
    ) == {"mode": "inherit"}
    assert app._blob_icon_spec_for_custom_field({"field_type": "blob_image"})
    app._reset_blob_badge_render_cache = lambda: setattr(app, "_blob_badge_icon_cache", {})
    app.style = lambda: None
    icon = app._resolve_blob_badge_icon(
        spec={"mode": "inherit"},
        kind="audio_database",
        size=12,
    )
    assert not icon.isNull()
    cached = app._resolve_blob_badge_icon(
        spec={"mode": "inherit"},
        kind="audio_database",
        size=12,
    )
    assert not cached.isNull()

    app.active_custom_fields = [{"id": "bad"}, {"id": 20}]
    assert app._custom_field_index_by_id(20) == 1
    assert app._custom_field_index_by_id(99) == -1
    app.track_service = SimpleNamespace(fetch_track_title=lambda track_id, **_kwargs: "A/B:C")
    app.cursor = object()
    assert app._make_default_export_filename(8, {}, "application/octet-stream") == "A_B_C.bin"
    app.catalog_reads = SimpleNamespace(list_tracks=lambda: ["track"])
    assert app._list_all_tracks() == ["track"]


def test_main_window_table_header_layout_visibility_and_state_workflows(monkeypatch) -> None:
    require_qapplication()
    app = _app()
    app.settings = _Settings()
    app.current_db_path = "/tmp/music-catalog.db"
    app.BASE_HEADERS = ["Track Title", "Unmapped Header"]
    app.active_custom_fields = [
        {"id": "bad", "name": "Broken Custom"},
        {"id": 44, "name": "Lyrics"},
        {"name": "Detached Custom"},
    ]
    labels = ["Track Title", "Unmapped Header", "Broken Custom", "Lyrics", "Detached Custom"]
    history_actions: list[dict[str, object]] = []
    save_calls: list[object] = []
    restore_calls: list[object] = []
    visibility_calls: list[object] = []
    checked_states: list[bool] = []
    menu_toggles: list[tuple[int, bool]] = []
    logger_messages: list[str] = []

    assert app._table_settings_prefix().startswith("table/")
    assert (
        app._catalog_header_state_manager(path="/tmp/other.db")
        .settings_prefix()
        .startswith("table/")
    )
    assert app._header_label_for_logical_index(0) == ""

    class FakeModel:
        def headerData(self, logical_index: int, orientation, role):
            assert orientation == Qt.Horizontal
            assert role == Qt.DisplayRole
            return labels[logical_index]

    class FakeHeader:
        def __init__(self) -> None:
            self.movable = False
            self.visuals = {0: 2, 1: 0, 2: -1, 3: 1, 4: 4}

        def setSectionsMovable(self, enabled: bool) -> None:
            self.movable = bool(enabled)

        def sectionsMovable(self) -> bool:
            return self.movable

        def visualIndex(self, logical_index: int) -> int:
            return self.visuals.get(logical_index, logical_index)

    class FakeTable:
        def __init__(self) -> None:
            self.hidden = {1, 3}
            self.header = FakeHeader()
            self.hidden_updates: list[tuple[int, bool]] = []

        def model(self):
            return FakeModel()

        def horizontalHeader(self):
            return self.header

        def isColumnHidden(self, logical_index: int) -> bool:
            return logical_index in self.hidden

        def setColumnHidden(self, logical_index: int, hidden: bool) -> None:
            self.hidden_updates.append((logical_index, hidden))
            if hidden:
                self.hidden.add(logical_index)
            else:
                self.hidden.discard(logical_index)

    class FakeController:
        def __init__(self, host) -> None:
            self.host = host
            self.view = None
            self.models = None

        def bind_view(self, view) -> None:
            self.view = view

        def bind_models(self, **kwargs) -> None:
            self.models = kwargs

    app.table = FakeTable()
    app._catalog_view_column_count = lambda: len(labels)
    app._catalog_source_model = lambda: "source-model"
    app._catalog_proxy_model = lambda: "proxy-model"
    monkeypatch.setattr(main_window, "CatalogTableController", FakeController)

    controller = app._catalog_table_controller()
    assert app._catalog_table_controller() is controller
    assert controller.view is app.table
    assert controller.models == {"table_model": "source-model", "filter_proxy": "proxy-model"}
    assert app._header_label_for_logical_index(2) == "Broken Custom"
    assert App._fallback_header_column_key("  Odd Header! ", prefix="base", logical_index=7) == (
        "base:odd_header:7"
    )
    assert App._fallback_header_column_key("", prefix="custom", logical_index=8) == (
        "custom:column:8"
    )

    specs = app._catalog_header_column_specs()
    assert [spec.header_text for spec in specs] == labels
    assert specs[0].key.startswith("base:")
    assert specs[1].key == "base:unmapped_header:1"
    assert specs[2].key == "custom:broken_custom:2"
    assert specs[3].key == "custom:44"
    assert specs[3].hidden_by_default is True
    assert specs[4].key == "custom:detached_custom:4"
    assert app._default_header_labels() == [
        "Track Title",
        "Unmapped Header",
    ] + [field.get("name") for field in app.active_custom_fields]

    app._suspend_layout_history = False
    app._table_setting_keys = lambda **_kwargs: ["layout-key"]
    app._table_settings_prefix = lambda: "table/profile"

    def run_setting_action(**kwargs):
        history_actions.append(kwargs)
        kwargs["mutation"]()

    app._run_setting_bundle_history_action = run_setting_action
    app._save_header_state = lambda **kwargs: save_calls.append(("toggle", kwargs))
    app._toggle_columns_movable(True)
    assert app.table.horizontalHeader().sectionsMovable() is True
    assert save_calls[-1] == ("toggle", {"record_history": False})
    assert history_actions[-1]["action_label"] == "Toggle Column Reordering"

    app.logger = SimpleNamespace(
        warning=lambda message, *args: logger_messages.append(message % args),
        exception=lambda message, *args: logger_messages.append(message % args),
    )
    app._run_setting_bundle_history_action = lambda **_kwargs: (_ for _ in ()).throw(
        RuntimeError("history failed")
    )
    app._toggle_columns_movable(False)
    assert any("Exception while toggling columns movable" in message for message in logger_messages)

    class FakeStateManager:
        def save_state(self, header, *, column_specs) -> None:
            save_calls.append(("save", header, tuple(column_specs)))

        def restore_state(self, header, *, column_specs) -> None:
            restore_calls.append((header, tuple(column_specs)))

        def restore_visibility(self, header, *, column_specs) -> None:
            visibility_calls.append((header, tuple(column_specs)))

    app._catalog_header_state_manager = lambda: FakeStateManager()
    app._catalog_header_column_specs = lambda: ("spec-a", "spec-b")
    app._run_setting_bundle_history_action = run_setting_action
    app._save_header_state = App._save_header_state.__get__(app, App)
    app._save_header_state()
    assert save_calls[-1][0] == "save"
    assert history_actions[-1]["action_label"] == "Update Table Layout"
    app._save_header_state(record_history=False)
    assert save_calls[-1][0] == "save"

    app._catalog_header_state_manager = lambda: (_ for _ in ()).throw(RuntimeError("save failed"))
    app._save_header_state()
    assert any("Error saving header state" in message for message in logger_messages)

    app._catalog_header_state_manager = lambda: FakeStateManager()
    app._apply_saved_column_visibility()
    assert visibility_calls
    assert app._suspend_layout_history is False

    app._catalog_view_column_count = lambda: 5
    app._catalog_header_text_for_column = lambda index: labels[index]
    app._save_header_state = lambda **kwargs: save_calls.append(("visibility", kwargs))
    app._rebuild_search_column_choices = lambda: save_calls.append(("rebuild", {}))
    app._apply_catalog_search_filter = lambda: save_calls.append(("filter", {}))
    app._refresh_column_visibility_menu = lambda: save_calls.append(("menu", {}))
    app._run_setting_bundle_history_action = run_setting_action
    app._toggle_column_visibility(-1, True)
    assert app.table.hidden_updates == []
    app._toggle_column_visibility(3, True)
    assert app.table.hidden_updates[-1] == (3, False)
    assert history_actions[-1]["entity_id"] == "table/profile/column_visibility"
    assert app._suspend_layout_history is False

    columns_menu = main_window.QMenu()
    previous_actions = [main_window.QAction("Old", columns_menu)]
    columns_menu.addAction(previous_actions[0])
    app.columns_menu = columns_menu
    app.column_visibility_actions = previous_actions
    app._refresh_column_visibility_menu = App._refresh_column_visibility_menu.__get__(app, App)
    app._toggle_column_visibility = lambda logical_index, visible: menu_toggles.append(
        (logical_index, visible)
    )
    app.table.hidden.add(3)
    app._refresh_column_visibility_menu()
    assert [action.text() for action in app.column_visibility_actions] == [
        "Unmapped Header",
        "Lyrics",
        "Track Title",
        "Detached Custom",
        "Broken Custom",
    ]
    app.column_visibility_actions[1].setChecked(True)
    assert menu_toggles[-1] == (3, True)

    app._catalog_header_state_manager = lambda: FakeStateManager()
    app.act_reorder_columns = object()
    app._set_action_checked_silently = lambda _action, checked: checked_states.append(bool(checked))
    app._refresh_column_visibility_menu = lambda: restore_calls.append(("menu", ()))
    app._rebuild_search_column_choices = lambda: restore_calls.append(("rebuild", ()))
    app.table.horizontalHeader().setSectionsMovable(True)
    app._load_header_state()
    assert restore_calls[0][1] == ("spec-a", "spec-b")
    assert checked_states[-1] is True
    assert app._suspend_layout_history is False

    app._catalog_header_state_manager = lambda: (_ for _ in ()).throw(RuntimeError("load failed"))
    app._load_header_state()
    assert any("Error loading header state" in message for message in logger_messages)


def test_table_layout_history_hint_and_resize_edge_paths(monkeypatch) -> None:
    app = _app()
    events: list[object] = []
    warnings: list[str] = []
    saves: list[dict[str, object]] = []

    class FakeSignal:
        def __init__(self, *, fail_disconnect: bool = False) -> None:
            self.fail_disconnect = fail_disconnect
            self.connected: list[object] = []
            self.disconnected: list[object] = []

        def connect(self, slot) -> None:
            self.connected.append(slot)

        def disconnect(self, slot) -> None:
            self.disconnected.append(slot)
            if self.fail_disconnect:
                raise RuntimeError("disconnect failed")

    class FakeHeader:
        def __init__(self) -> None:
            self.sectionMoved = FakeSignal(fail_disconnect=True)
            self.sectionResized = FakeSignal(fail_disconnect=True)
            self.resize_modes: list[tuple[object, ...]] = []
            self.stretch_states: list[bool] = []

        def setSectionResizeMode(self, *args) -> None:
            self.resize_modes.append(args)

        def setStretchLastSection(self, enabled: bool) -> None:
            self.stretch_states.append(bool(enabled))

    class FakeVerticalHeader(FakeHeader):
        pass

    class FakeTable:
        def __init__(self) -> None:
            self.header = FakeHeader()
            self.vertical = FakeVerticalHeader()
            self.resized_columns = 0
            self.row_heights: list[tuple[int, int]] = []

        def horizontalHeader(self):
            return self.header

        def verticalHeader(self):
            return self.vertical

        def resizeColumnsToContents(self) -> None:
            self.resized_columns += 1

        def setRowHeight(self, row: int, height: int) -> None:
            self.row_heights.append((row, height))

    class FakeLabel:
        def __init__(self) -> None:
            self.moves: list[object] = []
            self.visible = False
            self._user_moved = True

        def move(self, pos) -> None:
            self.moves.append(pos)

        def show(self) -> None:
            self.visible = True

        def hide(self) -> None:
            self.visible = False

    monkeypatch.setattr(main_window.QTimer, "singleShot", lambda _ms, callback: callback())

    app.table = FakeTable()
    app._suspend_layout_history = False
    app._unbind_header_state_signals = lambda: events.append("unbind")
    app._bind_header_state_signals = lambda: (_ for _ in ()).throw(RuntimeError("bind failed"))
    app.logger = SimpleNamespace(warning=lambda message, *args: warnings.append(message % args))

    with app._suspend_table_layout_history():
        assert app._suspend_layout_history is True
        events.append("inside")
    assert app._suspend_layout_history is False
    assert events == ["unbind", "inside"]
    assert "Failed to rebind header history signals: bind failed" in warnings[-1]

    app._bind_header_state_signals = lambda: events.append("bind")
    app.identity = None
    app.theme_settings = None
    app.blob_icon_settings = None
    app.active_custom_fields = []
    app._load_identity = lambda: "identity"
    app._load_theme_settings = lambda: {"theme": "dark"}
    app._load_blob_icon_settings = lambda: {"icons": "default"}
    app._apply_identity = lambda: events.append("identity")
    app._apply_theme = lambda: events.append("theme")
    app.load_active_custom_fields = lambda: [{"name": "Lyrics"}]
    app._rebuild_table_headers = lambda: events.append("headers")
    app._load_header_state = lambda: (_ for _ in ()).throw(RuntimeError("header failed"))
    app._apply_saved_hint_positions = lambda: events.append("hints")
    app._apply_saved_view_preferences = lambda: (_ for _ in ()).throw(RuntimeError("view failed"))
    app.populate_all_comboboxes = lambda: events.append("combos")
    app._update_add_data_generated_fields = lambda: events.append("generated")
    app.refresh_table_preserve_view = lambda: events.append("refresh")
    app._refresh_catalog_workspace_docks = lambda: events.append("docks")
    app._refresh_auto_snapshot_schedule = lambda: events.append("schedule")
    app._current_auto_snapshot_marker = lambda: 7
    app._refresh_history_actions = lambda: events.append("history-actions")
    app._refresh_after_history_change()
    assert app.identity == "identity"
    assert app._last_auto_snapshot_marker == 7
    assert "history-actions" in events

    point = main_window.QPoint(3, 4)
    moved_label = FakeLabel()
    app.settings = SimpleNamespace(
        value=lambda key, **_kwargs: point if key == "display/col_hint_pos" else None
    )
    app.col_hint_label = moved_label
    app.row_hint_label = None
    App._apply_saved_hint_positions(app)
    assert moved_label.moves == [point]

    app._save_header_state = lambda **kwargs: saves.append(kwargs)
    app._suspend_layout_history = True
    app._on_header_layout_changed()
    app._on_header_sections_reordered()
    assert saves == []
    app._suspend_layout_history = False
    app._table_settings_prefix = lambda: "table/profile"
    app._on_header_layout_changed()
    app._on_header_sections_reordered()
    assert saves[-2:] == [
        {},
        {
            "action_label": "Reorder Columns",
            "history_entity_id": "table/profile/column_order",
        },
    ]

    app.col_width_action = SimpleNamespace(isChecked=lambda: False)
    assert app._should_record_header_resize_history() is False
    app.col_width_action = SimpleNamespace(isChecked=lambda: True)
    monkeypatch.setattr(
        main_window,
        "QApplication",
        SimpleNamespace(mouseButtons=lambda: main_window.Qt.LeftButton),
    )
    assert app._should_record_header_resize_history() is True
    app._on_header_sections_resized()
    assert saves[-1] == {
        "action_label": "Adjust Column Widths",
        "history_entity_id": "table/profile/column_widths",
    }
    monkeypatch.setattr(
        main_window,
        "QApplication",
        SimpleNamespace(mouseButtons=lambda: (_ for _ in ()).throw(RuntimeError("mouse failed"))),
    )
    assert app._should_record_header_resize_history() is False

    app._header_layout_signals_bound = False
    App._unbind_header_state_signals(app)
    app._header_layout_signals_bound = True
    app._header_section_moved_wrapper = "moved"
    app._header_section_resized_wrapper = "resized"
    App._unbind_header_state_signals(app)
    assert app._header_layout_signals_bound is False
    assert app._header_section_moved_wrapper is None
    assert app._header_section_resized_wrapper is None

    del app.table
    App._bind_header_state_signals(app)
    app.table = FakeTable()
    app._connect_args_signal = lambda signal, _owner, slot: signal.connected.append(slot) or slot
    App._bind_header_state_signals(app)
    assert app._header_layout_signals_bound is True
    assert app.table.horizontalHeader().sectionMoved.connected

    app._catalog_view_column_count = lambda: 2
    app._catalog_view_row_count = lambda: 3
    app.table = FakeTable()
    app.table.horizontalHeader().sectionResized.fail_disconnect = False
    app.table.verticalHeader().sectionResized.fail_disconnect = False
    app.col_hint_label = FakeLabel()
    app.row_hint_label = FakeLabel()
    app._col_hint_signal_bound = True
    app._row_hint_signal_bound = True
    app._ensure_col_hint_label = lambda: events.append("ensure-col")
    app._ensure_row_hint_label = lambda: events.append("ensure-row")
    app._apply_table_view_settings = lambda: events.append("view-settings")
    app._reset_hint_label = lambda: events.append("reset-hints")
    app.col_width_action = SimpleNamespace(isChecked=lambda: False)
    app._apply_col_width_mode(True)
    app._apply_col_width_mode(False)
    assert app.table.horizontalHeader().stretch_states == [False, True]
    assert app.table.resized_columns == 1
    assert app.col_hint_label.visible is False

    app._apply_row_height_mode(True)
    app._apply_row_height_mode(False)
    assert app.table.row_heights == [(0, 24), (1, 24), (2, 24)]
    assert app.row_hint_label.visible is False


def test_catalog_track_choices_uses_model_columns_and_title_fallbacks() -> None:
    app = _app()

    class Model:
        def rowCount(self) -> int:
            return 3

        def index(self, row: int, column: int):
            return (row, column)

        def data(self, index, role):
            assert role == Qt.DisplayRole
            return {
                (0, 1): "Model Title",
                (0, 2): "Artist",
                (0, 3): "Album",
                (1, 1): "",
                (1, 2): "",
                (1, 3): "Album B",
            }.get(index, "")

    class Controller:
        def active_model(self):
            return Model()

        def column_for_key(self, key: str):
            return {
                "base:track_title": 1,
                "base:artist_name": 2,
                "base:album_title": 3,
            }.get(key)

        def track_id_for_index(self, index):
            row, _column = index
            return {0: 10, 1: 11, 2: None}[row]

    app._catalog_table_controller = lambda: Controller()
    app._get_track_title = lambda track_id: f"Fallback {track_id}"

    choices = app._catalog_track_choices()
    assert choices == [
        TrackChoice(track_id=10, title="Model Title", subtitle="Artist / Album"),
        TrackChoice(track_id=11, title="Fallback 11", subtitle="Album B"),
    ]

    app._catalog_table_controller = lambda: SimpleNamespace(active_model=lambda: None)
    assert app._catalog_track_choices() == []


def test_background_task_helpers_cover_runtime_status_error_and_scaled_progress(
    monkeypatch,
) -> None:
    app = _app()
    configured: list[dict[str, object]] = []
    checkpoints: list[tuple[object, str]] = []
    monkeypatch.setattr(
        main_window.DatabaseWriteCoordinator,
        "for_path",
        lambda db_path: ("lock", db_path),
    )
    monkeypatch.setattr(
        main_window,
        "safe_wal_checkpoint",
        lambda conn, *, mode, logger: checkpoints.append((conn, mode)),
    )

    app.settings = SimpleNamespace(fileName=lambda: "/tmp/settings.ini")
    app.current_db_path = " /tmp/catalog.db "
    app.background_service_factory = SimpleNamespace(
        configure=lambda **kwargs: configured.append(kwargs)
    )
    app._configure_background_runtime()
    assert configured == [{"db_path": "/tmp/catalog.db", "settings_path": "/tmp/settings.ini"}]
    assert app._background_write_lock == ("lock", "/tmp/catalog.db")
    app.current_db_path = ""
    app._configure_background_runtime()
    assert configured[-1] == {"db_path": None, "settings_path": "/tmp/settings.ini"}
    assert app._background_write_lock is None

    app_without_factory = _app()
    app_without_factory.current_db_path = ""
    app_without_factory._configure_background_runtime()
    assert app_without_factory._background_write_lock is None

    shown_messages: list[str] = []
    cleared: list[bool] = []
    status_bar = SimpleNamespace(
        showMessage=lambda message: shown_messages.append(message),
        clearMessage=lambda: cleared.append(True),
    )
    app.findChildren = lambda *_args, **_kwargs: []
    app.background_tasks = SimpleNamespace(has_running_tasks=lambda: True)
    app._on_background_task_state_changed()
    assert shown_messages == []
    app.findChildren = lambda *_args, **_kwargs: [status_bar]
    app.background_tasks = SimpleNamespace(
        has_running_tasks=lambda: True,
        active_task_titles=lambda: ["One", "Two", "Three", "Four"],
    )
    app._on_background_task_state_changed()
    assert shown_messages == ["Background tasks running: One, Two, Three, ..."]
    app.background_tasks = SimpleNamespace(has_running_tasks=lambda: False)
    app._on_background_task_state_changed()
    assert cleared == [True]

    class Conn:
        def __init__(self, *, fail_commit: bool = False) -> None:
            self.fail_commit = fail_commit
            self.commits = 0

        def commit(self) -> None:
            self.commits += 1
            if self.fail_commit:
                raise RuntimeError("commit failed")

    app.logger = SimpleNamespace(error=lambda *_args, **_kwargs: None)
    app.conn = None
    app._prepare_for_background_db_task()
    app.conn = Conn()
    app._prepare_for_background_db_task()
    assert app.conn.commits == 1
    assert checkpoints == [(app.conn, "PASSIVE")]
    app.conn = Conn(fail_commit=True)
    monkeypatch.setattr(
        main_window,
        "safe_wal_checkpoint",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("wal failed")),
    )
    app._prepare_for_background_db_task()
    assert app.conn.commits == 1

    criticals: list[tuple[str, str]] = []
    warning_sounds: list[bool] = []
    logs: list[tuple[object, ...]] = []
    app.logger = SimpleNamespace(error=lambda *args, **_kwargs: logs.append(args))
    app._play_warning_sound = lambda: warning_sounds.append(True)
    monkeypatch.setattr(
        main_window.QMessageBox,
        "critical",
        lambda _parent, title, message: criticals.append((title, message)),
    )
    app._show_background_task_error(
        "Import",
        main_window.TaskFailure(message="boom", traceback_text="traceback"),
        user_message="Failed:",
    )
    assert warning_sounds == [True]
    assert criticals == [("Import", "Failed:\nboom")]
    assert any("traceback" in str(call) for call in logs)

    progress_calls: list[dict[str, object]] = []
    scaled = App._scaled_progress_callback(
        lambda **kwargs: progress_calls.append(kwargs),
        start=10,
        end=50,
    )
    scaled(1, 4, "quarter")
    scaled(999, None, "direct")
    scaled("bad", "also-bad", "broken")
    App._scaled_progress_callback(None, start=0, end=10)(5, 10, "ignored")
    assert progress_calls == [
        {"value": 20, "maximum": 100, "message": "quarter"},
        {"value": 50, "maximum": 100, "message": "direct"},
        {"value": None, "maximum": None, "message": "broken"},
    ]


def test_background_task_submission_wrappers_cover_profile_lock_bundle_and_audit_paths(
    monkeypatch,
) -> None:
    app = _app()
    warnings: list[tuple[str, str]] = []
    warning_sounds: list[str] = []
    prepared: list[str] = []
    submissions: list[dict[str, object]] = []
    lock_events: list[str] = []
    bundle_events: list[str] = []

    class FakeMessageBox:
        @classmethod
        def warning(cls, _parent, title, message) -> None:
            warnings.append((title, message))

    monkeypatch.setattr(main_window, "QMessageBox", FakeMessageBox)

    class FakeBackgroundTasks:
        def submit(self, **kwargs):
            submissions.append(kwargs)
            return f"task-{len(submissions)}"

    class FakeLock:
        class Guard:
            def __enter__(self):
                lock_events.append("enter")

            def __exit__(self, *_exc_info):
                lock_events.append("exit")
                return False

        def acquire(self):
            lock_events.append("acquire")
            return self.Guard()

    class FakeContext:
        def __init__(self) -> None:
            self.statuses: list[str] = []
            self.progress: list[tuple[int, int, str]] = []
            self.cancel_checks = 0

        def set_status(self, message: str) -> None:
            self.statuses.append(message)

        def raise_if_cancelled(self) -> None:
            self.cancel_checks += 1

        def report_progress(self, *, value: int, maximum: int, message: str) -> None:
            self.progress.append((value, maximum, message))

    app.current_db_path = ""
    app.background_tasks = FakeBackgroundTasks()
    app._background_write_lock = FakeLock()
    app._play_warning_sound = lambda: warning_sounds.append("warning")
    app._prepare_for_background_db_task = lambda: prepared.append("prepare")

    assert (
        app._submit_background_task(
            title="Needs Profile",
            description="Needs a database",
            task_fn=lambda _ctx: None,
        )
        is None
    )
    assert warning_sounds == ["warning"]
    assert warnings[-1] == ("Needs Profile", "Open a profile first.")
    assert submissions == []

    app.current_db_path = "/tmp/profile.db"
    result = app._submit_background_task(
        title="Write Task",
        description="Writing",
        task_fn=lambda ctx: ctx.statuses.append("worked") or "payload",
        kind="write",
        unique_key="write.task",
        worker_completion_progress=(75, "Committed"),
        owner="owner",
        on_success=lambda _result: None,
        on_finished=lambda: None,
    )
    assert result == "task-1"
    assert prepared == ["prepare"]
    assert submissions[-1]["kind"] == "write"
    assert submissions[-1]["owner"] == "owner"
    ctx = FakeContext()
    assert submissions[-1]["task_fn"](ctx) == "payload"
    assert ctx.statuses == ["Writing", "worked"]
    assert ctx.cancel_checks == 1
    assert ctx.progress == [(75, 100, "Committed")]
    assert lock_events == ["acquire", "enter", "exit"]

    class BundleContextManager:
        def __enter__(self):
            bundle_events.append("enter")
            return "bundle"

        def __exit__(self, *_exc_info):
            bundle_events.append("exit")
            return False

    app.background_service_factory = SimpleNamespace(open_bundle=lambda: BundleContextManager())
    result = app._submit_background_bundle_task(
        title="Bundle Task",
        description="Bundling",
        task_fn=lambda bundle, ctx: bundle_events.append(f"task:{bundle}") or "bundle-result",
        kind="read",
        worker_completion_progress=(100, "Loaded"),
    )
    assert result == "task-2"
    bundle_ctx = FakeContext()
    assert submissions[-1]["task_fn"](bundle_ctx) == "bundle-result"
    assert bundle_events == ["enter", "task:bundle", "exit"]
    assert bundle_ctx.progress == [(100, 100, "Loaded")]

    executed: list[tuple[str, tuple[object, ...]]] = []

    class AuditConnection:
        def __init__(self, *, fail: bool = False) -> None:
            self.fail = fail

        def execute(self, sql, params) -> None:
            if self.fail:
                raise RuntimeError("audit table unavailable")
            executed.append((sql, params))

    audit = App._background_schema_audit_callback(AuditConnection())
    audit("CREATE", "Profile", 42, "details")
    assert executed[-1][1] == (None, "CREATE", "Profile", "42", "details")
    failing_audit = App._background_schema_audit_callback(AuditConnection(fail=True))
    failing_audit("FAIL", "Profile", None, None)
    assert executed[-1][1] == (None, "CREATE", "Profile", "42", "details")


def test_startup_feedback_helpers_cover_tracker_fallbacks_and_completion(monkeypatch) -> None:
    app = _app()
    drained: list[str] = []
    phases: list[tuple[main_window.StartupPhase, str | None]] = []
    progress_reports: list[tuple[object, ...]] = []
    status_messages: list[str] = []

    class Tracker:
        def __init__(self) -> None:
            self.finished = False

        def set_phase(self, phase, message=None) -> None:
            phases.append((phase, message))

        def report_progress(self, phase, *, value=None, maximum=None, message=None) -> None:
            progress_reports.append((phase, value, maximum, message))

        def progress_callback(self, phase):
            return lambda value=None, maximum=None, message=None: progress_reports.append(
                ("callback", phase, value, maximum, message)
            )

        def finish(self) -> None:
            self.finished = True

    class Feedback:
        current_phase = main_window.StartupPhase.STARTING

        def __init__(self, *, fail_phase: bool = False, fail_status: bool = False) -> None:
            self.fail_phase = fail_phase
            self.fail_status = fail_status
            self.finished_with: object | None = None

        def set_phase(self, phase, message=None) -> None:
            if self.fail_phase:
                raise RuntimeError("phase failed")
            phases.append((phase, message))

        def set_status(self, message) -> None:
            if self.fail_status:
                raise RuntimeError("status failed")
            status_messages.append(str(message))

        def report_progress(self, progress, message, *, phase=None) -> None:
            if progress == -1:
                raise RuntimeError("progress failed")
            progress_reports.append((progress, message, phase))

        def finish(self, owner) -> None:
            self.finished_with = owner

    app._startup_progress_tracker = Tracker()
    app._startup_feedback = Feedback()
    app._startup_feedback_completed = False
    app._report_startup_phase(main_window.StartupPhase.STARTING, "Booting")
    app._report_startup_progress(
        main_window.StartupPhase.LOADING_CATALOG,
        value=2,
        maximum=4,
        message_override="Half",
    )
    callback = app._startup_progress_callback(main_window.StartupPhase.LOADING_CATALOG)
    callback(1, 2, "callback")
    assert phases == [(main_window.StartupPhase.STARTING, "Booting")]
    assert progress_reports == [
        (main_window.StartupPhase.LOADING_CATALOG, 2, 4, "Half"),
        ("callback", main_window.StartupPhase.LOADING_CATALOG, 1, 2, "callback"),
    ]

    app._startup_progress_tracker = None
    app._startup_feedback = Feedback(fail_phase=True)
    app._report_startup_phase(main_window.StartupPhase.LOADING_CATALOG, "Fallback status")
    assert status_messages[-1] == "Fallback status"
    app._startup_feedback = Feedback(fail_phase=True, fail_status=True)
    app._report_startup_phase(main_window.StartupPhase.LOADING_CATALOG, "Ignored failure")
    app._startup_feedback_completed = True
    app._report_startup_phase(main_window.StartupPhase.READY, "ignored")
    app._startup_feedback_completed = False

    app._startup_feedback = Feedback(fail_phase=True)
    fallback_callback = app._startup_progress_callback(main_window.StartupPhase.LOADING_CATALOG)
    fallback_callback(5, 10, "Catalog")
    assert status_messages[-1] == "Catalog"

    app._drain_qt_events = lambda: drained.append("drain")
    app._report_startup_progress = (
        lambda phase, *, value=None, maximum=None, message_override=None: progress_reports.append(
            ("storage", phase, value, maximum, message_override)
        )
    )
    app._report_storage_startup_progress(1, 3, "")
    assert progress_reports[-1] == (
        "storage",
        main_window.StartupPhase.RESOLVING_STORAGE,
        1,
        3,
        "Resolving storage layout...",
    )
    assert drained == ["drain"]
    app._startup_feedback_completed = True
    app._report_storage_startup_progress(2, 3, "done")
    assert drained == ["drain"]

    app._startup_feedback_completed = False
    app._startup_feedback = SimpleNamespace(suspend=lambda: drained.append("suspend"))
    app._suspend_startup_feedback()
    app._startup_feedback = SimpleNamespace(
        suspend=lambda: (_ for _ in ()).throw(RuntimeError("suspend failed"))
    )
    app._suspend_startup_feedback()
    app._startup_feedback = SimpleNamespace(resume=lambda: drained.append("resume"))
    app._resume_startup_feedback()
    app._startup_feedback = SimpleNamespace(
        resume=lambda: (_ for _ in ()).throw(RuntimeError("resume failed"))
    )
    app._resume_startup_feedback()
    assert drained == ["drain", "suspend", "drain", "drain", "resume", "drain", "drain"]

    feedback = Feedback(fail_phase=True)
    app._set_loading_feedback_phase(
        feedback,
        main_window.StartupPhase.LOADING_CATALOG,
        "Status after phase failure",
    )
    assert status_messages[-1] == "Status after phase failure"
    app._set_loading_feedback_phase(None, main_window.StartupPhase.LOADING_CATALOG)
    app._set_loading_feedback_progress(
        feedback,
        progress=33,
        phase=main_window.StartupPhase.LOADING_CATALOG,
        message_override="Progress",
    )
    assert progress_reports[-1] == (33, "Progress", main_window.StartupPhase.LOADING_CATALOG)
    no_progress_feedback = SimpleNamespace(
        current_phase=main_window.StartupPhase.LOADING_CATALOG,
        set_phase=lambda phase, message=None: phases.append((phase, message)),
    )
    app._set_loading_feedback_progress(
        no_progress_feedback,
        progress=50,
        phase=main_window.StartupPhase.READY,
        message_override="Phase fallback",
    )
    assert phases[-1] == (main_window.StartupPhase.READY, "Phase fallback")
    app._set_loading_feedback_progress(
        no_progress_feedback,
        progress=50,
        message_override="Status fallback",
    )
    assert phases[-1] == (main_window.StartupPhase.LOADING_CATALOG, "Status fallback")

    loading_callback = app._loading_feedback_progress_callback(
        feedback,
        None,
        main_window.StartupPhase.LOADING_CATALOG,
    )
    loading_callback(1, 4, "Quarter")
    loading_callback("bad", "also-bad", "Broken")
    assert progress_reports[-2:] == [
        (25, "Quarter", main_window.StartupPhase.LOADING_CATALOG),
        (0, "Broken", main_window.StartupPhase.LOADING_CATALOG),
    ]
    tracker = Tracker()
    tracker_callback = app._loading_feedback_progress_callback(
        feedback,
        tracker,
        main_window.StartupPhase.LOADING_CATALOG,
    )
    tracker_callback(3, 4, "tracker")
    assert progress_reports[-1] == (
        "callback",
        main_window.StartupPhase.LOADING_CATALOG,
        3,
        4,
        "tracker",
    )

    app._startup_feedback = Feedback()
    app._startup_progress_tracker = tracker
    app.complete_startup_feedback()
    assert tracker.finished is True
    assert app._startup_feedback is None
    assert app._startup_progress_tracker is None
    app.complete_startup_feedback()

    app._startup_feedback_completed = False
    app._startup_feedback = SimpleNamespace(
        report_progress=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("progress failed")
        ),
        finish=lambda owner: status_messages.append(f"finished:{owner is app}"),
    )
    app._startup_progress_tracker = None
    app.complete_startup_feedback()
    assert status_messages[-1] == "finished:True"


def test_startup_ready_gate_message_box_and_runtime_feedback(monkeypatch) -> None:
    require_qapplication()
    app = _app()
    reports: list[main_window.StartupPhase] = []
    waveform_runs: list[object] = []
    emitted: list[bool] = []

    app._startup_ready_emitted = True
    app._maybe_finish_startup_loading()
    app._startup_ready_emitted = False
    app._workspace_layout_restore_complete = False
    app._maybe_finish_startup_loading()
    assert waveform_runs == []

    app._workspace_layout_restore_complete = True
    app._startup_catalog_refresh_complete = False
    app._report_startup_phase = lambda phase, message_override=None: reports.append(phase)
    app._maybe_finish_startup_loading()
    assert reports == [main_window.StartupPhase.LOADING_CATALOG]

    app._startup_catalog_refresh_complete = True
    app._startup_waveform_cache_complete = False
    app._startup_progress_callback = lambda phase: ("progress", phase)
    app._run_startup_audio_waveform_cache_pass = (
        lambda progress_callback=None: waveform_runs.append(progress_callback)
    )
    app.startupReady = SimpleNamespace(emit=lambda: emitted.append(True))
    app._maybe_finish_startup_loading()
    assert app._startup_waveform_cache_complete is True
    assert waveform_runs == [("progress", main_window.StartupPhase.LOADING_CATALOG)]
    assert app._startup_ready_emitted is True
    assert emitted == [True]

    created_feedback: list[object] = []

    class Feedback:
        def __init__(self) -> None:
            self.shown = False

        def show(self) -> None:
            self.shown = True

    feedback = Feedback()
    monkeypatch.setattr(main_window, "create_startup_splash_controller", lambda _app: feedback)
    runtime_feedback = app._create_runtime_loading_feedback()
    created_feedback.append(runtime_feedback)
    assert runtime_feedback is feedback
    assert feedback.shown is True
    monkeypatch.setattr(main_window, "create_startup_splash_controller", lambda _app: None)
    assert app._create_runtime_loading_feedback() is None

    finish_calls: list[object] = []
    app._finish_loading_feedback(SimpleNamespace(finish=lambda owner: finish_calls.append(owner)))
    app._finish_loading_feedback(
        SimpleNamespace(finish=lambda _owner: (_ for _ in ()).throw(RuntimeError("finish failed")))
    )
    app._finish_loading_feedback(None)
    assert finish_calls == [app]

    app._suspend_startup_feedback = lambda: reports.append(main_window.StartupPhase.STARTING)
    app._resume_startup_feedback = lambda: reports.append(main_window.StartupPhase.READY)
    app.isVisible = lambda: False
    message_boxes: list[object] = []

    class FakeMessageBox:
        AcceptRole = object()
        Information = object()

        def __init__(self, parent=None) -> None:
            self.parent = parent
            self.title = ""
            self.icon = None
            self.text = ""
            self.modality = None
            self.buttons: list[tuple[str, object]] = []
            self.default_button = None
            self.executed = False
            message_boxes.append(self)

        def setWindowTitle(self, title) -> None:
            self.title = title

        def setIcon(self, icon) -> None:
            self.icon = icon

        def setText(self, text) -> None:
            self.text = text

        def setWindowModality(self, modality) -> None:
            self.modality = modality

        def addButton(self, label, role):
            button = (label, role)
            self.buttons.append(button)
            return button

        def setDefaultButton(self, button) -> None:
            self.default_button = button

        def exec(self) -> None:
            self.executed = True

    monkeypatch.setattr(main_window, "QMessageBox", FakeMessageBox)
    shown = app._run_startup_message_box(
        title="Startup",
        icon=FakeMessageBox.Information,
        text="Ready",
    )
    assert shown.parent is None
    assert shown.title == "Startup"
    assert shown.text == "Ready"
    assert shown.modality == Qt.ApplicationModal
    assert shown.buttons == [("OK", FakeMessageBox.AcceptRole)]
    assert shown.default_button == shown.buttons[0]
    assert shown.executed is True
    assert reports[-2:] == [
        main_window.StartupPhase.STARTING,
        main_window.StartupPhase.READY,
    ]

    configured: list[FakeMessageBox] = []
    app.isVisible = lambda: True
    configured_box = app._run_startup_message_box(
        title="Configured",
        icon=FakeMessageBox.Information,
        text="Text",
        configure=lambda box: configured.append(box),
    )
    assert configured == [configured_box]
    assert configured_box.parent is app
    assert configured_box.buttons == []


def test_first_launch_close_workspace_and_add_track_guard_workflows(monkeypatch) -> None:
    require_qapplication()
    app = _app()
    warnings: list[tuple[str, str]] = []
    settings_opened: list[str] = []
    diagnostics_tabs: list[str] = []
    ignored_close: list[bool] = []
    panel_events: list[str] = []

    class FakeMessageBox:
        AcceptRole = object()
        RejectRole = object()
        Question = object()

        @classmethod
        def warning(cls, _parent, title, message) -> None:
            warnings.append((title, message))

    monkeypatch.setattr(main_window, "QMessageBox", FakeMessageBox)

    class FirstLaunchBox:
        def __init__(self, *, click_first: bool) -> None:
            self.click_first = click_first
            self.buttons: list[object] = []
            self.default_button = None

        def addButton(self, _label, _role):
            button = object()
            self.buttons.append(button)
            return button

        def setDefaultButton(self, button) -> None:
            self.default_button = button

        def clickedButton(self):
            return self.buttons[0] if self.click_first else self.buttons[-1]

    app.settings = _Settings({"startup/offer_open_settings_on_first_launch_pending": False})
    app._run_startup_message_box = lambda **_kwargs: (_ for _ in ()).throw(
        AssertionError("prompt should not open")
    )
    app._offer_settings_on_first_launch_if_pending()

    app.settings = _Settings({"startup/offer_open_settings_on_first_launch_pending": True})

    def run_first_launch_prompt(**kwargs):
        box = FirstLaunchBox(click_first=True)
        kwargs["configure"](box)
        return box

    app._run_startup_message_box = run_first_launch_prompt
    app.open_settings_dialog = lambda: settings_opened.append("settings")
    app._offer_settings_on_first_launch_if_pending()
    assert app.settings.values["startup/offer_open_settings_on_first_launch_pending"] is False
    assert app.settings.synced is True
    assert settings_opened == ["settings"]

    app.background_tasks = SimpleNamespace(
        has_running_tasks=lambda: True,
        active_task_titles=lambda: [f"Task {index}" for index in range(10)],
    )
    event = SimpleNamespace(ignore=lambda: ignored_close.append(True))
    app.closeEvent(event)
    assert ignored_close == [True]
    assert warnings[-1][0] == "Background Tasks Running"
    assert "Task 7" in warnings[-1][1]
    assert "Task 8" not in warnings[-1][1]

    app.catalog_service = None
    app.open_catalog_managers_dialog(initial_tab="albums")
    assert warnings[-1] == ("Catalog Cleanup", "Open a profile first.")
    app.catalog_service = object()
    app.open_diagnostics_dialog = lambda **kwargs: diagnostics_tabs.append(
        kwargs["initial_cleanup_tab"]
    )
    app.open_catalog_managers_dialog(initial_tab="artists")
    app._manage_stored_artists()
    app._manage_stored_albums()
    assert diagnostics_tabs == ["artists", "artists", "albums"]

    class FakePanel:
        def refresh_selection_scope(self) -> None:
            panel_events.append("refresh-scope")

    class FakeDock:
        def __init__(self) -> None:
            self.panel = FakePanel()

        def show_panel(self):
            panel_events.append("show")
            return self.panel

    dock = FakeDock()
    panel = app._show_workspace_panel(
        lambda: dock,
        panel_attr="workspace_panel",
        legacy_attr="legacy_workspace",
        configure=lambda opened_panel: panel_events.append(
            f"configure:{opened_panel is dock.panel}"
        ),
        refresh_scope=True,
    )
    assert panel is dock.panel
    assert app.workspace_panel is dock.panel
    assert app.legacy_workspace is dock.panel
    assert panel_events == ["show", "configure:True", "refresh-scope"]

    app.code_registry_service = None
    app.open_code_registry_workspace()
    assert warnings[-1] == ("Code Registry Workspace", "Open a profile first.")
    app.code_registry_service = object()
    app._ensure_code_registry_workspace_dock = lambda: dock
    assert app.open_code_registry_workspace() is dock.panel

    app.global_search_service = None
    app.relationship_explorer_service = object()
    app.open_global_search()
    assert warnings[-1] == ("Global Search", "Open a profile first.")
    app.global_search_service = object()
    app._ensure_global_search_dock = lambda: dock
    assert app.open_global_search() is dock.panel
    assert app.global_search_dialog is dock.panel

    cleanup_dialogs: list[object] = []

    class FakeHistoryCleanupDialog:
        def __init__(self, owner, parent=None) -> None:
            cleanup_dialogs.append((owner, parent))

        def exec(self) -> None:
            cleanup_dialogs.append("exec")

    monkeypatch.setattr(main_window, "HistoryCleanupDialog", FakeHistoryCleanupDialog)
    app.open_history_cleanup_dialog()
    assert cleanup_dialogs == [(app, app), "exec"]

    class FakeDiagnosticsCatalogCleanupPanel:
        def __init__(self, owner, parent=None) -> None:
            self.owner = owner
            self.parent = parent

    monkeypatch.setattr(
        main_window,
        "DiagnosticsCatalogCleanupPanel",
        FakeDiagnosticsCatalogCleanupPanel,
    )
    app.catalog_service = object()
    assert app._create_diagnostics_catalog_cleanup_panel(parent=object()) is not None
    app.catalog_service = None
    assert app._create_diagnostics_catalog_cleanup_panel(parent=object()) is None

    group, layout = App._create_add_data_group("Metadata", "Describe this panel")
    field = App._create_add_data_status_field("Waiting")
    label = main_window.QLabel("Status")
    row = App._create_add_data_row(label, field, top_aligned=True)
    try:
        assert group.title() == "Metadata"
        assert layout.count() == 1
        assert field.isReadOnly() is True
        assert field.placeholderText() == "Waiting"
        assert row.layout().count() == 2
    finally:
        row.deleteLater()
        group.deleteLater()

    add_track_events: list[str] = []
    app.track_service = None
    app.conn = object()
    app.open_add_track_entry()
    assert warnings[-1] == ("Add Track", "Open a profile first.")
    app.track_service = object()
    app._apply_add_data_panel_state = lambda visible: add_track_events.append(f"panel:{visible}")
    app._set_pending_work_track_context = lambda: add_track_events.append("pending")
    app.clear_form_fields = lambda: add_track_events.append("clear")
    app._refresh_work_track_creation_context_ui = lambda: add_track_events.append("work-ui")
    app._show_add_track_details_tab = lambda: add_track_events.append("details-tab")
    app.track_title_field = SimpleNamespace(setFocus=lambda: add_track_events.append("focus"))
    app.open_add_track_entry()
    assert add_track_events == [
        "panel:True",
        "pending",
        "clear",
        "work-ui",
        "details-tab",
        "focus",
    ]

    app.conn = None
    assert app._artist_lookup_values() == []
    app.conn = object()
    app._catalog_combo_values_from_connection = lambda _conn: {"artists": ("One", "Two")}
    assert app._artist_lookup_values() == ["One", "Two"]
    assert App._media_file_filter("audio_file").startswith("Audio")
    assert App._media_file_filter("album_art").startswith("Images")
    assert App._audio_format_label(".mp3") == "MP3"
    assert App._audio_format_label(".weird") == "WEIRD"
    assert App._audio_format_label("") == "audio"


def test_startup_feedback_logging_and_trace_edge_paths(monkeypatch, tmp_path: Path) -> None:
    app = _app()
    phase_calls: list[tuple[object, str | None]] = []
    status_calls: list[str] = []
    progress_calls: list[tuple[object, ...]] = []
    finish_calls: list[object] = []

    class Feedback:
        current_phase = main_window.StartupPhase.STARTING

        def __init__(
            self,
            *,
            fail_phase: bool = False,
            fail_status: bool = False,
            fail_progress: bool = False,
        ) -> None:
            self.fail_phase = fail_phase
            self.fail_status = fail_status
            self.fail_progress = fail_progress

        def set_phase(self, phase, message=None) -> None:
            if self.fail_phase:
                raise RuntimeError("phase failed")
            phase_calls.append((phase, message))

        def set_status(self, message) -> None:
            if self.fail_status:
                raise RuntimeError("status failed")
            status_calls.append(str(message))

        def report_progress(self, progress, message, *, phase=None) -> None:
            if self.fail_progress:
                raise RuntimeError("progress failed")
            progress_calls.append((progress, message, phase))

        def finish(self, owner) -> None:
            finish_calls.append(owner)

    app._startup_progress_tracker = None
    app._startup_feedback_completed = False
    app._startup_feedback = Feedback()
    app._report_startup_phase(main_window.StartupPhase.READY, "Ready")
    assert phase_calls[-1] == (main_window.StartupPhase.READY, "Ready")

    app._startup_feedback = None
    app._report_startup_phase(main_window.StartupPhase.READY, "No controller")
    assert phase_calls[-1] == (main_window.StartupPhase.READY, "Ready")

    app._set_loading_feedback_progress(None, progress=5, message_override="ignored")
    failing_progress = Feedback(fail_progress=True)
    app._set_loading_feedback_progress(
        failing_progress,
        progress=50,
        message_override="Status fallback",
    )
    assert status_calls[-1] == "Status fallback"

    failing_progress_and_phase = Feedback(fail_progress=True, fail_phase=True)
    app._set_loading_feedback_progress(
        failing_progress_and_phase,
        progress=50,
        phase=main_window.StartupPhase.LOADING_CATALOG,
        message_override="Phase then status fallback",
    )
    assert status_calls[-1] == "Phase then status fallback"

    app._set_loading_feedback_status(None, "ignored")
    status_fallback = Feedback(fail_status=True)
    app._set_loading_feedback_status(status_fallback, "Phase fallback")
    assert phase_calls[-1] == (main_window.StartupPhase.STARTING, "Phase fallback")

    fully_failing_status = Feedback(fail_status=True, fail_phase=True)
    app._set_loading_feedback_status(fully_failing_status, "swallowed")

    no_progress_callback = app._loading_feedback_progress_callback(
        failing_progress,
        None,
        main_window.StartupPhase.LOADING_CATALOG,
    )
    no_progress_callback(2, 0, "zero maximum")
    assert phase_calls[-1] == (main_window.StartupPhase.LOADING_CATALOG, "zero maximum")

    app._startup_feedback = SimpleNamespace(
        set_phase=lambda phase, message=None: phase_calls.append((phase, message)),
        finish=lambda owner: finish_calls.append(owner),
    )
    app._startup_feedback_completed = False
    app.complete_startup_feedback()
    assert phase_calls[-1] == (main_window.StartupPhase.READY, None)
    assert finish_calls[-1] is app
    assert app._startup_feedback is None

    app._startup_feedback = SimpleNamespace(
        set_phase=lambda _phase, _message=None: (_ for _ in ()).throw(RuntimeError("phase failed")),
        finish=lambda owner: finish_calls.append(owner),
    )
    app._startup_feedback_completed = False
    app.complete_startup_feedback()
    assert finish_calls[-1] is app

    class RaisingHandler(logging.Handler):
        def emit(self, record) -> None:
            del record

        def close(self) -> None:
            raise RuntimeError("close failed")

    app_logger = logging.getLogger(f"isrc-test-app-{id(tmp_path)}")
    trace_logger = logging.getLogger(f"isrc-test-trace-{id(tmp_path)}")
    for logger in (app_logger, trace_logger):
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
        logger.addHandler(RaisingHandler())

    app.logger = app_logger
    app.trace_logger = trace_logger
    app.log_path = tmp_path / "app.log"
    app.trace_log_path = tmp_path / "trace.jsonl"
    app._logging_configured = False
    app._bootstrap_log_buffer = [("app", logging.INFO, "buffered app", None)]
    app._flush_bootstrap_log_buffer()
    assert app._bootstrap_log_buffer
    app._bootstrap_log_buffer.append(
        ("trace", logging.INFO, "buffered trace", {"event": "startup"})
    )
    try:
        app._configure_logging()
        assert app._logging_configured is True
        assert app._bootstrap_log_buffer == []
        assert app.log_path.exists()
        assert app.trace_log_path.exists()
    finally:
        for logger in (app_logger, trace_logger):
            for handler in list(logger.handlers):
                logger.removeHandler(handler)
                try:
                    handler.close()
                except Exception:
                    pass

    nested = App._normalize_log_value({"path": tmp_path, "items": [tmp_path / "a", {"b": 2}]})
    assert nested == {"path": str(tmp_path), "items": [str(tmp_path / "a"), {"b": 2}]}
    assert App._safe_trace_field_name("event", set()) == "field_event"
    assert App._safe_trace_field_name("event", {"field_event"}) == "field_event_2"

    app.current_db_path = tmp_path / "catalog.db"
    trace_payload = app._trace_context(
        event="reserved",
        empty="",
        nested={"path": tmp_path / "nested"},
    )
    assert trace_payload["profile"] == "catalog.db"
    assert trace_payload["field_event"] == "reserved"
    assert trace_payload["nested"] == {"path": str(tmp_path / "nested")}

    app.trace_logger = None
    app._log_trace("missing-trace")
    app.trace_logger = SimpleNamespace(log=lambda *args, **kwargs: progress_calls.append(args))
    app.logger = SimpleNamespace(log=lambda *args, **kwargs: status_calls.append(args[1]))
    app._bootstrap_log_buffer = []
    app._logging_configured = False
    app._log_event("buffered", "Buffered", values=[1, tmp_path])
    assert app._bootstrap_log_buffer[0][0] == "app"
    assert app._bootstrap_log_buffer[1][0] == "trace"

    app._logging_configured = True
    app._log_event("logged", "Logged", values=[1, 2], skipped="")
    assert "values=1, 2" in status_calls[-1]


def test_shortcut_zoom_audit_and_refresh_helper_edge_paths(monkeypatch, tmp_path: Path) -> None:
    app = _app()
    shortcut_events: list[tuple[str, object]] = []
    log_events: list[tuple[object, ...]] = []

    class FakeSignal:
        def connect(self, callback) -> None:
            shortcut_events.append(("connect", callback))

    class FakeShortcut:
        def __init__(self, sequence, parent) -> None:
            shortcut_events.append(("shortcut", sequence.toString(QKeySequence.PortableText)))
            assert parent is app
            self.activated = FakeSignal()

        def setContext(self, context) -> None:
            shortcut_events.append(("context", context))

    class FakeAction:
        def __init__(self, text: str, *, enabled: bool = True) -> None:
            self._text = text
            self._enabled = enabled
            self.triggered = 0

        def text(self) -> str:
            return self._text

        def isEnabled(self) -> bool:
            return self._enabled

        def trigger(self) -> None:
            self.triggered += 1

    monkeypatch.setattr(main_window, "QShortcut", FakeShortcut)
    app._log_event = lambda *args, **kwargs: log_events.append((args, kwargs))

    assert app._should_register_explicit_action_shortcuts([QKeySequence("Ctrl+S")]) is True
    assert app._should_register_explicit_action_shortcuts([QKeySequence("Alt+S")]) is False
    assert app._should_register_explicit_action_shortcuts([QKeySequence()]) is False

    kept_action = FakeAction("Keep")
    new_action = FakeAction("New")
    app._explicit_action_shortcut_registry = {"Ctrl+S": kept_action}
    app._explicit_action_shortcut_objects = {}
    app._install_explicit_action_shortcuts(
        new_action,
        [QKeySequence(), QKeySequence("Ctrl+S"), QKeySequence("Meta+S")],
    )
    assert any(event[0] == "shortcut" and event[1] == "Meta+S" for event in shortcut_events)
    assert app._explicit_action_shortcut_registry["Meta+S"] is new_action
    assert app._explicit_action_shortcut_objects[new_action]
    assert log_events[-1][0][0] == "shortcut.duplicate_custom_binding"

    disabled = FakeAction("Disabled", enabled=False)
    app._trigger_explicit_action_shortcut(None)
    app._trigger_explicit_action_shortcut(disabled)
    app._trigger_explicit_action_shortcut(new_action)
    assert disabled.triggered == 0
    assert new_action.triggered == 1

    ordered = app._ordered_custom_shortcuts(["", "Ctrl+K", "Ctrl+K", "Meta+K", "Alt+F"])
    assert [shortcut.toString(QKeySequence.PortableText) for shortcut in ordered] == [
        "Ctrl+K",
        "Meta+K",
        "Alt+F",
    ]
    assert app._platform_variant_shortcut_group("Ctrl+Meta+K") is None

    monkeypatch.setattr(main_window, "current_app_version", lambda: "9.9.9")
    monkeypatch.setattr(
        main_window,
        "render_help_html",
        lambda title, version, *, theme: f"{title}:{version}:{theme['mode']}",
    )
    app._effective_theme_settings = lambda: {"mode": "test"}
    assert app._help_html() == "Music Catalog Manager:9.9.9:test"

    executed: list[tuple[str, tuple[object, ...]]] = []
    exceptions: list[str] = []
    traces: list[tuple[str, dict[str, object]]] = []

    class FakeCursor:
        def __init__(self, *, fail: bool = False) -> None:
            self.fail = fail

        def execute(self, sql, params) -> None:
            if self.fail:
                raise RuntimeError("audit write failed")
            executed.append((sql, params))

    class FakeConnection:
        def __init__(self, *, fail: bool = False) -> None:
            self.fail = fail
            self.commits = 0

        def commit(self) -> None:
            self.commits += 1
            if self.fail:
                raise RuntimeError("commit failed")

    app.cursor = FakeCursor()
    app.logger = SimpleNamespace(exception=lambda message: exceptions.append(str(message)))
    app._log_trace = lambda event, **payload: traces.append((event, payload))
    app._audit("CREATE", "Track", ref_id=7, details="isrc=demo", user="tester")
    assert executed[-1][1] == ("tester", "CREATE", "Track", "7", "isrc=demo")
    assert traces[-1][0] == "audit"
    app.cursor = FakeCursor(fail=True)
    app._audit("FAIL", "Track")
    assert "Failed to write AuditLog" in exceptions[-1]

    app.conn = FakeConnection()
    app._audit_commit()
    assert app.conn.commits == 1
    app.conn = FakeConnection(fail=True)
    app._audit_commit()
    assert "Audit commit error" in exceptions[-1]

    App._on_background_task_state_changed(SimpleNamespace())

    processed_events: list[str] = []

    class FakeApplication:
        def processEvents(self) -> None:
            processed_events.append("processed")

    monkeypatch.setattr(
        main_window,
        "QApplication",
        SimpleNamespace(instance=lambda: FakeApplication()),
    )
    ui_reports: list[dict[str, object]] = []
    ui_progress = SimpleNamespace(report_progress=lambda **kwargs: ui_reports.append(kwargs))
    App._advance_task_ui_progress(ui_progress, value=44, maximum=50, message="Almost")
    assert ui_reports[-1] == {"value": 44, "maximum": 50, "message": "Almost"}
    assert processed_events == ["processed"]

    scaled_reports: list[tuple[int, int, str]] = []
    app._advance_task_ui_progress = lambda _ui, *, value, maximum, message: scaled_reports.append(
        (value, maximum, message)
    )
    scaled = app._scaled_ui_progress_callback("ui", start=10, end=20)
    scaled(15, None, "direct")
    scaled("bad", "also-bad", "fallback")
    assert scaled_reports == [(15, 100, "direct"), (10, 100, "fallback")]

    app.edit_identity = App.edit_identity.__get__(app, App)
    focused: list[str | None] = []
    app.open_settings_dialog = lambda initial_focus=None: focused.append(initial_focus)
    app.edit_identity()
    assert focused == ["window_title"]

    class FakeTrackService:
        def __init__(self) -> None:
            self.artists = {"Known"}
            self.albums = {"Known Album"}

        def artist_exists(self, name, *, cursor=None):
            del cursor
            return str(name) in self.artists

        def album_exists(self, title, *, cursor=None):
            del cursor
            return str(title) in self.albums

    app.track_service = FakeTrackService()
    app.cursor = object()
    assert app._collect_catalog_cleanup_targets(
        artist_name="Known",
        additional_artists=["New Artist", "", "New Artist"],
        album_title="New Album",
    ) == (["New Artist"], ["New Album"])

    refreshes: list[str] = []
    identities: list[str] = []
    monkeypatch.setattr(
        main_window,
        "refresh_catalog_workspace_docks",
        lambda owner: refreshes.append(f"refresh:{owner is app}"),
    )
    app._load_identity = lambda: "identity"
    app._apply_identity = lambda: identities.append(app.identity)
    app.identity = "old"
    app._refresh_catalog_workspace_docks()
    assert refreshes == ["refresh:True"]
    assert identities == ["identity"]


def test_catalog_zoom_gestures_and_add_track_lookup_edge_paths(monkeypatch) -> None:
    require_qapplication()
    app = _app()
    controller_events: list[tuple[str, object]] = []
    accepted: list[str] = []

    class FakeZoomController:
        def step_zoom(self, steps: int, *, immediate: bool) -> None:
            controller_events.append(("step", (steps, immediate)))

        def apply_pinch_scale(self, factor: float, *, immediate: bool) -> None:
            controller_events.append(("pinch", (round(factor, 3), immediate)))

        def reset_zoom(self, *, immediate: bool) -> None:
            controller_events.append(("reset", immediate))

    app._catalog_zoom_controller = lambda: FakeZoomController()

    point_font = QFont()
    point_font.setPointSizeF(10.0)
    assert App._scaled_catalog_zoom_font(point_font, 150).pointSizeF() == 15.0
    pixel_font = QFont()
    pixel_font.setPixelSize(12)
    assert App._scaled_catalog_zoom_font(pixel_font, 50).pixelSize() == 6

    def wheel_event(*, modifiers=Qt.ControlModifier, pixel=QPoint(), angle=QPoint()):
        return SimpleNamespace(
            modifiers=lambda: modifiers,
            pixelDelta=lambda: pixel,
            angleDelta=lambda: angle,
            accept=lambda: accepted.append("wheel"),
        )

    assert App._catalog_zoom_steps_from_wheel_event(wheel_event(pixel=QPoint(0, 80))) == 2
    assert App._catalog_zoom_steps_from_wheel_event(wheel_event(pixel=QPoint(60, 10))) == 2
    assert App._catalog_zoom_steps_from_wheel_event(wheel_event(angle=QPoint(0, -240))) == -2
    assert App._catalog_zoom_steps_from_wheel_event(wheel_event()) == 0

    assert (
        app._handle_catalog_zoom_wheel_event(
            wheel_event(modifiers=Qt.NoModifier, angle=QPoint(0, 120))
        )
        is False
    )
    assert app._handle_catalog_zoom_wheel_event(wheel_event()) is False
    assert app._handle_catalog_zoom_wheel_event(wheel_event(pixel=QPoint(0, 80))) is True
    assert controller_events[-1] == ("step", (2, False))

    def native_event(gesture_type, value=0.0):
        return SimpleNamespace(
            gestureType=lambda: gesture_type,
            value=lambda: value,
            accept=lambda: accepted.append("native"),
        )

    assert (
        app._handle_catalog_zoom_native_gesture_event(native_event(Qt.ZoomNativeGesture, 0.0))
        is False
    )
    assert (
        app._handle_catalog_zoom_native_gesture_event(native_event(Qt.ZoomNativeGesture, 0.25))
        is True
    )
    assert controller_events[-1] == ("pinch", (1.25, True))
    assert (
        app._handle_catalog_zoom_native_gesture_event(native_event(Qt.SmartZoomNativeGesture))
        is True
    )
    assert controller_events[-1] == ("reset", True)
    assert app._handle_catalog_zoom_native_gesture_event(native_event(object())) is False

    assert app._handle_catalog_zoom_pinch_gesture_event(SimpleNamespace()) is False
    assert (
        app._handle_catalog_zoom_pinch_gesture_event(
            SimpleNamespace(gesture=lambda _gesture_type: None)
        )
        is False
    )
    monkeypatch.setattr(main_window, "QPinchGesture", SimpleNamespace(ScaleFactorChanged=1))

    class FakePinch:
        def __init__(self, *, flags, last=1.0, current=1.0) -> None:
            self._flags = flags
            self._last = last
            self._current = current

        def changeFlags(self):
            return self._flags

        def lastScaleFactor(self):
            return self._last

        def scaleFactor(self):
            return self._current

    def pinch_event(pinch):
        return SimpleNamespace(
            gesture=lambda _gesture_type: pinch,
            accept=lambda: accepted.append("pinch"),
        )

    assert app._handle_catalog_zoom_pinch_gesture_event(pinch_event(FakePinch(flags=0))) is False
    assert (
        app._handle_catalog_zoom_pinch_gesture_event(
            pinch_event(
                FakePinch(
                    flags=main_window.QPinchGesture.ScaleFactorChanged,
                    last=1.0,
                    current=1.0001,
                )
            )
        )
        is False
    )
    assert (
        app._handle_catalog_zoom_pinch_gesture_event(
            pinch_event(
                FakePinch(
                    flags=main_window.QPinchGesture.ScaleFactorChanged,
                    last=0.0,
                    current=1.5,
                )
            )
        )
        is True
    )
    assert controller_events[-1] == ("pinch", (1.5, True))
    assert (
        app._handle_catalog_zoom_pinch_gesture_event(
            pinch_event(
                FakePinch(
                    flags=main_window.QPinchGesture.ScaleFactorChanged,
                    last=2.0,
                    current=1.0,
                )
            )
        )
        is True
    )
    assert controller_events[-1] == ("pinch", (0.5, True))

    table = SimpleNamespace(viewport=lambda: "viewport")
    app.table = table
    routed: list[str] = []
    app._handle_catalog_zoom_wheel_event = lambda _event: routed.append("wheel") or True
    app._handle_catalog_zoom_native_gesture_event = lambda _event: routed.append("native") or True
    app._handle_catalog_zoom_pinch_gesture_event = lambda _event: routed.append("gesture") or True
    assert (
        app._handle_catalog_zoom_event(
            table,
            SimpleNamespace(type=lambda: main_window.QEvent.Wheel),
        )
        is True
    )
    assert (
        app._handle_catalog_zoom_event(
            "viewport",
            SimpleNamespace(type=lambda: main_window.QEvent.NativeGesture),
        )
        is True
    )
    app._catalog_zoom_gesture_platform = "darwin"
    assert (
        app._handle_catalog_zoom_event(
            table,
            SimpleNamespace(type=lambda: main_window.QEvent.Gesture),
        )
        is False
    )
    app._catalog_zoom_gesture_platform = "linux"
    assert (
        app._handle_catalog_zoom_event(
            table,
            SimpleNamespace(type=lambda: main_window.QEvent.Gesture),
        )
        is True
    )
    assert app._handle_catalog_zoom_event("other", SimpleNamespace(type=lambda: 0)) is False
    app.table = None
    assert app._handle_catalog_zoom_event(table, SimpleNamespace(type=lambda: 0)) is False
    assert routed == ["wheel", "native", "gesture"]

    app.conn = None
    artist_refreshes: list[str] = []
    app._refresh_add_track_artist_party_choices = lambda: artist_refreshes.append("artists")
    app._refresh_add_track_lookup_sources_preserving_text()
    assert artist_refreshes == ["artists"]

    app.conn = object()
    album_combo = QComboBox()
    upc_combo = QComboBox()
    genre_combo = QComboBox()
    for combo, text in (
        (album_combo, "Current Album"),
        (upc_combo, "Current UPC"),
        (genre_combo, "Genre A"),
    ):
        combo.setEditable(True)
        combo.setCurrentText(text)

    catalog_refreshes: list[str] = []
    catalog_field = SimpleNamespace(
        currentText=lambda: "CAT-001",
        refresh=lambda: catalog_refreshes.append("refresh"),
        setCurrentText=lambda text: catalog_refreshes.append(f"set:{text}"),
    )
    app.album_title_field = album_combo
    app.upc_field = upc_combo
    app.genre_field = genre_combo
    app.catalog_number_field = catalog_field
    app._catalog_combo_values_from_connection = lambda _conn: {
        "albums": ["Album A", "", "Album A"],
        "upcs": ["123456789012"],
        "genres": ["Genre A", "Genre B"],
    }
    try:
        app._refresh_add_track_lookup_sources_preserving_text()
        assert album_combo.findText("Current Album", Qt.MatchFixedString) >= 0
        assert upc_combo.findText("Current UPC", Qt.MatchFixedString) >= 0
        assert genre_combo.currentText() == "Genre A"
        assert catalog_refreshes == ["refresh", "set:CAT-001"]

        app_without_add_panel = _app()
        app_without_add_panel._ensure_add_track_panel_initialized()

        add_panel_events: list[str] = []
        app.add_data_work_mode_combo = object()
        app._current_work_track_context = lambda: add_panel_events.append("context")
        app._refresh_work_track_creation_context_ui = lambda: add_panel_events.append("work-ui")
        app._refresh_add_track_lookup_sources_preserving_text = lambda: add_panel_events.append(
            "lookup"
        )
        app.catalog_number_field = SimpleNamespace(combo=QComboBox())
        app._ensure_add_track_panel_initialized()
        assert add_panel_events == ["context", "work-ui", "lookup"]
    finally:
        album_combo.deleteLater()
        upc_combo.deleteLater()
        genre_combo.deleteLater()
        app.catalog_number_field.combo.deleteLater()


def test_save_validation_media_generation_and_rollback_paths(monkeypatch) -> None:
    app = _app()
    warnings: list[tuple[str, str]] = []
    criticals: list[tuple[str, str]] = []
    rollbacks: list[str] = []
    logged_exceptions: list[str] = []
    media_mode_calls: list[tuple[str | None, str | None]] = []
    lossy_prompts: list[list[str | None]] = []
    released_claims: list[str] = []

    class FakeMessageBox:
        @classmethod
        def warning(cls, _parent, title, message) -> None:
            warnings.append((title, message))

        @classmethod
        def critical(cls, _parent, title, message) -> None:
            criticals.append((title, message))

    monkeypatch.setattr(main_window, "QMessageBox", FakeMessageBox)

    class TextField:
        def __init__(self, value: str = "") -> None:
            self.value = value

        def text(self) -> str:
            return self.value

        def clear(self) -> None:
            self.value = ""

    class ComboField:
        def __init__(self, value: str = "") -> None:
            self.value = value

        def currentText(self) -> str:
            return self.value

        def setCurrentText(self, value: str) -> None:
            self.value = value

    class SpinField:
        def __init__(self, value: int) -> None:
            self._value = value

        def value(self) -> int:
            return self._value

    class FakeDate:
        def toString(self, _format: str) -> str:
            return "2026-05-26"

    def install_fields(
        *,
        title: str = "Song",
        artist: str = "Artist",
        upc: str = "",
        iswc: str = "",
        audio: str = "",
        artwork: str = "",
    ) -> None:
        app.track_title_field = TextField(title)
        app.artist_field = ComboField(artist)
        app.additional_artist_field = ComboField("Guest, Guest 2")
        app.album_title_field = ComboField("Album")
        app.upc_field = ComboField(upc)
        app.catalog_number_field = ComboField("CAT-001")
        app.genre_field = ComboField("Genre")
        app.audio_file_field = TextField(audio)
        app.album_art_field = TextField(artwork)
        app.iswc_field = TextField(iswc)
        app.buma_work_number_field = TextField("BUMA")
        app.release_date_field = SimpleNamespace(selectedDate=lambda: FakeDate())
        app.track_len_h = SpinField(0)
        app.track_len_m = SpinField(3)
        app.track_len_s = SpinField(30)
        app.track_number_field = SpinField(1)
        app.prev_release_toggle = SimpleNamespace(isChecked=lambda: False)

    class FakeConnection:
        def rollback(self) -> None:
            rollbacks.append("rollback")

    app.conn = FakeConnection()
    app.logger = SimpleNamespace(exception=lambda message: logged_exceptions.append(str(message)))
    app.track_service = object()
    app.cursor = object()
    app._current_work_track_context = lambda: {"mode": "create_new_work"}
    app._isrc_generation_state = lambda: ("disabled",)
    app._log_trace = lambda *_args, **_kwargs: None
    app._resolve_artist_party_choice = lambda field: (field.currentText(), None)
    app._resolve_party_backed_artist_name = lambda name, *, selected_party_id=None, cursor=None: (
        name,
        selected_party_id,
    )
    app._parse_additional_artists = lambda value: [
        part.strip() for part in str(value).split(",") if part.strip()
    ]
    app._resolve_party_backed_additional_artist_names = lambda names, *, cursor=None: list(names)
    app._warn_duplicate_track_numbers = lambda **_kwargs: None
    app._confirm_lossy_primary_audio_selection = (
        lambda values, **_kwargs: lossy_prompts.append(list(values)) or False
    )
    app._choose_track_media_storage_modes = (
        lambda *, audio_source_path, album_art_source_path, title: media_mode_calls.append(
            (audio_source_path, album_art_source_path)
        )
        or ("file", "file")
    )
    app._release_reserved_isrc_claim = lambda isrc: released_claims.append(isrc)
    app._capture_catalog_refresh_request = lambda: {"request": "captured"}

    install_fields(title="", artist="Artist")
    app.save()
    assert warnings[-1][0] == "Missing data"

    install_fields()
    app._current_work_track_context = lambda: {"mode": "link_existing_work", "work_id": None}
    app.save()
    assert warnings[-1][0] == "Missing Work"

    app._current_work_track_context = lambda: {"mode": "create_new_work"}
    install_fields(upc="123")
    app.save()
    assert warnings[-1][0] == "Invalid UPC/EAN"

    install_fields(iswc="not an iswc")
    app.save()
    assert warnings[-1][0] == "Invalid ISWC"

    install_fields(audio="/tmp/song.mp3")
    app.save()
    assert lossy_prompts[-1] == ["/tmp/song.mp3"]
    assert media_mode_calls == []

    app._confirm_lossy_primary_audio_selection = lambda values, **_kwargs: True
    app._choose_track_media_storage_modes = (
        lambda *, audio_source_path, album_art_source_path, title: media_mode_calls.append(
            (audio_source_path, album_art_source_path)
        )
        or None
    )
    install_fields(artwork="/tmp/cover.jpg")
    app.save()
    assert media_mode_calls[-1] == (None, "/tmp/cover.jpg")

    app._choose_track_media_storage_modes = (
        lambda *, audio_source_path, album_art_source_path, title: ("database", "file")
    )
    app._isrc_generation_state = lambda: ("ready",)
    app._claim_next_generated_isrc = lambda **_kwargs: ""
    install_fields()
    app.save()
    assert criticals[-1][0] == "ISRC Error"
    assert "No free ISRC sequence" in criticals[-1][1]

    app._claim_next_generated_isrc = lambda **_kwargs: "invalid"
    app.save()
    assert released_claims == ["invalid"]
    assert "Generated ISRC is invalid" in criticals[-1][1]

    app._isrc_generation_state = lambda: ("disabled",)
    app._resolve_artist_party_choice = lambda _field: _raise(sqlite3.IntegrityError("duplicate"))
    install_fields()
    app.save()
    assert rollbacks[-1] == "rollback"
    assert criticals[-1][0] == "Save Error"
    assert "Database constraint error" in criticals[-1][1]
    assert "Save failed (integrity)" in logged_exceptions[-1]

    app._resolve_artist_party_choice = lambda _field: _raise(RuntimeError("unexpected"))
    app.save()
    assert rollbacks[-1] == "rollback"
    assert "Failed to save record" in criticals[-1][1]
    assert "Save failed" in logged_exceptions[-1]


def test_qt_message_filter_covers_filter_previous_and_stderr_paths(monkeypatch) -> None:
    installed_handlers: list[object] = []
    previous_calls: list[tuple[object, object, str]] = []
    stderr_writes: list[str] = []

    monkeypatch.setattr(main_window, "_PREVIOUS_QT_MESSAGE_HANDLER", None)
    monkeypatch.setattr(
        main_window,
        "qInstallMessageHandler",
        lambda handler: installed_handlers.append(handler) or None,
    )
    monkeypatch.setattr(
        main_window.sys.stderr, "write", lambda message: stderr_writes.append(message)
    )

    main_window._install_qt_message_filter()
    handler = installed_handlers[-1]

    handler(
        main_window.QtMsgType.QtDebugMsg,
        SimpleNamespace(category="qt.multimedia.ffmpeg"),
        "filtered multimedia",
    )
    handler(
        main_window.QtMsgType.QtWarningMsg,
        SimpleNamespace(category="qt.qpa.fonts"),
        "Populating font family aliases took 10 ms",
    )
    handler(
        main_window.QtMsgType.QtWarningMsg,
        SimpleNamespace(category="qt.other"),
        "visible warning",
    )
    assert stderr_writes == ["visible warning\n"]

    def previous_handler(mode, context, message):
        previous_calls.append((mode, context, message))

    monkeypatch.setattr(
        main_window,
        "qInstallMessageHandler",
        lambda handler: installed_handlers.append(handler) or previous_handler,
    )
    main_window._install_qt_message_filter()
    forwarding_handler = installed_handlers[-1]
    forwarding_handler(
        main_window.QtMsgType.QtWarningMsg,
        SimpleNamespace(category="qt.other"),
        "forwarded warning",
    )
    assert previous_calls[-1][2] == "forwarded warning"

    installed_count = len(installed_handlers)
    main_window._install_qt_message_filter()
    assert len(installed_handlers) == installed_count


def test_main_window_history_setting_and_file_actions_cover_rollback_and_recording(
    tmp_path: Path,
) -> None:
    app = _app()
    app.logger = SimpleNamespace(exception=lambda message: log_messages.append(message))
    log_messages: list[str] = []
    refreshes: list[str] = []
    app._refresh_history_actions = lambda: refreshes.append("refresh")

    app.history_manager = None
    assert (
        app._run_setting_bundle_history_action(
            action_label="No History",
            setting_keys=["theme"],
            mutation=lambda: "plain-result",
        )
        == "plain-result"
    )
    assert (
        app._run_file_history_action(
            action_label="No History File",
            action_type="file.write",
            target_path=tmp_path / "plain.txt",
            mutation=lambda: "plain-file",
        )
        == "plain-file"
    )

    class FakeHistoryManager:
        def __init__(self) -> None:
            self.setting_states: list[list[dict[str, object]]] = []
            self.file_states: list[dict[str, object]] = []
            self.setting_records: list[dict[str, object]] = []
            self.file_records: list[dict[str, object]] = []
            self.applied_settings: list[list[dict[str, object]]] = []
            self.restored_files: list[tuple[object, dict[str, object]]] = []
            self.fail_setting_restore = False
            self.fail_file_restore = False

        def capture_setting_states(self, setting_keys):
            assert setting_keys == ["theme"]
            return self.setting_states.pop(0)

        def apply_setting_entries(self, entries) -> None:
            self.applied_settings.append(entries)
            if self.fail_setting_restore:
                raise RuntimeError("settings restore failed")

        def record_setting_bundle_change(self, **kwargs) -> None:
            self.setting_records.append(kwargs)

        def capture_file_state(self, target_path, *, companion_suffixes=()):
            assert Path(target_path).name == "managed.txt"
            assert companion_suffixes == (".sidecar",)
            return self.file_states.pop(0)

        def restore_file_state(self, target_path, before_state) -> None:
            self.restored_files.append((target_path, before_state))
            if self.fail_file_restore:
                raise RuntimeError("file restore failed")

        def record_file_write_action(self, **kwargs) -> None:
            self.file_records.append(kwargs)

    history = FakeHistoryManager()
    app.history_manager = history

    app._record_setting_bundle_from_entries(
        action_label="Unchanged Settings",
        before_entries=[{"key": "theme", "value": "dark"}],
        after_entries=[{"key": "theme", "value": "dark"}],
    )
    assert history.setting_records == []
    app._record_setting_bundle_from_entries(
        action_label="Changed Settings",
        before_entries=[{"key": "theme", "value": "dark"}],
        after_entries=[{"key": "theme", "value": "light"}],
        entity_id="theme",
    )
    assert history.setting_records[-1]["label"] == "Changed Settings"
    assert history.setting_records[-1]["entity_id"] == "theme"

    history.setting_states = [
        [{"key": "theme", "value": "dark"}],
        [{"key": "theme", "value": "light"}],
    ]
    assert (
        app._run_setting_bundle_history_action(
            action_label="Apply Theme",
            setting_keys=["theme"],
            mutation=lambda: "applied",
            entity_id="theme",
        )
        == "applied"
    )
    assert history.setting_records[-1]["label"] == "Apply Theme"

    history.setting_states = [[{"key": "theme", "value": "before"}]]
    try:
        app._run_setting_bundle_history_action(
            action_label="Fail Theme",
            setting_keys=["theme"],
            mutation=lambda: _raise(RuntimeError("mutation failed")),
        )
    except RuntimeError as error:
        assert str(error) == "mutation failed"
    else:
        raise AssertionError("mutation failure should propagate")
    assert history.applied_settings[-1] == [{"key": "theme", "value": "before"}]

    history.setting_states = [[{"key": "theme", "value": "rollback"}]]
    history.fail_setting_restore = True
    try:
        app._run_setting_bundle_history_action(
            action_label="Fail Rollback",
            setting_keys=["theme"],
            mutation=lambda: _raise(RuntimeError("mutation failed again")),
        )
    except RuntimeError as error:
        assert str(error) == "mutation failed again"
    else:
        raise AssertionError("mutation failure should propagate")
    assert "Settings rollback failed for Fail Rollback" in log_messages[-1]
    history.fail_setting_restore = False

    target = tmp_path / "managed.txt"
    history.file_states = [{"digest": "same"}, {"digest": "same"}]
    assert (
        app._run_file_history_action(
            action_label="Unchanged File",
            action_type="file.write",
            target_path=target,
            companion_suffixes=(".sidecar",),
            mutation=lambda: "same-result",
        )
        == "same-result"
    )
    assert history.file_records == []

    history.file_states = [{"digest": "before"}, {"digest": "after"}]
    assert (
        app._run_file_history_action(
            action_label=lambda result: f"Changed {result}",
            action_type="file.write",
            target_path=target,
            companion_suffixes=(".sidecar",),
            entity_type="Media",
            entity_id="42",
            payload=lambda result: {"result": result},
            mutation=lambda: "file-result",
        )
        == "file-result"
    )
    assert history.file_records[-1]["label"] == "Changed file-result"
    assert history.file_records[-1]["payload"] == {"result": "file-result"}
    assert history.file_records[-1]["entity_type"] == "Media"

    history.file_states = [{"digest": "rollback"}]
    try:
        app._run_file_history_action(
            action_label="Fail File",
            action_type="file.write",
            target_path=target,
            companion_suffixes=(".sidecar",),
            mutation=lambda: _raise(RuntimeError("write failed")),
        )
    except RuntimeError as error:
        assert str(error) == "write failed"
    else:
        raise AssertionError("file mutation failure should propagate")
    assert history.restored_files[-1] == (target, {"digest": "rollback"})

    history.file_states = [{"digest": "rollback-fails"}]
    history.fail_file_restore = True
    try:
        app._run_file_history_action(
            action_label="Fail File Rollback",
            action_type="file.write",
            target_path=target,
            companion_suffixes=(".sidecar",),
            mutation=lambda: _raise(RuntimeError("write failed again")),
        )
    except RuntimeError as error:
        assert str(error) == "write failed again"
    else:
        raise AssertionError("file mutation failure should propagate")
    assert "File rollback failed for file.write" in log_messages[-1]
    assert refreshes


def test_main_window_history_candidate_undo_redo_and_session_profile_workflows(
    monkeypatch,
) -> None:
    app = _app()
    critical_messages: list[tuple[str, str]] = []
    refresh_actions: list[str] = []
    refresh_after: list[str] = []
    dialog_refreshes: list[str] = []
    profile_events: list[tuple[str, object]] = []
    log_messages: list[str] = []

    monkeypatch.setattr(
        main_window.QMessageBox,
        "critical",
        lambda _parent, title, message: critical_messages.append((title, message)),
    )

    app.logger = SimpleNamespace(exception=lambda message: log_messages.append(message))
    app._refresh_history_actions = lambda: refresh_actions.append("actions")
    app._refresh_after_history_change = lambda: refresh_after.append("after")
    app.history_dialog = SimpleNamespace(
        isVisible=lambda: True,
        refresh_data=lambda: dialog_refreshes.append("dialog"),
    )

    class FakeHistoryManager:
        def __init__(self) -> None:
            self.current_entry = SimpleNamespace(
                entry_id=1,
                created_at="2026-05-26T08:00:00",
            )
            self.redo_entry = SimpleNamespace(
                entry_id=5,
                created_at="2026-05-26T08:05:00",
            )
            self.can_undo_value = True
            self.undo_result = SimpleNamespace(entry_id=10)
            self.redo_result = SimpleNamespace(entry_id=11)
            self.raise_undo = False
            self.raise_redo = False

        def can_undo(self) -> bool:
            return self.can_undo_value

        def get_current_visible_entry(self):
            return self.current_entry

        def get_default_redo_entry(self):
            return self.redo_entry

        def undo(self):
            if self.raise_undo:
                raise RuntimeError("profile undo failed")
            return self.undo_result

        def redo(self):
            if self.raise_redo:
                raise RuntimeError("profile redo failed")
            return self.redo_result

    class FakeSessionHistoryManager:
        def __init__(self) -> None:
            self.current_entry = SimpleNamespace(
                entry_id=2,
                created_at="2026-05-26T09:00:00",
            )
            self.redo_entry = SimpleNamespace(
                entry_id=3,
                created_at="2026-05-26T07:00:00",
            )
            self.can_undo_value = True
            self.undo_result = SimpleNamespace(entry_id=20)
            self.redo_result = SimpleNamespace(entry_id=21)
            self.raise_undo = False
            self.raise_redo = False

        def can_undo(self) -> bool:
            return self.can_undo_value

        def get_current_entry(self):
            return self.current_entry

        def get_default_redo_entry(self):
            return self.redo_entry

        def undo(self, owner):
            assert owner is app
            if self.raise_undo:
                raise RuntimeError("session undo failed")
            return self.undo_result

        def redo(self, owner):
            assert owner is app
            if self.raise_redo:
                raise RuntimeError("session redo failed")
            return self.redo_result

    history = FakeHistoryManager()
    session_history = FakeSessionHistoryManager()
    app.history_manager = history
    app.session_history_manager = session_history

    assert App._history_time_key(None) == datetime.min
    assert App._history_time_key(SimpleNamespace(created_at="")) == datetime.min
    assert App._history_time_key(SimpleNamespace(created_at="not-a-date")) == datetime.min
    assert App._history_time_key(history.current_entry) == datetime.fromisoformat(
        "2026-05-26T08:00:00"
    )

    assert app._get_best_history_candidate("undo")[0] == "session"
    assert app._get_best_history_candidate("redo")[0] == "profile"
    history.can_undo_value = False
    session_history.can_undo_value = False
    history.redo_entry = None
    session_history.redo_entry = None
    assert app._get_best_history_candidate("undo") == (None, None)
    assert app._get_best_history_candidate("redo") == (None, None)

    history.can_undo_value = True
    session_history.can_undo_value = True
    history.redo_entry = SimpleNamespace(entry_id=5, created_at="2026-05-26T08:05:00")
    session_history.redo_entry = SimpleNamespace(entry_id=3, created_at="2026-05-26T07:00:00")

    app.history_undo()
    assert refresh_actions[-1] == "actions"
    assert dialog_refreshes[-1] == "dialog"

    session_history.can_undo_value = False
    app.history_undo()
    assert refresh_after[-1] == "after"

    history.can_undo_value = False
    session_history.can_undo_value = True
    session_history.raise_undo = True
    app.history_undo()
    assert critical_messages[-1][0] == "Undo Error"
    assert "session undo failed" in critical_messages[-1][1]
    assert "Undo failed" in log_messages[-1]
    session_history.raise_undo = False

    app.history_redo()
    assert refresh_after[-1] == "after"

    history.redo_entry = None
    session_history.redo_entry = SimpleNamespace(entry_id=8, created_at="2026-05-26T10:00:00")
    app.history_redo()
    assert refresh_actions[-1] == "actions"
    assert dialog_refreshes[-1] == "dialog"

    session_history.raise_redo = True
    app.history_redo()
    assert critical_messages[-1][0] == "Redo Error"
    assert "session redo failed" in critical_messages[-1][1]
    assert "Redo failed" in log_messages[-1]

    app._activate_profile_in_background = lambda path: profile_events.append(("open", path))
    app._session_history_open_profile("/tmp/profile.db")
    assert profile_events[-1] == ("open", "/tmp/profile.db")

    app.current_db_path = "/tmp/current.db"
    app.conn = object()
    app._reload_profiles_list = lambda select_path=None: profile_events.append(
        ("reload", select_path)
    )
    app.refresh_table_preserve_view = lambda: profile_events.append(("refresh-table", None))
    app.populate_all_comboboxes = lambda: profile_events.append(("combos", None))
    app._session_history_reload_profiles()
    assert ("reload", "/tmp/current.db") in profile_events
    assert ("refresh-table", None) in profile_events
    assert ("combos", None) in profile_events

    deleted_profiles: list[str] = []
    app.profile_workflows = SimpleNamespace(
        profile_store=SimpleNamespace(delete_profile=lambda path: deleted_profiles.append(path))
    )
    app._close_database_connection = lambda: profile_events.append(("close", None))
    app._session_history_delete_profile("/tmp/current.db")
    assert ("close", None) in profile_events
    assert deleted_profiles == ["/tmp/current.db"]


def test_main_window_snapshot_history_actions_cover_prompt_task_and_refresh_paths(
    monkeypatch,
) -> None:
    app = _app()
    refresh_actions: list[str] = []
    refresh_after: list[str] = []
    dialog_refreshes: list[str] = []
    info_messages: list[tuple[str, str]] = []
    background_errors: list[tuple[str, str]] = []
    submitted_tasks: list[dict[str, object]] = []
    budget_events: list[tuple[str, int | None, bool]] = []
    budget_allowed = True

    class FakeHistoryManager:
        def __init__(self) -> None:
            self.deleted_snapshots: list[int] = []
            self.deleted_backups: list[int] = []
            self.restored_snapshots: list[int] = []
            self.created_labels: list[str | None] = []

        def create_manual_snapshot(self, label):
            self.created_labels.append(label)
            return SimpleNamespace(snapshot_id=77, label=label or "Untitled")

        def delete_snapshot_as_action(self, snapshot_id: int) -> None:
            self.deleted_snapshots.append(snapshot_id)

        def delete_backup(self, backup_id: int) -> None:
            self.deleted_backups.append(backup_id)

        def restore_snapshot_as_action(self, snapshot_id: int) -> str:
            self.restored_snapshots.append(snapshot_id)
            return "restored"

    history = FakeHistoryManager()
    app.history_manager = None
    app.create_manual_snapshot()
    app.delete_snapshot_from_history(1)
    app.delete_backup_from_history(2)
    app.restore_snapshot_from_history(3)

    app.history_manager = history
    app.logger = SimpleNamespace(info=lambda *_args, **_kwargs: None)
    app.history_dialog = SimpleNamespace(
        isVisible=lambda: True,
        refresh_data=lambda: dialog_refreshes.append("dialog"),
    )
    app._refresh_history_actions = lambda: refresh_actions.append("actions")
    app._refresh_after_history_change = lambda: refresh_after.append("after")
    app._estimate_history_snapshot_capture_bytes = lambda: 4096

    def prepare_budget(*, trigger_label, additional_bytes, interactive):
        budget_events.append((trigger_label, additional_bytes, interactive))
        return budget_allowed

    app._prepare_history_storage_for_projected_growth = prepare_budget
    app._enforce_history_storage_budget = (
        lambda *, trigger_label, interactive: budget_events.append(
            (f"enforce:{trigger_label}", None, interactive)
        )
    )
    app._show_background_task_error = (
        lambda title, _failure, *, user_message: background_errors.append((title, user_message))
    )

    class FakeContext:
        def __init__(self) -> None:
            self.statuses: list[str] = []

        def set_status(self, message: str) -> None:
            self.statuses.append(message)

    def submit_task(**kwargs):
        submitted_tasks.append(kwargs)
        ctx = FakeContext()
        result = kwargs["task_fn"](SimpleNamespace(history_manager=history), ctx)
        submitted_tasks.append({"ctx_statuses": ctx.statuses, "result": result})
        kwargs["on_success"](result)
        kwargs["on_error"](SimpleNamespace(message="boom"))
        return "task-id"

    app._submit_background_bundle_task = submit_task

    class FakeInputDialog:
        responses: list[tuple[str, bool]] = []

        @classmethod
        def getText(cls, *_args, **_kwargs):
            return cls.responses.pop(0)

    class FakeMessageBox:
        Yes = 1
        No = 2
        Question = object()

        responses: list[int] = []

        @classmethod
        def information(cls, _parent, title, message) -> None:
            info_messages.append((title, message))

        @classmethod
        def question(cls, *_args, **_kwargs):
            return cls.responses.pop(0)

    monkeypatch.setattr(main_window, "QInputDialog", FakeInputDialog)
    monkeypatch.setattr(main_window, "QMessageBox", FakeMessageBox)

    FakeInputDialog.responses = [("ignored", False)]
    app.create_manual_snapshot()
    assert submitted_tasks == []

    budget_allowed = False
    FakeInputDialog.responses = [("Budget Blocked", True)]
    app.create_manual_snapshot()
    assert submitted_tasks == []
    assert budget_events[-1] == ("manual snapshot", 4096, True)

    budget_allowed = True
    FakeInputDialog.responses = [("  Manual Label  ", True)]
    app.create_manual_snapshot()
    assert submitted_tasks[0]["title"] == "Create Snapshot"
    assert submitted_tasks[0]["kind"] == "read"
    assert submitted_tasks[1]["ctx_statuses"] == ["Capturing a full profile snapshot..."]
    assert history.created_labels == ["Manual Label"]
    assert info_messages[-1] == ("Snapshot Created", "Snapshot saved:\nManual Label")
    assert refresh_actions[-1] == "actions"
    assert dialog_refreshes[-1] == "dialog"
    assert budget_events[-1] == ("enforce:manual snapshot", None, True)
    assert background_errors[-1] == ("Snapshot Error", "Could not create the snapshot:")

    app.delete_snapshot_from_history(42)
    app.delete_backup_from_history(24)
    assert history.deleted_snapshots == [42]
    assert history.deleted_backups == [24]
    assert refresh_actions[-2:] == ["actions", "actions"]

    FakeMessageBox.responses = [FakeMessageBox.No]
    app.restore_snapshot_from_history(5)
    assert history.restored_snapshots == []

    budget_allowed = False
    FakeMessageBox.responses = [FakeMessageBox.Yes]
    app.restore_snapshot_from_history(5)
    assert budget_events[-1] == ("snapshot restore", 4096, True)
    assert history.restored_snapshots == []

    budget_allowed = True
    FakeMessageBox.responses = [FakeMessageBox.Yes]
    app.restore_snapshot_from_history(5)
    restore_task = submitted_tasks[-2]
    assert restore_task["title"] == "Restore Snapshot"
    assert restore_task["kind"] == "write"
    assert history.restored_snapshots == [5]
    assert refresh_after[-1] == "after"
    assert budget_events[-1] == ("enforce:snapshot restore", None, True)
    assert background_errors[-1] == ("Restore Snapshot", "Could not restore the snapshot:")

    dialogs: list[object] = []

    class FakeHistoryDialog:
        def __init__(self, owner, parent=None) -> None:
            dialogs.append((owner, parent))

        def exec(self) -> None:
            dialogs.append("exec")

    monkeypatch.setattr(main_window, "HistoryDialog", FakeHistoryDialog)
    app.open_history_dialog()
    assert dialogs == [(app, app), "exec"]


def test_main_window_database_maintenance_workflows_record_history_and_recover(
    monkeypatch, tmp_path: Path
) -> None:
    app = _app()
    current_db = tmp_path / "catalog.db"
    current_db.write_text("db", encoding="utf-8")
    backup_db = tmp_path / "backup.db"
    backup_db.write_text("backup", encoding="utf-8")
    safety_copy = tmp_path / "safety-copy.db"
    safety_copy.write_text("safety", encoding="utf-8")

    warnings: list[tuple[str, str]] = []
    information: list[tuple[str, str]] = []
    questions: list[tuple[str, str]] = []
    background_errors: list[tuple[str, str, str]] = []
    refreshes: list[str] = []
    log_events: list[tuple[str, dict[str, object]]] = []
    audits: list[tuple[str, str, object, str | None]] = []
    opened: list[str] = []
    closed: list[str] = []
    table_refreshes: list[str] = []
    logger_messages: list[str] = []
    bundle_statuses: list[list[str]] = []
    task_statuses: list[list[str]] = []

    class FakeMessageBox:
        Yes = 1
        No = 2

        question_responses: list[int] = []

        @classmethod
        def warning(cls, _parent, title, message) -> None:
            warnings.append((title, message))

        @classmethod
        def information(cls, _parent, title, message) -> None:
            information.append((title, message))

        @classmethod
        def question(cls, _parent, title, message, _buttons):
            questions.append((title, message))
            return cls.question_responses.pop(0)

    class FakeFileDialog:
        responses: list[tuple[str, str]] = []

        @classmethod
        def getOpenFileName(cls, *_args, **_kwargs):
            return cls.responses.pop(0)

    monkeypatch.setattr(main_window, "QMessageBox", FakeMessageBox)
    monkeypatch.setattr(main_window, "QFileDialog", FakeFileDialog)

    class FakeHistoryManager:
        FILE_COMPANION_SUFFIXES = (".wal", ".shm")

        def __init__(self) -> None:
            self.file_actions: list[dict[str, object]] = []
            self.backups: list[dict[str, object]] = []
            self.events: list[dict[str, object]] = []
            self.snapshots: list[SimpleNamespace] = []
            self.snapshot_actions: list[dict[str, object]] = []

        def capture_file_state(self, target_path, *, companion_suffixes=()):
            return {
                "target_path": str(target_path),
                "companion_suffixes": list(companion_suffixes),
                "exists": Path(target_path).exists(),
            }

        def record_file_write_action(self, **kwargs) -> None:
            self.file_actions.append(kwargs)

        def register_backup(self, backup_path, **kwargs) -> None:
            self.backups.append({"backup_path": str(backup_path), **kwargs})

        def record_event(self, **kwargs) -> None:
            self.events.append(kwargs)

        def capture_snapshot(self, *, kind, label):
            snapshot = SimpleNamespace(
                snapshot_id=len(self.snapshots) + 1,
                kind=kind,
                label=label,
            )
            self.snapshots.append(snapshot)
            return snapshot

        def register_snapshot(self, snapshot, **kwargs):
            self.snapshots.append(SimpleNamespace(snapshot=snapshot, **kwargs))
            return SimpleNamespace(snapshot_id=101)

        def record_snapshot_action(self, **kwargs) -> None:
            self.snapshot_actions.append(kwargs)

    class FakeMaintenance:
        def __init__(self) -> None:
            self.restore_results: list[SimpleNamespace] = []
            self.restore_calls: list[tuple[str, str]] = []

        def create_backup(self, _conn, src):
            assert Path(src) == current_db
            return SimpleNamespace(backup_path=backup_db, method="online")

        def verify_integrity(self, path):
            assert path == str(current_db)
            return "ok"

        def restore_database(self, source_path, target_path):
            self.restore_calls.append((str(source_path), str(target_path)))
            return self.restore_results.pop(0)

    class FakeBundleContext:
        def __init__(self) -> None:
            self.statuses: list[str] = []

        def set_status(self, message: str) -> None:
            self.statuses.append(message)

    history = FakeHistoryManager()
    maintenance = FakeMaintenance()
    app.current_db_path = str(tmp_path / "missing.db")
    app.backups_dir = tmp_path
    app.history_manager = history
    app.conn = object()
    app.database_maintenance = maintenance
    app.logger = SimpleNamespace(
        exception=lambda message, *args: logger_messages.append(message % args if args else message)
    )
    app._refresh_history_actions = lambda: refreshes.append("actions")
    app._log_event = lambda name, _message, **kwargs: log_events.append((name, kwargs))
    app._audit = lambda action, entity, *, ref_id=None, details=None: audits.append(
        (action, entity, ref_id, details)
    )
    app._audit_commit = lambda: audits.append(("COMMIT", "audit", None, None))
    app._show_background_task_error = (
        lambda title, failure, *, user_message: background_errors.append(
            (title, user_message, str(getattr(failure, "message", failure)))
        )
    )

    def submit_bundle_task(**kwargs):
        ctx = FakeBundleContext()
        result = kwargs["task_fn"](
            SimpleNamespace(
                conn=app.conn,
                database_maintenance=maintenance,
                history_manager=app.history_manager,
            ),
            ctx,
        )
        bundle_statuses.append(ctx.statuses)
        kwargs["on_success"](result)
        kwargs["on_error"](SimpleNamespace(message="simulated background failure"))

    app._submit_background_bundle_task = submit_bundle_task

    app.backup_database()
    assert warnings[-1] == ("Backup", "No current database to backup.")

    app.current_db_path = str(current_db)
    app.backup_database()
    assert bundle_statuses[-1] == ["Creating a database backup..."]
    assert history.file_actions[-1]["action_type"] == "file.db_backup"
    assert history.backups[-1]["kind"] == "manual"
    assert information[-1] == ("Backup", f"Backup created:\n{backup_db}")
    assert log_events[-1][0] == "db.backup"
    assert background_errors[-1][0] == "Backup Error"

    app.verify_integrity()
    assert bundle_statuses[-1] == ["Running SQLite integrity check..."]
    assert history.events[-1]["action_type"] == "db.verify"
    assert information[-1] == ("Integrity Check", "Result: ok")
    assert audits[-2][0] == "VERIFY"
    assert background_errors[-1][0] == "Integrity Error"

    def submit_restore_task(**kwargs):
        ctx = FakeBundleContext()
        result = kwargs["task_fn"](ctx)
        task_statuses.append(ctx.statuses)
        kwargs["on_success"](result)
        kwargs["on_error"](SimpleNamespace(message="restore worker failed"))

    app._submit_background_task = submit_restore_task
    app._close_database_connection = lambda: closed.append("close")
    app.open_database = lambda path: opened.append(str(path))
    app.refresh_table_preserve_view = lambda: table_refreshes.append("refresh")

    FakeFileDialog.responses = [("", "")]
    app.restore_database()
    assert not questions

    FakeFileDialog.responses = [(str(backup_db), "SQLite DB (*.db)")]
    FakeMessageBox.question_responses = [FakeMessageBox.No]
    app.restore_database()
    assert questions[-1][0] == "Restore"

    maintenance.restore_results = [
        SimpleNamespace(
            restored_path=current_db,
            integrity_result="ok",
            safety_copy_path=safety_copy,
        ),
        SimpleNamespace(restored_path=current_db, integrity_result="ok", safety_copy_path=None),
    ]
    FakeFileDialog.responses = [(str(backup_db), "SQLite DB (*.db)")]
    FakeMessageBox.question_responses = [FakeMessageBox.Yes]
    app.restore_database()

    assert task_statuses[-1] == ["Restoring the database from backup..."]
    assert opened[-2:] == [str(current_db), str(current_db)]
    assert table_refreshes[-1] == "refresh"
    assert history.backups[-1]["kind"] == "pre_restore_safety_copy"
    assert history.snapshot_actions[-1]["action_type"] == "db.restore"
    assert history.snapshot_actions[-1]["payload"]["file_effects"][0]["target_path"] == str(
        safety_copy
    )
    assert information[-1][0] == "Restore"
    assert log_events[-1][0] == "db.restore"
    assert background_errors[-1][0] == "Restore Error"

    def open_database_with_finalization_failure(path: str) -> None:
        opened.append(str(path))
        if str(path) == str(current_db) and opened.count(str(current_db)) == 3:
            raise RuntimeError("finalization failed")

    app.open_database = open_database_with_finalization_failure
    maintenance.restore_results = [
        SimpleNamespace(
            restored_path=current_db,
            integrity_result="ok",
            safety_copy_path=safety_copy,
        ),
        SimpleNamespace(restored_path=current_db, integrity_result="ok", safety_copy_path=None),
        SimpleNamespace(restored_path=current_db, integrity_result="ok", safety_copy_path=None),
    ]
    FakeFileDialog.responses = [(str(backup_db), "SQLite DB (*.db)")]
    FakeMessageBox.question_responses = [FakeMessageBox.Yes]
    app.restore_database()
    assert "Restore finalization failed" in logger_messages[-1]
    assert maintenance.restore_calls[-1] == (str(safety_copy), str(current_db))
    assert background_errors[-2] == (
        "Restore Error",
        "Failed to finalize the restored database:",
        "finalization failed",
    )


def test_main_window_album_track_ordering_dialog_covers_noop_and_reorder_paths(
    monkeypatch,
) -> None:
    app = _app()
    warnings: list[tuple[str, str]] = []
    information: list[tuple[str, str]] = []
    status_messages: list[tuple[str, int]] = []
    submitted_tasks: list[dict[str, object]] = []
    refresh_requests: list[tuple[dict[str, object], dict[str, object]]] = []
    progress_messages: list[str] = []
    updated_numbers: list[tuple[int, int]] = []
    log_events: list[tuple[str, dict[str, object]]] = []
    background_errors: list[tuple[str, str]] = []
    combo_refreshes: list[str] = []
    dock_refreshes: list[str] = []

    class FakeMessageBox:
        @classmethod
        def warning(cls, _parent, title, message) -> None:
            warnings.append((title, message))

        @classmethod
        def information(cls, _parent, title, message) -> None:
            information.append((title, message))

    monkeypatch.setattr(main_window, "QMessageBox", FakeMessageBox)

    class FakeDialog:
        exec_results: list[int] = []
        orders: list[list[int]] = []
        init_payloads: list[dict[str, object]] = []

        def __init__(self, owner, *, album_title, snapshots, parent) -> None:
            self.owner = owner
            self.album_title = album_title
            self.snapshots = snapshots
            self.parent = parent
            self.init_payloads.append(
                {"album_title": album_title, "track_ids": [s.track_id for s in snapshots]}
            )

        def exec(self):
            return self.exec_results.pop(0)

        def ordered_track_ids(self):
            return self.orders.pop(0)

    monkeypatch.setattr(main_window, "AlbumTrackOrderingDialog", FakeDialog)

    def snapshot(track_id: int, track_number: int, title: str):
        return SimpleNamespace(
            track_id=track_id,
            isrc=f"NL-AAA-26-{track_id:05d}",
            track_title=title,
            artist_name="Artist",
            additional_artists=["Guest"],
            album_title="Album",
            release_date="2026-05-26",
            track_length_sec=track_id * 10,
            iswc=None,
            upc=None,
            genre="Genre",
            track_number=track_number,
            catalog_number=None,
            catalog_number_mode=None,
            catalog_registry_entry_id=None,
            catalog_external_code_identifier_id=None,
            external_catalog_identifier_id=None,
            buma_work_number=None,
            composer=None,
            publisher=None,
            comments=None,
            lyrics=None,
            work_id=None,
            parent_track_id=None,
            relationship_type="original",
        )

    class FakeConnection:
        def __init__(self) -> None:
            self.commits = 0

        def __enter__(self):
            return self

        def __exit__(self, *_exc_info):
            return False

        def cursor(self):
            return "cursor"

        def commit(self) -> None:
            self.commits += 1

    class FakeTrackService:
        def __init__(self) -> None:
            self.snapshots = [snapshot(1, 9, "First"), snapshot(2, 8, "Second")]
            self.raise_list = False
            self.return_empty = False
            self.fetch_missing = False

        def list_album_group_snapshots(self, track_id, *, include_media_blobs):
            assert include_media_blobs is False
            if self.raise_list:
                raise RuntimeError("album lookup failed")
            if self.return_empty:
                return []
            assert int(track_id) == 1
            return list(self.snapshots)

        def fetch_track_snapshot(self, track_id, *, cursor, include_media_blobs):
            assert cursor == "cursor"
            assert include_media_blobs is False
            if self.fetch_missing:
                return None
            return next((item for item in self.snapshots if item.track_id == int(track_id)), None)

        def update_track(self, payload, *, cursor) -> None:
            assert cursor == "cursor"
            updated_numbers.append((int(payload.track_id), int(payload.track_number)))

    class FakeContext:
        def report_progress(self, *args, **kwargs) -> None:
            message = kwargs.get("message")
            if message is None and len(args) >= 3:
                message = args[2]
            if message:
                progress_messages.append(str(message))

    track_service = FakeTrackService()
    app.track_service = None
    app.conn = FakeConnection()
    app.logger = SimpleNamespace(info=lambda *_args, **_kwargs: None)
    app.current_db_path = "/tmp/profile.db"
    app._catalog_table_controller = lambda: SimpleNamespace(
        current_track_id=lambda: None,
        selected_track_ids=lambda: [],
    )
    app.statusBar = lambda: SimpleNamespace(
        showMessage=lambda message, timeout=0: status_messages.append((message, timeout))
    )
    app._capture_catalog_refresh_request = lambda **kwargs: {"request": kwargs}
    app._current_profile_name = lambda: "profile.db"
    app._scaled_progress_callback = (
        lambda callback, *, start, end: lambda value, maximum, message: callback(
            value=value, maximum=maximum, message=f"{start}-{end}:{message}"
        )
    )
    app._scaled_ui_progress_callback = lambda callback, *, start, end: lambda **kwargs: callback(
        value=kwargs.get("value", start),
        maximum=kwargs.get("maximum", end),
        message=kwargs.get("message", "ui"),
    )
    app._sync_releases_for_tracks = lambda track_ids, **_kwargs: [
        int(track_id) + 100 for track_id in track_ids
    ]
    app._load_catalog_ui_dataset_from_bundle = lambda _bundle, _ctx, **_kwargs: {"rows": ["loaded"]}
    app._apply_catalog_refresh_request = (
        lambda dataset, request, **_kwargs: refresh_requests.append((dataset, request))
    )
    app._advance_task_ui_progress = lambda ui_progress, **kwargs: ui_progress(
        value=kwargs.get("value", 0),
        maximum=100,
        message=kwargs.get("message", ""),
    )
    app.populate_all_comboboxes = lambda: combo_refreshes.append("combos")
    app._refresh_catalog_workspace_docks = lambda: dock_refreshes.append("docks")
    app._log_event = lambda name, _message, **kwargs: log_events.append((name, kwargs))
    app._show_background_task_error = (
        lambda title, _failure, *, user_message: background_errors.append((title, user_message))
    )

    def run_history_action(**kwargs):
        payload = kwargs["mutation"]()
        progress = kwargs.get("progress_callback")
        if progress is not None:
            progress(value=64, maximum=100, message=kwargs["record_progress"][1])
        return payload

    monkeypatch.setattr(main_window, "run_snapshot_history_action", run_history_action)

    def submit_album_order_task(**kwargs):
        submitted_tasks.append(kwargs)
        ctx = FakeContext()
        bundle = SimpleNamespace(
            conn=app.conn,
            track_service=track_service,
            release_service=object(),
            history_manager=object(),
        )
        result = kwargs["task_fn"](bundle, ctx)
        kwargs["on_success_before_cleanup"](
            result,
            lambda **progress: progress_messages.append(str(progress.get("message", ""))),
        )
        kwargs["on_success_after_cleanup"](result)
        kwargs["on_error"](SimpleNamespace(message="save failed"))

    app._submit_background_bundle_task = submit_album_order_task

    app.open_album_track_ordering_dialog()
    assert warnings[-1] == ("Album Track Ordering", "Open a profile first.")

    app.track_service = track_service
    app.open_album_track_ordering_dialog(track_id="bad")
    assert information[-1][0] == "Album Track Ordering"
    assert "Select a catalog row" in information[-1][1]

    app._catalog_table_controller = lambda: SimpleNamespace(
        current_track_id=lambda: None,
        selected_track_ids=lambda: [1],
    )
    assert app._current_catalog_context_track_id() == 1

    track_service.raise_list = True
    app.open_album_track_ordering_dialog(track_id=True)
    assert warnings[-1] == ("Album Track Ordering", "album lookup failed")
    track_service.raise_list = False

    track_service.return_empty = True
    app.open_album_track_ordering_dialog(track_id=1)
    assert information[-1][1] == "The selected track is not part of a saved album group."
    track_service.return_empty = False

    FakeDialog.exec_results = [QDialog.Rejected]
    app.open_album_track_ordering_dialog(track_id=1)
    assert submitted_tasks == []

    track_service.snapshots = [snapshot(1, 1, "First"), snapshot(2, 2, "Second")]
    FakeDialog.exec_results = [QDialog.Accepted]
    FakeDialog.orders = [[1, 2]]
    app.open_album_track_ordering_dialog(track_id=1)
    assert status_messages[-1] == ("Album track order unchanged.", 4000)
    assert submitted_tasks == []

    track_service.snapshots = [snapshot(1, 9, "First"), snapshot(2, 8, "Second")]
    FakeDialog.exec_results = [QDialog.Accepted]
    FakeDialog.orders = [[2, 1]]
    app.open_album_track_ordering_dialog(track_id=1)
    assert submitted_tasks[-1]["title"] == "Album Track Ordering"
    assert updated_numbers == [(2, 1), (1, 2)]
    assert refresh_requests[-1] == ({"rows": ["loaded"]}, {"request": {"focus_id": 1}})
    assert combo_refreshes == ["combos"]
    assert dock_refreshes == ["docks"]
    assert log_events[-1][0] == "track.album_order.update"
    assert status_messages[-1] == ('Updated album track ordering for "Album".', 5000)
    assert background_errors[-1] == (
        "Album Track Ordering",
        "Could not save the album track order:",
    )
    assert any("Saving reordered track 1 of 2" in message for message in progress_messages)

    track_service.fetch_missing = True
    FakeDialog.exec_results = [QDialog.Accepted]
    FakeDialog.orders = [[1]]
    try:
        app.open_album_track_ordering_dialog(track_id=1)
    except ValueError as exc:
        assert str(exc) == "Track 1 could not be loaded."
    else:
        raise AssertionError("missing reordered track should fail the worker mutation")


def test_main_window_editor_and_gs1_routing_cover_selection_and_dialog_failures(
    monkeypatch,
) -> None:
    app = _app()
    warnings: list[tuple[str, str]] = []
    information: list[tuple[str, str]] = []
    editor_events: list[tuple[str, object, object, object]] = []
    selected_editor_calls: list[tuple[int, list[int] | None, str | None]] = []
    gs1_events: list[tuple[str, int, list[int]]] = []
    combo_refreshes: list[str] = []

    class FakeMessageBox:
        @classmethod
        def warning(cls, _parent, title, message) -> None:
            warnings.append((title, message))

        @classmethod
        def information(cls, _parent, title, message) -> None:
            information.append((title, message))

    class FakeEditDialog:
        def __init__(
            self,
            track_id,
            owner,
            *,
            batch_track_ids=None,
            initial_focus_target=None,
        ) -> None:
            if int(track_id) == 99:
                raise ValueError("track 99 is unavailable")
            editor_events.append(
                ("init", int(track_id), list(batch_track_ids or []), initial_focus_target)
            )
            assert owner is app

        def exec(self) -> None:
            editor_events.append(("exec", None, None, None))

    class FakeGS1MetadataDialog:
        def __init__(self, *, app: object, track_id, batch_track_ids, parent) -> None:
            if int(track_id) == 13:
                raise ValueError("track 13 has no GS1 payload")
            assert app is parent
            gs1_events.append(("init", int(track_id), list(batch_track_ids or [])))

        def exec(self) -> None:
            gs1_events.append(("exec", -1, []))

    monkeypatch.setattr(main_window, "QMessageBox", FakeMessageBox)
    monkeypatch.setattr(main_window, "EditDialog", FakeEditDialog)
    monkeypatch.setattr(main_window, "GS1MetadataDialog", FakeGS1MetadataDialog)
    app.populate_all_comboboxes = lambda: combo_refreshes.append("combos")

    app.open_track_editor(5, batch_track_ids=[5, 6], initial_focus_target="track_title")
    assert editor_events == [
        ("init", 5, [5, 6], "track_title"),
        ("exec", None, None, None),
    ]
    assert combo_refreshes == ["combos"]

    app.open_track_editor(99)
    assert warnings[-1] == ("Edit Track", "track 99 is unavailable")

    app._catalog_table_controller = lambda: SimpleNamespace(selected_track_ids=lambda: [])
    app.open_selected_editor(True)
    assert warnings[-1][0] == "Edit Track"
    assert "Select one or more catalog rows" in warnings[-1][1]
    app.open_selected_editor("not-a-track")
    assert warnings[-1][0] == "Edit Track"

    app.open_track_editor = lambda track_id, **kwargs: selected_editor_calls.append(
        (
            int(track_id),
            kwargs.get("batch_track_ids"),
            kwargs.get("initial_focus_target"),
        )
    )
    app._catalog_table_controller = lambda: SimpleNamespace(selected_track_ids=lambda: [7, 8])
    app.open_selected_editor(None, initial_focus_target="artist")
    app.open_selected_editor(9, initial_focus_target="isrc")
    assert selected_editor_calls == [
        (7, [7, 8], "artist"),
        (9, [9], "isrc"),
    ]

    app._catalog_table_controller = lambda: SimpleNamespace(selected_track_ids=lambda: [])
    app.open_gs1_dialog(None)
    assert information[-1][0] == "GS1 Metadata"
    assert "Select a catalog row first" in information[-1][1]
    app.open_gs1_dialog("bad")
    assert warnings[-1][0] == "GS1 Metadata"
    assert "Could not determine" in warnings[-1][1]

    app._catalog_table_controller = lambda: SimpleNamespace(selected_track_ids=lambda: [10, 11])
    app.open_gs1_dialog(True)
    app.open_gs1_dialog(12)
    app.open_gs1_dialog(13)
    assert gs1_events == [
        ("init", 10, [10, 11]),
        ("exec", -1, []),
        ("init", 12, [12, 10, 11]),
        ("exec", -1, []),
    ]
    assert warnings[-1] == ("GS1 Metadata", "track 13 has no GS1 payload")

    class FakeModel:
        def index(self, row: int, column: int):
            return (row, column)

    class FakeEditController:
        def __init__(self) -> None:
            self.track_id: int | None = None

        def track_id_for_index(self, _index):
            return self.track_id

        def cell_target(self, _index, **_kwargs):
            return "base:track_title"

    edit_controller = FakeEditController()
    app.table = SimpleNamespace(model=lambda: FakeModel())
    app.BASE_HEADERS = ["Track Title"]
    app.active_custom_fields = []
    app._catalog_table_controller = lambda: edit_controller
    app._catalog_editor_focus_target = lambda cell_target: f"focus:{cell_target}"
    app.open_selected_editor = lambda track_id, **kwargs: selected_editor_calls.append(
        (
            int(track_id),
            None,
            kwargs.get("initial_focus_target"),
        )
    )

    app.edit_entry(SimpleNamespace(row=lambda: 2, column=lambda: 3))
    assert warnings[-1] == ("Edit Track", "Could not determine the selected track.")

    edit_controller.track_id = 44
    app.edit_entry(SimpleNamespace(row=lambda: 1))
    assert selected_editor_calls[-1] == (44, None, "focus:base:track_title")


def test_main_window_composition_shell_delegates_to_feature_controllers(monkeypatch) -> None:
    app = _app()
    calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

    def patch_function(target, name: str, *, result=None) -> None:
        def fake(*args, **kwargs):
            calls.append((name, args, kwargs))
            return result if result is not None else f"{name}:result"

        monkeypatch.setattr(target, name, fake)

    for name in [
        "_coerce_settings_bool",
        "_app_sound_enabled",
        "_startup_sound_enabled",
        "_current_app_sound_settings",
        "_app_sound_path",
        "_startup_sound_path",
        "_app_sound_effect",
        "_play_app_sound",
        "_schedule_startup_sound_after_startup",
        "_play_startup_sound",
        "_play_notice_sound",
        "_play_warning_sound",
        "_enable_app_interaction_sounds",
        "_install_app_sound_widget_hooks",
        "_message_box_notice_worthy",
        "_play_message_box_sound_once",
    ]:
        patch_function(main_window.app_sound_controller, name)

    assert App._coerce_settings_bool("yes", default=True) == "_coerce_settings_bool:result"
    assert app._app_sound_enabled("notice") == "_app_sound_enabled:result"
    assert app._startup_sound_enabled() == "_startup_sound_enabled:result"
    assert app._current_app_sound_settings() == "_current_app_sound_settings:result"
    assert app._app_sound_path("notice") == "_app_sound_path:result"
    assert app._startup_sound_path() == "_startup_sound_path:result"
    assert app._app_sound_effect("notice") == "_app_sound_effect:result"
    assert app._play_app_sound("notice", throttle_key="k", throttle_ms=25) == (
        "_play_app_sound:result"
    )
    assert (
        app._schedule_startup_sound_after_startup()
        == "_schedule_startup_sound_after_startup:result"
    )
    assert app._play_startup_sound() == "_play_startup_sound:result"
    assert app._play_notice_sound() == "_play_notice_sound:result"
    assert app._play_warning_sound() == "_play_warning_sound:result"
    assert app._enable_app_interaction_sounds() == "_enable_app_interaction_sounds:result"
    assert app._install_app_sound_widget_hooks("root") == "_install_app_sound_widget_hooks:result"
    assert app._message_box_notice_worthy("box") == "_message_box_notice_worthy:result"
    assert app._play_message_box_sound_once("widget") == "_play_message_box_sound_once:result"

    for name in [
        "_cleanup_ready_update_backup_handoff",
        "_cleanup_legacy_update_backup_siblings",
        "_cleanup_update_cache_artifacts",
        "_finalize_update_backup_handoff",
        "_mark_update_backup_handoff_ready_on_close",
        "_schedule_startup_update_check",
        "_run_startup_update_check",
        "check_for_updates",
        "_build_update_checker",
        "_start_update_check",
        "_handle_update_check_result",
        "_show_update_available_message",
        "_confirm_and_start_update_install",
        "_start_update_install",
        "_launch_prepared_update",
        "_show_update_release_notes",
        "_present_update_release_notes",
    ]:
        patch_function(main_window.update_controller, name)

    assert app._cleanup_ready_update_backup_handoff("a") == (
        "_cleanup_ready_update_backup_handoff:result"
    )
    assert app._cleanup_legacy_update_backup_siblings() == (
        "_cleanup_legacy_update_backup_siblings:result"
    )
    assert app._cleanup_update_cache_artifacts() == "_cleanup_update_cache_artifacts:result"
    assert app._finalize_update_backup_handoff() == "_finalize_update_backup_handoff:result"
    assert app._mark_update_backup_handoff_ready_on_close() == (
        "_mark_update_backup_handoff_ready_on_close:result"
    )
    assert app._schedule_startup_update_check() == "_schedule_startup_update_check:result"
    assert app._run_startup_update_check() == "_run_startup_update_check:result"
    assert app.check_for_updates(manual=True) == "check_for_updates:result"
    assert app._build_update_checker() == "_build_update_checker:result"
    assert app._start_update_check("checker") == "_start_update_check:result"
    assert app._handle_update_check_result("result") == "_handle_update_check_result:result"
    assert app._show_update_available_message("result") == "_show_update_available_message:result"
    assert app._confirm_and_start_update_install("result") == (
        "_confirm_and_start_update_install:result"
    )
    assert app._start_update_install("result") == "_start_update_install:result"
    assert app._launch_prepared_update("handoff") == "_launch_prepared_update:result"
    assert app._show_update_release_notes("notes") == "_show_update_release_notes:result"
    assert app._present_update_release_notes("notes") == "_present_update_release_notes:result"

    for name in [
        "_history_snapshot_summary",
        "_custom_value_field_column_name",
        "_count_orphaned_custom_values",
        "_legacy_promoted_field_repair_candidates",
        "_diagnostics_managed_file_scan_counts",
        "_build_diagnostics_progress_plan",
        "_application_storage_admin_service",
        "_history_retention_settings_for_storage_summary",
        "_application_storage_summary_payload",
        "_application_storage_item_payload",
        "_build_application_storage_audit_payload",
        "_build_diagnostics_report",
    ]:
        patch_function(main_window.diagnostics_report, name)
    for name in [
        "_preview_diagnostics_repair",
        "_run_diagnostics_repair",
        "_load_application_storage_audit_async",
        "_run_application_storage_cleanup_async",
        "_load_diagnostics_report_async",
        "_run_bundle_diagnostics_repair",
        "_apply_diagnostics_repair_result",
        "_run_diagnostics_repair_async",
    ]:
        patch_function(main_window.diagnostics_controller, name)

    assert app._history_snapshot_summary("conn") == "_history_snapshot_summary:result"
    assert app._custom_value_field_column_name("conn") == "_custom_value_field_column_name:result"
    assert app._count_orphaned_custom_values("conn") == "_count_orphaned_custom_values:result"
    assert app._legacy_promoted_field_repair_candidates("conn") == (
        "_legacy_promoted_field_repair_candidates:result"
    )
    assert app._diagnostics_managed_file_scan_counts("conn") == (
        "_diagnostics_managed_file_scan_counts:result"
    )
    assert app._build_diagnostics_progress_plan(conn="conn", current_db_path="db") == (
        "_build_diagnostics_progress_plan:result"
    )
    assert app._preview_diagnostics_repair("repair", {"status": "warning"}) == (
        "_preview_diagnostics_repair:result"
    )
    assert app._run_diagnostics_repair("repair") == "_run_diagnostics_repair:result"
    assert app._application_storage_admin_service() == "_application_storage_admin_service:result"
    assert app._history_retention_settings_for_storage_summary("db") == (
        "_history_retention_settings_for_storage_summary:result"
    )
    assert app._application_storage_summary_payload("audit", current_db_path="db") == (
        "_application_storage_summary_payload:result"
    )
    assert app._application_storage_item_payload("item") == (
        "_application_storage_item_payload:result"
    )
    assert app._build_application_storage_audit_payload(current_db_path="db") == (
        "_build_application_storage_audit_payload:result"
    )
    assert app._load_application_storage_audit_async(owner="owner") == (
        "_load_application_storage_audit_async:result"
    )
    assert app._run_application_storage_cleanup_async(["cache"], allow_warning_deletes=True) == (
        "_run_application_storage_cleanup_async:result"
    )
    assert app._build_diagnostics_report(conn="conn", data_root="root") == (
        "_build_diagnostics_report:result"
    )
    assert app._load_diagnostics_report_async(owner="owner") == (
        "_load_diagnostics_report_async:result"
    )
    assert (
        app._run_bundle_diagnostics_repair(
            "repair",
            {"status": "warning"},
            bundle="bundle",
            current_db_path="db",
            data_root="root",
        )
        == "_run_bundle_diagnostics_repair:result"
    )
    assert app._apply_diagnostics_repair_result("repair", {"fixed": True}) == (
        "_apply_diagnostics_repair_result:result"
    )
    assert app._run_diagnostics_repair_async("repair", owner="owner") == (
        "_run_diagnostics_repair_async:result"
    )

    for name in [
        "_theme_setting_defaults",
        "_theme_setting_keys",
        "_normalize_theme_string",
        "_format_theme_qss_issues",
        "_normalize_theme_font_family",
        "_normalize_theme_color",
        "_load_theme_settings",
        "_normalize_theme_settings",
        "_stored_theme_payload",
        "_sanitize_theme_library",
        "_load_theme_library",
        "_save_theme_library",
        "_color_relative_luminance",
        "_contrast_ratio",
        "_pick_contrasting_color",
        "_shift_color",
        "_effective_theme_settings",
        "_save_theme_settings",
        "_blob_icon_setting_defaults",
        "_load_blob_icon_settings",
        "_save_blob_icon_settings",
        "_reset_blob_badge_render_cache",
        "_active_custom_qss",
        "_build_theme_stylesheet",
        "_set_application_theme_stylesheet",
        "_apply_theme",
        "_prepare_theme_application_payload",
        "_apply_prepared_theme_payload",
        "_refresh_menu_theme_state",
        "_apply_theme_with_loading",
    ]:
        patch_function(main_window.theme_controller, name)

    assert App._theme_setting_defaults() == "_theme_setting_defaults:result"
    assert App._theme_setting_keys() == "_theme_setting_keys:result"
    assert App._normalize_theme_string("  theme  ") == "_normalize_theme_string:result"
    assert App._format_theme_qss_issues(["issue"]) == "_format_theme_qss_issues:result"
    assert App._normalize_theme_font_family("", "Sans") == "_normalize_theme_font_family:result"
    assert App._normalize_theme_color("#fff") == "_normalize_theme_color:result"
    assert app._load_theme_settings() == "_load_theme_settings:result"
    assert app._normalize_theme_settings({"theme": "dark"}) == "_normalize_theme_settings:result"
    assert app._stored_theme_payload({"theme": "dark"}) == "_stored_theme_payload:result"
    assert app._sanitize_theme_library({"A": {}}) == "_sanitize_theme_library:result"
    assert app._load_theme_library() == "_load_theme_library:result"
    assert app._save_theme_library({"A": {}}) == "_save_theme_library:result"
    assert App._color_relative_luminance("#000") == "_color_relative_luminance:result"
    assert App._contrast_ratio("#000", "#fff") == "_contrast_ratio:result"
    assert App._pick_contrasting_color("#000") == "_pick_contrasting_color:result"
    assert App._shift_color("#000", 10) == "_shift_color:result"
    assert app._effective_theme_settings({"theme": "dark"}) == "_effective_theme_settings:result"
    assert app._save_theme_settings({"theme": "dark"}) == "_save_theme_settings:result"
    assert App._blob_icon_setting_defaults() == "_blob_icon_setting_defaults:result"
    assert app._load_blob_icon_settings() == "_load_blob_icon_settings:result"
    assert app._save_blob_icon_settings({}) == "_save_blob_icon_settings:result"
    assert app._reset_blob_badge_render_cache() == "_reset_blob_badge_render_cache:result"
    assert app._active_custom_qss() == "_active_custom_qss:result"
    assert app._build_theme_stylesheet({}) == "_build_theme_stylesheet:result"
    assert app._set_application_theme_stylesheet("qt-app", "css") == (
        "_set_application_theme_stylesheet:result"
    )
    assert app._apply_theme({}) == "_apply_theme:result"
    assert app._prepare_theme_application_payload({}) == (
        "_prepare_theme_application_payload:result"
    )
    assert app._apply_prepared_theme_payload({}) == "_apply_prepared_theme_payload:result"
    assert app._refresh_menu_theme_state() == "_refresh_menu_theme_state:result"
    assert app._apply_theme_with_loading({}, title="Theme", description="Apply") == (
        "_apply_theme_with_loading:result"
    )

    for name in [
        "_stored_window_title_override",
        "_current_owner_company_name",
        "_resolve_window_title",
        "_load_identity",
        "_apply_identity",
        "_current_settings_values",
        "_apply_settings_changes",
        "open_settings_dialog",
        "export_application_settings_bundle",
        "import_application_settings_bundle",
        "_apply_single_setting_value",
    ]:
        patch_function(main_window.settings_controller, name)
    for name in [
        "_current_auto_snapshot_settings",
        "_current_history_retention_settings",
        "_application_history_storage_budget_mb",
        "_set_application_history_storage_budget_mb",
        "_apply_history_snapshot_retention_policy",
        "_path_size_recursive",
        "_allocated_path_size",
        "_estimate_history_snapshot_capture_bytes",
        "_prepare_history_storage_for_projected_growth",
        "_enforce_history_storage_budget",
        "_refresh_auto_snapshot_schedule",
        "_current_auto_snapshot_marker",
        "_on_auto_snapshot_timer",
    ]:
        patch_function(main_window.history_retention_controller, name)
    for name in [
        "_apply_storage_layout",
        "_reconcile_startup_storage_root",
        "_maybe_run_storage_layout_migration",
        "_run_storage_layout_migration",
        "_reload_profiles_list",
        "_on_profile_changed",
        "create_new_profile",
        "browse_profile",
        "remove_selected_profile",
        "_close_database_connection",
    ]:
        patch_function(main_window.profile_session, name)

    assert app._stored_window_title_override() == "_stored_window_title_override:result"
    assert app._current_owner_company_name() == "_current_owner_company_name:result"
    assert app._resolve_window_title("Custom") == "_resolve_window_title:result"
    assert app._load_identity() == "_load_identity:result"
    assert app._apply_identity() == "_apply_identity:result"
    assert app._apply_storage_layout(active_data_root="root") == "_apply_storage_layout:result"
    assert app._reconcile_startup_storage_root() == "_reconcile_startup_storage_root:result"
    assert app._maybe_run_storage_layout_migration() == "_maybe_run_storage_layout_migration:result"
    assert app._run_storage_layout_migration() == "_run_storage_layout_migration:result"
    assert app._current_auto_snapshot_settings() == "_current_auto_snapshot_settings:result"
    assert app._current_history_retention_settings() == "_current_history_retention_settings:result"
    assert app._application_history_storage_budget_mb(default=100) == (
        "_application_history_storage_budget_mb:result"
    )
    assert app._set_application_history_storage_budget_mb(200) == (
        "_set_application_history_storage_budget_mb:result"
    )
    assert app._apply_history_snapshot_retention_policy(trigger_label="test") == (
        "_apply_history_snapshot_retention_policy:result"
    )
    assert App._path_size_recursive(Path("/tmp")) == "_path_size_recursive:result"
    assert App._allocated_path_size(Path("/tmp/file")) == "_allocated_path_size:result"
    assert app._estimate_history_snapshot_capture_bytes() == (
        "_estimate_history_snapshot_capture_bytes:result"
    )
    assert (
        app._prepare_history_storage_for_projected_growth(
            trigger_label="test",
            additional_bytes=10,
            interactive=False,
        )
        == "_prepare_history_storage_for_projected_growth:result"
    )
    assert app._enforce_history_storage_budget(trigger_label="test") == (
        "_enforce_history_storage_budget:result"
    )
    assert app._refresh_auto_snapshot_schedule() == "_refresh_auto_snapshot_schedule:result"
    assert app._current_auto_snapshot_marker() == "_current_auto_snapshot_marker:result"
    assert app._on_auto_snapshot_timer() == "_on_auto_snapshot_timer:result"
    assert app._current_settings_values() == "_current_settings_values:result"
    assert app._apply_settings_changes({"before": 1}, {"after": 2}, show_confirmation=True) == (
        "_apply_settings_changes:result"
    )
    assert app.open_settings_dialog("theme") == "open_settings_dialog:result"
    assert app.export_application_settings_bundle() == "export_application_settings_bundle:result"
    assert app.import_application_settings_bundle() == "import_application_settings_bundle:result"
    assert app._apply_single_setting_value("artist_code", "12") == (
        "_apply_single_setting_value:result"
    )
    assert app._reload_profiles_list("/tmp/profile.db") == "_reload_profiles_list:result"
    assert app._on_profile_changed(2) == "_on_profile_changed:result"
    assert app.create_new_profile() == "create_new_profile:result"
    assert app.browse_profile() == "browse_profile:result"
    assert app.remove_selected_profile() == "remove_selected_profile:result"
    assert app._close_database_connection() == "_close_database_connection:result"

    patch_function(main_window, "initialize_foreground_services")
    patch_function(
        main_window.audio_conversion_controller, "_refresh_audio_conversion_action_states"
    )
    app._init_services()
    assert app._refresh_audio_conversion_action_states("a", state=True) == (
        "_refresh_audio_conversion_action_states:result"
    )

    assert calls
    assert any(name == "_current_app_sound_settings" and args == (app,) for name, args, _ in calls)
    assert any(
        name == "_build_diagnostics_report" and kwargs["data_root"] == "root"
        for name, _args, kwargs in calls
    )

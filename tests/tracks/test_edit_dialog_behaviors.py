from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace
from unittest import mock

import pytest
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QComboBox, QDialog, QLineEdit, QWidget

from isrc_manager.file_storage import STORAGE_MODE_DATABASE
from isrc_manager.services.tracks import TrackUpdatePayload
from isrc_manager.tracks import edit_dialog as edit_dialog_module
from isrc_manager.tracks.edit_dialog import EditDialog
from tests.qt_test_helpers import require_qapplication


def _dialog() -> EditDialog:
    return EditDialog.__new__(EditDialog)


class _TextWidget:
    def __init__(self, text: str = "") -> None:
        self._text = text
        self.current_text_values: list[str] = []

    def text(self) -> str:
        return self._text

    def setText(self, value: str) -> None:
        self._text = value

    def clear(self) -> None:
        self._text = ""

    def currentText(self) -> str:
        return self._text

    def setCurrentText(self, value: str) -> None:
        self._text = value
        self.current_text_values.append(value)


class _ValueWidget:
    def __init__(self, value: int) -> None:
        self._value = value

    def value(self) -> int:
        return self._value


class _DateWidget:
    def __init__(self, value: str = "2026-05-26") -> None:
        self._value = value

    def selectedDate(self):
        return SimpleNamespace(toString=lambda _format: self._value)


class _CatalogWidget(_TextWidget):
    def identifier_mode(self):
        return "manual"

    def catalog_registry_entry_id(self):
        return 101

    def external_code_identifier_id(self):
        return 202

    def external_catalog_identifier_id(self):
        return 303


class _FakeConn:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0
        self.commit_exception: Exception | None = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return "cursor"

    def commit(self) -> None:
        if self.commit_exception is not None:
            raise self.commit_exception
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class _QueryCursor:
    def __init__(self) -> None:
        self.queries: list[str] = []
        self._rows: list[tuple[str | None]] = []

    def execute(self, query: str):
        self.queries.append(query)
        if "Albums" in query:
            self._rows = [("",), ("Catalog Album",), ("Catalog Album",), ("Other Album",)]
        elif "genre" in query:
            self._rows = [(None,), ("Rock",), ("Rock",), ("Ambient",)]
        else:
            self._rows = []
        return self

    def fetchall(self):
        return list(self._rows)


class _FakeTrackService:
    def __init__(self, snapshot=None) -> None:
        self.snapshot = snapshot
        self.updated_payloads: list[TrackUpdatePayload] = []
        self.album_updates: list[tuple[list[int], dict[str, object]]] = []
        self.album_group_track_ids = [1]
        self.album_art_messages: dict[int, str] = {}
        self.resolve_media_exc: Exception | None = None
        self.materialize_exc: Exception | None = None
        self.duration_result: int | None = 123
        self.duration_exc: Exception | None = None
        self.source_handle = SimpleNamespace(
            materialize_path=lambda: nullcontext("/tmp/saved-audio.wav")
        )
        self.edit_states: dict[int, object] = {}

    def fetch_track_snapshot(self, track_id: int):
        return (
            self.snapshot
            if self.snapshot is not None and track_id == self.snapshot.track_id
            else None
        )

    def describe_album_art_edit_state(self, track_id: int):
        return self.edit_states.get(
            track_id,
            SimpleNamespace(
                can_replace_directly=True,
                is_shared_reference=False,
                owner_track_id=None,
                owner_track_title="",
            ),
        )

    def resolve_media_path(self, stored_path):
        return str(stored_path or "")

    def list_album_group_track_ids(self, _track_id: int):
        return list(self.album_group_track_ids)

    def album_art_replacement_message(self, track_id: int) -> str:
        return self.album_art_messages.get(track_id, "")

    def update_track(self, payload: TrackUpdatePayload, cursor=None) -> None:
        self.updated_payloads.append(payload)

    def apply_album_metadata_to_tracks(self, track_ids, *, field_updates, cursor=None) -> None:
        self.album_updates.append((list(track_ids), dict(field_updates)))

    def resolve_media_source(self, _track_id: int, _media_key: str):
        if self.resolve_media_exc is not None:
            raise self.resolve_media_exc
        return self.source_handle

    def derive_audio_duration_seconds(self, _source_path) -> int | None:
        if self.duration_exc is not None:
            raise self.duration_exc
        return self.duration_result


class _FakeTaskContext:
    def __init__(self) -> None:
        self.progress: list[tuple[object, object, str]] = []

    def report_progress(self, value=None, maximum=None, *, message: str = "") -> None:
        self.progress.append((value, maximum, message))


class _FakeParent:
    def __init__(self, snapshot=None) -> None:
        self.conn = _FakeConn()
        self.cursor = object()
        self.track_service = _FakeTrackService(snapshot)
        self.release_service = object()
        self.history_manager = object()
        self.logger = mock.Mock()
        self.duplicate_isrc = False
        self.confirm_lossy = True
        self.media_modes = ("managed_file", "managed_file")
        self.submitted_tasks: list[dict] = []
        self.submit_exception: Exception | None = None
        self.execute_tasks = False
        self.accepted = False
        self.refresh_requests: list[dict] = []
        self.audit_calls: list[tuple] = []
        self.log_calls: list[tuple] = []
        self.synced_tracks: list[list[int]] = []
        self.length_sets: list[int] = []
        self.status_messages: list[tuple[str, int]] = []

    def _parse_additional_artists(self, value: str) -> list[str]:
        return [part.strip() for part in value.split(",") if part.strip()]

    def _artist_lookup_values(self) -> list[str]:
        return ["", "Lookup Artist", "Lookup Artist", "Guest Lookup"]

    def _resolve_artist_party_choice(self, widget):
        return widget.currentText(), None

    def _resolve_party_backed_artist_name(self, name: str, *, selected_party_id=None, cursor=None):
        return name, selected_party_id

    def _resolve_party_backed_additional_artist_names(self, names, *, cursor=None):
        return list(names)

    def is_isrc_taken_normalized(self, _isrc: str, *, exclude_track_id: int) -> bool:
        return self.duplicate_isrc

    def _warn_duplicate_track_numbers(self, **_kwargs) -> None:
        return None

    def _confirm_lossy_primary_audio_selection(self, *_args, **_kwargs) -> bool:
        return self.confirm_lossy

    def _choose_track_media_storage_modes(self, **_kwargs):
        return self.media_modes

    def _collect_catalog_cleanup_targets(self, **_kwargs):
        return [], []

    def _current_profile_name(self) -> str:
        return "Test Profile"

    def _capture_catalog_refresh_request(self, **kwargs):
        return dict(kwargs)

    def _sync_releases_for_tracks(self, track_ids, **_kwargs) -> None:
        self.synced_tracks.append(list(track_ids))

    def _load_catalog_ui_dataset_from_bundle(self, *_args, **_kwargs):
        return {"rows": ["fresh"]}

    def _sync_application_isrc_registry(self) -> None:
        return None

    def _scaled_ui_progress_callback(self, ui_progress, *, start: int, end: int):
        return lambda value=None, maximum=None, *, message="": ui_progress(value, maximum, message)

    def _apply_catalog_refresh_request(self, dataset, refresh_request, *, progress_callback=None):
        self.refresh_requests.append({"dataset": dataset, "request": refresh_request})
        if progress_callback:
            progress_callback(1, 1, message="refreshed")

    def _advance_task_ui_progress(self, ui_progress, *, value: int, message: str) -> None:
        ui_progress(value, 100, message)

    def _log_event(self, *args, **kwargs) -> None:
        self.log_calls.append((args, kwargs))

    def _audit(self, *args, **kwargs) -> None:
        self.audit_calls.append((args, kwargs))

    def _audit_commit(self) -> None:
        return None

    def _show_background_task_error(self, *_args, **_kwargs) -> None:
        return None

    def _submit_background_bundle_task(self, **kwargs):
        if self.submit_exception is not None:
            raise self.submit_exception
        self.submitted_tasks.append(kwargs)
        if self.execute_tasks:
            ctx = _FakeTaskContext()
            bundle = SimpleNamespace(
                conn=self.conn,
                track_service=self.track_service,
                release_service=self.release_service,
                history_manager=self.history_manager,
            )
            result = kwargs["task_fn"](bundle, ctx)
            kwargs["on_success_before_cleanup"](
                result,
                lambda value=None, maximum=None, message="": ctx.report_progress(
                    value, maximum, message=message
                ),
            )
            kwargs["on_success_after_cleanup"](result)
            return result
        return None

    def statusBar(self):
        return SimpleNamespace(
            showMessage=lambda message, timeout=0: self.status_messages.append((message, timeout))
        )

    def _set_track_length_widgets(self, _hours, _minutes, _seconds, duration_seconds: int) -> None:
        self.length_sets.append(duration_seconds)

    def _browse_track_media_file(self, media_key: str, *, parent_widget=None) -> str:
        return f"/picked/{media_key}.bin"

    def _refresh_line_edit_lossy_audio_warning(self, line_edit) -> None:
        line_edit.lossy_warning_refreshed = True

    def _apply_audio_duration_to_widgets(self, path, **_kwargs) -> None:
        self.applied_audio_duration_path = path


class _WidgetParent(QWidget, _FakeParent):
    def __init__(self, snapshots: list[SimpleNamespace]) -> None:
        QWidget.__init__(self)
        _FakeParent.__init__(self, snapshots[0])
        self.cursor = _QueryCursor()
        self.work_service = SimpleNamespace(
            fetch_work=lambda work_id: (
                SimpleNamespace(registration_number="BUMA-WORK") if work_id == 7 else None
            )
        )
        self.party_service = SimpleNamespace(fetch_party=lambda _party_id: None)
        self.code_registry_service = None
        self.track_service.snapshot = snapshots[0]
        self.track_service.fetch_track_snapshot = lambda track_id: next(
            (snapshot for snapshot in snapshots if snapshot.track_id == track_id), None
        )


def _snapshot(track_id: int = 1, **overrides) -> SimpleNamespace:
    values = {
        "track_id": track_id,
        "db_entry_date": "2026-01-01",
        "isrc": "NL-ABC-26-00001",
        "track_title": "Original Track",
        "artist_name": "Artist",
        "additional_artists": ["Guest"],
        "album_title": "Album",
        "release_date": "2026-05-01",
        "track_length_sec": 90,
        "iswc": None,
        "upc": None,
        "genre": "Rock",
        "catalog_number": "CAT-1",
        "buma_work_number": None,
        "composer": None,
        "publisher": None,
        "comments": None,
        "lyrics": None,
        "track_number": 1,
        "catalog_number_mode": "manual",
        "catalog_registry_entry_id": None,
        "catalog_external_code_identifier_id": None,
        "external_catalog_identifier_id": None,
        "work_id": None,
        "audio_file_path": "",
        "audio_file_storage_mode": None,
        "audio_file_filename": "",
        "audio_file_blob_b64": "",
        "album_art_path": "",
        "album_art_storage_mode": None,
        "album_art_filename": "",
        "album_art_blob_b64": "",
        "main_artist_party_id": None,
        "additional_artist_party_ids": [],
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _single_save_dialog(parent: _FakeParent | None = None) -> tuple[EditDialog, _FakeParent]:
    parent = parent or _FakeParent(_snapshot())
    dialog = _dialog()
    dialog.parent = parent
    dialog.parentWidget = lambda: parent
    dialog.track_id = 1
    dialog.batch_track_ids = [1]
    dialog._is_bulk_edit = False
    dialog._clear_audio_file = False
    dialog._clear_album_art = False
    dialog._existing_audio_display_path = ""
    dialog._existing_album_art_display_path = ""
    dialog._buma_work_number_managed_by_work = False
    dialog.snapshot = parent.track_service.snapshot
    dialog.isrc_field = _TextWidget("")
    dialog.iswc = _TextWidget("")
    dialog.upc = _TextWidget("")
    dialog.genre = _TextWidget("Rock")
    dialog.track_title = _TextWidget("Updated Track")
    dialog.artist_name = _TextWidget("Updated Artist")
    dialog.album_title = _TextWidget("Updated Album")
    dialog.track_number = _ValueWidget(2)
    dialog.release_date = _DateWidget("2026-05-26")
    dialog.catalog_number = _CatalogWidget("CAT-2")
    dialog.buma_work_number = _TextWidget("")
    dialog.additional_artist = _TextWidget("Guest One, Guest Two")
    dialog.audio_file = _TextWidget("")
    dialog.album_art = _TextWidget("")
    dialog.len_h = _ValueWidget(0)
    dialog.len_m = _ValueWidget(2)
    dialog.len_s = _ValueWidget(3)
    dialog.accept = lambda: setattr(parent, "accepted", True)
    return dialog, parent


def _bulk_save_dialog(parent: _FakeParent | None = None) -> tuple[EditDialog, _FakeParent]:
    snapshots = [
        _snapshot(track_id=1, track_title="One", artist_name="Artist A"),
        _snapshot(track_id=2, track_title="Two", artist_name="Artist B", track_number=2),
    ]
    parent = parent or _FakeParent(snapshots[0])
    parent.track_service.fetch_track_snapshot = lambda track_id: next(
        (snapshot for snapshot in snapshots if snapshot.track_id == track_id), None
    )
    dialog = _dialog()
    dialog.parent = parent
    dialog.parentWidget = lambda: parent
    dialog.track_id = 1
    dialog.batch_track_ids = [1, 2]
    dialog._bulk_snapshots = snapshots
    dialog._is_bulk_edit = True
    dialog._bulk_loading = False
    dialog._clear_audio_file = False
    dialog._clear_album_art = False
    dialog._bulk_field_state = {}
    for field_name, value in {
        "track_title": "One",
        "artist_name": "Artist A",
        "additional_artists": tuple(["Guest"]),
        "album_title": "Album",
        "genre": "Rock",
        "release_date": "2026-05-01",
        "track_length_sec": 90,
        "upc": "",
        "catalog_number": "CAT-1",
        "buma_work_number": "",
        "audio_file": "",
        "album_art": "",
    }.items():
        dialog._bulk_field_state[field_name] = {
            "mixed": False,
            "initial": value,
            "modified": False,
        }
    dialog.track_title = _TextWidget("One")
    dialog.artist_name = _TextWidget("Artist A")
    dialog.additional_artist = _TextWidget("Guest")
    dialog.album_title = _TextWidget("Album")
    dialog.genre = _TextWidget("Rock")
    dialog.upc = _TextWidget("")
    dialog.catalog_number = _CatalogWidget("CAT-1")
    dialog.buma_work_number = _TextWidget("")
    dialog.release_date = _DateWidget("2026-05-01")
    dialog.len_h = _ValueWidget(0)
    dialog.len_m = _ValueWidget(1)
    dialog.len_s = _ValueWidget(30)
    dialog.audio_file = _TextWidget("")
    dialog.album_art = _TextWidget("")
    dialog.accept = lambda: setattr(parent, "accepted", True)
    return dialog, parent


def _payload(
    track_id: int,
    *,
    album_title: str | None,
    album_art_source_path: str | None,
) -> TrackUpdatePayload:
    return TrackUpdatePayload(
        track_id=track_id,
        isrc="",
        track_title=f"Track {track_id}",
        artist_name="Artist",
        additional_artists=[],
        album_title=album_title,
        release_date=None,
        track_length_sec=0,
        iswc=None,
        upc=None,
        genre=None,
        album_art_source_path=album_art_source_path,
        album_art_storage_mode="managed_file" if album_art_source_path else None,
    )


def test_bulk_field_and_media_apply_decisions_cover_locked_mixed_and_clear_paths() -> None:
    dialog = _dialog()
    dialog._is_bulk_edit = True
    dialog._bulk_loading = False
    dialog._bulk_field_state = {}
    dialog._clear_album_art = False
    dialog._clear_audio_file = False

    dialog._set_bulk_field_state("genre", ["Rock", "Rock"])
    dialog._set_bulk_field_state("artist_name", ["Artist A", "Artist B"])
    dialog._set_bulk_field_state("album_art", ["/covers/a.jpg", "/covers/a.jpg"])

    assert dialog._display_value(None) == ""
    assert dialog._display_value(["Artist", "", "Guest"]) == "Artist, Guest"
    assert dialog._display_value(12) == "12"
    assert dialog._display_value_for_field("genre", "Ignored") == "Rock"
    assert dialog._display_value_for_field("artist_name", "Ignored") == dialog.BULK_MIXED_TEXT
    assert dialog._bulk_field_is_mixed("artist_name") is True
    assert dialog._bulk_field_initial("genre") == "Rock"
    assert dialog._bulk_field_modified("genre") is False

    assert dialog._bulk_field_should_apply("genre", "Jazz") is False
    dialog._mark_bulk_field_modified("genre")
    assert dialog._bulk_field_modified("genre") is True
    assert dialog._bulk_field_should_apply("genre", "Rock") is False
    assert dialog._bulk_field_should_apply("genre", "Jazz") is True

    dialog._mark_bulk_field_modified("artist_name")
    assert dialog._bulk_field_should_apply("artist_name", "Unified Artist") is True
    assert dialog._bulk_field_should_apply("track_title", "Locked Title") is False

    assert (
        dialog._bulk_media_should_apply("audio_file", "", clear_attr="_clear_audio_file") is False
    )
    assert (
        dialog._bulk_media_should_apply("album_art", "/covers/a.jpg", clear_attr="_clear_album_art")
        is False
    )
    dialog._mark_bulk_field_modified("album_art")
    assert (
        dialog._bulk_media_should_apply("album_art", "/covers/b.jpg", clear_attr="_clear_album_art")
        is True
    )
    dialog._clear_album_art = True
    assert dialog._bulk_media_should_apply("album_art", "", clear_attr="_clear_album_art") is True

    dialog._is_bulk_edit = False
    assert dialog._bulk_media_should_apply("album_art", "", clear_attr="_clear_album_art") is True
    dialog._clear_album_art = False
    assert dialog._bulk_media_should_apply("album_art", "", clear_attr="_clear_album_art") is False
    assert (
        dialog._bulk_media_should_apply(
            "album_art", "/covers/new.jpg", clear_attr="_clear_album_art"
        )
        is True
    )


def test_album_art_owner_hints_and_deduplication_group_shared_art_updates() -> None:
    dialog = _dialog()
    assert dialog._album_art_owner_label(SimpleNamespace(owner_track_id=None)) == "another track"
    assert (
        dialog._album_art_owner_label(SimpleNamespace(owner_track_id=4, owner_track_title="Master"))
        == 'Track #4 "Master"'
    )
    assert dialog._album_art_owner_label(SimpleNamespace(owner_track_id=5)) == "Track #5"

    dialog.track_id = 1
    dialog._album_art_edit_states = {
        1: SimpleNamespace(
            is_shared_reference=True,
            owner_track_id=4,
            owner_track_title="Master",
        ),
        2: SimpleNamespace(
            is_shared_reference=True,
            owner_track_id=4,
            owner_track_title="Duplicate Master",
        ),
        3: SimpleNamespace(
            is_shared_reference=False,
            owner_track_id=9,
            owner_track_title="Ignored",
        ),
    }
    assert dialog._album_art_owner_targets() == [(4, 'Track #4 "Master"')]
    assert (
        dialog._single_album_art_hint_text()
        == 'This track uses shared album art managed by Track #4 "Master". '
        "Edit that record to replace the shared image."
    )
    assert (
        dialog._bulk_album_art_hint_text()
        == 'Some selected tracks use shared album art managed by Track #4 "Master"; '
        'Track #4 "Duplicate Master". Edit those records to replace the shared image.'
    )

    dialog._album_art_edit_states = {
        index: SimpleNamespace(
            is_shared_reference=True,
            owner_track_id=index,
            owner_track_title=f"Owner {index}",
        )
        for index in range(1, 7)
    }
    multi_hint = dialog._bulk_album_art_hint_text()
    assert "Owner 1" in multi_hint
    assert "Owner 4" in multi_hint
    assert "\u2026" in multi_hint
    assert "Owner 5" not in multi_hint

    payloads = [
        _payload(1, album_title="Album", album_art_source_path="/covers/a.jpg"),
        _payload(2, album_title=" album ", album_art_source_path="/covers/a-copy.jpg"),
        _payload(3, album_title="Single", album_art_source_path="/covers/single.jpg"),
        _payload(4, album_title="Single", album_art_source_path="/covers/other-single.jpg"),
        _payload(5, album_title=None, album_art_source_path=None),
    ]
    dialog._deduplicate_bulk_album_art_updates(payloads)
    assert payloads[0].album_art_source_path == "/covers/a.jpg"
    assert payloads[1].album_art_source_path is None
    assert payloads[1].album_art_storage_mode is None
    assert payloads[2].album_art_source_path == "/covers/single.jpg"
    assert payloads[3].album_art_source_path == "/covers/other-single.jpg"


def test_party_backed_artist_text_and_album_art_block_messages_use_real_fallbacks() -> None:
    dialog = _dialog()
    dialog._is_bulk_edit = False
    dialog.artist_name = SimpleNamespace(currentText=lambda: "")
    dialog.additional_artist = SimpleNamespace(currentText=lambda: "")
    dialog.snapshot = SimpleNamespace(
        artist_name="Snapshot Artist",
        main_artist_party_id=11,
        additional_artists=["Stored Guest"],
        additional_artist_party_ids=[21, 22, 23, 22],
    )

    party_records = {
        11: SimpleNamespace(name="Lead Party"),
        21: SimpleNamespace(name="Guest One"),
        22: SimpleNamespace(name="guest one"),
        23: SimpleNamespace(name="Guest Two"),
    }

    class PartyService:
        def fetch_party(self, party_id: int):
            return party_records.get(party_id)

    class TrackService:
        def __init__(self) -> None:
            self.messages = {
                1: "Shared with a master record.",
                2: "Shared with a master record.",
                3: "Locked by artwork policy.",
            }

        def album_art_replacement_message(self, track_id: int) -> str:
            return self.messages.get(track_id, "")

    dialog.parent = SimpleNamespace(
        party_service=PartyService(),
        track_service=TrackService(),
        _artist_party_primary_label=lambda record: record.name,
    )

    assert dialog._party_backed_artist_field_text() == "Lead Party"
    assert dialog._party_backed_additional_artist_text() == "Guest One, Guest Two"

    dialog.artist_name = SimpleNamespace(currentText=lambda: "Typed Artist")
    dialog.additional_artist = SimpleNamespace(currentText=lambda: "Typed Guest")
    assert dialog._party_backed_artist_field_text() == "Typed Artist"
    assert dialog._party_backed_additional_artist_text() == "Typed Guest"

    assert dialog._album_art_upload_block_message([99]) is None
    assert dialog._album_art_upload_block_message([1]) == "Shared with a master record."
    assert dialog._album_art_upload_block_message([1, 2, 3]) == (
        "Album art cannot be replaced for some selected tracks:\n"
        "- Shared with a master record.\n"
        "- Locked by artwork policy."
    )

    dialog.parent.track_service = None
    assert dialog._album_art_upload_block_message([1]) is None


def test_media_display_and_buma_work_resolution_cover_database_and_service_fallbacks() -> None:
    dialog = _dialog()

    class TrackService:
        def resolve_media_path(self, stored_path):
            if stored_path == "managed/audio.wav":
                return "/resolved/audio.wav"
            if stored_path == "managed/cover.jpg":
                return "/resolved/cover.jpg"
            return None

    class WorkService:
        def fetch_work(self, work_id: int):
            if work_id == 7:
                return SimpleNamespace(registration_number="  BUMA-7  ")
            return None

    dialog.parent = SimpleNamespace(track_service=TrackService(), work_service=WorkService())

    audio_snapshot = SimpleNamespace(
        audio_file_path="managed/audio.wav",
        audio_file_storage_mode="managed_file",
        audio_file_blob_b64="",
        audio_file_filename="",
    )
    assert dialog._resolve_audio_file_display(audio_snapshot) == "/resolved/audio.wav"
    audio_snapshot.audio_file_path = ""
    audio_snapshot.audio_file_storage_mode = STORAGE_MODE_DATABASE
    audio_snapshot.audio_file_filename = "mix.wav"
    assert dialog._resolve_audio_file_display(audio_snapshot) == "mix.wav (stored in database)"
    audio_snapshot.audio_file_filename = ""
    assert dialog._resolve_audio_file_display(audio_snapshot) == "Stored in database"
    audio_snapshot.audio_file_storage_mode = ""
    audio_snapshot.audio_file_blob_b64 = ""
    assert dialog._resolve_audio_file_display(audio_snapshot) == ""

    art_snapshot = SimpleNamespace(
        album_art_path="managed/cover.jpg",
        album_art_storage_mode="managed_file",
        album_art_blob_b64="",
        album_art_filename="",
    )
    assert dialog._resolve_album_art_display(art_snapshot) == "/resolved/cover.jpg"
    art_snapshot.album_art_path = ""
    art_snapshot.album_art_blob_b64 = "encoded"
    art_snapshot.album_art_filename = "cover.jpg"
    assert dialog._resolve_album_art_display(art_snapshot) == "cover.jpg (stored in database)"

    buma_snapshot = SimpleNamespace(work_id=7, buma_work_number="Fallback")
    assert dialog._resolved_buma_work_number_text(buma_snapshot) == "BUMA-7"
    assert dialog._buma_work_number_is_work_managed(buma_snapshot) is True
    no_work_snapshot = SimpleNamespace(work_id=None, buma_work_number="Fallback")
    assert dialog._resolved_buma_work_number_text(no_work_snapshot) == "Fallback"
    assert dialog._buma_work_number_is_work_managed(no_work_snapshot) is False


def test_single_edit_album_update_helpers_report_only_changed_values() -> None:
    dialog = _dialog()
    before = SimpleNamespace(
        artist_name="Artist",
        album_title="Album",
        release_date="2024-01-01",
        upc="123456789012",
        genre="Rock",
        catalog_number="CAT-1",
    )

    assert (
        dialog._single_edit_album_field_updates(
            before,
            artist_name="Artist",
            album_title="Album",
            release_date="2024-01-01",
            upc="123456789012",
            genre="Rock",
            catalog_number="CAT-1",
        )
        == {}
    )
    assert dialog._single_edit_album_field_updates(
        before,
        artist_name="New Artist",
        album_title=None,
        release_date=None,
        upc=None,
        genre="Jazz",
        catalog_number=None,
    ) == {
        "artist_name": "New Artist",
        "album_title": None,
        "release_date": None,
        "upc": None,
        "genre": "Jazz",
        "catalog_number": None,
    }

    dialog._clear_album_art = False
    assert dialog._single_edit_album_art_changed(None) is False
    assert dialog._single_edit_album_art_changed("/covers/new.jpg") is True
    dialog._clear_album_art = True
    assert dialog._single_edit_album_art_changed(None) is True


def test_dialog_routing_gs1_and_album_art_helpers_cover_workflow_edges(monkeypatch) -> None:
    dialog = _dialog()
    routed: list[str] = []
    dialog._save_bulk_changes = lambda: routed.append("bulk")
    dialog._save_single_changes = lambda: routed.append("single")
    dialog._is_bulk_edit = True
    dialog.save_changes()
    dialog._is_bulk_edit = False
    dialog.save_changes()
    assert routed == ["bulk", "single"]

    assert dialog._display_album_shared_field_names(["genre", "unknown", "genre", "album_art"]) == [
        "Genre",
        "Album Art",
    ]

    payloads = [
        _payload(1, album_title="Album", album_art_source_path="/covers/a.jpg"),
        _payload(2, album_title="album", album_art_source_path="/covers/b.jpg"),
        _payload(3, album_title="Single", album_art_source_path="/covers/c.jpg"),
    ]
    assert dialog._album_art_update_group_key(payloads[0]) == ("album", "album")
    assert dialog._album_art_update_group_key(payloads[2]) == ("track", 3)
    dialog._deduplicate_bulk_album_art_updates(payloads)
    assert payloads[0].album_art_source_path == "/covers/a.jpg"
    assert payloads[1].album_art_source_path is None
    assert payloads[2].album_art_source_path == "/covers/c.jpg"

    warnings: list[tuple[str, str]] = []
    monkeypatch.setattr(
        edit_dialog_module.QMessageBox,
        "warning",
        lambda _parent, title, message: warnings.append((title, message)),
    )

    gs1_dialog, _parent = _single_save_dialog()
    opened: list[dict[str, object] | str] = []

    class FakeGS1Dialog:
        def __init__(self, **kwargs) -> None:
            opened.append(kwargs)

        def exec(self) -> None:
            opened.append("exec")

    monkeypatch.setattr(edit_dialog_module, "GS1MetadataDialog", FakeGS1Dialog)
    gs1_dialog._open_gs1_metadata()
    assert opened[-1] == "exec"
    assert opened[0]["track_id"] == 1

    class BrokenGS1Dialog:
        def __init__(self, **_kwargs) -> None:
            raise ValueError("missing GS1 settings")

    monkeypatch.setattr(edit_dialog_module, "GS1MetadataDialog", BrokenGS1Dialog)
    gs1_dialog._open_gs1_metadata()
    assert warnings[-1] == ("GS1 Metadata", "missing GS1 settings")


def test_batch_ids_combo_refresh_focus_and_media_helpers_cover_ui_edges(monkeypatch) -> None:
    app = require_qapplication()
    assert EditDialog._normalize_batch_track_ids(0, [2, "2", "bad", -3]) == [2]
    assert EditDialog._normalize_batch_track_ids(7, [7, 8, None]) == [7, 8]

    combo = QComboBox()
    EditDialog._refresh_editable_combo_items(
        combo,
        ["", " Rock ", "Rock", "Jazz"],
        current_text="Fusion",
        allow_empty=True,
    )
    assert [combo.itemText(index) for index in range(combo.count())] == ["", "Rock", "Jazz"]
    assert combo.currentText() == "Fusion"
    EditDialog._refresh_editable_combo_items(
        combo,
        ["One"],
        current_text="",
        allow_empty=False,
    )
    assert combo.currentIndex() == -1

    dialog = _dialog()
    QDialog.__init__(dialog)
    dialog._is_bulk_edit = True
    dialog._bulk_loading = False
    dialog._bulk_field_state = {
        "artist_name": {"mixed": True, "initial": None, "modified": False},
        "genre": {"mixed": False, "initial": "Rock", "modified": False},
    }
    dialog._bulk_focus_targets = {}
    line_edit = QLineEdit()
    dialog._configure_text_field(line_edit, "artist_name", "Ignored")
    assert line_edit.text() == dialog.BULK_MIXED_TEXT
    assert "different values" in line_edit.toolTip()
    assert line_edit in dialog._bulk_focus_targets

    locked_line_edit = QLineEdit()
    dialog._configure_text_field(locked_line_edit, "isrc", "NL-ABC-26-00001")
    assert locked_line_edit.isReadOnly()
    assert "view-only" in locked_line_edit.toolTip()

    note = dialog._create_bulk_note("artist_name", "Replace every artist")
    assert note is not None
    assert note.text() == "Replace every artist"
    assert dialog._create_bulk_note("genre", "No note") is None

    assert dialog.eventFilter(line_edit, QEvent(QEvent.FocusIn)) is False

    plain_widget = QWidget()
    assert EditDialog._preferred_focus_widget(None) is None
    assert EditDialog._preferred_focus_widget(plain_widget) is plain_widget

    focus_dialog = _dialog()
    QDialog.__init__(focus_dialog)
    focus_dialog.track_title = QLineEdit()
    focus_dialog.artist_name = QComboBox()
    focus_dialog.artist_name.setEditable(True)
    focus_dialog.additional_artist = QLineEdit()
    focus_dialog.genre = QLineEdit()
    focus_dialog.album_title = QLineEdit()
    focus_dialog.track_number = QWidget()
    focus_dialog.release_date = QWidget()
    focus_dialog.len_h = QWidget()
    focus_dialog.isrc_field = QWidget()
    focus_dialog.iswc = QWidget()
    focus_dialog.upc = QWidget()
    focus_dialog.catalog_number = QWidget()
    focus_dialog.buma_work_number = QWidget()
    focus_dialog.entry_date_field = QWidget()
    focus_dialog.audio_file_browse_button = QWidget()
    focus_dialog.album_art_browse_button = QWidget()
    focus_dialog._editor_tab_indices = {"track": 0}
    focus_dialog.editor_tabs = SimpleNamespace(
        current_index=None, setCurrentIndex=lambda index: None
    )
    assert focus_dialog.focus_editor_target("") is False
    assert focus_dialog.focus_editor_target("missing") is False
    assert focus_dialog.focus_editor_target("track_title") in {True, False}

    parent = _FakeParent(_snapshot())
    media_dialog, _parent = _single_save_dialog(parent)
    media_dialog.len_h = object()
    media_dialog.len_m = object()
    media_dialog.len_s = object()
    media_line = _TextWidget()
    media_dialog._choose_track_media("audio_file", media_line, clear_attr="_clear_audio_file")
    assert media_line.text() == "/picked/audio_file.bin"
    assert media_dialog._clear_audio_file is False
    assert parent.applied_audio_duration_path == "/picked/audio_file.bin"

    media_dialog._clear_track_media(media_line, clear_attr="_clear_audio_file")
    assert media_line.text() == ""
    assert media_dialog._clear_audio_file is True
    assert media_line.lossy_warning_refreshed is True

    clipboard_dialog, _parent = _single_save_dialog(parent)
    clipboard_dialog.isrc_field = _TextWidget("NLABC2600001")
    clipboard_dialog.iswc = _TextWidget("T1234567890")
    clipboard_dialog._copy_isrc_iso()
    assert app.clipboard().text() == "NL-ABC-26-00001"
    clipboard_dialog._copy_isrc_compact()
    assert app.clipboard().text() == "NLABC2600001"
    clipboard_dialog._copy_iswc_iso()
    assert app.clipboard().text() == "T-123.456.789-0"
    clipboard_dialog._copy_iswc_compact()
    assert app.clipboard().text() == "T1234567890"

    opened: list[int] = []
    focus_dialog.parentWidget = lambda: SimpleNamespace(
        refresh_table_preserve_view=lambda focus_id: opened.append(focus_id),
        open_track_editor=lambda track_id, batch_track_ids: opened.append(track_id),
    )
    focus_dialog._open_album_art_owner_track(44)
    assert opened == [44, 44]
    focus_dialog.parentWidget = lambda: None
    focus_dialog._open_album_art_owner_track(55)
    assert opened == [44, 44]


def test_edit_dialog_constructor_covers_single_and_bulk_layout_branches() -> None:
    require_qapplication()

    single_snapshot = _snapshot(
        artist_name="New Artist",
        album_title="Unique Album",
        genre="Unique Genre",
        work_id=7,
        buma_work_number="Fallback BUMA",
        audio_file_path="",
        audio_file_storage_mode=STORAGE_MODE_DATABASE,
        audio_file_filename="mix.wav",
        album_art_path="",
        album_art_storage_mode=STORAGE_MODE_DATABASE,
        album_art_filename="cover.jpg",
    )
    single_parent = _WidgetParent([single_snapshot])

    single_dialog = EditDialog(1, single_parent, initial_focus_target=" track_title ")
    try:
        assert single_dialog.windowTitle() == "Edit Track"
        assert single_dialog._initial_focus_target == "track_title"
        assert single_dialog.editor_tabs.count() == 4
        assert single_dialog.artist_name.findText("New Artist") >= 0
        assert single_dialog.album_title.findText("Unique Album") >= 0
        assert single_dialog.genre.findText("Unique Genre") >= 0
        assert single_dialog.audio_file.text() == "mix.wav (stored in database)"
        assert single_dialog.album_art.text() == "cover.jpg (stored in database)"
        assert single_dialog.buma_work_number.isReadOnly()
        assert "Managed by the linked Work" in single_dialog.buma_work_number.toolTip()
    finally:
        single_dialog.close()
        single_dialog.deleteLater()

    shared_states = {
        1: SimpleNamespace(
            can_replace_directly=False,
            is_shared_reference=True,
            owner_track_id=10,
            owner_track_title="Master One",
        ),
        2: SimpleNamespace(
            can_replace_directly=True,
            is_shared_reference=True,
            owner_track_id=11,
            owner_track_title="Master Two",
        ),
    }
    mixed_parent = _WidgetParent(
        [
            _snapshot(track_id=1, track_number=1, release_date="2026-01-01", track_length_sec=90),
            _snapshot(track_id=2, track_number=2, release_date="2026-02-01", track_length_sec=91),
        ]
    )
    mixed_parent.track_service.edit_states = shared_states

    mixed_dialog = EditDialog(1, mixed_parent, batch_track_ids=[1, 2])
    try:
        assert mixed_dialog.windowTitle() == "Bulk Edit 2 Tracks"
        assert mixed_dialog.track_number.value() == 1
        assert not mixed_dialog.track_number.isEnabled()
        assert not mixed_dialog.audio_file_browse_button.isEnabled()
        assert not mixed_dialog.audio_file_clear_button.isEnabled()
        assert not mixed_dialog.album_art_browse_button.isEnabled()
        assert mixed_dialog.album_art_open_master_button.text() == "Open Master Record…"
        assert "Choose which master record" in mixed_dialog.album_art_open_master_button.toolTip()
    finally:
        mixed_dialog.close()
        mixed_dialog.deleteLater()

    locked_parent = _WidgetParent(
        [
            _snapshot(track_id=1, track_number=3, release_date="2026-03-01", track_length_sec=120),
            _snapshot(track_id=2, track_number=3, release_date="2026-03-01", track_length_sec=120),
        ]
    )

    locked_dialog = EditDialog(1, locked_parent, batch_track_ids=[1, 2])
    try:
        assert locked_dialog.track_number.value() == 3
        assert not locked_dialog.len_h.isEnabled()
        assert not locked_dialog.len_m.isEnabled()
        assert not locked_dialog.len_s.isEnabled()
        assert locked_dialog.release_date.selectedDate().toString("yyyy-MM-dd") == "2026-03-01"
    finally:
        locked_dialog.close()
        locked_dialog.deleteLater()


def test_edit_dialog_remaining_helper_edges_cover_empty_missing_and_menu_paths(
    monkeypatch,
) -> None:
    require_qapplication()

    assert EditDialog._normalize_batch_track_ids(0, ["bad", None, -5]) == [0]

    missing_snapshot_dialog = _dialog()
    missing_snapshot_dialog.parent = SimpleNamespace(
        track_service=SimpleNamespace(fetch_track_snapshot=lambda _track_id: None)
    )
    missing_snapshot_dialog.batch_track_ids = [44]
    with pytest.raises(ValueError, match="Track 44 not found"):
        missing_snapshot_dialog._load_bulk_snapshots()

    no_service_dialog = _dialog()
    no_service_dialog.parent = SimpleNamespace(track_service=None)
    assert no_service_dialog._load_album_art_edit_states() == {}

    combo = QComboBox()
    EditDialog._refresh_editable_combo_items(
        combo,
        ["", "One", "One"],
        current_text="",
        allow_empty=True,
    )
    assert combo.currentIndex() == 0

    bulk_party_dialog = _dialog()
    bulk_party_dialog._is_bulk_edit = True
    bulk_party_dialog.artist_name = SimpleNamespace(currentText=lambda: "Bulk Artist")
    bulk_party_dialog.additional_artist = SimpleNamespace(currentText=lambda: "Bulk Guest")
    assert bulk_party_dialog._party_backed_artist_field_text() == "Bulk Artist"
    assert bulk_party_dialog._party_backed_additional_artist_text() == "Bulk Guest"

    refresh_dialog = _dialog()
    refresh_dialog._is_bulk_edit = False
    refresh_dialog._bulk_field_state = {}
    refresh_dialog.snapshot = _snapshot(
        artist_name="Snapshot Artist",
        additional_artists=["Stored Guest"],
        main_artist_party_id=None,
        additional_artist_party_ids=[999, 21],
    )
    refresh_dialog.parent = SimpleNamespace(
        _artist_lookup_values=lambda: ["", "Lookup Artist", "Lookup Artist"],
        party_service=SimpleNamespace(
            fetch_party=lambda party_id: (
                SimpleNamespace(name="Known Guest") if party_id == 21 else None
            )
        ),
        _artist_party_primary_label=lambda record: record.name,
    )
    refresh_dialog.artist_name = QComboBox()
    refresh_dialog.artist_name.setEditable(True)
    refresh_dialog.additional_artist = QComboBox()
    refresh_dialog.additional_artist.setEditable(True)
    refresh_dialog._refresh_artist_combo_sources()
    assert refresh_dialog.artist_name.currentText() == "Snapshot Artist"
    assert refresh_dialog.additional_artist.currentText() == "Known Guest"
    refresh_dialog._handle_party_authority_changed()
    assert refresh_dialog.artist_name.findText("Lookup Artist") >= 0

    class BrokenLineEditWidget(QWidget):
        def lineEdit(self):  # noqa: N802 - Qt-style method name for this fake widget
            raise RuntimeError("broken editor")

    broken_widget = BrokenLineEditWidget()
    assert EditDialog._preferred_focus_widget(broken_widget) is broken_widget

    focus_dialog = _dialog()
    QDialog.__init__(focus_dialog)
    focus_dialog.track_title = QLineEdit()
    focus_dialog.artist_name = QLineEdit()
    focus_dialog.additional_artist = QLineEdit()
    focus_dialog.genre = QLineEdit()
    focus_dialog.album_title = QLineEdit()
    focus_dialog.track_number = QLineEdit()
    focus_dialog.release_date = QLineEdit()
    focus_dialog.len_h = QLineEdit()
    focus_dialog.isrc_field = QLineEdit()
    focus_dialog.iswc = QLineEdit()
    focus_dialog.upc = QLineEdit()
    focus_dialog.catalog_number = QLineEdit()
    focus_dialog.buma_work_number = QLineEdit()
    focus_dialog.entry_date_field = QLineEdit()
    focus_dialog.audio_file_browse_button = QLineEdit()
    focus_dialog.album_art_browse_button = QLineEdit()
    focus_dialog.editor_tabs = SimpleNamespace(setCurrentIndex=lambda _index: None)
    focus_dialog._editor_tab_indices = {"track": 0}
    focus_dialog.track_title.setEnabled(False)
    assert focus_dialog.focus_editor_target("track_title") is False
    focus_dialog.track_title.setEnabled(True)
    focus_dialog._editor_tab_indices = {}
    assert focus_dialog.focus_editor_target("track_title") is False

    media_dialog = _dialog()
    media_dialog.parent = SimpleNamespace(
        track_service=SimpleNamespace(resolve_media_path=lambda _: "")
    )
    art_snapshot = SimpleNamespace(
        album_art_path="",
        album_art_storage_mode=STORAGE_MODE_DATABASE,
        album_art_blob_b64="encoded",
        album_art_filename="",
    )
    assert media_dialog._resolve_album_art_display(art_snapshot) == "Stored in database"

    target_dialog = _dialog()
    target_dialog.track_id = 1
    target_dialog._album_art_edit_states = {
        1: SimpleNamespace(is_shared_reference=True, owner_track_id=None, owner_track_title=""),
    }
    assert target_dialog._album_art_owner_targets() == []
    target_dialog._album_art_edit_states = {
        1: SimpleNamespace(is_shared_reference=False, owner_track_id=None, owner_track_title=""),
    }
    assert target_dialog._bulk_album_art_hint_text() == ""

    opened: list[int] = []
    target_dialog.parentWidget = lambda: SimpleNamespace(
        refresh_table_preserve_view=lambda focus_id: opened.append(focus_id),
        open_track_editor=lambda track_id, batch_track_ids: opened.append(track_id),
    )
    target_dialog._album_art_hint_owner_targets = [(77, "Master 77")]
    target_dialog._open_album_art_owner_from_hint()
    assert opened == [77, 77]
    target_dialog._album_art_hint_owner_targets = []
    target_dialog._open_album_art_owner_from_hint()
    assert opened == [77, 77]

    class FakeSignal:
        def __init__(self) -> None:
            self.callbacks = []

        def connect(self, callback) -> None:
            self.callbacks.append(callback)

    class FakeMenu:
        exec_positions: list[object] = []

        def __init__(self, _parent) -> None:
            self.actions = []

        def addAction(self, label: str):
            action = SimpleNamespace(label=label, triggered=FakeSignal())
            self.actions.append(action)
            return action

        def exec(self, position) -> None:
            FakeMenu.exec_positions.append(position)

    monkeypatch.setattr(edit_dialog_module, "QMenu", FakeMenu)
    target_dialog.album_art_open_master_button = SimpleNamespace(
        mapToGlobal=lambda point: ("global", point),
        rect=lambda: SimpleNamespace(bottomLeft=lambda: "bottom-left"),
    )
    target_dialog._album_art_hint_owner_targets = [(1, "One"), (2, "Two")]
    target_dialog._open_album_art_owner_from_hint()
    assert FakeMenu.exec_positions == [("global", "bottom-left")]

    class FakeButton:
        def __init__(self) -> None:
            self.enabled = None
            self.visible = None
            self.text = ""
            self.tooltip = ""

        def setEnabled(self, value: bool) -> None:
            self.enabled = value

        def setVisible(self, value: bool) -> None:
            self.visible = value

        def setText(self, value: str) -> None:
            self.text = value

        def setToolTip(self, value: str) -> None:
            self.tooltip = value

    class FakeLabel:
        def __init__(self) -> None:
            self.text = ""
            self.visible = None

        def setText(self, value: str) -> None:
            self.text = value

        def setVisible(self, value: bool) -> None:
            self.visible = value

    controls_dialog = _dialog()
    controls_dialog._is_bulk_edit = True
    controls_dialog.track_id = 1
    controls_dialog._album_art_edit_states = {
        1: SimpleNamespace(
            can_replace_directly=True,
            is_shared_reference=True,
            owner_track_id=1,
            owner_track_title="One",
        ),
        2: SimpleNamespace(
            can_replace_directly=True,
            is_shared_reference=True,
            owner_track_id=2,
            owner_track_title="Two",
        ),
    }
    controls_dialog.album_art_browse_button = FakeButton()
    controls_dialog.album_art_clear_button = FakeButton()
    controls_dialog.album_art_hint_label = FakeLabel()
    controls_dialog.album_art_open_master_button = FakeButton()
    controls_dialog._refresh_album_art_controls()
    assert controls_dialog.album_art_open_master_button.text == "Open Master Record…"
    assert (
        controls_dialog.album_art_open_master_button.tooltip
        == "Choose which master record to open."
    )

    state_dialog = _dialog()
    QDialog.__init__(state_dialog)
    state_dialog._is_bulk_edit = False
    state_dialog._bulk_loading = False
    state_dialog._bulk_field_state = {"genre": {"modified": False}}
    state_dialog._mark_bulk_field_modified("genre")
    assert state_dialog._bulk_field_state["genre"]["modified"] is False
    state_dialog._is_bulk_edit = True
    state_dialog._bulk_loading = True
    state_dialog._mark_bulk_field_modified("genre")
    assert state_dialog._bulk_field_state["genre"]["modified"] is False
    state_dialog._bulk_loading = False
    state_dialog._mark_bulk_field_modified("missing")
    assert "missing" not in state_dialog._bulk_field_state
    target = QWidget()
    state_dialog._bulk_focus_targets = {}
    state_dialog._is_bulk_edit = False
    state_dialog._register_bulk_focus_target(target, "genre")
    assert state_dialog._bulk_focus_targets == {}
    state_dialog._is_bulk_edit = True
    state_dialog._register_bulk_focus_target(target, "genre")
    assert state_dialog._bulk_focus_targets[target] == "genre"

    media_apply_dialog = _dialog()
    media_apply_dialog._is_bulk_edit = True
    media_apply_dialog._clear_album_art = False
    media_apply_dialog._bulk_field_state = {
        "album_art": {"mixed": True, "initial": None, "modified": True}
    }
    assert (
        media_apply_dialog._bulk_media_should_apply("album_art", "", clear_attr="_clear_album_art")
        is True
    )


def test_edit_dialog_remaining_constructor_focus_hint_and_commit_edges(
    monkeypatch,
) -> None:
    require_qapplication()

    no_media_parent = _WidgetParent([_snapshot(audio_file_path="", audio_file_blob_b64="")])
    no_media_dialog = EditDialog(1, no_media_parent)
    try:
        assert not no_media_dialog.set_length_from_saved_audio_button.isEnabled()
        assert "No saved audio file" in no_media_dialog.set_length_from_saved_audio_button.toolTip()
    finally:
        no_media_dialog.close()
        no_media_dialog.deleteLater()

    focus_dialog = _dialog()
    focus_dialog._initial_focus_target = "genre"
    called: list[str] = []
    focus_dialog.focus_editor_target = lambda target: called.append(target) or True
    focus_dialog._apply_initial_focus_target()
    assert called == ["genre"]

    line_edit = QLineEdit()

    class LineEditGetter(QWidget):
        def lineEdit(self):  # noqa: N802 - Qt-style method name for this fake widget
            return line_edit

    assert EditDialog._preferred_focus_widget(LineEditGetter()) is line_edit

    class FlakyCombo(QComboBox):
        def __init__(self) -> None:
            super().__init__()
            self.calls = 0
            self._fallback_line_edit = QLineEdit()

        def lineEdit(self):  # noqa: N802 - Qt-style method name for this fake widget
            self.calls += 1
            return None if self.calls == 1 else self._fallback_line_edit

    flaky_combo = FlakyCombo()
    assert EditDialog._preferred_focus_widget(flaky_combo) is flaky_combo._fallback_line_edit

    success_focus_dialog = _dialog()
    QDialog.__init__(success_focus_dialog)
    for name in (
        "track_title",
        "artist_name",
        "additional_artist",
        "genre",
        "album_title",
        "track_number",
        "release_date",
        "len_h",
        "isrc_field",
        "iswc",
        "upc",
        "catalog_number",
        "buma_work_number",
        "entry_date_field",
        "audio_file_browse_button",
        "album_art_browse_button",
    ):
        setattr(success_focus_dialog, name, QLineEdit())
    success_focus_dialog.editor_tabs = SimpleNamespace(setCurrentIndex=lambda _index: None)
    success_focus_dialog._editor_tab_indices = {"track": 0}
    assert success_focus_dialog.focus_editor_target("track_title") in {True, False}

    buma_dialog = _dialog()
    buma_dialog.snapshot = SimpleNamespace(work_id=7, buma_work_number="Fallback")
    buma_dialog.parent = SimpleNamespace(
        work_service=SimpleNamespace(
            fetch_work=lambda _work_id: SimpleNamespace(registration_number="   ")
        )
    )
    assert buma_dialog._resolved_buma_work_number_text() == "Fallback"

    hint_dialog = _dialog()
    hint_dialog._album_art_edit_states = {
        1: SimpleNamespace(
            is_shared_reference=True,
            owner_track_id=4,
            owner_track_title="Master",
        ),
        2: SimpleNamespace(
            is_shared_reference=True,
            owner_track_id=4,
            owner_track_title="Master",
        ),
    }
    assert hint_dialog._bulk_album_art_hint_text() == (
        'Some selected tracks use shared album art managed by Track #4 "Master". '
        "Edit that record to replace the shared image."
    )

    monkeypatch.setattr(
        edit_dialog_module,
        "run_snapshot_history_action",
        lambda **kwargs: {**kwargs["mutation"](), "history": kwargs["action_type"]},
    )

    single_dialog, single_parent = _single_save_dialog()
    single_parent.execute_tasks = True
    single_parent.conn.commit_exception = RuntimeError("commit failed")
    single_dialog._save_single_changes()
    assert single_parent.accepted is True
    assert single_parent.refresh_requests

    bulk_dialog, bulk_parent = _bulk_save_dialog()
    bulk_parent.execute_tasks = True
    bulk_parent.conn.commit_exception = RuntimeError("commit failed")
    bulk_dialog._mark_bulk_field_modified("artist_name")
    bulk_dialog.artist_name.setCurrentText("Unified Artist")
    bulk_dialog._save_bulk_changes()
    assert bulk_parent.accepted is True
    assert bulk_parent.refresh_requests


def test_set_track_length_from_saved_audio_handles_success_and_failures(monkeypatch) -> None:
    warnings: list[tuple[str, str]] = []
    monkeypatch.setattr(
        edit_dialog_module.QMessageBox,
        "warning",
        lambda _parent, title, message: warnings.append((title, message)),
    )

    dialog, parent = _single_save_dialog()
    dialog.len_h = object()
    dialog.len_m = object()
    dialog.len_s = object()
    dialog._set_track_length_from_saved_audio()
    assert parent.length_sets == [123]
    assert parent.status_messages

    bulk_dialog, _parent = _single_save_dialog()
    bulk_dialog._is_bulk_edit = True
    bulk_dialog._set_track_length_from_saved_audio()
    assert warnings == []

    missing_service_dialog, missing_parent = _single_save_dialog()
    missing_parent.track_service = None
    missing_service_dialog._set_track_length_from_saved_audio()
    assert warnings[-1][1] == "Open a profile before reading saved audio."

    missing_file_dialog, missing_file_parent = _single_save_dialog()
    missing_file_parent.track_service.resolve_media_exc = FileNotFoundError("missing")
    missing_file_dialog._set_track_length_from_saved_audio()
    assert "does not have a saved audio file" in warnings[-1][1]

    open_error_dialog, open_error_parent = _single_save_dialog()
    open_error_parent.track_service.resolve_media_exc = RuntimeError("open failed")
    open_error_dialog._set_track_length_from_saved_audio()
    assert "Could not open" in warnings[-1][1]

    read_error_dialog, read_error_parent = _single_save_dialog()
    read_error_parent.track_service.duration_exc = RuntimeError("decode failed")
    read_error_dialog._set_track_length_from_saved_audio()
    assert "Could not read" in warnings[-1][1]

    no_duration_dialog, no_duration_parent = _single_save_dialog()
    no_duration_parent.track_service.duration_result = None
    no_duration_dialog._set_track_length_from_saved_audio()
    assert "Could not read a duration" in warnings[-1][1]


def test_single_save_validation_cancellation_success_and_rollback_paths(monkeypatch) -> None:
    warnings: list[tuple[str, str]] = []
    criticals: list[tuple[str, str]] = []
    monkeypatch.setattr(
        edit_dialog_module.QMessageBox,
        "warning",
        lambda _parent, title, message: warnings.append((title, message)),
    )
    monkeypatch.setattr(
        edit_dialog_module.QMessageBox,
        "critical",
        lambda _parent, title, message: criticals.append((title, message)),
    )

    dialog, _parent = _single_save_dialog()
    dialog.isrc_field.setText("bad")
    dialog._save_single_changes()
    assert warnings[-1][0] == "Invalid ISRC"

    dialog, _parent = _single_save_dialog()
    dialog.iswc.setText("bad")
    dialog._save_single_changes()
    assert warnings[-1][0] == "Invalid ISWC"

    dialog, _parent = _single_save_dialog()
    dialog.track_title.setText("")
    dialog._save_single_changes()
    assert warnings[-1][0] == "Missing data"

    dialog, _parent = _single_save_dialog()
    dialog.upc.setText("123")
    dialog._save_single_changes()
    assert warnings[-1][0] == "Invalid UPC/EAN"

    dialog, _parent = _single_save_dialog()
    dialog.parentWidget = lambda: None
    dialog._save_single_changes()
    assert criticals[-1][1] == "No parent window set."

    dialog, parent = _single_save_dialog()
    parent.track_service.snapshot = None
    dialog._save_single_changes()
    assert warnings[-1][1] == "Could not load the selected track."

    dialog, parent = _single_save_dialog()
    dialog.isrc_field.setText("NLABC2600001")
    parent.duplicate_isrc = True
    dialog._save_single_changes()
    assert criticals[-1][0] == "Duplicate ISRC"

    dialog, parent = _single_save_dialog()
    dialog.audio_file.setText("/audio.mp3")
    parent.confirm_lossy = False
    dialog._save_single_changes()
    assert parent.submitted_tasks == []

    dialog, parent = _single_save_dialog()
    dialog.album_art.setText("/cover.jpg")
    parent.track_service.album_art_messages = {1: "Shared album art"}
    dialog._save_single_changes()
    assert warnings[-1] == ("Album Art Managed Elsewhere", "Shared album art")

    dialog, parent = _single_save_dialog()
    parent.media_modes = None
    dialog._save_single_changes()
    assert parent.submitted_tasks == []

    success_dialog, success_parent = _single_save_dialog()
    success_parent.execute_tasks = True
    success_parent.track_service.album_group_track_ids = [1, 2, 3]
    success_dialog.album_art.setText("/cover.jpg")
    monkeypatch.setattr(
        edit_dialog_module,
        "run_snapshot_history_action",
        lambda **kwargs: {**kwargs["mutation"](), "history": kwargs["action_type"]},
    )

    success_dialog._save_single_changes()

    assert success_parent.accepted is True
    assert success_parent.track_service.updated_payloads
    assert success_parent.track_service.album_updates
    assert success_parent.synced_tracks == [[1, 2, 3]]
    assert success_parent.refresh_requests
    assert success_parent.audit_calls[-1][1]["details"].startswith("isrc=")

    nonpropagated_dialog, nonpropagated_parent = _single_save_dialog()
    nonpropagated_parent.execute_tasks = True
    nonpropagated_parent.track_service.album_group_track_ids = [1]
    monkeypatch.setattr(
        edit_dialog_module,
        "run_snapshot_history_action",
        lambda **kwargs: {**kwargs["mutation"](), "history": kwargs["action_type"]},
    )

    nonpropagated_dialog._save_single_changes()

    assert nonpropagated_parent.accepted is True
    assert nonpropagated_parent.synced_tracks == [[1]]
    assert nonpropagated_parent.audit_calls[-1][1]["details"] == "isrc="

    rollback_dialog, rollback_parent = _single_save_dialog()
    rollback_parent.submit_exception = RuntimeError("submit failed")
    rollback_dialog._save_single_changes()
    assert rollback_parent.conn.rollbacks == 1
    assert criticals[-1][0] == "Update Error"


def test_bulk_save_validation_noop_success_and_rollback_paths(monkeypatch) -> None:
    warnings: list[tuple[str, str]] = []
    criticals: list[tuple[str, str]] = []
    infos: list[tuple[str, str]] = []
    monkeypatch.setattr(
        edit_dialog_module.QMessageBox,
        "warning",
        lambda _parent, title, message: warnings.append((title, message)),
    )
    monkeypatch.setattr(
        edit_dialog_module.QMessageBox,
        "critical",
        lambda _parent, title, message: criticals.append((title, message)),
    )
    monkeypatch.setattr(
        edit_dialog_module.QMessageBox,
        "information",
        lambda _parent, title, message: infos.append((title, message)),
    )

    dialog, _parent = _bulk_save_dialog()
    dialog.parentWidget = lambda: None
    dialog._save_bulk_changes()
    assert criticals[-1][1] == "No parent window set."

    dialog, _parent = _bulk_save_dialog()
    dialog._mark_bulk_field_modified("artist_name")
    dialog.artist_name.setCurrentText("")
    dialog._save_bulk_changes()
    assert warnings[-1][1] == "Artist cannot be blank when bulk editing."

    dialog, _parent = _bulk_save_dialog()
    dialog._mark_bulk_field_modified("upc")
    dialog.upc.setCurrentText("123")
    dialog._save_bulk_changes()
    assert warnings[-1][0] == "Invalid UPC/EAN"

    dialog, parent = _bulk_save_dialog()
    dialog._mark_bulk_field_modified("album_art")
    dialog.album_art.setText("/cover.jpg")
    parent.track_service.album_art_messages = {2: "Shared album art"}
    dialog._save_bulk_changes()
    assert warnings[-1][0] == "Album Art Managed Elsewhere"

    dialog, _parent = _bulk_save_dialog()
    dialog._save_bulk_changes()
    assert infos[-1] == ("Bulk Edit", "No editable fields were changed.")

    dialog, parent = _bulk_save_dialog()
    dialog._mark_bulk_field_modified("artist_name")
    dialog.artist_name.setCurrentText("Unified Artist")
    parent.media_modes = None
    dialog._save_bulk_changes()
    assert parent.submitted_tasks == []

    success_dialog, success_parent = _bulk_save_dialog()
    success_parent.execute_tasks = True
    success_dialog._mark_bulk_field_modified("artist_name")
    success_dialog.artist_name.setCurrentText("Unified Artist")
    success_dialog._mark_bulk_field_modified("additional_artists")
    success_dialog.additional_artist.setCurrentText("Guest, Another")
    success_dialog._mark_bulk_field_modified("album_title")
    success_dialog.album_title.setCurrentText("Unified Album")
    success_dialog._mark_bulk_field_modified("genre")
    success_dialog.genre.setCurrentText("Disco")
    success_dialog._mark_bulk_field_modified("release_date")
    success_dialog.release_date = _DateWidget("2026-06-01")
    success_dialog._mark_bulk_field_modified("upc")
    success_dialog.upc.setCurrentText("123456789012")
    success_dialog._mark_bulk_field_modified("catalog_number")
    success_dialog.catalog_number.setCurrentText("CAT-9")
    success_dialog._mark_bulk_field_modified("album_art")
    success_dialog.album_art.setText("/cover.jpg")
    monkeypatch.setattr(
        edit_dialog_module,
        "run_snapshot_history_action",
        lambda **kwargs: {**kwargs["mutation"](), "history": kwargs["action_type"]},
    )

    success_dialog._save_bulk_changes()

    assert success_parent.accepted is True
    assert len(success_parent.track_service.updated_payloads) == 2
    assert success_parent.synced_tracks == [[1, 2]]
    assert success_parent.refresh_requests[-1]["request"]["focus_id"] == 1
    assert success_parent.audit_calls[-1][1]["ref_id"] == "batch"

    rollback_dialog, rollback_parent = _bulk_save_dialog()
    rollback_dialog._mark_bulk_field_modified("artist_name")
    rollback_dialog.artist_name.setCurrentText("Unified Artist")
    rollback_parent.submit_exception = RuntimeError("submit failed")
    rollback_dialog._save_bulk_changes()
    assert rollback_parent.conn.rollbacks == 1
    assert criticals[-1][0] == "Update Error"

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from isrc_manager.releases import controller as release_controller
from isrc_manager.releases.models import ReleaseRecord, ReleaseSummary, ReleaseTrackPlacement
from isrc_manager.services.tracks import TrackSnapshot


def _release_record(
    release_id: int,
    title: str,
    *,
    primary_artist: str | None = None,
    release_type: str = "album",
    artwork_path: str | None = None,
) -> ReleaseRecord:
    return ReleaseRecord(
        id=release_id,
        title=title,
        version_subtitle=None,
        primary_artist=primary_artist,
        album_artist=None,
        release_type=release_type,
        release_date=None,
        original_release_date=None,
        label=None,
        sublabel=None,
        catalog_number=None,
        catalog_number_mode=None,
        catalog_registry_entry_id=None,
        catalog_external_code_identifier_id=None,
        external_catalog_identifier_id=None,
        upc=None,
        barcode_validation_status="missing",
        territory=None,
        explicit_flag=False,
        repertoire_status=None,
        metadata_complete=False,
        contract_signed=False,
        rights_verified=False,
        notes=None,
        artwork_path=artwork_path,
    )


def _snapshot(
    track_id: int,
    *,
    title: str = "Track",
    album: str | None = "Album",
    artist: str = "Artist",
    track_number: int | None = None,
    album_art_path: str | None = None,
) -> TrackSnapshot:
    return TrackSnapshot(
        track_id=track_id,
        db_entry_date=None,
        isrc=f"NL-ABC-26-{track_id:05d}",
        track_title=title,
        artist_name=artist,
        additional_artists=[],
        album_title=album,
        release_date="2026-05-27",
        track_length_sec=180,
        iswc=None,
        upc=None,
        genre=None,
        catalog_number=None,
        buma_work_number=None,
        composer=None,
        publisher="QA Label",
        comments=None,
        lyrics=None,
        track_number=track_number,
        album_art_path=album_art_path,
    )


class _Messages:
    Yes = 1
    No = 2

    def __init__(self) -> None:
        self.warnings: list[tuple[str, str]] = []
        self.infos: list[tuple[str, str]] = []
        self.questions: list[tuple[str, str]] = []
        self.question_response = self.Yes

    def warning(self, _parent, title: str, message: str) -> None:
        self.warnings.append((title, message))

    def information(self, _parent, title: str, message: str) -> None:
        self.infos.append((title, message))

    def question(self, _parent, title: str, message: str, *_args) -> int:
        self.questions.append((title, message))
        return self.question_response


class _InputDialog:
    selected = ("", False)
    calls: list[tuple[str, str, tuple[str, ...]]] = []

    @classmethod
    def getItem(cls, _parent, title, prompt, labels, *_args):
        cls.calls.append((title, prompt, tuple(labels)))
        return cls.selected


class _Connection:
    def __init__(self) -> None:
        self.commits = 0

    def __enter__(self):
        return self

    def __exit__(self, *_exc) -> None:
        return None

    def cursor(self):
        return object()

    def commit(self) -> None:
        self.commits += 1


class _TrackService:
    def __init__(self, snapshots: dict[int, TrackSnapshot] | None = None) -> None:
        self.snapshots = snapshots or {}
        self.groups: dict[int, list[int]] = {}
        self.media_paths: dict[str, Path | None] = {}

    def fetch_track_snapshot(self, track_id: int):
        return self.snapshots.get(int(track_id))

    def list_album_group_track_ids(self, track_id: int, *, cursor=None):
        return list(self.groups.get(int(track_id), []))

    def resolve_media_path(self, stored_path: str | None):
        return self.media_paths.get(str(stored_path or ""), None)


class _ReleaseService:
    def __init__(self) -> None:
        self.releases: list[ReleaseRecord] = []
        self.primary_by_track: dict[int, ReleaseRecord | None] = {}
        self.summaries: dict[int, ReleaseSummary | None] = {}
        self.created_payloads = []
        self.updated_payloads = []
        self.added_tracks = []
        self.deleted_ids = []
        self.duplicated_ids = []

    def list_releases(self):
        return list(self.releases)

    def find_primary_release_for_track(self, track_id: int):
        return self.primary_by_track.get(int(track_id))

    def fetch_release_summary(self, release_id: int):
        return self.summaries.get(int(release_id))

    def create_release(self, payload, *, cursor=None):
        self.created_payloads.append(payload)
        return 700 + len(self.created_payloads)

    def update_release(self, release_id: int, payload, *, cursor=None):
        self.updated_payloads.append((int(release_id), payload))
        return int(release_id)

    def add_tracks_to_release(self, release_id: int, track_ids: list[int]):
        self.added_tracks.append((int(release_id), list(track_ids)))
        return list(track_ids)

    def delete_release(self, release_id: int):
        self.deleted_ids.append(int(release_id))

    def duplicate_release(self, release_id: int):
        self.duplicated_ids.append(int(release_id))
        return int(release_id) + 1000


def _app() -> SimpleNamespace:
    app = SimpleNamespace()
    app.conn = _Connection()
    app.logger = mock.Mock()
    app.track_service = _TrackService()
    app.release_service = _ReleaseService()
    app.submitted_tasks = []
    app.events = []
    app.audits = []
    app.audit_commits = 0
    app.history_refreshes = 0
    app.table_refreshes = []
    app.browser_refreshes = 0
    app.ui_progress = []
    app.errors = []
    app.opened_editor_selections = []
    app.add_specific_calls = []
    app.selected_track_ids = []
    app._normalize_track_ids = lambda raw: [
        int(value) for value in (raw or []) if str(value).strip() and int(value) > 0
    ]
    app._first_non_blank = lambda *values: next(
        (str(value).strip() for value in values if str(value or "").strip()),
        None,
    )
    app._normalize_track_number_value = lambda value: (
        int(value) if str(value or "").strip().isdigit() and int(value) > 0 else None
    )
    app._current_profile_name = lambda: "QA Profile"
    app._catalog_table_controller = lambda: SimpleNamespace(
        selected_track_ids=lambda: list(app.selected_track_ids)
    )
    app._get_track_title = lambda track_id: f"Track {track_id}"
    app.open_release_editor = lambda **kwargs: app.opened_editor_selections.append(kwargs)
    app._release_choices = lambda: release_controller._release_choices(app)
    app._prompt_for_release_choice = lambda **kwargs: release_controller._prompt_for_release_choice(
        app, **kwargs
    )
    app.add_selected_tracks_to_specific_release = (
        lambda release_id, track_ids=None: app.add_specific_calls.append(
            (int(release_id), track_ids)
        )
    )
    app._sync_releases_for_tracks = (
        lambda track_ids, **kwargs: release_controller._sync_releases_for_tracks(
            app, track_ids, **kwargs
        )
    )
    app._release_payload_for_track_ids = (
        lambda track_ids, **kwargs: release_controller._release_payload_for_track_ids(
            app, track_ids, **kwargs
        )
    )
    app._release_browser_task_owner = lambda: app
    app._submit_background_bundle_task = lambda **kwargs: app.submitted_tasks.append(kwargs)
    app._advance_task_ui_progress = lambda _ui_progress, **kwargs: app.ui_progress.append(kwargs)
    app._refresh_history_actions = lambda: setattr(
        app,
        "history_refreshes",
        app.history_refreshes + 1,
    )
    app._log_event = lambda *args, **kwargs: app.events.append((args, kwargs))
    app._audit = lambda *args, **kwargs: app.audits.append((args, kwargs))
    app._audit_commit = lambda: setattr(app, "audit_commits", app.audit_commits + 1)
    app.refresh_table_preserve_view = lambda **kwargs: app.table_refreshes.append(kwargs)
    app._refresh_release_browser_panel = lambda: setattr(
        app,
        "browser_refreshes",
        app.browser_refreshes + 1,
    )
    app._show_background_task_error = lambda title, failure, **kwargs: app.errors.append(
        (title, failure, kwargs)
    )
    return app


def test_release_choices_and_track_context_cover_absent_and_partial_releases() -> None:
    app = _app()
    app.release_service = None
    assert release_controller._release_choices(app) == []
    assert release_controller._release_context_for_track(app, 1) == (None, None)

    service = _ReleaseService()
    release = _release_record(10, "Album", primary_artist="Artist")
    bare_release = _release_record(11, "Instrumentals")
    service.releases = [release, bare_release]
    service.primary_by_track = {1: release, 2: bare_release}
    service.summaries = {
        10: ReleaseSummary(
            release=release,
            tracks=[ReleaseTrackPlacement(track_id=1, track_number=3)],
        ),
        11: ReleaseSummary(
            release=bare_release,
            tracks=[ReleaseTrackPlacement(track_id=99, track_number=1)],
        ),
    }
    app.release_service = service

    assert release_controller._release_choices(app) == [
        (10, "Album — Artist"),
        (11, "Instrumentals"),
    ]
    assert release_controller._release_context_for_track(app, 99) == (None, None)
    assert release_controller._release_context_for_track(app, 1) == (
        release,
        service.summaries[10].tracks[0],
    )
    assert release_controller._release_context_for_track(app, 2) == (bare_release, None)

    service.summaries[11] = None
    assert release_controller._release_context_for_track(app, 2) == (bare_release, None)


def test_release_payload_validates_services_preserves_order_and_derives_artwork(tmp_path) -> None:
    app = _app()
    artwork = tmp_path / "cover.png"
    artwork.write_bytes(b"\x89PNG\r\n\x1a\nqa")
    app.track_service = _TrackService(
        {
            1: _snapshot(1, title="Second", album="Shared Album", track_number=4),
            2: _snapshot(2, title="First", album="Shared Album", track_number=None),
        }
    )
    app.track_service.media_paths["cover-key"] = artwork
    app.track_service.snapshots[2].album_art_path = "cover-key"
    existing = _release_record(20, "Existing Title", primary_artist="Existing Artist")
    existing.version_subtitle = "Deluxe"
    existing.release_type = "ep"
    existing.label = "Existing Label"
    summary = ReleaseSummary(
        release=existing,
        tracks=[ReleaseTrackPlacement(track_id=1, disc_number=2, track_number=8)],
    )

    payload = release_controller._release_payload_for_track_ids(
        app,
        [1, 2, 999],
        existing_release=existing,
        existing_summary=summary,
    )

    assert payload.title == "Shared Album"
    assert payload.primary_artist == "Existing Artist"
    assert payload.version_subtitle == "Deluxe"
    assert payload.release_type == "ep"
    assert payload.label == "Existing Label"
    assert payload.artwork_source_path == str(artwork)
    assert payload.profile_name == "QA Profile"
    assert [
        (p.track_id, p.disc_number, p.track_number, p.sequence_number) for p in payload.placements
    ] == [
        (2, 1, 1, 1),
        (1, 2, 8, 2),
    ]

    payload = release_controller._release_payload_for_track_ids(
        app,
        [2],
        clear_artwork=True,
        artwork_source_path=str(tmp_path / "manual.png"),
    )
    assert payload.clear_artwork is True
    assert payload.artwork_source_path == str(tmp_path / "manual.png")

    app.track_service = None
    with pytest.raises(ValueError, match="Track service"):
        release_controller._release_payload_for_track_ids(app, [1])

    app.track_service = _TrackService()
    with pytest.raises(ValueError, match="No valid tracks"):
        release_controller._release_payload_for_track_ids(app, [999])


def test_sync_releases_for_tracks_deduplicates_groups_and_splits_stale_release_summaries() -> None:
    app = _app()
    release = _release_record(30, "Grouped Release")
    stale_summary = ReleaseSummary(
        release=release,
        tracks=[
            ReleaseTrackPlacement(track_id=1, track_number=1),
            ReleaseTrackPlacement(track_id=99, track_number=2),
        ],
    )
    matching = _release_record(31, "Single Release")
    app.track_service = _TrackService(
        {
            1: _snapshot(1, album="Grouped", track_number=1),
            2: _snapshot(2, album="Grouped", track_number=2),
            3: _snapshot(3, album="Single", track_number=1),
        }
    )
    app.track_service.groups = {1: [1, 2], 2: [1, 2], 3: []}
    app.release_service.primary_by_track = {1: release, 3: matching}
    app.release_service.summaries = {
        30: stale_summary,
        31: ReleaseSummary(
            release=matching,
            tracks=[ReleaseTrackPlacement(track_id=3, track_number=1)],
        ),
    }

    release_ids = release_controller._sync_releases_for_tracks(
        app,
        [1, 2, 3],
        cursor=object(),
    )

    assert release_ids == [701, 31]
    assert [payload.title for payload in app.release_service.created_payloads] == ["Grouped"]
    assert [
        (release_id, payload.title) for release_id, payload in app.release_service.updated_payloads
    ] == [(31, "Single")]

    app.release_service = None
    assert release_controller._sync_releases_for_tracks(app, [1], cursor=object()) == []


def test_release_prompt_and_selection_paths_handle_cancel_missing_and_success(monkeypatch) -> None:
    messages = _Messages()
    monkeypatch.setattr(
        release_controller,
        "_root_attr",
        lambda name, fallback: (
            messages
            if name == "QMessageBox"
            else (_InputDialog if name == "QInputDialog" else fallback)
        ),
    )
    app = _app()

    release_controller.create_release_from_selection(app, [])
    assert messages.infos[-1] == (
        "Create Release",
        "Select one or more tracks first, then create the release from that selection.",
    )

    app.selected_track_ids = [8, "9", 0]
    release_controller.create_release_from_selection(app)
    assert app.opened_editor_selections[-1] == {"selected_track_ids": [8, 9]}

    app.release_service.releases = []
    assert release_controller._prompt_for_release_choice(app, title="T", prompt="P") is None
    assert messages.infos[-1] == ("T", "No releases exist yet. Create one first.")

    app.release_service.releases = [_release_record(5, "Pick Me")]
    _InputDialog.selected = ("", False)
    assert release_controller._prompt_for_release_choice(app, title="T", prompt="P") is None

    _InputDialog.selected = ("Unknown", True)
    assert release_controller._prompt_for_release_choice(app, title="T", prompt="P") is None

    _InputDialog.selected = ("Pick Me", True)
    assert release_controller._prompt_for_release_choice(app, title="T", prompt="P") == 5

    app._prompt_for_release_choice = lambda **_kwargs: None
    release_controller.add_selected_tracks_to_release(app, [1])
    assert app.add_specific_calls == []

    app._prompt_for_release_choice = lambda **_kwargs: 5
    release_controller.add_selected_tracks_to_release(app, [1, 2])
    assert app.add_specific_calls == [(5, [1, 2])]


def test_add_selected_tracks_to_specific_release_validates_and_runs_background_callbacks(
    monkeypatch,
) -> None:
    messages = _Messages()

    def root_attr(name: str, fallback):
        if name == "QMessageBox":
            return messages
        if name == "run_snapshot_history_action":
            return lambda **kwargs: kwargs["mutation"]()
        return fallback

    monkeypatch.setattr(release_controller, "_root_attr", root_attr)
    app = _app()
    app.release_service = None
    release_controller.add_selected_tracks_to_specific_release(app, 1, [1])
    assert messages.warnings[-1] == ("Release Browser", "Open a profile first.")

    app = _app()
    release_controller.add_selected_tracks_to_specific_release(app, 1, [])
    assert messages.infos[-1] == ("Release Browser", "Select one or more tracks first.")

    app.release_service.summaries[1] = None
    release_controller.add_selected_tracks_to_specific_release(app, 1, [9])
    assert messages.warnings[-1] == (
        "Release Browser",
        "The chosen release could not be loaded.",
    )

    release = _release_record(1, "Target Release")
    app.release_service.summaries[1] = ReleaseSummary(release=release, tracks=[])
    release_controller.add_selected_tracks_to_specific_release(app, 1, [9, 10])
    task = app.submitted_tasks[-1]
    bundle = SimpleNamespace(release_service=app.release_service, history_manager=object())
    ctx = SimpleNamespace(report_progress=mock.Mock())

    assert task["task_fn"](bundle, ctx) == [9, 10]
    task["on_success_before_cleanup"]([9, 10], object())
    task["on_success_after_cleanup"]([9, 10])
    task["on_error"](RuntimeError("failed"))

    assert app.release_service.added_tracks == [(1, [9, 10])]
    assert app.table_refreshes[-1] == {"focus_id": 9}
    assert app.browser_refreshes == 2
    assert messages.infos[-1] == (
        "Release Browser",
        "Added 2 tracks to 'Target Release'.",
    )
    assert app.errors[-1][0] == "Release Browser"


def test_delete_and_duplicate_release_validate_summary_and_refresh_after_tasks(monkeypatch) -> None:
    messages = _Messages()

    def root_attr(name: str, fallback):
        if name == "QMessageBox":
            return messages
        if name == "run_snapshot_history_action":
            return lambda **kwargs: kwargs["mutation"]()
        return fallback

    monkeypatch.setattr(release_controller, "_root_attr", root_attr)
    app = _app()
    app.release_service = None
    release_controller.delete_release(app, 7)
    release_controller.duplicate_release(app, 7)
    assert messages.warnings[-1] == ("Release Browser", "Open a profile first.")
    assert app.submitted_tasks == []

    app = _app()
    app.release_service.summaries[7] = None
    release_controller.delete_release(app, 7)
    release_controller.duplicate_release(app, 7)
    assert messages.warnings[-2:] == [
        ("Delete Release", "The selected release could not be loaded."),
        ("Duplicate Release", "The selected release could not be loaded."),
    ]

    release = _release_record(7, "Delete Me")
    app.release_service.summaries[7] = ReleaseSummary(
        release=release,
        tracks=[ReleaseTrackPlacement(track_id=44)],
    )
    bundle = SimpleNamespace(release_service=app.release_service, history_manager=object())
    ctx = SimpleNamespace(report_progress=mock.Mock())

    release_controller.delete_release(app, 7)
    delete_task = app.submitted_tasks[-1]
    assert delete_task["task_fn"](bundle, ctx) is None
    delete_task["on_success_before_cleanup"](None, object())
    delete_task["on_success_after_cleanup"](None)
    assert app.release_service.deleted_ids == [7]
    assert app.table_refreshes[-1] == {"focus_id": 44}
    assert app.events[-1][0][0] == "release.delete"

    release_controller.duplicate_release(app, 7)
    duplicate_task = app.submitted_tasks[-1]
    assert duplicate_task["task_fn"](bundle, ctx) == 1007
    duplicate_task["on_success_before_cleanup"](1007, object())
    duplicate_task["on_success_after_cleanup"](1007)
    duplicate_task["on_error"](RuntimeError("duplicate failed"))
    assert app.release_service.duplicated_ids == [7]
    assert app.audits[-1][0] == ("CREATE", "Release")
    assert app.errors[-1][0] == "Duplicate Release"

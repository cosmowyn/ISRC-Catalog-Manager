from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from isrc_manager.tags import catalog, mapping
from isrc_manager.tags.models import ArtworkPayload, AudioTagData


@dataclass
class _Snapshot:
    track_title: str = "Catalog Song"
    artist_name: str = "Catalog Artist"
    album_title: str = "Catalog Album"
    track_number: int | None = None
    genre: str = ""
    composer: str = ""
    publisher: str = ""
    release_date: str = ""
    isrc: str = ""
    upc: str = ""
    comments: str = ""
    lyrics: str = ""
    album_art_path: str = ""
    album_art_blob_b64: str = ""
    album_art_filename: str = ""
    album_art_size_bytes: int = 0
    album_art_mime_type: str = ""


class _Release:
    def __init__(self, release_id: int, title: str = "Release Album") -> None:
        self.id = release_id
        self.title = title

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "title": self.title,
            "primary_artist": "Release Artist",
            "label": "Release Label",
            "release_date": "2026-05-25",
            "upc": "123456789012",
        }


class _TrackService:
    def __init__(self, snapshot: _Snapshot | None, *, media_failure: bool = False) -> None:
        self.snapshot = snapshot
        self.media_failure = media_failure
        self.media_calls: list[tuple[int, str]] = []

    def fetch_track_snapshot(self, track_id: int):
        assert track_id == 7
        return self.snapshot

    def fetch_media_bytes(self, track_id: int, media_key: str):
        self.media_calls.append((track_id, media_key))
        if self.media_failure:
            raise FileNotFoundError("missing art")
        return b"art", "image/png"


class _ReleaseService:
    def __init__(self) -> None:
        self.primary_release: _Release | None = None
        self.release_ids: list[int] = []
        self.releases: dict[int, _Release] = {}
        self.summaries: dict[int, object | None] = {}

    def find_primary_release_for_track(self, track_id: int):
        assert track_id == 7
        return self.primary_release

    def find_release_ids_for_track(self, track_id: int):
        assert track_id == 7
        return self.release_ids

    def fetch_release(self, release_id: int):
        return self.releases.get(release_id)

    def fetch_release_summary(self, release_id: int):
        return self.summaries.get(release_id)


def _summary(release: _Release, *, track_id: int = 7, track_number: int = 4, disc_number: int = 2):
    return SimpleNamespace(
        release=release,
        tracks=[
            SimpleNamespace(track_id=999, track_number=1, disc_number=1),
            SimpleNamespace(
                track_id=track_id,
                track_number=track_number,
                disc_number=disc_number,
            ),
        ],
    )


def test_catalog_metadata_to_tags_prefers_release_and_placement_values() -> None:
    artwork = ArtworkPayload(data=b"image", mime_type="image/jpeg")

    tag_data = mapping.catalog_metadata_to_tags(
        track_values={
            "track_title": " Track ",
            "artist_name": " Artist ",
            "album_title": "Track Album",
            "track_number": 0,
            "genre": " Rock ",
            "composer": " Composer ",
            "publisher": "Track Publisher",
            "release_date": "2025-01-01",
            "isrc": " ISRC ",
            "upc": "Track UPC",
            "comments": " Notes ",
            "lyrics": " Words ",
        },
        release_values={
            "title": "Release Album",
            "album_artist": "",
            "primary_artist": "Release Artist",
            "label": "Release Label",
            "release_date": "2026-05-25",
            "upc": "Release UPC",
        },
        placement_values={"track_number": 5, "disc_number": 2},
        artwork=artwork,
    )

    assert tag_data == AudioTagData(
        title="Track",
        artist="Artist",
        album="Release Album",
        album_artist="Release Artist",
        track_number=5,
        disc_number=2,
        genre="Rock",
        composer="Composer",
        publisher="Release Label",
        release_date="2026-05-25",
        isrc="ISRC",
        upc="Release UPC",
        comments="Notes",
        lyrics="Words",
        artwork=artwork,
    )


def test_merge_imported_tags_applies_policies_and_reports_conflicts() -> None:
    db_values = {
        "title": "Database Title",
        "artist": "",
        "album": "Database Album",
        "track_number": 1,
        "artwork": ArtworkPayload(data=b"db", mime_type="image/jpeg"),
    }
    file_tags = AudioTagData(
        title="File Title",
        artist="File Artist",
        album="File Album",
        track_number=2,
        artwork=ArtworkPayload(data=b"file", mime_type="image/png"),
    )

    prefer_database = mapping.merge_imported_tags(
        database_values=db_values,
        file_tags=file_tags,
        policy="prefer_database",
    )
    prefer_file = mapping.merge_imported_tags(
        database_values=db_values,
        file_tags=file_tags,
        policy="prefer_file_tags",
    )
    merge_blanks = mapping.merge_imported_tags(
        database_values=db_values,
        file_tags=file_tags,
        policy="",
    )

    assert prefer_database.patch.values["title"] == "Database Title"
    assert prefer_database.patch.values["artist"] == "File Artist"
    assert prefer_database.patch.values["artwork"] == db_values["artwork"]
    assert prefer_file.patch.values["title"] == "File Title"
    assert prefer_file.patch.values["album"] == "File Album"
    assert merge_blanks.patch.values["title"] == "Database Title"
    assert {conflict.field_name for conflict in merge_blanks.conflicts} >= {
        "title",
        "album",
        "track_number",
        "artwork",
    }


def test_effective_artwork_payload_handles_absent_media_and_fetch_failures() -> None:
    no_art_snapshot = _Snapshot()
    assert (
        catalog._effective_artwork_payload_for_track(
            7,
            snapshot=no_art_snapshot,
            track_service=_TrackService(no_art_snapshot),
        )
        is None
    )

    art_snapshot = _Snapshot(album_art_filename="cover.jpg", album_art_mime_type="")
    service = _TrackService(art_snapshot)
    payload = catalog._effective_artwork_payload_for_track(
        7,
        snapshot=art_snapshot,
        track_service=service,
    )
    assert payload == ArtworkPayload(data=b"art", mime_type="image/png")
    assert service.media_calls == [(7, "album_art")]

    failing_service = _TrackService(art_snapshot, media_failure=True)
    assert (
        catalog._effective_artwork_payload_for_track(
            7,
            snapshot=art_snapshot,
            track_service=failing_service,
        )
        is None
    )


def test_select_release_context_primary_and_unambiguous_policies() -> None:
    snapshot = _Snapshot(album_title="Matched Album")
    release_service = _ReleaseService()
    primary = _Release(10, "Primary Album")
    release_service.primary_release = primary
    release_service.summaries[10] = _summary(primary, track_number=8, disc_number=3)

    release_values, placement_values = catalog._select_release_context(
        7,
        track_snapshot=snapshot,
        release_service=release_service,
        release_policy="primary",
    )
    assert release_values["title"] == "Primary Album"
    assert placement_values == {"track_number": 8, "disc_number": 3}

    release_service.release_ids = [20, 21]
    release_service.releases = {
        20: _Release(20, "Other Album"),
        21: _Release(21, "Matched Album"),
    }
    release_service.summaries[21] = _summary(_Release(21, "Matched Album"))
    release_values, placement_values = catalog._select_release_context(
        7,
        track_snapshot=snapshot,
        release_service=release_service,
        release_policy="unambiguous",
    )
    assert release_values["title"] == "Matched Album"
    assert placement_values == {"track_number": 4, "disc_number": 2}

    release_service.release_ids = [30, 31]
    release_service.releases = {
        30: _Release(30, "Matched Album"),
        31: _Release(31, "Matched Album"),
    }
    assert catalog._select_release_context(
        7,
        track_snapshot=snapshot,
        release_service=release_service,
        release_policy="unambiguous",
    ) == (None, None)


def test_build_catalog_tag_data_uses_release_context_and_artwork() -> None:
    snapshot = _Snapshot(album_art_size_bytes=42, track_number=9)
    track_service = _TrackService(snapshot)
    release = _Release(40, "Release Album")
    release_service = _ReleaseService()
    release_service.release_ids = [40]
    release_service.summaries[40] = _summary(release, track_number=3, disc_number=1)

    tag_data = catalog.build_catalog_tag_data(
        7,
        track_service=track_service,
        release_service=release_service,
    )

    assert tag_data.album == "Release Album"
    assert tag_data.track_number == 9
    assert tag_data.disc_number == 1
    assert tag_data.artwork == ArtworkPayload(data=b"art", mime_type="image/png")

    without_art = catalog.build_catalog_export_tag_data(
        7,
        track_service=track_service,
        release_service=release_service,
        include_artwork_bytes=False,
    )
    assert without_art.artwork is None


def test_build_catalog_tag_data_raises_for_missing_track() -> None:
    with pytest.raises(ValueError, match="Track 7 not found"):
        catalog.build_catalog_tag_data(7, track_service=_TrackService(None))


def test_write_catalog_export_tags_reports_success_and_best_effort_failures(
    monkeypatch,
    tmp_path: Path,
) -> None:
    tag_service = SimpleNamespace(write_tags=mock.Mock())
    destination = tmp_path / "song.wav"
    monkeypatch.setattr(
        catalog,
        "build_catalog_export_tag_data",
        mock.Mock(return_value=AudioTagData(title="Song")),
    )

    assert catalog.write_catalog_export_tags(
        destination,
        track_id=7,
        track_service=object(),
        tag_service=tag_service,
    ) == (True, None)
    tag_service.write_tags.assert_called_once()

    monkeypatch.setattr(
        catalog,
        "build_catalog_export_tag_data",
        mock.Mock(side_effect=RuntimeError("missing catalog")),
    )
    ok, message = catalog.write_catalog_export_tags(
        destination,
        track_id=7,
        track_service=object(),
        tag_service=tag_service,
    )
    assert ok is False
    assert message == "catalog metadata was unavailable (missing catalog)"

    monkeypatch.setattr(
        catalog,
        "build_catalog_export_tag_data",
        mock.Mock(return_value=AudioTagData()),
    )
    ok, message = catalog.write_catalog_export_tags(
        destination,
        track_id=7,
        track_service=object(),
        tag_service=tag_service,
    )
    assert ok is False
    assert message == "catalog metadata was empty, so no embedded tags were written"

    tag_service.write_tags = mock.Mock(side_effect=OSError("read-only"))
    monkeypatch.setattr(
        catalog,
        "build_catalog_export_tag_data",
        mock.Mock(return_value=AudioTagData(title="Song")),
    )
    ok, message = catalog.write_catalog_export_tags(
        destination,
        track_id=7,
        track_service=object(),
        tag_service=tag_service,
    )
    assert ok is False
    assert message == "embedded metadata could not be written (read-only)"

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from isrc_manager.file_storage import STORAGE_MODE_DATABASE
from isrc_manager.media import export_controller
from isrc_manager.tags.models import AudioTagData, TaggedAudioExportPlanItem


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

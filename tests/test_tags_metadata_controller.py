from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from isrc_manager.file_storage import STORAGE_MODE_MANAGED_FILE
from isrc_manager.services.tracks import TrackSnapshot
from isrc_manager.tags import ArtworkPayload, DroppedAudioImportItem, metadata_controller


def _snapshot(track_id: int = 1, **overrides) -> TrackSnapshot:
    values = {
        "track_id": track_id,
        "db_entry_date": None,
        "isrc": "NL-ABC-26-00001",
        "track_title": "Original Title",
        "artist_name": "Original Artist",
        "additional_artists": ["Guest"],
        "album_title": "Original Album",
        "release_date": "2026-05-25",
        "track_length_sec": 180,
        "iswc": "T1234567890",
        "upc": "123456789012",
        "genre": "Pop",
        "catalog_number": "CAT-1",
        "buma_work_number": "BUMA-1",
        "composer": "Composer",
        "publisher": "Publisher",
        "comments": "Comment",
        "lyrics": "Lyrics",
        "track_number": 1,
        "audio_file_path": "audio.wav",
    }
    values.update(overrides)
    return TrackSnapshot(**values)


def test_display_values_and_dropped_audio_dialog_rows_cover_payload_variants():
    artwork = ArtworkPayload(data=b"image", mime_type="image/png")
    item = DroppedAudioImportItem(
        source_path="/audio/song.wav",
        source_name="song.wav",
        title="Song",
        artist="Artist",
        album="Album",
        track_number=3,
        release_date="2026-05-25",
        duration_seconds=123,
        isrc="NLABC2600001",
        upc="123456789012",
        genre="Pop",
        composer="Composer",
        publisher="Publisher",
        comments="Comment",
        lyrics="Lyrics",
        artwork=artwork,
        warning="original warning",
    )

    assert metadata_controller._display_tag_value(artwork) == "<Artwork image/png>"
    assert metadata_controller._display_tag_value(None) == ""
    assert metadata_controller._display_tag_value(b"abc") == "<3 bytes>"
    assert metadata_controller._display_tag_value("value") == "value"

    row = metadata_controller._dropped_audio_import_dialog_row(item, warning="override")

    assert row["source_path"] == "/audio/song.wav"
    assert row["source_name"] == "song.wav"
    assert row["artwork"] is artwork
    assert row["warning"] == "override"


def test_build_tag_preview_rows_skips_unchanged_values_but_keeps_artwork_changes():
    artwork = ArtworkPayload(data=b"cover", mime_type="image/jpeg")
    app = SimpleNamespace(
        _get_track_title=mock.Mock(return_value="Fallback Title"),
        _display_tag_value=metadata_controller._display_tag_value,
    )
    file_tags = SimpleNamespace(title="Same", artist="File Artist", artwork=artwork)

    rows = metadata_controller._build_tag_preview_rows(
        app,
        track_id=5,
        source_path="/audio/source.wav",
        database_values={"title": "Same", "artist": "Database Artist", "artwork": artwork},
        file_tags=file_tags,
        chosen_values={"title": "Same", "artist": "File Artist", "artwork": artwork},
    )

    assert [row["field"] for row in rows] == ["Artist", "Artwork"]
    assert rows[0]["track"] == "Fallback Title"
    assert rows[0]["database"] == "Database Artist"
    assert rows[0]["file"] == "File Artist"
    assert rows[1]["chosen"] == "<Artwork image/jpeg>"


def test_prepare_tag_import_preview_collects_success_rows_warnings_and_progress(
    monkeypatch, tmp_path
):
    good_path = tmp_path / "good.wav"
    good_path.write_bytes(b"RIFF")
    missing_path = tmp_path / "missing.wav"
    snapshots = {
        1: _snapshot(1, track_title="Readable", audio_file_path="good.wav"),
        3: _snapshot(3, track_title="Missing", audio_file_path="missing.wav"),
        4: _snapshot(4, track_title="Broken", audio_file_path="broken.wav"),
    }
    resolved_paths = {
        "good.wav": good_path,
        "missing.wav": missing_path,
        "broken.wav": good_path,
    }
    track_service = SimpleNamespace(
        fetch_track_snapshot=mock.Mock(side_effect=lambda track_id: snapshots.get(track_id)),
        resolve_media_path=mock.Mock(side_effect=lambda path: resolved_paths[path]),
    )
    file_tags = SimpleNamespace(title="Imported Title")
    audio_tag_service = SimpleNamespace(
        read_tags=mock.Mock(side_effect=[file_tags, RuntimeError("cannot read tags")])
    )
    progress_calls = []
    app = SimpleNamespace(
        track_service=track_service,
        release_service=object(),
        audio_tag_service=audio_tag_service,
        _normalize_track_ids=mock.Mock(return_value=[1, 2, 3, 4]),
        _catalog_tag_data_for_track=mock.Mock(
            return_value=SimpleNamespace(to_dict=lambda: {"title": "Database Title"})
        ),
        _build_tag_preview_rows=mock.Mock(
            return_value=[{"field": "Title", "chosen": "Imported Title"}]
        ),
    )
    monkeypatch.setattr(
        metadata_controller,
        "merge_imported_tags",
        mock.Mock(
            return_value=SimpleNamespace(patch=SimpleNamespace(values={"title": "Imported Title"}))
        ),
    )

    result = metadata_controller._prepare_tag_import_preview(
        app,
        [1, 2, 3, 4],
        policy="merge_blanks",
        progress_callback=lambda *args: progress_calls.append(args),
    )

    assert result["prepared"] == [
        {
            "track_id": 1,
            "track_title": "Readable",
            "source_path": str(good_path),
            "file_tags": file_tags,
        }
    ]
    assert result["rows"] == [{"field": "Title", "chosen": "Imported Title"}]
    assert "Track 2 could not be loaded." in result["warnings"]
    assert "Missing: no managed audio file is attached." in result["warnings"]
    assert "Broken: cannot read tags" in result["warnings"]
    assert progress_calls[-1] == (4, 4, "Audio tag preview ready.")


def test_apply_tag_patch_updates_track_and_removes_materialized_artwork(tmp_path):
    snapshot = _snapshot()
    captured_payloads = []
    track_service = SimpleNamespace(
        fetch_track_snapshot=mock.Mock(return_value=snapshot),
        update_track=mock.Mock(
            side_effect=lambda payload, **kwargs: captured_payloads.append(payload)
        ),
    )
    artwork = ArtworkPayload(data=b"new-cover", mime_type="image/png")
    app = SimpleNamespace(
        track_service=track_service,
        _effective_artwork_payload_for_track=mock.Mock(return_value=None),
        _normalize_track_number_value=mock.Mock(return_value=7),
    )

    metadata_controller._apply_tag_patch_to_track(
        app,
        1,
        {
            "title": "Imported Title",
            "artist": "Imported Artist",
            "album": "Imported Album",
            "release_date": "2026-06-01",
            "upc": "987654321098",
            "genre": "Rock",
            "track_number": "7",
            "composer": "New Composer",
            "publisher": "New Publisher",
            "comments": "New Comment",
            "lyrics": "New Lyrics",
            "artwork": artwork,
        },
        track_service=track_service,
    )

    payload = captured_payloads[0]
    assert payload.track_id == 1
    assert payload.track_title == "Imported Title"
    assert payload.artist_name == "Imported Artist"
    assert payload.album_title == "Imported Album"
    assert payload.track_number == 7
    assert payload.album_art_source_path
    assert not Path(payload.album_art_source_path).exists()


def test_build_dropped_audio_import_payloads_reports_validation_errors():
    app = SimpleNamespace(
        is_isrc_taken_normalized=mock.Mock(side_effect=lambda value: value == "NL-ABC-26-00003"),
        _normalize_track_number_value=mock.Mock(return_value=1),
        _materialize_artwork_payload=mock.Mock(),
    )
    rows = [
        {"artist": "Artist", "source_path": "/audio/a.wav"},
        {"title": "Song", "source_path": "/audio/b.wav"},
        {"title": "Song", "artist": "Artist"},
        {
            "title": "Song",
            "artist": "Artist",
            "source_path": "/audio/c.wav",
            "isrc": "not-an-isrc",
        },
        {
            "title": "Song",
            "artist": "Artist",
            "source_path": "/audio/d.wav",
            "isrc": "NLABC2600002",
        },
        {
            "title": "Song",
            "artist": "Artist",
            "source_path": "/audio/e.wav",
            "isrc": "NLABC2600002",
        },
        {
            "title": "Song",
            "artist": "Artist",
            "source_path": "/audio/f.wav",
            "isrc": "NLABC2600003",
        },
    ]

    payloads, errors, temp_paths = metadata_controller._build_dropped_audio_import_payloads(
        app,
        rows,
        storage_mode=STORAGE_MODE_MANAGED_FILE,
    )

    assert payloads == []
    assert temp_paths == []
    assert "Row 1: track title is required." in errors
    assert "Row 2: artist is required." in errors
    assert "Row 3: source audio path is missing." in errors
    assert "Row 4: ISRC 'not-an-isrc' is not valid." in errors
    assert "Row 6: ISRC NL-ABC-26-00002 is already queued on row 5." in errors
    assert "Row 7: ISRC NL-ABC-26-00003 already exists." in errors


def test_build_dropped_audio_import_payloads_materializes_artwork_and_normalizes_values():
    artwork = ArtworkPayload(data=b"cover", mime_type="image/jpeg")
    app = SimpleNamespace(
        is_isrc_taken_normalized=mock.Mock(return_value=False),
        _normalize_track_number_value=mock.Mock(return_value=9),
        _materialize_artwork_payload=mock.Mock(return_value="/tmp/cover.jpg"),
    )

    payloads, errors, temp_paths = metadata_controller._build_dropped_audio_import_payloads(
        app,
        [
            {
                "title": "  Song ",
                "artist": " Artist ",
                "album": " Album ",
                "release_date": "2026-05-25",
                "duration_seconds": 234,
                "source_path": " /audio/song.wav ",
                "isrc": "NLABC2600001",
                "upc": " 123456789012 ",
                "genre": " Pop ",
                "track_number": "09",
                "composer": " Composer ",
                "publisher": " Publisher ",
                "comments": " Comment ",
                "lyrics": " Lyrics ",
                "artwork": artwork,
                "import_artwork": True,
            }
        ],
        storage_mode=STORAGE_MODE_MANAGED_FILE,
    )

    assert errors == []
    assert temp_paths == ["/tmp/cover.jpg"]
    payload = payloads[0]
    assert payload.isrc == "NL-ABC-26-00001"
    assert payload.track_title == "Song"
    assert payload.artist_name == "Artist"
    assert payload.album_title == "Album"
    assert payload.release_date == "2026-05-25"
    assert payload.audio_file_source_path == "/audio/song.wav"
    assert payload.audio_file_storage_mode == STORAGE_MODE_MANAGED_FILE
    assert payload.album_art_source_path == "/tmp/cover.jpg"
    assert payload.album_art_storage_mode == STORAGE_MODE_MANAGED_FILE


def test_materialize_artwork_payload_writes_bytes_with_mime_suffix():
    path = Path(
        metadata_controller._materialize_artwork_payload(
            ArtworkPayload(data=b"cover-bytes", mime_type="image/png")
        )
    )
    try:
        assert path.suffix == ".png"
        assert path.read_bytes() == b"cover-bytes"
    finally:
        path.unlink(missing_ok=True)


def test_create_and_import_tag_workflows_report_early_blockers(monkeypatch, tmp_path):
    messages = []

    class FakeMessageBox:
        @classmethod
        def warning(cls, *args):
            messages.append(("warning", args))

        @classmethod
        def information(cls, *args):
            messages.append(("information", args))

    monkeypatch.setattr(metadata_controller, "_message_box", lambda: FakeMessageBox)

    metadata_controller._create_tracks_from_dropped_audio_files(
        SimpleNamespace(audio_tag_service=None, track_service=None, work_service=None),
        [str(tmp_path / "song.wav")],
    )
    assert messages[-1][0] == "warning"

    app = SimpleNamespace(
        audio_tag_service=object(),
        track_service=object(),
        work_service=object(),
        _is_supported_media_attach_path=mock.Mock(return_value=False),
    )
    missing_file = tmp_path / "missing.wav"
    metadata_controller._create_tracks_from_dropped_audio_files(app, [str(missing_file)])
    assert messages[-1][0] == "information"

    metadata_controller.import_tags_from_audio(
        SimpleNamespace(audio_tag_service=None, track_service=None)
    )
    assert messages[-1][0] == "warning"

    app = SimpleNamespace(
        audio_tag_service=object(),
        track_service=object(),
        _normalize_track_ids=mock.Mock(return_value=[]),
        _catalog_table_controller=mock.Mock(),
    )
    metadata_controller.import_tags_from_audio(app, [])
    assert messages[-1][0] == "information"

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from isrc_manager.media import preview_dialogs as preview


def _preload_task(
    *,
    db_path: str,
    cancel_event: threading.Event | None = None,
    source_spec: dict[str, object] | None = None,
    build_preview_state: bool = False,
) -> preview._AudioPreviewPreloadTask:
    return preview._AudioPreviewPreloadTask(
        generation=7,
        track_id=3,
        source_spec=source_spec or {"media_key": "audio_file"},
        source_key="track:3:audio",
        db_path=db_path,
        data_root=None,
        cancel_event=cancel_event or threading.Event(),
        waveform_width=320,
        cache_budget_bytes=1024,
        require_decoded=False,
        base_track_order=[3, 2, 3],
        effective_track_order=[2, 3],
        build_preview_state=build_preview_state,
    )


def _prepared_media(
    *,
    source_path: str,
    owns_source_path: bool = False,
    decoded_samples: object | None = None,
    sample_rate: int = 0,
) -> preview._AudioPreviewPreparedMedia:
    return preview._AudioPreviewPreparedMedia(
        track_id=3,
        source_key="track:3:audio",
        audio_mime="audio/wav",
        source_path=source_path,
        owns_source_path=owns_source_path,
        decoded_samples=decoded_samples,
        sample_rate=sample_rate,
        waveform_peaks=[(-0.1, 0.2)],
        spectrum_frames=[[0.1, 0.4]],
        peak_frames=[(-12.0, -6.0)],
        byte_count=11,
        generation=7,
        created_at=time.monotonic(),
    )


def test_audio_preview_mime_suffix_prepared_media_and_tempfile_helpers(tmp_path: Path) -> None:
    assert preview._audio_preview_detect_mime_from_bytes(b"RIFFxxxxWAVE") == "audio/wav"
    assert preview._audio_preview_detect_mime_from_bytes(b"fLaCxxxx") == "audio/flac"
    assert preview._audio_preview_detect_mime_from_bytes(b"OggS" + b"OpusHead") == "audio/opus"
    assert preview._audio_preview_detect_mime_from_bytes(b"OggSxxxx") == "audio/ogg"
    assert preview._audio_preview_detect_mime_from_bytes(b"ID3tag") == "audio/mpeg"
    assert preview._audio_preview_detect_mime_from_bytes(bytes([0xFF, 0xE3, 0x00])) == "audio/mpeg"
    assert preview._audio_preview_detect_mime_from_bytes(b"unknown") == ""
    assert preview._audio_preview_suffix_for_mime(" audio/opus ") == ".opus"
    assert preview._audio_preview_suffix_for_mime("missing/type", ".raw") == ".raw"

    class Samples:
        nbytes = 33

    owned_path = tmp_path / "owned.wav"
    owned_path.write_bytes(b"audio")
    prepared = _prepared_media(
        source_path=str(owned_path),
        owns_source_path=True,
        decoded_samples=Samples(),
    )
    assert prepared.memory_cost() == 44
    prepared.dispose()
    assert not owned_path.exists()
    assert prepared.owns_source_path is False
    prepared.dispose()

    temp_path = Path(preview._audio_preview_write_preload_temp_file(b"abc", ".wav"))
    try:
        assert temp_path.exists()
        assert temp_path.read_bytes() == b"abc"
        assert temp_path.suffix == ".wav"
    finally:
        temp_path.unlink(missing_ok=True)


def test_audio_preview_fetch_source_for_custom_blob_and_cancel_paths(tmp_path: Path) -> None:
    db_path = tmp_path / "profile.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE CustomFieldDefs(id INTEGER PRIMARY KEY, field_type TEXT);
            CREATE TABLE CustomFieldValues(
                track_id INTEGER,
                field_def_id INTEGER,
                blob_value BLOB,
                managed_file_path TEXT,
                storage_mode TEXT,
                filename TEXT,
                mime_type TEXT,
                size_bytes INTEGER
            );
            """
        )
        conn.execute("INSERT INTO CustomFieldDefs(id, field_type) VALUES (9, 'blob_audio')")
        conn.execute(
            """
            INSERT INTO CustomFieldValues(
                track_id, field_def_id, blob_value, filename, mime_type, size_bytes
            )
            VALUES (3, 9, ?, 'take.wav', '', 3)
            """,
            (sqlite3.Binary(b"RIFFxxxxWAVE"),),
        )
        conn.commit()
    finally:
        conn.close()

    task = _preload_task(
        db_path=str(db_path),
        source_spec={"kind": "custom", "field_id": 9},
    )
    source_path, owns_source, mime, byte_count = preview._audio_preview_fetch_source_for_preload(
        task
    )
    try:
        assert owns_source is True
        assert Path(source_path).exists()
        assert mime == "audio/wav"
        assert byte_count == len(b"RIFFxxxxWAVE")
    finally:
        Path(source_path).unlink(missing_ok=True)

    cancelled = threading.Event()
    cancelled.set()
    with pytest.raises(preview._AudioPreviewPreloadCancelled):
        preview._audio_preview_fetch_source_for_preload(
            _preload_task(
                db_path=str(db_path),
                cancel_event=cancelled,
                source_spec={"kind": "custom", "field_id": 9},
            )
        )
    with pytest.raises(FileNotFoundError):
        preview._audio_preview_fetch_source_for_preload(
            _preload_task(db_path="", source_spec={"kind": "custom", "field_id": 9})
        )
    with pytest.raises(FileNotFoundError):
        preview._audio_preview_fetch_source_for_preload(
            _preload_task(
                db_path=str(db_path),
                source_spec={"kind": "custom", "field_id": 0},
            )
        )


def test_audio_preview_queue_and_artwork_helpers_handle_duplicates_and_failures() -> None:
    snapshots = {
        1: SimpleNamespace(track_title="One", artist_name="Artist", album_title="Album"),
        2: SimpleNamespace(track_title="", artist_name="", album_title=""),
    }

    class TrackService:
        def fetch_track_snapshot(self, track_id, include_media_blobs=False):
            if track_id == 99:
                raise RuntimeError("missing")
            return snapshots.get(track_id)

        def fetch_media_bytes(self, track_id, media_key):
            if track_id == 1 and media_key == "album_art":
                return b"image", "image/png"
            raise FileNotFoundError

    items = preview._audio_preview_track_queue_items_for_service(
        TrackService(),
        [1, "bad", 2, 1, 99],
    )
    assert items == [
        {"track_id": 1, "title": "One", "label": "One", "album": "Album", "position": 1},
        {"track_id": 2, "title": "Track 2", "label": "Track 2", "album": "", "position": 3},
        {"track_id": 99, "title": "Track 99", "label": "Track 99", "album": "", "position": 5},
    ]

    snapshot_with_art = SimpleNamespace(
        album_art_path="",
        album_art_blob_b64="present",
        album_art_filename="cover.png",
        album_art_size_bytes=5,
        album_art_mime_type="",
    )
    artwork = preview._audio_preview_artwork_payload_for_snapshot(
        TrackService(), 1, snapshot_with_art
    )
    assert artwork is not None
    assert artwork.data == b"image"
    assert artwork.mime_type == "image/png"
    assert (
        preview._audio_preview_artwork_payload_for_snapshot(TrackService(), 2, snapshot_with_art)
        is None
    )
    assert preview._audio_preview_artwork_payload_for_snapshot(TrackService(), 1, None) is None


def test_build_audio_preview_preload_success_cancel_and_error(monkeypatch, tmp_path: Path) -> None:
    source_path = tmp_path / "source.wav"
    source_path.write_bytes(b"audio")

    monkeypatch.setattr(
        preview,
        "_audio_preview_fetch_source_for_preload",
        lambda _task: (str(source_path), True, "audio/wav", 5),
    )
    monkeypatch.setattr(preview, "load_wav_peaks", lambda path, width: [(-0.2, 0.5)])
    monkeypatch.setattr(preview, "load_audio_spectrum_frames", lambda path: [[0.1, 0.2]])
    monkeypatch.setattr(preview, "load_audio_peak_meter_frames", lambda path: [(-12.0, -3.0)])
    monkeypatch.setattr(
        preview,
        "_audio_preview_state_for_preload_task",
        lambda task, prepared: {"track_id": task.track_id, "prepared": prepared.source_key},
    )

    result = preview._build_audio_preview_preload(
        _preload_task(db_path=str(tmp_path / "profile.db"), build_preview_state=True)
    )
    assert result.error == ""
    assert result.cancelled is False
    assert result.prepared is not None
    assert result.prepared.waveform_peaks == [(-0.2, 0.5)]
    assert result.prepared.preview_state == {"track_id": 3, "prepared": "track:3:audio"}
    result.prepared.dispose()

    cancelled = threading.Event()
    cancelled.set()
    cancelled_result = preview._build_audio_preview_preload(
        _preload_task(db_path=str(tmp_path / "profile.db"), cancel_event=cancelled)
    )
    assert cancelled_result.cancelled is True

    monkeypatch.setattr(
        preview,
        "_audio_preview_fetch_source_for_preload",
        lambda _task: (_ for _ in ()).throw(RuntimeError("decode failed")),
    )
    error_result = preview._build_audio_preview_preload(
        _preload_task(db_path=str(tmp_path / "profile.db"))
    )
    assert "decode failed" in error_result.error


def test_build_audio_preview_track_load_uses_prepared_or_decodes_owned_preload(
    monkeypatch,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "profile.db"
    sqlite3.connect(db_path).close()

    class FakeTrackService:
        def __init__(self, _conn, _data_root):
            pass

        def fetch_track_snapshot(self, track_id, include_media_blobs=False):
            return SimpleNamespace(
                track_title=f"Track {track_id}",
                artist_name="Artist",
                album_title="Album",
                album_art_path="",
                album_art_blob_b64="",
                album_art_filename="",
                album_art_size_bytes=0,
                album_art_mime_type="",
            )

    monkeypatch.setattr(preview, "TrackService", FakeTrackService)
    prepared = _prepared_media(
        source_path=str(tmp_path / "prepared.wav"),
        decoded_samples=SimpleNamespace(nbytes=12),
        sample_rate=44100,
    )
    task = preview._AudioPreviewTrackLoadTask(
        request_id=11,
        track_id=3,
        source_spec={"media_key": "audio_file"},
        source_key="track:3:audio",
        autoplay=True,
        db_path=str(db_path),
        data_root=None,
        base_track_order=[3, 2],
        effective_track_order=[2, 3],
        cancel_event=threading.Event(),
        waveform_width=480,
        cache_budget_bytes=1024,
        prepared_media=prepared,
    )

    result = preview._build_audio_preview_track_load(task)
    assert result.error == ""
    assert result.cancelled is False
    assert result.prepared_owned_by_result is False
    assert result.state is not None
    assert result.state["title"] == "Track 3"
    assert result.state["_autoplay"] is True
    assert [item["track_id"] for item in result.state["effective_track_queue"]] == [2, 3]

    preload_path = tmp_path / "preloaded.wav"
    preload_path.write_bytes(b"audio")
    owned_prepared = _prepared_media(source_path=str(preload_path), owns_source_path=True)
    monkeypatch.setattr(
        preview,
        "_build_audio_preview_preload",
        lambda _task: preview._AudioPreviewPreloadResult(
            generation=12,
            track_id=3,
            source_key="track:3:audio",
            prepared=owned_prepared,
        ),
    )
    monkeypatch.setattr(
        preview,
        "_decode_audio_file",
        lambda _path: (SimpleNamespace(nbytes=24), 48000),
    )
    task.prepared_media = None
    decoded = preview._build_audio_preview_track_load(task)
    assert decoded.error == ""
    assert decoded.prepared_owned_by_result is True
    assert decoded.state["prepared_media"].sample_rate == 48000

    cancelled = threading.Event()
    cancelled.set()
    cancelled_result = preview._build_audio_preview_track_load(
        preview._AudioPreviewTrackLoadTask(
            request_id=12,
            track_id=3,
            source_spec={},
            source_key="track:3:audio",
            autoplay=False,
            db_path=str(db_path),
            data_root=None,
            base_track_order=[],
            effective_track_order=[],
            cancel_event=cancelled,
            waveform_width=480,
            cache_budget_bytes=1024,
        )
    )
    assert cancelled_result.cancelled is True

    missing_db = preview._build_audio_preview_track_load(
        preview._AudioPreviewTrackLoadTask(
            request_id=13,
            track_id=3,
            source_spec={},
            source_key="track:3:audio",
            autoplay=False,
            db_path="",
            data_root=None,
            base_track_order=[],
            effective_track_order=[],
            cancel_event=threading.Event(),
            waveform_width=480,
            cache_budget_bytes=1024,
        )
    )
    assert "No active profile database" in missing_db.error

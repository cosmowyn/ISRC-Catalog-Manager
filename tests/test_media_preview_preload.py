from __future__ import annotations

import os
import sqlite3
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QBuffer, QEvent, QIODevice, QPoint, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QPixmap
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QMenu, QPinchGesture, QToolButton

from isrc_manager.media import preview_dialogs as preview
from isrc_manager.media.bookmarks import AudioBookmark
from tests.qt_test_helpers import require_qapplication


def _preload_task(
    *,
    db_path: str,
    cancel_event: threading.Event | None = None,
    source_spec: dict[str, object] | None = None,
    data_root: str | None = None,
    build_preview_state: bool = False,
) -> preview._AudioPreviewPreloadTask:
    return preview._AudioPreviewPreloadTask(
        generation=7,
        track_id=3,
        source_spec=source_spec or {"media_key": "audio_file"},
        source_key="track:3:audio",
        db_path=db_path,
        data_root=data_root,
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


def _png_bytes(width: int = 32, height: int = 20, color: str = "#336699") -> bytes:
    image = QImage(width, height, QImage.Format_ARGB32)
    image.fill(QColor(color))
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    assert image.save(buffer, "PNG")
    return bytes(buffer.data())


class _DeltaEvent:
    def __init__(
        self,
        *,
        pixel: QPoint | None = None,
        angle: QPoint | None = None,
        modifiers=Qt.NoModifier,
    ) -> None:
        self._pixel = pixel or QPoint()
        self._angle = angle or QPoint()
        self._modifiers = modifiers
        self.accepted = False

    def pixelDelta(self) -> QPoint:
        return self._pixel

    def angleDelta(self) -> QPoint:
        return self._angle

    def modifiers(self):
        return self._modifiers

    def accept(self) -> None:
        self.accepted = True


class _NativeGestureEvent:
    def __init__(self, gesture_type, value: float = 0.0) -> None:
        self._gesture_type = gesture_type
        self._value = value
        self.accepted = False

    def gestureType(self):
        return self._gesture_type

    def value(self) -> float:
        return self._value

    def accept(self) -> None:
        self.accepted = True


class _PinchGesture:
    def __init__(
        self,
        *,
        flags=QPinchGesture.ChangeFlag(0),
        last_factor: float = 1.0,
        scale_factor: float = 1.0,
    ) -> None:
        self._flags = flags
        self._last_factor = last_factor
        self._scale_factor = scale_factor

    def changeFlags(self):
        return self._flags

    def lastScaleFactor(self) -> float:
        return self._last_factor

    def scaleFactor(self) -> float:
        return self._scale_factor


class _GestureEvent:
    def __init__(self, pinch=None) -> None:
        self._pinch = pinch
        self.accepted = False

    def gesture(self, gesture_type):
        return self._pinch if gesture_type == Qt.PinchGesture else None

    def accept(self) -> None:
        self.accepted = True


class _MouseEvent:
    def __init__(self, button=Qt.LeftButton) -> None:
        self._button = button
        self.accepted = False

    def button(self):
        return self._button

    def accept(self) -> None:
        self.accepted = True


class _Style:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def unpolish(self, _widget) -> None:
        self.calls.append("unpolish")

    def polish(self, _widget) -> None:
        self.calls.append("polish")


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


def test_audio_preview_prepared_media_dispose_ignores_missing_and_remove_errors(
    monkeypatch,
    tmp_path: Path,
) -> None:
    missing = _prepared_media(source_path=str(tmp_path / "missing.wav"), owns_source_path=True)
    missing.dispose()
    assert missing.owns_source_path is False

    failing = _prepared_media(source_path=str(tmp_path / "failing.wav"), owns_source_path=True)
    monkeypatch.setattr(
        preview.os,
        "remove",
        lambda _path: (_ for _ in ()).throw(OSError("locked")),
    )
    failing.dispose()
    assert failing.owns_source_path is False


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
    with pytest.raises(FileNotFoundError, match="No custom audio file stored"):
        preview._audio_preview_fetch_source_for_preload(
            _preload_task(
                db_path=str(db_path),
                source_spec={"kind": "custom", "field_id": 10},
            )
        )

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            UPDATE CustomFieldValues
            SET blob_value=NULL, managed_file_path=NULL, storage_mode='database'
            WHERE track_id=3 AND field_def_id=9
            """
        )
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(FileNotFoundError, match="No custom audio blob stored"):
        preview._audio_preview_fetch_source_for_preload(
            _preload_task(
                db_path=str(db_path),
                source_spec={"kind": "custom", "field_id": 9},
            )
        )


def test_audio_preview_fetch_source_handles_managed_custom_files_and_track_service(
    monkeypatch,
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    managed_path = data_root / "custom_field_media" / "managed.wav"
    managed_path.parent.mkdir(parents=True)
    managed_path.write_bytes(b"RIFFxxxxWAVE")

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
                track_id, field_def_id, blob_value, managed_file_path, storage_mode,
                filename, mime_type, size_bytes
            )
            VALUES (3, 9, NULL, 'custom_field_media/managed.wav', 'managed_file',
                    'managed.wav', '', 0)
            """
        )
        conn.commit()
    finally:
        conn.close()

    managed = preview._audio_preview_fetch_source_for_preload(
        _preload_task(
            db_path=str(db_path),
            data_root=str(data_root),
            source_spec={"kind": "custom", "field_id": 9},
        )
    )
    assert managed[0] == str(managed_path)
    assert managed[1] is False
    assert managed[2].startswith("audio/")
    assert managed[3] == managed_path.stat().st_size

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            UPDATE CustomFieldValues
            SET managed_file_path='custom_field_media/missing.wav',
                filename='missing.wav'
            """
        )
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(FileNotFoundError, match="missing.wav"):
        preview._audio_preview_fetch_source_for_preload(
            _preload_task(
                db_path=str(db_path),
                data_root=str(data_root),
                source_spec={"kind": "custom", "field_id": 9},
            )
        )

    class FakeTrackService:
        handle = SimpleNamespace(
            source_path=tmp_path / "track.wav",
            source_bytes=None,
            mime_type="",
            suffix="",
            size_bytes=0,
        )

        def __init__(self, _conn, _data_root):
            pass

        def resolve_media_source(self, _track_id, _media_key):
            return self.handle

    FakeTrackService.handle.source_path.write_bytes(b"RIFF")
    monkeypatch.setattr(preview, "TrackService", FakeTrackService)

    track_file = preview._audio_preview_fetch_source_for_preload(
        _preload_task(db_path=str(db_path), source_spec={"media_key": "audio_file"})
    )
    assert track_file[0] == str(FakeTrackService.handle.source_path)
    assert track_file[1] is False
    assert track_file[2].startswith("audio/")
    assert track_file[3] == 0

    FakeTrackService.handle = SimpleNamespace(
        source_path=None,
        source_bytes=b"fLaCdata",
        mime_type="",
        suffix=".flac",
        size_bytes=0,
    )
    temp_file = preview._audio_preview_fetch_source_for_preload(
        _preload_task(db_path=str(db_path), source_spec={"media_key": "alt_audio"})
    )
    try:
        assert temp_file[1] is True
        assert Path(temp_file[0]).exists()
        assert temp_file[2] == "audio/flac"
        assert temp_file[3] == len(b"fLaCdata")
        assert Path(temp_file[0]).suffix == ".flac"
    finally:
        Path(temp_file[0]).unlink(missing_ok=True)

    FakeTrackService.handle = SimpleNamespace(
        source_path=None,
        source_bytes=b"",
        mime_type="",
        suffix="",
        size_bytes=0,
    )
    with pytest.raises(FileNotFoundError, match="missing_audio"):
        preview._audio_preview_fetch_source_for_preload(
            _preload_task(db_path=str(db_path), source_spec={"media_key": "missing_audio"})
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


def test_audio_preview_state_for_preload_task_builds_metadata_and_respects_cancellation(
    monkeypatch,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "profile.db"
    sqlite3.connect(db_path).close()
    prepared = _prepared_media(source_path=str(tmp_path / "prepared.wav"))

    class FakeTrackService:
        def __init__(self, _conn, _data_root):
            pass

        def fetch_track_snapshot(self, track_id, include_media_blobs=False):
            if track_id == 99:
                raise RuntimeError("unreadable")
            return SimpleNamespace(
                track_title="" if track_id == 4 else f"Track {track_id}",
                artist_name="Artist" if track_id == 3 else "",
                album_title="Album" if track_id == 3 else "",
                album_art_path="",
                album_art_blob_b64="present" if track_id == 3 else "",
                album_art_filename="cover.png" if track_id == 3 else "",
                album_art_size_bytes=5 if track_id == 3 else 0,
                album_art_mime_type="",
            )

        def fetch_media_bytes(self, track_id, media_key):
            assert track_id == 3
            assert media_key == "album_art"
            return b"cover", "image/png"

    monkeypatch.setattr(preview, "TrackService", FakeTrackService)

    task = _preload_task(db_path=str(db_path), build_preview_state=True)
    task.base_track_order = ["bad", 4, 4, 99]
    task.effective_track_order = []
    state = preview._audio_preview_state_for_preload_task(task, prepared)
    assert state is not None
    assert state["track_id"] == 3
    assert state["track_order"] == [3, 4, 99]
    assert state["effective_track_order"] == [3, 4, 99]
    assert state["title"] == "Track 3"
    assert state["artist"] == "Artist"
    assert state["album"] == "Album"
    assert state["artwork_payload"].data == b"cover"
    assert [item["title"] for item in state["track_queue"]] == [
        "Track 3",
        "Track 4",
        "Track 99",
    ]

    no_state = preview._audio_preview_state_for_preload_task(
        _preload_task(db_path=str(db_path), build_preview_state=False),
        prepared,
    )
    assert no_state is None
    no_db = preview._audio_preview_state_for_preload_task(
        _preload_task(db_path="", build_preview_state=True),
        prepared,
    )
    assert no_db is None

    cancelled = threading.Event()
    cancelled.set()
    with pytest.raises(preview._AudioPreviewPreloadCancelled):
        preview._audio_preview_state_for_preload_task(
            _preload_task(
                db_path=str(db_path),
                cancel_event=cancelled,
                build_preview_state=True,
            ),
            prepared,
        )


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


def test_build_audio_preview_preload_handles_state_errors_and_late_cancellation(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "late-cancel.wav"
    source_path.write_bytes(b"audio")

    monkeypatch.setattr(
        preview,
        "_audio_preview_fetch_source_for_preload",
        lambda _task: (str(source_path), True, "audio/wav", 5),
    )
    monkeypatch.setattr(preview, "load_wav_peaks", lambda _path, _width: [(-0.2, 0.5)])
    monkeypatch.setattr(preview, "load_audio_spectrum_frames", lambda _path: [[0.1, 0.2]])
    monkeypatch.setattr(preview, "load_audio_peak_meter_frames", lambda _path: [(-12.0, -3.0)])
    monkeypatch.setattr(
        preview,
        "_audio_preview_state_for_preload_task",
        lambda _task, _prepared: (_ for _ in ()).throw(RuntimeError("state failed")),
    )

    result = preview._build_audio_preview_preload(
        _preload_task(db_path=str(tmp_path / "profile.db"), build_preview_state=True)
    )
    assert result.error == ""
    assert result.prepared is not None
    assert result.prepared.preview_state is None
    result.prepared.dispose()

    source_path.write_bytes(b"audio")
    cancel_event = threading.Event()

    def load_spectrum(_path):
        cancel_event.set()
        return [[0.3]]

    monkeypatch.setattr(preview, "load_audio_spectrum_frames", load_spectrum)
    cancelled = preview._build_audio_preview_preload(
        _preload_task(db_path=str(tmp_path / "profile.db"), cancel_event=cancel_event)
    )
    assert cancelled.cancelled is True
    assert not source_path.exists()


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


def test_build_audio_preview_track_load_handles_preload_cancel_empty_and_decode_cancel(
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
    task = preview._AudioPreviewTrackLoadTask(
        request_id=21,
        track_id=3,
        source_spec={"media_key": "audio_file"},
        source_key="track:3:audio",
        autoplay=False,
        db_path=str(db_path),
        data_root=None,
        base_track_order=[3],
        effective_track_order=[3],
        cancel_event=threading.Event(),
        waveform_width=480,
        cache_budget_bytes=1024,
    )

    monkeypatch.setattr(
        preview,
        "_build_audio_preview_preload",
        lambda _task: preview._AudioPreviewPreloadResult(
            generation=21,
            track_id=3,
            source_key="track:3:audio",
            cancelled=True,
        ),
    )
    cancelled = preview._build_audio_preview_track_load(task)
    assert cancelled.cancelled is True

    monkeypatch.setattr(
        preview,
        "_build_audio_preview_preload",
        lambda _task: preview._AudioPreviewPreloadResult(
            generation=22,
            track_id=3,
            source_key="track:3:audio",
        ),
    )
    empty = preview._build_audio_preview_track_load(task)
    assert "No playable audio" in empty.error

    owned_path = tmp_path / "owned-cancel.wav"
    owned_path.write_bytes(b"audio")

    def preload_and_cancel(load_task):
        load_task.cancel_event.set()
        return preview._AudioPreviewPreloadResult(
            generation=23,
            track_id=3,
            source_key="track:3:audio",
            prepared=_prepared_media(source_path=str(owned_path), owns_source_path=True),
        )

    task.cancel_event = threading.Event()
    monkeypatch.setattr(preview, "_build_audio_preview_preload", preload_and_cancel)
    decode_cancelled = preview._build_audio_preview_track_load(task)
    assert decode_cancelled.cancelled is True
    assert not owned_path.exists()


def test_build_audio_preview_preload_cleans_owned_source_when_cancelled_after_decode(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "owned.wav"
    source_path.write_bytes(b"audio")
    cancel_event = threading.Event()

    monkeypatch.setattr(
        preview,
        "_audio_preview_fetch_source_for_preload",
        lambda _task: (str(source_path), True, "audio/wav", 5),
    )

    def load_peaks(_path, _width):
        cancel_event.set()
        return [(-0.2, 0.5)]

    monkeypatch.setattr(preview, "load_wav_peaks", load_peaks)
    monkeypatch.setattr(preview, "load_audio_spectrum_frames", lambda _path: [[0.1]])
    monkeypatch.setattr(preview, "load_audio_peak_meter_frames", lambda _path: [(-8.0, -3.0)])

    result = preview._build_audio_preview_preload(
        _preload_task(db_path=str(tmp_path / "profile.db"), cancel_event=cancel_event)
    )
    assert result.cancelled is True
    assert not source_path.exists()


def test_build_audio_preview_track_load_reports_preload_error_and_disposes_owned_prepared(
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
                track_title="",
                artist_name="",
                album_title="",
                album_art_path="",
                album_art_blob_b64="",
                album_art_filename="",
                album_art_size_bytes=0,
                album_art_mime_type="",
            )

    monkeypatch.setattr(preview, "TrackService", FakeTrackService)
    monkeypatch.setattr(
        preview,
        "_build_audio_preview_preload",
        lambda _task: preview._AudioPreviewPreloadResult(
            generation=15,
            track_id=3,
            source_key="track:3:audio",
            error="preload failed",
        ),
    )
    base_task = preview._AudioPreviewTrackLoadTask(
        request_id=15,
        track_id=3,
        source_spec={"media_key": "audio_file"},
        source_key="track:3:audio",
        autoplay=False,
        db_path=str(db_path),
        data_root=None,
        base_track_order=[3],
        effective_track_order=[3],
        cancel_event=threading.Event(),
        waveform_width=480,
        cache_budget_bytes=1024,
    )

    preload_error = preview._build_audio_preview_track_load(base_task)
    assert "preload failed" in preload_error.error

    owned_path = tmp_path / "owned-prepared.wav"
    owned_path.write_bytes(b"audio")
    monkeypatch.setattr(
        preview,
        "_build_audio_preview_preload",
        lambda _task: preview._AudioPreviewPreloadResult(
            generation=16,
            track_id=3,
            source_key="track:3:audio",
            prepared=_prepared_media(source_path=str(owned_path), owns_source_path=True),
        ),
    )
    monkeypatch.setattr(
        preview,
        "_decode_audio_file",
        lambda _path: (_ for _ in ()).throw(RuntimeError("decode failed")),
    )

    decode_error = preview._build_audio_preview_track_load(base_task)
    assert "decode failed" in decode_error.error
    assert not owned_path.exists()


def test_audio_preview_preload_workers_cover_late_cancel_and_cleanup_failures(
    monkeypatch,
    tmp_path: Path,
) -> None:
    class CloseFailConnection:
        def close(self) -> None:
            raise RuntimeError("close failed")

    class FakeConnectionFactory:
        def open(self, _path):
            return CloseFailConnection()

    class FakeTrackService:
        cancel_on_snapshot: threading.Event | None = None

        def __init__(self, _conn, _data_root=None):
            pass

        def resolve_media_source(self, _track_id, _media_key):
            return SimpleNamespace(
                source_path=None,
                source_bytes=b"RIFFxxxxWAVE",
                mime_type="",
                suffix=".wav",
                size_bytes=0,
            )

        def fetch_track_snapshot(self, track_id, include_media_blobs=False):
            if self.cancel_on_snapshot is not None:
                self.cancel_on_snapshot.set()
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

    monkeypatch.setattr(preview, "SQLiteConnectionFactory", FakeConnectionFactory)
    monkeypatch.setattr(preview, "TrackService", FakeTrackService)

    fetched = preview._audio_preview_fetch_source_for_preload(
        _preload_task(db_path=str(tmp_path / "profile.db"))
    )
    try:
        assert fetched[1] is True
        assert Path(fetched[0]).exists()
    finally:
        Path(fetched[0]).unlink(missing_ok=True)

    prepared = _prepared_media(source_path=str(tmp_path / "prepared.wav"))
    duplicate_task = _preload_task(
        db_path=str(tmp_path / "profile.db"),
        build_preview_state=True,
    )
    duplicate_task.base_track_order = [3, 3, "bad"]
    state = preview._audio_preview_state_for_preload_task(duplicate_task, prepared)
    assert state is not None
    assert state["track_order"] == [3]

    late_cancel = threading.Event()
    FakeTrackService.cancel_on_snapshot = late_cancel
    with pytest.raises(preview._AudioPreviewPreloadCancelled):
        preview._audio_preview_state_for_preload_task(
            _preload_task(
                db_path=str(tmp_path / "profile.db"),
                cancel_event=late_cancel,
                build_preview_state=True,
            ),
            prepared,
        )
    FakeTrackService.cancel_on_snapshot = None

    class ToggleCancel(threading.Event):
        def __init__(self, values: list[bool]) -> None:
            super().__init__()
            self._values = list(values)

        def is_set(self) -> bool:
            if self._values:
                return self._values.pop(0)
            return True

    early_cancel_path = tmp_path / "early-cancel.wav"
    early_cancel_path.write_bytes(b"audio")
    monkeypatch.setattr(
        preview,
        "_audio_preview_fetch_source_for_preload",
        lambda _task: (str(early_cancel_path), True, "audio/wav", 5),
    )
    monkeypatch.setattr(preview, "load_wav_peaks", lambda _path, _width: [(-0.2, 0.3)])
    monkeypatch.setattr(preview, "load_audio_spectrum_frames", lambda _path: [[0.1]])
    monkeypatch.setattr(preview, "load_audio_peak_meter_frames", lambda _path: [(-6.0, -3.0)])

    early_cancel = preview._build_audio_preview_preload(
        _preload_task(
            db_path=str(tmp_path / "profile.db"),
            cancel_event=ToggleCancel([False, True]),
        )
    )
    assert early_cancel.cancelled is True
    assert not early_cancel_path.exists()

    prepared_cancel_path = tmp_path / "prepared-cancel.wav"
    prepared_cancel_path.write_bytes(b"audio")
    monkeypatch.setattr(
        preview,
        "_audio_preview_fetch_source_for_preload",
        lambda _task: (str(prepared_cancel_path), True, "audio/wav", 5),
    )
    monkeypatch.setattr(
        preview,
        "_audio_preview_state_for_preload_task",
        lambda _task, _prepared: (_ for _ in ()).throw(preview._AudioPreviewPreloadCancelled()),
    )
    prepared_cancel = preview._build_audio_preview_preload(
        _preload_task(db_path=str(tmp_path / "profile.db"), build_preview_state=True)
    )
    assert prepared_cancel.cancelled is True
    assert not prepared_cancel_path.exists()

    error_cleanup_path = tmp_path / "error-cleanup.wav"
    error_cleanup_path.write_bytes(b"audio")
    monkeypatch.setattr(
        preview,
        "_audio_preview_fetch_source_for_preload",
        lambda _task: (str(error_cleanup_path), True, "audio/wav", 5),
    )
    monkeypatch.setattr(
        preview,
        "load_wav_peaks",
        lambda _path, _width: (_ for _ in ()).throw(RuntimeError("decode exploded")),
    )
    remove_calls: list[str] = []
    monkeypatch.setattr(
        preview.os,
        "remove",
        lambda path: remove_calls.append(str(path)) or (_ for _ in ()).throw(OSError("busy")),
    )
    error_cleanup = preview._build_audio_preview_preload(
        _preload_task(db_path=str(tmp_path / "profile.db"))
    )
    assert "decode exploded" in error_cleanup.error
    assert remove_calls == [str(error_cleanup_path)]


def test_audio_preview_track_load_close_and_decode_cancel_edges(
    monkeypatch,
    tmp_path: Path,
) -> None:
    class CloseFailConnection:
        def close(self) -> None:
            raise RuntimeError("close failed")

    class FakeConnectionFactory:
        def open(self, _path):
            return CloseFailConnection()

    class FakeTrackService:
        def __init__(self, _conn, _data_root=None):
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

    monkeypatch.setattr(preview, "SQLiteConnectionFactory", FakeConnectionFactory)
    monkeypatch.setattr(preview, "TrackService", FakeTrackService)

    cancel_event = threading.Event()
    decoded_prepared = _prepared_media(
        source_path=str(tmp_path / "decoded.wav"),
        decoded_samples=SimpleNamespace(nbytes=12),
        sample_rate=44100,
    )
    task = preview._AudioPreviewTrackLoadTask(
        request_id=31,
        track_id=3,
        source_spec={"media_key": "audio_file"},
        source_key="track:3:audio",
        autoplay=False,
        db_path=str(tmp_path / "profile.db"),
        data_root=None,
        base_track_order=[3],
        effective_track_order=[3],
        cancel_event=cancel_event,
        waveform_width=480,
        cache_budget_bytes=1024,
        prepared_media=decoded_prepared,
    )
    loaded = preview._build_audio_preview_track_load(task)
    assert loaded.error == ""
    assert loaded.state is not None
    assert loaded.state["prepared_media"] is decoded_prepared

    decode_cancel_path = tmp_path / "decode-cancel.wav"
    decode_cancel_path.write_bytes(b"audio")
    decode_cancel = threading.Event()

    def decode_and_cancel(_path):
        decode_cancel.set()
        return SimpleNamespace(nbytes=24), 48000

    monkeypatch.setattr(preview, "_decode_audio_file", decode_and_cancel)
    task.cancel_event = decode_cancel
    task.prepared_media = _prepared_media(source_path=str(decode_cancel_path))
    cancelled = preview._build_audio_preview_track_load(task)
    assert cancelled.cancelled is True


def test_audio_preview_dialog_queue_source_and_waiting_preload_helpers() -> None:
    dialog = preview._AudioPreviewDialog.__new__(preview._AudioPreviewDialog)
    provider_calls: list[list[int]] = []

    def queue_provider(track_ids):
        ids = [int(track_id) for track_id in track_ids]
        provider_calls.append(ids)
        if ids == [8]:
            raise RuntimeError("queue unavailable")
        return [{"track_id": ids[0], "label": f"Fetched {ids[0]}"}]

    dialog.app = SimpleNamespace(
        _audio_preview_track_queue_items=queue_provider,
        _audio_preview_navigation_track_ids=lambda _source_spec: ["bad", 4, 5, 4],
        _normalize_track_ids=lambda values: [
            int(value) for value in values if str(value).isdigit()
        ],
    )
    dialog._source_spec = {"media_key": "audio_file"}
    dialog._current_track_id = 3
    dialog._track_order = [1, 2, 3, 4]
    dialog._base_track_queue = [
        {"track_id": 2, "title": "Two"},
        {"track_id": "bad", "title": "Ignored"},
    ]
    dialog._track_queue = [{"track_id": 4, "label": "Four"}]
    dialog._loop_mode = preview._AudioPreviewDialog.LOOP_MODE_PLAYLIST
    dialog._shuffle_enabled = False

    assert preview._AudioPreviewDialog._audio_preload_source_key(None) == "raw"
    assert (
        preview._AudioPreviewDialog._audio_preload_source_key({"kind": "custom", "field_id": "bad"})
        == '{"field_id":0,"kind":"custom"}'
    )
    assert (
        preview._AudioPreviewDialog._audio_preload_source_key({"media_key": ""})
        == '{"kind":"","media_key":"audio_file"}'
    )
    assert dialog._audio_preload_key(3) == (
        3,
        '{"kind":"","media_key":"audio_file"}',
    )
    assert dialog._audio_preload_window_track_ids(1, radius=2) == [1, 2, 4, 3]

    ordered = dialog._ordered_track_queue_items([2, "bad", 7, 8])
    assert ordered == [
        {"track_id": 2, "title": "Two", "label": "Two", "position": 1},
        {
            "track_id": 7,
            "label": "Fetched 7",
            "title": "Fetched 7",
            "position": 3,
        },
        {"track_id": 8, "title": "Track 8", "label": "Track 8", "position": 4},
    ]
    assert provider_calls == [[7], [8]]

    assert dialog._track_order_for_load_request(
        3,
        {"media_key": "audio_file"},
    ) == [3, 4, 5, 4]
    dialog.app._audio_preview_navigation_track_ids = lambda _source_spec: (
        (_ for _ in ()).throw(RuntimeError("navigation failed"))
    )
    assert dialog._track_order_for_load_request(9, {"media_key": "audio_file"}) == [9]

    assert dialog._effective_track_order_for_load_request(
        3,
        {"media_key": "audio_file"},
        [3, 4],
    ) == [1, 2, 3, 4]
    dialog._shuffle_enabled = True
    dialog._source_spec = {"media_key": "other_audio"}
    dialog._create_shuffled_track_order = lambda order, current_id: [current_id, *order[::-1]]
    assert dialog._effective_track_order_for_load_request(
        3,
        {"media_key": "audio_file"},
        [3, 4],
    ) == [3, 4, 3]

    placeholders = dialog._placeholder_track_queue_items([2, 4, 9])
    assert placeholders == [
        {"track_id": 2, "title": "Two", "label": "Two", "position": 1},
        {"track_id": 4, "label": "Four", "title": "Four", "position": 2},
        {"track_id": 9, "title": "Track 9", "label": "Track 9", "position": 3},
    ]

    key = (3, '{"kind":"","media_key":"audio_file"}')
    assert dialog._waiting_preload_for_key(key) is None
    waiting = {
        "key": key,
        "track_id": 3,
        "source_spec": {"media_key": "audio_file"},
        "base_track_order": [3],
        "effective_track_order": [3],
        "autoplay": True,
    }
    dialog._audio_load_waiting_for_preload = dict(waiting)
    submitted: list[tuple[str, preview._AudioPreviewPreparedMedia | None]] = []
    dialog._prepared_media_ready_for_instant_playback = lambda _prepared: False
    dialog._submit_waiting_preload_as_active_load = (
        lambda _waiting, prepared, *, reason: submitted.append((reason, prepared))
    )
    prepared = _prepared_media(source_path="/tmp/missing-audio.wav")
    assert dialog._apply_waiting_preload_result(key, prepared) is True
    assert submitted == [("preload-not-decoded", prepared)]

    dialog._audio_load_waiting_for_preload = dict(waiting)
    dialog._prepared_media_ready_for_instant_playback = lambda _prepared: True
    applied_calls: list[bool] = []
    logs: list[tuple[str, dict[str, object]]] = []
    dialog._apply_cached_track_preview = (
        lambda *_args, **_kwargs: applied_calls.append(True) or True
    )
    dialog._log_audio_preload = lambda action, **details: logs.append((action, details))
    assert dialog._apply_waiting_preload_result(key, prepared) is True
    assert dialog._audio_load_waiting_for_preload is None
    assert applied_calls == [True]
    assert logs == [("wait-ready", {"track_id": 3, "source_key": key[1]})]

    dialog._audio_load_waiting_for_preload = dict(waiting)
    dialog._apply_cached_track_preview = lambda *_args, **_kwargs: False
    assert dialog._apply_waiting_preload_result(key, prepared) is False
    assert dialog._audio_load_waiting_for_preload == waiting


def test_audio_preview_dialog_active_load_cache_raw_and_submission_paths(tmp_path: Path) -> None:
    dialog = preview._AudioPreviewDialog.__new__(preview._AudioPreviewDialog)
    logs: list[tuple[str, dict[str, object]]] = []
    applied: list[dict[str, object]] = []
    submitted: list[tuple[int, int, dict[str, object], list[int], list[int], object, bool]] = []
    cancellations: list[str] = []
    preload_cancellations: list[str] = []
    evictions: list[tuple[set[tuple[int, str]], str]] = []
    begin_calls: list[tuple[int, dict[str, object], list[int], list[int]]] = []
    raw_states: list[tuple[bytes, str, str]] = []

    dialog.app = SimpleNamespace(
        current_db_path=str(tmp_path / "profile.db"),
        data_root=str(tmp_path),
        _normalize_track_ids=lambda values: [
            int(value) for value in values if str(value).isdigit()
        ],
        _audio_preview_export_actions_for_track=lambda track_id, source_spec, **_kwargs: [
            {"text": f"Export {track_id}:{source_spec.get('media_key')}"}
        ],
        _audio_preview_state_for_raw_bytes=lambda data, mime, title, **_kwargs: raw_states.append(
            (bytes(data), str(mime), str(title))
        )
        or {
            "track_id": None,
            "audio_bytes": bytes(data),
            "audio_mime": mime,
            "title": title,
        },
    )
    dialog._source_spec = {"media_key": "audio_file"}
    dialog._current_track_id = 3
    dialog._track_order = [3, 4, 5]
    dialog._base_track_queue = [{"track_id": 3, "title": "Three"}]
    dialog._track_queue = [{"track_id": 5, "title": "Five"}]
    dialog._shuffle_enabled = False
    dialog._loop_mode = dialog.LOOP_MODE_PLAYLIST
    dialog._audio_load_request_id = 10
    dialog._audio_load_jobs = {}
    dialog._audio_preload_jobs = {}
    dialog._audio_load_waiting_for_preload = {"stale": True}
    dialog._log_audio_preload = lambda action, **details: logs.append((action, details))
    dialog._prepared_media_ready_for_instant_playback = lambda prepared: prepared is not None
    dialog._apply_preview_state = lambda state, **kwargs: applied.append(
        {"state": dict(state), **kwargs}
    )

    cached_path = tmp_path / "cached.wav"
    cached_path.write_bytes(b"audio")
    prepared = _prepared_media(
        source_path=str(cached_path),
        decoded_samples=SimpleNamespace(nbytes=12),
        sample_rate=44100,
    )
    prepared.preview_state = {
        "track_id": 3,
        "track_order": [99],
        "effective_track_order": [88],
        "title": "Cached Three",
        "artist": "Artist",
    }

    assert dialog._apply_cached_track_preview(
        3,
        {"media_key": "audio_file"},
        [3, 4],
        [3, 5],
        prepared,
        autoplay=True,
    )
    assert dialog._audio_load_request_id == 11
    assert dialog._audio_load_waiting_for_preload is None
    assert applied[-1]["autoplay"] is True
    assert applied[-1]["source_spec"] == {"media_key": "audio_file"}
    assert applied[-1]["state"]["track_order"] == [3, 4]
    assert [item["track_id"] for item in applied[-1]["state"]["track_queue"]] == [3, 4]
    assert applied[-1]["state"]["effective_track_order"] == [3, 5]
    assert [item["track_id"] for item in applied[-1]["state"]["effective_track_queue"]] == [3, 5]
    assert applied[-1]["state"]["export_actions"][0]["text"] == "Export 3:audio_file"
    assert logs[-1][0] == "instant-hit"

    dialog.app._audio_preview_export_actions_for_track = lambda *_args, **_kwargs: (
        (_ for _ in ()).throw(RuntimeError("export actions failed"))
    )
    assert (
        dialog._apply_cached_track_preview(
            3,
            {"media_key": "audio_file"},
            [3],
            [3],
            prepared,
            autoplay=False,
        )
        is False
    )
    assert logs[-1][0] == "instant-hit-failed"
    assert "export actions failed" in logs[-1][1]["error"]
    dialog.app._audio_preview_export_actions_for_track = lambda track_id, source_spec, **_kwargs: [
        {"text": f"Export {track_id}"}
    ]

    waiting = {
        "track_id": 4,
        "source_spec": {"media_key": "alt_audio"},
        "base_track_order": [4, 3],
        "effective_track_order": [4],
        "autoplay": True,
    }
    dialog._audio_load_waiting_for_preload = dict(waiting)
    dialog._submit_audio_track_load = lambda request_id, track_id, source_spec, base_track_order, effective_track_order, prepared_media, autoplay: submitted.append(
        (
            int(request_id),
            int(track_id),
            dict(source_spec),
            list(base_track_order),
            list(effective_track_order),
            prepared_media,
            bool(autoplay),
        )
    )
    dialog._submit_waiting_preload_as_active_load(waiting, prepared, reason="decode-needed")
    assert dialog._audio_load_waiting_for_preload is None
    assert submitted[-1] == (
        13,
        4,
        {"media_key": "alt_audio"},
        [4, 3],
        [4],
        prepared,
        True,
    )
    assert logs[-1][0] == "wait-fallback"

    class InlineExecutor:
        _shutdown = False

        def __init__(self) -> None:
            self.tasks = []

        def submit(self, fn, task):
            self.tasks.append((fn, task))

            class DoneFuture:
                def result(self_inner):
                    return preview._AudioPreviewTrackLoadResult(
                        request_id=task.request_id,
                        track_id=task.track_id,
                        source_key=task.source_key,
                        error="inline failed",
                    )

                def add_done_callback(self_inner, callback):
                    callback(self_inner)

                def cancel(self_inner):
                    return False

            return DoneFuture()

    emitted: list[preview._AudioPreviewTrackLoadResult] = []
    dialog._audio_preload_bridge = SimpleNamespace(
        track_ready=SimpleNamespace(emit=lambda result: emitted.append(result))
    )
    dialog._audio_load_executor = InlineExecutor()
    dialog._audio_load_jobs = {}
    dialog.wave = SimpleNamespace(width=lambda: 320)
    dialog.PRELOAD_CACHE_BUDGET_BYTES = 123
    dialog._submit_audio_track_load = preview._AudioPreviewDialog._submit_audio_track_load.__get__(
        dialog,
        preview._AudioPreviewDialog,
    )
    dialog._submit_audio_track_load(
        13,
        5,
        {"media_key": "audio_file"},
        [5, 4],
        [5],
        prepared,
        False,
    )
    assert dialog._audio_load_jobs[13][0] is not None
    assert emitted[-1].error == "inline failed"
    assert logs[-1][0] == "load-start"

    dialog._track_order_for_load_request = lambda track_id, _source: [int(track_id), 6]
    dialog._effective_track_order_for_load_request = lambda track_id, _source, base: list(
        reversed(base)
    )
    dialog._cached_prepared_media_for = lambda _track_id, _source: prepared
    dialog._apply_cached_track_preview = lambda *_args, **_kwargs: True
    dialog.open_track_preview(7, {"media_key": "audio_file"}, autoplay=True)
    assert not begin_calls

    dialog._apply_cached_track_preview = lambda *_args, **_kwargs: False
    dialog._use_inflight_preload_for_track = lambda *_args, **_kwargs: True
    dialog.open_track_preview(8, {"media_key": "audio_file"}, autoplay=False)
    assert not begin_calls

    dialog._use_inflight_preload_for_track = lambda *_args, **_kwargs: False
    dialog._cancel_audio_load_jobs = lambda *, reason: cancellations.append(reason)
    dialog._cancel_audio_preload_jobs = lambda *, reason: preload_cancellations.append(reason)
    dialog._begin_track_load = (
        lambda track_id, source_spec, base_order, effective_order: begin_calls.append(
            (int(track_id), dict(source_spec), list(base_order), list(effective_order))
        )
    )
    dialog._submit_audio_track_load = lambda request_id, track_id, source_spec, base_track_order, effective_track_order, prepared_media, autoplay: submitted.append(
        (
            int(request_id),
            int(track_id),
            dict(source_spec),
            list(base_track_order),
            list(effective_track_order),
            prepared_media,
            bool(autoplay),
        )
    )
    dialog.open_track_preview(9, {"media_key": "audio_file"}, autoplay=True)
    assert cancellations[-1] == "new-track"
    assert preload_cancellations[-1] == "active-track-load"
    assert begin_calls[-1] == (9, {"media_key": "audio_file"}, [9, 6], [6, 9])
    assert submitted[-1][:5] == (14, 9, {"media_key": "audio_file"}, [9, 6], [6, 9])

    dialog._cancel_audio_load_jobs = lambda *, reason: cancellations.append(reason)
    dialog._cancel_audio_preload_jobs = lambda *, reason: preload_cancellations.append(reason)
    dialog._evict_audio_preload_cache = lambda keep, *, reason: evictions.append(
        (set(keep), reason)
    )
    dialog.open_raw_preview(b"raw", "audio/wav", "Raw Take", autoplay=False)
    assert cancellations[-1] == "raw-preview"
    assert preload_cancellations[-1] == "raw-preview"
    assert evictions[-1] == (set(), "raw-preview")
    assert raw_states[-1] == (b"raw", "audio/wav", "Raw Take")
    assert applied[-1]["state"]["title"] == "Raw Take"


def test_audio_preview_dialog_result_cache_cleanup_and_source_loading_paths(
    monkeypatch,
    tmp_path: Path,
) -> None:
    dialog = preview._AudioPreviewDialog.__new__(preview._AudioPreviewDialog)
    logs: list[tuple[str, dict[str, object]]] = []
    criticals: list[tuple[str, str]] = []
    applied: list[dict[str, object]] = []
    waveform_loads: list[tuple[str, object | None]] = []
    positions: list[tuple[int, int]] = []
    decoded_sources: list[tuple[object, int, bool]] = []
    raw_sources: list[str] = []
    cancelled_futures: list[str] = []

    monkeypatch.setattr(
        preview.QMessageBox,
        "critical",
        lambda _parent, title, message: criticals.append((title, message)),
    )

    class FakeLabel:
        def __init__(self) -> None:
            self.text = ""
            self.visible = False

        def setText(self, text: str) -> None:
            self.text = str(text)

        def setVisible(self, visible: bool) -> None:
            self.visible = bool(visible)

    class FakeWave:
        def __init__(self) -> None:
            self.visible = True
            self.peaks: list[object] = []
            self.cached: list[object] = []

        def setVisible(self, visible: bool) -> None:
            self.visible = bool(visible)

        def set_peaks(self, peaks) -> None:
            self.peaks = list(peaks)

        def set_cached_waveform(self, peaks, **kwargs) -> None:
            self.cached.append((list(peaks), kwargs))

        def width(self) -> int:
            return 240

    class FakePeakMeter:
        def __init__(self) -> None:
            self.reset_count = 0
            self.frames: list[object] = []

        def reset_signal_activity(self) -> None:
            self.reset_count += 1

        def set_peak_frames(self, frames) -> None:
            self.frames = list(frames)

    class FakePlayer:
        def __init__(self) -> None:
            self.duration_value = 1234
            self.sources: list[object] = []

        def setDecodedSource(self, samples, sample_rate: int, *, assume_prepared: bool) -> None:
            decoded_sources.append((samples, sample_rate, assume_prepared))

        def setSource(self, source) -> None:
            self.sources.append(source)
            raw_sources.append(source.toLocalFile())

        def duration(self) -> int:
            return self.duration_value

        def stop(self) -> None:
            return None

    dialog.app = SimpleNamespace(
        _audio_preview_export_actions_for_track=lambda track_id, source_spec, **_kwargs: [
            {"text": f"Export {track_id}:{source_spec.get('media_key')}"}
        ]
    )
    dialog._source_spec = {"media_key": "audio_file"}
    dialog._current_track_id = 3
    dialog._audio_load_request_id = 31
    dialog._audio_load_jobs = {}
    dialog._audio_preload_jobs = {}
    dialog._audio_preload_cache = {}
    dialog._log_audio_preload = lambda action, **details: logs.append((action, details))
    dialog.wave = FakeWave()
    dialog.wave_status_label = FakeLabel()
    dialog.peak_meter = FakePeakMeter()
    dialog.scope = SimpleNamespace(
        set_spectrum_frames=lambda _frames: None,
        set_gain=lambda *_args, **_kwargs: None,
    )
    dialog._player = FakePlayer()
    dialog._audio_out = SimpleNamespace(stop=lambda: None)
    dialog._tmp_path = None
    dialog._source_tmp_path = None
    dialog._tmp_path_owned = False
    dialog._load_waveform = lambda path, prepared_media=None: waveform_loads.append(
        (str(path), prepared_media)
    )
    dialog._apply_position = lambda position, duration: positions.append(
        (int(position), int(duration))
    )
    dialog._apply_preview_state = lambda state, **kwargs: applied.append(
        {"state": dict(state), **kwargs}
    )

    dialog._on_audio_track_load_result(object())

    cancelled = preview._AudioPreviewTrackLoadResult(
        request_id=31,
        track_id=3,
        source_key='{"kind":"","media_key":"audio_file"}',
        cancelled=True,
    )
    dialog._audio_load_jobs[31] = (SimpleNamespace(cancel=lambda: None), threading.Event())
    dialog._on_audio_track_load_result(cancelled)
    assert logs[-1][0] == "load-cancelled"

    stale_path = tmp_path / "stale.wav"
    stale_path.write_bytes(b"stale")
    stale_prepared = _prepared_media(
        source_path=str(stale_path),
        owns_source_path=True,
        decoded_samples=SimpleNamespace(nbytes=8),
        sample_rate=44100,
    )
    stale = preview._AudioPreviewTrackLoadResult(
        request_id=30,
        track_id=3,
        source_key='{"kind":"","media_key":"audio_file"}',
        state={"prepared_media": stale_prepared},
        prepared_owned_by_result=True,
    )
    dialog._on_audio_track_load_result(stale)
    assert logs[-1][0] == "load-stale"
    assert not stale_path.exists()

    error_result = preview._AudioPreviewTrackLoadResult(
        request_id=31,
        track_id=3,
        source_key='{"kind":"","media_key":"audio_file"}',
        error="decode failed",
    )
    dialog._on_audio_track_load_result(error_result)
    assert logs[-1][0] == "load-failed"
    assert dialog.wave.visible is False
    assert dialog.wave_status_label.text == "Could not load audio"
    assert criticals[-1][0] == "Audio Player"

    no_state = preview._AudioPreviewTrackLoadResult(
        request_id=31,
        track_id=3,
        source_key='{"kind":"","media_key":"audio_file"}',
    )
    dialog._on_audio_track_load_result(no_state)
    assert logs[-1][0] == "load-failed"

    success = preview._AudioPreviewTrackLoadResult(
        request_id=31,
        track_id=3,
        source_key='{"kind":"","media_key":"audio_file"}',
        state={"title": "Loaded", "_autoplay": True},
    )
    dialog._on_audio_track_load_result(success)
    assert logs[-1][0] == "load-ready"
    assert applied[-1]["autoplay"] is True
    assert applied[-1]["state"]["export_actions"][0]["text"] == "Export 3:audio_file"

    apply_fail_path = tmp_path / "apply-fail.wav"
    apply_fail_path.write_bytes(b"apply")
    apply_fail_prepared = _prepared_media(
        source_path=str(apply_fail_path),
        owns_source_path=True,
        decoded_samples=SimpleNamespace(nbytes=8),
        sample_rate=44100,
    )
    dialog._apply_preview_state = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        RuntimeError("apply failed")
    )
    apply_fail = preview._AudioPreviewTrackLoadResult(
        request_id=31,
        track_id=3,
        source_key='{"kind":"","media_key":"audio_file"}',
        state={"title": "Broken", "prepared_media": apply_fail_prepared},
        prepared_owned_by_result=True,
    )
    dialog._on_audio_track_load_result(apply_fail)
    assert logs[-1][0] == "load-apply-failed"
    assert "apply failed" in criticals[-1][1]
    assert not apply_fail_path.exists()

    class FakeFuture:
        def __init__(self, name: str) -> None:
            self.name = name

        def cancel(self) -> None:
            cancelled_futures.append(self.name)

    keep_key = (1, "keep")
    drop_key = (2, "drop")
    drop_cancel = threading.Event()
    dialog._audio_preload_jobs = {
        keep_key: (FakeFuture("keep"), threading.Event(), 4),
        drop_key: (FakeFuture("drop"), drop_cancel, 4),
    }
    dialog._cancel_audio_preload_jobs(keep_keys={keep_key}, reason="test")
    assert keep_key in dialog._audio_preload_jobs
    assert drop_key not in dialog._audio_preload_jobs
    assert drop_cancel.is_set()
    assert cancelled_futures == ["drop"]
    assert logs[-1][0] == "cancel"

    keep_cache_path = tmp_path / "keep-cache.wav"
    drop_cache_path = tmp_path / "drop-cache.wav"
    keep_cache_path.write_bytes(b"keep")
    drop_cache_path.write_bytes(b"drop")
    keep_prepared = _prepared_media(source_path=str(keep_cache_path), owns_source_path=True)
    drop_prepared = _prepared_media(source_path=str(drop_cache_path), owns_source_path=True)
    dialog._audio_preload_cache = {keep_key: keep_prepared, drop_key: drop_prepared}
    dialog._evict_audio_preload_cache({keep_key}, reason="window")
    assert keep_key in dialog._audio_preload_cache
    assert drop_key not in dialog._audio_preload_cache
    assert not drop_cache_path.exists()
    assert logs[-1][0] == "evict"

    protected_key = (3, "protected")
    evict_key = (4, "oversize")
    protected_path = tmp_path / "protected.wav"
    evict_path = tmp_path / "oversize.wav"
    protected_path.write_bytes(b"protected")
    evict_path.write_bytes(b"oversize")
    protected = _prepared_media(
        source_path=str(protected_path),
        owns_source_path=True,
        decoded_samples=SimpleNamespace(nbytes=40),
        sample_rate=44100,
    )
    evict_me = _prepared_media(
        source_path=str(evict_path),
        owns_source_path=True,
        decoded_samples=SimpleNamespace(nbytes=80),
        sample_rate=44100,
    )
    dialog._audio_preload_cache = {protected_key: protected, evict_key: evict_me}
    dialog.PRELOAD_CACHE_BUDGET_BYTES = 32
    dialog._audio_preload_required_keys = lambda: {protected_key}
    dialog._audio_preload_window_keys = lambda: [protected_key, evict_key]
    dialog._enforce_audio_preload_budget({protected_key, evict_key})
    assert protected_key in dialog._audio_preload_cache
    assert evict_key not in dialog._audio_preload_cache
    assert not evict_path.exists()
    assert logs[-1][0] == "evict"
    assert logs[-1][1]["reason"] == "budget"

    invalid_prepared = _prepared_media(source_path=str(tmp_path / "invalid.wav"))
    try:
        dialog._load_audio_source(b"", "audio/wav", prepared_media=invalid_prepared)
    except RuntimeError as exc:
        assert "not prepared" in str(exc)
    else:  # pragma: no cover - defensive guard for this branch assertion
        raise AssertionError("expected invalid prepared media to fail")

    prepared_path = tmp_path / "decoded.wav"
    prepared_path.write_bytes(b"decoded")
    decoded_samples = SimpleNamespace(nbytes=24)
    valid_prepared = _prepared_media(
        source_path=str(prepared_path),
        owns_source_path=True,
        decoded_samples=decoded_samples,
        sample_rate=48000,
    )
    dialog._load_audio_source(b"", "audio/wav", prepared_media=valid_prepared)
    assert decoded_sources[-1] == (decoded_samples, 48000, True)
    assert valid_prepared.owns_source_path is False
    assert valid_prepared.decoded_samples is None
    assert waveform_loads[-1] == (str(prepared_path), valid_prepared)
    assert positions[-1] == (0, 1234)

    dialog._load_audio_source(b"raw-audio", "audio/ogg")
    raw_temp_path = Path(raw_sources[-1])
    try:
        assert raw_temp_path.exists()
        assert raw_temp_path.suffix == ".ogg"
        assert waveform_loads[-1] == (str(raw_temp_path), None)
    finally:
        raw_temp_path.unlink(missing_ok=True)


def test_image_preview_dialog_zoom_export_gesture_and_artwork_label_paths(
    monkeypatch,
) -> None:
    require_qapplication()
    monkeypatch.setattr(preview.platform, "system", lambda: "Linux")
    exports: list[dict[str, object]] = []
    app = SimpleNamespace(
        _detect_mime=lambda data: "image/png" if data else "",
        _sanitize_filename=lambda value: str(value).replace(" ", "_"),
        _export_bytes_with_picker=lambda data, **kwargs: exports.append({"data": data, **kwargs}),
    )
    dialog = preview._ImagePreviewDialog(app)
    try:
        image_data = _png_bytes()
        with pytest.raises(ValueError, match="decode image"):
            dialog.set_preview(b"not-an-image", "Broken")
        dialog.set_preview(image_data, " Cover Art ")
        assert dialog.windowTitle().endswith("Cover Art")
        assert dialog._current_mime == "image/png"

        assert dialog._zoom_steps_from_event(_DeltaEvent(pixel=QPoint(0, 80))) == 2
        assert dialog._zoom_steps_from_event(_DeltaEvent(pixel=QPoint(-120, 0))) == -3
        assert dialog._zoom_steps_from_event(_DeltaEvent(angle=QPoint(0, 240))) == 2
        assert dialog._zoom_steps_from_event(_DeltaEvent()) == 0

        null_dialog = preview._ImagePreviewDialog(app)
        try:
            assert null_dialog._fit_percent() == 100
            null_dialog._apply_zoom(120)
            assert null_dialog._image_label.pixmap().isNull()
            null_dialog._export_current_image()
            assert exports == []
        finally:
            null_dialog.close()
            null_dialog.deleteLater()

        dialog._current_pct = 100
        dialog._adjust_zoom_steps(0)
        assert dialog._current_pct == 100
        dialog._mark_user_zoomed()
        assert dialog._user_zoomed is True
        dialog._adjust_zoom_steps(2)
        assert dialog._current_pct == 120
        dialog._adjust_zoom_factor(0)
        assert dialog._current_pct == 120
        dialog._adjust_zoom_factor(1.5)
        assert dialog._current_pct == 180

        no_modifier = _DeltaEvent(angle=QPoint(0, 120), modifiers=Qt.NoModifier)
        assert dialog._handle_zoom_wheel_event(no_modifier) is False
        zero_wheel = _DeltaEvent(modifiers=Qt.ControlModifier)
        assert dialog._handle_zoom_wheel_event(zero_wheel) is False
        zoom_wheel = _DeltaEvent(angle=QPoint(0, -120), modifiers=Qt.ControlModifier)
        assert dialog._handle_zoom_wheel_event(zoom_wheel) is True
        assert zoom_wheel.accepted is True

        tiny_gesture = _NativeGestureEvent(Qt.ZoomNativeGesture, 0.0)
        assert dialog._handle_native_gesture_event(tiny_gesture) is False
        zoom_gesture = _NativeGestureEvent(Qt.ZoomNativeGesture, 0.1)
        assert dialog._handle_native_gesture_event(zoom_gesture) is True
        assert zoom_gesture.accepted is True
        smart_gesture = _NativeGestureEvent(Qt.SmartZoomNativeGesture)
        assert dialog._handle_native_gesture_event(smart_gesture) is True
        assert smart_gesture.accepted is True
        other_gesture = _NativeGestureEvent(None)
        assert dialog._handle_native_gesture_event(other_gesture) is False

        assert dialog._handle_pinch_gesture_event(object()) is False
        assert dialog._handle_pinch_gesture_event(_GestureEvent(None)) is False
        unchanged = _GestureEvent(_PinchGesture())
        assert dialog._handle_pinch_gesture_event(unchanged) is False
        changed = _GestureEvent(
            _PinchGesture(
                flags=QPinchGesture.ScaleFactorChanged,
                last_factor=0.0,
                scale_factor=1.25,
            )
        )
        assert dialog._handle_pinch_gesture_event(changed) is True
        assert changed.accepted is True

        filter_wheel = _DeltaEvent(angle=QPoint(0, 120), modifiers=Qt.ControlModifier)
        setattr(filter_wheel, "type", lambda: QEvent.Wheel)
        assert dialog.eventFilter(dialog._image_label, filter_wheel) is True
        assert filter_wheel.accepted is True
        filter_native = _NativeGestureEvent(Qt.ZoomNativeGesture, 0.1)
        setattr(filter_native, "type", lambda: QEvent.NativeGesture)
        assert dialog.eventFilter(dialog._image_label, filter_native) is True
        assert filter_native.accepted is True
        filter_pinch = _GestureEvent(
            _PinchGesture(
                flags=QPinchGesture.ScaleFactorChanged,
                last_factor=2.0,
                scale_factor=3.0,
            )
        )
        setattr(filter_pinch, "type", lambda: QEvent.Gesture)
        assert dialog.eventFilter(dialog._image_label, filter_pinch) is True
        assert filter_pinch.accepted is True

        double_click = SimpleNamespace(
            type=lambda: QEvent.MouseButtonDblClick,
            button=lambda: Qt.LeftButton,
            accept=lambda: setattr(double_click, "accepted", True),
            accepted=False,
        )
        assert dialog.eventFilter(dialog._image_label, double_click) is True
        assert double_click.accepted is True

        dialog._export_current_image()
        assert exports[-1]["data"] == image_data
        assert exports[-1]["mime"] == "image/png"
        assert exports[-1]["entity_id"] == "Cover_Art"

        label = preview._HiDpiArtworkLabel()
        activated: list[bool] = []
        label.artworkActivated.connect(lambda: activated.append(True))
        pixmap = QPixmap.fromImage(QImage.fromData(image_data))
        label.set_artwork_pixmap(pixmap)
        same_size = label.sizeHint()
        label.set_target_extent(same_size.width())
        label.set_target_extent(96)
        assert label.sizeHint().width() == 96
        art_event = _MouseEvent()
        label.mouseDoubleClickEvent(art_event)
        assert activated == [True]
        assert art_event.accepted is True
        assert not label.pixmap().isNull()
        label.clear()
        assert label.pixmap().isNull()
        label.deleteLater()
    finally:
        dialog.close()
        dialog.deleteLater()


def test_audio_preview_dialog_icon_menu_logging_and_selection_edge_guards(
    monkeypatch,
    tmp_path: Path,
) -> None:
    require_qapplication()
    monkeypatch.setattr(preview.platform, "system", lambda: "Windows")
    monkeypatch.setenv("PATH", "base-path")

    class RaisingLogger:
        def info(self, *_args, **_kwargs) -> None:
            raise RuntimeError("logger unavailable")

        def exception(self, *_args, **_kwargs) -> None:
            return None

    app = SimpleNamespace(
        conn=None,
        settings=SimpleNamespace(),
        logger=RaisingLogger(),
        media_player_action=SimpleNamespace(icon=lambda: QIcon()),
        _effective_theme_settings=lambda: (_ for _ in ()).throw(RuntimeError("theme failed")),
        _log_event=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("event log unavailable")
        ),
    )
    dialog = preview._AudioPreviewDialog(app)
    try:
        assert r"C:\ffmpeg\bin" in os.environ["PATH"]

        class InvalidPalette:
            def color(self, _role):
                return QColor()

        class FakePaletteButton:
            def palette(self):
                return InvalidPalette()

            def isChecked(self) -> bool:
                return False

        assert dialog._media_icon_path("missing-key") == Path()
        assert dialog._media_icon_background_color(FakePaletteButton()).isValid()
        assert dialog._media_icon_contrasting_color(None, None).isValid()
        assert dialog._media_icon("missing-key", color=None).isNull()
        fallback_button = QToolButton(dialog)
        dialog._set_icon_button_content(fallback_button, "missing-key", "Fallback")
        assert fallback_button.text() == "Fallback"
        assert fallback_button.toolButtonStyle() == Qt.ToolButtonTextOnly

        dialog._media_stage_syncing = True
        dialog._sync_media_stage_size()
        dialog._media_stage_syncing = False
        dialog.media_group = None
        dialog._sync_media_stage_size()
        dialog.media_group = SimpleNamespace(layout=lambda: None)
        dialog._sync_media_stage_size()

        dialog._log_audio_preload("ignored", track_id=3)

        guard = preview._AudioPreviewDialog.__new__(preview._AudioPreviewDialog)
        guard.app = app
        guard._source_spec = None
        guard._current_track_id = "bad"
        guard._loop_mode = preview._AudioPreviewDialog.LOOP_MODE_OFF
        guard._track_order = [1]
        guard._album_scope_menu = None
        guard._bookmark_menu = None
        guard._equalizer_settings = {"enabled": False}
        guard._current_bookmarks = []
        guard._set_icon_button_content = lambda *_args, **_kwargs: None
        guard._format_time = preview._AudioPreviewDialog._format_time
        guard._seek_to_ms = lambda _position: None
        guard._sync_bookmark_button()
        guard._rebuild_bookmark_menu()
        guard._add_bookmark_at_current_position()
        guard._remove_bookmark(1)
        guard._remove_all_bookmarks_for_current_track()
        guard._apply_stop_button_font()
        guard._sync_loop_button()
        guard._sync_shuffle_button()
        guard._sync_auto_advance_button()
        guard._sync_album_scope_button()
        guard._sync_equalizer_button()
        guard._apply_play_next_font()
        guard._set_play_next_items([])
        guard._sync_play_next_selection()
        assert guard._audio_preload_window_keys() == []
        assert guard._audio_preload_required_keys() == set()

        guard._source_spec = {"media_key": "audio_file"}
        guard._current_track_id = 1
        guard._loop_mode = preview._AudioPreviewDialog.LOOP_MODE_OFF
        guard._track_order = [1]
        assert guard._audio_preload_window_track_ids(1, radius=2) == [1]
        guard._loop_mode = preview._AudioPreviewDialog.LOOP_MODE_PLAYLIST
        guard._track_order = [1, 2]
        assert guard._audio_preload_window_track_ids(1, radius=3) == [1, 2]

        font_guard = preview._AudioPreviewDialog.__new__(preview._AudioPreviewDialog)
        font_guard.app = SimpleNamespace(
            _effective_theme_settings=lambda: {"secondary_text_font_size": "bad"}
        )
        font_guard.font = lambda: QFont()
        assert font_guard._hint_text_font().pointSize() >= 1

        titles_guard = preview._AudioPreviewDialog.__new__(preview._AudioPreviewDialog)
        titles_guard.app = SimpleNamespace(
            _audio_preview_album_titles=lambda: [],
            _audio_preview_album_track_ids=lambda *_args: (_ for _ in ()).throw(
                RuntimeError("album provider failed")
            ),
            _normalize_track_ids=lambda values: [
                int(value) for value in values if str(value).isdigit()
            ],
        )
        titles_guard._source_spec = {"media_key": "audio_file"}
        titles_guard._base_track_queue = [
            object(),
            {"album": "Album A", "track_id": "bad"},
            {"album": "Album A", "track_id": 7},
        ]
        assert titles_guard._available_album_scope_titles() == ["Album A"]
        assert titles_guard._album_track_order_for_title("Album A") == [7]

        play_guard = preview._AudioPreviewDialog.__new__(preview._AudioPreviewDialog)
        play_guard.app = SimpleNamespace()
        play_guard._current_track_id = "bad"
        play_guard._source_spec = {"media_key": "audio_file"}
        play_guard._hint_text_font = lambda: require_qapplication().font()
        play_guard.open_track_preview = lambda *_args, **_kwargs: None
        play_guard.play_next_list = QListWidget()
        try:
            play_guard._set_play_next_items(
                [
                    {"track_id": 10, "title": "   ", "label": ""},
                    {"track_id": 11, "title": "Eleven"},
                ]
            )
            assert play_guard.play_next_list.item(0).text() == "Track 10"
            assert play_guard.play_next_list.currentRow() == -1
            play_guard._current_track_id = 12
            invalid_item = QListWidgetItem("invalid")
            invalid_item.setData(Qt.UserRole, "bad")
            play_guard._play_next_item(invalid_item)
            play_guard._current_track_id = 10
            play_guard._play_next_item(play_guard.play_next_list.item(0))
        finally:
            play_guard.play_next_list.deleteLater()

        cache_guard = preview._AudioPreviewDialog.__new__(preview._AudioPreviewDialog)
        cache_guard.app = SimpleNamespace(
            _audio_preview_state_for_track=lambda *_args, **_kwargs: {
                "track_id": 3,
                "track_order": [3, 4],
                "track_queue": [],
                "effective_track_order": [3, 4],
                "effective_track_queue": [],
                "title": "Fetched",
            },
            _normalize_track_ids=lambda values: [int(value) for value in values],
            _audio_preview_export_actions_for_track=lambda *_args, **_kwargs: [],
        )
        cache_guard._prepared_media_ready_for_instant_playback = (
            lambda prepared: prepared is not None
        )
        cache_guard._cancel_audio_load_jobs = lambda *, reason: setattr(
            cache_guard,
            "_cancel_reason",
            reason,
        )
        cache_guard._audio_load_waiting_for_preload = {"key": (99, "stale")}
        cache_guard._audio_load_request_id = 0
        cache_guard._base_track_queue = []
        cache_guard._track_queue = []
        cache_guard._log_audio_preload = lambda action, **details: setattr(
            cache_guard,
            "_last_log",
            (action, details),
        )
        applied: list[dict[str, object]] = []
        cache_guard._apply_preview_state = lambda state, **kwargs: applied.append(
            {"state": dict(state), **kwargs}
        )
        prepared = _prepared_media(source_path=str(tmp_path / "cached.wav"))
        prepared.preview_state = None
        assert cache_guard._waiting_preload_for_key((3, "audio")) is None
        assert cache_guard._apply_cached_track_preview(
            3,
            {"media_key": "audio_file"},
            [3, 4],
            [3, 4],
            prepared,
            autoplay=False,
        )
        assert cache_guard._cancel_reason == "cache-hit"
        assert [item["track_id"] for item in applied[-1]["state"]["track_queue"]] == [3, 4]
        assert [item["track_id"] for item in applied[-1]["state"]["effective_track_queue"]] == [
            3,
            4,
        ]
    finally:
        dialog.close()
        dialog.deleteLater()


def test_audio_preview_dialog_preload_cache_waveform_navigation_and_cleanup_edges(
    monkeypatch,
    tmp_path: Path,
) -> None:
    require_qapplication()
    dialog = preview._AudioPreviewDialog.__new__(preview._AudioPreviewDialog)
    logs: list[tuple[str, dict[str, object]]] = []

    dialog._log_audio_preload = lambda action, **details: logs.append((action, details))
    dialog._audio_preload_jobs = {}
    dialog._audio_preload_cache = {}

    ignored_result = object()
    dialog._on_audio_preload_result(ignored_result)
    assert logs == []

    preload_path = tmp_path / "preload-result.wav"
    preload_path.write_bytes(b"audio")
    prepared = _prepared_media(source_path=str(preload_path), owns_source_path=True)
    key = (3, "track:3:audio")
    dialog._audio_preload_jobs[key] = (object(), threading.Event(), 4)
    dialog._on_audio_preload_result(
        preview._AudioPreviewPreloadResult(
            generation=4,
            track_id=3,
            source_key="track:3:audio",
            prepared=prepared,
        )
    )
    assert key not in dialog._audio_preload_jobs
    assert not preload_path.exists()
    assert logs[-1][0] == "ignored"

    dialog._dispose_track_load_result_media(
        preview._AudioPreviewTrackLoadResult(
            request_id=1,
            track_id=3,
            source_key="track:3:audio",
            state={},
            prepared_owned_by_result=False,
        )
    )
    dialog._dispose_track_load_result_media(
        preview._AudioPreviewTrackLoadResult(
            request_id=1,
            track_id=3,
            source_key="track:3:audio",
            state={"prepared_media": object()},
            prepared_owned_by_result=True,
        )
    )
    cached_path = tmp_path / "cached-owned.wav"
    cached_path.write_bytes(b"audio")
    cached_prepared = _prepared_media(source_path=str(cached_path), owns_source_path=True)
    dialog._audio_preload_cache[(3, "track:3:audio")] = cached_prepared
    dialog._dispose_track_load_result_media(
        preview._AudioPreviewTrackLoadResult(
            request_id=1,
            track_id=3,
            source_key="track:3:audio",
            state={"prepared_media": cached_prepared},
            prepared_owned_by_result=True,
        )
    )
    assert cached_path.exists()

    bridge_dispose_path = tmp_path / "bridge-dispose.wav"
    bridge_dispose_path.write_bytes(b"audio")
    bridge_prepared = _prepared_media(
        source_path=str(bridge_dispose_path),
        owns_source_path=True,
    )

    class ImmediateFuture:
        def result(self):
            return preview._AudioPreviewTrackLoadResult(
                request_id=9,
                track_id=3,
                source_key='{"kind":"","media_key":"audio_file"}',
                state={"prepared_media": bridge_prepared},
                prepared_owned_by_result=True,
            )

        def add_done_callback(self, callback) -> None:
            callback(self)

        def cancel(self) -> bool:
            return False

    class ImmediateExecutor:
        _shutdown = False

        def submit(self, _fn, _task):
            return ImmediateFuture()

    dialog.app = SimpleNamespace(current_db_path="", data_root="")
    dialog.wave = SimpleNamespace(width=lambda: 480)
    dialog.PRELOAD_CACHE_BUDGET_BYTES = 1024
    dialog._audio_load_executor = ImmediateExecutor()
    dialog._audio_load_jobs = {}
    dialog._audio_preload_bridge = SimpleNamespace(
        track_ready=SimpleNamespace(
            emit=lambda _result: (_ for _ in ()).throw(RuntimeError("bridge closed"))
        )
    )
    dialog._submit_audio_track_load(
        9,
        3,
        {"media_key": "audio_file"},
        [3],
        [3],
        None,
        False,
    )
    assert not bridge_dispose_path.exists()

    monkeypatch.setattr(preview.os, "remove", lambda _path: (_ for _ in ()).throw(OSError("busy")))
    preview._AudioPreviewDialog._remove_temp_path("")
    preview._AudioPreviewDialog._remove_temp_path(str(tmp_path / "missing.wav"))
    preview._AudioPreviewDialog._remove_temp_path(str(tmp_path / "locked.wav"))

    class FakeWave:
        def __init__(self) -> None:
            self.cached: list[tuple[list[object], dict[str, object]]] = []
            self.peaks: list[object] = []
            self.visible: bool | None = None

        def width(self) -> int:
            return 120

        def set_cached_waveform(self, peaks, **kwargs) -> None:
            self.cached.append((list(peaks), dict(kwargs)))

        def set_peaks(self, peaks) -> None:
            self.peaks = list(peaks)

        def setVisible(self, visible: bool) -> None:
            self.visible = bool(visible)

    class FakeLabel:
        def __init__(self) -> None:
            self.text = ""
            self.visible: bool | None = None

        def setText(self, text: str) -> None:
            self.text = str(text)

        def setVisible(self, visible: bool) -> None:
            self.visible = bool(visible)

    dialog.app = SimpleNamespace(
        _audio_waveform_cache_for_track=lambda _track_id: SimpleNamespace(
            peaks=[],
            light_preview_png=b"light",
            dark_preview_png=b"dark",
            source_fingerprint="cache-key",
        )
    )
    dialog._source_spec = {"kind": "standard", "media_key": "audio_file"}
    dialog._current_track_id = 3
    dialog.wave = FakeWave()
    dialog.wave_status_label = FakeLabel()
    dialog.scope = SimpleNamespace(
        spectrum=[],
        set_spectrum_frames=lambda frames: dialog.scope.spectrum.append(list(frames)),
    )
    dialog.peak_meter = SimpleNamespace(
        peaks=[],
        set_peak_frames=lambda frames: dialog.peak_meter.peaks.append(list(frames)),
    )
    dialog._start_scope_visualization_if_playing = lambda: logs.append(("scope-start", {}))
    monkeypatch.setattr(preview, "load_audio_spectrum_frames", lambda _path: [[0.1, 0.2]])
    monkeypatch.setattr(preview, "load_audio_peak_meter_frames", lambda _path: [(-6.0, -2.0)])
    dialog._load_waveform(str(tmp_path / "cached.wav"))
    assert dialog.wave.cached[-1][1]["cache_key"] == "cache-key"
    assert dialog.wave_status_label.text == "Waveform unavailable"
    assert dialog.scope.spectrum[-1] == [[0.1, 0.2]]
    assert dialog.peak_meter.peaks[-1] == [(-6.0, -2.0)]

    dialog.export_menu = QMenu()
    dialog.export_button = QToolButton()
    enabled: list[bool] = []
    try:
        dialog._set_media_button_enabled = lambda _button, active: enabled.append(bool(active))
        handler_calls: list[str] = []
        dialog._set_export_actions(
            [
                {"text": "", "handler": lambda: handler_calls.append("empty")},
                {"text": "Broken", "handler": object()},
                {"text": "Export", "handler": lambda: handler_calls.append("export")},
            ]
        )
        assert [action.text() for action in dialog.export_menu.actions()] == ["Export"]
        assert enabled[-1] is True

        artwork_opened: list[tuple[bytes, str]] = []
        dialog._current_artwork_data = b""
        dialog._current_title = "Track"
        dialog.app = SimpleNamespace(
            _open_image_preview=lambda data, title: artwork_opened.append((data, title))
        )
        dialog._open_artwork_preview()
        assert artwork_opened == []
        dialog._current_artwork_data = b"image"
        dialog._open_artwork_preview()
        assert artwork_opened == [(b"image", "Track")]
    finally:
        dialog.export_menu.deleteLater()
        dialog.export_button.deleteLater()

    shuffle_dialog = preview._AudioPreviewDialog.__new__(preview._AudioPreviewDialog)
    monkeypatch.setattr(preview.random, "shuffle", lambda values: values.reverse())
    assert shuffle_dialog._create_shuffled_track_order(["bad", 1, 1, 2], 1) == [1, 2]
    assert shuffle_dialog._create_shuffled_track_order([2, 3], 1) == [3, 2]
    shuffle_dialog._shuffled_track_order = ["bad", 2, 1]
    assert shuffle_dialog._shuffle_order_for_base_track_order([1, 2]) == [2, 1]
    shuffle_dialog._current_track_id = 1
    assert shuffle_dialog._shuffle_order_for_base_track_order([1, 3]) == [1, 3]
    shuffle_dialog._shuffle_enabled = True
    shuffle_dialog._effective_base_track_order = lambda: [1, 2]
    shuffle_dialog._ordered_track_queue_items = lambda order: [
        {"track_id": track_id} for track_id in order
    ]
    play_next_updates: list[list[dict[str, object]]] = []
    shuffle_dialog._set_play_next_items = lambda items: play_next_updates.append(list(items))
    shuffle_dialog._sync_album_scope_button = lambda: None
    shuffle_dialog._apply_effective_track_order()
    assert [item["track_id"] for item in play_next_updates[-1]] == [1, 2]

    nav_dialog = preview._AudioPreviewDialog.__new__(preview._AudioPreviewDialog)
    opened: list[tuple[int, dict[str, object], bool]] = []
    nav_dialog._source_spec = None
    nav_dialog._current_track_id = 1
    nav_dialog._track_order = [1, 2]
    nav_dialog.open_track_preview = lambda track_id, source_spec, *, autoplay: opened.append(
        (int(track_id), dict(source_spec), bool(autoplay))
    )
    assert nav_dialog._navigate_relative(1, autoplay=True) is False
    nav_dialog._source_spec = {"media_key": "audio_file"}
    nav_dialog._current_track_id = 99
    assert nav_dialog._navigate_relative(1, autoplay=True) is False
    nav_dialog._current_track_id = 1
    assert nav_dialog._navigate_relative(0, autoplay=True) is False
    assert nav_dialog._navigate_relative(-1, autoplay=True) is False
    assert nav_dialog._navigate_relative(1, autoplay=True) is True
    assert opened[-1] == (2, {"media_key": "audio_file"}, True)
    assert preview._AudioPreviewDialog._format_time(3_661_000) == "1:01:01"

    media_dialog = preview._AudioPreviewDialog.__new__(preview._AudioPreviewDialog)
    media_dialog._handling_end_of_media = True
    media_dialog._on_media_status_changed(
        getattr(preview.QMediaPlayer, "MediaStatus", preview.QMediaPlayer).EndOfMedia
    )
    media_dialog._handling_end_of_media = False
    media_dialog._loop_mode = preview._AudioPreviewDialog.LOOP_MODE_PLAYLIST
    media_dialog._player = SimpleNamespace(
        duration=lambda: 9_000, play=lambda: logs.append(("play", {}))
    )
    media_dialog._apply_position = lambda position, duration: logs.append(
        ("position", {"position": position, "duration": duration})
    )
    media_dialog._navigate_relative = lambda *_args, **_kwargs: False
    media_dialog._restart_current_media = lambda: logs.append(("restart", {}))
    media_dialog._auto_advance_enabled = lambda: False
    media_dialog._ensure_visualization_release_running = lambda: logs.append(("release", {}))
    media_dialog._on_media_status_changed(
        getattr(preview.QMediaPlayer, "MediaStatus", preview.QMediaPlayer).EndOfMedia
    )
    assert logs[-1][0] == "restart"

    reset_dialog = preview._AudioPreviewDialog.__new__(preview._AudioPreviewDialog)
    reset_dialog._player = SimpleNamespace(
        stop=lambda: (_ for _ in ()).throw(RuntimeError("stop failed")),
        setSource=lambda _source: (_ for _ in ()).throw(RuntimeError("source failed")),
    )
    reset_dialog._audio_out = SimpleNamespace(
        stop=lambda: (_ for _ in ()).throw(RuntimeError("audio out failed"))
    )
    reset_dialog._reset_player_source()


def test_audio_preview_dialog_buttons_album_equalizer_bookmarks_and_play_next(
    monkeypatch,
) -> None:
    require_qapplication()
    dialog = preview._AudioPreviewDialog.__new__(preview._AudioPreviewDialog)
    conn = sqlite3.connect(":memory:")
    icon_calls: list[tuple[QToolButton, str, str, bool]] = []
    preload_refreshes: list[str] = []
    navigation_updates: list[str] = []
    opened_tracks: list[tuple[int, dict[str, object], bool]] = []

    dialog.app = SimpleNamespace(
        conn=conn,
        settings=SimpleNamespace(),
        logger=SimpleNamespace(exception=lambda *_args, **_kwargs: None),
        _audio_preview_album_titles=lambda: [" Album B ", "album a", "Album B", ""],
        _audio_preview_album_track_ids=lambda title, _source: (
            [5, "6", 5]
            if title == "Album B"
            else (_ for _ in ()).throw(RuntimeError("provider failed"))
        ),
        _normalize_track_ids=lambda values: list(
            dict.fromkeys(int(value) for value in values if str(value).isdigit())
        ),
    )
    dialog._set_icon_button_content = (
        lambda button, icon_key, fallback_text, *, inactive=False: icon_calls.append(
            (button, icon_key, fallback_text, bool(inactive))
        )
    )
    dialog._refresh_audio_preload_window_if_ready = lambda: preload_refreshes.append("refresh")
    dialog._update_navigation_buttons = lambda: navigation_updates.append("nav")
    dialog._apply_effective_track_order = lambda: setattr(
        dialog,
        "_track_order",
        dialog._effective_base_track_order(),
    )
    dialog.open_track_preview = lambda track_id, source_spec, *, autoplay: opened_tracks.append(
        (int(track_id), dict(source_spec), bool(autoplay))
    )
    dialog._source_spec = {"media_key": "audio_file"}
    dialog._base_track_order = [1, 2, 3]
    dialog._track_order = [1, 2, 3]
    dialog._base_track_queue = [
        {"track_id": 1, "album": "Album A", "title": "One"},
        {"track_id": 2, "album": "album a", "title": "Two"},
        {"track_id": "bad", "album": "Album B"},
        {"track_id": 3, "album": "Album B", "title": "Three"},
    ]
    dialog._track_queue = list(dialog._base_track_queue)
    dialog._current_track_id = "2"
    dialog._loop_mode = "mystery"
    dialog._shuffle_enabled = False
    dialog._album_scope_title = None
    dialog._album_scope_menu = QMenu()
    dialog._equalizer_settings = {"enabled": False}
    dialog._equalizer_dialog = None
    dialog._current_bookmarks = []
    dialog._bookmark_menu = QMenu()
    dialog._seek_to_ms = lambda position: setattr(dialog, "_last_seek", int(position))
    dialog._format_time = preview._AudioPreviewDialog._format_time
    dialog._hint_text_font = lambda: require_qapplication().font()
    dialog.play_next_list = QListWidget()

    try:
        loop_button = QToolButton()
        dialog.loop_button = loop_button
        dialog._set_loop_mode("bad-mode")
        assert dialog._loop_mode == dialog.LOOP_MODE_OFF
        assert loop_button.property("loopMode") == dialog.LOOP_MODE_OFF
        assert icon_calls[-1][1:] == ("repeat", "R", True)
        dialog._cycle_loop_mode()
        assert dialog._loop_mode == dialog.LOOP_MODE_PLAYLIST
        dialog._cycle_loop_mode()
        assert dialog._loop_mode == dialog.LOOP_MODE_TRACK

        shuffle_button = QToolButton()
        dialog.shuffle_button = shuffle_button
        dialog._sync_shuffle_button()
        assert shuffle_button.property("shuffleEnabled") is False
        dialog._shuffle_enabled = True
        dialog._sync_shuffle_button(shuffle_button)
        assert shuffle_button.property("shuffleEnabled") is True

        auto_button = QToolButton()
        auto_button.setCheckable(True)
        dialog.auto_advance_button = auto_button
        assert dialog._auto_advance_enabled() is False
        auto_button.setChecked(True)
        dialog._sync_auto_advance_button()
        assert auto_button.property("autoAdvanceEnabled") is True
        no_auto = preview._AudioPreviewDialog.__new__(preview._AudioPreviewDialog)
        assert no_auto._auto_advance_enabled() is True

        assert dialog._available_album_scope_titles() == ["album a", "Album B"]
        dialog.app._audio_preview_album_titles = lambda: (_ for _ in ()).throw(
            RuntimeError("albums failed")
        )
        assert dialog._available_album_scope_titles() == ["Album A", "Album B"]
        assert dialog._album_track_order_for_title("Album B") == [5, 6]
        assert dialog._album_track_order_for_title("Album A") == [1, 2]
        assert dialog._album_track_order_for_title("") == []

        album_button = QToolButton()
        dialog.album_scope_button = album_button
        dialog._set_album_scope_title("Album B")
        assert dialog._album_scope_title == "Album B"
        assert opened_tracks[-1] == (5, {"media_key": "audio_file"}, False)
        assert album_button.property("albumScopeTitle") == "Album B"
        dialog._rebuild_album_scope_menu()
        assert [
            action.text() for action in dialog._album_scope_menu.actions() if action.text()
        ] == [
            "Off",
            "Album A",
            "Album B",
        ]
        dialog._set_album_scope_title(None)
        assert dialog._effective_base_track_order() == [1, 2, 3]

        class FakeSignal:
            def __init__(self) -> None:
                self.callbacks = []

            def connect(self, callback) -> None:
                self.callbacks.append(callback)

        class FakeEqualizerDialog:
            def __init__(self, settings, parent=None) -> None:
                self.settings = dict(settings)
                self.parent = parent
                self.settingsChanged = FakeSignal()
                self.spectra: list[object] = []
                self.events: list[str] = []

            def set_settings(self, settings) -> None:
                self.settings = dict(settings)

            def set_playback_spectrum(self, spectrum) -> None:
                self.spectra.append(spectrum)

            def show(self) -> None:
                self.events.append("show")

            def raise_(self) -> None:
                self.events.append("raise")

            def activateWindow(self) -> None:
                self.events.append("activate")

        monkeypatch.setattr(preview, "EqualizerDialog", FakeEqualizerDialog)
        dialog.scope = SimpleNamespace(
            settings=[],
            set_equalizer_settings=lambda settings: dialog.scope.settings.append(dict(settings)),
        )
        dialog._player = SimpleNamespace(
            equalizer=[],
            set_equalizer_settings=lambda settings: dialog._player.equalizer.append(dict(settings)),
            spectrumFrameChanged=FakeSignal(),
        )
        eq_button = QToolButton()
        dialog.equalizer_button = eq_button
        dialog._set_equalizer_settings({"enabled": True, "preamp_db": 2}, persist=True)
        assert dialog._player.equalizer[-1]["enabled"] is True
        assert dialog.scope.settings[-1]["enabled"] is True
        dialog._open_equalizer_dialog()
        assert isinstance(dialog._equalizer_dialog, FakeEqualizerDialog)
        assert dialog._equalizer_dialog.events == ["show", "raise", "activate"]
        dialog._open_equalizer_dialog()
        assert dialog._equalizer_dialog.events[-3:] == ["show", "raise", "activate"]
        dialog._set_equalizer_settings({"enabled": False}, persist=False)
        assert dialog._equalizer_dialog.settings["enabled"] is False

        dialog._player = SimpleNamespace(
            duration=lambda: "bad",
            position=lambda: "also-bad",
        )
        dialog._slider = SimpleNamespace(maximum=lambda: 12_000, value=lambda: 15_000)
        assert dialog._bookmark_duration_ms() == 12_000
        assert dialog._bookmark_position_ms() == 12_000
        assert (
            dialog._bookmark_label(AudioBookmark(1, 2, 61_000, "Chorus", "created", "updated"))
            == "1:01 - Chorus"
        )
        assert (
            dialog._bookmark_label(AudioBookmark(2, 2, 3_000, "", "created", "updated")) == "0:03"
        )

        bookmark_button = QToolButton()
        dialog.bookmark_button = bookmark_button
        dialog._current_bookmarks = [AudioBookmark(1, 2, 1_000, "A", "c", "u")]
        dialog._sync_bookmark_button()
        assert bookmark_button.isEnabled() is True
        assert "1 saved bookmark" in bookmark_button.toolTip()
        dialog.app.conn = object()
        dialog._sync_bookmark_button()
        assert bookmark_button.isEnabled() is False
        dialog.app.conn = conn

        wave_marks: list[list[int]] = []
        dialog.wave = SimpleNamespace(set_bookmarks_ms=lambda marks: wave_marks.append(list(marks)))
        monkeypatch.setattr(
            preview,
            "load_audio_bookmarks",
            lambda _conn, _track_id: [
                AudioBookmark(3, 2, 2_000, "B", "c", "u"),
            ],
        )
        dialog._reload_current_bookmarks()
        assert [bookmark.id for bookmark in dialog._current_bookmarks] == [3]
        assert wave_marks[-1] == [2_000]
        monkeypatch.setattr(
            preview,
            "load_audio_bookmarks",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("load failed")),
        )
        dialog._reload_current_bookmarks()
        assert dialog._current_bookmarks == []

        dialog._current_bookmarks = [
            AudioBookmark(3, 2, 2_000, "B", "c", "u"),
            AudioBookmark(4, 2, 4_000, "", "c", "u"),
        ]
        dialog._rebuild_bookmark_menu()
        menu_texts = [
            action.text()
            for action in dialog._bookmark_menu.actions()
            if action.text() and not action.menu()
        ]
        assert any(text.startswith("Add Bookmark") for text in menu_texts)
        assert "0:02 - B" in menu_texts
        assert "0:04" in menu_texts
        assert "Remove All Bookmarks" in menu_texts

        warnings: list[tuple[str, str]] = []
        monkeypatch.setattr(
            preview.QMessageBox,
            "warning",
            lambda _parent, title, message: warnings.append((title, message)),
        )
        added = AudioBookmark(5, 2, 5_000, "", "c", "u")
        monkeypatch.setattr(preview, "add_audio_bookmark", lambda *_args, **_kwargs: added)
        dialog._reload_current_bookmarks = lambda: setattr(dialog, "_reloaded", True)
        dialog._add_bookmark_at_current_position()
        assert dialog._last_seek == 5_000
        monkeypatch.setattr(
            preview,
            "add_audio_bookmark",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("save failed")),
        )
        dialog._add_bookmark_at_current_position()
        assert warnings[-1][0] == "Bookmark"
        assert "save failed" in warnings[-1][1]

        monkeypatch.setattr(preview, "delete_audio_bookmark", lambda *_args, **_kwargs: None)
        dialog._remove_bookmark(3)
        monkeypatch.setattr(
            preview,
            "delete_audio_bookmark",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("remove failed")),
        )
        dialog._remove_bookmark(3)
        assert "remove failed" in warnings[-1][1]
        monkeypatch.setattr(
            preview,
            "delete_audio_bookmarks_for_track",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("clear failed")),
        )
        dialog._remove_all_bookmarks_for_current_track()
        assert "clear failed" in warnings[-1][1]

        dialog._current_track_id = None
        dialog._set_play_next_items([])
        assert dialog.play_next_list.count() == 1
        assert dialog.play_next_list.item(0).text() == "No playable tracks"
        dialog._current_track_id = 8
        dialog._set_play_next_items(
            [
                {"track_id": "bad", "label": "ignored"},
                {"track_id": 8, "title": "", "label": ""},
                {"track_id": 9, "title": "Nine", "label": "N"},
            ]
        )
        assert dialog.play_next_list.count() == 2
        assert dialog.play_next_list.currentItem().data(Qt.UserRole) == 8
        dialog._source_spec = None
        dialog._play_next_item(dialog.play_next_list.item(1))
        assert opened_tracks[-1][0] == 5
        dialog._source_spec = {"media_key": "audio_file"}
        dialog._play_next_item(None)
        dialog._play_next_item(dialog.play_next_list.item(0))
        assert opened_tracks[-1][0] == 5
        dialog._play_next_item(dialog.play_next_list.item(1))
        assert opened_tracks[-1] == (9, {"media_key": "audio_file"}, True)
    finally:
        conn.close()
        dialog._album_scope_menu.deleteLater()
        dialog._bookmark_menu.deleteLater()
        dialog.play_next_list.deleteLater()

from __future__ import annotations

import math
import sqlite3
import struct
import wave
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter

from isrc_manager.media import waveform_cache
from isrc_manager.media.audio_visualization import (
    SpectrumGraphWidget,
    StereoPeakMeterWidget,
    load_audio_harmonic_frames,
    load_audio_peak_meter_frames,
    load_audio_spectrum_frames,
)
from isrc_manager.media.waveform import WaveformWidget, load_wav_peaks
from isrc_manager.media.waveform_cache import AudioWaveformCacheService
from tests.qt_test_helpers import require_qapplication


def _write_stereo_wav(
    path: Path, frames: list[tuple[int, int]], *, sample_rate: int = 22050
) -> None:
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(2)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        payload = b"".join(struct.pack("<hh", left, right) for left, right in frames)
        wav_file.writeframes(payload)


def _tone_frames(
    *,
    sample_rate: int = 22050,
    duration_seconds: float = 0.18,
    frequency: float = 440.0,
) -> list[tuple[int, int]]:
    frame_count = int(sample_rate * duration_seconds)
    frames: list[tuple[int, int]] = []
    for index in range(frame_count):
        sample = int(math.sin((2.0 * math.pi * frequency * index) / sample_rate) * 18000)
        frames.append((sample, -sample // 2))
    return frames


def _png_bytes(color: QColor) -> bytes:
    image = QImage(3, 3, QImage.Format.Format_ARGB32)
    image.fill(color)
    payload = QByteArray()
    buffer = QBuffer(payload)
    assert buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    assert image.save(buffer, "PNG")
    return bytes(payload)


class _PointDelta:
    def __init__(self, x_value: int = 0, y_value: int = 0) -> None:
        self._x = x_value
        self._y = y_value

    def x(self) -> int:
        return self._x

    def y(self) -> int:
        return self._y

    def isNull(self) -> bool:
        return self._x == 0 and self._y == 0


class _MouseLikeEvent:
    def __init__(
        self,
        *,
        x_value: float,
        button=Qt.MouseButton.LeftButton,
        buttons=Qt.MouseButton.LeftButton,
    ) -> None:
        self._position = QPointF(x_value, 0.0)
        self._button = button
        self._buttons = buttons
        self.accepted = False
        self.ignored = False

    def position(self) -> QPointF:
        return self._position

    def button(self):
        return self._button

    def buttons(self):
        return self._buttons

    def accept(self) -> None:
        self.accepted = True

    def ignore(self) -> None:
        self.ignored = True


class _WheelLikeEvent:
    def __init__(self, *, pixel_delta: int = 0, angle_delta: int = 0) -> None:
        self._pixel_delta = _PointDelta(0, pixel_delta)
        self._angle_delta = _PointDelta(0, angle_delta)
        self.accepted = False

    def pixelDelta(self) -> _PointDelta:
        return self._pixel_delta

    def angleDelta(self) -> _PointDelta:
        return self._angle_delta

    def accept(self) -> None:
        self.accepted = True


def _connect_int_signal(signal):
    values: list[int] = []
    signal.connect(lambda value: values.append(int(value)))
    return values


def test_waveform_widget_state_math_cached_images_and_events() -> None:
    require_qapplication()
    widget = WaveformWidget()
    widget.resize(121, 48)
    widget.set_preferred_height(72)

    assert widget.sizeHint().height() == 72
    assert widget.minimumSizeHint().height() >= 24

    widget.set_duration_ms(1000)
    widget.set_playhead_ms(1500)
    assert widget._duration == 1000
    assert widget._playhead == 1000
    assert widget._position_from_x(0) == 0
    assert 490 <= widget._position_from_x(widget.width() / 2.0) <= 510
    assert widget._playhead_x_for_ms(500) in {60, 61}

    seek_values = _connect_int_signal(widget.seekRequested)
    scrub_values = _connect_int_signal(widget.scrubRequested)
    press_event = _MouseLikeEvent(x_value=widget.width() / 4.0)
    widget.mousePressEvent(press_event)
    assert press_event.accepted is True
    assert seek_values and 240 <= seek_values[-1] <= 260

    move_event = _MouseLikeEvent(x_value=widget.width() * 0.75)
    widget.mouseMoveEvent(move_event)
    assert move_event.accepted is True
    assert scrub_values == []

    wheel_event = _WheelLikeEvent(pixel_delta=8)
    widget.set_playhead_ms(500)
    widget.wheelEvent(wheel_event)
    assert wheel_event.accepted is True
    assert seek_values[-1] != 500

    peaks = [(-0.1, 0.2), (-0.8, 0.6), (0.0, 0.0)]
    widget.set_peaks(peaks)
    assert widget._peaks == peaks
    assert widget._peaks_version >= 1
    widget.set_cached_waveform(
        peaks,
        light_preview_png=_png_bytes(QColor("#ffffff")),
        dark_preview_png=_png_bytes(QColor("#101010")),
        cache_key=("track", 1),
    )
    assert widget._stored_waveform_cache_key == ("track", 1)
    assert widget._stored_waveform_pixmap() is not None

    widget.set_bookmarks_ms([500, "120", 120, 900.9])
    assert widget._bookmarks_ms == [120, 500, 900]
    widget.set_harmonic_frames([[1.2, -0.5, 0.25], [0.0, 0.75, 2.0]])
    widget.set_playhead_ms(500)
    assert widget.has_live_visualization() is True
    assert widget._harmonic_frame_position() == pytest.approx(0.5)
    assert widget._harmonic_frame_at_position(0.5) == pytest.approx([0.5, 0.375, 0.625])
    assert widget._current_harmonic_frame() == pytest.approx([0.5, 0.375, 0.625])

    rendered = widget._static_waveform_pixmap(widget._waveform_rect(widget.rect()))
    assert not rendered.isNull()
    assert widget._static_waveform_pixmap(widget._waveform_rect(widget.rect())).cacheKey() == (
        rendered.cacheKey()
    )


def test_waveform_widget_color_and_trace_helpers_cover_edge_branches() -> None:
    require_qapplication()
    widget = WaveformWidget()
    widget.resize(80, 32)

    assert widget._fallback_waveform_rgb_for_peak(-1.0) == widget._fallback_waveform_rgb_for_peak(
        0.0
    )
    assert widget._fallback_waveform_rgb_for_peak(0.9) != widget._fallback_waveform_rgb_for_peak(
        0.1
    )
    assert widget._harmonic_frame_energy([]) == 0.0
    assert widget._harmonic_frame_energy([2.0, -1.0, 0.5]) > 0.0

    points, intensities = widget._harmonic_trace_points(
        [1.0, 0.5, 0.25],
        QRectF(0.0, 0.0, 16.0, 12.0),
        phase_offset=0.2,
        amplitude_scale=0.8,
    )
    assert len(points) == 16
    assert len(intensities) == 16
    assert all(0.0 <= value <= 1.0 for value in intensities)

    image = QImage(20, 20, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    try:
        widget._draw_harmonic_trace(
            painter,
            points[:3],
            intensities[:3],
            light_mode=False,
            alpha_scale=0.5,
            width_scale=0.75,
        )
        widget._draw_harmonic_trace(
            painter, [], [], light_mode=True, alpha_scale=1.0, width_scale=1.0
        )
    finally:
        painter.end()


def test_load_wav_peaks_handles_pcm_widths_and_invalid_files(tmp_path: Path) -> None:
    wav_path = tmp_path / "tone.wav"
    _write_stereo_wav(
        wav_path,
        [(0, 0), (12000, -6000), (-20000, 16000), (32767, -32768)],
        sample_rate=8000,
    )

    peaks = load_wav_peaks(str(wav_path), 2)
    assert peaks
    assert all(-1.0 <= low <= 0.0 and 0.0 <= high <= 1.0 for low, high in peaks)
    assert max(high for _low, high in peaks) > 0.6
    assert min(low for low, _high in peaks) < -0.4

    invalid = tmp_path / "not-a-wave.bin"
    invalid.write_bytes(b"not wave data")
    assert load_wav_peaks(str(invalid), 10) in ([], [(-0.0, 0.0)])


def test_stereo_peak_meter_state_machine_and_formatting() -> None:
    require_qapplication()
    meter = StereoPeakMeterWidget()
    meter.resize(60, 32)
    meter.setBarHeight(20)
    assert meter.height() >= 20

    meter.set_peak_frames([(-80.0, 8.0), (-18.5, -6.25)])
    assert meter._frames[0] == (
        StereoPeakMeterWidget.DB_FLOOR,
        StereoPeakMeterWidget.DB_TOP,
    )
    meter.set_duration_ms(1000)
    meter.set_playhead_ms(1000)
    assert meter._frame_at_playhead() == pytest.approx((-18.5, -6.25))
    assert meter._db_to_ratio(StereoPeakMeterWidget.DB_FLOOR) == 0.0
    assert meter._db_to_ratio(StereoPeakMeterWidget.DB_TOP) == 1.0
    assert meter._format_db(StereoPeakMeterWidget.DB_FLOOR) == "-inf"
    assert meter._format_compact_db(-12.34) == "-12.3"

    meter.mark_signal_activity()
    assert meter._signal_active is True
    assert meter._live_peak_db() > StereoPeakMeterWidget.DB_FLOOR
    meter.set_gain(0.25)
    meter.begin_release()
    assert meter.is_releasing() is True
    assert meter.advance_release(1) is True
    assert meter.advance_release(StereoPeakMeterWidget.RELEASE_MS * 2) is False

    left_rect, right_rect = meter._bar_rects()
    assert left_rect.width() == right_rect.width()
    assert meter._meter_gradient(left_rect).stops()


def test_spectrum_graph_frequency_scale_fade_release_and_segments() -> None:
    require_qapplication()
    graph = SpectrumGraphWidget()
    graph.resize(100, 40)

    graph.set_peaks([(-0.5, 0.5)])
    assert graph._peaks == []
    graph.set_spectrum_frames([[0.0, 0.5, 1.5], [1.0, 0.25, 0.0]])
    assert graph.has_live_visualization() is True
    graph.set_frequency_scale("log")
    assert graph.frequency_scale() == SpectrumGraphWidget.SPECTRUM_SCALE_LOG
    assert len(graph._log_scaled_spectrum_values([0.0, 0.25, 0.5, 1.0])) == 4
    assert len(graph._spectrum_display_values([0.0, 0.5, 2.0])) == 3
    segments = graph._spectrum_line_segments([0.0, 0.5, 1.0], QRectF(0, 0, 30, 12))
    assert len(segments) == 3
    assert segments[-1][1] < segments[-1][2]

    graph.set_frequency_scale("unknown")
    assert graph.frequency_scale() == SpectrumGraphWidget.SPECTRUM_SCALE_LINEAR
    graph.set_gain(1.0)
    graph.start_fade_in()
    assert graph._fade_opacity >= 0.72
    graph._fade_timer.stop()
    graph._advance_fade_in()
    assert graph._fade_opacity > 0.0
    graph.start_release()
    assert graph.is_releasing() is True
    assert graph.advance_release(1) is True
    graph.set_gain(1.0, cancel_release=True)
    assert graph.is_releasing() is False
    graph.start_release()
    assert graph.advance_release(SpectrumGraphWidget.SPECTRUM_RELEASE_MS * 2) is False

    ignored = _MouseLikeEvent(x_value=1)
    graph.mousePressEvent(ignored)
    graph.mouseMoveEvent(ignored)
    graph.wheelEvent(ignored)
    assert ignored.ignored is True


def test_audio_visualization_loaders_extract_frames_from_wav(tmp_path: Path) -> None:
    wav_path = tmp_path / "tone.wav"
    _write_stereo_wav(wav_path, _tone_frames(), sample_rate=22050)

    peak_frames = load_audio_peak_meter_frames(str(wav_path), target_sr=11025)
    assert peak_frames
    assert all(
        StereoPeakMeterWidget.DB_FLOOR <= left <= StereoPeakMeterWidget.DB_TOP
        and StereoPeakMeterWidget.DB_FLOOR <= right <= StereoPeakMeterWidget.DB_TOP
        for left, right in peak_frames
    )

    harmonic_frames = load_audio_harmonic_frames(str(wav_path), target_sr=11025)
    assert harmonic_frames
    assert all(0.0 <= value <= 1.0 for frame in harmonic_frames for value in frame)

    spectrum_frames = load_audio_spectrum_frames(str(wav_path), target_sr=11025, bin_count=12)
    assert spectrum_frames
    assert len(spectrum_frames[0]) == 48
    assert all(0.0 <= value <= 1.0 for frame in spectrum_frames for value in frame)

    missing_path = tmp_path / "missing.wav"
    assert load_audio_peak_meter_frames(str(missing_path)) == []
    assert load_audio_harmonic_frames(str(missing_path)) == []
    assert load_audio_spectrum_frames(str(missing_path)) == []


def _new_cache_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE Tracks(
            id INTEGER PRIMARY KEY,
            track_title TEXT,
            audio_file_path TEXT,
            audio_file_storage_mode TEXT,
            audio_file_filename TEXT,
            audio_file_mime_type TEXT,
            audio_file_size_bytes INTEGER,
            audio_file_blob BLOB
        )
        """
    )
    return conn


def _insert_cache_row(
    conn: sqlite3.Connection,
    *,
    track_id: int,
    fingerprint: str = "fp",
    peaks_json: str | None = None,
    analyzer_version: int | None = None,
    light_preview_png: bytes = b"light",
    dark_preview_png: bytes = b"dark",
) -> None:
    conn.execute(
        """
        INSERT INTO TrackAudioWaveformCache(
            track_id, source_fingerprint, source_size_bytes, source_filename,
            source_storage_mode, source_mime_type, analyzer_version, width_px,
            height_px, peaks_json, light_preview_png, dark_preview_png,
            generated_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
        """,
        (
            track_id,
            fingerprint,
            123,
            f"track-{track_id}.wav",
            "database",
            "audio/wav",
            (
                analyzer_version
                if analyzer_version is not None
                else waveform_cache.WAVEFORM_CACHE_ANALYZER_VERSION
            ),
            waveform_cache.WAVEFORM_CACHE_WIDTH,
            waveform_cache.WAVEFORM_CACHE_HEIGHT,
            peaks_json or waveform_cache._peaks_to_json([(-0.2, 0.4)]),
            light_preview_png,
            dark_preview_png,
        ),
    )


def test_waveform_cache_helpers_render_decode_resample_and_fingerprint(tmp_path: Path) -> None:
    assert (
        waveform_cache.WaveformCacheInspection(
            orphaned_rows=1,
            stale_rows=2,
            missing_audio_rows=3,
        ).issue_count
        == 6
    )
    assert waveform_cache._json_to_peaks(None) == []
    assert waveform_cache._json_to_peaks("not json") == []
    assert waveform_cache._json_to_peaks('[[-2,2],[0.25,-0.5],["bad",1],[0],[0.2,0.4,9]]') == [
        (-1.0, 1.0),
        (0.0, 0.0),
        (0.0, 0.4),
    ]
    assert waveform_cache._peaks_to_json([(-2, 2), (0.2, 0.4)]) == "[[-2.0,2.0],[0.2,0.4]]"
    assert waveform_cache._resample_peaks_to_width([(-0.1, 0.2)], 3) == [
        (-0.1, 0.2),
        (-0.1, 0.2),
        (-0.1, 0.2),
    ]
    assert waveform_cache._resample_waveform_colors([(1, 2, 3)], 3) == [(1, 2, 3)] * 3
    assert waveform_cache._fallback_waveform_rgb_for_peak(0.8) != (
        waveform_cache._fallback_waveform_rgb_for_peak(0.1)
    )

    png = waveform_cache.render_waveform_cache_png(
        [(-0.3, 0.6), (-0.8, 0.1)],
        width_px=4,
        height_px=8,
        light_background=True,
        waveform_colors=[(250, 40, 20), (20, 220, 120)],
    )
    assert png.startswith(b"\x89PNG")
    assert waveform_cache.render_waveform_cache_png([], light_background=False) == b""

    byte_handle = SimpleNamespace(
        source_bytes=b"abcdef",
        source_path=None,
        filename="bytes.wav",
        media_key="audio",
    )
    assert waveform_cache.audio_source_fingerprint(
        byte_handle
    ) == waveform_cache._bytes_edge_fingerprint(
        b"abcdef",
        6,
    )
    file_path = tmp_path / "audio.bin"
    file_path.write_bytes(b"0123456789")
    file_handle = SimpleNamespace(
        source_bytes=None,
        source_path=str(file_path),
        filename="audio.bin",
        media_key="audio",
    )
    assert waveform_cache.audio_source_fingerprint(file_handle)
    with pytest.raises(FileNotFoundError):
        waveform_cache.audio_source_fingerprint(
            SimpleNamespace(source_bytes=None, source_path=None, filename="", media_key="missing")
        )


def test_waveform_cache_loaders_and_color_helpers_handle_wav_and_decode_failures(
    tmp_path: Path,
) -> None:
    wav_path = tmp_path / "tone.wav"
    _write_stereo_wav(wav_path, _tone_frames(duration_seconds=0.08), sample_rate=11025)

    peaks = waveform_cache.load_audio_waveform_peaks(str(wav_path), 8)
    assert peaks
    assert all(-1.0 <= low <= 0.0 and 0.0 <= high <= 1.0 for low, high in peaks)

    colors = waveform_cache.load_audio_waveform_colors(str(wav_path), 6)
    assert len(colors) == 6
    assert all(
        len(color) == 3 and all(0 <= channel <= 255 for channel in color) for color in colors
    )

    invalid = tmp_path / "invalid.wav"
    invalid.write_bytes(b"not a wave")
    assert waveform_cache.load_audio_waveform_peaks(str(invalid), 3) == []
    assert waveform_cache.load_audio_waveform_colors(str(invalid), 3) == []
    assert (
        waveform_cache._shade_waveform_rgb(
            (300, -4, 80),
            peak=2.0,
            edge_ratio=2.0,
            light_background=False,
        )[3]
        == 255
    )


class _FakeTrackService:
    def __init__(self, handle) -> None:
        self.handle = handle

    def resolve_media_source(self, *_args, **_kwargs):
        return self.handle


class _MissingTrackService:
    def resolve_media_source(self, *_args, **_kwargs):
        raise FileNotFoundError("audio missing")


class _FakeHandle:
    source_path = None
    source_bytes = b"audio bytes"
    filename = "audio.wav"
    media_key = "audio_file"
    storage_mode = "database"
    mime_type = "audio/wav"
    size_bytes = len(source_bytes)

    @contextmanager
    def materialize_path(self):
        yield Path("materialized.wav")


def test_audio_waveform_cache_service_get_inspect_cleanup_and_summary(monkeypatch) -> None:
    conn = _new_cache_connection()
    service = AudioWaveformCacheService(conn)
    service.ensure_schema()
    blob = b"audio bytes"
    conn.execute(
        """
        INSERT INTO Tracks(id, track_title, audio_file_storage_mode, audio_file_filename,
                           audio_file_mime_type, audio_file_size_bytes, audio_file_blob)
        VALUES (1, 'Valid', ?, 'valid.wav', 'audio/wav', ?, ?),
               (2, 'Stale', ?, 'stale.wav', 'audio/wav', ?, ?),
               (3, 'Missing', '', '', '', 0, NULL)
        """,
        (
            waveform_cache.STORAGE_MODE_DATABASE,
            len(blob),
            blob,
            waveform_cache.STORAGE_MODE_DATABASE,
            len(blob),
            blob,
        ),
    )
    valid_fingerprint = service._database_blob_fingerprint(1, len(blob))
    _insert_cache_row(conn, track_id=1, fingerprint=valid_fingerprint)
    _insert_cache_row(conn, track_id=2, fingerprint="wrong")
    _insert_cache_row(conn, track_id=3, fingerprint="missing")
    _insert_cache_row(conn, track_id=99, fingerprint="orphan")

    cached = service.get_cached_waveform(1)
    assert cached is not None
    assert cached.track_id == 1
    assert (
        service.get_cached_waveform(2, validate_source=True, track_service=_MissingTrackService())
        is None
    )
    _insert_cache_row(conn, track_id=4, fingerprint="", light_preview_png=b"", dark_preview_png=b"")
    assert service.get_cached_waveform(4) is None
    conn.execute("DELETE FROM TrackAudioWaveformCache WHERE track_id=4")

    inspection = service.inspect_invalid_caches(_MissingTrackService())
    assert inspection.valid_rows == 1
    assert inspection.orphaned_track_ids == (99,)
    assert inspection.stale_track_ids == (2,)
    assert inspection.missing_audio_track_ids == (3,)
    assert inspection.issue_count == 3

    assert service.cleanup_invalid_caches(_MissingTrackService()) == 3
    remaining_ids = {
        row[0] for row in conn.execute("SELECT track_id FROM TrackAudioWaveformCache").fetchall()
    }
    assert remaining_ids == {1}
    conn.execute("DELETE FROM TrackAudioWaveformCache")
    conn.execute("DELETE FROM Tracks")

    _insert_cache_row(conn, track_id=2, fingerprint="reuse")
    conn.execute(
        """
        INSERT OR REPLACE INTO Tracks(id, track_title, audio_file_path, audio_file_size_bytes)
        VALUES (2, 'Reuse', 'reuse.wav', 1),
               (5, 'Render', 'render.wav', 1),
               (6, 'Skip', 'skip.wav', 1),
               (7, 'Error', 'error.wav', 1)
        """
    )

    def fake_ensure_track_cache(_track_service, track_id, **_kwargs):
        if track_id == 2:
            return waveform_cache.CachedWaveform(
                track_id=2,
                source_fingerprint="reuse",
                source_size_bytes=1,
                source_filename="reuse.wav",
                source_storage_mode="file",
                analyzer_version=waveform_cache.WAVEFORM_CACHE_ANALYZER_VERSION,
                width_px=waveform_cache.WAVEFORM_CACHE_WIDTH,
                height_px=waveform_cache.WAVEFORM_CACHE_HEIGHT,
                peaks=[(-0.1, 0.2)],
                light_preview_png=b"light",
                dark_preview_png=b"dark",
                generated_at="now",
            )
        if track_id == 5:
            return waveform_cache.CachedWaveform(
                track_id=5,
                source_fingerprint="new",
                source_size_bytes=1,
                source_filename="render.wav",
                source_storage_mode="file",
                analyzer_version=waveform_cache.WAVEFORM_CACHE_ANALYZER_VERSION,
                width_px=waveform_cache.WAVEFORM_CACHE_WIDTH,
                height_px=waveform_cache.WAVEFORM_CACHE_HEIGHT,
                peaks=[(-0.1, 0.2)],
                light_preview_png=b"light",
                dark_preview_png=b"dark",
                generated_at="now",
            )
        if track_id == 6:
            return None
        raise RuntimeError("boom")

    monkeypatch.setattr(service, "ensure_track_cache", fake_ensure_track_cache)
    progress: list[tuple[int, int, str]] = []
    summary = service.ensure_all_track_caches(
        _FakeTrackService(_FakeHandle()),
        progress_callback=lambda value, maximum, message: progress.append(
            (value, maximum, message)
        ),
    )
    assert summary.total_audio_tracks == 4
    assert summary.checked == 3
    assert summary.reused == 1
    assert summary.rendered == 1
    assert summary.skipped == 1
    assert summary.errors == 1
    assert progress
    conn.close()


def test_audio_waveform_cache_service_generates_persists_and_deletes_empty_cache(
    monkeypatch,
) -> None:
    conn = _new_cache_connection()
    service = AudioWaveformCacheService(conn)
    service.ensure_schema()
    conn.execute(
        """
        INSERT INTO Tracks(id, track_title, audio_file_path, audio_file_filename,
                           audio_file_mime_type, audio_file_size_bytes)
        VALUES (1, 'Generate', 'generate.wav', 'generate.wav', 'audio/wav', 11),
               (2, 'Delete', 'delete.wav', 'delete.wav', 'audio/wav', 11)
        """
    )
    handle = _FakeHandle()
    track_service = _FakeTrackService(handle)
    progress: list[tuple[int, int, str]] = []
    monkeypatch.setattr(waveform_cache, "load_audio_waveform_peaks", lambda *_args: [(-0.2, 0.5)])
    monkeypatch.setattr(waveform_cache, "load_audio_waveform_colors", lambda *_args: [(10, 20, 30)])
    monkeypatch.setattr(
        waveform_cache,
        "render_waveform_cache_png",
        lambda *_args, light_background, **_kwargs: b"light" if light_background else b"dark",
    )

    cached = service.ensure_track_cache(
        track_service,
        1,
        progress_callback=lambda value, maximum, message: progress.append(
            (value, maximum, message)
        ),
    )
    assert cached is not None
    assert cached.peaks == [(-0.2, 0.5)]
    assert cached.light_preview_png == b"light"
    assert cached.dark_preview_png == b"dark"
    assert len(progress) == 3

    _insert_cache_row(conn, track_id=2, fingerprint="old")
    monkeypatch.setattr(waveform_cache, "load_audio_waveform_peaks", lambda *_args: [])
    assert service.ensure_track_cache(track_service, 2, force=True) is None
    assert (
        conn.execute("SELECT COUNT(*) FROM TrackAudioWaveformCache WHERE track_id=2").fetchone()[0]
        == 0
    )
    conn.close()

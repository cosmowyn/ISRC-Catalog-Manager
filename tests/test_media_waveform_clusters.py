from __future__ import annotations

import math
import sqlite3
import struct
import sys
import types
import wave
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QBuffer, QByteArray, QEvent, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter

from isrc_manager.media import waveform as waveform_module
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


def _pack_s24(value: int) -> bytes:
    if value < 0:
        value += 1 << 24
    return bytes((value & 0xFF, (value >> 8) & 0xFF, (value >> 16) & 0xFF))


def _write_pcm_wav(
    path: Path,
    samples: list[tuple[int, ...]],
    *,
    channels: int,
    sample_width: int,
    sample_rate: int = 22050,
) -> None:
    payload = bytearray()
    for frame in samples:
        values = list(frame)
        if len(values) == 1 and channels > 1:
            values *= channels
        for value in values[:channels]:
            if sample_width == 1:
                payload.append(max(0, min(255, int(value))))
            elif sample_width == 2:
                payload.extend(struct.pack("<h", int(value)))
            elif sample_width == 3:
                payload.extend(_pack_s24(int(value)))
            elif sample_width == 4:
                payload.extend(struct.pack("<i", int(value)))
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(sample_width)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(bytes(payload))


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
    def __init__(
        self,
        *,
        pixel_delta: int = 0,
        angle_delta: int = 0,
        pixel_x: int = 0,
        angle_x: int = 0,
    ) -> None:
        self._pixel_delta = _PointDelta(pixel_x, pixel_delta)
        self._angle_delta = _PointDelta(angle_x, angle_delta)
        self.accepted = False
        self.ignored = False

    def pixelDelta(self) -> _PointDelta:
        return self._pixel_delta

    def angleDelta(self) -> _PointDelta:
        return self._angle_delta

    def accept(self) -> None:
        self.accepted = True

    def ignore(self) -> None:
        self.ignored = True


class _FakeSignal:
    def __init__(self) -> None:
        self._callbacks = []

    def connect(self, callback) -> None:
        self._callbacks.append(callback)

    def emit(self, *args) -> None:
        for callback in list(self._callbacks):
            callback(*args)


class _FakeEventLoop:
    def __init__(self) -> None:
        self.quit_called = False

    def exec(self) -> None:
        return None

    def quit(self) -> None:
        self.quit_called = True


class _FakeTimer:
    def __init__(self, *_args) -> None:
        self.timeout = _FakeSignal()
        self.active = False

    def setSingleShot(self, _value: bool) -> None:
        return None

    def start(self, *_args) -> None:
        self.active = True

    def stop(self) -> None:
        self.active = False


class _FakeAudioFormat:
    def __init__(self, sample_format) -> None:
        self._sample_format = sample_format

    def bytesPerFrame(self) -> int:
        return 4

    def bytesPerSample(self) -> int:
        return 2

    def channelCount(self) -> int:
        return 2

    def sampleFormat(self):
        return self._sample_format

    def sampleRate(self) -> int:
        return 8000


class _FakeAudioBuffer:
    def __init__(self, payload: bytes, sample_format) -> None:
        self._payload = payload
        self._format = _FakeAudioFormat(sample_format)

    def isValid(self) -> bool:
        return True

    def format(self):
        return self._format

    def data(self) -> bytes:
        return self._payload


def _fake_decoder_class(sample_format, payload: bytes):
    class _FakeDecoder:
        def __init__(self) -> None:
            self.bufferReady = _FakeSignal()
            self.finished = _FakeSignal()
            self.error = _FakeSignal()
            self._buffer = _FakeAudioBuffer(payload, sample_format)
            self.stopped = False

        def isSupported(self) -> bool:
            return True

        def setSource(self, _source) -> None:
            return None

        def start(self) -> None:
            self.bufferReady.emit()
            self.finished.emit()

        def stop(self) -> None:
            self.stopped = True

        def read(self):
            return self._buffer

        def duration(self) -> int:
            return 1

        def errorString(self) -> str:
            return ""

    return _FakeDecoder


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


def test_waveform_widget_edge_events_and_render_paths() -> None:
    require_qapplication()
    widget = WaveformWidget()
    widget.resize(96, 48)
    widget.set_preferred_height(widget.sizeHint().height())
    widget.set_cached_waveform(
        [(-0.4, 0.7), (0.0, 0.0)],
        light_preview_png=b"",
        dark_preview_png=b"not a png",
        cache_key="bad-preview",
    )
    assert widget._stored_waveform_pixmap() is None

    widget.set_harmonic_frames([[0.5], object(), ["bad"], []])
    assert widget._harmonic_frames == [[0.5]]
    assert widget._harmonic_frame_position() == 0.0
    assert widget._harmonic_frame_at_position(0) == [0.5]
    widget.set_harmonic_frames(None)
    assert widget._harmonic_frame_at_position(0) == []

    widget.set_duration_ms(1000)
    widget.resize(1, 24)
    assert widget._position_from_x(99) == 0
    assert widget._playhead_x_for_ms(500) == widget.rect().left()

    widget.resize(96, 48)
    widget.set_peaks([(-0.4, 0.7), (0.0, 0.0)])
    widget.set_playhead_ms(250)
    widget.set_bookmarks_ms([250, "250", "bad", 900])
    widget.set_bookmarks_ms([250, 900])

    scrub_values = _connect_int_signal(widget.scrubRequested)
    horizontal_pixel = _WheelLikeEvent(pixel_x=80, pixel_delta=2)
    widget.wheelEvent(horizontal_pixel)
    assert horizontal_pixel.accepted is True
    assert scrub_values[-1] == 2000

    horizontal_angle = _WheelLikeEvent(angle_x=-120, angle_delta=1)
    widget.wheelEvent(horizontal_angle)
    assert horizontal_angle.accepted is True
    assert scrub_values[-1] == -1000

    no_delta = _WheelLikeEvent()
    widget.wheelEvent(no_delta)
    assert no_delta.ignored is True

    rendered = QImage(96, 48, QImage.Format.Format_ARGB32)
    rendered.fill(Qt.GlobalColor.transparent)
    widget.render(rendered)

    widget.set_cached_waveform(
        [(-0.2, 0.5)],
        dark_preview_png=_png_bytes(QColor("#101010")),
        cache_key="dark-fallback",
    )
    assert widget._stored_waveform_pixmap() is not None
    rendered_cached = QImage(96, 48, QImage.Format.Format_ARGB32)
    rendered_cached.fill(Qt.GlobalColor.transparent)
    widget.render(rendered_cached)
    widget.changeEvent(QEvent(QEvent.Type.PaletteChange))

    widget.set_harmonic_frames([[0.2, 0.7], [0.6, 0.1]])
    live_image = QImage(96, 48, QImage.Format.Format_ARGB32)
    live_image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(live_image)
    try:
        widget._draw_live_harmonics(painter, widget.rect(), light_mode=False)
    finally:
        painter.end()


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


def test_load_wav_peaks_handles_24_32_bit_and_decoder_fallbacks(
    monkeypatch,
    tmp_path: Path,
) -> None:
    wav_24 = tmp_path / "tone24.wav"
    _write_pcm_wav(
        wav_24,
        [(0, 0), (3_000_000, -4_000_000), (-8_000_000, 7_000_000)],
        channels=2,
        sample_width=3,
    )
    peaks_24 = load_wav_peaks(str(wav_24), 2)
    assert peaks_24
    assert min(low for low, _high in peaks_24) < -0.4

    wav_32 = tmp_path / "tone32.wav"
    _write_pcm_wav(
        wav_32,
        [(0,), (1_200_000_000,), (-1_600_000_000,)],
        channels=1,
        sample_width=4,
    )
    peaks_32 = load_wav_peaks(str(wav_32), 2)
    assert peaks_32
    assert max(high for _low, high in peaks_32) > 0.5

    raw_path = tmp_path / "compressed.bin"
    raw_path.write_bytes(b"not-riff")

    import shutil
    import subprocess

    pcm = b"".join(struct.pack("<hh", 12000, -6000) for _ in range(448))

    class _FakeStdout:
        def __init__(self, payload: bytes) -> None:
            self._payload = payload
            self.closed = False

        def read(self, _size: int) -> bytes:
            payload, self._payload = self._payload, b""
            return payload

        def close(self) -> None:
            self.closed = True

    class _FakeProcess:
        def __init__(self, payload: bytes) -> None:
            self.stdout = _FakeStdout(payload)
            self.killed = False

        def wait(self, *, timeout=None):
            raise TimeoutError

        def kill(self) -> None:
            self.killed = True

    monkeypatch.setattr(
        shutil,
        "which",
        lambda name: f"/fake/{name}" if name in {"ffmpeg", "ffprobe"} else None,
    )
    monkeypatch.setattr(subprocess, "check_output", lambda *_args, **_kwargs: b"0.05")
    monkeypatch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: _FakeProcess(pcm))
    ffmpeg_peaks = load_wav_peaks(str(raw_path), 2)
    assert ffmpeg_peaks
    assert ffmpeg_peaks[0][0] < 0.0

    import platform

    class _UnsupportedDecoder:
        def isSupported(self) -> bool:
            return False

    class _FakeAudioRead:
        samplerate = 44100
        duration = 0.05
        channels = 1

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def __iter__(self):
            return iter([b"".join(struct.pack("<h", 9000) for _ in range(512))])

    monkeypatch.setattr(shutil, "which", lambda _name: None)
    monkeypatch.setattr(platform, "system", lambda: "plan9")
    monkeypatch.setattr("isrc_manager.media.waveform.QAudioDecoder", _UnsupportedDecoder)
    monkeypatch.setitem(
        sys.modules,
        "audioread",
        types.SimpleNamespace(audio_open=lambda _path: _FakeAudioRead()),
    )
    audioread_peaks = load_wav_peaks(str(raw_path), 2)
    assert audioread_peaks
    assert audioread_peaks[0][1] > 0.0


def test_qt_decoder_waveform_fallbacks_are_deterministic(
    monkeypatch,
    tmp_path: Path,
) -> None:
    require_qapplication()
    raw_path = tmp_path / "decoder-source.bin"
    raw_path.write_bytes(b"not-riff")
    payload = b"".join(struct.pack("<hh", 12000, -8000) for _ in range(8))

    import os
    import platform
    import shutil

    monkeypatch.setattr(shutil, "which", lambda _name: None)
    monkeypatch.setattr(platform, "system", lambda: "plan9")
    monkeypatch.setattr(os.path, "exists", lambda _path: False)
    monkeypatch.setattr(waveform_module, "QEventLoop", _FakeEventLoop)
    monkeypatch.setattr(waveform_module, "QTimer", _FakeTimer)
    monkeypatch.setattr(
        waveform_module,
        "QAudioDecoder",
        _fake_decoder_class(waveform_module.QAudioFormat.SampleFormat.Int16, payload),
    )
    peaks = load_wav_peaks(str(raw_path), 2)
    assert peaks
    assert peaks[0][0] < 0.0
    assert peaks[0][1] > 0.0

    import PySide6.QtCore as qtcore
    import PySide6.QtMultimedia as qtmultimedia

    assert waveform_cache._qt_application_instance_available() is True
    monkeypatch.setattr(qtcore, "QEventLoop", _FakeEventLoop)
    monkeypatch.setattr(qtcore, "QTimer", _FakeTimer)
    monkeypatch.setattr(
        qtmultimedia,
        "QAudioDecoder",
        _fake_decoder_class(qtmultimedia.QAudioFormat.SampleFormat.Int16, payload),
    )
    cache_peaks = waveform_cache._load_qt_decoder_peaks(str(raw_path), 2)
    assert cache_peaks
    assert cache_peaks[0][0] < 0.0
    assert cache_peaks[0][1] > 0.0


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


def test_audio_visualization_widget_edge_states_and_rendering() -> None:
    require_qapplication()
    meter = StereoPeakMeterWidget()
    meter.resize(64, 48)
    meter.set_peak_frames([None, ("bad", 1), (-12,), (-12.0, -6.0)])
    assert meter._frames == [(-12.0, -6.0)]
    assert meter._frame_at_playhead() == pytest.approx((-12.0, -6.0))
    meter.set_gain(0.0)
    assert meter._frame_at_playhead() == (
        StereoPeakMeterWidget.DB_FLOOR,
        StereoPeakMeterWidget.DB_FLOOR,
    )
    meter.reset_signal_activity()
    meter.set_playhead_ms(1)
    meter.set_gain(1.0)
    assert meter._current_db == (
        StereoPeakMeterWidget.DB_FLOOR,
        StereoPeakMeterWidget.DB_FLOOR,
    )
    meter.mark_signal_activity()
    meter.reset_peak_hold()
    meter.begin_release()
    meter.begin_release()
    meter.set_playhead_ms(1)
    meter.set_gain(0.5)
    meter._current_db = (-12.0, -6.0)
    meter._hold_db = -6.0

    image = QImage(64, 48, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    meter.render(image)

    graph = SpectrumGraphWidget()
    graph.resize(96, 40)
    graph.set_equalizer_settings(None)
    graph.set_equalizer_settings({"enabled": True, "gains": [3.0] * 8, "pan": 0.25})
    menu = graph._create_frequency_scale_context_menu()
    assert [action.text() for action in menu.actions()] == ["Linear view", "Log view"]
    menu.actions()[1].trigger()
    assert graph.frequency_scale() == SpectrumGraphWidget.SPECTRUM_SCALE_LOG

    graph.start_fade_in()
    assert graph._fade_opacity == 0.0
    graph.set_gain(0.0)
    graph.set_spectrum_frames([[0.2, 0.8, 0.4]])
    graph.start_fade_in()
    assert graph._fade_opacity == 0.0
    graph.set_gain(1.0)
    graph._fade_opacity = 1.0
    graph.start_fade_in()
    graph._fade_opacity = 0.0
    graph.start_release()
    assert graph.is_releasing() is False
    assert graph.advance_release(1) is False
    graph._fade_opacity = 0.8
    graph.start_release()
    graph.start_release()
    graph._advance_fade_in()
    assert graph.is_releasing() is True
    graph.advance_release(SpectrumGraphWidget.SPECTRUM_RELEASE_MS * 2)

    assert graph._log_scaled_spectrum_values([0.1, 0.2]) == [0.1, 0.2]
    assert graph._spectrum_line_segments([], QRectF(0, 0, 10, 10)) == []
    graph._release_active = False
    graph.set_gain(1.0)
    graph.set_spectrum_frames([[0.2, 0.8, 0.4, 1.0]])
    graph._fade_opacity = 1.0
    image = QImage(96, 40, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    try:
        graph._draw_spectrum_graph(painter, graph.rect(), light_mode=True)
    finally:
        painter.end()
    graph.render(image)


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


def test_audio_visualization_loaders_cover_pcm_width_and_channel_variants(
    tmp_path: Path,
) -> None:
    wav_8_mono = tmp_path / "mono8.wav"
    _write_pcm_wav(
        wav_8_mono,
        [(128,), (255,), (0,), (200,), (40,)] * 120,
        channels=1,
        sample_width=1,
        sample_rate=8000,
    )
    peak_frames = load_audio_peak_meter_frames(str(wav_8_mono), target_sr=8000)
    assert peak_frames
    assert all(left == right for left, right in peak_frames)

    wav_24_stereo = tmp_path / "stereo24.wav"
    samples_24 = [
        (
            int(math.sin(index / 12.0) * 6_000_000),
            int(math.cos(index / 13.0) * 5_000_000),
        )
        for index in range(4096)
    ]
    _write_pcm_wav(
        wav_24_stereo,
        samples_24,
        channels=2,
        sample_width=3,
        sample_rate=16000,
    )
    spectrum_frames = load_audio_spectrum_frames(str(wav_24_stereo), target_sr=16000, bin_count=4)
    assert spectrum_frames
    assert len(spectrum_frames[0]) == 48

    wav_32_mono = tmp_path / "mono32.wav"
    samples_32 = [
        (int(math.sin((2.0 * math.pi * 440.0 * index) / 22050) * 1_200_000_000),)
        for index in range(4096)
    ]
    _write_pcm_wav(
        wav_32_mono,
        samples_32,
        channels=1,
        sample_width=4,
        sample_rate=22050,
    )
    harmonic_frames = load_audio_harmonic_frames(str(wav_32_mono), target_sr=11025)
    assert harmonic_frames
    assert all(len(frame) == 14 for frame in harmonic_frames)


def test_audio_visualization_loaders_decode_ffmpeg_fallbacks(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "compressed-source.m4a"
    source.write_bytes(b"not-riff")

    import os
    import platform
    import shutil
    import subprocess

    monkeypatch.setattr(shutil, "which", lambda _name: None)
    monkeypatch.setattr(platform, "system", lambda: "windows")
    monkeypatch.setattr(
        os.path,
        "exists",
        lambda path: str(path).lower().endswith("ffmpeg.exe"),
    )

    def fake_check_output(args, **_kwargs):
        channels = int(args[args.index("-ac") + 1])
        sample_rate = int(args[args.index("-ar") + 1])
        frame_count = 4096
        frames = []
        for index in range(frame_count):
            sample = int(math.sin((2.0 * math.pi * 440.0 * index) / sample_rate) * 18000)
            if channels == 2:
                frames.append(struct.pack("<hh", sample, -sample // 2))
            else:
                frames.append(struct.pack("<h", sample))
        return b"".join(frames)

    monkeypatch.setattr(subprocess, "check_output", fake_check_output)

    harmonic_frames = load_audio_harmonic_frames(str(source), target_sr=8000)
    assert harmonic_frames
    peak_frames = load_audio_peak_meter_frames(str(source), target_sr=8000)
    assert peak_frames
    spectrum_frames = load_audio_spectrum_frames(str(source), target_sr=8000, bin_count=4)
    assert spectrum_frames
    assert len(spectrum_frames[0]) == 48


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


def test_waveform_cache_schema_delete_decoder_and_color_edge_branches(
    monkeypatch,
    tmp_path: Path,
) -> None:
    plain_conn = sqlite3.connect(":memory:")
    waveform_cache.ensure_audio_waveform_cache_schema(plain_conn)
    assert waveform_cache.delete_audio_waveform_cache(plain_conn, 1) == 0
    plain_conn.close()

    conn = _new_cache_connection()
    service = AudioWaveformCacheService(conn)
    service.ensure_schema()
    conn.execute(
        "INSERT INTO Tracks(id, track_title, audio_file_path) VALUES (1, 'Delete me', 'a.wav')"
    )
    _insert_cache_row(conn, track_id=1)
    assert waveform_cache.delete_audio_waveform_cache(conn, 1) == 1
    _insert_cache_row(conn, track_id=1)
    conn.execute("DELETE FROM Tracks WHERE id=1")
    assert conn.execute("SELECT COUNT(*) FROM TrackAudioWaveformCache").fetchone()[0] == 0
    conn.close()

    not_riff = tmp_path / "not-riff.bin"
    not_riff.write_bytes(b"nope")
    assert waveform_cache._load_wave_peaks(str(not_riff), 2) is None
    wrong_riff = tmp_path / "wrong-riff.bin"
    wrong_riff.write_bytes(b"RIFF0000AIFF")
    assert waveform_cache._load_wave_peaks(str(wrong_riff), 2) == []
    corrupt_wav = tmp_path / "corrupt.wav"
    corrupt_wav.write_bytes(b"RIFF0000WAVE")
    assert waveform_cache._load_wave_peaks(str(corrupt_wav), 2) == []

    wav_24 = tmp_path / "cache24.wav"
    _write_pcm_wav(
        wav_24,
        [(0, 0), (4_000_000, -5_000_000), (-7_000_000, 3_000_000)],
        channels=2,
        sample_width=3,
    )
    assert waveform_cache._load_wave_peaks(str(wav_24), 2)
    wav_32 = tmp_path / "cache32.wav"
    _write_pcm_wav(
        wav_32,
        [(0,), (1_000_000_000,), (-1_500_000_000,)],
        channels=1,
        sample_width=4,
    )
    assert waveform_cache._load_wave_peaks(str(wav_32), 2)

    mp3_missing = tmp_path / "missing.mp3"
    assert waveform_cache._mp3_source_has_frame_sync(str(mp3_missing)) is False
    mp3_empty = tmp_path / "empty.mp3"
    mp3_empty.write_bytes(b"")
    assert waveform_cache._mp3_source_has_frame_sync(str(mp3_empty)) is False
    mp3_sync = tmp_path / "sync.mp3"
    mp3_sync.write_bytes(b"\x00\xff\xe3\x00")
    assert waveform_cache._mp3_source_has_frame_sync(str(mp3_sync)) is True

    with monkeypatch.context() as which_patch:
        which_patch.setattr(
            waveform_cache.shutil,
            "which",
            lambda name: "/direct/bin/tool" if name == "direct" else None,
        )
        assert waveform_cache._which("direct") == "/direct/bin/tool"
        which_patch.setattr(waveform_cache.shutil, "which", lambda _name: None)
        which_patch.setattr(waveform_cache.platform, "system", lambda: "windows")
        which_patch.setattr(
            waveform_cache.os.path,
            "exists",
            lambda path: str(path).lower().endswith("ffmpeg.exe"),
        )
        assert waveform_cache._which("ffmpeg").lower().endswith("ffmpeg.exe")
        which_patch.setattr(waveform_cache.platform, "system", lambda: "plan9")
        assert waveform_cache._which("ffmpeg") is None

    import subprocess

    class _NoStdoutProcess:
        stdout = None

        def __init__(self) -> None:
            self.killed = False

        def kill(self) -> None:
            self.killed = True

    monkeypatch.setattr(
        waveform_cache,
        "_which",
        lambda name: f"/fake/{name}" if name in {"ffmpeg", "ffprobe"} else None,
    )
    monkeypatch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: _NoStdoutProcess())
    assert waveform_cache._load_ffmpeg_peaks(str(not_riff), 2) is None

    class _FakeStdout:
        def __init__(self, payload: bytes) -> None:
            self._payload = payload

        def read(self, _size: int) -> bytes:
            payload, self._payload = self._payload, b""
            return payload

        def close(self) -> None:
            pass

    class _FakeProcess:
        def __init__(self, payload: bytes) -> None:
            self.stdout = _FakeStdout(payload)
            self.killed = False

        def wait(self, *, timeout=None):
            raise TimeoutError

        def poll(self):
            return None

        def kill(self) -> None:
            self.killed = True

    pcm = b"".join(struct.pack("<hh", 16000, -4000) for _ in range(12))
    monkeypatch.setattr(subprocess, "check_output", lambda *_args, **_kwargs: b"0.01")
    monkeypatch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: _FakeProcess(pcm))
    assert waveform_cache._load_ffmpeg_peaks(str(not_riff), 2)

    monkeypatch.setattr(waveform_cache, "_load_wave_peaks", lambda *_args: None)
    monkeypatch.setattr(waveform_cache, "_load_ffmpeg_peaks", lambda *_args: None)
    assert waveform_cache.load_audio_waveform_peaks(str(tmp_path / "silent.wav"), 2) == []
    monkeypatch.setattr(waveform_cache, "_mp3_source_has_frame_sync", lambda _path: False)
    assert waveform_cache.load_audio_waveform_peaks(str(tmp_path / "silent.mp3"), 2) == []
    monkeypatch.setattr(waveform_cache, "_mp3_source_has_frame_sync", lambda _path: True)
    monkeypatch.setattr(waveform_cache, "_load_qt_decoder_peaks", lambda *_args: [(-0.1, 0.2)])
    assert waveform_cache.load_audio_waveform_peaks(str(tmp_path / "qt.mp3"), 2) == [(-0.1, 0.2)]

    import numpy as np

    monkeypatch.setattr(
        waveform_cache,
        "_decode_mono_audio_for_waveform_colors",
        lambda _path: (np.zeros(8, dtype=np.float32), 8000),
    )
    zero_colors = waveform_cache.load_audio_waveform_colors("silence.wav", 3)
    assert len(zero_colors) == 3
    monkeypatch.setattr(
        waveform_cache,
        "_decode_mono_audio_for_waveform_colors",
        lambda _path: (None, 0),
    )
    assert waveform_cache.load_audio_waveform_colors("missing.wav", 3) == []

    assert waveform_cache._build_waveform_path([], QRectF(0, 0, 10, 10)).isEmpty()
    assert not waveform_cache._build_waveform_path([(-0.4, 0.7)], QRectF(0, 0, 10, 10)).isEmpty()
    assert waveform_cache._resample_peaks_to_width(
        [(-0.1, 0.1), (-0.8, 0.2), (-0.2, 0.9), (-0.3, 0.4)],
        2,
    ) == [(-0.8, 0.2), (-0.3, 0.9)]
    fallback_png = waveform_cache.render_waveform_cache_png(
        [(-0.2, 0.0), (0.0, 0.7)],
        width_px=2,
        height_px=6,
        light_background=False,
    )
    assert fallback_png.startswith(b"\x89PNG")

    assert waveform_cache._read_edge_bytes(not_riff, 0) == (b"", b"")
    large_data = b"a" * (waveform_cache._FINGERPRINT_EDGE_BYTES + 2)
    assert waveform_cache._bytes_edge_fingerprint(large_data, len(large_data))


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


def test_waveform_cache_ffmpeg_color_decode_resampling_and_service_edges(
    monkeypatch,
    tmp_path: Path,
) -> None:
    import numpy as np

    monkeypatch.setattr(waveform_cache, "_which", lambda name: f"/fake/{name}")
    monkeypatch.setattr(
        waveform_cache.subprocess,
        "check_output",
        lambda *_args, **_kwargs: struct.pack("<ff", 0.25, -0.5),
    )
    mono, sample_rate = waveform_cache._decode_mono_audio_with_ffmpeg("source.flac", target_sr=8)
    assert sample_rate == 8
    assert mono.tolist() == pytest.approx([0.25, -0.5])
    monkeypatch.setattr(waveform_cache.subprocess, "check_output", lambda *_args, **_kwargs: b"")
    assert waveform_cache._decode_mono_audio_with_ffmpeg("empty.flac", target_sr=8) == (None, 0)

    resampled = waveform_cache._resample_mono_audio(
        np.asarray([0.0, 1.0], dtype=np.float32),
        2,
        4,
    )
    assert len(resampled) >= 2
    same = np.asarray([0.0, 0.5], dtype=np.float32)
    assert waveform_cache._resample_mono_audio(same, 0, 4) is same

    high_color = waveform_cache._frequency_color_from_bands(0.0, 0.0, 0.0, 10.0, 1.0)
    low_color = waveform_cache._frequency_color_from_bands(10.0, 0.0, 0.0, 0.0, 0.5)
    assert high_color != low_color

    conn = _new_cache_connection()
    service = AudioWaveformCacheService(conn)
    service.ensure_schema()
    assert service._row_to_cached_waveform(None) is None
    tuple_cached = service._row_to_cached_waveform(
        (
            9,
            "fp",
            12,
            "tuple.wav",
            "file",
            waveform_cache.WAVEFORM_CACHE_ANALYZER_VERSION,
            waveform_cache.WAVEFORM_CACHE_WIDTH,
            waveform_cache.WAVEFORM_CACHE_HEIGHT,
            waveform_cache._peaks_to_json([(-0.1, 0.2)]),
            b"light",
            b"dark",
            "now",
        )
    )
    assert tuple_cached is not None
    assert tuple_cached.track_id == 9
    assert AudioWaveformCacheService._cached_waveform_is_complete(tuple_cached) is True
    with pytest.raises(FileNotFoundError):
        service._track_audio_metadata(404)
    assert service._database_blob_fingerprint(404, 0)

    blob = b"database audio bytes"
    conn.execute(
        """
        INSERT INTO Tracks(id, track_title, audio_file_storage_mode, audio_file_size_bytes,
                           audio_file_blob)
        VALUES (1, 'Cached', ?, ?, ?)
        """,
        (waveform_cache.STORAGE_MODE_DATABASE, len(blob), blob),
    )
    fingerprint = service._database_blob_fingerprint(1, len(blob))
    _insert_cache_row(conn, track_id=1, fingerprint=fingerprint)
    cached = service.ensure_track_cache(_FakeTrackService(_FakeHandle()), 1)
    assert cached is not None
    assert cached.source_fingerprint == fingerprint
    assert service.get_cached_waveform(1, validate_source=True) is None

    source_path = tmp_path / "external.wav"
    source_path.write_bytes(b"external audio bytes")

    class _PathHandle:
        def __init__(self, path: Path) -> None:
            self.filename = "external.wav"
            self.media_key = "audio_file"
            self.mime_type = "audio/wav"
            self.source_bytes = None
            self.source_path = path
            self.storage_mode = "file"
            self.size_bytes = path.stat().st_size

        @contextmanager
        def materialize_path(self):
            yield self.source_path

    conn.execute(
        """
        INSERT INTO Tracks(id, track_title, audio_file_path, audio_file_size_bytes)
        VALUES (2, 'External', ?, ?),
               (3, 'Explodes', 'explodes.wav', 1)
        """,
        (str(source_path), source_path.stat().st_size),
    )
    fingerprint, metadata = service._source_fingerprint_for_track(
        _FakeTrackService(_PathHandle(source_path)),
        2,
    )
    assert fingerprint
    assert metadata["filename"] == "external.wav"
    _insert_cache_row(conn, track_id=2, fingerprint=fingerprint)
    assert service.cleanup_invalid_caches(_FakeTrackService(_PathHandle(source_path))) == 0

    monkeypatch.setattr(waveform_cache, "load_audio_waveform_peaks", lambda *_args: [(-0.1, 0.2)])
    monkeypatch.setattr(waveform_cache, "load_audio_waveform_colors", lambda *_args: [])
    monkeypatch.setattr(waveform_cache, "render_waveform_cache_png", lambda *_args, **_kwargs: b"")
    assert (
        service.ensure_track_cache(_FakeTrackService(_PathHandle(source_path)), 2, force=True)
        is None
    )

    class _ExplodingTrackService:
        def resolve_media_source(self, *_args, **_kwargs):
            raise RuntimeError("resolver failed")

    _insert_cache_row(conn, track_id=3, fingerprint="stale")
    inspection = service.inspect_invalid_caches(_ExplodingTrackService())
    assert inspection.stale_track_ids == (3,)
    assert "could not verify source" in inspection.details[0]

    empty_conn = _new_cache_connection()
    empty_service = AudioWaveformCacheService(empty_conn)
    progress: list[tuple[int, int, str]] = []
    summary = empty_service.ensure_all_track_caches(
        _FakeTrackService(_FakeHandle()),
        progress_callback=lambda value, maximum, message: progress.append(
            (value, maximum, message)
        ),
    )
    assert summary.total_audio_tracks == 0
    assert progress == [(1, 1, "No audio waveform cache work needed.")]
    conn.close()
    empty_conn.close()


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

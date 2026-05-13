from __future__ import annotations

import os
import platform
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtMultimedia import QAudioFormat, QAudioOutput, QAudioSink, QMediaDevices, QMediaPlayer

from isrc_manager.media.equalizer import (
    EQUALIZER_BANDS,
    equalizer_biquad_coefficients,
    normalize_equalizer_settings,
)


def _which(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    system = platform.system().lower()
    search_dirs: list[str] = []
    if system == "darwin":
        search_dirs = ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin"]
    elif system == "linux":
        search_dirs = ["/usr/bin", "/usr/local/bin"]
    elif system == "windows":
        search_dirs = [
            r"C:\Program Files\ffmpeg\bin",
            r"C:\ffmpeg\bin",
            r"C:\ProgramData\chocolatey\bin",
            os.path.expandvars(r"%USERPROFILE%\scoop\shims"),
        ]
    candidates = [name]
    if system == "windows" and not name.lower().endswith(".exe"):
        candidates.append(f"{name}.exe")
    for directory in search_dirs:
        for candidate in candidates:
            full_path = os.path.join(directory, candidate)
            if os.path.exists(full_path):
                return full_path
    return None


def _decode_audio_file(path: str):
    import numpy as np

    ffmpeg = _which("ffmpeg")
    if ffmpeg:
        try:
            output = subprocess.check_output(
                [
                    ffmpeg,
                    "-v",
                    "error",
                    "-nostdin",
                    "-vn",
                    "-i",
                    os.fspath(path),
                    "-f",
                    "f32le",
                    "-acodec",
                    "pcm_f32le",
                    "-ac",
                    "2",
                    "-ar",
                    "44100",
                    "-",
                ],
                stderr=subprocess.STDOUT,
                timeout=45,
            )
            if output:
                values = np.frombuffer(output, dtype="<f4")
                usable = (len(values) // 2) * 2
                if usable > 0:
                    samples = values[:usable].reshape(-1, 2).astype("float32", copy=True)
                    return np.clip(samples, -1.0, 1.0), 44100
        except Exception:
            pass

    try:
        import soundfile as sf

        values, sample_rate = sf.read(os.fspath(path), dtype="float32", always_2d=True)
        if values is not None and values.size > 0:
            if values.shape[1] == 1:
                values = np.repeat(values, 2, axis=1)
            elif values.shape[1] > 2:
                values = values[:, :2]
            return np.clip(values.astype("float32", copy=True), -1.0, 1.0), int(sample_rate)
    except Exception:
        pass

    raise RuntimeError(f"Could not decode audio for live playback: {Path(path).name}")


@dataclass
class _LiveBiquad:
    b0: float = 1.0
    b1: float = 0.0
    b2: float = 0.0
    a1: float = 0.0
    a2: float = 0.0
    z1: Any = None
    z2: Any = None
    active: bool = False

    def configure(
        self,
        *,
        filter_type: str,
        frequency_hz: float,
        q: float,
        gain_db: float,
        sample_rate: int,
        channels: int,
    ) -> None:
        import numpy as np

        if self.z1 is None or len(self.z1) != channels:
            self.z1 = np.zeros(channels, dtype=np.float64)
            self.z2 = np.zeros(channels, dtype=np.float64)

        was_active = bool(self.active)
        if abs(float(gain_db)) < 0.05:
            self.b0, self.b1, self.b2 = 1.0, 0.0, 0.0
            self.a1, self.a2 = 0.0, 0.0
            self.active = False
            if was_active:
                self.reset(channels)
            return

        self.b0, self.b1, self.b2, self.a1, self.a2 = equalizer_biquad_coefficients(
            filter_type,
            frequency_hz,
            q,
            gain_db,
            sample_rate,
        )
        self.active = True
        if not was_active:
            self.reset(channels)

    def reset(self, channels: int) -> None:
        import numpy as np

        self.z1 = np.zeros(channels, dtype=np.float64)
        self.z2 = np.zeros(channels, dtype=np.float64)

    def process(self, samples):
        if not self.active or samples.size <= 0:
            return samples
        output = samples.copy()
        for index in range(output.shape[0]):
            x_value = output[index]
            y_value = (self.b0 * x_value) + self.z1
            self.z1 = (self.b1 * x_value) - (self.a1 * y_value) + self.z2
            self.z2 = (self.b2 * x_value) - (self.a2 * y_value)
            output[index] = y_value
        return output


class LiveEqualizerPlayer(QObject):
    durationChanged = Signal(int)
    positionChanged = Signal(int)
    mediaStatusChanged = Signal(object)
    playbackStateChanged = Signal(object)
    spectrumFrameChanged = Signal(list)

    POSITION_TIMER_MS = 33
    BUFFER_FRAMES = 1024
    SINK_BUFFER_BLOCKS = 4
    SPECTRUM_BINS = 96
    SPECTRUM_MIN_HZ = 20.0
    SPECTRUM_MAX_HZ = 20000.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self._lock = threading.RLock()
        self._samples = None
        self._sample_rate = 44100
        self._channels = 2
        self._duration_ms = 0
        self._position_frames = 0
        self._state = QMediaPlayer.PlaybackState.StoppedState
        self._audio_output: QAudioOutput | None = None
        self._sink: QAudioSink | None = None
        self._sink_io: Any | None = None
        self._equalizer_settings = normalize_equalizer_settings(None)
        self._filters = [_LiveBiquad() for _band in EQUALIZER_BANDS]
        self._pending_finish = False
        self._last_emitted_position = -1
        self._spectrum_smoothed = None
        self._spectrum_reference = 0.0
        self._spectrum_fast_frames = 0
        self._recent_output_samples = None

        self._position_timer = QTimer(self)
        self._position_timer.setInterval(self.POSITION_TIMER_MS)
        self._position_timer.timeout.connect(self._emit_position_tick)

        self._render_timer = QTimer(self)
        self._render_timer.setInterval(8)
        self._render_timer.timeout.connect(self._push_audio)

        self._spectrum_timer = QTimer(self)
        self._spectrum_timer.setInterval(45)
        self._spectrum_timer.timeout.connect(self._emit_spectrum_tick)

    def setAudioOutput(self, audio_output: QAudioOutput | None) -> None:
        self._audio_output = audio_output
        if audio_output is None:
            return
        try:
            audio_output.volumeChanged.connect(lambda *_args: self._sync_sink_volume())
        except Exception:
            pass
        try:
            audio_output.mutedChanged.connect(lambda *_args: self._sync_sink_volume())
        except Exception:
            pass
        self._sync_sink_volume()

    def set_equalizer_settings(self, settings: dict[str, object]) -> None:
        normalized = normalize_equalizer_settings(settings)
        changed = False
        with self._lock:
            changed = normalized != self._equalizer_settings
            self._equalizer_settings = normalized
            self._configure_filters_locked(reset=False)
            if changed:
                self._recent_output_samples = None
                self._spectrum_fast_frames = 5
        if changed and self._state == QMediaPlayer.PlaybackState.PlayingState:
            QTimer.singleShot(0, self._emit_spectrum_tick)

    def setSource(self, source: QUrl) -> None:
        self.stop()
        if source is None or source.isEmpty():
            with self._lock:
                self._samples = None
                self._duration_ms = 0
                self._position_frames = 0
            self.durationChanged.emit(0)
            self.positionChanged.emit(0)
            return

        path = source.toLocalFile()
        samples, sample_rate = _decode_audio_file(path)
        with self._lock:
            self._samples = samples
            self._sample_rate = max(1, int(sample_rate or 44100))
            self._channels = int(samples.shape[1]) if len(samples.shape) > 1 else 1
            self._position_frames = 0
            self._recent_output_samples = None
            self._pending_finish = False
            self._duration_ms = int((len(samples) / self._sample_rate) * 1000)
            self._configure_filters_locked(reset=True)
        self._last_emitted_position = -1
        self.durationChanged.emit(self._duration_ms)
        self.positionChanged.emit(0)

    def setDecodedSource(
        self,
        samples,
        sample_rate: int,
        *,
        assume_prepared: bool = False,
    ) -> None:
        import numpy as np

        self.stop()
        if samples is None:
            self.setSource(QUrl())
            return
        prepared = np.asarray(samples, dtype=np.float32)
        if prepared.ndim == 1:
            prepared = prepared.reshape(-1, 1)
        if prepared.size <= 0:
            self.setSource(QUrl())
            return
        if not assume_prepared:
            prepared = np.clip(prepared, -1.0, 1.0)
        with self._lock:
            self._samples = prepared
            self._sample_rate = max(1, int(sample_rate or 44100))
            self._channels = int(self._samples.shape[1]) if len(self._samples.shape) > 1 else 1
            self._position_frames = 0
            self._recent_output_samples = None
            self._pending_finish = False
            self._duration_ms = int((len(self._samples) / self._sample_rate) * 1000)
            self._configure_filters_locked(reset=True)
        self._last_emitted_position = -1
        self.durationChanged.emit(self._duration_ms)
        self.positionChanged.emit(0)

    def decoded_source_snapshot(self):
        with self._lock:
            if self._samples is None:
                return None
            return self._samples, int(self._sample_rate)

    def duration(self) -> int:
        return int(self._duration_ms)

    def position(self) -> int:
        with self._lock:
            return int((self._position_frames / max(1, self._sample_rate)) * 1000)

    def playbackState(self):
        return self._state

    def play(self) -> None:
        with self._lock:
            if self._samples is None or len(self._samples) <= 0:
                return
            if self._position_frames >= len(self._samples):
                self._position_frames = 0
            self._pending_finish = False
        if not self._start_sink():
            return
        self._set_state(QMediaPlayer.PlaybackState.PlayingState)
        self._position_timer.start()
        self._spectrum_timer.start()

    def pause(self) -> None:
        if self._state != QMediaPlayer.PlaybackState.PlayingState:
            return
        self._stop_sink()
        self._set_state(QMediaPlayer.PlaybackState.PausedState)
        self._position_timer.stop()
        self._spectrum_timer.stop()
        self._emit_position(force=True)
        self.spectrumFrameChanged.emit([])

    def stop(self) -> None:
        self._stop_sink()
        self._position_timer.stop()
        self._spectrum_timer.stop()
        with self._lock:
            self._position_frames = 0
            self._pending_finish = False
            self._recent_output_samples = None
            self._reset_filter_state_locked()
        self._set_state(QMediaPlayer.PlaybackState.StoppedState)
        self._emit_position(force=True)
        self.spectrumFrameChanged.emit([])

    def setPosition(self, position_ms: int) -> None:
        with self._lock:
            target = int((max(0, int(position_ms)) / 1000.0) * self._sample_rate)
            if self._samples is not None:
                target = max(0, min(target, len(self._samples)))
            self._position_frames = target
            self._pending_finish = False
            self._recent_output_samples = None
            self._reset_filter_state_locked()
        self._emit_position(force=True)

    def _set_state(self, state) -> None:
        if self._state == state:
            return
        self._state = state
        self.playbackStateChanged.emit(state)

    def _audio_format(self) -> QAudioFormat:
        fmt = QAudioFormat()
        fmt.setSampleRate(max(1, int(self._sample_rate)))
        fmt.setChannelCount(max(1, int(self._channels)))
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        return fmt

    def buffer_byte_count(self) -> int:
        bytes_per_frame = max(1, int(self._channels)) * 2
        return max(1, int(self.BUFFER_FRAMES)) * bytes_per_frame

    def _start_sink(self) -> bool:
        self._stop_sink()
        fmt = self._audio_format()
        device = QMediaDevices.defaultAudioOutput()
        try:
            sink = QAudioSink(device, fmt, self)
        except TypeError:
            try:
                sink = QAudioSink(fmt, self)
            except Exception:
                return False
        except Exception:
            return False
        try:
            sink.setBufferSize(self.buffer_byte_count() * max(1, int(self.SINK_BUFFER_BLOCKS)))
        except Exception:
            pass
        self._sink = sink
        self._sync_sink_volume()
        try:
            self._sink_io = sink.start()
        except Exception:
            self._sink = None
            self._sink_io = None
            try:
                sink.stop()
            except Exception:
                pass
            sink.deleteLater()
            return False
        if self._sink_io is None:
            self._sink = None
            try:
                sink.stop()
            except Exception:
                pass
            sink.deleteLater()
            return False
        self._render_timer.start()
        self._push_audio()
        return True

    def _stop_sink(self) -> None:
        self._render_timer.stop()
        self._sink_io = None
        sink = self._sink
        self._sink = None
        if sink is not None:
            try:
                sink.stop()
            except Exception:
                pass
            sink.deleteLater()

    def _push_audio(self) -> None:
        sink = self._sink
        sink_io = self._sink_io
        if sink is None or sink_io is None:
            return

        block_size = self.buffer_byte_count()
        try:
            bytes_free = int(sink.bytesFree())
        except Exception:
            bytes_free = block_size

        blocks_written = 0
        while bytes_free >= block_size and blocks_written < max(1, int(self.SINK_BUFFER_BLOCKS)):
            data = self._read_audio_bytes(min(block_size, bytes_free))
            if not data:
                should_finish = False
                with self._lock:
                    if self._samples is not None and self._pending_finish:
                        should_finish = self._position_frames >= len(self._samples)
                if should_finish and self._state == QMediaPlayer.PlaybackState.PlayingState:
                    self._finish_playback()
                return
            try:
                written = int(sink_io.write(data))
            except Exception:
                self._stop_sink()
                return
            if written <= 0:
                return
            bytes_free -= written
            blocks_written += 1

    def _sync_sink_volume(self) -> None:
        sink = self._sink
        if sink is None:
            return
        volume = 1.0
        muted = False
        if self._audio_output is not None:
            try:
                volume = float(self._audio_output.volume())
            except Exception:
                volume = 1.0
            try:
                muted = bool(self._audio_output.isMuted())
            except Exception:
                muted = False
        try:
            sink.setVolume(0.0 if muted else max(0.0, min(1.0, volume)))
        except Exception:
            pass

    def _configure_filters_locked(self, *, reset: bool) -> None:
        gains = list(self._equalizer_settings.get("gains") or [])
        enabled = bool(self._equalizer_settings.get("enabled"))
        channels = max(1, int(self._channels))
        for index, (filter_, band) in enumerate(zip(self._filters, EQUALIZER_BANDS, strict=False)):
            gain = float(gains[index]) if enabled and index < len(gains) else 0.0
            filter_.configure(
                filter_type=band.filter_type,
                frequency_hz=band.frequency_hz,
                q=band.q,
                gain_db=gain,
                sample_rate=self._sample_rate,
                channels=channels,
            )
            if reset:
                filter_.reset(channels)

    def _reset_filter_state_locked(self) -> None:
        channels = max(1, int(self._channels))
        for filter_ in self._filters:
            filter_.reset(channels)

    def _read_audio_bytes(self, maxlen: int) -> bytes:
        import numpy as np

        bytes_per_frame = max(1, int(self._channels)) * 2
        requested_frames = max(
            1,
            min(int(self.BUFFER_FRAMES), int(maxlen) // bytes_per_frame),
        )
        with self._lock:
            if self._samples is None or self._position_frames >= len(self._samples):
                self._pending_finish = True
                return b""
            start = int(self._position_frames)
            end = min(len(self._samples), start + requested_frames)
            chunk = self._samples[start:end].astype(np.float64, copy=True)
            self._position_frames = end
            if end >= len(self._samples):
                self._pending_finish = True
            if bool(self._equalizer_settings.get("enabled")):
                for filter_ in self._filters:
                    chunk = filter_.process(chunk)
            chunk = self._apply_pan_locked(chunk)
            self._remember_output_samples_locked(chunk)
        chunk = np.clip(chunk, -0.98, 0.98)
        pcm = (chunk * 32767.0).astype("<i2", copy=False)
        return pcm.tobytes()

    def _apply_pan_locked(self, samples):
        if samples is None or getattr(samples, "size", 0) <= 0:
            return samples
        if len(getattr(samples, "shape", ())) < 2 or samples.shape[1] < 2:
            return samples
        try:
            pan = float(self._equalizer_settings.get("pan", 0.0))
        except (TypeError, ValueError):
            pan = 0.0
        pan = max(-1.0, min(1.0, pan))
        if abs(pan) < 0.001:
            return samples
        output = samples.copy()
        left_gain = 1.0 if pan <= 0.0 else 1.0 - pan
        right_gain = 1.0 + pan if pan < 0.0 else 1.0
        output[:, 0] *= left_gain
        output[:, 1] *= right_gain
        return output

    def _remember_output_samples_locked(self, samples) -> None:
        import numpy as np

        if samples is None or samples.size <= 0:
            return
        output = samples.astype(np.float64, copy=True)
        history_frames = max(int(self.BUFFER_FRAMES) * 4, 4096)
        recent = self._recent_output_samples
        if recent is None or getattr(recent, "shape", (0, 0))[1:] != output.shape[1:]:
            self._recent_output_samples = output[-history_frames:]
            return
        combined = np.concatenate((recent, output), axis=0)
        self._recent_output_samples = combined[-history_frames:]

    def _emit_spectrum_tick(self) -> None:
        import numpy as np

        if self._state != QMediaPlayer.PlaybackState.PlayingState:
            return

        with self._lock:
            if self._samples is None or len(self._samples) <= 0:
                return
            sample_rate = self._sample_rate
            recent = self._recent_output_samples
            if recent is not None and len(recent) >= 32:
                chunk = recent.astype(np.float64, copy=True)
                settings = None
            else:
                settings = normalize_equalizer_settings(self._equalizer_settings)
                recent = None
            end = max(0, min(int(self._position_frames), len(self._samples)))
            if end <= 0:
                return
            if recent is None:
                window_frames = min(
                    len(self._samples),
                    max(int(self.BUFFER_FRAMES) * 2, 2048),
                )
                start = max(0, end - window_frames)
                chunk = self._samples[start:end].astype(np.float64, copy=True)
        self._publish_spectrum_frame(chunk, sample_rate, settings)

    def _publish_spectrum_frame(
        self,
        samples,
        sample_rate: int,
        settings: dict[str, object] | None = None,
    ) -> None:
        import numpy as np

        if samples is None or samples.size <= 0:
            return
        if len(samples) < 32:
            return

        mono = samples.mean(axis=1) if len(samples.shape) > 1 else samples
        mono = mono.astype(np.float64, copy=False)
        mono = mono - float(np.mean(mono))
        if not np.any(np.abs(mono) > 0.000001):
            return

        window = np.hanning(len(mono))
        spectrum = np.abs(np.fft.rfft(mono * window))
        freqs = np.fft.rfftfreq(len(mono), 1.0 / max(1, int(sample_rate)))
        nyquist = max(1.0, float(sample_rate) / 2.0)
        min_hz = max(self.SPECTRUM_MIN_HZ, float(sample_rate) / max(1, len(mono)))
        max_hz = min(self.SPECTRUM_MAX_HZ, nyquist * 0.94)
        if max_hz <= min_hz:
            return

        edges = np.geomspace(min_hz, max_hz, int(self.SPECTRUM_BINS) + 1)
        peaks = np.zeros(int(self.SPECTRUM_BINS), dtype=np.float64)
        for index in range(int(self.SPECTRUM_BINS)):
            indexes = np.where((freqs >= edges[index]) & (freqs < edges[index + 1]))[0]
            if len(indexes) == 0:
                center = (edges[index] + edges[index + 1]) / 2.0
                indexes = np.array([int(np.argmin(np.abs(freqs - center)))])
            peaks[index] = float(np.max(spectrum[indexes])) if len(indexes) else 0.0

        centers = np.sqrt(edges[:-1] * edges[1:])
        if settings is not None:
            peaks = peaks * self._equalizer_response_for_frequencies(
                centers,
                settings,
                sample_rate,
            )
        low_weight = 0.36 + (0.64 / (1.0 + ((92.0 / np.maximum(centers, 1.0)) ** 1.25)))
        high_taper = 0.74 + (0.26 / (1.0 + ((centers / 15000.0) ** 1.7)))
        presence_lift = 0.86 + (
            0.14 * np.exp(-0.5 * ((np.log2(np.maximum(centers, 1.0) / 2600.0) / 2.1) ** 2))
        )
        weighted = peaks * low_weight * high_taper * presence_lift
        levels = np.log1p(weighted * 18.0)
        frame_ref = float(np.percentile(levels, 94)) if levels.size else 0.0
        fast_frames = 0
        with self._lock:
            fast_frames = int(self._spectrum_fast_frames)
            if self._spectrum_fast_frames > 0:
                self._spectrum_fast_frames -= 1

        if self._spectrum_reference <= 0.00001:
            self._spectrum_reference = frame_ref
        elif fast_frames > 0:
            self._spectrum_reference = (self._spectrum_reference * 0.992) + (frame_ref * 0.008)
        elif frame_ref > self._spectrum_reference:
            self._spectrum_reference = (self._spectrum_reference * 0.9) + (frame_ref * 0.1)
        else:
            self._spectrum_reference = (self._spectrum_reference * 0.985) + (frame_ref * 0.015)
        reference = max(0.00001, float(self._spectrum_reference) * 1.18)
        normalized = np.clip(levels / reference, 0.0, 1.24)
        normalized = np.power(normalized, 0.84)

        if self._spectrum_smoothed is None or len(self._spectrum_smoothed) != len(normalized):
            smoothed = normalized
        else:
            previous = self._spectrum_smoothed
            attack = 0.62 if fast_frames > 0 else 0.48
            release = 0.34 if fast_frames > 0 else 0.14
            coeff = np.where(normalized > previous, attack, release)
            smoothed = previous + ((normalized - previous) * coeff)
        self._spectrum_smoothed = smoothed
        self.spectrumFrameChanged.emit([float(max(0.0, min(1.24, value))) for value in smoothed])

    def _equalizer_response_for_frequencies(
        self,
        frequencies,
        settings: dict[str, object],
        sample_rate: int,
    ):
        import numpy as np

        normalized = normalize_equalizer_settings(settings)
        if not bool(normalized.get("enabled")):
            return np.ones_like(frequencies, dtype=np.float64)

        freqs = np.asarray(frequencies, dtype=np.float64)
        freqs = np.clip(freqs, 1.0, max(1.0, (float(sample_rate) / 2.0) * 0.98))
        z1 = np.exp(-1j * ((2.0 * np.pi * freqs) / max(1, int(sample_rate))))
        z2 = z1 * z1
        response = np.ones_like(freqs, dtype=np.float64)
        for band, gain in zip(EQUALIZER_BANDS, normalized.get("gains") or [], strict=False):
            gain = float(gain)
            if abs(gain) < 0.01:
                continue
            b0, b1, b2, a1, a2 = equalizer_biquad_coefficients(
                band.filter_type,
                band.frequency_hz,
                band.q,
                gain,
                sample_rate,
            )
            numerator = b0 + (b1 * z1) + (b2 * z2)
            denominator = 1.0 + (a1 * z1) + (a2 * z2)
            safe_denominator = np.where(np.abs(denominator) > 1e-12, denominator, 1e-12)
            response *= np.abs(numerator / safe_denominator)
        return np.clip(response, 0.12, 3.8)

    def _emit_position(self, *, force: bool = False) -> None:
        position = self.position()
        if force or position != self._last_emitted_position:
            self._last_emitted_position = position
            self.positionChanged.emit(position)

    def _emit_position_tick(self) -> None:
        self._emit_position()
        should_finish = False
        with self._lock:
            if self._samples is not None and self._pending_finish:
                should_finish = self._position_frames >= len(self._samples)
        if should_finish and self._state == QMediaPlayer.PlaybackState.PlayingState:
            self._finish_playback()

    def _finish_playback(self) -> None:
        self._stop_sink()
        self._position_timer.stop()
        self._spectrum_timer.stop()
        self._set_state(QMediaPlayer.PlaybackState.StoppedState)
        self._emit_position(force=True)
        self.spectrumFrameChanged.emit([])
        self.mediaStatusChanged.emit(QMediaPlayer.MediaStatus.EndOfMedia)

"""Cached static waveform previews for primary track audio."""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
import platform
import queue
import shutil
import sqlite3
import struct
import subprocess
import threading
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from isrc_manager.file_storage import STORAGE_MODE_DATABASE

if TYPE_CHECKING:
    from isrc_manager.services.tracks import TrackMediaSourceHandle, TrackService

WAVEFORM_CACHE_ANALYZER_VERSION = 4
WAVEFORM_CACHE_WIDTH = 1600
WAVEFORM_CACHE_HEIGHT = 172
WAVEFORM_DB_FLOOR = -96.0
WAVEFORM_DB_STOPS = (0.0, -3.0, -6.0, -12.0, -18.0, -30.0, -48.0, -72.0, -96.0)
WAVEFORM_COLOR_SOFTEN_AMOUNT = 0.13
_FINGERPRINT_EDGE_BYTES = 64 * 1024


@dataclass(slots=True)
class CachedWaveform:
    track_id: int
    source_fingerprint: str
    source_size_bytes: int
    source_filename: str
    source_storage_mode: str
    analyzer_version: int
    width_px: int
    height_px: int
    peaks: list[tuple[float, float]]
    light_preview_png: bytes
    dark_preview_png: bytes
    generated_at: str


@dataclass(slots=True)
class WaveformCacheRunSummary:
    total_audio_tracks: int = 0
    checked: int = 0
    rendered: int = 0
    reused: int = 0
    skipped: int = 0
    errors: int = 0


@dataclass(slots=True)
class WaveformCacheInspection:
    total_rows: int = 0
    valid_rows: int = 0
    orphaned_rows: int = 0
    stale_rows: int = 0
    missing_audio_rows: int = 0
    orphaned_track_ids: tuple[int, ...] = ()
    stale_track_ids: tuple[int, ...] = ()
    missing_audio_track_ids: tuple[int, ...] = ()
    details: tuple[str, ...] = ()

    @property
    def issue_count(self) -> int:
        return int(self.orphaned_rows + self.stale_rows + self.missing_audio_rows)


def ensure_audio_waveform_cache_schema(conn: sqlite3.Connection) -> None:
    table_names = {
        str(row[0])
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        if row and row[0]
    }
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS TrackAudioWaveformCache (
            track_id INTEGER PRIMARY KEY,
            source_fingerprint TEXT NOT NULL,
            source_size_bytes INTEGER NOT NULL DEFAULT 0,
            source_filename TEXT,
            source_storage_mode TEXT,
            source_mime_type TEXT,
            analyzer_version INTEGER NOT NULL,
            width_px INTEGER NOT NULL,
            height_px INTEGER NOT NULL,
            peaks_json TEXT NOT NULL,
            light_preview_png BLOB NOT NULL,
            dark_preview_png BLOB NOT NULL,
            generated_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY(track_id) REFERENCES Tracks(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_track_audio_waveform_cache_fingerprint
        ON TrackAudioWaveformCache(source_fingerprint)
        """
    )
    if "Tracks" in table_names:
        conn.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_tracks_waveform_cache_delete
            AFTER DELETE ON Tracks
            FOR EACH ROW
            BEGIN
                DELETE FROM TrackAudioWaveformCache WHERE track_id = OLD.id;
            END
            """
        )


def delete_audio_waveform_cache(
    conn: sqlite3.Connection,
    track_id: int,
    *,
    cursor: sqlite3.Cursor | None = None,
) -> int:
    cur = cursor or conn.cursor()
    ensure_audio_waveform_cache_schema(conn)
    before = cur.execute(
        "SELECT COUNT(*) FROM TrackAudioWaveformCache WHERE track_id=?",
        (int(track_id),),
    ).fetchone()
    cur.execute("DELETE FROM TrackAudioWaveformCache WHERE track_id=?", (int(track_id),))
    return int(before[0] or 0) if before else 0


def _json_to_peaks(value: object) -> list[tuple[float, float]]:
    try:
        raw = json.loads(str(value or "[]"))
    except Exception:
        return []
    peaks: list[tuple[float, float]] = []
    if not isinstance(raw, list):
        return peaks
    for item in raw:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        try:
            lo = max(-1.0, min(0.0, float(item[0])))
            hi = max(0.0, min(1.0, float(item[1])))
        except (TypeError, ValueError):
            continue
        peaks.append((lo, hi))
    return peaks


def _peaks_to_json(peaks: list[tuple[float, float]]) -> str:
    return json.dumps(
        [[round(float(lo), 6), round(float(hi), 6)] for lo, hi in peaks],
        separators=(",", ":"),
    )


def _which(name: str) -> str | None:
    path = shutil.which(name)
    if path:
        return path
    sysname = platform.system().lower()
    if sysname == "darwin":
        search_dirs = ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin"]
    elif sysname == "linux":
        search_dirs = ["/usr/bin", "/usr/local/bin"]
    elif sysname == "windows":
        search_dirs = [
            r"C:\Program Files\ffmpeg\bin",
            r"C:\ffmpeg\bin",
            r"C:\ProgramData\chocolatey\bin",
            os.path.expandvars(r"%USERPROFILE%\scoop\shims"),
        ]
    else:
        search_dirs = []
    candidates = [name]
    if sysname == "windows" and not name.lower().endswith(".exe"):
        candidates.append(name + ".exe")
    for directory in search_dirs:
        for candidate in candidates:
            full_path = os.path.join(directory, candidate)
            if os.path.exists(full_path):
                return full_path
    return None


def _append_peak(peaks: list[tuple[float, float]], left_peak: float, right_peak: float) -> None:
    left = max(0.0, min(1.0, abs(float(left_peak))))
    right = max(0.0, min(1.0, abs(float(right_peak))))
    peaks.append((-right, left))


def _load_wave_peaks(path: str, buckets: int) -> list[tuple[float, float]] | None:
    import wave

    with open(path, "rb") as handle:
        head = handle.read(12)
    if len(head) < 12 or head[:4] != b"RIFF":
        return None
    if head[8:12] != b"WAVE":
        return []

    try:
        wav_file = wave.open(path, "rb")
    except Exception:
        return []
    with wav_file as wav:
        channels = max(1, wav.getnchannels())
        sample_width = wav.getsampwidth()
        frame_count = wav.getnframes()
        if frame_count <= 0:
            return []
        step = max(1, frame_count // max(1, int(buckets)))
        full_scale = (
            32768.0 if sample_width == 2 else (8388608.0 if sample_width == 3 else 2147483648.0)
        )
        peaks: list[tuple[float, float]] = []
        for frame_start in range(0, frame_count, step):
            wav.setpos(frame_start)
            raw = wav.readframes(min(step, frame_count - frame_start))
            if not raw:
                continue
            if sample_width == 2:
                count = len(raw) // 2
                if count <= 0:
                    continue
                values = struct.unpack("<" + "h" * count, raw)
                usable = (len(values) // channels) * channels
                if usable <= 0:
                    continue
                left_values = values[:usable:channels]
                right_values = values[1:usable:channels] if channels > 1 else left_values
                _append_peak(
                    peaks,
                    max(abs(value) for value in left_values) / full_scale,
                    max(abs(value) for value in right_values) / full_scale,
                )
            elif sample_width == 3:
                count = len(raw) // (3 * channels)
                if count <= 0:
                    continue
                step_bytes = 3 * channels
                left_peak = 0
                right_peak = 0

                def _read_s24(offset: int) -> int:
                    b0, b1, b2 = raw[offset], raw[offset + 1], raw[offset + 2]
                    value = b0 | (b1 << 8) | (b2 << 16)
                    if value & 0x800000:
                        value -= 0x1000000
                    return value

                for offset in range(0, count * step_bytes, step_bytes):
                    left = _read_s24(offset)
                    right = _read_s24(offset + 3) if channels > 1 else left
                    left_peak = max(left_peak, abs(left))
                    right_peak = max(right_peak, abs(right))
                _append_peak(peaks, left_peak / full_scale, right_peak / full_scale)
            elif sample_width == 4:
                count = len(raw) // 4
                if count <= 0:
                    continue
                values = struct.unpack("<" + "i" * count, raw)
                usable = (len(values) // channels) * channels
                if usable <= 0:
                    continue
                left_values = values[:usable:channels]
                right_values = values[1:usable:channels] if channels > 1 else left_values
                _append_peak(
                    peaks,
                    max(abs(value) for value in left_values) / full_scale,
                    max(abs(value) for value in right_values) / full_scale,
                )
        return peaks


def _load_ffmpeg_peaks(path: str, buckets: int) -> list[tuple[float, float]] | None:
    ffmpeg = _which("ffmpeg")
    if not ffmpeg:
        return None
    sample_rate = 44100
    total_samples = None
    ffprobe = _which("ffprobe")
    if ffprobe:
        with suppress(Exception):
            duration_text = (
                subprocess.check_output(
                    [
                        ffprobe,
                        "-v",
                        "error",
                        "-show_entries",
                        "format=duration",
                        "-of",
                        "default=nw=1:nk=1",
                        os.fspath(path),
                    ],
                    stderr=subprocess.STDOUT,
                    timeout=8,
                )
                .decode("utf-8", "replace")
                .strip()
            )
            if duration_text:
                duration = float(duration_text)
                if duration > 0:
                    total_samples = int(sample_rate * duration)
    target_step = max(1, (total_samples // buckets) if total_samples else (sample_rate // 100))
    try:
        process = subprocess.Popen(
            [
                ffmpeg,
                "-v",
                "error",
                "-nostdin",
                "-vn",
                "-i",
                os.fspath(path),
                "-f",
                "s16le",
                "-acodec",
                "pcm_s16le",
                "-ac",
                "2",
                "-ar",
                str(sample_rate),
                "-",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except Exception:
        return None
    if process.stdout is None:
        with suppress(Exception):
            process.kill()
        return None

    peaks: list[tuple[float, float]] = []
    frame_bytes = 4
    full_scale = 32768.0
    need = target_step
    left_peak = 0.0
    right_peak = 0.0
    bucket_had_sample = False
    buffer = bytearray()
    try:
        while True:
            chunk = process.stdout.read(8192)
            if not chunk:
                break
            buffer.extend(chunk)
            frame_count = len(buffer) // frame_bytes
            if frame_count <= 0:
                continue
            offset_frames = 0
            while frame_count > 0:
                take = min(need, frame_count)
                data_len = take * frame_bytes
                data = bytes(
                    buffer[offset_frames * frame_bytes : offset_frames * frame_bytes + data_len]
                )
                for index in range(0, len(data), frame_bytes):
                    left_value = struct.unpack_from("<h", data, index)[0] / full_scale
                    right_value = struct.unpack_from("<h", data, index + 2)[0] / full_scale
                    left_peak = max(left_peak, abs(left_value))
                    right_peak = max(right_peak, abs(right_value))
                    bucket_had_sample = True
                need -= take
                offset_frames += take
                frame_count -= take
                if need == 0:
                    if bucket_had_sample:
                        _append_peak(peaks, left_peak, right_peak)
                    left_peak = 0.0
                    right_peak = 0.0
                    bucket_had_sample = False
                    need = target_step
            del buffer[: offset_frames * frame_bytes]
        if bucket_had_sample:
            _append_peak(peaks, left_peak, right_peak)
    finally:
        with suppress(Exception):
            process.stdout.close()
        with suppress(Exception):
            process.wait(timeout=2)
        if process.poll() is None:
            with suppress(Exception):
                process.kill()
    return peaks or []


def _load_qt_decoder_peaks(path: str, buckets: int) -> list[tuple[float, float]] | None:
    try:
        from PySide6.QtCore import QEventLoop, QTimer, QUrl
        from PySide6.QtMultimedia import QAudioDecoder, QAudioFormat
    except Exception:
        return None

    decoder = QAudioDecoder()
    if not decoder.isSupported():
        return None
    state = {
        "peaks": [],
        "target_step": None,
        "need": None,
        "left_peak": 0.0,
        "right_peak": 0.0,
        "bucket_had_sample": False,
        "had_buffer": False,
    }
    loop = QEventLoop()
    timeout = QTimer()
    timeout.setSingleShot(True)

    def _sample_value(raw: bytes, offset: int, sample_format) -> float | None:
        if sample_format == QAudioFormat.SampleFormat.UInt8:
            return (raw[offset] - 128.0) / 128.0
        if sample_format == QAudioFormat.SampleFormat.Int16:
            return struct.unpack_from("<h", raw, offset)[0] / 32768.0
        if sample_format == QAudioFormat.SampleFormat.Int32:
            return struct.unpack_from("<i", raw, offset)[0] / 2147483648.0
        if sample_format == QAudioFormat.SampleFormat.Float:
            return max(-1.0, min(1.0, struct.unpack_from("<f", raw, offset)[0]))
        return None

    def _finish_pending_peak() -> None:
        if state["bucket_had_sample"]:
            _append_peak(state["peaks"], state["left_peak"], state["right_peak"])
            state["left_peak"] = 0.0
            state["right_peak"] = 0.0
            state["bucket_had_sample"] = False

    def _on_buffer_ready() -> None:
        audio_buffer = decoder.read()
        if not audio_buffer.isValid():
            return
        fmt = audio_buffer.format()
        frame_bytes = fmt.bytesPerFrame()
        sample_bytes = fmt.bytesPerSample()
        channels = max(1, fmt.channelCount())
        if frame_bytes <= 0:
            frame_bytes = sample_bytes * channels
        if frame_bytes <= 0:
            return
        sample_format = fmt.sampleFormat()
        if sample_format not in (
            QAudioFormat.SampleFormat.UInt8,
            QAudioFormat.SampleFormat.Int16,
            QAudioFormat.SampleFormat.Int32,
            QAudioFormat.SampleFormat.Float,
        ):
            return
        if state["target_step"] is None:
            sample_rate = fmt.sampleRate() or 44100
            duration_ms = decoder.duration()
            total_samples = (
                int((sample_rate * duration_ms) / 1000) if duration_ms and duration_ms > 0 else None
            )
            state["target_step"] = max(
                1, (total_samples // buckets) if total_samples else (sample_rate // 100)
            )
            state["need"] = state["target_step"]
        raw = bytes(audio_buffer.data())
        frame_count = len(raw) // frame_bytes
        if frame_count <= 0:
            return
        state["had_buffer"] = True
        for frame_index in range(frame_count):
            offset = frame_index * frame_bytes
            left_value = _sample_value(raw, offset, sample_format)
            if left_value is None:
                continue
            right_value = left_value
            if channels > 1 and sample_bytes > 0:
                decoded_right = _sample_value(raw, offset + sample_bytes, sample_format)
                if decoded_right is not None:
                    right_value = decoded_right
            state["left_peak"] = max(state["left_peak"], abs(left_value))
            state["right_peak"] = max(state["right_peak"], abs(right_value))
            state["bucket_had_sample"] = True
            state["need"] -= 1
            if state["need"] == 0:
                _finish_pending_peak()
                state["need"] = state["target_step"]

    decoder.bufferReady.connect(_on_buffer_ready)
    decoder.finished.connect(loop.quit)
    decoder.error.connect(lambda *_args: loop.quit())
    timeout.timeout.connect(lambda: (decoder.stop(), loop.quit()))
    decoder.setSource(QUrl.fromLocalFile(os.fspath(path)))
    decoder.start()
    timeout.start(5000)
    loop.exec()
    timeout.stop()
    _finish_pending_peak()
    if state["peaks"]:
        return state["peaks"]
    return [(-0.0, 0.0)] if state["had_buffer"] else None


def load_audio_waveform_peaks(
    path: str, width_px: int = WAVEFORM_CACHE_WIDTH
) -> list[tuple[float, float]]:
    width_px = max(1, int(width_px or WAVEFORM_CACHE_WIDTH))
    buckets = width_px
    suffix = Path(path).suffix.lower()
    wave_peaks = _load_wave_peaks(path, buckets)
    if wave_peaks is not None:
        return wave_peaks
    if suffix == ".wav":
        return []
    peaks = _load_ffmpeg_peaks(path, buckets)
    if peaks is not None:
        return peaks
    peaks = _load_qt_decoder_peaks(path, buckets)
    if peaks is not None:
        return peaks
    return []


def _decode_mono_audio_for_waveform_colors(
    path: str,
    *,
    target_sr: int = 22050,
):
    try:
        import numpy as np
    except Exception:
        return None, 0
    try:
        import soundfile as sf
    except Exception:
        return _decode_mono_audio_with_ffmpeg(path, target_sr=target_sr)
    try:
        data, sample_rate = sf.read(path, dtype="float32", always_2d=True)
    except Exception:
        return _decode_mono_audio_with_ffmpeg(path, target_sr=target_sr)
    if data.size <= 0:
        return None, 0
    mono = np.mean(data, axis=1, dtype=np.float32)
    return _resample_mono_audio(mono, int(sample_rate or target_sr), target_sr), target_sr


def _decode_mono_audio_with_ffmpeg(
    path: str,
    *,
    target_sr: int,
):
    ffmpeg = _which("ffmpeg")
    if not ffmpeg:
        return None, 0
    try:
        import numpy as np
    except Exception:
        return None, 0
    try:
        raw = subprocess.check_output(
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
                "1",
                "-ar",
                str(int(target_sr)),
                "-",
            ],
            stderr=subprocess.STDOUT,
            timeout=45,
        )
    except Exception:
        return None, 0
    if not raw:
        return None, 0
    data = np.frombuffer(raw, dtype="<f4").astype(np.float32, copy=False)
    if data.size <= 0:
        return None, 0
    return data, int(target_sr)


def _resample_mono_audio(mono, sample_rate: int, target_sr: int):
    if sample_rate <= 0 or sample_rate == target_sr:
        return mono
    try:
        from scipy.signal import resample_poly

        divisor = math.gcd(int(sample_rate), int(target_sr))
        return resample_poly(
            mono,
            int(target_sr) // divisor,
            int(sample_rate) // divisor,
        ).astype("float32", copy=False)
    except Exception:
        import numpy as np

        target_count = max(1, int(round(len(mono) * (float(target_sr) / float(sample_rate)))))
        source_positions = np.linspace(0, max(0, len(mono) - 1), target_count)
        return np.interp(source_positions, np.arange(len(mono)), mono).astype("float32")


def _frequency_band_masks(frequencies):
    low_mask = (frequencies >= 30.0) & (frequencies < 190.0)
    low_mid_mask = (frequencies >= 190.0) & (frequencies < 720.0)
    mid_mask = (frequencies >= 720.0) & (frequencies < 2600.0)
    high_mask = frequencies >= 2600.0
    return low_mask, low_mid_mask, mid_mask, high_mask


def _frequency_color_from_bands(
    low: float,
    low_mid: float,
    mid: float,
    high: float,
    amplitude: float,
) -> tuple[int, int, int]:
    total = max(1e-12, float(low) + float(low_mid) + float(mid) + float(high))
    low_ratio = float(low) / total
    low_mid_ratio = float(low_mid) / total
    mid_ratio = float(mid) / total
    high_ratio = float(high) / total
    amplitude = max(0.0, min(1.0, float(amplitude)))

    red = (250.0 * low_ratio) + (255.0 * low_mid_ratio) + (228.0 * mid_ratio) + (40.0 * high_ratio)
    green = (
        (32.0 * low_ratio) + (112.0 * low_mid_ratio) + (205.0 * mid_ratio) + (228.0 * high_ratio)
    )
    blue = (18.0 * low_ratio) + (24.0 * low_mid_ratio) + (42.0 * mid_ratio) + (116.0 * high_ratio)

    if high_ratio > 0.42 and low_ratio < 0.24:
        green += 35.0 * high_ratio
        blue += 42.0 * high_ratio
    if low_ratio > 0.45:
        red += 28.0 * low_ratio
        green *= 0.82
        blue *= 0.72

    brightness = 0.52 + (0.48 * (amplitude**0.45))
    return _soften_waveform_rgb(
        (
            int(max(0, min(255, red * brightness))),
            int(max(0, min(255, green * brightness))),
            int(max(0, min(255, blue * brightness))),
        )
    )


def load_audio_waveform_colors(
    path: str,
    width_px: int = WAVEFORM_CACHE_WIDTH,
) -> list[tuple[int, int, int]]:
    try:
        import numpy as np
    except Exception:
        return []
    width_px = max(1, int(width_px or WAVEFORM_CACHE_WIDTH))
    mono, sample_rate = _decode_mono_audio_for_waveform_colors(path)
    if mono is None or sample_rate <= 0 or len(mono) <= 0:
        return []

    mono = np.asarray(mono, dtype=np.float32)
    mono = np.nan_to_num(mono, copy=False)
    if mono.size <= 0:
        return []

    window_size = 2048
    if mono.size < window_size:
        padded = np.zeros(window_size, dtype=np.float32)
        padded[: mono.size] = mono
        mono = padded

    centers = np.linspace(0, mono.size - 1, width_px, dtype=np.float64).astype(np.int64)
    offsets = np.arange(window_size, dtype=np.int64) - (window_size // 2)
    indices = np.clip(centers[:, None] + offsets[None, :], 0, mono.size - 1)
    window = np.hanning(window_size).astype(np.float32)
    frames = mono[indices] * window[None, :]
    rms = np.sqrt(np.mean(frames * frames, axis=1))
    spectrum = np.abs(np.fft.rfft(frames, axis=1)) ** 2
    frequencies = np.fft.rfftfreq(window_size, d=1.0 / float(sample_rate))
    low_mask, low_mid_mask, mid_mask, high_mask = _frequency_band_masks(frequencies)
    low = spectrum[:, low_mask].sum(axis=1)
    low_mid = spectrum[:, low_mid_mask].sum(axis=1)
    mid = spectrum[:, mid_mask].sum(axis=1)
    high = spectrum[:, high_mask].sum(axis=1)
    amp_ref = float(np.percentile(rms, 95)) if rms.size else 0.0
    if amp_ref <= 1e-9:
        amp_ref = float(np.max(rms)) if rms.size else 1.0
    amp_ref = max(amp_ref, 1e-9)
    colors: list[tuple[int, int, int]] = []
    for index in range(width_px):
        colors.append(
            _frequency_color_from_bands(
                float(low[index]),
                float(low_mid[index]),
                float(mid[index]),
                float(high[index]),
                float(rms[index]) / amp_ref,
            )
        )
    return colors


def _resample_waveform_colors(
    colors: list[tuple[int, int, int]],
    width_px: int,
) -> list[tuple[int, int, int]]:
    width_px = max(1, int(width_px))
    if not colors:
        return []
    if len(colors) == width_px:
        return colors
    if len(colors) == 1:
        return [colors[0]] * width_px
    scale = (len(colors) - 1) / max(1, width_px - 1)
    return [colors[min(len(colors) - 1, int(round(index * scale)))] for index in range(width_px)]


def _fallback_waveform_rgb_for_peak(peak: float) -> tuple[int, int, int]:
    peak = max(0.0, min(1.0, float(peak)))
    if peak >= 0.72:
        return _soften_waveform_rgb((255, 45, 16))
    if peak >= 0.46:
        return _soften_waveform_rgb((255, 117, 18))
    if peak >= 0.24:
        return _soften_waveform_rgb((245, 206, 38))
    return _soften_waveform_rgb((35, 214, 95))


def _soften_waveform_rgb(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    amount = max(0.0, min(1.0, WAVEFORM_COLOR_SOFTEN_AMOUNT))
    red, green, blue = (max(0, min(255, int(channel))) for channel in rgb)
    luma = (0.2126 * red) + (0.7152 * green) + (0.0722 * blue)
    return (
        int(round((red * (1.0 - amount)) + (luma * amount))),
        int(round((green * (1.0 - amount)) + (luma * amount))),
        int(round((blue * (1.0 - amount)) + (luma * amount))),
    )


def _shade_waveform_rgb(
    rgb: tuple[int, int, int],
    *,
    peak: float,
    edge_ratio: float,
    light_background: bool,
) -> tuple[int, int, int, int]:
    peak = max(0.0, min(1.0, float(peak)))
    edge_ratio = max(0.0, min(1.0, float(edge_ratio)))
    if light_background:
        base_scale = 0.42 + (0.22 * peak)
        edge_lift = 0.26 * (edge_ratio**0.7)
        highlight = 0.04 * edge_ratio
    else:
        base_scale = 0.58 + (0.18 * peak)
        edge_lift = 0.30 * (edge_ratio**0.7)
        highlight = 0.10 * (edge_ratio**1.8)
    scale = min(1.18, base_scale + edge_lift)
    return (
        int(max(0, min(255, (rgb[0] * scale) + (255 * highlight)))),
        int(max(0, min(255, (rgb[1] * scale) + (255 * highlight)))),
        int(max(0, min(255, (rgb[2] * scale) + (255 * highlight)))),
        255,
    )


def _build_waveform_path(peaks: list[tuple[float, float]], rect):
    from PySide6.QtGui import QPainterPath

    path = QPainterPath()
    if not peaks:
        return path
    mid = rect.center().y()
    xscale = (rect.width() - 1.0) / max(1, len(peaks) - 1)
    amplitude = rect.height() * 0.45
    for index, (lo, hi) in enumerate(peaks):
        x_pos = rect.left() + (index * xscale)
        top_peak = max(0.0, min(1.0, float(hi)))
        bottom_peak = max(0.0, min(1.0, -float(lo)))
        if top_peak > 0.0:
            path.moveTo(x_pos, mid)
            path.lineTo(x_pos, mid - (top_peak * amplitude))
        if bottom_peak > 0.0:
            path.moveTo(x_pos, mid)
            path.lineTo(x_pos, mid + (bottom_peak * amplitude))
    return path


def _resample_peaks_to_width(
    peaks: list[tuple[float, float]], width_px: int
) -> list[tuple[float, float]]:
    width_px = max(1, int(width_px))
    if not peaks:
        return []
    if len(peaks) == width_px:
        return peaks
    if len(peaks) < width_px:
        if len(peaks) == 1:
            return [peaks[0]] * width_px
        scale = (len(peaks) - 1) / max(1, width_px - 1)
        return [peaks[min(len(peaks) - 1, int(round(index * scale)))] for index in range(width_px)]

    scale = len(peaks) / float(width_px)
    resampled: list[tuple[float, float]] = []
    for index in range(width_px):
        start = int(index * scale)
        end = max(start + 1, int((index + 1) * scale))
        bucket = peaks[start:end]
        low = min((float(item[0]) for item in bucket), default=0.0)
        high = max((float(item[1]) for item in bucket), default=0.0)
        resampled.append((max(-1.0, min(0.0, low)), max(0.0, min(1.0, high))))
    return resampled


def render_waveform_cache_png(
    peaks: list[tuple[float, float]],
    *,
    width_px: int = WAVEFORM_CACHE_WIDTH,
    height_px: int = WAVEFORM_CACHE_HEIGHT,
    light_background: bool,
    waveform_colors: list[tuple[int, int, int]] | None = None,
) -> bytes:
    if not peaks:
        return b""
    from PIL import Image

    width_px = max(1, int(width_px))
    height_px = max(1, int(height_px))
    peaks = _resample_peaks_to_width(peaks, width_px)
    waveform_colors = _resample_waveform_colors(list(waveform_colors or []), width_px)
    image = Image.new("RGBA", (width_px, height_px), (0, 0, 0, 0))
    center_y = (height_px - 1) / 2.0
    amplitude_px = max(1.0, height_px * 0.47)

    pixels = image.load()
    center_index = int(round(center_y))
    for x_pos, (low, high) in enumerate(peaks):
        top_peak = max(0.0, min(1.0, float(high)))
        bottom_peak = max(0.0, min(1.0, -float(low)))
        dominant_peak = max(top_peak, bottom_peak)
        if dominant_peak <= 0.0:
            continue
        base_rgb = (
            waveform_colors[x_pos]
            if x_pos < len(waveform_colors)
            else _fallback_waveform_rgb_for_peak(dominant_peak)
        )
        if top_peak > 0.0:
            start_y = max(0, min(height_px - 1, int(round(center_y - (top_peak * amplitude_px)))))
            end_y = max(0, min(height_px - 1, center_index))
            for y_pos in range(start_y, end_y + 1):
                edge_ratio = abs(float(y_pos) - center_y) / max(1.0, top_peak * amplitude_px)
                pixels[x_pos, y_pos] = _shade_waveform_rgb(
                    base_rgb,
                    peak=top_peak,
                    edge_ratio=edge_ratio,
                    light_background=light_background,
                )
        if bottom_peak > 0.0:
            start_y = max(0, min(height_px - 1, center_index))
            end_y = max(0, min(height_px - 1, int(round(center_y + (bottom_peak * amplitude_px)))))
            for y_pos in range(start_y, end_y + 1):
                edge_ratio = abs(float(y_pos) - center_y) / max(1.0, bottom_peak * amplitude_px)
                pixels[x_pos, y_pos] = _shade_waveform_rgb(
                    base_rgb,
                    peak=bottom_peak,
                    edge_ratio=edge_ratio,
                    light_background=light_background,
                )

    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def _read_edge_bytes(path: Path, size: int) -> tuple[bytes, bytes]:
    if size <= 0:
        return b"", b""
    edge = min(_FINGERPRINT_EDGE_BYTES, int(size))
    with path.open("rb") as handle:
        first = handle.read(edge)
        if size > edge:
            handle.seek(max(0, size - edge))
            last = handle.read(edge)
        else:
            last = b""
    return first, last


def audio_source_fingerprint(handle: "TrackMediaSourceHandle") -> str:
    digest = hashlib.blake2b(digest_size=20)
    if handle.source_bytes is not None:
        data = bytes(handle.source_bytes)
        return _bytes_edge_fingerprint(data, len(data))
    if handle.source_path is None:
        raise FileNotFoundError(handle.filename or handle.media_key)
    path = Path(handle.source_path)
    stat = path.stat()
    first, last = _read_edge_bytes(path, int(stat.st_size))
    digest.update(b"file-v1\0")
    digest.update(str(int(stat.st_size)).encode("ascii"))
    digest.update(b"\0")
    digest.update(str(int(stat.st_mtime_ns)).encode("ascii"))
    digest.update(b"\0")
    digest.update(first)
    digest.update(last)
    return digest.hexdigest()


def _bytes_edge_fingerprint(data: bytes, size: int) -> str:
    digest = hashlib.blake2b(digest_size=20)
    edge = min(_FINGERPRINT_EDGE_BYTES, int(size))
    digest.update(b"bytes-v1\0")
    digest.update(str(int(size)).encode("ascii"))
    digest.update(b"\0")
    digest.update(bytes(data[:edge]))
    if size > edge:
        digest.update(bytes(data[-edge:]))
    return digest.hexdigest()


class AudioWaveformCacheService:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def ensure_schema(self) -> None:
        ensure_audio_waveform_cache_schema(self.conn)

    @staticmethod
    def _cached_waveform_is_complete(cached: CachedWaveform | None) -> bool:
        return bool(
            cached is not None
            and cached.source_fingerprint
            and cached.analyzer_version == WAVEFORM_CACHE_ANALYZER_VERSION
            and cached.width_px == WAVEFORM_CACHE_WIDTH
            and cached.height_px == WAVEFORM_CACHE_HEIGHT
            and cached.peaks
            and cached.light_preview_png
            and cached.dark_preview_png
        )

    def _row_to_cached_waveform(self, row) -> CachedWaveform | None:
        if not row:
            return None
        return CachedWaveform(
            track_id=int(row["track_id"] if isinstance(row, sqlite3.Row) else row[0]),
            source_fingerprint=str(
                row["source_fingerprint"] if isinstance(row, sqlite3.Row) else row[1]
            ),
            source_size_bytes=int(
                row["source_size_bytes"] if isinstance(row, sqlite3.Row) else row[2] or 0
            ),
            source_filename=str(
                row["source_filename"] if isinstance(row, sqlite3.Row) else row[3] or ""
            ),
            source_storage_mode=str(
                row["source_storage_mode"] if isinstance(row, sqlite3.Row) else row[4] or ""
            ),
            analyzer_version=int(
                row["analyzer_version"] if isinstance(row, sqlite3.Row) else row[5] or 0
            ),
            width_px=int(row["width_px"] if isinstance(row, sqlite3.Row) else row[6] or 0),
            height_px=int(row["height_px"] if isinstance(row, sqlite3.Row) else row[7] or 0),
            peaks=_json_to_peaks(row["peaks_json"] if isinstance(row, sqlite3.Row) else row[8]),
            light_preview_png=bytes(
                row["light_preview_png"] if isinstance(row, sqlite3.Row) else row[9] or b""
            ),
            dark_preview_png=bytes(
                row["dark_preview_png"] if isinstance(row, sqlite3.Row) else row[10] or b""
            ),
            generated_at=str(
                row["generated_at"] if isinstance(row, sqlite3.Row) else row[11] or ""
            ),
        )

    def _fetch_cache_row(
        self,
        track_id: int,
        *,
        cursor: sqlite3.Cursor | None = None,
    ):
        cur = cursor or self.conn.cursor()
        return cur.execute(
            """
            SELECT track_id, source_fingerprint, source_size_bytes, source_filename,
                   source_storage_mode, analyzer_version, width_px, height_px,
                   peaks_json, light_preview_png, dark_preview_png, generated_at
            FROM TrackAudioWaveformCache
            WHERE track_id=?
            """,
            (int(track_id),),
        ).fetchone()

    def get_cached_waveform(
        self,
        track_id: int,
        *,
        cursor: sqlite3.Cursor | None = None,
        track_service: "TrackService" | None = None,
        validate_source: bool = False,
    ) -> CachedWaveform | None:
        """Return a usable cached preview without generating missing previews."""

        self.ensure_schema()
        cur = cursor or self.conn.cursor()
        cached = self._row_to_cached_waveform(self._fetch_cache_row(int(track_id), cursor=cur))
        if not self._cached_waveform_is_complete(cached):
            return None
        if validate_source:
            if track_service is None:
                return None
            try:
                fingerprint, _metadata = self._source_fingerprint_for_track(
                    track_service,
                    int(track_id),
                    cursor=cur,
                )
            except Exception:
                return None
            if cached.source_fingerprint != fingerprint:
                return None
        return cached

    def _track_audio_metadata(
        self,
        track_id: int,
        *,
        cursor: sqlite3.Cursor | None = None,
    ) -> dict[str, object]:
        cur = cursor or self.conn.cursor()
        row = cur.execute(
            """
            SELECT audio_file_path, audio_file_storage_mode, audio_file_filename,
                   audio_file_mime_type, audio_file_size_bytes,
                   audio_file_blob IS NOT NULL, length(audio_file_blob)
            FROM Tracks
            WHERE id=?
            """,
            (int(track_id),),
        ).fetchone()
        if not row:
            raise FileNotFoundError(f"audio_file for track {track_id}")
        return {
            "path": str(row[0] or "").strip(),
            "storage_mode": str(row[1] or "").strip(),
            "filename": str(row[2] or "").strip(),
            "mime_type": str(row[3] or "").strip(),
            "size_bytes": int(row[4] or row[6] or 0),
            "blob_present": bool(row[5]),
            "blob_size": int(row[6] or 0),
        }

    def _database_blob_fingerprint(
        self,
        track_id: int,
        size: int,
        *,
        cursor: sqlite3.Cursor | None = None,
    ) -> str:
        cur = cursor or self.conn.cursor()
        edge = min(_FINGERPRINT_EDGE_BYTES, max(0, int(size)))
        if edge <= 0:
            return _bytes_edge_fingerprint(b"", 0)
        start = max(1, int(size) - edge + 1)
        row = cur.execute(
            """
            SELECT substr(audio_file_blob, 1, ?),
                   substr(audio_file_blob, ?, ?)
            FROM Tracks
            WHERE id=?
            """,
            (edge, start, edge, int(track_id)),
        ).fetchone()
        first = bytes(row[0] or b"") if row else b""
        last = bytes(row[1] or b"") if row and int(size) > edge else b""
        return _bytes_edge_fingerprint(first + last, int(size))

    def _source_fingerprint_for_track(
        self,
        track_service: "TrackService",
        track_id: int,
        *,
        cursor: sqlite3.Cursor | None = None,
    ) -> tuple[str, dict[str, object]]:
        metadata = self._track_audio_metadata(int(track_id), cursor=cursor)
        storage_mode = str(metadata.get("storage_mode") or "")
        blob_present = bool(metadata.get("blob_present"))
        stored_path = str(metadata.get("path") or "")
        if blob_present and (storage_mode == STORAGE_MODE_DATABASE or not stored_path):
            size = int(metadata.get("blob_size") or metadata.get("size_bytes") or 0)
            return (
                self._database_blob_fingerprint(int(track_id), size, cursor=cursor),
                metadata,
            )
        handle = track_service.resolve_media_source(int(track_id), "audio_file", cursor=cursor)
        metadata.update(
            {
                "filename": handle.filename,
                "storage_mode": handle.storage_mode or "",
                "mime_type": handle.mime_type or "",
                "size_bytes": int(handle.size_bytes or 0),
            }
        )
        return audio_source_fingerprint(handle), metadata

    def ensure_track_cache(
        self,
        track_service: "TrackService",
        track_id: int,
        *,
        cursor: sqlite3.Cursor | None = None,
        force: bool = False,
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> CachedWaveform | None:
        self.ensure_schema()
        cur = cursor or self.conn.cursor()
        fingerprint, metadata = self._source_fingerprint_for_track(
            track_service,
            int(track_id),
            cursor=cur,
        )
        row = self._fetch_cache_row(int(track_id), cursor=cur)
        cached = self._row_to_cached_waveform(row)
        if (
            self._cached_waveform_is_complete(cached)
            and not force
            and cached.source_fingerprint == fingerprint
        ):
            return cached

        handle = track_service.resolve_media_source(int(track_id), "audio_file", cursor=cur)
        if callable(progress_callback):
            progress_callback(0, 3, f"Analysing cached waveform for {handle.filename}...")
        with handle.materialize_path() as materialized_path:
            materialized_text = str(materialized_path)
            peaks = load_audio_waveform_peaks(materialized_text, WAVEFORM_CACHE_WIDTH)
            waveform_colors = load_audio_waveform_colors(materialized_text, WAVEFORM_CACHE_WIDTH)
        if not peaks:
            cur.execute("DELETE FROM TrackAudioWaveformCache WHERE track_id=?", (int(track_id),))
            return None

        if callable(progress_callback):
            progress_callback(1, 3, f"Rendering cached waveform for {handle.filename}...")
        light_png = render_waveform_cache_png(
            peaks,
            width_px=WAVEFORM_CACHE_WIDTH,
            height_px=WAVEFORM_CACHE_HEIGHT,
            light_background=True,
            waveform_colors=waveform_colors,
        )
        dark_png = render_waveform_cache_png(
            peaks,
            width_px=WAVEFORM_CACHE_WIDTH,
            height_px=WAVEFORM_CACHE_HEIGHT,
            light_background=False,
            waveform_colors=waveform_colors,
        )
        if not light_png or not dark_png:
            cur.execute("DELETE FROM TrackAudioWaveformCache WHERE track_id=?", (int(track_id),))
            return None

        if callable(progress_callback):
            progress_callback(2, 3, f"Storing cached waveform for {handle.filename}...")
        cur.execute(
            """
            INSERT INTO TrackAudioWaveformCache(
                track_id, source_fingerprint, source_size_bytes, source_filename,
                source_storage_mode, source_mime_type, analyzer_version, width_px,
                height_px, peaks_json, light_preview_png, dark_preview_png,
                generated_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
            ON CONFLICT(track_id) DO UPDATE SET
                source_fingerprint=excluded.source_fingerprint,
                source_size_bytes=excluded.source_size_bytes,
                source_filename=excluded.source_filename,
                source_storage_mode=excluded.source_storage_mode,
                source_mime_type=excluded.source_mime_type,
                analyzer_version=excluded.analyzer_version,
                width_px=excluded.width_px,
                height_px=excluded.height_px,
                peaks_json=excluded.peaks_json,
                light_preview_png=excluded.light_preview_png,
                dark_preview_png=excluded.dark_preview_png,
                updated_at=datetime('now')
            """,
            (
                int(track_id),
                fingerprint,
                int(metadata.get("size_bytes") or handle.size_bytes or 0),
                str(metadata.get("filename") or handle.filename or ""),
                str(metadata.get("storage_mode") or handle.storage_mode or ""),
                str(metadata.get("mime_type") or handle.mime_type or ""),
                WAVEFORM_CACHE_ANALYZER_VERSION,
                WAVEFORM_CACHE_WIDTH,
                WAVEFORM_CACHE_HEIGHT,
                _peaks_to_json(peaks),
                sqlite3.Binary(light_png),
                sqlite3.Binary(dark_png),
            ),
        )
        row = self._fetch_cache_row(int(track_id), cursor=cur)
        return self._row_to_cached_waveform(row)

    def ensure_all_track_caches(
        self,
        track_service: "TrackService",
        *,
        cursor: sqlite3.Cursor | None = None,
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> WaveformCacheRunSummary:
        self.ensure_schema()
        cur = cursor or self.conn.cursor()
        rows = cur.execute(
            """
            SELECT id, COALESCE(track_title, '')
            FROM Tracks
            WHERE COALESCE(trim(audio_file_path), '') != ''
               OR audio_file_blob IS NOT NULL
               OR COALESCE(audio_file_size_bytes, 0) > 0
            ORDER BY id
            """
        ).fetchall()
        summary = WaveformCacheRunSummary(total_audio_tracks=len(rows))
        total = max(1, len(rows))
        if not rows:
            if callable(progress_callback):
                progress_callback(1, 1, "No audio waveform cache work needed.")
            return summary
        for index, (track_id, title) in enumerate(rows, start=1):
            title_text = str(title or f"Track {track_id}").strip() or f"Track {track_id}"
            message = f"Checking cached waveform {index}/{len(rows)}: {title_text}"
            if callable(progress_callback):
                progress_callback(index - 1, total, message)
            before_row = self._fetch_cache_row(int(track_id), cursor=cur)
            before = self._row_to_cached_waveform(before_row)
            try:
                cached = self.ensure_track_cache(
                    track_service,
                    int(track_id),
                    cursor=cur,
                    progress_callback=(
                        (
                            lambda _value, _maximum, inner_message, index=index, total=total: progress_callback(
                                index - 1,
                                total,
                                inner_message,
                            )
                        )
                        if callable(progress_callback)
                        else None
                    ),
                )
            except Exception:
                summary.errors += 1
                continue
            summary.checked += 1
            if cached is None:
                summary.skipped += 1
            elif before is not None and before.source_fingerprint == cached.source_fingerprint:
                summary.reused += 1
            else:
                summary.rendered += 1
            if callable(progress_callback):
                progress_callback(index, total, f"Cached waveform checked: {title_text}")
        return summary

    def inspect_invalid_caches(self, track_service: "TrackService") -> WaveformCacheInspection:
        self.ensure_schema()
        cur = self.conn.cursor()
        rows = cur.execute(
            """
            SELECT c.track_id, c.source_fingerprint, c.analyzer_version,
                   c.width_px, c.height_px, c.peaks_json,
                   c.light_preview_png, c.dark_preview_png, t.id
            FROM TrackAudioWaveformCache c
            LEFT JOIN Tracks t ON t.id = c.track_id
            ORDER BY c.track_id
            """
        ).fetchall()
        orphaned: list[int] = []
        stale: list[int] = []
        missing_audio: list[int] = []
        details: list[str] = []
        valid_rows = 0
        for row in rows:
            track_id = int(row[0])
            if row[8] is None:
                orphaned.append(track_id)
                details.append(f"Track #{track_id}: cache row has no matching track.")
                continue
            try:
                fingerprint, _metadata = self._source_fingerprint_for_track(
                    track_service,
                    track_id,
                    cursor=cur,
                )
            except FileNotFoundError:
                missing_audio.append(track_id)
                details.append(f"Track #{track_id}: cache row remains after audio was removed.")
                continue
            except Exception as exc:
                stale.append(track_id)
                details.append(f"Track #{track_id}: cache could not verify source ({exc}).")
                continue
            row_valid = (
                str(row[1] or "") == fingerprint
                and int(row[2] or 0) == WAVEFORM_CACHE_ANALYZER_VERSION
                and int(row[3] or 0) == WAVEFORM_CACHE_WIDTH
                and int(row[4] or 0) == WAVEFORM_CACHE_HEIGHT
                and bool(_json_to_peaks(row[5]))
                and bool(row[6])
                and bool(row[7])
            )
            if row_valid:
                valid_rows += 1
            else:
                stale.append(track_id)
                details.append(
                    f"Track #{track_id}: cached waveform is stale for the current audio."
                )
        return WaveformCacheInspection(
            total_rows=len(rows),
            valid_rows=valid_rows,
            orphaned_rows=len(orphaned),
            stale_rows=len(stale),
            missing_audio_rows=len(missing_audio),
            orphaned_track_ids=tuple(orphaned),
            stale_track_ids=tuple(stale),
            missing_audio_track_ids=tuple(missing_audio),
            details=tuple(details),
        )

    def cleanup_invalid_caches(self, track_service: "TrackService") -> int:
        inspection = self.inspect_invalid_caches(track_service)
        track_ids = sorted(
            set(
                inspection.orphaned_track_ids
                + inspection.stale_track_ids
                + inspection.missing_audio_track_ids
            )
        )
        if not track_ids:
            return 0
        placeholders = ", ".join("?" for _ in track_ids)
        with self.conn:
            self.conn.execute(
                f"DELETE FROM TrackAudioWaveformCache WHERE track_id IN ({placeholders})",
                tuple(track_ids),
            )
        return len(track_ids)


class AudioWaveformCacheWorker:
    """Dedicated daemon for cache generation and validation on its own DB connection."""

    _STOP = object()

    def __init__(
        self,
        *,
        db_path: str | Path,
        data_root: str | Path,
        connection_factory=None,
        logger=None,
        name: str = "AudioWaveformCacheWorker",
    ):
        self.db_path = str(Path(db_path))
        self.data_root = Path(data_root)
        self.connection_factory = connection_factory
        self.logger = logger
        self.name = str(name or "AudioWaveformCacheWorker")
        self._queue: queue.Queue[tuple[str, int | None, bool] | object] = queue.Queue()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._pending_tracks: set[int] = set()
        self._pending_all = False

    def is_for_database(self, db_path: str | Path) -> bool:
        return self.db_path == str(Path(db_path))

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run, name=self.name, daemon=True)
            self._thread.start()

    def stop(self, *, wait: bool = False, timeout: float = 2.0) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            self._queue.put(self._STOP)
            if wait:
                thread.join(timeout=max(0.0, float(timeout)))
        with self._lock:
            self._pending_tracks.clear()
            self._pending_all = False

    def enqueue_track(self, track_id: int, *, force: bool = False) -> bool:
        clean_track_id = int(track_id)
        if clean_track_id <= 0:
            return False
        self.start()
        with self._lock:
            if clean_track_id in self._pending_tracks:
                return False
            self._pending_tracks.add(clean_track_id)
        self._queue.put(("track", clean_track_id, bool(force)))
        return True

    def enqueue_all(self, *, force: bool = False) -> bool:
        self.start()
        with self._lock:
            if self._pending_all:
                return False
            self._pending_all = True
        self._queue.put(("all", None, bool(force)))
        return True

    def _log_debug(self, message: str, *args) -> None:
        logger = self.logger
        if logger is not None:
            with suppress(Exception):
                logger.debug(message, *args)

    def _log_warning(self, message: str, *args) -> None:
        logger = self.logger
        if logger is not None:
            with suppress(Exception):
                logger.warning(message, *args)

    def _clear_pending_jobs(self) -> None:
        with self._lock:
            self._pending_tracks.clear()
            self._pending_all = False

    def _open_worker_services(self):
        from isrc_manager.services.db_access import SQLiteConnectionFactory
        from isrc_manager.services.tracks import TrackService

        factory = self.connection_factory or SQLiteConnectionFactory()
        conn = factory.open(self.db_path)
        service = AudioWaveformCacheService(conn)
        track_service = TrackService(conn, self.data_root, require_governed_creation=True)
        return conn, service, track_service

    def _run(self) -> None:
        try:
            conn, service, track_service = self._open_worker_services()
        except Exception as exc:
            self._log_warning("Could not start waveform cache worker for %s: %s", self.db_path, exc)
            self._clear_pending_jobs()
            return
        try:
            while not self._stop_event.is_set():
                job = self._queue.get()
                if job is self._STOP:
                    break
                if not isinstance(job, tuple):
                    continue
                kind, track_id, force = job
                try:
                    if kind == "all":
                        summary = service.ensure_all_track_caches(track_service)
                        conn.commit()
                        self._log_debug(
                            "Waveform cache background pass completed for %s: %s checked, "
                            "%s rendered, %s reused, %s skipped, %s errors",
                            self.db_path,
                            summary.checked,
                            summary.rendered,
                            summary.reused,
                            summary.skipped,
                            summary.errors,
                        )
                    elif kind == "track" and track_id is not None:
                        service.ensure_track_cache(track_service, int(track_id), force=bool(force))
                        conn.commit()
                        self._log_debug(
                            "Waveform cache background job completed for track %s",
                            track_id,
                        )
                except Exception as exc:
                    with suppress(Exception):
                        conn.rollback()
                    self._log_warning("Waveform cache background job failed: %s", exc)
                finally:
                    with self._lock:
                        if kind == "all":
                            self._pending_all = False
                        elif track_id is not None:
                            self._pending_tracks.discard(int(track_id))
        finally:
            with suppress(Exception):
                conn.close()

from __future__ import annotations

import json
import math
import os
import platform
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Any

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

EQ_SETTINGS_ENABLED_KEY = "media_player/equalizer/enabled"
EQ_SETTINGS_GAINS_KEY = "media_player/equalizer/gains_json"
EQ_GAIN_MIN_DB = -9.0
EQ_GAIN_MAX_DB = 9.0
EQ_GAIN_STEP_DB = 0.5
EQ_MIN_FREQUENCY_HZ = 20.0
EQ_MAX_FREQUENCY_HZ = 20000.0


@dataclass(frozen=True)
class EqualizerBand:
    key: str
    label: str
    tone_label: str
    frequency_hz: float
    q: float
    width_octaves: float
    filter_type: str = "bell"


EQUALIZER_BANDS: tuple[EqualizerBand, ...] = (
    EqualizerBand("sub", "40 Hz", "Low Shelf", 40.0, 0.62, 1.35, "low_shelf"),
    EqualizerBand("bass", "80 Hz", "Bass", 80.0, 0.66, 1.28),
    EqualizerBand("punch", "160 Hz", "Punch", 160.0, 0.72, 1.16),
    EqualizerBand("body", "400 Hz", "Body", 400.0, 0.78, 1.08),
    EqualizerBand("presence", "1 kHz", "Presence", 1000.0, 0.84, 1.0),
    EqualizerBand("clarity", "2.5 kHz", "Clarity", 2500.0, 0.86, 0.94),
    EqualizerBand("shimmer", "6.3 kHz", "Shimmer", 6300.0, 0.82, 0.98),
    EqualizerBand("air", "12 kHz", "High Shelf", 12000.0, 0.74, 1.12, "high_shelf"),
)


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _coerce_gain(value: Any) -> float:
    try:
        gain = float(value)
    except (TypeError, ValueError):
        gain = 0.0
    gain = max(EQ_GAIN_MIN_DB, min(EQ_GAIN_MAX_DB, gain))
    return round(gain / EQ_GAIN_STEP_DB) * EQ_GAIN_STEP_DB


def default_equalizer_settings() -> dict[str, object]:
    return {
        "enabled": False,
        "gains": [0.0 for _band in EQUALIZER_BANDS],
    }


def normalize_equalizer_settings(value: Any) -> dict[str, object]:
    defaults = default_equalizer_settings()
    if not isinstance(value, dict):
        return defaults

    raw_gains = value.get("gains", defaults["gains"])
    if isinstance(raw_gains, str):
        try:
            raw_gains = json.loads(raw_gains)
        except Exception:
            raw_gains = []
    if not isinstance(raw_gains, (list, tuple)):
        raw_gains = []

    gains = [
        _coerce_gain(raw_gains[index]) if index < len(raw_gains) else 0.0
        for index in range(len(EQUALIZER_BANDS))
    ]
    return {
        "enabled": _coerce_bool(value.get("enabled"), False),
        "gains": gains,
    }


def load_equalizer_settings(settings: Any) -> dict[str, object]:
    if settings is None:
        return default_equalizer_settings()
    try:
        enabled = settings.value(EQ_SETTINGS_ENABLED_KEY, False, bool)
    except TypeError:
        enabled = settings.value(EQ_SETTINGS_ENABLED_KEY, False)
    except Exception:
        enabled = False
    try:
        gains_raw = settings.value(EQ_SETTINGS_GAINS_KEY, "[]", str)
    except TypeError:
        gains_raw = settings.value(EQ_SETTINGS_GAINS_KEY, "[]")
    except Exception:
        gains_raw = "[]"
    return normalize_equalizer_settings(
        {
            "enabled": enabled,
            "gains": gains_raw,
        }
    )


def save_equalizer_settings(settings: Any, value: Any) -> dict[str, object]:
    normalized = normalize_equalizer_settings(value)
    if settings is None:
        return normalized
    try:
        settings.setValue(EQ_SETTINGS_ENABLED_KEY, bool(normalized["enabled"]))
        settings.setValue(EQ_SETTINGS_GAINS_KEY, json.dumps(normalized["gains"]))
        sync = getattr(settings, "sync", None)
        if callable(sync):
            sync()
    except Exception:
        pass
    return normalized


def equalizer_is_enabled(value: Any) -> bool:
    return bool(normalize_equalizer_settings(value)["enabled"])


def equalizer_has_audible_gain(value: Any) -> bool:
    normalized = normalize_equalizer_settings(value)
    if not bool(normalized["enabled"]):
        return False
    return any(abs(float(gain)) >= 0.05 for gain in normalized["gains"])


def equalizer_response_db_at_frequency(frequency_hz: float, value: Any) -> float:
    normalized = normalize_equalizer_settings(value)
    if not bool(normalized["enabled"]):
        return 0.0
    frequency = max(EQ_MIN_FREQUENCY_HZ, min(EQ_MAX_FREQUENCY_HZ, float(frequency_hz or 0.0)))
    total_db = 0.0
    for band, gain in zip(EQUALIZER_BANDS, normalized["gains"], strict=False):
        gain = float(gain)
        if abs(gain) < 0.01:
            continue
        distance = math.log2(frequency / max(1.0, band.frequency_hz))
        transition = max(0.18, band.width_octaves / 2.35)
        if band.filter_type == "low_shelf":
            total_db += gain / (1.0 + math.exp(distance / transition))
        elif band.filter_type == "high_shelf":
            total_db += gain / (1.0 + math.exp(-distance / transition))
        else:
            sigma = max(0.28, band.width_octaves / 2.0)
            total_db += gain * math.exp(-0.5 * ((distance / sigma) ** 2))
    return max(EQ_GAIN_MIN_DB * 1.6, min(EQ_GAIN_MAX_DB * 1.6, total_db))


def _frequency_for_bin(
    index: int,
    count: int,
    *,
    frequency_scale: str,
    min_hz: float,
    max_hz: float,
) -> float:
    count = max(1, int(count))
    ratio = (float(index) + 0.5) / float(count)
    min_hz = max(1.0, float(min_hz or EQ_MIN_FREQUENCY_HZ))
    max_hz = max(min_hz + 1.0, float(max_hz or EQ_MAX_FREQUENCY_HZ))
    if str(frequency_scale or "").strip().lower() == "log":
        return min_hz * ((max_hz / min_hz) ** ratio)
    return min_hz + ((max_hz - min_hz) * ratio)


def equalizer_response_for_bins(
    bin_count: int,
    value: Any,
    *,
    frequency_scale: str = "linear",
    min_hz: float = EQ_MIN_FREQUENCY_HZ,
    max_hz: float = EQ_MAX_FREQUENCY_HZ,
) -> list[float]:
    count = max(0, int(bin_count or 0))
    if count <= 0:
        return []
    normalized = normalize_equalizer_settings(value)
    if not bool(normalized["enabled"]):
        return [1.0 for _index in range(count)]
    multipliers = []
    for index in range(count):
        frequency = _frequency_for_bin(
            index,
            count,
            frequency_scale=frequency_scale,
            min_hz=min_hz,
            max_hz=max_hz,
        )
        response_db = equalizer_response_db_at_frequency(frequency, normalized)
        multipliers.append(max(0.18, min(3.2, 10.0 ** (response_db / 20.0))))
    return multipliers


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


def _ffmpeg_filter_chain(value: Any) -> str:
    normalized = normalize_equalizer_settings(value)
    filters: list[str] = []
    for band, gain in zip(EQUALIZER_BANDS, normalized["gains"], strict=False):
        gain = float(gain)
        if abs(gain) < 0.05:
            continue
        if band.filter_type == "low_shelf":
            filter_name = "bass"
        elif band.filter_type == "high_shelf":
            filter_name = "treble"
        else:
            filter_name = "equalizer"
        filters.append(f"{filter_name}=f={band.frequency_hz:.3f}:t=q:w={band.q:.3f}:g={gain:.3f}")
    if not filters:
        return ""
    if max(float(gain) for gain in normalized["gains"]) > 0.0:
        filters.append("volume=0.95")
        filters.append("alimiter=limit=0.98")
    return ",".join(filters)


def _apply_equalizer_with_ffmpeg(source_path: str, target_path: str, value: Any) -> bool:
    ffmpeg = _which("ffmpeg")
    if not ffmpeg:
        return False
    filter_chain = _ffmpeg_filter_chain(value)
    if not filter_chain:
        return False
    try:
        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-v",
                "error",
                "-nostdin",
                "-i",
                os.fspath(source_path),
                "-vn",
                "-af",
                filter_chain,
                "-f",
                "wav",
                os.fspath(target_path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=90,
            check=True,
        )
    except Exception:
        return False
    return Path(target_path).exists() and Path(target_path).stat().st_size > 0


def equalizer_biquad_coefficients(
    filter_type: str,
    frequency_hz: float,
    q: float,
    gain_db: float,
    sample_rate: int,
) -> tuple[float, float, float, float, float]:
    sample_rate = max(1, int(sample_rate or 44100))
    frequency = max(1.0, min(float(frequency_hz), (sample_rate / 2.0) * 0.94))
    omega = 2.0 * math.pi * frequency / float(sample_rate)
    amp = 10.0 ** (float(gain_db) / 40.0)
    cos_omega = math.cos(omega)
    sin_omega = math.sin(omega)
    normalized_type = str(filter_type or "bell").strip().lower()

    if normalized_type in {"low_shelf", "high_shelf"}:
        slope = max(0.1, min(2.0, float(q or 1.0)))
        alpha = (sin_omega / 2.0) * math.sqrt(((amp + (1.0 / amp)) * ((1.0 / slope) - 1.0)) + 2.0)
        sqrt_amp = math.sqrt(amp)
        if normalized_type == "low_shelf":
            b0 = amp * ((amp + 1.0) - ((amp - 1.0) * cos_omega) + (2.0 * sqrt_amp * alpha))
            b1 = 2.0 * amp * ((amp - 1.0) - ((amp + 1.0) * cos_omega))
            b2 = amp * ((amp + 1.0) - ((amp - 1.0) * cos_omega) - (2.0 * sqrt_amp * alpha))
            a0 = (amp + 1.0) + ((amp - 1.0) * cos_omega) + (2.0 * sqrt_amp * alpha)
            a1 = -2.0 * ((amp - 1.0) + ((amp + 1.0) * cos_omega))
            a2 = (amp + 1.0) + ((amp - 1.0) * cos_omega) - (2.0 * sqrt_amp * alpha)
        else:
            b0 = amp * ((amp + 1.0) + ((amp - 1.0) * cos_omega) + (2.0 * sqrt_amp * alpha))
            b1 = -2.0 * amp * ((amp - 1.0) + ((amp + 1.0) * cos_omega))
            b2 = amp * ((amp + 1.0) + ((amp - 1.0) * cos_omega) - (2.0 * sqrt_amp * alpha))
            a0 = (amp + 1.0) - ((amp - 1.0) * cos_omega) + (2.0 * sqrt_amp * alpha)
            a1 = 2.0 * ((amp - 1.0) - ((amp + 1.0) * cos_omega))
            a2 = (amp + 1.0) - ((amp - 1.0) * cos_omega) - (2.0 * sqrt_amp * alpha)
    else:
        alpha = sin_omega / (2.0 * max(0.1, float(q)))
        b0 = 1.0 + (alpha * amp)
        b1 = -2.0 * cos_omega
        b2 = 1.0 - (alpha * amp)
        a0 = 1.0 + (alpha / amp)
        a1 = -2.0 * cos_omega
        a2 = 1.0 - (alpha / amp)

    return b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0


def _equalizer_sos(
    filter_type: str,
    frequency_hz: float,
    q: float,
    gain_db: float,
    sample_rate: int,
):
    import numpy as np

    b0, b1, b2, a1, a2 = equalizer_biquad_coefficients(
        filter_type,
        frequency_hz,
        q,
        gain_db,
        sample_rate,
    )
    return np.array([[b0, b1, b2, 1.0, a1, a2]], dtype=np.float64)


def _apply_equalizer_with_soundfile(source_path: str, target_path: str, value: Any) -> bool:
    try:
        import numpy as np
        import soundfile as sf
        from scipy.signal import sosfilt
    except Exception:
        return False

    normalized = normalize_equalizer_settings(value)
    try:
        samples, sample_rate = sf.read(os.fspath(source_path), dtype="float32", always_2d=True)
    except Exception:
        return False
    if samples is None or samples.size <= 0:
        return False

    processed = samples.astype(np.float64, copy=True)
    try:
        for band, gain in zip(EQUALIZER_BANDS, normalized["gains"], strict=False):
            gain = float(gain)
            if abs(gain) < 0.05:
                continue
            sos = _equalizer_sos(
                band.filter_type,
                band.frequency_hz,
                band.q,
                gain,
                int(sample_rate),
            )
            for channel in range(processed.shape[1]):
                processed[:, channel] = sosfilt(sos, processed[:, channel])
        peak = float(np.max(np.abs(processed))) if processed.size else 0.0
        if peak > 0.98:
            processed *= 0.98 / peak
        processed = np.clip(processed, -1.0, 1.0).astype(np.float32)
        sf.write(
            os.fspath(target_path),
            processed,
            int(sample_rate),
            format="WAV",
            subtype="PCM_16",
        )
    except Exception:
        return False
    return Path(target_path).exists() and Path(target_path).stat().st_size > 0


def apply_equalizer_to_audio(source_path: str, target_path: str, value: Any) -> bool:
    if not source_path or not target_path or not equalizer_has_audible_gain(value):
        return False
    Path(target_path).parent.mkdir(parents=True, exist_ok=True)
    if _apply_equalizer_with_ffmpeg(source_path, target_path, value):
        return True
    return _apply_equalizer_with_soundfile(source_path, target_path, value)


class EqualizerCurveWidget(QWidget):
    AUDIO_SPECTRUM_FADE_INTERVAL_MS = 45
    AUDIO_SPECTRUM_HOLD_SECONDS = 0.18

    def __init__(self, parent=None):
        super().__init__(parent)
        self._settings = default_equalizer_settings()
        self._audio_spectrum_values: list[float] = []
        self._audio_spectrum_opacity = 0.0
        self._last_audio_spectrum_update = 0.0
        self._audio_spectrum_fade_timer = QTimer(self)
        self._audio_spectrum_fade_timer.setInterval(self.AUDIO_SPECTRUM_FADE_INTERVAL_MS)
        self._audio_spectrum_fade_timer.timeout.connect(self._advance_audio_spectrum_fade)
        self.setMinimumHeight(92)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def sizeHint(self) -> QSize:
        return QSize(420, 108)

    def set_settings(self, value: Any) -> None:
        self._settings = normalize_equalizer_settings(value)
        self.update()

    def set_audio_spectrum(self, values: list[float] | tuple[float, ...]) -> None:
        if not values:
            if self._audio_spectrum_opacity > 0.0:
                self._last_audio_spectrum_update = 0.0
                if not self._audio_spectrum_fade_timer.isActive():
                    self._audio_spectrum_fade_timer.start()
            return

        cleaned = [max(0.0, min(1.24, float(value))) for value in values]
        if len(cleaned) <= 1:
            return

        if len(self._audio_spectrum_values) != len(cleaned):
            self._audio_spectrum_values = cleaned
        else:
            blended = []
            for old, new in zip(self._audio_spectrum_values, cleaned, strict=False):
                factor = 0.56 if new >= old else 0.18
                blended.append(old + ((new - old) * factor))
            self._audio_spectrum_values = blended

        self._audio_spectrum_opacity = min(1.0, max(self._audio_spectrum_opacity, 0.92))
        self._last_audio_spectrum_update = monotonic()
        if not self._audio_spectrum_fade_timer.isActive():
            self._audio_spectrum_fade_timer.start()
        self.update()

    def _advance_audio_spectrum_fade(self) -> None:
        if (
            self._last_audio_spectrum_update > 0.0
            and monotonic() - self._last_audio_spectrum_update < self.AUDIO_SPECTRUM_HOLD_SECONDS
        ):
            return
        self._audio_spectrum_opacity *= 0.88
        self._audio_spectrum_values = [value * 0.94 for value in self._audio_spectrum_values]
        if self._audio_spectrum_opacity <= 0.025:
            self._audio_spectrum_opacity = 0.0
            self._audio_spectrum_values = []
            self._audio_spectrum_fade_timer.stop()
        self.update()

    @staticmethod
    def _relative_luminance(color: QColor) -> float:
        return 0.2126 * color.redF() + 0.7152 * color.greenF() + 0.0722 * color.blueF()

    def _frequency_to_x(self, frequency_hz: float, rect: QRectF) -> float:
        min_log = math.log10(EQ_MIN_FREQUENCY_HZ)
        max_log = math.log10(EQ_MAX_FREQUENCY_HZ)
        frequency = max(EQ_MIN_FREQUENCY_HZ, min(EQ_MAX_FREQUENCY_HZ, float(frequency_hz)))
        ratio = (math.log10(frequency) - min_log) / max(0.01, max_log - min_log)
        return rect.left() + (rect.width() * max(0.0, min(1.0, ratio)))

    def _db_to_y(self, gain_db: float, rect: QRectF) -> float:
        ratio = (float(gain_db) - EQ_GAIN_MIN_DB) / max(0.01, EQ_GAIN_MAX_DB - EQ_GAIN_MIN_DB)
        return rect.bottom() - (rect.height() * max(0.0, min(1.0, ratio)))

    def _draw_curve(self, painter: QPainter, rect: QRectF, *, light_mode: bool) -> None:
        enabled = equalizer_is_enabled(self._settings)
        curve_color = QColor("#0A84FF" if enabled else "#8A8F98")
        fill_color = QColor(curve_color)
        fill_color.setAlpha(44 if enabled else 22)
        curve_color.setAlpha(230 if enabled else 150)

        zero_y = self._db_to_y(0.0, rect)
        points: list[tuple[float, float]] = []
        for index in range(max(2, int(rect.width()))):
            ratio = index / max(1, int(rect.width()) - 1)
            frequency = EQ_MIN_FREQUENCY_HZ * ((EQ_MAX_FREQUENCY_HZ / EQ_MIN_FREQUENCY_HZ) ** ratio)
            response = equalizer_response_db_at_frequency(frequency, self._settings)
            points.append((rect.left() + index, self._db_to_y(response, rect)))

        painter.setPen(Qt.NoPen)
        for x_pos, y_pos in points:
            top = min(y_pos, zero_y)
            height = abs(zero_y - y_pos)
            painter.fillRect(QRectF(x_pos, top, 1.0, height), fill_color)

        if len(points) < 2:
            return
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(QPen(curve_color, 2.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        previous = points[0]
        for point in points[1:]:
            painter.drawLine(
                int(round(previous[0])),
                int(round(previous[1])),
                int(round(point[0])),
                int(round(point[1])),
            )
            previous = point

        handle_color = QColor("#FFFFFF" if not light_mode else "#111827")
        handle_outline = QColor(curve_color)
        handle_outline.setAlpha(210)
        painter.setPen(QPen(handle_outline, 1.1))
        painter.setBrush(handle_color)
        for band, gain in zip(EQUALIZER_BANDS, self._settings["gains"], strict=False):
            x_pos = self._frequency_to_x(band.frequency_hz, rect)
            y_pos = self._db_to_y(float(gain), rect)
            painter.drawEllipse(QRectF(x_pos - 3.2, y_pos - 3.2, 6.4, 6.4))

    def _audio_spectrum_color(self, value: float, *, light_mode: bool) -> QColor:
        intensity = max(0.0, min(1.0, float(value))) ** 0.58
        hue = 0.62 * (1.0 - intensity)
        saturation = 0.92
        brightness = (0.72 + (intensity * 0.18)) if light_mode else (0.86 + (intensity * 0.1))
        alpha = (0.12 + (intensity * 0.14)) * max(0.0, min(1.0, self._audio_spectrum_opacity))
        color = QColor()
        color.setHsvF(hue, saturation, min(1.0, brightness), min(0.32, alpha))
        return color

    def _draw_audio_spectrum_ridge(
        self,
        painter: QPainter,
        rect: QRectF,
        *,
        light_mode: bool,
    ) -> None:
        if self._audio_spectrum_opacity <= 0.0 or len(self._audio_spectrum_values) < 2:
            return

        values = list(self._audio_spectrum_values)
        spatial = []
        for index, value in enumerate(values):
            previous = values[max(0, index - 1)]
            next_value = values[min(len(values) - 1, index + 1)]
            spatial.append((previous * 0.22) + (value * 0.56) + (next_value * 0.22))

        response = equalizer_response_for_bins(
            len(spatial),
            self._settings,
            frequency_scale="log",
            min_hz=EQ_MIN_FREQUENCY_HZ,
            max_hz=EQ_MAX_FREQUENCY_HZ,
        )
        if response:
            spatial = [
                max(0.0, min(1.32, value * (float(response[index]) ** 0.62)))
                for index, value in enumerate(spatial)
            ]

        base_y = rect.bottom() - (rect.height() * 0.12)
        amplitude = rect.height() * 0.64
        points: list[QPointF] = []
        for index, value in enumerate(spatial):
            ratio = index / max(1, len(spatial) - 1)
            x_pos = rect.left() + (rect.width() * ratio)
            shaped = (max(0.0, min(1.32, value)) / 1.32) ** 0.78
            points.append(QPointF(x_pos, base_y - (shaped * amplitude)))

        if len(points) < 2:
            return

        painter.save()
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            glow = QColor("#0A84FF" if not light_mode else "#0067D6")
            glow.setAlphaF(0.07 * max(0.0, min(1.0, self._audio_spectrum_opacity)))
            painter.setPen(QPen(glow, 3.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            for index in range(len(points) - 1):
                painter.drawLine(points[index], points[index + 1])

            for index in range(len(points) - 1):
                intensity = (spatial[index] + spatial[index + 1]) / 2.0
                painter.setPen(
                    QPen(
                        self._audio_spectrum_color(intensity, light_mode=light_mode),
                        1.15,
                        Qt.SolidLine,
                        Qt.RoundCap,
                        Qt.RoundJoin,
                    )
                )
                painter.drawLine(points[index], points[index + 1])
        finally:
            painter.restore()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            outer = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
            graph_rect = outer.adjusted(10.0, 8.0, -10.0, -14.0)

            palette = self.palette()
            background = palette.window().color()
            light_mode = self._relative_luminance(background) >= 0.5
            panel_color = palette.base().color()
            border_color = QColor("#CDD2DA" if light_mode else "#4F5562")
            grid_color = QColor("#D8DDE6" if light_mode else "#444A55")
            zero_color = QColor("#8D96A6" if light_mode else "#7B8391")
            text_color = palette.windowText().color()

            painter.setPen(QPen(border_color, 1.0))
            painter.setBrush(panel_color)
            painter.drawRoundedRect(outer, 6.0, 6.0)

            painter.setClipRect(graph_rect.adjusted(-1.0, -1.0, 1.0, 1.0))
            self._draw_audio_spectrum_ridge(painter, graph_rect, light_mode=light_mode)
            painter.setPen(QPen(grid_color, 0.65))
            for band in EQUALIZER_BANDS:
                x_pos = self._frequency_to_x(band.frequency_hz, graph_rect)
                painter.drawLine(
                    int(x_pos),
                    int(graph_rect.top()),
                    int(x_pos),
                    int(graph_rect.bottom()),
                )

            zero_y = self._db_to_y(0.0, graph_rect)
            painter.setPen(QPen(zero_color, 1.1))
            painter.drawLine(
                int(graph_rect.left()),
                int(zero_y),
                int(graph_rect.right()),
                int(zero_y),
            )
            self._draw_curve(painter, graph_rect, light_mode=light_mode)
            painter.setClipping(False)

            font = QFont(self.font())
            font.setPointSize(max(7, font.pointSize() - 2))
            painter.setFont(font)
            text_color.setAlpha(190)
            painter.setPen(text_color)
            for band in (EQUALIZER_BANDS[0], EQUALIZER_BANDS[3], EQUALIZER_BANDS[-1]):
                x_pos = self._frequency_to_x(band.frequency_hz, graph_rect)
                painter.drawText(
                    QRectF(x_pos - 36.0, outer.bottom() - 14.0, 72.0, 12.0),
                    Qt.AlignCenter,
                    band.label,
                )
        finally:
            painter.end()


class EqualizerDialog(QDialog):
    settingsChanged = Signal(dict)

    def __init__(self, settings: Any | None = None, parent=None):
        super().__init__(parent)
        self._settings = normalize_equalizer_settings(settings)
        self._syncing = False
        self._sliders: list[QSlider] = []
        self._value_labels: list[QLabel] = []

        self.setObjectName("mediaEqualizerDialog")
        self.setWindowTitle("Equalizer")
        self.setModal(False)
        self.setWindowModality(Qt.NonModal)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.setMinimumSize(560, 320)
        self.resize(600, 350)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        top_row = QHBoxLayout()
        top_row.setSpacing(8)
        self.enabled_check = QCheckBox("On", self)
        self.enabled_check.setObjectName("mediaEqualizerEnabledCheck")
        self.enabled_check.setToolTip("Turn equalizer on or off")
        self.reset_button = QPushButton("Reset", self)
        self.reset_button.setObjectName("mediaEqualizerResetButton")
        self.reset_button.setFixedWidth(68)
        top_row.addWidget(self.enabled_check, 0, Qt.AlignLeft | Qt.AlignVCenter)
        top_row.addStretch(1)
        top_row.addWidget(self.reset_button, 0, Qt.AlignRight | Qt.AlignVCenter)
        root.addLayout(top_row)

        self.graph = EqualizerCurveWidget(self)
        self.graph.setObjectName("mediaEqualizerCurve")
        root.addWidget(self.graph)

        slider_frame = QFrame(self)
        slider_frame.setObjectName("mediaEqualizerSliderFrame")
        slider_layout = QGridLayout(slider_frame)
        slider_layout.setContentsMargins(0, 0, 0, 0)
        slider_layout.setHorizontalSpacing(8)
        slider_layout.setVerticalSpacing(4)
        for column, band in enumerate(EQUALIZER_BANDS):
            tone = QLabel(band.tone_label, slider_frame)
            tone.setObjectName("mediaEqualizerToneLabel")
            tone.setAlignment(Qt.AlignCenter)
            tone.setToolTip(f"{band.tone_label}: {band.label}")
            tone.setMinimumWidth(58)

            slider = QSlider(Qt.Vertical, slider_frame)
            slider.setObjectName(f"mediaEqualizerSlider_{band.key}")
            slider.setRange(int(EQ_GAIN_MIN_DB * 10), int(EQ_GAIN_MAX_DB * 10))
            slider.setSingleStep(int(EQ_GAIN_STEP_DB * 10))
            slider.setPageStep(10)
            slider.setTickInterval(30)
            slider.setTickPosition(QSlider.TickPosition.TicksBothSides)
            slider.setMinimumHeight(132)
            slider.setToolTip(f"{band.tone_label} ({band.label})")
            slider.valueChanged.connect(self._on_control_changed)

            frequency = QLabel(band.label, slider_frame)
            frequency.setObjectName("mediaEqualizerBandLabel")
            frequency.setAlignment(Qt.AlignCenter)
            frequency.setToolTip(f"{band.tone_label}: {band.label}")

            value_label = QLabel("0 dB", slider_frame)
            value_label.setObjectName("mediaEqualizerValueLabel")
            value_label.setAlignment(Qt.AlignCenter)

            slider_layout.addWidget(tone, 0, column, Qt.AlignCenter)
            slider_layout.addWidget(slider, 1, column, Qt.AlignCenter)
            slider_layout.addWidget(frequency, 2, column, Qt.AlignCenter)
            slider_layout.addWidget(value_label, 3, column, Qt.AlignCenter)
            slider_layout.setColumnStretch(column, 1)
            self._sliders.append(slider)
            self._value_labels.append(value_label)
        root.addWidget(slider_frame)

        self.enabled_check.toggled.connect(self._on_control_changed)
        self.reset_button.clicked.connect(self._reset_gains)
        self._sync_from_settings()

    @staticmethod
    def _format_gain(value: float) -> str:
        gain = _coerce_gain(value)
        if abs(gain) < 0.05:
            return "0 dB"
        return f"{gain:+.1f} dB"

    def settings(self) -> dict[str, object]:
        return normalize_equalizer_settings(self._settings)

    def set_settings(self, value: Any, *, emit: bool = False) -> None:
        self._settings = normalize_equalizer_settings(value)
        self._sync_from_settings()
        if emit:
            self.settingsChanged.emit(self.settings())

    def set_playback_spectrum(self, values: list[float]) -> None:
        self.graph.set_audio_spectrum(values)

    def _current_settings_from_controls(self) -> dict[str, object]:
        gains = [round(float(slider.value()) / 10.0, 1) for slider in self._sliders]
        return normalize_equalizer_settings(
            {
                "enabled": bool(self.enabled_check.isChecked()),
                "gains": gains,
            }
        )

    def _sync_from_settings(self) -> None:
        self._syncing = True
        try:
            normalized = normalize_equalizer_settings(self._settings)
            self.enabled_check.setChecked(bool(normalized["enabled"]))
            for slider, label, gain in zip(
                self._sliders,
                self._value_labels,
                normalized["gains"],
                strict=False,
            ):
                slider.setValue(int(round(float(gain) * 10)))
                label.setText(self._format_gain(float(gain)))
            self.graph.set_settings(normalized)
        finally:
            self._syncing = False

    def _on_control_changed(self, *_args) -> None:
        if self._syncing:
            return
        self._settings = self._current_settings_from_controls()
        for label, gain in zip(self._value_labels, self._settings["gains"], strict=False):
            label.setText(self._format_gain(float(gain)))
        self.graph.set_settings(self._settings)
        self.settingsChanged.emit(self.settings())

    def _reset_gains(self) -> None:
        self._settings = normalize_equalizer_settings(
            {
                "enabled": bool(self.enabled_check.isChecked()),
                "gains": [0.0 for _band in EQUALIZER_BANDS],
            }
        )
        self._sync_from_settings()
        self.settingsChanged.emit(self.settings())

    def closeEvent(self, event) -> None:
        event.ignore()
        self.hide()

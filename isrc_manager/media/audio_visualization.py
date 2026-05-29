import math
import platform

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPen
from PySide6.QtWidgets import QMenu, QSizePolicy, QWidget

from isrc_manager.media.equalizer import (
    equalizer_response_for_bins,
    normalize_equalizer_settings,
)
from isrc_manager.media.waveform import WaveformWidget


class StereoPeakMeterWidget(QWidget):
    BAR_WIDTH = 5
    BAR_GAP = 5
    DB_FLOOR = -60.0
    DB_ZERO = 0.0
    DB_TOP = 3.0
    PEAK_HOLD_LABEL_HEIGHT = 10
    PEAK_LIVE_LABEL_HEIGHT = 10
    PEAK_LABEL_HEIGHT = PEAK_HOLD_LABEL_HEIGHT + PEAK_LIVE_LABEL_HEIGHT
    RELEASE_MS = 900

    def __init__(self, parent=None):
        super().__init__(parent)
        self._frames: list[tuple[float, float]] = []
        self._duration = 1
        self._playhead = 0
        self._gain = 1.0
        self._bar_height = 74
        self._signal_active = True
        self._current_db = (self.DB_FLOOR, self.DB_FLOOR)
        self._hold_db = self.DB_FLOOR
        self._release_active = False
        self._release_elapsed_ms = 0
        self._release_start_db = (self.DB_FLOOR, self.DB_FLOOR)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setToolTip("Stereo peak meter")
        self._update_fixed_size()

    def _update_fixed_size(self) -> None:
        width = max(58, (self.BAR_WIDTH * 2) + self.BAR_GAP)
        height = max(1, int(self._bar_height))
        self.setFixedSize(width, height)

    def setBarHeight(self, height: int) -> None:
        self._bar_height = max(1, int(height))
        self._update_fixed_size()
        self.update()

    def set_peak_frames(self, frames) -> None:
        cleaned = []
        for frame in frames or []:
            try:
                left = float(frame[0])
                right = float(frame[1])
            except TypeError, ValueError, IndexError:
                continue
            cleaned.append((self._clamp_db(left), self._clamp_db(right)))
        self._frames = cleaned
        self._current_db = (self.DB_FLOOR, self.DB_FLOOR)
        self._hold_db = self.DB_FLOOR
        self._release_active = False
        self._release_elapsed_ms = 0
        self.update()

    def reset_signal_activity(self) -> None:
        self._signal_active = False
        self._current_db = (self.DB_FLOOR, self.DB_FLOOR)
        self._hold_db = self.DB_FLOOR
        self._release_active = False
        self._release_elapsed_ms = 0
        self.update()

    def reset_peak_hold(self) -> None:
        self._hold_db = self.DB_FLOOR
        self.update()

    def _update_peak_hold(self) -> None:
        self._hold_db = max(self._hold_db, self._current_db[0], self._current_db[1])

    def mark_signal_activity(self) -> None:
        was_active = self._signal_active and not self._release_active
        self._signal_active = True
        self._release_active = False
        self._release_elapsed_ms = 0
        self._current_db = self._frame_at_playhead()
        self._update_peak_hold()
        if not was_active:
            self.update()

    def begin_release(self) -> None:
        if self._release_active:
            return
        self._signal_active = False
        if self._current_db == (self.DB_FLOOR, self.DB_FLOOR):
            self._release_active = False
            return
        self._release_active = True
        self._release_elapsed_ms = 0
        self._release_start_db = self._current_db
        self.update()

    def is_releasing(self) -> bool:
        return bool(self._release_active)

    def advance_release(self, elapsed_ms: int) -> bool:
        if not self._release_active:
            return False
        self._release_elapsed_ms += max(1, int(elapsed_ms))
        progress = max(0.0, min(1.0, self._release_elapsed_ms / max(1.0, float(self.RELEASE_MS))))
        eased = 1.0 - ((1.0 - progress) * (1.0 - progress))
        next_values = []
        for start_db in self._release_start_db:
            next_values.append(start_db + ((self.DB_FLOOR - start_db) * eased))
        self._current_db = (self._clamp_db(next_values[0]), self._clamp_db(next_values[1]))
        if progress >= 1.0:
            self._current_db = (self.DB_FLOOR, self.DB_FLOOR)
            self._release_active = False
        self.update()
        return self._release_active

    def set_duration_ms(self, ms: int) -> None:
        self._duration = max(1, int(ms))

    def set_playhead_ms(self, ms: int) -> None:
        self._playhead = max(0, min(int(ms), self._duration))
        if self._release_active:
            self.update()
            return
        if not self._signal_active:
            self._current_db = (self.DB_FLOOR, self.DB_FLOOR)
            self.update()
            return
        self._current_db = self._frame_at_playhead()
        self._update_peak_hold()
        self.update()

    def set_gain(self, gain: float) -> None:
        self._gain = max(0.0, float(gain))
        if self._release_active:
            self.update()
            return
        if not self._signal_active:
            self._current_db = (self.DB_FLOOR, self.DB_FLOOR)
            self.update()
            return
        self._current_db = self._frame_at_playhead()
        if self._gain > 0.0:
            self._update_peak_hold()
        self.update()

    def _gain_db(self) -> float:
        if self._gain <= 0.0:
            return self.DB_FLOOR
        return 20.0 * math.log10(self._gain)

    def _frame_position(self) -> float:
        if len(self._frames) <= 1:
            return 0.0
        ratio = max(0.0, min(1.0, self._playhead / max(1, self._duration)))
        return ratio * (len(self._frames) - 1)

    def _frame_at_playhead(self) -> tuple[float, float]:
        if not self._frames:
            return (self.DB_FLOOR, self.DB_FLOOR)
        if self._gain <= 0.0:
            return (self.DB_FLOOR, self.DB_FLOOR)
        gain_db = self._gain_db()
        if len(self._frames) == 1:
            left, right = self._frames[0]
        else:
            frame_pos = self._frame_position()
            lower_index = int(frame_pos)
            upper_index = min(len(self._frames) - 1, lower_index + 1)
            blend = frame_pos - lower_index
            lower = self._frames[lower_index]
            upper = self._frames[upper_index]
            left = (lower[0] * (1.0 - blend)) + (upper[0] * blend)
            right = (lower[1] * (1.0 - blend)) + (upper[1] * blend)
        return (self._clamp_db(left + gain_db), self._clamp_db(right + gain_db))

    def _clamp_db(self, value: float) -> float:
        return max(self.DB_FLOOR, min(self.DB_TOP, float(value)))

    def _db_to_ratio(self, value: float) -> float:
        value = self._clamp_db(value)
        return max(0.0, min(1.0, (value - self.DB_FLOOR) / (self.DB_TOP - self.DB_FLOOR)))

    def _format_db(self, value: float) -> str:
        if value <= self.DB_FLOOR + 0.05:
            return "-inf"
        return f"{value:+.1f} dB"

    def _format_compact_db(self, value: float) -> str:
        if value <= self.DB_FLOOR + 0.05:
            return "-inf"
        return f"{value:+.1f}"

    def _live_peak_db(self) -> float:
        return max(self._current_db[0], self._current_db[1])

    def _bar_rects(self) -> tuple[QRectF, QRectF]:
        top = float(self.PEAK_LABEL_HEIGHT)
        bar_height = max(1.0, float(self.height()) - top)
        total_width = (self.BAR_WIDTH * 2) + self.BAR_GAP
        start_x = max(0.0, (float(self.width()) - float(total_width)) / 2.0)
        left = QRectF(start_x, top, float(self.BAR_WIDTH), bar_height)
        right = QRectF(
            start_x + float(self.BAR_WIDTH + self.BAR_GAP),
            top,
            float(self.BAR_WIDTH),
            bar_height,
        )
        return left, right

    def _meter_gradient(self, rect: QRectF):
        from PySide6.QtGui import QLinearGradient

        gradient = QLinearGradient(rect.left(), rect.bottom(), rect.left(), rect.top())
        zero_stop = self._db_to_ratio(self.DB_ZERO)
        gradient.setColorAt(0.0, QColor(28, 178, 82))
        gradient.setColorAt(max(0.0, zero_stop - 0.24), QColor(223, 214, 48))
        gradient.setColorAt(zero_stop, QColor(255, 130, 122))
        gradient.setColorAt(1.0, QColor(232, 0, 0))
        return gradient

    def paintEvent(self, event):
        from PySide6.QtGui import QBrush, QFont, QPainter, QPen

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        pal = self.palette()
        label_font = QFont(self.font())
        point_size = label_font.pointSizeF()
        if point_size > 0:
            label_font.setPointSizeF(max(5.0, point_size - 3.0))
        painter.setFont(label_font)

        hold_label_color = pal.text().color()
        hold_label_color.setAlphaF(0.46)
        painter.setPen(hold_label_color)
        painter.drawText(
            QRectF(0.0, 0.0, float(self.width()), float(self.PEAK_HOLD_LABEL_HEIGHT)),
            Qt.AlignCenter,
            self._format_compact_db(self._hold_db),
        )

        live_label_color = pal.text().color()
        live_label_color.setAlphaF(0.86)
        painter.setPen(live_label_color)
        painter.drawText(
            QRectF(
                0.0,
                float(self.PEAK_HOLD_LABEL_HEIGHT),
                float(self.width()),
                float(self.PEAK_LIVE_LABEL_HEIGHT),
            ),
            Qt.AlignCenter,
            self._format_db(self._live_peak_db()),
        )

        outline = QColor(pal.mid().color())
        outline.setAlphaF(0.72)
        background = QColor(pal.base().color())
        background.setAlphaF(0.42)
        for rect, db_value in zip(self._bar_rects(), self._current_db):
            painter.fillRect(rect, background)
            fill_ratio = self._db_to_ratio(db_value)
            if fill_ratio > 0.0:
                fill_height = rect.height() * fill_ratio
                fill_rect = QRectF(
                    rect.left(),
                    rect.bottom() - fill_height,
                    rect.width(),
                    fill_height,
                )
                painter.fillRect(fill_rect, QBrush(self._meter_gradient(rect)))
            painter.setPen(QPen(outline, 1))
            painter.drawRect(rect.adjusted(0, 0, -1, -1))


class SpectrumGraphWidget(WaveformWidget):
    SPECTRUM_SCALE_LINEAR = "linear"
    SPECTRUM_SCALE_LOG = "log"
    SPECTRUM_LINE_WIDTH = 0.56
    SPECTRUM_COLOR_ALPHA_BOOST = 1.58
    SPECTRUM_FADE_IN_MS = 18
    SPECTRUM_FADE_STEP_MS = 10
    SPECTRUM_RELEASE_MS = 900
    SPECTRUM_MIN_HZ = 20.0
    SPECTRUM_MAX_HZ = 20000.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self._peaks = []
        self._fade_elapsed_ms = 0
        self._fade_opacity = 0.0
        self._gain = 1.0
        self._release_active = False
        self._release_elapsed_ms = 0
        self._release_start_opacity = 0.0
        self._frequency_scale = self.SPECTRUM_SCALE_LINEAR
        self._equalizer_settings = normalize_equalizer_settings(None)
        self._fade_timer = QTimer(self)
        self._fade_timer.setInterval(self.SPECTRUM_FADE_STEP_MS)
        self._fade_timer.timeout.connect(self._advance_fade_in)
        self.setMinimumHeight(1)
        self.setCursor(Qt.ArrowCursor)

    def set_peaks(self, peaks):
        self._peaks = []
        self._invalidate_waveform_cache()
        self.update()

    def set_spectrum_frames(self, frames):
        super().set_spectrum_frames(frames)
        self.reset_fade_in()

    def set_equalizer_settings(self, settings) -> None:
        normalized = normalize_equalizer_settings(settings)
        if normalized == getattr(self, "_equalizer_settings", None):
            return
        self._equalizer_settings = normalized
        self.update()

    def frequency_scale(self) -> str:
        return self._frequency_scale

    def set_frequency_scale(self, mode: str) -> None:
        normalized = str(mode or "").strip().lower()
        if normalized not in {self.SPECTRUM_SCALE_LINEAR, self.SPECTRUM_SCALE_LOG}:
            normalized = self.SPECTRUM_SCALE_LINEAR
        if normalized == self._frequency_scale:
            return
        self._frequency_scale = normalized
        self.update()

    def _create_frequency_scale_context_menu(self) -> QMenu:
        menu = QMenu(self)
        linear_action = menu.addAction("Linear view")
        linear_action.setCheckable(True)
        linear_action.setChecked(self._frequency_scale == self.SPECTRUM_SCALE_LINEAR)
        linear_action.triggered.connect(lambda _checked=False: self.set_frequency_scale("linear"))
        log_action = menu.addAction("Log view")
        log_action.setCheckable(True)
        log_action.setChecked(self._frequency_scale == self.SPECTRUM_SCALE_LOG)
        log_action.triggered.connect(lambda _checked=False: self.set_frequency_scale("log"))
        return menu

    def contextMenuEvent(self, event) -> None:
        menu = self._create_frequency_scale_context_menu()
        menu.exec(event.globalPos())
        event.accept()

    def reset_fade_in(self) -> None:
        self._fade_timer.stop()
        self._fade_elapsed_ms = 0
        self._fade_opacity = 0.0
        self._release_active = False
        self._release_elapsed_ms = 0
        self.update()

    def set_gain(self, gain: float, *, cancel_release: bool = True) -> None:
        self._gain = max(0.0, min(1.0, float(gain)))
        if cancel_release and self._gain > 0.0 and self._release_active:
            self._release_active = False
            self._release_elapsed_ms = 0
        self.update()

    def start_fade_in(self) -> None:
        if not self.has_live_visualization() or self._gain <= 0.0 or self._fade_opacity >= 1.0:
            return
        self._release_active = False
        self._release_elapsed_ms = 0
        if self._fade_opacity < 0.72:
            self._fade_opacity = 0.72
            self.update()
        if not self._fade_timer.isActive():
            self._fade_timer.start()

    def start_release(self) -> None:
        self._fade_timer.stop()
        if self._release_active:
            return
        release_start_opacity = max(0.0, self._fade_opacity * max(0.0, self._gain))
        if release_start_opacity <= 0.0:
            self._fade_opacity = 0.0
            self._release_active = False
            return
        self._release_active = True
        self._release_elapsed_ms = 0
        self._fade_opacity = release_start_opacity
        self._release_start_opacity = release_start_opacity
        self.update()

    def is_releasing(self) -> bool:
        return bool(self._release_active)

    def advance_release(self, elapsed_ms: int) -> bool:
        if not self._release_active:
            return False
        self._release_elapsed_ms += max(1, int(elapsed_ms))
        progress = max(
            0.0,
            min(1.0, self._release_elapsed_ms / max(1.0, float(self.SPECTRUM_RELEASE_MS))),
        )
        eased = 1.0 - ((1.0 - progress) * (1.0 - progress))
        self._fade_opacity = max(0.0, self._release_start_opacity * (1.0 - eased))
        if progress >= 1.0 or self._fade_opacity <= 0.001:
            self._fade_opacity = 0.0
            self._release_active = False
        self.update()
        return self._release_active

    def _advance_fade_in(self) -> None:
        if self._release_active:
            self._fade_timer.stop()
            return
        self._fade_elapsed_ms += self.SPECTRUM_FADE_STEP_MS
        progress = max(
            0.0,
            min(1.0, self._fade_elapsed_ms / max(1.0, float(self.SPECTRUM_FADE_IN_MS))),
        )
        self._fade_opacity = 1.0 - ((1.0 - progress) * (1.0 - progress))
        if progress >= 1.0:
            self._fade_opacity = 1.0
            self._fade_timer.stop()
        self.update()

    def _harmonic_rect(self, rect) -> QRectF:
        return QRectF(
            float(rect.left()),
            float(rect.top()),
            float(rect.width()),
            max(1.0, float(rect.height())),
        )

    def _spectrum_graph_rect(self, rect) -> QRectF:
        return QRectF(
            float(rect.left()),
            float(rect.top()) + 1.0,
            float(rect.width()),
            max(1.0, float(rect.height()) - 2.0),
        )

    def _current_spectrum_frame(self):
        return self._current_harmonic_frame()

    def _log_scaled_spectrum_values(self, values: list[float]) -> list[float]:
        count = len(values)
        if count <= 2:
            return list(values)
        min_hz = max(1.0, float(self.SPECTRUM_MIN_HZ))
        max_hz = max(min_hz + 1.0, float(self.SPECTRUM_MAX_HZ))
        max_index = count - 1
        scaled = []
        for index in range(count):
            ratio = (index + 0.5) / max(1.0, float(count))
            frequency = min_hz * ((max_hz / min_hz) ** ratio)
            source_pos = ((frequency - min_hz) / (max_hz - min_hz)) * max_index
            source_pos = max(0.0, min(float(max_index), source_pos))
            lower = int(math.floor(source_pos))
            upper = min(max_index, lower + 1)
            blend = source_pos - lower
            scaled.append((values[lower] * (1.0 - blend)) + (values[upper] * blend))
        return scaled

    def _spectrum_display_values(self, frame) -> list[float]:
        values = [max(0.0, min(1.0, float(value))) for value in frame or []]
        if self._frequency_scale == self.SPECTRUM_SCALE_LOG:
            values = self._log_scaled_spectrum_values(values)
        response = equalizer_response_for_bins(
            len(values),
            getattr(self, "_equalizer_settings", None),
            frequency_scale=self._frequency_scale,
            min_hz=self.SPECTRUM_MIN_HZ,
            max_hz=self.SPECTRUM_MAX_HZ,
        )
        if response:
            values = [
                max(0.0, min(1.0, value * response[index])) for index, value in enumerate(values)
            ]
        return values

    def _spectrum_line_segments(self, frame, visual_rect: QRectF):
        if not frame:
            return []
        values = self._spectrum_display_values(frame)
        if not values:
            return []
        left = float(visual_rect.left())
        bottom = float(visual_rect.bottom())
        height = max(1.0, float(visual_rect.height()))
        x_step = float(visual_rect.width()) / max(1, len(values) - 1)
        segments = []
        for index, value in enumerate(values):
            shaped = value**0.58
            x_pos = left + (index * x_step)
            top = bottom - (shaped * height)
            segments.append((x_pos, top, bottom, value))
        return segments

    def _visual_color_for_intensity(self, value: float, *, light_mode: bool) -> QColor:
        hotness = max(0.0, min(1.0, float(value))) ** 0.56
        hue = 0.62 * (1.0 - hotness)
        saturation = 0.99
        brightness = (0.74 + (hotness * 0.22)) if light_mode else (0.86 + (hotness * 0.14))
        alpha = (0.52 + (hotness * 0.44)) if light_mode else (0.58 + (hotness * 0.4))
        color = QColor()
        color.setHsvF(hue, saturation, min(1.0, brightness), min(1.0, alpha))
        return color

    def _draw_spectrum_graph(self, painter, rect, *, light_mode: bool) -> None:
        frame = self._current_spectrum_frame()
        opacity = max(0.0, min(1.0, self._fade_opacity))
        if not self._release_active:
            opacity *= max(0.0, min(1.0, self._gain))
        if not frame or opacity <= 0.0:
            return
        visual_rect = self._spectrum_graph_rect(rect)
        display_frame = [max(0.0, min(1.0, float(value) * opacity)) for value in frame]
        for x_pos, top, bottom, intensity in self._spectrum_line_segments(
            display_frame,
            visual_rect,
        ):
            color = self._visual_color_for_intensity(intensity, light_mode=light_mode)
            alpha = max(0.2, min(1.0, color.alphaF() * self.SPECTRUM_COLOR_ALPHA_BOOST))
            color.setAlphaF(alpha * opacity)
            painter.setPen(
                QPen(color, self.SPECTRUM_LINE_WIDTH, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
            )
            painter.drawLine(QPointF(x_pos, bottom), QPointF(x_pos, top))

    def mousePressEvent(self, event):
        event.ignore()

    def mouseMoveEvent(self, event):
        event.ignore()

    def wheelEvent(self, event):
        event.ignore()

    def paintEvent(self, e):
        from PySide6.QtGui import QPainter

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        pal = self.palette()
        bg = pal.window().color()
        lum = 0.2126 * bg.redF() + 0.7152 * bg.greenF() + 0.0722 * bg.blueF()
        light_mode = lum >= 0.5

        self._draw_spectrum_graph(p, self.rect(), light_mode=light_mode)


OscilloscopeWidget = SpectrumGraphWidget


def load_audio_harmonic_frames(path: str, *, target_sr: int = 22050):
    """
    Build normalized harmonic partial frames for the live playback visualizer.
    Returns: list[list[float]] with each value in [0.0, 1.0].
    """
    import os
    import shutil
    import subprocess

    try:
        import numpy as np
    except Exception:
        return []

    def _which(name: str):
        p = shutil.which(name)
        if p:
            return p
        sysname = platform.system().lower()
        search_dirs = []
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
        candidates = [name]
        if sysname == "windows" and not name.lower().endswith(".exe"):
            candidates.append(name + ".exe")
        for directory in search_dirs:
            for candidate in candidates:
                full_path = os.path.join(directory, candidate)
                if os.path.exists(full_path):
                    return full_path
        return None

    def _downsample(samples, sample_rate: int):
        clean_sample_rate = max(1, int(sample_rate or target_sr))
        if clean_sample_rate <= target_sr:
            return samples.astype(np.float32, copy=False), clean_sample_rate
        stride = max(1, int(round(clean_sample_rate / target_sr)))
        return samples[::stride].astype(np.float32, copy=False), max(1, clean_sample_rate // stride)

    def _decode_wav():
        import wave

        try:
            with open(path, "rb") as handle:
                head = handle.read(12)
            if len(head) < 12 or head[:4] != b"RIFF" or head[8:12] != b"WAVE":
                return None
            with wave.open(path, "rb") as wav_file:
                channels = max(1, wav_file.getnchannels())
                sample_width = wav_file.getsampwidth()
                sample_rate = wav_file.getframerate() or target_sr
                frame_count = wav_file.getnframes()
                if frame_count <= 0:
                    return None
                raw = wav_file.readframes(frame_count)
            if not raw:
                return None
            if sample_width == 1:
                values = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
            elif sample_width == 2:
                values = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
            elif sample_width == 3:
                data = np.frombuffer(raw, dtype=np.uint8)
                usable = (len(data) // 3) * 3
                if usable <= 0:
                    return None
                triples = data[:usable].reshape(-1, 3).astype(np.int32)
                values = triples[:, 0] | (triples[:, 1] << 8) | (triples[:, 2] << 16)
                values = np.where(values & 0x800000, values - 0x1000000, values).astype(np.float32)
                values = values / 8388608.0
            elif sample_width == 4:
                values = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0
            else:
                return None
            if channels > 1:
                usable = (len(values) // channels) * channels
                if usable <= 0:
                    return None
                values = values[:usable].reshape(-1, channels).mean(axis=1)
            return _downsample(np.clip(values, -1.0, 1.0), sample_rate)
        except Exception:
            return None

    def _decode_ffmpeg():
        ffmpeg = _which("ffmpeg")
        if not ffmpeg:
            return None
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
                    "s16le",
                    "-acodec",
                    "pcm_s16le",
                    "-ac",
                    "1",
                    "-ar",
                    str(target_sr),
                    "-",
                ],
                stderr=subprocess.STDOUT,
                timeout=30,
            )
            if not output:
                return None
            values = np.frombuffer(output, dtype="<i2").astype(np.float32) / 32768.0
            return np.clip(values, -1.0, 1.0), int(target_sr)
        except Exception:
            return None

    def _decode_soundfile():
        try:
            import soundfile as sf

            values, sample_rate = sf.read(path, dtype="float32", always_2d=True)
            if values.size <= 0:
                return None
            mono = values.mean(axis=1)
            return _downsample(np.clip(mono, -1.0, 1.0), int(sample_rate or target_sr))
        except Exception:
            return None

    decoded = _decode_wav() or _decode_ffmpeg() or _decode_soundfile()
    if decoded is None:
        return []
    samples, sample_rate = decoded
    if samples is None or len(samples) <= 0:
        return []

    sample_rate = max(1, int(sample_rate or target_sr))
    duration_ms = max(1, int((len(samples) / sample_rate) * 1000))
    frame_ms = max(60, int(duration_ms / 5000))
    hop = max(1, int(sample_rate * (frame_ms / 1000.0)))
    fft_size = 2048
    if len(samples) < fft_size:
        fft_size = 1024 if len(samples) >= 1024 else 512
    fft_size = max(128, int(fft_size))
    window = np.hanning(fft_size).astype(np.float32)
    freqs = np.fft.rfftfreq(fft_size, 1.0 / sample_rate)
    nyquist = sample_rate / 2.0

    raw_frames = []
    for start in range(0, len(samples), hop):
        segment = samples[start : start + fft_size]
        if len(segment) < fft_size:
            padded = np.zeros(fft_size, dtype=np.float32)
            padded[: len(segment)] = segment
            segment = padded
        spectrum = np.abs(np.fft.rfft(segment * window))
        usable_indexes = np.where((freqs >= 45.0) & (freqs <= min(1200.0, nyquist * 0.82)))[0]
        if len(usable_indexes) == 0:
            continue
        fundamental_index = usable_indexes[int(np.argmax(spectrum[usable_indexes]))]
        fundamental = float(freqs[fundamental_index])
        if fundamental <= 0:
            continue
        frame = []
        for harmonic_index in range(1, 15):
            center = fundamental * harmonic_index
            if center >= nyquist:
                frame.append(0.0)
                continue
            half_width = max(18.0, fundamental * 0.055 * harmonic_index)
            indexes = np.where((freqs >= center - half_width) & (freqs <= center + half_width))[0]
            if len(indexes) == 0:
                indexes = np.array([int(np.argmin(np.abs(freqs - center)))])
            band = spectrum[indexes]
            frame.append(float(np.sqrt(np.mean(band * band))) if len(band) else 0.0)
        raw_frames.append(frame)

    if not raw_frames:
        return []

    levels = np.log1p(np.asarray(raw_frames, dtype=np.float32) * 12.0)
    normalizer = float(np.percentile(levels, 96)) if levels.size else 0.0
    if normalizer > 0:
        levels = np.clip(levels / normalizer, 0.0, 1.0)
    else:
        levels = np.zeros_like(levels)
    levels = np.power(levels, 0.72)

    smoothed = []
    previous = None
    for frame in levels:
        if previous is None:
            current = frame
        else:
            current = (previous * 0.55) + (frame * 0.45)
        smoothed.append([float(max(0.0, min(1.0, value))) for value in current])
        previous = current
    return smoothed


def load_audio_peak_meter_frames(path: str, *, target_sr: int = 22050):
    """
    Build stereo peak frames in dBFS for the compact L/R peak meter.
    Returns: list[(left_db, right_db)] clamped to [-60.0, +3.0].
    """
    import os
    import shutil
    import subprocess

    try:
        import numpy as np
    except Exception:
        return []

    db_floor = float(StereoPeakMeterWidget.DB_FLOOR)
    db_top = float(StereoPeakMeterWidget.DB_TOP)

    def _which(name: str):
        p = shutil.which(name)
        if p:
            return p
        sysname = platform.system().lower()
        search_dirs = []
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
        candidates = [name]
        if sysname == "windows" and not name.lower().endswith(".exe"):
            candidates.append(name + ".exe")
        for directory in search_dirs:
            for candidate in candidates:
                full_path = os.path.join(directory, candidate)
                if os.path.exists(full_path):
                    return full_path
        return None

    def _stereo(values, channels: int):
        channels = max(1, int(channels or 1))
        usable = (len(values) // channels) * channels
        if usable <= 0:
            return None
        shaped = values[:usable].reshape(-1, channels)
        if channels == 1:
            return np.column_stack((shaped[:, 0], shaped[:, 0])).astype(np.float32, copy=False)
        return shaped[:, :2].astype(np.float32, copy=False)

    def _downsample(samples, sample_rate: int):
        clean_sample_rate = max(1, int(sample_rate or target_sr))
        if clean_sample_rate <= target_sr:
            return samples.astype(np.float32, copy=False), clean_sample_rate
        stride = max(1, int(round(clean_sample_rate / target_sr)))
        return samples[::stride].astype(np.float32, copy=False), max(1, clean_sample_rate // stride)

    def _decode_wav():
        import wave

        try:
            with open(path, "rb") as handle:
                head = handle.read(12)
            if len(head) < 12 or head[:4] != b"RIFF" or head[8:12] != b"WAVE":
                return None
            with wave.open(path, "rb") as wav_file:
                channels = max(1, wav_file.getnchannels())
                sample_width = wav_file.getsampwidth()
                sample_rate = wav_file.getframerate() or target_sr
                frame_count = wav_file.getnframes()
                if frame_count <= 0:
                    return None
                raw = wav_file.readframes(frame_count)
            if not raw:
                return None
            if sample_width == 1:
                values = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
            elif sample_width == 2:
                values = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
            elif sample_width == 3:
                data = np.frombuffer(raw, dtype=np.uint8)
                usable = (len(data) // 3) * 3
                if usable <= 0:
                    return None
                triples = data[:usable].reshape(-1, 3).astype(np.int32)
                values = triples[:, 0] | (triples[:, 1] << 8) | (triples[:, 2] << 16)
                values = np.where(values & 0x800000, values - 0x1000000, values).astype(np.float32)
                values = values / 8388608.0
            elif sample_width == 4:
                values = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0
            else:
                return None
            stereo = _stereo(values, channels)
            if stereo is None:
                return None
            return _downsample(stereo, sample_rate)
        except Exception:
            return None

    def _decode_ffmpeg():
        ffmpeg = _which("ffmpeg")
        if not ffmpeg:
            return None
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
                    "s16le",
                    "-acodec",
                    "pcm_s16le",
                    "-ac",
                    "2",
                    "-ar",
                    str(target_sr),
                    "-",
                ],
                stderr=subprocess.STDOUT,
                timeout=30,
            )
            if not output:
                return None
            values = np.frombuffer(output, dtype="<i2").astype(np.float32) / 32768.0
            stereo = _stereo(values, 2)
            if stereo is None:
                return None
            return stereo, int(target_sr)
        except Exception:
            return None

    def _decode_soundfile():
        try:
            import soundfile as sf

            values, sample_rate = sf.read(path, dtype="float32", always_2d=True)
            if values.size <= 0:
                return None
            if values.shape[1] == 1:
                stereo = np.column_stack((values[:, 0], values[:, 0]))
            else:
                stereo = values[:, :2]
            return _downsample(stereo.astype(np.float32, copy=False), int(sample_rate or target_sr))
        except Exception:
            return None

    decoded = _decode_wav() or _decode_ffmpeg() or _decode_soundfile()
    if decoded is None:
        return []
    samples, sample_rate = decoded
    if samples is None or len(samples) <= 0:
        return []

    sample_rate = max(1, int(sample_rate or target_sr))
    frame_ms = 33
    hop = max(1, int(sample_rate * (frame_ms / 1000.0)))
    frames = []
    for start in range(0, len(samples), hop):
        segment = samples[start : start + hop]
        if len(segment) <= 0:
            continue
        peaks = np.max(np.abs(segment), axis=0)
        frame = []
        for peak in peaks[:2]:
            peak = float(peak)
            if peak <= 0.000001:
                db_value = db_floor
            else:
                db_value = 20.0 * math.log10(peak)
            frame.append(max(db_floor, min(db_top, db_value)))
        if len(frame) == 1:
            frame.append(frame[0])
        frames.append((float(frame[0]), float(frame[1])))
    return frames


def load_audio_spectrum_frames(path: str, *, target_sr: int = 22050, bin_count: int = 192):
    """
    Build normalized linear-frequency FFT frames for the compact playback spectrum graph.
    Returns: list[list[float]] with each value in [0.0, 1.0].
    """
    import os
    import shutil
    import subprocess

    try:
        import numpy as np
    except Exception:
        return []

    bin_count = max(48, int(bin_count))

    def _which(name: str):
        p = shutil.which(name)
        if p:
            return p
        sysname = platform.system().lower()
        search_dirs = []
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
        candidates = [name]
        if sysname == "windows" and not name.lower().endswith(".exe"):
            candidates.append(name + ".exe")
        for directory in search_dirs:
            for candidate in candidates:
                full_path = os.path.join(directory, candidate)
                if os.path.exists(full_path):
                    return full_path
        return None

    def _downsample(samples, sample_rate: int):
        clean_sample_rate = max(1, int(sample_rate or target_sr))
        if clean_sample_rate <= target_sr:
            return samples.astype(np.float32, copy=False), clean_sample_rate
        stride = max(1, int(round(clean_sample_rate / target_sr)))
        return samples[::stride].astype(np.float32, copy=False), max(1, clean_sample_rate // stride)

    def _decode_wav():
        import wave

        try:
            with open(path, "rb") as handle:
                head = handle.read(12)
            if len(head) < 12 or head[:4] != b"RIFF" or head[8:12] != b"WAVE":
                return None
            with wave.open(path, "rb") as wav_file:
                channels = max(1, wav_file.getnchannels())
                sample_width = wav_file.getsampwidth()
                sample_rate = wav_file.getframerate() or target_sr
                frame_count = wav_file.getnframes()
                if frame_count <= 0:
                    return None
                raw = wav_file.readframes(frame_count)
            if not raw:
                return None
            if sample_width == 1:
                values = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
            elif sample_width == 2:
                values = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
            elif sample_width == 3:
                data = np.frombuffer(raw, dtype=np.uint8)
                usable = (len(data) // 3) * 3
                if usable <= 0:
                    return None
                triples = data[:usable].reshape(-1, 3).astype(np.int32)
                values = triples[:, 0] | (triples[:, 1] << 8) | (triples[:, 2] << 16)
                values = np.where(values & 0x800000, values - 0x1000000, values).astype(np.float32)
                values = values / 8388608.0
            elif sample_width == 4:
                values = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0
            else:
                return None
            if channels > 1:
                usable = (len(values) // channels) * channels
                if usable <= 0:
                    return None
                values = values[:usable].reshape(-1, channels).mean(axis=1)
            return _downsample(np.clip(values, -1.0, 1.0), sample_rate)
        except Exception:
            return None

    def _decode_ffmpeg():
        ffmpeg = _which("ffmpeg")
        if not ffmpeg:
            return None
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
                    "s16le",
                    "-acodec",
                    "pcm_s16le",
                    "-ac",
                    "1",
                    "-ar",
                    str(target_sr),
                    "-",
                ],
                stderr=subprocess.STDOUT,
                timeout=30,
            )
            if not output:
                return None
            values = np.frombuffer(output, dtype="<i2").astype(np.float32) / 32768.0
            return np.clip(values, -1.0, 1.0), int(target_sr)
        except Exception:
            return None

    def _decode_soundfile():
        try:
            import soundfile as sf

            values, sample_rate = sf.read(path, dtype="float32", always_2d=True)
            if values.size <= 0:
                return None
            mono = values.mean(axis=1)
            return _downsample(np.clip(mono, -1.0, 1.0), int(sample_rate or target_sr))
        except Exception:
            return None

    decoded = _decode_wav() or _decode_ffmpeg() or _decode_soundfile()
    if decoded is None:
        return []
    samples, sample_rate = decoded
    if samples is None or len(samples) <= 0:
        return []

    sample_rate = max(1, int(sample_rate or target_sr))
    duration_ms = max(1, int((len(samples) / sample_rate) * 1000))
    frame_ms = max(45, int(duration_ms / 6000))
    hop = max(1, int(sample_rate * (frame_ms / 1000.0)))
    fft_size = 4096
    if len(samples) < fft_size:
        fft_size = 2048 if len(samples) >= 2048 else 1024
    fft_size = max(256, int(fft_size))
    window = np.hanning(fft_size).astype(np.float32)
    freqs = np.fft.rfftfreq(fft_size, 1.0 / sample_rate)
    nyquist = sample_rate / 2.0
    max_freq = max(80.0, min(nyquist * 0.94, 18000.0))
    edges = np.linspace(20.0, max_freq, bin_count + 1)
    bin_indexes = []
    for index in range(bin_count):
        indexes = np.where((freqs >= edges[index]) & (freqs < edges[index + 1]))[0]
        if len(indexes) == 0:
            center = (edges[index] + edges[index + 1]) / 2.0
            indexes = np.array([int(np.argmin(np.abs(freqs - center)))])
        bin_indexes.append(indexes)

    raw_frames = []
    for start in range(0, len(samples), hop):
        segment = samples[start : start + fft_size]
        if len(segment) < fft_size:
            padded = np.zeros(fft_size, dtype=np.float32)
            padded[: len(segment)] = segment
            segment = padded
        spectrum = np.abs(np.fft.rfft(segment * window))
        frame = []
        for indexes in bin_indexes:
            band = spectrum[indexes]
            frame.append(float(np.sqrt(np.mean(band * band))) if len(band) else 0.0)
        raw_frames.append(frame)

    if not raw_frames:
        return []

    levels = np.log1p(np.asarray(raw_frames, dtype=np.float32) * 14.0)
    normalizer = float(np.percentile(levels, 97)) if levels.size else 0.0
    if normalizer > 0:
        levels = np.clip(levels / normalizer, 0.0, 1.0)
    else:
        levels = np.zeros_like(levels)
    levels = np.power(levels, 0.66)

    smoothed = []
    previous = None
    for frame in levels:
        if previous is None:
            current = frame
        else:
            current = (previous * 0.46) + (frame * 0.54)
        smoothed.append([float(max(0.0, min(1.0, value))) for value in current])
        previous = current
    return smoothed


__all__ = [
    "OscilloscopeWidget",
    "SpectrumGraphWidget",
    "StereoPeakMeterWidget",
    "load_audio_harmonic_frames",
    "load_audio_peak_meter_frames",
    "load_audio_spectrum_frames",
]

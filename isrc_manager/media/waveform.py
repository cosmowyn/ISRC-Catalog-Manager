import math

from PySide6.QtCore import (
    QEvent,
    QEventLoop,
    QPoint,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import QColor, QImage, QPen, QPixmap
from PySide6.QtMultimedia import QAudioDecoder, QAudioFormat
from PySide6.QtWidgets import QWidget


class WaveformWidget(QWidget):
    scrubRequested = Signal(int)
    seekRequested = Signal(int)
    WAVEFORM_DB_FLOOR = -96.0
    WAVEFORM_DB_STOPS = (
        0.0,
        -3.0,
        -6.0,
        -12.0,
        -18.0,
        -30.0,
        -48.0,
        -72.0,
        -96.0,
    )
    OSCILLOSCOPE_PHASE_SPAN_DEGREES = 180.0
    OSCILLOSCOPE_VERTICAL_ZOOM = 0.92
    OSCILLOSCOPE_MAX_AMPLITUDE = 0.54
    OSCILLOSCOPE_RESPONSE_LIFT = 1.28
    OSCILLOSCOPE_MAX_HARMONICS = 14
    STATIC_WAVEFORM_OPACITY = 0.92
    WAVEFORM_COLOR_SOFTEN_AMOUNT = 0.13

    def __init__(self, parent=None):
        super().__init__(parent)
        self._peaks = []
        self._peaks_version = 0
        self._waveform_cache = QPixmap()
        self._waveform_cache_key = None
        self._stored_waveform_pixmaps: dict[str, QPixmap] = {}
        self._stored_waveform_cache_key = None
        self._harmonic_frames = []
        self._bookmarks_ms: list[int] = []
        self._duration = 1
        self._playhead = 0
        self._preferred_height = 120
        self.setMinimumHeight(120)
        self.setCursor(Qt.SizeHorCursor)

    def set_preferred_height(self, height: int) -> None:
        next_height = max(1, int(height))
        if self._preferred_height == next_height:
            return
        self._preferred_height = next_height
        self.updateGeometry()

    def sizeHint(self) -> QSize:
        return QSize(480, self._preferred_height)

    def minimumSizeHint(self) -> QSize:
        return QSize(120, max(1, self.minimumHeight()))

    def set_peaks(self, peaks):
        self._peaks = peaks or []
        self._peaks_version += 1
        self._stored_waveform_pixmaps = {}
        self._stored_waveform_cache_key = None
        self._invalidate_waveform_cache()
        self.update()

    def set_cached_waveform(
        self,
        peaks,
        *,
        light_preview_png: bytes | None = None,
        dark_preview_png: bytes | None = None,
        cache_key: object | None = None,
    ) -> None:
        self._peaks = peaks or []
        self._peaks_version += 1
        self._stored_waveform_pixmaps = {}
        for theme_key, payload in (
            ("light", light_preview_png),
            ("dark", dark_preview_png),
        ):
            if not payload:
                continue
            pixmap = QPixmap()
            if pixmap.loadFromData(bytes(payload), "PNG") and not pixmap.isNull():
                self._stored_waveform_pixmaps[theme_key] = pixmap
        self._stored_waveform_cache_key = cache_key
        self._invalidate_waveform_cache()
        self.update()

    def set_harmonic_frames(self, frames):
        cleaned = []
        for frame in frames or []:
            try:
                values = [max(0.0, min(1.0, float(value))) for value in frame]
            except (TypeError, ValueError):
                continue
            if values:
                cleaned.append(values)
        self._harmonic_frames = cleaned
        self.update()

    def set_spectrum_frames(self, frames):
        self.set_harmonic_frames(frames)

    def has_live_visualization(self) -> bool:
        return bool(self._harmonic_frames)

    def set_duration_ms(self, ms):
        self._duration = max(1, int(ms))
        self.update()

    def set_playhead_ms(self, ms):
        next_playhead = max(0, min(int(ms), self._duration))
        if next_playhead == self._playhead:
            return
        previous_playhead = self._playhead
        self._playhead = next_playhead
        if self._peaks:
            self._update_playhead_regions(previous_playhead, next_playhead)
        else:
            self.update()

    def set_bookmarks_ms(self, positions_ms) -> None:
        cleaned: list[int] = []
        seen: set[int] = set()
        for position_ms in positions_ms or []:
            try:
                clean_position = max(0, int(position_ms))
            except (TypeError, ValueError):
                continue
            if clean_position in seen:
                continue
            cleaned.append(clean_position)
            seen.add(clean_position)
        cleaned.sort()
        if cleaned == self._bookmarks_ms:
            return
        self._bookmarks_ms = cleaned
        self.update()

    def _position_from_x(self, x_pos: float) -> int:
        rect = self.rect()
        if rect.width() <= 1:
            return 0
        ratio = max(0.0, min(1.0, (float(x_pos) - rect.left()) / max(1, rect.width() - 1)))
        return int(self._duration * ratio)

    def _playhead_x_for_ms(self, ms: int) -> int:
        rect = self.rect()
        if rect.width() <= 1 or self._duration <= 0:
            return rect.left()
        ratio = max(0.0, min(1.0, int(ms) / self._duration))
        return int(rect.left() + ((rect.width() - 1) * ratio))

    def _update_playhead_regions(self, *positions_ms: int) -> None:
        rect = self.rect()
        if rect.isNull():
            self.update()
            return
        for position_ms in positions_ms:
            x_pos = self._playhead_x_for_ms(position_ms)
            self.update(QRect(x_pos - 3, rect.top(), 7, rect.height()))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            x_pos = event.position().x() if hasattr(event, "position") else event.pos().x()
            self.seekRequested.emit(self._position_from_x(x_pos))
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            x_pos = event.position().x() if hasattr(event, "position") else event.pos().x()
            self.seekRequested.emit(self._position_from_x(x_pos))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def wheelEvent(self, event):
        pixel_delta = event.pixelDelta()
        angle_delta = event.angleDelta()
        delta_ms = 0
        if not pixel_delta.isNull():
            if abs(pixel_delta.x()) >= abs(pixel_delta.y()) and pixel_delta.x():
                delta_ms = int(round((pixel_delta.x() / 40.0) * 1000))
            elif pixel_delta.y():
                delta_ms = int(round((-pixel_delta.y() / 40.0) * 1000))
        elif not angle_delta.isNull():
            if abs(angle_delta.x()) >= abs(angle_delta.y()) and angle_delta.x():
                delta_ms = int(round((angle_delta.x() / 120.0) * 1000))
            elif angle_delta.y():
                delta_ms = int(round((-angle_delta.y() / 120.0) * 1000))
        if delta_ms:
            self.scrubRequested.emit(delta_ms)
            event.accept()
            return
        event.ignore()

    def _harmonic_frame_position(self) -> float:
        if len(self._harmonic_frames) <= 1:
            return 0.0
        ratio = max(0.0, min(1.0, self._playhead / max(1, self._duration)))
        return ratio * (len(self._harmonic_frames) - 1)

    def _harmonic_frame_at_position(self, frame_pos: float):
        if not self._harmonic_frames:
            return []
        if len(self._harmonic_frames) == 1:
            return self._harmonic_frames[0]
        frame_pos = max(0.0, min(float(frame_pos), len(self._harmonic_frames) - 1))
        lower_index = int(frame_pos)
        upper_index = min(len(self._harmonic_frames) - 1, lower_index + 1)
        blend = frame_pos - lower_index
        lower = self._harmonic_frames[lower_index]
        upper = self._harmonic_frames[upper_index]
        count = min(len(lower), len(upper))
        if count <= 0:
            return []
        if blend <= 0:
            return lower[:count]
        return [(lower[index] * (1.0 - blend)) + (upper[index] * blend) for index in range(count)]

    def _current_harmonic_frame(self):
        return self._harmonic_frame_at_position(self._harmonic_frame_position())

    def _harmonic_rect(self, rect) -> QRectF:
        return QRectF(
            float(rect.left()),
            float(rect.top()),
            float(rect.width()),
            max(1.0, float(rect.height()) * 0.62),
        )

    def _waveform_rect(self, rect) -> QRectF:
        return QRectF(
            float(rect.left()),
            float(rect.top()),
            float(rect.width()),
            max(1.0, float(rect.height())),
        )

    def _invalidate_waveform_cache(self) -> None:
        self._waveform_cache = QPixmap()
        self._waveform_cache_key = None

    def resizeEvent(self, event):
        self._invalidate_waveform_cache()
        super().resizeEvent(event)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (
            QEvent.PaletteChange,
            QEvent.ApplicationPaletteChange,
            QEvent.StyleChange,
        ):
            self._invalidate_waveform_cache()

    @staticmethod
    def _relative_luminance(color: QColor) -> float:
        return 0.2126 * color.redF() + 0.7152 * color.greenF() + 0.0722 * color.blueF()

    def _window_background_color(self) -> QColor:
        widget = self.window()
        if widget is not None:
            return widget.palette().window().color()
        return self.palette().window().color()

    def _waveform_cache_key_for(self, rect: QRectF):
        background = self._window_background_color()
        return (
            self._peaks_version,
            int(self.width()),
            int(self.height()),
            round(float(self.devicePixelRatioF()), 3),
            round(float(rect.left()), 2),
            round(float(rect.top()), 2),
            round(float(rect.width()), 2),
            round(float(rect.height()), 2),
            background.name(QColor.HexArgb),
        )

    def _empty_waveform_pixmap(self) -> QPixmap:
        if self.size().isEmpty():
            return QPixmap()
        dpr = max(1.0, float(self.devicePixelRatioF()))
        pixmap_size = QSize(
            max(1, int(math.ceil(self.width() * dpr))),
            max(1, int(math.ceil(self.height() * dpr))),
        )
        pixmap = QPixmap(pixmap_size)
        pixmap.setDevicePixelRatio(dpr)
        pixmap.fill(Qt.transparent)
        return pixmap

    def _fallback_waveform_rgb_for_peak(self, peak: float) -> tuple[int, int, int]:
        peak = max(0.0, min(1.0, float(peak)))
        if peak >= 0.72:
            return self._soften_waveform_rgb((255, 45, 16))
        if peak >= 0.46:
            return self._soften_waveform_rgb((255, 117, 18))
        if peak >= 0.24:
            return self._soften_waveform_rgb((245, 206, 38))
        return self._soften_waveform_rgb((35, 214, 95))

    def _soften_waveform_rgb(self, rgb: tuple[int, int, int]) -> tuple[int, int, int]:
        amount = max(0.0, min(1.0, self.WAVEFORM_COLOR_SOFTEN_AMOUNT))
        red, green, blue = (max(0, min(255, int(channel))) for channel in rgb)
        luma = (0.2126 * red) + (0.7152 * green) + (0.0722 * blue)
        return (
            int(round((red * (1.0 - amount)) + (luma * amount))),
            int(round((green * (1.0 - amount)) + (luma * amount))),
            int(round((blue * (1.0 - amount)) + (luma * amount))),
        )

    def _shade_static_waveform_color(
        self,
        rgb: tuple[int, int, int],
        *,
        peak: float,
        edge_ratio: float,
    ) -> QColor:
        background = self._window_background_color()
        light_background = self._relative_luminance(background) >= 0.5
        peak = max(0.0, min(1.0, float(peak)))
        edge_ratio = max(0.0, min(1.0, float(edge_ratio)))
        if light_background:
            base_scale = 0.42 + (0.22 * peak)
            edge_lift = 0.26 * (edge_ratio**0.7)
        else:
            base_scale = 0.58 + (0.18 * peak)
            edge_lift = 0.30 * (edge_ratio**0.7)
        scale = min(1.18, base_scale + edge_lift)
        highlight = 0.10 * (edge_ratio**1.8) if not light_background else 0.04 * edge_ratio
        red = int(max(0, min(255, (rgb[0] * scale) + (255 * highlight))))
        green = int(max(0, min(255, (rgb[1] * scale) + (255 * highlight))))
        blue = int(max(0, min(255, (rgb[2] * scale) + (255 * highlight))))
        return QColor(red, green, blue, 255)

    def _render_static_waveform_cache(self, rect: QRectF) -> QPixmap:
        if not self._peaks or self.size().isEmpty():
            return QPixmap()
        pixmap = self._empty_waveform_pixmap()
        dpr = max(1.0, float(pixmap.devicePixelRatioF()))
        image = QImage(pixmap.size(), QImage.Format_ARGB32_Premultiplied)
        image.setDevicePixelRatio(dpr)
        image.fill(Qt.transparent)
        physical_rect = QRectF(
            float(rect.left()) * dpr,
            float(rect.top()) * dpr,
            float(rect.width()) * dpr,
            float(rect.height()) * dpr,
        )
        mid = float(physical_rect.center().y())
        center_y = max(0, min(image.height() - 1, int(round(mid))))
        amplitude = max(1.0, float(physical_rect.height()) * 0.47)
        width = max(1, int(round(physical_rect.width())))
        peak_count = max(1, len(self._peaks))
        for x_offset in range(width):
            peak_index = min(peak_count - 1, int((x_offset / max(1, width - 1)) * (peak_count - 1)))
            low, high = self._peaks[peak_index]
            top_peak = max(0.0, min(1.0, float(high)))
            bottom_peak = max(0.0, min(1.0, -float(low)))
            dominant_peak = max(top_peak, bottom_peak)
            if dominant_peak <= 0.0:
                continue
            base_rgb = self._fallback_waveform_rgb_for_peak(dominant_peak)
            x_pos = int(round(physical_rect.left())) + x_offset
            if x_pos < 0 or x_pos >= image.width():
                continue
            if top_peak > 0.0:
                start_y = max(0, int(round(mid - (top_peak * amplitude))))
                end_y = center_y
                for y_pos in range(start_y, end_y + 1):
                    edge_ratio = abs(float(y_pos) - mid) / max(1.0, top_peak * amplitude)
                    image.setPixelColor(
                        x_pos,
                        y_pos,
                        self._shade_static_waveform_color(
                            base_rgb,
                            peak=top_peak,
                            edge_ratio=edge_ratio,
                        ),
                    )
            if bottom_peak > 0.0:
                start_y = center_y
                end_y = max(0, min(image.height() - 1, int(round(mid + (bottom_peak * amplitude)))))
                for y_pos in range(start_y, end_y + 1):
                    edge_ratio = abs(float(y_pos) - mid) / max(1.0, bottom_peak * amplitude)
                    image.setPixelColor(
                        x_pos,
                        y_pos,
                        self._shade_static_waveform_color(
                            base_rgb,
                            peak=bottom_peak,
                            edge_ratio=edge_ratio,
                        ),
                    )
        pixmap = QPixmap.fromImage(image)
        return pixmap

    def _static_waveform_pixmap(self, rect: QRectF) -> QPixmap:
        cache_key = self._waveform_cache_key_for(rect)
        if self._waveform_cache_key != cache_key or self._waveform_cache.isNull():
            self._waveform_cache = self._render_static_waveform_cache(rect)
            self._waveform_cache_key = cache_key
        return self._waveform_cache

    def _stored_waveform_theme_key(self) -> str:
        background = self._window_background_color()
        return "light" if self._relative_luminance(background) >= 0.5 else "dark"

    def _stored_waveform_pixmap(self) -> QPixmap | None:
        if not self._stored_waveform_pixmaps:
            return None
        theme_key = self._stored_waveform_theme_key()
        pixmap = self._stored_waveform_pixmaps.get(theme_key)
        if pixmap is not None and not pixmap.isNull():
            return pixmap
        for candidate in self._stored_waveform_pixmaps.values():
            if not candidate.isNull():
                return candidate
        return None

    def _visual_color_for_intensity(self, value: float, *, light_mode: bool) -> QColor:
        hotness = max(0.0, min(1.0, float(value))) ** 0.62
        hue = 0.62 * (1.0 - hotness)
        saturation = 0.92
        lightness = (0.48 + (hotness * 0.2)) if light_mode else (0.58 + (hotness * 0.18))
        alpha = (0.36 + (hotness * 0.52)) if light_mode else (0.42 + (hotness * 0.5))
        color = QColor()
        color.setHslF(hue, saturation, min(0.82, lightness), min(0.96, alpha))
        return color

    def _harmonic_frame_energy(self, frame) -> float:
        if not frame:
            return 0.0
        values = [
            max(0.0, min(1.0, float(value))) for value in frame[: self.OSCILLOSCOPE_MAX_HARMONICS]
        ]
        if not values:
            return 0.0
        peak = max(values)
        mean = sum(values) / max(1, len(values))
        fundamental = values[0]
        energy = (peak * 0.72) + (fundamental * 0.18) + (mean * 0.1)
        lifted = max(0.0, min(1.0, energy * self.OSCILLOSCOPE_RESPONSE_LIFT))
        return lifted**0.74

    def _harmonic_trace_points(
        self,
        frame,
        visual_rect: QRectF,
        *,
        phase_offset: float = 0.0,
        amplitude_scale: float = 1.0,
    ):
        if frame is None:
            return [], []
        width = max(2, int(visual_rect.width()))
        center_y = visual_rect.center().y()
        frame_values = [
            max(0.0, min(1.0, float(value))) for value in frame[: self.OSCILLOSCOPE_MAX_HARMONICS]
        ]
        energy = self._harmonic_frame_energy(frame_values)
        amplitude = min(
            visual_rect.height() * self.OSCILLOSCOPE_MAX_AMPLITUDE,
            visual_rect.height()
            * self.OSCILLOSCOPE_VERTICAL_ZOOM
            * energy
            * float(amplitude_scale),
        )
        phase_span = math.radians(self.OSCILLOSCOPE_PHASE_SPAN_DEGREES)
        points = []
        intensities = []
        for x_offset in range(width):
            x_ratio = x_offset / max(1, width - 1)
            phase = (phase_span * x_ratio) + phase_offset
            value = 0.0
            weight_sum = 0.0
            for harmonic_index, harmonic_level in enumerate(frame_values, start=1):
                if harmonic_level <= 0.001:
                    continue
                weight = harmonic_level / (harmonic_index**0.42)
                value += weight * math.sin(phase * harmonic_index)
                weight_sum += weight
            normalized = value / weight_sum if weight_sum else 0.0
            normalized = max(-1.0, min(1.0, normalized))
            points.append((visual_rect.left() + x_offset, center_y - (normalized * amplitude)))
            intensities.append(max(0.0, min(1.0, energy * (0.62 + (abs(normalized) * 0.38)))))
        return points, intensities

    def _draw_harmonic_trace(
        self,
        painter,
        points,
        intensities,
        *,
        light_mode: bool,
        alpha_scale: float,
        width_scale: float,
    ) -> None:
        if len(points) < 2:
            return
        for index in range(len(points) - 1):
            intensity = (intensities[index] + intensities[index + 1]) / 2.0
            color = self._visual_color_for_intensity(intensity, light_mode=light_mode)
            color.setAlphaF(max(0.02, min(0.9, color.alphaF() * float(alpha_scale))))
            glow = QColor(color)
            glow.setAlphaF(min(0.32, color.alphaF() * 0.52))
            painter.setPen(QPen(glow, 4.2 * width_scale, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.drawLine(
                int(points[index][0]),
                int(points[index][1]),
                int(points[index + 1][0]),
                int(points[index + 1][1]),
            )
            painter.setPen(QPen(color, 1.45 * width_scale, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.drawLine(
                int(points[index][0]),
                int(points[index][1]),
                int(points[index + 1][0]),
                int(points[index + 1][1]),
            )

    def _draw_live_harmonics(self, painter, rect, *, light_mode: bool) -> None:
        if not self._harmonic_frames:
            return
        visual_rect = self._harmonic_rect(rect)
        painter.save()
        frame = self._current_harmonic_frame()
        if frame is not None:
            points, intensities = self._harmonic_trace_points(frame, visual_rect)
            self._draw_harmonic_trace(
                painter,
                points,
                intensities,
                light_mode=light_mode,
                alpha_scale=1.0,
                width_scale=1.08,
            )
        painter.restore()

    def paintEvent(self, e):
        from PySide6.QtGui import QColor, QPainter, QPen

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        r = self.rect()
        waveform_rect = self._waveform_rect(r)

        # Decide colors based on window background brightness
        bg = self._window_background_color()
        lum = self._relative_luminance(bg)
        light_mode = lum >= 0.5

        playhead_color = QColor(255, 255, 255) if light_mode else QColor(0, 0, 0)

        # waveform (vertical min–max bars)
        if self._peaks:
            stored_pixmap = self._stored_waveform_pixmap()
            p.save()
            p.setOpacity(self.STATIC_WAVEFORM_OPACITY)
            if stored_pixmap is not None:
                p.setRenderHint(QPainter.SmoothPixmapTransform, False)
                p.drawPixmap(waveform_rect, stored_pixmap, QRectF(stored_pixmap.rect()))
            else:
                p.drawPixmap(QPoint(0, 0), self._static_waveform_pixmap(waveform_rect))
            p.restore()

        if self._bookmarks_ms and self._duration > 0:
            marker_color = QColor("#0A84FF" if light_mode else "#4DA3FF")
            marker_shadow = QColor(0, 0, 0, 70) if light_mode else QColor(255, 255, 255, 60)
            for position_ms in self._bookmarks_ms:
                ratio = max(0.0, min(1.0, position_ms / self._duration))
                x = r.left() + (r.width() - 1) * ratio
                x_pos = int(round(x))
                p.setPen(QPen(marker_shadow, 3))
                p.drawLine(x_pos, int(waveform_rect.top()), x_pos, int(waveform_rect.bottom()))
                p.setPen(QPen(marker_color, 2))
                p.drawLine(x_pos, int(waveform_rect.top()), x_pos, int(waveform_rect.bottom()))

        # playhead
        if self._duration > 0:
            x = r.left() + (r.width() - 1) * (self._playhead / self._duration)
            p.setPen(QPen(playhead_color))
            p.drawLine(int(x), int(waveform_rect.top()), int(x), int(waveform_rect.bottom()))


def load_wav_peaks(path: str, width_px: int):
    """
    Build stereo peaks for drawing a waveform.
    - Fast path: RIFF/WAVE (16, 24, 32-bit PCM) via `wave`.
    - Generic path: decode any compressed format to stereo s16le via ffmpeg (if present),
      else fallback to QtMultimedia's decoder, then `audioread` as a last resort.
    Returns: list[(-right_peak, left_peak)] in [-1.0, 1.0].
    """
    import os
    import shutil
    import struct
    import subprocess

    width_px = max(1, int(width_px))
    buckets = width_px * 4  # ~4 samples/bucket for smooth lines

    def _clamp_peak(value: float) -> float:
        if value < -1.0:
            return -1.0
        if value > 1.0:
            return 1.0
        return value

    def _append_pending_peak(peaks, left_peak: float, right_peak: float) -> None:
        peaks.append((-abs(_clamp_peak(right_peak)), abs(_clamp_peak(left_peak))))

    def _load_peaks_via_qt_decoder():
        decoder = QAudioDecoder()
        if not decoder.isSupported():
            return None

        state = {
            "peaks": [],
            "sample_rate": 44100,
            "target_step": None,
            "need": None,
            "left_peak": 0.0,
            "right_peak": 0.0,
            "bucket_had_sample": False,
            "had_buffer": False,
            "timed_out": False,
            "decode_error": None,
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
                return _clamp_peak(struct.unpack_from("<f", raw, offset)[0])
            return None

        def _finish_pending_peak() -> None:
            if state["bucket_had_sample"]:
                _append_pending_peak(state["peaks"], state["left_peak"], state["right_peak"])
                state["left_peak"], state["right_peak"] = 0.0, 0.0
                state["bucket_had_sample"] = False

        def _on_buffer_ready() -> None:
            buf = decoder.read()
            if not buf.isValid():
                return

            fmt = buf.format()
            frame_bytes = fmt.bytesPerFrame()
            bytes_per_sample = fmt.bytesPerSample()
            if frame_bytes <= 0:
                channels = max(1, fmt.channelCount())
                frame_bytes = bytes_per_sample * channels
            if frame_bytes <= 0:
                return
            channels = max(1, fmt.channelCount())

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
                    int((sample_rate * duration_ms) / 1000)
                    if duration_ms and duration_ms > 0
                    else None
                )
                state["sample_rate"] = sample_rate
                state["target_step"] = max(
                    1, (total_samples // buckets) if total_samples else (sample_rate // 100)
                )
                state["need"] = state["target_step"]

            raw = bytes(buf.data())
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
                if channels > 1 and bytes_per_sample > 0:
                    decoded_right = _sample_value(raw, offset + bytes_per_sample, sample_format)
                    if decoded_right is not None:
                        right_value = decoded_right
                state["left_peak"] = max(state["left_peak"], abs(left_value))
                state["right_peak"] = max(state["right_peak"], abs(right_value))
                state["bucket_had_sample"] = True
                state["need"] -= 1
                if state["need"] == 0:
                    _finish_pending_peak()
                    state["need"] = state["target_step"]

        def _on_finished() -> None:
            loop.quit()

        def _on_error(*_args) -> None:
            state["decode_error"] = decoder.errorString() or "QtMultimedia decode failed"
            loop.quit()

        def _on_timeout() -> None:
            state["timed_out"] = True
            try:
                decoder.stop()
            finally:
                loop.quit()

        decoder.bufferReady.connect(_on_buffer_ready)
        decoder.finished.connect(_on_finished)
        decoder.error.connect(_on_error)
        timeout.timeout.connect(_on_timeout)

        decoder.setSource(QUrl.fromLocalFile(os.fspath(path)))
        decoder.start()
        timeout.start(5000)
        loop.exec()
        timeout.stop()

        _finish_pending_peak()
        if state["peaks"]:
            return state["peaks"]

        if state["had_buffer"]:
            return [(-0.0, 0.0)]

        if state["decode_error"] or state["timed_out"]:
            return None

        return None

    # --- helper: best-effort find a binary on common paths ---
    def _which(name: str):
        import os
        import platform

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

        # try plain name and .exe on Windows
        candidates = [name]
        if sysname == "windows" and not name.lower().endswith(".exe"):
            candidates.append(name + ".exe")

        for d in search_dirs:
            for cand in candidates:
                full = os.path.join(d, cand)
                if os.path.exists(full):
                    return full
        return None

    # --- WAV fast path -------------------------------------------------------
    try:
        with open(path, "rb") as f:
            head = f.read(12)
        if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WAVE":
            import wave

            with wave.open(path, "rb") as w:
                ch = max(1, w.getnchannels())
                sampwidth = w.getsampwidth()  # bytes: 2, 3, 4
                nframes = w.getnframes()
                if nframes <= 0:
                    return []

                step = max(1, nframes // buckets)
                fs = 32768.0 if sampwidth == 2 else (8388608.0 if sampwidth == 3 else 2147483648.0)

                peaks = []
                for i in range(0, nframes, step):
                    w.setpos(i)
                    frames = min(step, nframes - i)
                    raw = w.readframes(frames)
                    if not raw:
                        continue

                    if sampwidth == 2:
                        count = len(raw) // 2
                        if count == 0:
                            continue
                        vals = struct.unpack("<" + "h" * count, raw)
                        usable = (len(vals) // ch) * ch
                        if usable <= 0:
                            continue
                        left_vals = vals[:usable:ch]
                        right_vals = vals[1:usable:ch] if ch > 1 else left_vals
                        left_peak = max(abs(value) for value in left_vals) / fs
                        right_peak = max(abs(value) for value in right_vals) / fs
                    elif sampwidth == 3:
                        b = raw
                        count = len(b) // (3 * ch)
                        if count <= 0:
                            continue
                        step_bytes = 3 * ch
                        left_peak_value = 0
                        right_peak_value = 0

                        def _read_s24(offset: int) -> int:
                            b0, b1, b2 = b[offset], b[offset + 1], b[offset + 2]
                            value = b0 | (b1 << 8) | (b2 << 16)
                            if value & 0x800000:
                                value -= 0x1000000
                            return value

                        for off in range(0, count * step_bytes, step_bytes):
                            left_value = _read_s24(off)
                            right_value = _read_s24(off + 3) if ch > 1 else left_value
                            left_peak_value = max(left_peak_value, abs(left_value))
                            right_peak_value = max(right_peak_value, abs(right_value))
                        left_peak = left_peak_value / fs
                        right_peak = right_peak_value / fs
                    elif sampwidth == 4:
                        count = len(raw) // 4
                        if count == 0:
                            continue
                        vals = struct.unpack("<" + "i" * count, raw)
                        usable = (len(vals) // ch) * ch
                        if usable <= 0:
                            continue
                        left_vals = vals[:usable:ch]
                        right_vals = vals[1:usable:ch] if ch > 1 else left_vals
                        left_peak = max(abs(value) for value in left_vals) / fs
                        right_peak = max(abs(value) for value in right_vals) / fs
                    else:
                        continue

                    peaks.append((-min(1.0, float(right_peak)), min(1.0, float(left_peak))))
                return peaks
    except Exception:
        pass

    # --- Generic path A: ffmpeg streaming to stereo s16le --------------------
    ffmpeg = _which("ffmpeg")
    if ffmpeg:
        sr = 44100
        # Try to get duration for bucket sizing
        total_samples = None
        ffprobe = _which("ffprobe")
        if ffprobe:
            try:
                out = (
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
                    )
                    .decode("utf-8", "replace")
                    .strip()
                )
                if out:
                    d = float(out)
                    if d > 0:
                        total_samples = int(sr * d)
            except Exception:
                total_samples = None

        target_step = max(
            1, (total_samples // buckets) if total_samples else (sr // 100)
        )  # ~10 ms if unknown

        try:
            p = subprocess.Popen(
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
                    str(sr),
                    "-",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            peaks = []
            fs = 32768.0
            need = target_step
            left_peak, right_peak = 0.0, 0.0
            bucket_had_sample = False
            buf = bytearray()

            while True:
                chunk = p.stdout.read(8192)
                if not chunk:
                    break
                buf.extend(chunk)

                frame_bytes = 4
                n_frames = len(buf) // frame_bytes
                if n_frames <= 0:
                    continue

                off_frames = 0
                import struct as _st

                while n_frames > 0:
                    take = min(need, n_frames)
                    data_len = take * frame_bytes
                    data = bytes(
                        buf[off_frames * frame_bytes : off_frames * frame_bytes + data_len]
                    )  # copy; safe to resize buf
                    for i in range(0, len(data), frame_bytes):
                        left_value = _st.unpack_from("<h", data, i)[0] / fs
                        right_value = _st.unpack_from("<h", data, i + 2)[0] / fs
                        left_peak = max(left_peak, abs(left_value))
                        right_peak = max(right_peak, abs(right_value))
                        bucket_had_sample = True
                    need -= take
                    off_frames += take
                    n_frames -= take

                    if need == 0:
                        if bucket_had_sample:
                            peaks.append((-min(1.0, right_peak), min(1.0, left_peak)))
                        left_peak, right_peak = 0.0, 0.0
                        bucket_had_sample = False
                        need = target_step

                # drop consumed bytes
                del buf[: off_frames * frame_bytes]

            p.stdout.close()
            try:
                p.wait(timeout=2)
            except Exception:
                p.kill()

            if bucket_had_sample:
                peaks.append((-min(1.0, right_peak), min(1.0, left_peak)))

            return peaks or [(-0.0, 0.0)]
        except Exception:
            pass  # fall through to audioread

    # --- Generic path B: QtMultimedia decoder fallback -----------------------
    try:
        peaks = _load_peaks_via_qt_decoder()
        if peaks:
            return peaks
    except Exception:
        pass

    # --- Generic path C: audioread fallback (pip install audioread) ----------
    # audioread 3.0.1 still imports stdlib `aifc` via rawread, which breaks on
    # Python 3.13. Keep it only as a legacy fallback behind the Qt path.
    try:
        import struct as _st

        import audioread

        peaks = []
        with audioread.audio_open(path) as f:
            sr = f.samplerate or 44100
            duration = getattr(f, "duration", None)
            total_samples = int(sr * duration) if duration else None
            # frames = samples *per channel*; audioread blocks are interleaved across channels
            ch = max(1, getattr(f, "channels", 1))
            frame_bytes = 2 * ch  # 16-bit signed little-endian per sample * channels
            target_step = max(
                1, (total_samples // buckets) if total_samples else (sr // 100)
            )  # ~10 ms if unknown

            fs = 32768.0
            need = target_step
            left_peak, right_peak = 0.0, 0.0
            bucket_had_sample = False
            buf = bytearray()

            for block in f:  # raw 16-bit little-endian PCM
                buf.extend(block)
                frames = len(buf) // frame_bytes
                if frames <= 0:
                    continue

                off_frames = 0
                while frames > 0:
                    take = min(need, frames)
                    data_len = take * frame_bytes
                    data = bytes(
                        buf[off_frames * frame_bytes : off_frames * frame_bytes + data_len]
                    )  # copy
                    for i in range(0, len(data), frame_bytes):
                        left_value = _st.unpack_from("<h", data, i)[0] / fs
                        right_value = (
                            _st.unpack_from("<h", data, i + 2)[0] / fs if ch > 1 else left_value
                        )
                        left_peak = max(left_peak, abs(left_value))
                        right_peak = max(right_peak, abs(right_value))
                        bucket_had_sample = True
                    need -= take
                    off_frames += take
                    frames -= take
                    if need == 0:
                        if bucket_had_sample:
                            peaks.append((-min(1.0, right_peak), min(1.0, left_peak)))
                        left_peak, right_peak = 0.0, 0.0
                        bucket_had_sample = False
                        need = target_step

                del buf[: off_frames * frame_bytes]

            if bucket_had_sample:
                peaks.append((-min(1.0, right_peak), min(1.0, left_peak)))

            return peaks or [(-0.0, 0.0)]
    except Exception:
        pass

    # Last resort
    return []


__all__ = ["WaveformWidget", "load_wav_peaks"]

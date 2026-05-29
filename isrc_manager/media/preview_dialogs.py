"""Media preview dialogs and audio preview preload helpers."""

from __future__ import annotations

import json
import mimetypes
import os
import platform
import random
import sqlite3
import tempfile
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QIcon,
    QImage,
    QKeySequence,
    QPainter,
    QPalette,
    QPen,
    QPixmap,
    QShortcut,
)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLayout,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPinchGesture,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from isrc_manager.file_storage import (
    STORAGE_MODE_MANAGED_FILE,
    ManagedFileStorage,
    bytes_from_blob,
    infer_storage_mode,
)
from isrc_manager.media.audio_visualization import (
    SpectrumGraphWidget,
    StereoPeakMeterWidget,
    load_audio_peak_meter_frames,
    load_audio_spectrum_frames,
)
from isrc_manager.media.bookmarks import (
    AudioBookmark,
    add_audio_bookmark,
    delete_audio_bookmark,
    delete_audio_bookmarks_for_track,
    load_audio_bookmarks,
)
from isrc_manager.media.equalizer import (
    EqualizerDialog,
    equalizer_is_enabled,
    load_equalizer_settings,
    normalize_equalizer_settings,
    save_equalizer_settings,
)
from isrc_manager.media.equalizer_player import LiveEqualizerPlayer, _decode_audio_file
from isrc_manager.media.waveform import WaveformWidget, load_wav_peaks
from isrc_manager.paths import RES_DIR
from isrc_manager.services import TrackService, TrackSnapshot
from isrc_manager.services.db_access import SQLiteConnectionFactory
from isrc_manager.tags.models import ArtworkPayload
from isrc_manager.ui_common import (
    FocusWheelSlider,
    _add_standard_dialog_header,
    _apply_standard_dialog_chrome,
    _create_round_help_button,
    _create_standard_section,
)


class _ImagePreviewDialog(QDialog):
    def __init__(self, app, parent=None):
        super().__init__(parent, Qt.Window)
        self.app = app
        self._base_pix = QPixmap()
        self._current_pct = 100
        self._current_title = ""
        self._current_data = b""
        self._current_mime = "image/png"
        self._user_zoomed = False

        self.setObjectName("imagePreviewDialog")
        self.setWindowFlags(
            Qt.Window
            | Qt.WindowTitleHint
            | Qt.WindowSystemMenuHint
            | Qt.WindowCloseButtonHint
            | Qt.WindowMinMaxButtonsHint
        )
        self.setModal(False)
        self.setWindowModality(Qt.NonModal)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.setAttribute(Qt.WA_NativeWindow, True)
        self.setAttribute(Qt.WA_QuitOnClose, False)
        self.setWindowTitle("Image Preview")
        self.resize(1040, 780)
        self.setMinimumSize(900, 680)
        _apply_standard_dialog_chrome(self, "imagePreviewDialog")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)
        _add_standard_dialog_header(
            layout,
            self,
            title="Image Preview",
            subtitle="Inspect stored artwork or image media at full size or zoomed detail.",
            help_topic_id="media-preview",
        )

        controls_box, controls_layout = _create_standard_section(self, "Preview Controls")
        zoom_row = QHBoxLayout()
        zoom_row.setSpacing(10)
        zoom_row.addWidget(QLabel("Zoom"), 0)
        self._zoom_slider = FocusWheelSlider(Qt.Horizontal)
        self._zoom_slider.setObjectName("imagePreviewZoomSlider")
        self._zoom_slider.setRange(10, 400)
        self._zoom_value_label = QLabel("100%")
        self._zoom_value_label.setProperty("role", "statusText")
        zoom_row.addWidget(self._zoom_slider, 1)
        zoom_row.addWidget(self._zoom_value_label, 0)
        zoom_row.addSpacing(8)
        self._export_button = QToolButton(self)
        self._export_button.setText("Export Image…")
        self._export_button.setObjectName("imagePreviewExportButton")
        self._export_button.setProperty("role", "mediaExportButton")
        self._export_button.clicked.connect(self._export_current_image)
        zoom_row.addWidget(self._export_button, 0)
        controls_layout.addLayout(zoom_row)
        layout.addWidget(controls_box)

        self._image_label = QLabel(self)
        self._image_label.setAlignment(Qt.AlignCenter)
        self._gesture_platform = platform.system().lower()

        self._scroll_area = QScrollArea(self)
        self._scroll_area.setWidget(self._image_label)
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setFrameShape(QFrame.NoFrame)
        self._image_label.setAttribute(Qt.WA_AcceptTouchEvents, True)
        if self._gesture_platform != "darwin":
            self._image_label.grabGesture(Qt.PinchGesture)
        self._image_label.installEventFilter(self)
        preview_box, preview_layout = _create_standard_section(self, "Image")
        preview_layout.addWidget(self._scroll_area, 1)
        layout.addWidget(preview_box, 1)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        button_row.addStretch(1)
        close_btn = QPushButton("Close", self)
        close_btn.clicked.connect(self.close)
        button_row.addWidget(close_btn)
        layout.addLayout(button_row)

        self._zoom_slider.valueChanged.connect(self._apply_zoom)
        self._zoom_slider.sliderPressed.connect(self._mark_user_zoomed)

    def set_preview(self, data: bytes, title: str) -> None:
        image = QImage.fromData(data)
        if image.isNull():
            raise ValueError("Could not decode image data.")
        self._current_data = bytes(data)
        self._current_mime = self.app._detect_mime(self._current_data) or "image/png"
        self._current_title = str(title or "Image Preview").strip() or "Image Preview"
        self._base_pix = QPixmap.fromImage(image)
        self.setWindowTitle(f"Image Preview — {self._current_title}")
        self._user_zoomed = False
        self._reset_view_to_fit()

    def _mark_user_zoomed(self) -> None:
        self._user_zoomed = True

    @staticmethod
    def _zoom_steps_from_event(event) -> int:
        pixel_delta = event.pixelDelta()
        angle_delta = event.angleDelta()
        if not pixel_delta.isNull():
            dominant = (
                pixel_delta.y() if abs(pixel_delta.y()) >= abs(pixel_delta.x()) else pixel_delta.x()
            )
            return int(round(dominant / 40.0))
        if not angle_delta.isNull():
            dominant = (
                angle_delta.y() if abs(angle_delta.y()) >= abs(angle_delta.x()) else angle_delta.x()
            )
            return int(round(dominant / 120.0))
        return 0

    def _fit_percent(self) -> int:
        if self._base_pix.isNull():
            return 100
        avail_w = max(1, self._scroll_area.viewport().width() - 24)
        avail_h = max(1, self._scroll_area.viewport().height() - 24)
        sx = avail_w / max(1, self._base_pix.width())
        sy = avail_h / max(1, self._base_pix.height())
        return int(max(10, min(100, min(sx, sy) * 100)))

    def _set_zoom_percent(self, pct: int, *, user_initiated: bool = False) -> None:
        clamped = max(10, min(400, int(round(pct))))
        if user_initiated:
            self._user_zoomed = True
        if self._zoom_slider.value() != clamped:
            self._zoom_slider.setValue(clamped)
        else:
            self._apply_zoom(clamped)

    def _adjust_zoom_steps(self, steps: int) -> None:
        if not steps:
            return
        self._set_zoom_percent(self._current_pct + (int(steps) * 10), user_initiated=True)

    def _adjust_zoom_factor(self, factor: float) -> None:
        factor = float(factor or 1.0)
        if factor <= 0 or abs(factor - 1.0) < 0.001:
            return
        self._set_zoom_percent(self._current_pct * factor, user_initiated=True)

    def _reset_view_to_fit(self) -> None:
        self._user_zoomed = False
        self._set_zoom_percent(self._fit_percent())

    def _handle_zoom_wheel_event(self, event) -> bool:
        modifiers = event.modifiers() if hasattr(event, "modifiers") else Qt.NoModifier
        if not modifiers & (Qt.ControlModifier | Qt.MetaModifier):
            return False
        steps = self._zoom_steps_from_event(event)
        if not steps:
            return False
        self._adjust_zoom_steps(steps)
        event.accept()
        return True

    def _handle_native_gesture_event(self, event) -> bool:
        gesture_type = event.gestureType() if hasattr(event, "gestureType") else None
        if gesture_type == Qt.ZoomNativeGesture:
            value = float(event.value() if hasattr(event, "value") else 0.0)
            if abs(value) < 0.0001:
                return False
            self._adjust_zoom_factor(1.0 + value)
            event.accept()
            return True
        if gesture_type == Qt.SmartZoomNativeGesture:
            self._reset_view_to_fit()
            event.accept()
            return True
        return False

    def _handle_pinch_gesture_event(self, event) -> bool:
        if not hasattr(event, "gesture"):
            return False
        pinch = event.gesture(Qt.PinchGesture)
        if pinch is None:
            return False
        if not pinch.changeFlags() & QPinchGesture.ScaleFactorChanged:
            return False
        last_factor = float(pinch.lastScaleFactor() or 1.0)
        scale_factor = float(pinch.scaleFactor() or 1.0)
        if abs(last_factor) < 0.0001:
            factor = scale_factor
        else:
            factor = scale_factor / last_factor
        self._adjust_zoom_factor(factor)
        event.accept()
        return True

    def _apply_zoom(self, pct: int) -> None:
        self._current_pct = max(10, min(400, int(pct)))
        self._zoom_value_label.setText(f"{self._current_pct}%")
        if self._base_pix.isNull():
            self._image_label.clear()
            return
        width = max(1, int(self._base_pix.width() * (self._current_pct / 100.0)))
        height = max(1, int(self._base_pix.height() * (self._current_pct / 100.0)))
        self._image_label.setPixmap(
            self._base_pix.scaled(width, height, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )

    def _export_current_image(self) -> None:
        if not self._current_data:
            return
        self.app._export_bytes_with_picker(
            self._current_data,
            mime=self._current_mime,
            suggested_basename=self._current_title,
            parent_widget=self,
            action_label="Export Image Preview: {filename}",
            action_type="file.export_image_preview",
            entity_type="Preview",
            entity_id=self.app._sanitize_filename(self._current_title),
            payload={"title": self._current_title, "mime_type": self._current_mime},
        )

    def eventFilter(self, source, event):
        if source is self._image_label:
            if event.type() == QEvent.MouseButtonDblClick and event.button() == Qt.LeftButton:
                self._reset_view_to_fit()
                event.accept()
                return True
            if event.type() == QEvent.Wheel and self._handle_zoom_wheel_event(event):
                return True
            if event.type() == QEvent.NativeGesture and self._handle_native_gesture_event(event):
                return True
            if (
                self._gesture_platform != "darwin"
                and event.type() == QEvent.Gesture
                and self._handle_pinch_gesture_event(event)
            ):
                return True
        return super().eventFilter(source, event)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._user_zoomed and not self._base_pix.isNull():
            QTimer.singleShot(0, lambda: self._reset_view_to_fit())

    def resizeEvent(self, event):
        if not self._user_zoomed and not self._base_pix.isNull():
            self._apply_zoom(self._fit_percent())
        super().resizeEvent(event)


class _HiDpiArtworkLabel(QLabel):
    artworkActivated = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._paint_pixmap = QPixmap()
        self._target_extent = 200

    def set_artwork_pixmap(self, pixmap: QPixmap) -> None:
        self._paint_pixmap = QPixmap(pixmap)
        self.update()

    def set_target_extent(self, extent: int) -> None:
        next_extent = max(1, int(extent))
        if self._target_extent == next_extent:
            return
        self._target_extent = next_extent
        self.updateGeometry()
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(self._target_extent, self._target_extent)

    def minimumSizeHint(self) -> QSize:
        minimum = self.minimumSize()
        return QSize(max(1, minimum.width()), max(1, minimum.height()))

    def clear(self) -> None:
        self._paint_pixmap = QPixmap()
        super().clear()
        self.update()

    def pixmap(self) -> QPixmap:
        return QPixmap(self._paint_pixmap)

    def mouseDoubleClickEvent(self, event) -> None:
        if (
            not self._paint_pixmap.isNull()
            and hasattr(event, "button")
            and event.button() == Qt.LeftButton
        ):
            self.artworkActivated.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def paintEvent(self, event) -> None:
        if self._paint_pixmap.isNull():
            super().paintEvent(event)
            return
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
            logical_size = self._paint_pixmap.deviceIndependentSize()
            contents = QRectF(self.contentsRect())
            frame_rect = contents.adjusted(2.0, 2.0, -2.0, -2.0)
            draw_rect = QRectF(
                0.0,
                0.0,
                max(1.0, float(logical_size.width())),
                max(1.0, float(logical_size.height())),
            )
            draw_rect.moveCenter(contents.center())

            background = (
                self.window().palette().window().color()
                if self.window()
                else self.palette().window().color()
            )
            luminance = (
                (0.2126 * background.redF())
                + (0.7152 * background.greenF())
                + (0.0722 * background.blueF())
            )
            light_mode = luminance >= 0.5
            shadow = QColor(0, 0, 0, 72 if light_mode else 108)
            border = QColor(self.palette().highlight().color())
            border.setAlphaF(0.42 if light_mode else 0.36)

            painter.fillRect(frame_rect.translated(2.0, 2.0), shadow)
            painter.save()
            painter.setClipRect(frame_rect)
            painter.drawPixmap(draw_rect, self._paint_pixmap, QRectF(self._paint_pixmap.rect()))
            painter.restore()
            painter.setPen(QPen(border, 1.0))
            painter.drawRect(frame_rect.adjusted(0.5, 0.5, -0.5, -0.5))
        finally:
            painter.end()


class _AudioPreviewPreloadBridge(QWidget):
    ready = Signal(object)
    track_ready = Signal(object)
    failed = Signal(object)


class _AudioPreviewPreloadCancelled(Exception):
    pass


@dataclass(slots=True)
class _AudioPreviewPreparedMedia:
    track_id: int
    source_key: str
    audio_mime: str
    source_path: str
    owns_source_path: bool
    decoded_samples: object | None
    sample_rate: int
    waveform_peaks: list
    spectrum_frames: list
    peak_frames: list
    byte_count: int
    generation: int
    created_at: float
    preview_state: dict[str, object] | None = None

    def memory_cost(self) -> int:
        decoded_cost = int(getattr(self.decoded_samples, "nbytes", 0) or 0)
        return max(0, int(self.byte_count or 0)) + decoded_cost

    def dispose(self) -> None:
        if not self.owns_source_path:
            return
        try:
            os.remove(self.source_path)
        except FileNotFoundError:
            pass
        except Exception:
            pass
        self.owns_source_path = False


@dataclass(slots=True)
class _AudioPreviewPreloadTask:
    generation: int
    track_id: int
    source_spec: dict[str, object]
    source_key: str
    db_path: str
    data_root: str | None
    cancel_event: threading.Event
    waveform_width: int
    cache_budget_bytes: int
    require_decoded: bool = False
    base_track_order: list[int] | None = None
    effective_track_order: list[int] | None = None
    build_preview_state: bool = False


@dataclass(slots=True)
class _AudioPreviewPreloadResult:
    generation: int
    track_id: int
    source_key: str
    prepared: _AudioPreviewPreparedMedia | None = None
    error: str = ""
    cancelled: bool = False


@dataclass(slots=True)
class _AudioPreviewTrackLoadTask:
    request_id: int
    track_id: int
    source_spec: dict[str, object]
    source_key: str
    autoplay: bool
    db_path: str
    data_root: str | None
    base_track_order: list[int]
    effective_track_order: list[int]
    cancel_event: threading.Event
    waveform_width: int
    cache_budget_bytes: int
    prepared_media: _AudioPreviewPreparedMedia | None = None


@dataclass(slots=True)
class _AudioPreviewTrackLoadResult:
    request_id: int
    track_id: int
    source_key: str
    state: dict[str, object] | None = None
    prepared_owned_by_result: bool = False
    error: str = ""
    cancelled: bool = False


def _audio_preview_detect_mime_from_bytes(data: bytes) -> str:
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "audio/wav"
    if len(data) >= 4 and data[:4] == b"fLaC":
        return "audio/flac"
    if len(data) >= 4 and data[:4] == b"OggS":
        return "audio/opus" if b"OpusHead" in data[:64] else "audio/ogg"
    if len(data) >= 3 and data[:3] == b"ID3":
        return "audio/mpeg"
    if len(data) >= 2 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0:
        return "audio/mpeg"
    return ""


def _audio_preview_suffix_for_mime(mime: str, fallback: str = ".bin") -> str:
    return {
        "audio/mpeg": ".mp3",
        "audio/wav": ".wav",
        "audio/ogg": ".ogg",
        "audio/opus": ".opus",
        "audio/flac": ".flac",
        "audio/aiff": ".aiff",
        "audio/x-aiff": ".aiff",
    }.get(str(mime or "").strip().lower(), fallback)


def _audio_preview_fetch_source_for_preload(
    task: _AudioPreviewPreloadTask,
) -> tuple[str, bool, str, int]:
    if task.cancel_event.is_set():
        raise _AudioPreviewPreloadCancelled()
    if not task.db_path:
        raise FileNotFoundError("No active profile database for audio preload.")

    conn = SQLiteConnectionFactory().open(task.db_path)
    try:
        kind = str(task.source_spec.get("kind") or "").strip().lower()
        if kind == "custom":
            field_id = int(task.source_spec.get("field_id") or 0)
            if field_id <= 0:
                raise FileNotFoundError("No custom audio field selected.")
            row = conn.execute(
                """
                SELECT
                    cfv.blob_value,
                    cfv.managed_file_path,
                    cfv.storage_mode,
                    cfv.filename,
                    cfv.mime_type,
                    cfv.size_bytes
                FROM CustomFieldValues cfv
                JOIN CustomFieldDefs cfd ON cfd.id = cfv.field_def_id
                WHERE cfv.track_id=? AND cfv.field_def_id=? AND cfd.field_type='blob_audio'
                """,
                (int(task.track_id), field_id),
            ).fetchone()
            if not row:
                raise FileNotFoundError("No custom audio file stored for this track.")
            blob_value, managed_file_path, storage_mode, filename, mime_type, size_bytes = row
            effective_mode = infer_storage_mode(
                explicit_mode=storage_mode,
                stored_path=managed_file_path,
                blob_value=blob_value,
            )
            if effective_mode == STORAGE_MODE_MANAGED_FILE:
                store = ManagedFileStorage(
                    data_root=task.data_root,
                    relative_root="custom_field_media",
                )
                resolved = store.resolve(str(managed_file_path or ""))
                if resolved is None or not resolved.exists():
                    raise FileNotFoundError(
                        str(managed_file_path or filename or "custom audio file")
                    )
                mime = str(mime_type or mimetypes.guess_type(str(resolved))[0] or "")
                return str(resolved), False, mime, int(size_bytes or resolved.stat().st_size)
            if blob_value is None:
                raise FileNotFoundError("No custom audio blob stored for this track.")
            data = bytes_from_blob(blob_value)
            mime = str(mime_type or _audio_preview_detect_mime_from_bytes(data) or "audio/wav")
            suffix = Path(str(filename or "")).suffix or _audio_preview_suffix_for_mime(mime)
            return _audio_preview_write_preload_temp_file(data, suffix), True, mime, len(data)

        media_key = str(task.source_spec.get("media_key") or "audio_file").strip() or "audio_file"
        service = TrackService(conn, task.data_root)
        handle = service.resolve_media_source(int(task.track_id), media_key)
        if handle.source_path is not None and handle.source_path.exists():
            mime = str(handle.mime_type or mimetypes.guess_type(str(handle.source_path))[0] or "")
            return str(handle.source_path), False, mime, int(handle.size_bytes or 0)
        data = bytes(handle.source_bytes or b"")
        if not data:
            raise FileNotFoundError(f"{media_key} for track {task.track_id}")
        mime = str(handle.mime_type or _audio_preview_detect_mime_from_bytes(data) or "audio/wav")
        suffix = handle.suffix or _audio_preview_suffix_for_mime(mime)
        return _audio_preview_write_preload_temp_file(data, suffix), True, mime, len(data)
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _audio_preview_write_preload_temp_file(data: bytes, suffix: str) -> str:
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix or ".bin") as handle:
        handle.write(bytes(data or b""))
        return handle.name


def _audio_preview_artwork_payload_for_snapshot(
    track_service: TrackService,
    track_id: int,
    snapshot: TrackSnapshot | None,
) -> ArtworkPayload | None:
    if snapshot is None:
        return None
    has_album_art = bool(
        snapshot.album_art_path
        or snapshot.album_art_blob_b64
        or snapshot.album_art_filename
        or int(snapshot.album_art_size_bytes or 0) > 0
    )
    if not has_album_art:
        return None
    fallback_mime_type = str(snapshot.album_art_mime_type or "").strip() or "image/jpeg"
    try:
        data, mime_type = track_service.fetch_media_bytes(int(track_id), "album_art")
    except Exception:
        return None
    return ArtworkPayload(data=data, mime_type=mime_type or fallback_mime_type)


def _audio_preview_track_queue_items_for_service(
    track_service: TrackService,
    track_order: list[int],
) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    seen: set[int] = set()
    for position, track_id in enumerate(track_order, start=1):
        try:
            normalized_id = int(track_id)
        except TypeError, ValueError:
            continue
        if normalized_id in seen:
            continue
        seen.add(normalized_id)
        title = ""
        album = ""
        try:
            snapshot = track_service.fetch_track_snapshot(
                normalized_id,
                include_media_blobs=False,
            )
        except Exception:
            snapshot = None
        if snapshot is not None:
            title = str(snapshot.track_title or "").strip()
            album = str(snapshot.album_title or "").strip()
        if not title:
            title = f"Track {normalized_id}"
        items.append(
            {
                "track_id": normalized_id,
                "title": title,
                "label": title,
                "album": album,
                "position": position,
            }
        )
    return items


def _audio_preview_state_for_preload_task(
    task: _AudioPreviewPreloadTask,
    prepared: _AudioPreviewPreparedMedia,
) -> dict[str, object] | None:
    if not task.build_preview_state:
        return None
    if task.cancel_event.is_set():
        raise _AudioPreviewPreloadCancelled()
    if not task.db_path:
        return None

    def _coerce_track_ids(values: list[int] | None) -> list[int]:
        coerced: list[int] = []
        seen: set[int] = set()
        for track_id in list(values or []):
            try:
                normalized = int(track_id)
            except TypeError, ValueError:
                continue
            if normalized in seen:
                continue
            seen.add(normalized)
            coerced.append(normalized)
        return coerced

    base_track_order = _coerce_track_ids(task.base_track_order)
    effective_track_order = _coerce_track_ids(task.effective_track_order)
    if int(task.track_id) not in base_track_order:
        base_track_order = [int(task.track_id), *base_track_order]
    if not effective_track_order:
        effective_track_order = list(base_track_order)

    conn = SQLiteConnectionFactory().open(task.db_path)
    try:
        track_service = TrackService(conn, task.data_root)
        snapshot = track_service.fetch_track_snapshot(
            int(task.track_id),
            include_media_blobs=False,
        )
        title = str(
            (snapshot.track_title if snapshot is not None else None) or f"Track {task.track_id}"
        ).strip()
        artist = str((snapshot.artist_name if snapshot is not None else None) or "").strip()
        album = str((snapshot.album_title if snapshot is not None else None) or "").strip()
        artwork = _audio_preview_artwork_payload_for_snapshot(
            track_service,
            int(task.track_id),
            snapshot,
        )
        base_queue = _audio_preview_track_queue_items_for_service(
            track_service,
            list(base_track_order),
        )
        effective_queue = _audio_preview_track_queue_items_for_service(
            track_service,
            list(effective_track_order),
        )
    finally:
        try:
            conn.close()
        except Exception:
            pass

    if task.cancel_event.is_set():
        raise _AudioPreviewPreloadCancelled()
    return {
        "track_id": int(task.track_id),
        "track_order": list(base_track_order),
        "track_queue": base_queue,
        "effective_track_order": list(effective_track_order),
        "effective_track_queue": effective_queue,
        "title": title or f"Track {task.track_id}",
        "artist": artist,
        "album": album,
        "audio_bytes": b"",
        "audio_mime": str(prepared.audio_mime or "audio/wav"),
        "prepared_media": prepared,
        "artwork_payload": artwork,
        "window_title": f"Audio Player — {title or f'Track {task.track_id}'}",
        "export_actions": [],
    }


def _build_audio_preview_preload(task: _AudioPreviewPreloadTask) -> _AudioPreviewPreloadResult:
    source_path = ""
    owns_source_path = False
    prepared: _AudioPreviewPreparedMedia | None = None
    try:
        source_path, owns_source_path, mime, byte_count = _audio_preview_fetch_source_for_preload(
            task
        )
        if task.cancel_event.is_set():
            raise _AudioPreviewPreloadCancelled()

        if task.cancel_event.is_set():
            raise _AudioPreviewPreloadCancelled()

        waveform_width = max(480, int(task.waveform_width or 480))
        waveform_peaks = load_wav_peaks(source_path, waveform_width)
        if task.cancel_event.is_set():
            raise _AudioPreviewPreloadCancelled()
        spectrum_frames = load_audio_spectrum_frames(source_path)
        if task.cancel_event.is_set():
            raise _AudioPreviewPreloadCancelled()
        peak_frames = load_audio_peak_meter_frames(source_path)

        prepared = _AudioPreviewPreparedMedia(
            track_id=int(task.track_id),
            source_key=task.source_key,
            audio_mime=str(mime or "audio/wav"),
            source_path=source_path,
            owns_source_path=owns_source_path,
            decoded_samples=None,
            sample_rate=0,
            waveform_peaks=list(waveform_peaks or []),
            spectrum_frames=list(spectrum_frames or []),
            peak_frames=list(peak_frames or []),
            byte_count=int(byte_count or 0),
            generation=int(task.generation),
            created_at=time.monotonic(),
        )
        try:
            prepared.preview_state = _audio_preview_state_for_preload_task(task, prepared)
        except _AudioPreviewPreloadCancelled:
            raise
        except Exception:
            prepared.preview_state = None
        return _AudioPreviewPreloadResult(
            generation=int(task.generation),
            track_id=int(task.track_id),
            source_key=task.source_key,
            prepared=prepared,
        )
    except _AudioPreviewPreloadCancelled:
        if prepared is not None:
            prepared.dispose()
        elif owns_source_path and source_path:
            try:
                os.remove(source_path)
            except Exception:
                pass
        return _AudioPreviewPreloadResult(
            generation=int(task.generation),
            track_id=int(task.track_id),
            source_key=task.source_key,
            cancelled=True,
        )
    except Exception as exc:
        if prepared is not None:
            prepared.dispose()
        elif owns_source_path and source_path:
            try:
                os.remove(source_path)
            except Exception:
                pass
        return _AudioPreviewPreloadResult(
            generation=int(task.generation),
            track_id=int(task.track_id),
            source_key=task.source_key,
            error=str(exc),
        )


def _build_audio_preview_track_load(
    task: _AudioPreviewTrackLoadTask,
) -> _AudioPreviewTrackLoadResult:
    prepared = (
        task.prepared_media if isinstance(task.prepared_media, _AudioPreviewPreparedMedia) else None
    )
    prepared_owned_by_result = False
    try:
        if task.cancel_event.is_set():
            raise _AudioPreviewPreloadCancelled()
        if not task.db_path:
            raise FileNotFoundError("No active profile database for audio preview.")

        conn = SQLiteConnectionFactory().open(task.db_path)
        try:
            track_service = TrackService(conn, task.data_root)
            snapshot = track_service.fetch_track_snapshot(
                int(task.track_id),
                include_media_blobs=False,
            )
            title = str(
                (snapshot.track_title if snapshot is not None else None) or f"Track {task.track_id}"
            ).strip()
            artist = str((snapshot.artist_name if snapshot is not None else None) or "").strip()
            album = str((snapshot.album_title if snapshot is not None else None) or "").strip()
            artwork = _audio_preview_artwork_payload_for_snapshot(
                track_service,
                int(task.track_id),
                snapshot,
            )
            base_queue = _audio_preview_track_queue_items_for_service(
                track_service,
                list(task.base_track_order),
            )
            effective_queue = _audio_preview_track_queue_items_for_service(
                track_service,
                list(task.effective_track_order),
            )
        finally:
            try:
                conn.close()
            except Exception:
                pass

        if task.cancel_event.is_set():
            raise _AudioPreviewPreloadCancelled()

        if prepared is None:
            preload_result = _build_audio_preview_preload(
                _AudioPreviewPreloadTask(
                    generation=int(task.request_id),
                    track_id=int(task.track_id),
                    source_spec=dict(task.source_spec),
                    source_key=task.source_key,
                    db_path=task.db_path,
                    data_root=task.data_root,
                    cancel_event=task.cancel_event,
                    waveform_width=max(480, int(task.waveform_width or 480)),
                    cache_budget_bytes=int(task.cache_budget_bytes),
                    require_decoded=True,
                )
            )
            if preload_result.cancelled:
                raise _AudioPreviewPreloadCancelled()
            if preload_result.error:
                raise RuntimeError(preload_result.error)
            prepared = preload_result.prepared
            prepared_owned_by_result = prepared is not None

        if prepared is None:
            raise FileNotFoundError(f"No playable audio for track {task.track_id}.")
        if prepared.decoded_samples is None or int(prepared.sample_rate or 0) <= 0:
            if task.cancel_event.is_set():
                raise _AudioPreviewPreloadCancelled()
            samples, decoded_sample_rate = _decode_audio_file(prepared.source_path)
            prepared.decoded_samples = samples
            prepared.sample_rate = int(decoded_sample_rate or 0)
        if task.cancel_event.is_set():
            raise _AudioPreviewPreloadCancelled()

        state = {
            "track_id": int(task.track_id),
            "track_order": list(task.base_track_order),
            "track_queue": base_queue,
            "effective_track_order": list(task.effective_track_order),
            "effective_track_queue": effective_queue,
            "title": title or f"Track {task.track_id}",
            "artist": artist,
            "album": album,
            "audio_bytes": b"",
            "audio_mime": str(prepared.audio_mime or "audio/wav"),
            "prepared_media": prepared,
            "artwork_payload": artwork,
            "window_title": f"Audio Player — {title or f'Track {task.track_id}'}",
            "export_actions": [],
            "_autoplay": bool(task.autoplay),
        }
        return _AudioPreviewTrackLoadResult(
            request_id=int(task.request_id),
            track_id=int(task.track_id),
            source_key=task.source_key,
            state=state,
            prepared_owned_by_result=prepared_owned_by_result,
        )
    except _AudioPreviewPreloadCancelled:
        if prepared_owned_by_result and prepared is not None:
            prepared.dispose()
        return _AudioPreviewTrackLoadResult(
            request_id=int(task.request_id),
            track_id=int(task.track_id),
            source_key=task.source_key,
            cancelled=True,
        )
    except Exception as exc:
        if prepared_owned_by_result and prepared is not None:
            prepared.dispose()
        return _AudioPreviewTrackLoadResult(
            request_id=int(task.request_id),
            track_id=int(task.track_id),
            source_key=task.source_key,
            error=str(exc),
        )


class _AudioPreviewDialog(QDialog):
    SCRUB_STEP_MS = 1000
    JUMP_STEP_MS = 10000
    VISUALIZATION_TIMER_MS = 16
    STOP_BUTTON_FONT_SCALE = 2.5
    MEDIA_ICON_SIZE = QSize(18, 18)
    ARTWORK_SIZE = 200
    WAVEFORM_HEIGHT = 172
    MEDIA_ROW_HEIGHT = ARTWORK_SIZE
    STATUS_SLIDER_MAX_WIDTH = 420
    DEFAULT_WINDOW_WIDTH = 960
    DEFAULT_WINDOW_HEIGHT = 581
    CONTROL_GROUP_MARGIN = 8
    PEAK_LABEL_OFFSET = 20
    CONTROL_ROW_TOP_OFFSET = 0
    CONTROL_BAND_HEIGHT = 88
    PRELOAD_CACHE_BUDGET_BYTES = 192 * 1024 * 1024
    PRELOAD_WORKERS = 2
    LOOP_MODE_OFF = "off"
    LOOP_MODE_PLAYLIST = "playlist"
    LOOP_MODE_TRACK = "track"
    _MEDIA_ICON_FILES = {
        "media-player": "music-player-fill.svg",
        "previous": "skip-start-fill.svg",
        "rewind": "rewind-fill.svg",
        "play": "play-fill.svg",
        "pause": "pause-fill.svg",
        "stop": "stop-fill.svg",
        "forward": "fast-forward-fill.svg",
        "next": "skip-end-fill.svg",
        "shuffle": "shuffle.svg",
        "auto-advance": "music-note-list.svg",
        "album-scope": "collection-play-fill.svg",
        "repeat": "repeat.svg",
        "repeat-one": "repeat-1.svg",
        "volume-up": "volume-up-fill.svg",
        "volume-mute": "volume-mute-fill.svg",
        "equalizer": "sliders2-vertical.svg",
        "bookmark": "bookmark-plus-fill.svg",
        "export": "box-arrow-down.svg",
    }

    def __init__(self, app, parent=None):
        super().__init__(parent, Qt.Window)
        self.app = app
        self._tmp_path = None
        self._source_tmp_path = None
        self._tmp_path_owned = False
        self._source_spec = None
        self._current_track_id = None
        self._track_order = []
        self._track_queue = []
        self._current_audio_bytes = b""
        self._current_audio_mime = "audio/wav"
        self._current_title = ""
        self._current_artist = ""
        self._current_album = ""
        self._current_artwork_data = b""
        self._current_artwork_mime = "image/png"
        self._artwork_pixmap = QPixmap()
        self._handling_end_of_media = False
        self._shuffle_enabled = False
        self._base_track_order = []
        self._base_track_queue = []
        self._shuffled_track_order = []
        self._album_scope_title: str | None = None
        self._album_scope_menu: QMenu | None = None
        self._visualization_gain = 1.0
        self._loop_mode = self.LOOP_MODE_OFF
        self._media_icon_cache: dict[tuple[str, bool, str], QIcon] = {}
        self._media_stage_syncing = False
        self._equalizer_settings = load_equalizer_settings(getattr(app, "settings", None))
        self._equalizer_dialog: EqualizerDialog | None = None
        self._current_bookmarks: list[AudioBookmark] = []
        self._bookmark_menu: QMenu | None = None
        self._audio_preload_generation = 0
        self._audio_preload_cache: dict[tuple[int, str], _AudioPreviewPreparedMedia] = {}
        self._audio_preload_jobs: dict[tuple[int, str], tuple[Future, threading.Event, int]] = {}
        self._audio_preload_executor = None
        self._audio_load_request_id = 0
        self._audio_load_jobs: dict[int, tuple[Future, threading.Event]] = {}
        self._audio_load_waiting_for_preload: dict[str, object] | None = None
        self._audio_load_executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="audio-preview-load",
        )
        self._audio_preload_bridge = _AudioPreviewPreloadBridge(self)
        self._audio_preload_bridge.ready.connect(self._on_audio_preload_result)
        self._audio_preload_bridge.track_ready.connect(self._on_audio_track_load_result)

        self.setObjectName("audioPreviewDialog")
        self.setWindowFlags(
            Qt.Window
            | Qt.WindowTitleHint
            | Qt.WindowSystemMenuHint
            | Qt.WindowCloseButtonHint
            | Qt.WindowMinMaxButtonsHint
        )
        self.setModal(False)
        self.setWindowModality(Qt.NonModal)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.setAttribute(Qt.WA_NativeWindow, True)
        self.setAttribute(Qt.WA_QuitOnClose, False)
        self.setMinimumSize(self.DEFAULT_WINDOW_WIDTH, self.DEFAULT_WINDOW_HEIGHT)
        self.resize(self.DEFAULT_WINDOW_WIDTH, self.DEFAULT_WINDOW_HEIGHT)
        _apply_standard_dialog_chrome(self, "audioPreviewDialog")
        self._apply_window_icon()

        if platform.system().lower() == "darwin":
            os.environ.setdefault(
                "PATH", "/opt/homebrew/bin:/usr/local/bin:" + os.environ.get("PATH", "")
            )
        elif platform.system().lower() == "windows":
            extra = [
                r"C:\Program Files\ffmpeg\bin",
                r"C:\ffmpeg\bin",
                r"C:\ProgramData\chocolatey\bin",
                os.path.expandvars(r"%USERPROFILE%\scoop\shims"),
            ]
            os.environ["PATH"] = ";".join([*extra, os.environ.get("PATH", "")])

        self._player = LiveEqualizerPlayer(self)
        self._audio_out = QAudioOutput(self)
        self._player.setAudioOutput(self._audio_out)
        self._player.set_equalizer_settings(self._equalizer_settings)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)
        root.setSizeConstraint(QLayout.SetMinimumSize)

        metadata_group, metadata_layout = _create_standard_section(self, "Now Playing")
        metadata_group.setObjectName("audioPreviewMetadataGroup")
        metadata_group.setProperty("role", "panel")
        metadata_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        header_row = QHBoxLayout()
        header_row.setSpacing(10)
        header_text = QVBoxLayout()
        header_text.setSpacing(4)
        self.title_label = QLabel("Audio Player", metadata_group)
        self.title_label.setObjectName("audioPreviewTitleLabel")
        self.title_label.setProperty("role", "dialogTitle")
        self.artist_label = QLabel("", metadata_group)
        self.artist_label.setObjectName("audioPreviewArtistLabel")
        self.artist_label.setProperty("role", "secondary")
        self.artist_label.setWordWrap(True)
        self.album_label = QLabel("", metadata_group)
        self.album_label.setObjectName("audioPreviewAlbumLabel")
        self.album_label.setProperty("role", "meta")
        self.album_label.setWordWrap(True)
        self.album_label.hide()
        header_text.addWidget(self.title_label)
        header_text.addWidget(self.artist_label)
        header_text.addWidget(self.album_label)
        header_row.addLayout(header_text, 1)
        header_row.addWidget(
            _create_round_help_button(metadata_group, "media-preview"),
            0,
            Qt.AlignTop,
        )
        metadata_layout.addLayout(header_row)
        root.addWidget(metadata_group)

        self.media_group = QGroupBox("", self)
        self.media_group.setObjectName("audioPreviewMediaGroup")
        self.media_group.setProperty("role", "panel")
        self.media_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        media_layout = QVBoxLayout(self.media_group)
        media_layout.setContentsMargins(18, 12, 18, 14)
        media_layout.setSpacing(0)

        content_row = QHBoxLayout()
        content_row.setSpacing(20)
        self.waveform_panel = QFrame(self.media_group)
        self.waveform_panel.setObjectName("audioPreviewWaveformPanel")
        self.waveform_panel.setProperty("role", "mediaStage")
        self.waveform_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.waveform_panel.setMinimumHeight(self.MEDIA_ROW_HEIGHT)
        waveform_layout = QVBoxLayout(self.waveform_panel)
        waveform_layout.setContentsMargins(0, 0, 0, 0)
        waveform_layout.setSpacing(6)
        waveform_layout.addStretch(1)
        self.wave = WaveformWidget(self.waveform_panel)
        self.wave.setObjectName("audioPreviewWaveform")
        self.wave.setProperty("role", "mediaWaveform")
        self.wave.setMinimumHeight(self.WAVEFORM_HEIGHT)
        self.wave.setMaximumHeight(self.WAVEFORM_HEIGHT)
        self.wave.set_preferred_height(self.WAVEFORM_HEIGHT)
        self.wave.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.wave_status_label = QLabel("Waveform unavailable", self.waveform_panel)
        self.wave_status_label.setObjectName("audioPreviewWaveformStatusLabel")
        self.wave_status_label.setProperty("role", "secondary")
        self.wave_status_label.setAlignment(Qt.AlignCenter)
        self.wave_status_label.hide()
        waveform_layout.addWidget(self.wave, 0, Qt.AlignVCenter)
        waveform_layout.addWidget(self.wave_status_label, 0, Qt.AlignCenter)
        waveform_layout.addStretch(1)
        content_row.addWidget(self.waveform_panel, 1)

        self.artwork_container = QFrame(self.media_group)
        self.artwork_container.setObjectName("audioPreviewArtworkContainer")
        self.artwork_container.setProperty("role", "mediaArtworkStage")
        self.artwork_container.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self.artwork_container.setMinimumHeight(self.MEDIA_ROW_HEIGHT)
        self.artwork_container.setMinimumWidth(self.ARTWORK_SIZE)
        self.artwork_container.setMaximumWidth(self.ARTWORK_SIZE)
        artwork_layout = QVBoxLayout(self.artwork_container)
        artwork_layout.setContentsMargins(0, 0, 0, 0)
        artwork_layout.setSpacing(0)
        self.artwork_label = _HiDpiArtworkLabel(self.artwork_container)
        self.artwork_label.setObjectName("audioPreviewArtworkLabel")
        self.artwork_label.setProperty("role", "mediaArtwork")
        self.artwork_label.setAlignment(Qt.AlignCenter)
        self.artwork_label.setCursor(Qt.PointingHandCursor)
        self.artwork_label.setContextMenuPolicy(Qt.CustomContextMenu)
        self.artwork_label.setToolTip("Open album art preview")
        self.artwork_label.setMinimumSize(self.ARTWORK_SIZE, self.ARTWORK_SIZE)
        self.artwork_label.setMaximumSize(self.ARTWORK_SIZE, self.ARTWORK_SIZE)
        self.artwork_label.set_target_extent(self.ARTWORK_SIZE)
        self.artwork_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.artwork_label.artworkActivated.connect(self._open_artwork_preview)
        self.artwork_label.customContextMenuRequested.connect(self._show_artwork_context_menu)
        artwork_layout.addWidget(self.artwork_label, 0, Qt.AlignCenter)
        self.artwork_container.setContextMenuPolicy(Qt.CustomContextMenu)
        self.artwork_container.customContextMenuRequested.connect(self._show_artwork_context_menu)
        self.artwork_container.hide()
        content_row.addWidget(self.artwork_container, 0)
        media_layout.addLayout(content_row)
        root.addWidget(self.media_group, 1)

        self.playback_status_panel = QFrame(self)
        self.playback_status_panel.setObjectName("audioPreviewPlaybackStatusPanel")
        self.playback_status_panel.setProperty("role", "compactControlGroup")
        self.playback_status_panel.setAttribute(Qt.WA_StyledBackground, True)
        self.playback_status_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        playback_status_layout = QHBoxLayout(self.playback_status_panel)
        playback_status_layout.setContentsMargins(12, 8, 12, 8)
        playback_status_layout.setSpacing(10)
        self._label_time = QLabel("0:00 / 0:00", self.playback_status_panel)
        self._label_time.setObjectName("audioPreviewTimeLabel")
        self._label_time.setProperty("role", "statusText")
        playback_status_layout.addWidget(self._label_time, 0, Qt.AlignLeft | Qt.AlignVCenter)
        self._slider = FocusWheelSlider(Qt.Horizontal)
        self._slider.setObjectName("audioPreviewTimelineSlider")
        self._slider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._slider.setMinimumWidth(220)
        self._slider.setMaximumWidth(self.STATUS_SLIDER_MAX_WIDTH)
        playback_status_layout.addWidget(self._slider, 0, Qt.AlignLeft | Qt.AlignVCenter)
        self.scope = SpectrumGraphWidget(self.playback_status_panel)
        self.scope.setObjectName("audioPreviewSpectrumGraph")
        self.scope.setProperty("role", "mediaSpectrumGraph")
        scope_height = max(self._label_time.sizeHint().height(), self._slider.sizeHint().height())
        self.scope.setFixedHeight(max(1, int(scope_height)))
        self.scope.setMinimumWidth(160)
        self.scope.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        scope_slot = QHBoxLayout()
        scope_slot.setContentsMargins(0, 0, 0, 0)
        scope_slot.setSpacing(0)
        scope_slot.addStretch(1)
        scope_slot.addWidget(self.scope, 4, Qt.AlignVCenter)
        scope_slot.addStretch(1)
        playback_status_layout.addLayout(scope_slot, 1)
        root.addWidget(self.playback_status_panel)

        controls_row = QHBoxLayout()
        controls_row.setSpacing(10)

        playback_group, playback_layout = _create_standard_section(self, "Playback")
        self.playback_group = playback_group
        playback_group.setObjectName("audioPreviewPlaybackGroup")
        playback_group.setProperty("role", "panel")
        playback_group.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Maximum)
        playback_layout.setContentsMargins(
            self.CONTROL_GROUP_MARGIN,
            self.CONTROL_GROUP_MARGIN,
            self.CONTROL_GROUP_MARGIN,
            self.CONTROL_GROUP_MARGIN,
        )
        playback_layout.setSpacing(0)

        transport_buttons = QHBoxLayout()
        transport_buttons.setSpacing(6)
        self.previous_button = self._create_transport_button(
            "previous",
            "|◀",
            "Previous Track",
            "audioPreviewPreviousButton",
            self._go_to_previous_track,
        )
        self.rewind_button = self._create_transport_button(
            "rewind",
            "◀◀",
            "Jump Back 10 Seconds",
            "audioPreviewRewindButton",
            lambda: self._jump_by_ms(-self.JUMP_STEP_MS),
        )
        self.play_button = self._create_transport_button(
            "play",
            "▶",
            "Play",
            "audioPreviewPlayButton",
            self._player.play,
        )
        self.pause_button = self._create_transport_button(
            "pause",
            "▌▌",
            "Pause",
            "audioPreviewPauseButton",
            self._player.pause,
        )
        self.stop_button = self._create_transport_button(
            "stop",
            "■",
            "Stop",
            "audioPreviewStopButton",
            self._stop_playback,
        )
        self._apply_stop_button_font()
        self.forward_button = self._create_transport_button(
            "forward",
            "▶▶",
            "Jump Forward 10 Seconds",
            "audioPreviewForwardButton",
            lambda: self._jump_by_ms(self.JUMP_STEP_MS),
        )
        self.next_button = self._create_transport_button(
            "next",
            "▶|",
            "Next Track",
            "audioPreviewNextButton",
            self._go_to_next_track,
        )
        self.loop_button = self._create_loop_button()
        for button in (
            self.previous_button,
            self.rewind_button,
            self.play_button,
            self.pause_button,
            self.stop_button,
            self.forward_button,
            self.next_button,
            self.loop_button,
        ):
            transport_buttons.addWidget(button)
        transport_buttons.addStretch(1)

        playback_footer = QHBoxLayout()
        playback_footer.setSpacing(6)
        self.shuffle_button = self._create_shuffle_button()
        playback_footer.addWidget(self.shuffle_button, 0, Qt.AlignLeft | Qt.AlignBottom)
        self.album_scope_button = self._create_album_scope_button()
        playback_footer.addWidget(self.album_scope_button, 0, Qt.AlignLeft | Qt.AlignBottom)
        self.auto_advance_button = self._create_auto_advance_button()
        self.auto_advance_check = self.auto_advance_button
        playback_footer.addWidget(
            self.auto_advance_button,
            0,
            Qt.AlignLeft | Qt.AlignBottom,
        )
        self.equalizer_button = self._create_equalizer_button()
        playback_footer.addWidget(
            self.equalizer_button,
            0,
            Qt.AlignLeft | Qt.AlignBottom,
        )
        self.bookmark_button = self._create_bookmark_button()
        playback_footer.addWidget(
            self.bookmark_button,
            0,
            Qt.AlignLeft | Qt.AlignBottom,
        )
        playback_footer.addStretch(1)
        self.export_button = QToolButton(playback_group)
        self.export_button.setObjectName("audioPreviewExportButton")
        self.export_button.setProperty("role", "mediaExportButton")
        self.export_button.setPopupMode(QToolButton.InstantPopup)
        self.export_button.setAutoRaise(False)
        self.export_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.export_button.setFixedSize(42, 34)
        self._set_icon_button_content(self.export_button, "export", "Export")
        self.export_button.setToolTip("Export")
        self.export_button.setAccessibleName("Export")
        self.export_menu = QMenu(self.export_button)
        self.export_button.setMenu(self.export_menu)
        self._set_media_button_enabled(self.export_button, False)
        playback_footer.addWidget(self.export_button, 0, Qt.AlignRight | Qt.AlignBottom)
        self.playback_control_band = QWidget(playback_group)
        self.playback_control_band.setObjectName("audioPreviewPlaybackControlBand")
        self.playback_control_band.setFixedHeight(self.CONTROL_BAND_HEIGHT)
        self.playback_control_band.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        playback_band_layout = QVBoxLayout(self.playback_control_band)
        playback_band_layout.setContentsMargins(0, 0, 0, 0)
        playback_band_layout.setSpacing(0)
        playback_band_layout.addLayout(transport_buttons)
        playback_band_layout.addStretch(1)
        playback_band_layout.addLayout(playback_footer)
        playback_layout.addSpacing(self.CONTROL_ROW_TOP_OFFSET)
        playback_layout.addWidget(self.playback_control_band)
        controls_row.addWidget(playback_group, 0)

        volume_group, volume_layout = _create_standard_section(self, "Volume")
        volume_group.setObjectName("audioPreviewVolumeGroup")
        volume_group.setProperty("role", "panel")
        volume_group.setMinimumWidth(150)
        volume_group.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        volume_layout.setContentsMargins(
            self.CONTROL_GROUP_MARGIN,
            self.CONTROL_GROUP_MARGIN,
            self.CONTROL_GROUP_MARGIN,
            self.CONTROL_GROUP_MARGIN,
        )
        volume_layout.setSpacing(6)
        volume_body = QGridLayout()
        volume_body.setContentsMargins(0, 0, 0, 0)
        volume_body.setHorizontalSpacing(8)
        volume_body.setVerticalSpacing(0)
        self.peak_meter = StereoPeakMeterWidget(volume_group)
        self.peak_meter.setObjectName("audioPreviewStereoPeakMeter")
        self.peak_meter.setProperty("role", "mediaPeakMeter")
        self.peak_meter.setBarHeight(self.CONTROL_BAND_HEIGHT)
        self.volume_slider = FocusWheelSlider(Qt.Vertical)
        self.volume_slider.setObjectName("audioPreviewVolumeSlider")
        self.volume_slider.setProperty("role", "mediaVolumeSlider")
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setDoubleClickResetValue(100)
        self.volume_slider.setSingleStep(5)
        self.volume_slider.setPageStep(10)
        self.volume_slider.setToolTip("Volume")
        self.volume_slider.setMinimumHeight(self.CONTROL_BAND_HEIGHT)
        self.volume_slider.setMaximumHeight(self.CONTROL_BAND_HEIGHT)
        self.volume_label = QLabel("100%", volume_group)
        self.volume_label.setObjectName("audioPreviewVolumeLabel")
        self.volume_label.setProperty("role", "statusText")
        self.volume_label.setAlignment(Qt.AlignRight | Qt.AlignTop)
        self.volume_label.setMinimumWidth(44)
        self.mute_button = QToolButton(volume_group)
        self.mute_button.setObjectName("audioPreviewMuteButton")
        self.mute_button.setProperty("role", "mediaMuteButton")
        self.mute_button.setCheckable(True)
        self.mute_button.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.mute_button.setAutoRaise(False)
        self.mute_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.mute_button.setFixedSize(24, 24)
        self.mute_button.setIconSize(self.MEDIA_ICON_SIZE)
        self.mute_button.setStyleSheet("""
            QToolButton#audioPreviewMuteButton {
                min-width: 24px;
                max-width: 24px;
                min-height: 24px;
                max-height: 24px;
                border-radius: 6px;
                padding: 0px;
            }
            """)
        volume_body.setColumnStretch(0, 1)
        volume_body.setColumnStretch(4, 1)
        volume_body.setRowMinimumHeight(0, self.CONTROL_BAND_HEIGHT)
        volume_body.setRowStretch(0, 0)
        volume_body.addWidget(self.peak_meter, 0, 1, Qt.AlignHCenter | Qt.AlignTop)
        volume_body.addWidget(self.volume_slider, 0, 2, Qt.AlignHCenter | Qt.AlignTop)
        volume_body.addWidget(self.volume_label, 0, 3, Qt.AlignRight | Qt.AlignTop)
        volume_body.addWidget(self.mute_button, 0, 3, Qt.AlignRight | Qt.AlignBottom)
        volume_layout.addLayout(volume_body)
        volume_layout.addStretch(1)
        controls_row.addWidget(volume_group, 0)

        self.play_next_group, play_next_layout = _create_standard_section(self, "Play Next")
        play_next_group = self.play_next_group
        play_next_group.setObjectName("audioPreviewPlayNextGroup")
        play_next_group.setProperty("role", "panel")
        play_next_group.setMinimumWidth(200)
        play_next_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        play_next_layout.setContentsMargins(
            self.CONTROL_GROUP_MARGIN,
            self.CONTROL_GROUP_MARGIN,
            self.CONTROL_GROUP_MARGIN,
            self.CONTROL_GROUP_MARGIN,
        )
        play_next_layout.setSpacing(0)
        self.play_next_list = QListWidget(play_next_group)
        self.play_next_list.setObjectName("audioPreviewPlayNextList")
        self.play_next_list.setProperty("role", "hint")
        self.play_next_list.setAlternatingRowColors(False)
        self.play_next_list.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.play_next_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.play_next_list.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.play_next_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.play_next_list.setUniformItemSizes(True)
        self.play_next_list.setTextElideMode(Qt.ElideRight)
        self.play_next_list.setMinimumHeight(self.CONTROL_BAND_HEIGHT)
        self.play_next_list.setMaximumHeight(self.CONTROL_BAND_HEIGHT)
        self.play_next_list.itemClicked.connect(self._play_next_item)
        self.play_next_list.itemActivated.connect(self._play_next_item)
        play_next_layout.addSpacing(self.CONTROL_ROW_TOP_OFFSET)
        play_next_layout.addWidget(self.play_next_list)
        controls_row.addWidget(play_next_group, 1)
        controls_row.setStretch(0, 0)
        controls_row.setStretch(1, 0)
        controls_row.setStretch(2, 1)
        control_group_height = max(
            playback_group.sizeHint().height(),
            volume_group.sizeHint().height(),
            play_next_group.sizeHint().height(),
        )
        for group in (playback_group, volume_group, play_next_group):
            group.setMinimumHeight(control_group_height)
        self._apply_play_next_font()
        root.addLayout(controls_row, 0)

        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(50)
        self._resize_timer.timeout.connect(self._reload_peaks_for_current_width)

        self._visualization_timer = QTimer(self)
        self._visualization_timer.setInterval(self.VISUALIZATION_TIMER_MS)
        self._visualization_timer.timeout.connect(self._refresh_live_visualization)

        self._player.durationChanged.connect(self._on_duration_changed)
        self._player.positionChanged.connect(self._on_position_changed)
        self._player.mediaStatusChanged.connect(self._on_media_status_changed)
        self._player.playbackStateChanged.connect(self._sync_visualization_timer)
        self._slider.sliderMoved.connect(self._seek_to_ms)
        self.volume_slider.valueChanged.connect(self._set_volume_percent)
        self._audio_out.volumeChanged.connect(self._sync_volume_controls)
        self.mute_button.toggled.connect(self._set_muted)
        self._audio_out.mutedChanged.connect(self._sync_mute_button)
        self.wave.scrubRequested.connect(self._scrub_by_ms)
        self.wave.seekRequested.connect(self._seek_to_ms)
        self._sync_volume_controls()
        self._sync_mute_button()
        self._sync_equalizer_surfaces()
        self._install_shortcuts()
        QTimer.singleShot(0, self._sync_media_stage_size)

    def _apply_window_icon(self) -> None:
        icon = QIcon()
        action = getattr(self.app, "media_player_action", None)
        if action is not None:
            icon = action.icon()
        if icon.isNull():
            icon_path = self._media_icon_path("media-player")
            if icon_path.exists():
                icon = QIcon(str(icon_path))
        if not icon.isNull():
            self.setWindowIcon(icon)

    def _sync_media_stage_size(self) -> None:
        if getattr(self, "_media_stage_syncing", False):
            return
        if not hasattr(self, "media_group") or self.media_group is None:
            return
        layout = self.media_group.layout()
        if layout is None:
            return

        self._media_stage_syncing = True
        try:
            contents = self.media_group.contentsRect()
            margins = layout.contentsMargins()
            row_height = max(
                self.MEDIA_ROW_HEIGHT,
                int(contents.height()) - int(margins.top()) - int(margins.bottom()),
            )
            available_width = max(
                1,
                int(contents.width()) - int(margins.left()) - int(margins.right()),
            )
            art_spacing = 20 if self.artwork_container.isVisible() else 0
            max_art_by_width = available_width - art_spacing - 360
            if max_art_by_width <= 0:
                max_art_by_width = self.ARTWORK_SIZE
            artwork_size = max(
                self.ARTWORK_SIZE,
                min(row_height, int(max_art_by_width)),
            )
            waveform_height = max(
                self.WAVEFORM_HEIGHT,
                min(row_height, int(round(row_height * 0.86))),
            )

            if self.waveform_panel.maximumHeight() != row_height:
                self.waveform_panel.setMaximumHeight(row_height)
            if self.wave.maximumHeight() != waveform_height:
                self.wave.setMaximumHeight(waveform_height)
            self.wave.set_preferred_height(waveform_height)

            if self.artwork_container.maximumHeight() != row_height:
                self.artwork_container.setMaximumHeight(row_height)
            if self.artwork_container.maximumWidth() != artwork_size:
                self.artwork_container.setMaximumWidth(artwork_size)
            artwork_target = QSize(artwork_size, artwork_size)
            if self.artwork_label.maximumSize() != artwork_target:
                self.artwork_label.setMaximumSize(artwork_target)
            self.artwork_label.set_target_extent(artwork_size)
            if self.artwork_label.size() != artwork_target:
                self._refresh_artwork_pixmap()
            self.waveform_panel.updateGeometry()
            self.wave.updateGeometry()
            self.artwork_container.updateGeometry()
            self.artwork_label.updateGeometry()
        finally:
            self._media_stage_syncing = False

    def _media_icon_path(self, icon_key: str) -> Path:
        filename = self._MEDIA_ICON_FILES.get(str(icon_key or ""))
        if not filename:
            return Path()
        return RES_DIR() / "icons" / filename

    @staticmethod
    def _media_icon_relative_luminance(color: QColor) -> float:
        def channel(value: int) -> float:
            normalized = max(0.0, min(1.0, float(value) / 255.0))
            if normalized <= 0.03928:
                return normalized / 12.92
            return ((normalized + 0.055) / 1.055) ** 2.4

        return (
            0.2126 * channel(color.red())
            + 0.7152 * channel(color.green())
            + 0.0722 * channel(color.blue())
        )

    @classmethod
    def _media_icon_contrast_ratio(cls, foreground: QColor, background: QColor) -> float:
        fg_luminance = cls._media_icon_relative_luminance(foreground)
        bg_luminance = cls._media_icon_relative_luminance(background)
        lighter = max(fg_luminance, bg_luminance)
        darker = min(fg_luminance, bg_luminance)
        return (lighter + 0.05) / (darker + 0.05)

    def _media_icon_background_color(self, button: QToolButton | None) -> QColor:
        palette = button.palette() if button is not None else self.palette()
        if button is not None and button.isChecked():
            background = palette.color(QPalette.Highlight)
        else:
            background = palette.color(QPalette.Button)
        if not background.isValid():
            background = self.palette().color(QPalette.Window)
        return background

    def _media_icon_contrasting_color(
        self,
        button: QToolButton | None,
        preferred: QColor | None = None,
    ) -> QColor:
        background = self._media_icon_background_color(button)
        preferred_color = QColor(preferred) if isinstance(preferred, QColor) else QColor()
        if not preferred_color.isValid():
            preferred_color = self.palette().color(QPalette.ButtonText)
        if (
            preferred_color.isValid()
            and self._media_icon_contrast_ratio(preferred_color, background) >= 3.0
        ):
            return preferred_color

        dark = QColor("#111827")
        light = QColor("#FFFFFF")
        if self._media_icon_contrast_ratio(dark, background) >= self._media_icon_contrast_ratio(
            light, background
        ):
            return dark
        return light

    @staticmethod
    def _colorized_media_icon_pixmap(source: QPixmap, color: QColor) -> QPixmap:
        result = QPixmap(source.size())
        result.setDevicePixelRatio(source.devicePixelRatioF())
        result.fill(QColor(0, 0, 0, 0))
        painter = QPainter(result)
        try:
            painter.drawPixmap(0, 0, source)
            painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
            painter.fillRect(result.rect(), color)
        finally:
            painter.end()
        return result

    def _tinted_media_icon_pixmap(self, source: QPixmap, color: QColor) -> QPixmap:
        tinted = QPixmap(source.size())
        tinted.setDevicePixelRatio(source.devicePixelRatioF())
        tinted.fill(QColor(0, 0, 0, 0))

        outline_color = QColor(
            "#FFFFFF" if self._media_icon_relative_luminance(color) < 0.5 else "#111827"
        )
        outline_color.setAlphaF(max(0.0, min(1.0, color.alphaF() * 0.55)))
        outline = self._colorized_media_icon_pixmap(source, outline_color)
        foreground = self._colorized_media_icon_pixmap(source, color)

        painter = QPainter(tinted)
        try:
            for dx, dy in (
                (-1, 0),
                (1, 0),
                (0, -1),
                (0, 1),
                (-1, -1),
                (1, -1),
                (-1, 1),
                (1, 1),
            ):
                painter.drawPixmap(dx, dy, outline)
            painter.drawPixmap(0, 0, foreground)
        finally:
            painter.end()
        return tinted

    def _media_icon(
        self,
        icon_key: str,
        *,
        color: QColor | None = None,
        inactive: bool = False,
    ) -> QIcon:
        icon_color = QColor(color) if isinstance(color, QColor) else QColor()
        if not icon_color.isValid():
            icon_color = self.palette().color(QPalette.ButtonText)
        if inactive:
            icon_color.setAlphaF(max(0.0, min(1.0, icon_color.alphaF() * 0.38)))
        cache_key = (str(icon_key or ""), bool(inactive), icon_color.name(QColor.HexArgb))
        cached = self._media_icon_cache.get(cache_key)
        if isinstance(cached, QIcon):
            return cached

        icon_path = self._media_icon_path(str(icon_key or ""))
        icon = QIcon(str(icon_path)) if icon_path.exists() else QIcon()
        if not icon.isNull():
            pixmap = icon.pixmap(self.MEDIA_ICON_SIZE)
            if not pixmap.isNull():
                normal_pixmap = self._tinted_media_icon_pixmap(pixmap, icon_color)
                disabled_color = QColor(icon_color)
                disabled_color.setAlphaF(max(0.0, min(1.0, disabled_color.alphaF() * 0.38)))
                disabled_pixmap = self._tinted_media_icon_pixmap(pixmap, disabled_color)
                prepared_icon = QIcon()
                for mode in (QIcon.Normal, QIcon.Active, QIcon.Selected):
                    prepared_icon.addPixmap(normal_pixmap, mode, QIcon.Off)
                    prepared_icon.addPixmap(normal_pixmap, mode, QIcon.On)
                prepared_icon.addPixmap(disabled_pixmap, QIcon.Disabled, QIcon.Off)
                prepared_icon.addPixmap(disabled_pixmap, QIcon.Disabled, QIcon.On)
                icon = prepared_icon

        self._media_icon_cache[cache_key] = icon
        return icon

    def _set_icon_button_content(
        self,
        button: QToolButton,
        icon_key: str,
        fallback_text: str,
        *,
        inactive: bool = False,
    ) -> None:
        if button.isChecked():
            preferred_color = button.palette().color(QPalette.HighlightedText)
        else:
            preferred_color = button.palette().color(QPalette.ButtonText)
        icon = self._media_icon(
            icon_key,
            color=self._media_icon_contrasting_color(button, preferred_color),
            inactive=inactive,
        )
        button.setProperty("mediaIconKey", icon_key)
        button.setProperty("mediaFallbackText", fallback_text)
        button.setProperty("mediaIconInactive", bool(inactive))
        button.setIconSize(self.MEDIA_ICON_SIZE)
        if icon.isNull():
            button.setIcon(QIcon())
            button.setText(fallback_text)
            button.setToolButtonStyle(Qt.ToolButtonTextOnly)
            return
        button.setText("")
        button.setIcon(icon)
        button.setToolButtonStyle(Qt.ToolButtonIconOnly)

    def _create_transport_button(
        self,
        icon_key: str,
        fallback_text: str,
        tooltip: str,
        object_name: str,
        slot: Callable[[], None],
    ) -> QToolButton:
        button = QToolButton(self)
        button.setObjectName(object_name)
        button.setProperty("role", "mediaTransportButton")
        self._set_icon_button_content(button, icon_key, fallback_text)
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        button.setAutoRaise(False)
        button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        button.setFixedSize(42, 34)
        button.clicked.connect(slot)
        return button

    def _set_media_button_enabled(self, button: QToolButton, enabled: bool) -> None:
        was_enabled = bool(button.isEnabled())
        next_enabled = bool(enabled)
        button.setEnabled(next_enabled)
        if was_enabled == next_enabled:
            return
        icon_key = str(button.property("mediaIconKey") or "")
        fallback_text = str(button.property("mediaFallbackText") or "")
        inactive = bool(button.property("mediaIconInactive"))
        if icon_key:
            self._set_icon_button_content(button, icon_key, fallback_text, inactive=inactive)
        button.style().unpolish(button)
        button.style().polish(button)
        button.update()

    def _refresh_media_button_icons(self) -> None:
        for button in (
            getattr(self, "previous_button", None),
            getattr(self, "rewind_button", None),
            getattr(self, "play_button", None),
            getattr(self, "pause_button", None),
            getattr(self, "stop_button", None),
            getattr(self, "forward_button", None),
            getattr(self, "next_button", None),
        ):
            if not isinstance(button, QToolButton):
                continue
            icon_key = str(button.property("mediaIconKey") or "")
            fallback_text = str(button.property("mediaFallbackText") or "")
            if icon_key:
                self._set_icon_button_content(button, icon_key, fallback_text)
        if hasattr(self, "shuffle_button"):
            self._sync_shuffle_button()
        if hasattr(self, "auto_advance_button"):
            self._sync_auto_advance_button()
        if hasattr(self, "album_scope_button"):
            self._sync_album_scope_button()
        if hasattr(self, "loop_button"):
            self._sync_loop_button()
        if hasattr(self, "equalizer_button"):
            self._sync_equalizer_button()
        if hasattr(self, "bookmark_button"):
            self._sync_bookmark_button()
        if hasattr(self, "mute_button") and hasattr(self, "_audio_out"):
            self._sync_mute_button()
        export_button = getattr(self, "export_button", None)
        if isinstance(export_button, QToolButton):
            self._set_icon_button_content(export_button, "export", "Export")

    def _create_loop_button(self) -> QToolButton:
        button = QToolButton(self)
        button.setObjectName("audioPreviewLoopButton")
        button.setProperty("role", "mediaTransportButton")
        button.setCheckable(True)
        button.setAutoRaise(False)
        button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        button.setFixedSize(42, 34)
        button.clicked.connect(self._cycle_loop_mode)
        self._sync_loop_button(button)
        return button

    def _create_shuffle_button(self) -> QToolButton:
        button = QToolButton(self)
        button.setObjectName("audioPreviewShuffleButton")
        button.setProperty("role", "mediaTransportButton")
        button.setCheckable(True)
        button.setAutoRaise(False)
        button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        button.setFixedSize(42, 34)
        button.clicked.connect(lambda checked=False: self._set_shuffle_enabled(bool(checked)))
        self._sync_shuffle_button(button)
        return button

    def _create_auto_advance_button(self) -> QToolButton:
        button = QToolButton(self)
        button.setObjectName("audioPreviewAutoAdvanceButton")
        button.setProperty("role", "mediaToggle")
        button.setCheckable(True)
        button.setChecked(True)
        button.setAutoRaise(False)
        button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        button.setFixedSize(42, 34)
        button.clicked.connect(lambda _checked=False: self._sync_auto_advance_button(button))
        self._sync_auto_advance_button(button)
        return button

    def _create_album_scope_button(self) -> QToolButton:
        button = QToolButton(self)
        button.setObjectName("audioPreviewAlbumScopeButton")
        button.setProperty("role", "mediaToggle")
        button.setCheckable(True)
        button.setAutoRaise(False)
        button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        button.setFixedSize(42, 34)
        button.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(button)
        menu.aboutToShow.connect(self._rebuild_album_scope_menu)
        button.setMenu(menu)
        self._album_scope_menu = menu
        self._sync_album_scope_button(button)
        return button

    def _create_equalizer_button(self) -> QToolButton:
        button = QToolButton(self)
        button.setObjectName("audioPreviewEqualizerButton")
        button.setProperty("role", "mediaToggle")
        button.setCheckable(True)
        button.setAutoRaise(False)
        button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        button.setFixedSize(42, 34)
        button.clicked.connect(lambda _checked=False: self._open_equalizer_dialog())
        self._sync_equalizer_button(button)
        return button

    def _create_bookmark_button(self) -> QToolButton:
        button = QToolButton(self)
        button.setObjectName("audioPreviewBookmarkButton")
        button.setProperty("role", "mediaToggle")
        button.setAutoRaise(False)
        button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        button.setFixedSize(42, 34)
        button.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(button)
        menu.aboutToShow.connect(self._rebuild_bookmark_menu)
        button.setMenu(menu)
        self._bookmark_menu = menu
        self._sync_bookmark_button(button)
        return button

    def _apply_stop_button_font(self) -> None:
        if not hasattr(self, "stop_button"):
            return
        base_font = self.play_button.font() if hasattr(self, "play_button") else self.font()
        self.stop_button.setFont(base_font)
        self.stop_button.setStyleSheet("")

    def _cycle_loop_mode(self) -> None:
        next_modes = {
            self.LOOP_MODE_OFF: self.LOOP_MODE_PLAYLIST,
            self.LOOP_MODE_PLAYLIST: self.LOOP_MODE_TRACK,
            self.LOOP_MODE_TRACK: self.LOOP_MODE_OFF,
        }
        self._set_loop_mode(next_modes.get(self._loop_mode, self.LOOP_MODE_OFF))

    def _set_loop_mode(self, mode: str) -> None:
        normalized = str(mode or "").strip().lower()
        if normalized not in {
            self.LOOP_MODE_OFF,
            self.LOOP_MODE_PLAYLIST,
            self.LOOP_MODE_TRACK,
        }:
            normalized = self.LOOP_MODE_OFF
        self._loop_mode = normalized
        self._sync_loop_button()
        self._update_navigation_buttons()
        self._refresh_audio_preload_window_if_ready()

    def _sync_loop_button(self, button: QToolButton | None = None) -> None:
        button = button or getattr(self, "loop_button", None)
        if button is None:
            return
        mode = self._loop_mode
        active = mode != self.LOOP_MODE_OFF
        icon_key = "repeat-one" if mode == self.LOOP_MODE_TRACK else "repeat"
        fallback_text = "R1" if mode == self.LOOP_MODE_TRACK else "R"
        tooltip = {
            self.LOOP_MODE_OFF: "Loop Off",
            self.LOOP_MODE_PLAYLIST: "Loop Playlist",
            self.LOOP_MODE_TRACK: "Loop Current Track",
        }.get(mode, "Loop Off")
        button.blockSignals(True)
        try:
            button.setChecked(active)
        finally:
            button.blockSignals(False)
        button.setProperty("loopMode", mode)
        self._set_icon_button_content(
            button,
            icon_key,
            fallback_text,
            inactive=mode == self.LOOP_MODE_OFF,
        )
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        button.style().unpolish(button)
        button.style().polish(button)
        button.update()

    def _sync_shuffle_button(self, button: QToolButton | None = None) -> None:
        button = button or getattr(self, "shuffle_button", None)
        if button is None:
            return
        active = bool(self._shuffle_enabled)
        button.blockSignals(True)
        try:
            button.setChecked(active)
        finally:
            button.blockSignals(False)
        button.setProperty("shuffleEnabled", active)
        self._set_icon_button_content(
            button,
            "shuffle",
            "Shuf",
            inactive=not active,
        )
        tooltip = "Shuffle On" if active else "Shuffle Off"
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        button.style().unpolish(button)
        button.style().polish(button)
        button.update()

    def _auto_advance_enabled(self) -> bool:
        button = getattr(self, "auto_advance_button", None)
        return bool(button.isChecked()) if isinstance(button, QToolButton) else True

    def _sync_auto_advance_button(self, button: QToolButton | None = None) -> None:
        button = button or getattr(self, "auto_advance_button", None)
        if button is None:
            return
        active = bool(button.isChecked())
        button.setProperty("autoAdvanceEnabled", active)
        self._set_icon_button_content(
            button,
            "auto-advance",
            "Auto",
            inactive=not active,
        )
        tooltip = "Auto Advance On" if active else "Auto Advance Off"
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        button.style().unpolish(button)
        button.style().polish(button)
        button.update()

    def _available_album_scope_titles(self) -> list[str]:
        titles: list[str] = []
        provider = getattr(self.app, "_audio_preview_album_titles", None)
        if callable(provider):
            try:
                titles.extend(str(title or "").strip() for title in provider())
            except Exception:
                titles = []
        if not titles:
            for spec in list(getattr(self, "_base_track_queue", []) or []):
                try:
                    titles.append(str(spec.get("album") or "").strip())
                except AttributeError:
                    continue
        unique: dict[str, str] = {}
        for title in titles:
            clean = str(title or "").strip()
            if clean:
                unique.setdefault(clean.casefold(), clean)
        return sorted(unique.values(), key=str.casefold)

    def _album_track_order_for_title(self, album_title: str | None) -> list[int]:
        clean_title = str(album_title or "").strip()
        if not clean_title:
            return []
        provider = getattr(self.app, "_audio_preview_album_track_ids", None)
        if callable(provider):
            try:
                return self.app._normalize_track_ids(provider(clean_title, self._source_spec))
            except Exception:
                pass
        fallback: list[int] = []
        for spec in list(getattr(self, "_base_track_queue", []) or []):
            try:
                if str(spec.get("album") or "").strip().casefold() != clean_title.casefold():
                    continue
                fallback.append(int(spec.get("track_id")))
            except AttributeError, TypeError, ValueError:
                continue
        return self.app._normalize_track_ids(fallback)

    def _effective_base_track_order(self) -> list[int]:
        if self._album_scope_title:
            return self._album_track_order_for_title(self._album_scope_title)
        return list(self._base_track_order)

    def _set_album_scope_title(self, album_title: str | None) -> None:
        clean_title = str(album_title or "").strip() or None
        self._album_scope_title = clean_title
        self._apply_effective_track_order()
        self._sync_album_scope_button()
        self._update_navigation_buttons()
        self._refresh_audio_preload_window_if_ready()
        if clean_title and self._source_spec is not None and self._track_order:
            self.open_track_preview(int(self._track_order[0]), self._source_spec, autoplay=False)

    def _rebuild_album_scope_menu(self) -> None:
        menu = self._album_scope_menu
        if menu is None:
            return
        menu.clear()
        off_action = menu.addAction("Off")
        off_action.setCheckable(True)
        off_action.setChecked(self._album_scope_title is None)
        off_action.triggered.connect(lambda _checked=False: self._set_album_scope_title(None))

        titles = self._available_album_scope_titles()
        if titles:
            menu.addSeparator()
        active_title = str(self._album_scope_title or "").casefold()
        for title in titles:
            action = menu.addAction(title)
            action.setCheckable(True)
            action.setChecked(title.casefold() == active_title)
            action.triggered.connect(
                lambda _checked=False, album_title=title: self._set_album_scope_title(album_title)
            )

    def _sync_album_scope_button(self, button: QToolButton | None = None) -> None:
        button = button or getattr(self, "album_scope_button", None)
        if button is None:
            return
        active = bool(self._album_scope_title)
        button.blockSignals(True)
        try:
            button.setChecked(active)
        finally:
            button.blockSignals(False)
        button.setProperty("albumScopeTitle", self._album_scope_title or "")
        self._set_icon_button_content(
            button,
            "album-scope",
            "Album",
            inactive=not active,
        )
        tooltip = (
            f"Album Playlist: {self._album_scope_title}"
            if self._album_scope_title
            else "Album Playlist Off"
        )
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        button.style().unpolish(button)
        button.style().polish(button)
        button.update()

    def _effective_equalizer_settings(self) -> dict[str, object]:
        return normalize_equalizer_settings(getattr(self, "_equalizer_settings", None))

    def _sync_equalizer_button(self, button: QToolButton | None = None) -> None:
        button = button or getattr(self, "equalizer_button", None)
        if button is None:
            return
        settings = self._effective_equalizer_settings()
        enabled = equalizer_is_enabled(settings)
        button.blockSignals(True)
        try:
            button.setChecked(enabled)
        finally:
            button.blockSignals(False)
        self._set_icon_button_content(
            button,
            "equalizer",
            "EQ",
            inactive=not enabled,
        )
        tooltip = "Equalizer On" if enabled else "Equalizer Off"
        button.setToolTip(f"{tooltip} - Open Equalizer")
        button.setAccessibleName("Equalizer")
        button.style().unpolish(button)
        button.style().polish(button)
        button.update()

    def _sync_equalizer_surfaces(self) -> None:
        settings = self._effective_equalizer_settings()
        if hasattr(self, "scope"):
            self.scope.set_equalizer_settings(settings)
        self._sync_equalizer_button()
        dialog = getattr(self, "_equalizer_dialog", None)
        if isinstance(dialog, EqualizerDialog):
            dialog.set_settings(settings)

    def _open_equalizer_dialog(self) -> None:
        self._sync_equalizer_button()
        dialog = getattr(self, "_equalizer_dialog", None)
        if not isinstance(dialog, EqualizerDialog):
            dialog = EqualizerDialog(self._effective_equalizer_settings(), parent=self)
            dialog.settingsChanged.connect(self._on_equalizer_dialog_settings_changed)
            player = getattr(self, "_player", None)
            spectrum_signal = getattr(player, "spectrumFrameChanged", None)
            if spectrum_signal is not None:
                spectrum_signal.connect(dialog.set_playback_spectrum)
            self._equalizer_dialog = dialog
        else:
            dialog.set_settings(self._effective_equalizer_settings())
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _bookmark_connection(self) -> sqlite3.Connection | None:
        conn = getattr(self.app, "conn", None)
        return conn if isinstance(conn, sqlite3.Connection) else None

    def _bookmark_duration_ms(self) -> int:
        duration = 0
        for candidate in (
            getattr(getattr(self, "_player", None), "duration", lambda: 0)(),
            getattr(getattr(self, "_slider", None), "maximum", lambda: 0)(),
        ):
            try:
                duration = max(duration, int(candidate or 0))
            except TypeError, ValueError:
                continue
        return max(0, duration)

    def _bookmark_position_ms(self) -> int:
        position = 0
        for candidate in (
            getattr(getattr(self, "_player", None), "position", lambda: 0)(),
            getattr(getattr(self, "_slider", None), "value", lambda: 0)(),
        ):
            try:
                position = max(position, int(candidate or 0))
            except TypeError, ValueError:
                continue
        duration = self._bookmark_duration_ms()
        if duration > 0:
            position = min(position, duration)
        return max(0, position)

    def _bookmark_label(self, bookmark: AudioBookmark) -> str:
        label = str(getattr(bookmark, "label", "") or "").strip()
        time_label = self._format_time(int(bookmark.position_ms))
        if label:
            return f"{time_label} - {label}"
        return time_label

    def _reload_current_bookmarks(self) -> None:
        track_id = self._current_track_id_as_int()
        conn = self._bookmark_connection()
        bookmarks: list[AudioBookmark] = []
        if track_id is not None and conn is not None:
            try:
                bookmarks = load_audio_bookmarks(conn, track_id)
            except Exception:
                bookmarks = []
                logger = getattr(self.app, "logger", None)
                if logger is not None:
                    logger.exception("Failed to load audio bookmarks for track %s", track_id)
        self._current_bookmarks = bookmarks
        if hasattr(self, "wave"):
            self.wave.set_bookmarks_ms([bookmark.position_ms for bookmark in bookmarks])
        self._sync_bookmark_button()

    def _sync_bookmark_button(self, button: QToolButton | None = None) -> None:
        button = button or getattr(self, "bookmark_button", None)
        if button is None:
            return
        track_id = self._current_track_id_as_int()
        can_bookmark = track_id is not None and self._bookmark_connection() is not None
        count = len(getattr(self, "_current_bookmarks", []) or [])
        self._set_icon_button_content(
            button,
            "bookmark",
            "Mark",
            inactive=not can_bookmark,
        )
        button.setEnabled(can_bookmark)
        if can_bookmark:
            current_time = self._format_time(self._bookmark_position_ms())
            noun = "bookmark" if count == 1 else "bookmarks"
            button.setToolTip(f"Add Bookmark at {current_time} ({count} saved {noun})")
            button.setAccessibleName("Audio Bookmarks")
        else:
            button.setToolTip("Bookmarks are available for saved tracks")
            button.setAccessibleName("Audio Bookmarks")
        button.style().unpolish(button)
        button.style().polish(button)
        button.update()

    def _rebuild_bookmark_menu(self) -> None:
        menu = self._bookmark_menu
        if menu is None:
            return
        menu.clear()
        track_id = self._current_track_id_as_int()
        can_bookmark = track_id is not None and self._bookmark_connection() is not None

        add_action = menu.addAction(
            f"Add Bookmark at {self._format_time(self._bookmark_position_ms())}"
        )
        add_action.setEnabled(can_bookmark)
        add_action.triggered.connect(
            lambda _checked=False: self._add_bookmark_at_current_position()
        )

        bookmarks = list(getattr(self, "_current_bookmarks", []) or [])
        menu.addSeparator()
        if not bookmarks:
            empty_action = menu.addAction("No bookmarks for this track")
            empty_action.setEnabled(False)
            return

        for bookmark in bookmarks:
            action = menu.addAction(self._bookmark_label(bookmark))
            action.setData(int(bookmark.id))
            action.triggered.connect(
                lambda _checked=False, position_ms=bookmark.position_ms: self._jump_to_bookmark(
                    position_ms
                )
            )

        menu.addSeparator()
        remove_menu = menu.addMenu("Remove Bookmark")
        for bookmark in bookmarks:
            action = remove_menu.addAction(self._bookmark_label(bookmark))
            action.setData(int(bookmark.id))
            action.triggered.connect(
                lambda _checked=False, bookmark_id=bookmark.id: self._remove_bookmark(bookmark_id)
            )
        clear_action = menu.addAction("Remove All Bookmarks")
        clear_action.triggered.connect(
            lambda _checked=False: self._remove_all_bookmarks_for_current_track()
        )

    def _add_bookmark_at_current_position(self) -> None:
        track_id = self._current_track_id_as_int()
        conn = self._bookmark_connection()
        if track_id is None or conn is None:
            return
        try:
            bookmark = add_audio_bookmark(
                conn,
                track_id,
                self._bookmark_position_ms(),
                duration_ms=self._bookmark_duration_ms(),
            )
        except Exception as exc:
            QMessageBox.warning(self, "Bookmark", f"Could not save bookmark:\n{exc}")
            return
        self._reload_current_bookmarks()
        self._jump_to_bookmark(bookmark.position_ms)

    def _jump_to_bookmark(self, position_ms: int) -> None:
        self._seek_to_ms(int(position_ms))

    def _remove_bookmark(self, bookmark_id: int) -> None:
        track_id = self._current_track_id_as_int()
        conn = self._bookmark_connection()
        if track_id is None or conn is None:
            return
        try:
            delete_audio_bookmark(conn, bookmark_id, track_id=track_id)
        except Exception as exc:
            QMessageBox.warning(self, "Bookmark", f"Could not remove bookmark:\n{exc}")
            return
        self._reload_current_bookmarks()

    def _remove_all_bookmarks_for_current_track(self) -> None:
        track_id = self._current_track_id_as_int()
        conn = self._bookmark_connection()
        if track_id is None or conn is None:
            return
        try:
            delete_audio_bookmarks_for_track(conn, track_id)
        except Exception as exc:
            QMessageBox.warning(self, "Bookmark", f"Could not remove bookmarks:\n{exc}")
            return
        self._reload_current_bookmarks()

    def _on_equalizer_dialog_settings_changed(self, settings: dict[str, object]) -> None:
        self._set_equalizer_settings(settings, persist=True)

    def _set_equalizer_settings(
        self,
        settings: dict[str, object],
        *,
        persist: bool,
    ) -> None:
        normalized = normalize_equalizer_settings(settings)
        self._equalizer_settings = normalized
        if persist:
            self._equalizer_settings = save_equalizer_settings(
                getattr(self.app, "settings", None),
                normalized,
            )
        if hasattr(self, "_player"):
            self._player.set_equalizer_settings(self._equalizer_settings)
        self._sync_equalizer_surfaces()

    def _hint_text_font(self) -> QFont:
        font = QFont(self.font())
        effective_theme = {}
        provider = getattr(self.app, "_effective_theme_settings", None)
        if callable(provider):
            try:
                effective_theme = dict(provider() or {})
            except Exception:
                effective_theme = {}
        try:
            hint_size = int(effective_theme.get("secondary_text_font_size") or 0)
        except TypeError, ValueError:
            hint_size = 0
        if hint_size <= 0:
            point_size = font.pointSizeF()
            if point_size <= 0:
                point_size = float(QApplication.font().pointSizeF())
            hint_size = max(8, int(round(point_size - 1)))
        font.setPointSize(max(1, int(hint_size)))
        return font

    def _apply_play_next_font(self) -> None:
        if not hasattr(self, "play_next_list"):
            return
        font = self._hint_text_font()
        self.play_next_list.setFont(font)
        for index in range(self.play_next_list.count()):
            self.play_next_list.item(index).setFont(font)

    def _set_play_next_items(self, items: list[dict[str, object]]) -> None:
        if not hasattr(self, "play_next_list"):
            return
        self._track_queue = list(items or [])
        self.play_next_list.blockSignals(True)
        try:
            self.play_next_list.clear()
            font = self._hint_text_font()
            if not self._track_queue:
                item = QListWidgetItem("No playable tracks")
                item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
                item.setFont(font)
                self.play_next_list.addItem(item)
                return
            for position, spec in enumerate(self._track_queue, start=1):
                try:
                    track_id = int(spec.get("track_id"))
                except TypeError, ValueError:
                    continue
                title = str(spec.get("title") or spec.get("label") or f"Track {track_id}").strip()
                if not title:
                    title = f"Track {track_id}"
                label = str(spec.get("label") or title).strip() or title
                item = QListWidgetItem(label)
                item.setData(Qt.UserRole, track_id)
                item.setToolTip(f"{position}. {title}")
                item.setFont(font)
                self.play_next_list.addItem(item)
        finally:
            self.play_next_list.blockSignals(False)
        self._sync_play_next_selection()

    def _ordered_track_queue_items(self, track_order: list[int]) -> list[dict[str, object]]:
        by_id: dict[int, dict[str, object]] = {}
        for spec in self._base_track_queue:
            try:
                track_id = int(spec.get("track_id"))
            except AttributeError, TypeError, ValueError:
                continue
            by_id[track_id] = dict(spec)
        ordered: list[dict[str, object]] = []
        for position, track_id in enumerate(track_order, start=1):
            try:
                normalized_id = int(track_id)
            except TypeError, ValueError:
                continue
            spec = dict(by_id.get(normalized_id) or {})
            if not spec:
                queue_provider = getattr(self.app, "_audio_preview_track_queue_items", None)
                if callable(queue_provider):
                    try:
                        fetched = list(queue_provider([normalized_id]) or [])
                    except Exception:
                        fetched = []
                    if fetched:
                        spec = dict(fetched[0])
            title = str(spec.get("title") or spec.get("label") or "").strip()
            if not title:
                title = f"Track {normalized_id}"
            spec.update(
                {
                    "track_id": normalized_id,
                    "title": title,
                    "label": str(spec.get("label") or title).strip() or title,
                    "position": position,
                }
            )
            ordered.append(spec)
        return ordered

    def _sync_play_next_selection(self) -> None:
        if not hasattr(self, "play_next_list"):
            return
        current_id = self._current_track_id
        try:
            current_id = int(current_id)
        except TypeError, ValueError:
            current_id = None
        self.play_next_list.blockSignals(True)
        try:
            self.play_next_list.clearSelection()
            if current_id is None:
                self.play_next_list.setCurrentRow(-1)
                return
            for index in range(self.play_next_list.count()):
                item = self.play_next_list.item(index)
                try:
                    track_id = int(item.data(Qt.UserRole))
                except TypeError, ValueError:
                    continue
                if track_id == current_id:
                    self.play_next_list.setCurrentItem(item)
                    item.setSelected(True)
                    self.play_next_list.scrollToItem(item, QAbstractItemView.PositionAtCenter)
                    return
            self.play_next_list.setCurrentRow(-1)
        finally:
            self.play_next_list.blockSignals(False)

    def _play_next_item(self, item: QListWidgetItem | None) -> None:
        if item is None or self._source_spec is None:
            self._sync_play_next_selection()
            return
        try:
            track_id = int(item.data(Qt.UserRole))
        except TypeError, ValueError:
            self._sync_play_next_selection()
            return
        if track_id == self._current_track_id:
            self._sync_play_next_selection()
            return
        self.open_track_preview(track_id, self._source_spec, autoplay=True)

    def _install_shortcuts(self) -> None:
        bindings = (
            ("Space", self._toggle_play_pause),
            ("Left", lambda: self._scrub_by_ms(-self.SCRUB_STEP_MS)),
            ("Right", lambda: self._scrub_by_ms(self.SCRUB_STEP_MS)),
            ("Shift+Left", lambda: self._jump_by_ms(-self.JUMP_STEP_MS)),
            ("Shift+Right", lambda: self._jump_by_ms(self.JUMP_STEP_MS)),
            ("Meta+Left", self._go_to_previous_track),
            ("Meta+Right", self._go_to_next_track),
        )
        for sequence, handler in bindings:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.WindowShortcut)
            shortcut.activated.connect(handler)

    @staticmethod
    def _audio_preload_source_key(source_spec: dict[str, object] | None) -> str:
        if not isinstance(source_spec, dict):
            return "raw"
        relevant: dict[str, object] = {
            "kind": str(source_spec.get("kind") or "").strip().lower(),
        }
        if relevant["kind"] == "custom":
            try:
                relevant["field_id"] = int(source_spec.get("field_id") or 0)
            except TypeError, ValueError:
                relevant["field_id"] = 0
        else:
            relevant["media_key"] = (
                str(source_spec.get("media_key") or "audio_file").strip() or "audio_file"
            )
        return json.dumps(relevant, sort_keys=True, separators=(",", ":"))

    def _audio_preload_key(
        self,
        track_id: int,
        source_spec: dict[str, object] | None = None,
    ) -> tuple[int, str]:
        return int(track_id), self._audio_preload_source_key(
            source_spec if source_spec is not None else self._source_spec
        )

    def _log_audio_preload(self, action: str, **details) -> None:
        logger = getattr(self.app, "logger", None)
        message = f"Audio preview preload {action}"
        if logger is not None:
            try:
                logger.info("%s: %s", message, details)
            except Exception:
                pass
        log_event = getattr(self.app, "_log_event", None)
        if callable(log_event):
            try:
                log_event(f"audio_preview.preload.{action}", message, **details)
            except Exception:
                pass

    def _audio_preload_window_keys(self) -> list[tuple[int, str]]:
        source_spec = self._source_spec if isinstance(self._source_spec, dict) else None
        current_id = self._current_track_id_as_int()
        if source_spec is None or current_id is None:
            return []
        track_ids = self._audio_preload_window_track_ids(current_id)
        return [self._audio_preload_key(track_id, source_spec) for track_id in track_ids]

    def _audio_preload_required_keys(self) -> set[tuple[int, str]]:
        return set()

    def _audio_preload_window_track_ids(
        self,
        current_id: int,
        *,
        radius: int | None = None,
    ) -> list[int]:
        ordered: list[int] = []
        seen: set[int] = set()

        def _add(track_id: int | None) -> None:
            if track_id is None:
                return
            normalized = int(track_id)
            if normalized in seen:
                return
            seen.add(normalized)
            ordered.append(normalized)

        track_order = [int(track_id) for track_id in self._track_order]
        index = track_order.index(int(current_id)) if int(current_id) in track_order else -1
        wrap = self._loop_mode == self.LOOP_MODE_PLAYLIST and len(track_order) > 1
        preload_radius = max(1, int(1 if radius is None else radius))
        _add(current_id)
        if index >= 0:
            for distance in range(1, preload_radius + 1):
                next_index = index + distance
                previous_index = index - distance
                if wrap and track_order:
                    next_index %= len(track_order)
                    previous_index %= len(track_order)
                _add(track_order[next_index] if 0 <= next_index < len(track_order) else None)
                _add(
                    track_order[previous_index] if 0 <= previous_index < len(track_order) else None
                )
        return ordered

    def _cached_prepared_media_for(
        self,
        track_id: int,
        source_spec: dict[str, object],
    ) -> _AudioPreviewPreparedMedia | None:
        del track_id, source_spec
        return None

    def _track_order_for_load_request(
        self,
        track_id: int,
        source_spec: dict[str, object],
    ) -> list[int]:
        provider = getattr(self.app, "_audio_preview_navigation_track_ids", None)
        track_order: list[int] = []
        if callable(provider):
            try:
                track_order = self.app._normalize_track_ids(provider(source_spec))
            except Exception:
                track_order = []
        if int(track_id) not in track_order:
            track_order = [int(track_id), *track_order]
        return track_order

    def _effective_track_order_for_load_request(
        self,
        track_id: int,
        source_spec: dict[str, object],
        base_track_order: list[int],
    ) -> list[int]:
        request_source_key = self._audio_preload_source_key(source_spec)
        current_source_key = self._audio_preload_source_key(self._source_spec)
        existing_order = self.app._normalize_track_ids(getattr(self, "_track_order", []) or [])
        if (
            existing_order
            and int(track_id) in existing_order
            and request_source_key == current_source_key
        ):
            return existing_order
        if self._shuffle_enabled:
            return self._create_shuffled_track_order(list(base_track_order), int(track_id))
        return list(base_track_order)

    def _placeholder_track_queue_items(
        self,
        track_order: list[int],
    ) -> list[dict[str, object]]:
        known: dict[int, dict[str, object]] = {}
        for source in (
            getattr(self, "_base_track_queue", []) or [],
            getattr(self, "_track_queue", []) or [],
        ):
            for spec in list(source):
                try:
                    track_id = int(spec.get("track_id"))
                except AttributeError, TypeError, ValueError:
                    continue
                known[track_id] = dict(spec)
        items: list[dict[str, object]] = []
        for position, track_id in enumerate(track_order, start=1):
            normalized_id = int(track_id)
            spec = dict(known.get(normalized_id) or {})
            title = str(spec.get("title") or spec.get("label") or "").strip()
            if not title:
                title = f"Track {normalized_id}"
            spec.update(
                {
                    "track_id": normalized_id,
                    "title": title,
                    "label": str(spec.get("label") or title).strip() or title,
                    "position": position,
                }
            )
            items.append(spec)
        return items

    def _begin_track_load(
        self,
        track_id: int,
        source_spec: dict[str, object],
        base_track_order: list[int],
        effective_track_order: list[int],
    ) -> None:
        self._source_spec = dict(source_spec)
        self._current_track_id = int(track_id)
        self._reload_current_bookmarks()
        self._base_track_order = list(base_track_order)
        self._base_track_queue = self._placeholder_track_queue_items(base_track_order)
        self._track_order = list(effective_track_order)
        self._set_play_next_items(self._placeholder_track_queue_items(effective_track_order))
        self._sync_album_scope_button()
        self._reset_player_source()
        self._cleanup_temp_file()
        self._current_audio_bytes = b""
        self._current_audio_mime = "audio/wav"
        self._current_title = f"Track {track_id}"
        self._current_artist = ""
        self._current_album = ""
        self.title_label.setText("Loading audio...")
        self.artist_label.hide()
        self.artist_label.setText("")
        self.album_label.hide()
        self.album_label.setText("")
        self.setWindowTitle("Audio Player - Loading...")
        self._set_export_actions([])
        self._apply_artwork(None)
        self.peak_meter.reset_signal_activity()
        self.scope.set_spectrum_frames([])
        self.peak_meter.set_peak_frames([])
        self.wave.setVisible(False)
        self.wave_status_label.setText("Loading audio...")
        self.wave_status_label.setVisible(True)
        self._apply_position(0, 0)
        self._update_navigation_buttons()

    @staticmethod
    def _prepared_media_ready_for_instant_playback(
        prepared_media: _AudioPreviewPreparedMedia | None,
    ) -> bool:
        del prepared_media
        return False

    def _apply_cached_track_preview(
        self,
        track_id: int,
        source_spec: dict[str, object],
        base_track_order: list[int],
        effective_track_order: list[int],
        prepared_media: _AudioPreviewPreparedMedia | None,
        *,
        autoplay: bool,
    ) -> bool:
        if not self._prepared_media_ready_for_instant_playback(prepared_media):
            return False
        self._cancel_audio_load_jobs(reason="cache-hit")
        self._audio_load_waiting_for_preload = None
        self._audio_load_request_id += 1
        try:
            cached_state = prepared_media.preview_state
            if isinstance(cached_state, dict):
                state = dict(cached_state)
                state["prepared_media"] = prepared_media
            else:
                state = self.app._audio_preview_state_for_track(
                    int(track_id),
                    dict(source_spec),
                    parent_widget=self,
                    prepared_media=prepared_media,
                )
            if self.app._normalize_track_ids(state.get("track_order") or []) != list(
                base_track_order
            ):
                state["track_queue"] = self._placeholder_track_queue_items(base_track_order)
            elif not state.get("track_queue"):
                state["track_queue"] = self._placeholder_track_queue_items(base_track_order)
            state["track_order"] = list(base_track_order)
            if self.app._normalize_track_ids(state.get("effective_track_order") or []) != list(
                effective_track_order
            ):
                state["effective_track_queue"] = self._placeholder_track_queue_items(
                    effective_track_order
                )
            elif not state.get("effective_track_queue"):
                state["effective_track_queue"] = self._placeholder_track_queue_items(
                    effective_track_order
                )
            state["effective_track_order"] = list(effective_track_order)
            state["export_actions"] = self.app._audio_preview_export_actions_for_track(
                int(track_id),
                source_spec,
                parent_widget=self,
                title_override=str(state.get("title") or ""),
            )
            self._log_audio_preload(
                "instant-hit",
                track_id=int(track_id),
                source_key=self._audio_preload_source_key(source_spec),
                bytes=prepared_media.memory_cost(),
            )
            self._apply_preview_state(
                state,
                source_spec=dict(source_spec),
                autoplay=bool(autoplay),
            )
            return True
        except Exception as exc:
            self._log_audio_preload(
                "instant-hit-failed",
                track_id=int(track_id),
                source_key=self._audio_preload_source_key(source_spec),
                error=str(exc),
            )
            return False

    def _use_inflight_preload_for_track(
        self,
        track_id: int,
        source_spec: dict[str, object],
        base_track_order: list[int],
        effective_track_order: list[int],
        *,
        autoplay: bool,
    ) -> bool:
        del track_id, source_spec, base_track_order, effective_track_order, autoplay
        return False

    def _waiting_preload_for_key(self, key: tuple[int, str]) -> dict[str, object] | None:
        waiting = getattr(self, "_audio_load_waiting_for_preload", None)
        if not isinstance(waiting, dict):
            return None
        waiting_key = waiting.get("key")
        if waiting_key != key:
            return None
        return waiting

    def _submit_waiting_preload_as_active_load(
        self,
        waiting: dict[str, object],
        prepared_media: _AudioPreviewPreparedMedia | None,
        *,
        reason: str,
    ) -> None:
        self._audio_load_waiting_for_preload = None
        self._audio_load_request_id += 1
        request_id = int(self._audio_load_request_id)
        track_id = int(waiting.get("track_id") or 0)
        source_spec = dict(waiting.get("source_spec") or {})
        base_track_order = list(waiting.get("base_track_order") or [])
        effective_track_order = list(waiting.get("effective_track_order") or [])
        self._log_audio_preload(
            "wait-fallback",
            track_id=track_id,
            source_key=self._audio_preload_source_key(source_spec),
            reason=reason,
        )
        self._submit_audio_track_load(
            request_id,
            track_id,
            source_spec,
            base_track_order,
            effective_track_order,
            prepared_media,
            bool(waiting.get("autoplay", False)),
        )

    def _apply_waiting_preload_result(
        self,
        key: tuple[int, str],
        prepared_media: _AudioPreviewPreparedMedia,
    ) -> bool:
        waiting = self._waiting_preload_for_key(key)
        if waiting is None:
            return False
        if not self._prepared_media_ready_for_instant_playback(prepared_media):
            self._submit_waiting_preload_as_active_load(
                waiting,
                prepared_media,
                reason="preload-not-decoded",
            )
            return True
        applied = self._apply_cached_track_preview(
            int(waiting.get("track_id") or key[0]),
            dict(waiting.get("source_spec") or {}),
            list(waiting.get("base_track_order") or []),
            list(waiting.get("effective_track_order") or []),
            prepared_media,
            autoplay=bool(waiting.get("autoplay", False)),
        )
        if applied:
            self._audio_load_waiting_for_preload = None
            self._log_audio_preload(
                "wait-ready",
                track_id=key[0],
                source_key=key[1],
            )
        return applied

    def _submit_audio_track_load(
        self,
        request_id: int,
        track_id: int,
        source_spec: dict[str, object],
        base_track_order: list[int],
        effective_track_order: list[int],
        prepared_media: _AudioPreviewPreparedMedia | None,
        autoplay: bool,
    ) -> None:
        executor = getattr(self, "_audio_load_executor", None)
        if executor is None or bool(getattr(executor, "_shutdown", False)):
            executor = ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix="audio-preview-load",
            )
            self._audio_load_executor = executor
        cancel_event = threading.Event()
        source_key = self._audio_preload_source_key(source_spec)
        task = _AudioPreviewTrackLoadTask(
            request_id=int(request_id),
            track_id=int(track_id),
            source_spec=dict(source_spec),
            source_key=source_key,
            autoplay=bool(autoplay),
            db_path=str(getattr(self.app, "current_db_path", "") or ""),
            data_root=str(getattr(self.app, "data_root", "") or "") or None,
            base_track_order=list(base_track_order),
            effective_track_order=list(effective_track_order),
            cancel_event=cancel_event,
            waveform_width=max(
                480,
                int(self.wave.width() if hasattr(self, "wave") else 480),
            ),
            cache_budget_bytes=int(self.PRELOAD_CACHE_BUDGET_BYTES),
            prepared_media=prepared_media,
        )
        future = executor.submit(_build_audio_preview_track_load, task)
        self._audio_load_jobs[int(request_id)] = (future, cancel_event)
        self._log_audio_preload(
            "load-start",
            request_id=int(request_id),
            track_id=int(track_id),
            source_key=source_key,
            cached=prepared_media is not None,
        )

        def _done(done_future: Future, *, bridge=self._audio_preload_bridge) -> None:
            try:
                result = done_future.result()
            except Exception as exc:
                result = _AudioPreviewTrackLoadResult(
                    request_id=int(request_id),
                    track_id=int(track_id),
                    source_key=source_key,
                    error=str(exc),
                )
            try:
                bridge.track_ready.emit(result)
            except RuntimeError:
                if (
                    isinstance(result, _AudioPreviewTrackLoadResult)
                    and result.prepared_owned_by_result
                    and isinstance(result.state, dict)
                ):
                    prepared = result.state.get("prepared_media")
                    if isinstance(prepared, _AudioPreviewPreparedMedia):
                        prepared.dispose()

        future.add_done_callback(_done)

    def _cancel_audio_load_jobs(self, *, reason: str) -> None:
        had_jobs = bool(self._audio_load_jobs)
        for request_id, (future, cancel_event) in list(self._audio_load_jobs.items()):
            cancel_event.set()
            future.cancel()
            self._audio_load_jobs.pop(request_id, None)
            self._log_audio_preload(
                "load-cancel",
                request_id=request_id,
                reason=reason,
            )
        if had_jobs:
            self._audio_load_request_id += 1

    def open_track_preview(self, track_id: int, source_spec: dict[str, object], *, autoplay: bool):
        normalized_track_id = int(track_id)
        normalized_source_spec = dict(source_spec or {})
        base_track_order = self._track_order_for_load_request(
            normalized_track_id,
            normalized_source_spec,
        )
        effective_track_order = self._effective_track_order_for_load_request(
            normalized_track_id,
            normalized_source_spec,
            base_track_order,
        )
        prepared = self._cached_prepared_media_for(normalized_track_id, normalized_source_spec)
        if self._apply_cached_track_preview(
            normalized_track_id,
            normalized_source_spec,
            base_track_order,
            effective_track_order,
            prepared,
            autoplay=autoplay,
        ):
            return
        if self._use_inflight_preload_for_track(
            normalized_track_id,
            normalized_source_spec,
            base_track_order,
            effective_track_order,
            autoplay=autoplay,
        ):
            return
        self._cancel_audio_load_jobs(reason="new-track")
        self._audio_load_waiting_for_preload = None
        self._audio_load_request_id += 1
        request_id = int(self._audio_load_request_id)
        self._cancel_audio_preload_jobs(reason="active-track-load")
        self._begin_track_load(
            normalized_track_id,
            normalized_source_spec,
            base_track_order,
            effective_track_order,
        )
        self._submit_audio_track_load(
            request_id,
            normalized_track_id,
            normalized_source_spec,
            base_track_order,
            effective_track_order,
            prepared,
            autoplay,
        )

    def open_raw_preview(self, data: bytes, mime: str, title: str, *, autoplay: bool):
        self._cancel_audio_load_jobs(reason="raw-preview")
        self._cancel_audio_preload_jobs(reason="raw-preview")
        self._evict_audio_preload_cache(set(), reason="raw-preview")
        self._audio_load_waiting_for_preload = None
        state = self.app._audio_preview_state_for_raw_bytes(
            data,
            mime,
            title,
            parent_widget=self,
        )
        self._apply_preview_state(state, source_spec=None, autoplay=autoplay)

    def _current_track_id_as_int(self) -> int | None:
        try:
            return int(self._current_track_id)
        except TypeError, ValueError:
            return None

    def _create_shuffled_track_order(
        self,
        track_order: list[int],
        current_track_id: int | None,
    ) -> list[int]:
        normalized: list[int] = []
        seen: set[int] = set()
        for track_id in track_order:
            try:
                normalized_id = int(track_id)
            except TypeError, ValueError:
                continue
            if normalized_id in seen:
                continue
            normalized.append(normalized_id)
            seen.add(normalized_id)
        if len(normalized) <= 1:
            return normalized
        remainder = [track_id for track_id in normalized if track_id != current_track_id]
        random.shuffle(remainder)
        if current_track_id in seen:
            return [int(current_track_id), *remainder]
        return remainder

    def _shuffle_order_for_base_track_order(self, track_order: list[int]) -> list[int]:
        normalized: list[int] = []
        for track_id in track_order:
            try:
                normalized.append(int(track_id))
            except TypeError, ValueError:
                continue
        normalized_set = set(normalized)
        existing: list[int] = []
        for track_id in self._shuffled_track_order:
            try:
                normalized_id = int(track_id)
            except TypeError, ValueError:
                continue
            if normalized_id in normalized_set:
                existing.append(normalized_id)
        if len(existing) == len(normalized) and set(existing) == set(normalized):
            return existing
        self._shuffled_track_order = self._create_shuffled_track_order(
            normalized,
            self._current_track_id_as_int(),
        )
        return list(self._shuffled_track_order)

    def _apply_effective_track_order(self) -> None:
        base_track_order = self._effective_base_track_order()
        if self._shuffle_enabled:
            self._track_order = self._shuffle_order_for_base_track_order(base_track_order)
        else:
            self._track_order = list(base_track_order)
            self._shuffled_track_order = []
        self._set_play_next_items(self._ordered_track_queue_items(self._track_order))
        self._sync_album_scope_button()

    def _set_shuffle_enabled(self, enabled: bool) -> None:
        self._shuffle_enabled = bool(enabled)
        if self._shuffle_enabled:
            self._shuffled_track_order = self._create_shuffled_track_order(
                self._effective_base_track_order() or self._track_order,
                self._current_track_id_as_int(),
            )
        self._apply_effective_track_order()
        self._sync_shuffle_button()
        self._update_navigation_buttons()
        self._refresh_audio_preload_window_if_ready()

    def _apply_preview_state(
        self,
        state: dict[str, object],
        *,
        source_spec: dict[str, object] | None,
        autoplay: bool,
    ) -> None:
        self._source_spec = source_spec
        self._current_track_id = state.get("track_id")
        self._reload_current_bookmarks()
        self._base_track_order = list(state.get("track_order") or [])
        self._base_track_queue = list(state.get("track_queue") or [])
        effective_track_order = self.app._normalize_track_ids(
            state.get("effective_track_order") or []
        )
        if effective_track_order:
            self._track_order = effective_track_order
            self._set_play_next_items(
                list(state.get("effective_track_queue") or [])
                or self._ordered_track_queue_items(self._track_order)
            )
            self._sync_album_scope_button()
        else:
            self._apply_effective_track_order()
        prepared_media = state.get("prepared_media")
        if isinstance(prepared_media, _AudioPreviewPreparedMedia):
            prepared_media.preview_state = None
        self._current_audio_bytes = bytes(state.get("audio_bytes") or b"")
        self._current_audio_mime = str(state.get("audio_mime") or "audio/wav")
        self._current_title = str(state.get("title") or "Audio Player").strip() or "Audio Player"
        self._current_artist = str(state.get("artist") or "").strip()
        self._current_album = str(state.get("album") or "").strip()
        if self._album_scope_title:
            current_track_id = self._current_track_id_as_int()
            scoped_track_ids = self._album_track_order_for_title(self._album_scope_title)
            if current_track_id is not None and current_track_id not in scoped_track_ids:
                self._album_scope_title = self._current_album or None
        self.title_label.setText(self._current_title)
        self.artist_label.setVisible(bool(self._current_artist))
        self.artist_label.setText(self._current_artist)
        self.album_label.setVisible(bool(self._current_album))
        self.album_label.setText(f"Album · {self._current_album}" if self._current_album else "")
        self.setWindowTitle(
            str(state.get("window_title") or f"Audio Player — {self._current_title}")
        )
        self._set_export_actions(list(state.get("export_actions") or []))
        self._apply_artwork(state.get("artwork_payload"))
        self._load_audio_source(
            self._current_audio_bytes,
            self._current_audio_mime,
            prepared_media=prepared_media,
        )
        self._promote_current_audio_to_preload_cache(prepared_media)
        self._refresh_audio_preload_window()
        self._update_navigation_buttons()
        if autoplay:
            QTimer.singleShot(0, lambda: self._player.play())

    def _load_audio_source(
        self,
        data: bytes,
        mime: str,
        *,
        prepared_media: object | None = None,
    ) -> None:
        self._reset_player_source()
        self._cleanup_temp_file()
        self.peak_meter.reset_signal_activity()
        if isinstance(prepared_media, _AudioPreviewPreparedMedia):
            self._tmp_path = prepared_media.source_path
            self._source_tmp_path = None
            self._tmp_path_owned = bool(prepared_media.owns_source_path)
            if self._tmp_path_owned:
                prepared_media.owns_source_path = False
            if prepared_media.decoded_samples is None or prepared_media.sample_rate <= 0:
                raise RuntimeError("Audio was not prepared by the background loader.")
            self._player.setDecodedSource(
                prepared_media.decoded_samples,
                int(prepared_media.sample_rate),
                assume_prepared=True,
            )
            prepared_media.decoded_samples = None
            self._load_waveform(self._tmp_path, prepared_media=prepared_media)
            self._apply_position(0, self._player.duration())
            return
        ext = {
            "audio/mpeg": ".mp3",
            "audio/wav": ".wav",
            "audio/ogg": ".ogg",
            "audio/opus": ".opus",
            "audio/flac": ".flac",
            "audio/aiff": ".aiff",
            "audio/x-aiff": ".aiff",
        }.get(str(mime or "").strip().lower(), ".bin")
        try:
            handle = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
            handle.write(data)
            handle.flush()
            handle.close()
            self._source_tmp_path = handle.name
            self._tmp_path_owned = True
        except Exception as exc:
            raise RuntimeError(f"Could not create preview temp file: {exc}") from exc
        self._tmp_path = self._source_tmp_path
        self._player.setSource(QUrl.fromLocalFile(self._tmp_path))
        self._load_waveform(self._tmp_path)
        self._apply_position(0, self._player.duration())

    def _promote_current_audio_to_preload_cache(self, prepared_media: object | None) -> None:
        del prepared_media
        return

    def _refresh_audio_preload_window(self) -> None:
        self._audio_preload_generation += 1
        self._cancel_audio_preload_jobs(reason="disabled")
        self._evict_audio_preload_cache(set(), reason="disabled")
        self._log_audio_preload(
            "disabled",
            generation=int(self._audio_preload_generation),
        )

    def _refresh_audio_preload_window_if_ready(self) -> None:
        return

    def _submit_audio_preload(
        self,
        track_id: int,
        source_spec: dict[str, object],
        generation: int,
    ) -> None:
        del track_id, source_spec, generation
        return

    def _on_audio_preload_result(self, result: object) -> None:
        if not isinstance(result, _AudioPreviewPreloadResult):
            return
        key = (int(result.track_id), str(result.source_key))
        self._audio_preload_jobs.pop(key, None)
        prepared = result.prepared
        if isinstance(prepared, _AudioPreviewPreparedMedia):
            prepared.dispose()
        self._log_audio_preload(
            "ignored",
            track_id=result.track_id,
            source_key=result.source_key,
            reason="disabled",
        )
        return

    def _dispose_track_load_result_media(self, result: _AudioPreviewTrackLoadResult) -> None:
        if not result.prepared_owned_by_result or not isinstance(result.state, dict):
            return
        prepared = result.state.get("prepared_media")
        if not isinstance(prepared, _AudioPreviewPreparedMedia):
            return
        key = (int(prepared.track_id), str(prepared.source_key))
        if self._audio_preload_cache.get(key) is prepared:
            return
        prepared.dispose()

    def _on_audio_track_load_result(self, result: object) -> None:
        if not isinstance(result, _AudioPreviewTrackLoadResult):
            return
        self._audio_load_jobs.pop(int(result.request_id), None)
        current_key = self._audio_preload_key(result.track_id, self._source_spec)
        if result.cancelled:
            self._log_audio_preload(
                "load-cancelled",
                request_id=result.request_id,
                track_id=result.track_id,
                source_key=result.source_key,
            )
            return
        if (
            int(result.request_id) != int(self._audio_load_request_id)
            or int(result.track_id) != self._current_track_id_as_int()
            or str(result.source_key) != str(current_key[1])
        ):
            self._dispose_track_load_result_media(result)
            self._log_audio_preload(
                "load-stale",
                request_id=result.request_id,
                active_request_id=self._audio_load_request_id,
                track_id=result.track_id,
                source_key=result.source_key,
            )
            return
        if result.error:
            self._log_audio_preload(
                "load-failed",
                request_id=result.request_id,
                track_id=result.track_id,
                source_key=result.source_key,
                error=result.error,
            )
            self.wave.setVisible(False)
            self.wave_status_label.setText("Could not load audio")
            self.wave_status_label.setVisible(True)
            QMessageBox.critical(
                self,
                "Audio Player",
                f"Could not load the selected track:\n{result.error}",
            )
            return
        if not isinstance(result.state, dict):
            return

        state = dict(result.state)
        state["export_actions"] = self.app._audio_preview_export_actions_for_track(
            int(result.track_id),
            self._source_spec,
            parent_widget=self,
            title_override=str(state.get("title") or ""),
        )
        self._log_audio_preload(
            "load-ready",
            request_id=result.request_id,
            track_id=result.track_id,
            source_key=result.source_key,
            cached=not result.prepared_owned_by_result,
        )
        autoplay = bool(state.pop("_autoplay", False))
        try:
            self._apply_preview_state(state, source_spec=self._source_spec, autoplay=autoplay)
        except Exception as exc:
            self._dispose_track_load_result_media(result)
            self._log_audio_preload(
                "load-apply-failed",
                request_id=result.request_id,
                track_id=result.track_id,
                source_key=result.source_key,
                error=str(exc),
            )
            QMessageBox.critical(
                self,
                "Audio Player",
                f"Could not open the selected track:\n{exc}",
            )

    def _cancel_audio_preload_jobs(
        self,
        *,
        keep_keys: set[tuple[int, str]] | None = None,
        reason: str,
    ) -> None:
        keep = keep_keys or set()
        for key, (future, cancel_event, generation) in list(self._audio_preload_jobs.items()):
            if key in keep:
                continue
            cancel_event.set()
            future.cancel()
            self._audio_preload_jobs.pop(key, None)
            self._log_audio_preload(
                "cancel",
                track_id=key[0],
                source_key=key[1],
                generation=generation,
                reason=reason,
            )

    def _evict_audio_preload_cache(
        self,
        keep_keys: set[tuple[int, str]],
        *,
        reason: str,
    ) -> None:
        for key, prepared in list(self._audio_preload_cache.items()):
            if key in keep_keys:
                continue
            self._audio_preload_cache.pop(key, None)
            prepared.dispose()
            self._log_audio_preload(
                "evict",
                track_id=key[0],
                source_key=key[1],
                reason=reason,
            )

    def _enforce_audio_preload_budget(self, window_keys: set[tuple[int, str]]) -> None:
        budget = max(1, int(self.PRELOAD_CACHE_BUDGET_BYTES))
        total = sum(prepared.memory_cost() for prepared in self._audio_preload_cache.values())
        if total <= budget:
            return
        protected_keys = self._audio_preload_required_keys()
        priority: dict[tuple[int, str], int] = {}
        window_order = self._audio_preload_window_keys()
        for index, key in enumerate(window_order):
            priority[key] = index
        for key, prepared in sorted(
            list(self._audio_preload_cache.items()),
            key=lambda item: (priority.get(item[0], 99), -item[1].created_at),
            reverse=True,
        ):
            if total <= budget:
                break
            if key in protected_keys:
                continue
            self._audio_preload_cache.pop(key, None)
            total -= prepared.memory_cost()
            prepared.dispose()
            self._log_audio_preload(
                "evict",
                track_id=key[0],
                source_key=key[1],
                reason="budget",
                total_bytes=total,
                budget_bytes=budget,
            )

    @staticmethod
    def _remove_temp_path(path: str | None) -> None:
        if not path:
            return
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        except Exception:
            pass

    def _load_waveform(
        self,
        path: str,
        *,
        prepared_media: _AudioPreviewPreparedMedia | None = None,
    ) -> None:
        self._load_waveform_peaks(path, prepared_media=prepared_media)
        if prepared_media is not None:
            spectrum_frames = list(prepared_media.spectrum_frames)
        else:
            spectrum_frames = load_audio_spectrum_frames(path)
        if prepared_media is not None:
            peak_frames = list(prepared_media.peak_frames)
        else:
            peak_frames = load_audio_peak_meter_frames(path)
        self.scope.set_spectrum_frames(spectrum_frames)
        self.peak_meter.set_peak_frames(peak_frames)
        self._start_scope_visualization_if_playing()

    def _load_waveform_peaks(
        self,
        path: str,
        *,
        prepared_media: _AudioPreviewPreparedMedia | None = None,
    ) -> None:
        cached = None
        prepared_peaks = list(prepared_media.waveform_peaks or []) if prepared_media else []
        source_spec = self._source_spec if isinstance(self._source_spec, dict) else {}
        if prepared_media is not None:
            peaks = prepared_peaks
            self.wave.set_peaks(peaks)
        elif (
            self._current_track_id is not None
            and str(source_spec.get("kind") or "").strip().lower() == "standard"
            and str(source_spec.get("media_key") or "audio_file").strip() == "audio_file"
        ):
            cache_loader = getattr(self.app, "_audio_waveform_cache_for_track", None)
            if callable(cache_loader):
                cached = cache_loader(int(self._current_track_id))
        if prepared_media is None and cached is not None:
            peaks = list(getattr(cached, "peaks", []) or [])
            self.wave.set_cached_waveform(
                peaks,
                light_preview_png=getattr(cached, "light_preview_png", None),
                dark_preview_png=getattr(cached, "dark_preview_png", None),
                cache_key=getattr(cached, "source_fingerprint", None),
            )
        elif prepared_media is None:
            peaks = load_wav_peaks(path, max(self.wave.width(), 480))
            self.wave.set_peaks(peaks)
        has_peaks = bool(peaks)
        self.wave.setVisible(has_peaks)
        if not has_peaks:
            self.wave_status_label.setText("Waveform unavailable")
        self.wave_status_label.setVisible(not has_peaks)

    def _reload_peaks_for_current_width(self) -> None:
        if not self._tmp_path:
            return
        self._load_waveform_peaks(self._tmp_path)
        self._start_scope_visualization_if_playing()
        self.scope.update()
        self._refresh_artwork_pixmap()

    def _set_export_actions(self, actions: list[dict[str, object]]) -> None:
        self.export_menu.clear()
        for spec in actions:
            text = str(spec.get("text") or "").strip()
            handler = spec.get("handler")
            if not text or not callable(handler):
                continue
            action = self.export_menu.addAction(text)
            action.triggered.connect(handler)
        self._set_media_button_enabled(self.export_button, bool(self.export_menu.actions()))

    def _open_artwork_preview(self) -> None:
        if not self._current_artwork_data:
            return
        opener = getattr(self.app, "_open_image_preview", None)
        if callable(opener):
            opener(bytes(self._current_artwork_data), self._current_title or "Album Art")

    def _create_artwork_context_menu(self) -> QMenu:
        menu = QMenu(self)
        if self._current_artwork_data:
            view_action = menu.addAction("View Album Art")
            view_action.triggered.connect(self._open_artwork_preview)
        return menu

    def _show_artwork_context_menu(self, pos: QPoint) -> None:
        if not self._current_artwork_data:
            return
        source = self.sender()
        menu = self._create_artwork_context_menu()
        if not menu.actions():
            return
        if isinstance(source, QWidget):
            global_pos = source.mapToGlobal(pos)
        else:
            global_pos = QCursor.pos()
        menu.exec(global_pos)

    def _sync_volume_controls(self) -> None:
        percent = max(0, min(100, int(round(float(self._audio_out.volume()) * 100))))
        self.volume_slider.blockSignals(True)
        self.volume_slider.setValue(percent)
        self.volume_slider.blockSignals(False)
        self.volume_label.setText(f"{percent}%")
        self._sync_peak_meter_gain()

    def _sync_mute_button(self, *_args) -> None:
        muted = bool(self._audio_out.isMuted())
        self.mute_button.blockSignals(True)
        self.mute_button.setChecked(muted)
        self.mute_button.blockSignals(False)
        self._set_icon_button_content(
            self.mute_button,
            "volume-mute" if muted else "volume-up",
            "Mute" if muted else "Vol",
        )
        self.mute_button.setToolTip("Unmute" if muted else "Mute")
        self.mute_button.setAccessibleName("Unmute" if muted else "Mute")
        self._sync_peak_meter_gain()

    def _set_volume_percent(self, value: int) -> None:
        percent = max(0, min(100, int(value)))
        self._audio_out.setVolume(percent / 100.0)
        self.volume_label.setText(f"{percent}%")
        self._sync_peak_meter_gain()

    def _set_muted(self, muted: bool) -> None:
        self._audio_out.setMuted(bool(muted))
        self._sync_mute_button()

    def _effective_output_gain(self) -> float:
        muted = bool(self._audio_out.isMuted())
        if muted:
            return 0.0
        return max(0.0, min(1.0, float(self._audio_out.volume())))

    def _sync_peak_meter_gain(self) -> None:
        if not hasattr(self, "peak_meter"):
            return
        gain = self._effective_output_gain()
        previous_gain = max(0.0, float(getattr(self, "_visualization_gain", gain)))
        playing = self._is_media_playing()
        if playing and previous_gain > 0.0 and gain <= 0.0:
            self._begin_visualization_release()
        self._visualization_gain = gain
        self.peak_meter.set_gain(gain)
        if hasattr(self, "scope"):
            self.scope.set_gain(gain, cancel_release=playing)
        if not playing:
            return
        if gain > 0.0:
            self._start_scope_visualization_if_playing()
            if not self._visualization_timer.isActive():
                self._visualization_timer.start()
            return
        if self.peak_meter.is_releasing() or self.scope.is_releasing():
            if not self._visualization_timer.isActive():
                self._visualization_timer.start()
        elif self._visualization_timer.isActive():
            self._visualization_timer.stop()

    def _apply_artwork(self, artwork_payload) -> None:
        self._artwork_pixmap = QPixmap()
        self._current_artwork_data = b""
        self._current_artwork_mime = "image/png"
        data = getattr(artwork_payload, "data", b"") if artwork_payload is not None else b""
        if data:
            image = QImage.fromData(data)
            if not image.isNull():
                self._current_artwork_data = bytes(data)
                self._current_artwork_mime = (
                    str(getattr(artwork_payload, "mime_type", "") or "").strip() or "image/png"
                )
                self._artwork_pixmap = QPixmap.fromImage(image)
        has_artwork = not self._artwork_pixmap.isNull()
        self.artwork_container.setVisible(has_artwork)
        self._sync_media_stage_size()
        self._refresh_artwork_pixmap()

    def _refresh_artwork_pixmap(self) -> None:
        if self._artwork_pixmap.isNull():
            self.artwork_label.clear()
            return
        target = self.artwork_label.size()
        device_pixel_ratio = self._artwork_target_device_pixel_ratio()
        pixel_target = QSize(
            max(1, int(round(target.width() * device_pixel_ratio))),
            max(1, int(round(target.height() * device_pixel_ratio))),
        )
        scaled = self._artwork_pixmap.scaled(
            pixel_target,
            Qt.KeepAspectRatioByExpanding,
            Qt.SmoothTransformation,
        )
        scaled.setDevicePixelRatio(device_pixel_ratio)
        self.artwork_label.set_artwork_pixmap(scaled)

    def _artwork_target_device_pixel_ratio(self) -> float:
        ratio = 1.0
        try:
            ratio = max(ratio, float(self.artwork_label.devicePixelRatioF()))
        except Exception:
            pass
        try:
            handle = self.windowHandle()
            screen = handle.screen() if handle is not None else self.screen()
            if screen is not None:
                ratio = max(ratio, float(screen.devicePixelRatio()))
        except Exception:
            pass
        return max(1.0, ratio)

    def _toggle_play_pause(self) -> None:
        playing_state = getattr(QMediaPlayer, "PlaybackState", QMediaPlayer).PlayingState
        if self._player.playbackState() == playing_state:
            self._player.pause()
        else:
            self._player.play()

    def _stop_playback(self) -> None:
        self._ensure_visualization_release_running()
        self._player.stop()
        self._seek_to_ms(0)
        self._ensure_visualization_release_running()

    def _jump_by_ms(self, delta_ms: int) -> None:
        self._seek_to_ms(self._player.position() + int(delta_ms))

    def _scrub_by_ms(self, delta_ms: int) -> None:
        self._jump_by_ms(delta_ms)

    def _seek_to_ms(self, position_ms: int) -> None:
        duration = max(0, int(self._player.duration() or 0))
        clamped = max(0, min(int(position_ms), duration if duration else int(position_ms)))
        self._player.setPosition(clamped)
        self._apply_position(clamped, duration)

    def _on_duration_changed(self, duration: int) -> None:
        self._slider.setRange(0, max(0, int(duration)))
        self.wave.set_duration_ms(duration)
        self.scope.set_duration_ms(duration)
        self.peak_meter.set_duration_ms(duration)
        self._apply_position(self._player.position(), duration)

    def _on_position_changed(self, position: int) -> None:
        self._apply_position(position, self._player.duration())

    def _apply_position(self, position: int, duration: int) -> None:
        if not self._slider.isSliderDown():
            self._slider.blockSignals(True)
            self._slider.setValue(max(0, int(position)))
            self._slider.blockSignals(False)
        self._sync_peak_meter_gain()
        self.wave.set_duration_ms(duration)
        self.wave.set_playhead_ms(position)
        self.scope.set_duration_ms(duration)
        self.scope.set_playhead_ms(position)
        self.peak_meter.set_duration_ms(duration)
        self.peak_meter.set_playhead_ms(position)
        self._label_time.setText(f"{self._format_time(position)} / {self._format_time(duration)}")

    def _refresh_live_visualization(self) -> None:
        if self._is_media_playing():
            self._apply_position(self._player.position(), self._player.duration())
            if self._effective_output_gain() > 0.0:
                self._start_scope_visualization_if_playing()
                return
            if not self._advance_visualization_release():
                self._visualization_timer.stop()
            return
        if not self._advance_visualization_release():
            self._visualization_timer.stop()

    def _is_media_playing(self) -> bool:
        playing_state = getattr(QMediaPlayer, "PlaybackState", QMediaPlayer).PlayingState
        return self._player.playbackState() == playing_state

    def _start_scope_visualization_if_playing(self) -> None:
        if self._is_media_playing() and self._effective_output_gain() > 0.0:
            self.peak_meter.mark_signal_activity()
            self.scope.start_fade_in()

    def _begin_visualization_release(self) -> None:
        if hasattr(self, "peak_meter"):
            self.peak_meter.begin_release()
        if hasattr(self, "scope"):
            self.scope.start_release()

    def _ensure_visualization_release_running(self) -> bool:
        self._begin_visualization_release()
        active = False
        if hasattr(self, "peak_meter"):
            active = bool(self.peak_meter.is_releasing()) or active
        if hasattr(self, "scope"):
            active = bool(self.scope.is_releasing()) or active
        if active:
            if not self._visualization_timer.isActive():
                self._visualization_timer.start()
            return True
        if self._visualization_timer.isActive():
            self._visualization_timer.stop()
        return False

    def _advance_visualization_release(self) -> bool:
        active = False
        if hasattr(self, "peak_meter"):
            active = bool(self.peak_meter.advance_release(self.VISUALIZATION_TIMER_MS)) or active
        if hasattr(self, "scope"):
            active = bool(self.scope.advance_release(self.VISUALIZATION_TIMER_MS)) or active
        return active

    def _sync_visualization_timer(self, *_args) -> None:
        if self._is_media_playing():
            if self._effective_output_gain() > 0.0:
                self._start_scope_visualization_if_playing()
                if not self._visualization_timer.isActive():
                    self._visualization_timer.start()
                return
            self._ensure_visualization_release_running()
            return
        self._ensure_visualization_release_running()

    @staticmethod
    def _format_time(ms: int) -> str:
        total_seconds = max(0, int(ms or 0) // 1000)
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes}:{seconds:02d}"

    def _track_index(self) -> int:
        if self._current_track_id in self._track_order:
            return self._track_order.index(self._current_track_id)
        return -1

    def _update_navigation_buttons(self) -> None:
        index = self._track_index()
        can_wrap_playlist = (
            self._loop_mode == self.LOOP_MODE_PLAYLIST and index >= 0 and len(self._track_order) > 1
        )
        self._set_media_button_enabled(self.previous_button, can_wrap_playlist or index > 0)
        self._set_media_button_enabled(
            self.next_button,
            can_wrap_playlist or 0 <= index < len(self._track_order) - 1,
        )
        self._sync_play_next_selection()

    def _navigate_relative(self, offset: int, *, autoplay: bool, wrap: bool = False) -> bool:
        if self._source_spec is None:
            return False
        index = self._track_index()
        if index < 0:
            return False
        target_index = index + int(offset)
        if wrap and self._track_order:
            target_index %= len(self._track_order)
        elif target_index < 0 or target_index >= len(self._track_order):
            return False
        if target_index == index:
            return False
        target_track_id = int(self._track_order[target_index])
        self.open_track_preview(target_track_id, self._source_spec, autoplay=autoplay)
        return True

    def _go_to_previous_track(self) -> None:
        self._navigate_relative(
            -1,
            autoplay=True,
            wrap=self._loop_mode == self.LOOP_MODE_PLAYLIST,
        )

    def _go_to_next_track(self) -> None:
        self._navigate_relative(
            1,
            autoplay=True,
            wrap=self._loop_mode == self.LOOP_MODE_PLAYLIST,
        )

    def _on_media_status_changed(self, status) -> None:
        end_status = getattr(QMediaPlayer, "MediaStatus", QMediaPlayer).EndOfMedia
        if status != end_status or self._handling_end_of_media:
            return
        self._handling_end_of_media = True
        try:
            continued_playback = False
            self._apply_position(self._player.duration(), self._player.duration())
            if self._loop_mode == self.LOOP_MODE_TRACK:
                self._restart_current_media()
                continued_playback = True
            elif self._loop_mode == self.LOOP_MODE_PLAYLIST:
                continued_playback = self._navigate_relative(1, autoplay=True, wrap=True)
                if not continued_playback:
                    self._restart_current_media()
                    continued_playback = True
            elif self._auto_advance_enabled():
                continued_playback = self._navigate_relative(1, autoplay=True)
            if not continued_playback:
                self._ensure_visualization_release_running()
        finally:
            self._handling_end_of_media = False

    def _restart_current_media(self) -> None:
        self.peak_meter.reset_signal_activity()
        self._seek_to_ms(0)
        self._player.play()

    def _reset_player_source(self) -> None:
        try:
            self._player.stop()
        except Exception:
            pass
        try:
            self._audio_out.stop()
        except Exception:
            pass
        try:
            self._player.setSource(QUrl())
        except Exception:
            pass

    def _cleanup_temp_file(self) -> None:
        seen: set[str] = set()
        owned_paths = []
        if bool(getattr(self, "_tmp_path_owned", False)):
            owned_paths.append(getattr(self, "_tmp_path", None))
        owned_paths.append(getattr(self, "_source_tmp_path", None))
        for path in owned_paths:
            if not path or path in seen:
                continue
            seen.add(path)
            self._remove_temp_path(path)
        self._tmp_path = None
        self._source_tmp_path = None
        self._tmp_path_owned = False

    def closeEvent(self, event):
        self._visualization_timer.stop()
        self._cancel_audio_load_jobs(reason="dialog-close")
        self._cancel_audio_preload_jobs(reason="dialog-close")
        self._reset_player_source()
        self._cleanup_temp_file()
        self._evict_audio_preload_cache(set(), reason="dialog-close")
        for executor_name in ("_audio_load_executor", "_audio_preload_executor"):
            executor = getattr(self, executor_name, None)
            if executor is None:
                continue
            try:
                executor.shutdown(wait=False, cancel_futures=True)
            except TypeError:
                executor.shutdown(wait=False)
            except Exception:
                pass
            setattr(self, executor_name, None)
        self._audio_preload_executor = None
        super().closeEvent(event)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.FontChange, QEvent.ApplicationFontChange):
            self._apply_stop_button_font()
            self._apply_play_next_font()
        if event.type() in (
            QEvent.PaletteChange,
            QEvent.ApplicationPaletteChange,
            QEvent.StyleChange,
        ):
            self._media_icon_cache.clear()
            self._refresh_media_button_icons()
        elif event.type() == QEvent.WindowStateChange:
            QTimer.singleShot(0, self._resume_scope_visualization_after_window_state_change)

    def _resume_scope_visualization_after_window_state_change(self) -> None:
        self._start_scope_visualization_if_playing()
        if hasattr(self, "scope"):
            self.scope.update()

    def showEvent(self, event):
        super().showEvent(event)
        self._apply_stop_button_font()
        self._refresh_media_button_icons()
        QTimer.singleShot(0, lambda: self._apply_stop_button_font())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_media_stage_size()
        self._resize_timer.start()


# =============================================================================
# Application Startup (Settings bootstrap + Single-instance enforcement)
# =============================================================================

__all__ = [
    "_ImagePreviewDialog",
    "_HiDpiArtworkLabel",
    "_AudioPreviewPreloadBridge",
    "_AudioPreviewPreloadCancelled",
    "_AudioPreviewPreparedMedia",
    "_AudioPreviewPreloadTask",
    "_AudioPreviewPreloadResult",
    "_AudioPreviewTrackLoadTask",
    "_AudioPreviewTrackLoadResult",
    "_audio_preview_detect_mime_from_bytes",
    "_audio_preview_suffix_for_mime",
    "_audio_preview_fetch_source_for_preload",
    "_audio_preview_write_preload_temp_file",
    "_audio_preview_artwork_payload_for_snapshot",
    "_audio_preview_track_queue_items_for_service",
    "_audio_preview_state_for_preload_task",
    "_build_audio_preview_preload",
    "_build_audio_preview_track_load",
]

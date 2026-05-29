"""Media player and preview-opening orchestration for the application shell."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QColor, QFontMetrics, QIcon, QImage, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import QDialog, QMessageBox

from isrc_manager.media.preview_dialogs import (
    _AudioPreviewDialog,
    _AudioPreviewPreparedMedia,
    _ImagePreviewDialog,
)
from isrc_manager.paths import RES_DIR

MEDIA_PLAYER_ACTION_ICON_SCALE = 0.45


def _root_attr(name: str, fallback):
    main_window_module = sys.modules.get("isrc_manager.main_window")
    return (
        getattr(main_window_module, name, fallback) if main_window_module is not None else fallback
    )


def _message_box():
    return _root_attr("QMessageBox", QMessageBox)


def _media_player_icon_path(self) -> Path:
    return RES_DIR() / "icons" / "music-player-fill.svg"


def _text_scaled_icon_extent(self, font=None) -> int:
    metrics = QFontMetrics(font or self.font())
    return max(8, min(10, int(round(metrics.height() * 0.45))))


def _tinted_icon_pixmap(source: QPixmap, color: QColor, *, glyph_scale: float = 1.0) -> QPixmap:
    result = QPixmap(source.size())
    result.setDevicePixelRatio(source.devicePixelRatioF())
    result.fill(Qt.transparent)
    painter = QPainter(result)
    try:
        logical_size = source.deviceIndependentSize()
        scale = max(0.1, min(1.0, float(glyph_scale)))
        draw_size = QSize(
            max(1, int(round(logical_size.width() * scale))),
            max(1, int(round(logical_size.height() * scale))),
        )
        draw_rect = QRect(QPoint(0, 0), draw_size)
        draw_rect.moveCenter(QRect(QPoint(0, 0), logical_size.toSize()).center())
        painter.drawPixmap(draw_rect, source)
        painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
        painter.fillRect(result.rect(), color)
    finally:
        painter.end()
    return result


def _media_player_action_icon(self) -> QIcon:
    icon_path = self._media_player_icon_path()
    if not icon_path.exists():
        return QIcon()
    source_icon = QIcon(str(icon_path))
    if source_icon.isNull():
        return QIcon()

    icon_color = QColor(self.palette().color(QPalette.ButtonText))
    if not icon_color.isValid():
        icon_color = QColor(self.palette().color(QPalette.WindowText))
    if not icon_color.isValid():
        icon_color = QColor("#111827")

    tinted_icon = QIcon()
    for extent in (10, 12, 14, 16):
        pixmap = source_icon.pixmap(QSize(extent, extent))
        if pixmap.isNull():
            continue
        tinted_icon.addPixmap(
            self._tinted_icon_pixmap(
                pixmap,
                icon_color,
                glyph_scale=MEDIA_PLAYER_ACTION_ICON_SCALE,
            )
        )
    return tinted_icon if not tinted_icon.isNull() else source_icon


def _configure_media_player_action_icon(self) -> None:
    action = getattr(self, "media_player_action", None)
    if action is None:
        return
    action.setIcon(self._media_player_action_icon())
    action.setIconVisibleInMenu(True)


def _preview_blob_bytes(self, data, title: str) -> None:
    # Unwrap tuple returns: (bytes|memoryview, optional_mime)
    provided_mime = ""
    if isinstance(data, tuple):
        if len(data) >= 1:
            data_bytes = data[0]
        if len(data) >= 2 and isinstance(data[1], str):
            provided_mime = data[1]
        data = data_bytes
    if isinstance(data, memoryview):
        data = data.tobytes()

    # Prefer provided MIME if present and plausible
    mime = provided_mime.lower().strip() if provided_mime else ""
    if not (mime.startswith("audio/") or mime.startswith("image/")):
        mime = (self._detect_mime(data) or "").lower()

    # Try image decode first regardless of mime: cheap and robust
    try:
        img = QImage.fromData(data)
        if not img.isNull():
            self._open_image_preview(data, title)
            return
    except Exception:
        pass

    # Audio path if mime says audio, otherwise try common audio fallback
    audio_mime = mime if mime.startswith("audio/") else ""
    if not audio_mime:
        # Heuristic: raw looks not like image and not empty -> try wav
        audio_mime = "audio/wav"

    self._open_audio_preview(data, audio_mime, title)


def _detect_mime(self, b: bytes) -> str:
    # --- images ---
    if len(b) >= 8 and b[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if len(b) >= 2 and b[:2] == b"\xff\xd8":
        return "image/jpeg"
    if len(b) >= 6 and b[:6] in (b"GIF89a", b"GIF87a"):
        return "image/gif"
    if len(b) >= 12 and b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "image/webp"

    # --- audio ---
    if len(b) >= 12 and b[:4] == b"RIFF" and b[8:12] == b"WAVE":
        return "audio/wav"
    if len(b) >= 4 and b[:4] == b"fLaC":
        return "audio/flac"
    if len(b) >= 4 and b[:4] == b"OggS":
        if b"OpusHead" in b[:64]:
            return "audio/opus"
        return "audio/ogg"
    # MP3: ID3 header or MPEG frame sync (common cases)
    if len(b) >= 3 and b[:3] == b"ID3":
        return "audio/mpeg"
    if len(b) >= 2 and (b[0] == 0xFF and (b[1] & 0xE0) == 0xE0):
        return "audio/mpeg"

    return ""


def _bring_media_window_to_front(self, window: QDialog | None) -> None:
    if window is None:
        return
    try:
        if window.parentWidget() is not None:
            window.setParent(None, window.windowFlags() | Qt.Window)
        window.setWindowFlag(Qt.Window, True)
        window.setWindowModality(Qt.NonModal)
        window.setModal(False)
    except Exception:
        pass
    if window.isMinimized():
        window.showNormal()
    else:
        window.show()
    try:
        window.raise_()
    except Exception:
        pass
    try:
        window.activateWindow()
    except Exception:
        pass
    handle = window.windowHandle()
    if handle is not None:
        try:
            handle.requestActivate()
        except Exception:
            pass


def _audio_preview_navigation_track_ids(
    self,
    source_spec: dict[str, object] | None,
) -> list[int]:
    controller = self._catalog_table_controller()
    media_column = self._media_column_for_audio_source_spec(source_spec)
    if source_spec is None:
        return list(controller.visible_track_ids())
    if media_column is not None:
        ordered = []
        for index in controller.visible_indexes(column=media_column):
            if not self._media_cell_has_payload_for_source_spec(index, source_spec):
                continue
            track_id = controller.track_id_for_index(index)
            if track_id is not None:
                ordered.append(track_id)
        return self._normalize_track_ids(ordered)

    visible_ids = list(self._catalog_table_controller().visible_track_ids())
    if not visible_ids:
        visible_ids = self._normalize_track_ids(
            self._catalog_table_controller().selected_track_ids()
        )
    if not visible_ids and self.catalog_reads is not None:
        try:
            visible_ids = [int(track_id) for track_id, _title in self.catalog_reads.list_tracks()]
        except Exception:
            visible_ids = []
    if not source_spec:
        return self._normalize_track_ids(visible_ids)
    kind = str(source_spec.get("kind") or "").strip().lower()
    ordered: list[int] = []
    for track_id in visible_ids:
        try:
            if kind == "custom":
                field_id = int(source_spec.get("field_id") or 0)
                if field_id <= 0 or not self.cf_has_blob(int(track_id), field_id):
                    continue
            else:
                media_key = str(source_spec.get("media_key") or "audio_file").strip()
                if not self.track_has_media(int(track_id), media_key):
                    continue
            ordered.append(int(track_id))
        except Exception:
            continue
    return self._normalize_track_ids(ordered)


def _audio_preview_album_titles(self) -> list[str]:
    if self.conn is None:
        return []
    try:
        rows = self.conn.execute("""
            SELECT DISTINCT trim(title)
            FROM Albums
            WHERE title IS NOT NULL AND trim(title) != ''
            ORDER BY trim(title) COLLATE NOCASE
            """).fetchall()
    except Exception:
        return []
    titles: list[str] = []
    seen: set[str] = set()
    for (title,) in rows:
        clean_title = str(title or "").strip()
        key = clean_title.casefold()
        if clean_title and key not in seen:
            titles.append(clean_title)
            seen.add(key)
    return titles


def _audio_preview_track_has_source_payload(
    self,
    track_id: int,
    source_spec: dict[str, object] | None,
) -> bool:
    if source_spec is None:
        return True
    kind = str(source_spec.get("kind") or "").strip().lower()
    try:
        if kind == "custom":
            field_id = int(source_spec.get("field_id") or 0)
            return field_id > 0 and self.cf_has_blob(int(track_id), field_id)
        media_key = str(source_spec.get("media_key") or "audio_file").strip() or "audio_file"
        return self.track_has_media(int(track_id), media_key)
    except Exception:
        return False


def _audio_preview_album_track_ids(
    self,
    album_title: str | None,
    source_spec: dict[str, object] | None = None,
) -> list[int]:
    clean_title = str(album_title or "").strip()
    if not clean_title or self.conn is None:
        return []
    order_sql = """
        CASE WHEN t.track_number IS NULL OR t.track_number <= 0 THEN 1 ELSE 0 END,
        t.track_number,
        t.id
    """
    try:
        rows = self.conn.execute(
            f"""
            SELECT t.id
            FROM Tracks t
            INNER JOIN Albums al ON al.id = t.album_id
            WHERE trim(al.title)=?
            ORDER BY {order_sql}
            """,
            (clean_title,),
        ).fetchall()
    except sqlite3.OperationalError:
        rows = self.conn.execute(
            """
            SELECT t.id
            FROM Tracks t
            INNER JOIN Albums al ON al.id = t.album_id
            WHERE trim(al.title)=?
            ORDER BY t.id
            """,
            (clean_title,),
        ).fetchall()
    except Exception:
        return []
    track_ids = self._normalize_track_ids(int(row[0]) for row in rows)
    return [
        track_id
        for track_id in track_ids
        if self._audio_preview_track_has_source_payload(track_id, source_spec)
    ]


def _audio_preview_export_actions_for_track(
    self,
    track_id: int,
    source_spec: dict[str, object] | None,
    *,
    parent_widget=None,
    title_override: str | None = None,
) -> list[dict[str, object]]:
    parent = parent_widget or self
    title = (
        str(title_override or "").strip()
        or self._get_track_title(int(track_id))
        or f"track_{track_id}"
    )
    if source_spec is None:
        return []
    kind = str(source_spec.get("kind") or "").strip().lower()
    if kind == "custom":
        field_id = int(source_spec.get("field_id") or 0)
        field_name = str(source_spec.get("field_name") or "").strip()
        if field_id <= 0:
            return []
        suggested_basename = f"{title} - {field_name}" if field_name else title
        return [
            {
                "text": "Export Current Audio…",
                "handler": lambda _checked=False, tid=int(track_id), fid=field_id: (
                    self.cf_export_blob(
                        tid,
                        fid,
                        parent_widget=parent,
                        suggested_basename=suggested_basename,
                    )
                ),
            }
        ]

    actions = [
        {
            "text": "Export Current Audio…",
            "handler": lambda _checked=False, tid=int(track_id): (
                self._export_standard_media_for_track(
                    tid,
                    "audio_file",
                )
            ),
        }
    ]
    action_specs = (
        (
            getattr(self, "write_tags_to_exported_audio_action", None),
            "Export Catalog Audio Copies…",
            lambda tid=int(track_id): self.export_catalog_audio_copies([tid]),
        ),
        (
            getattr(self, "convert_selected_audio_action", None),
            "Export Audio Derivatives…",
            lambda tid=int(track_id): self.convert_selected_audio([tid]),
        ),
        (
            getattr(self, "export_authenticity_watermarked_audio_action", None),
            "Export Authentic Masters…",
            lambda tid=int(track_id): self.export_authenticity_watermarked_audio([tid]),
        ),
        (
            getattr(self, "export_authenticity_provenance_audio_action", None),
            "Export Provenance Copies…",
            lambda tid=int(track_id): self.export_authenticity_provenance_audio([tid]),
        ),
        (
            getattr(self, "export_forensic_watermarked_audio_action", None),
            "Export Forensic Watermarked Audio…",
            lambda tid=int(track_id): self.export_forensic_watermarked_audio([tid]),
        ),
    )
    for action, text, handler in action_specs:
        if action is not None and action.isEnabled():
            actions.append({"text": text, "handler": lambda _checked=False, fn=handler: fn()})
    return actions


def _audio_preview_track_queue_items(self, track_order: list[int]) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for position, track_id in enumerate(self._normalize_track_ids(track_order), start=1):
        title = ""
        album = ""
        try:
            if self.track_service is not None:
                snapshot = self.track_service.fetch_track_snapshot(
                    int(track_id),
                    include_media_blobs=False,
                )
            else:
                snapshot = None
            title = str(
                (snapshot.track_title if snapshot is not None else None)
                or self._get_track_title(int(track_id))
                or ""
            ).strip()
            album = str((snapshot.album_title if snapshot is not None else None) or "").strip()
        except Exception:
            title = ""
        if not title:
            title = f"Track {track_id}"
        items.append(
            {
                "track_id": int(track_id),
                "title": title,
                "label": title,
                "album": album,
                "position": position,
            }
        )
    return items


def _audio_preview_state_for_track(
    self,
    track_id: int,
    source_spec: dict[str, object],
    *,
    parent_widget=None,
    prepared_media: "_AudioPreviewPreparedMedia | None" = None,
) -> dict[str, object]:
    snapshot = None
    if self.track_service is not None:
        try:
            snapshot = self.track_service.fetch_track_snapshot(
                int(track_id),
                include_media_blobs=False,
            )
        except Exception:
            snapshot = None
    title = str(
        (snapshot.track_title if snapshot is not None else None)
        or self._get_track_title(int(track_id))
        or f"Track {track_id}"
    ).strip()
    artist = str((snapshot.artist_name if snapshot is not None else None) or "").strip()
    album = str((snapshot.album_title if snapshot is not None else None) or "").strip()
    artwork = self._effective_artwork_payload_for_track(
        int(track_id),
        snapshot=snapshot,
    )
    kind = str(source_spec.get("kind") or "").strip().lower()
    if kind == "custom":
        field_id = int(source_spec.get("field_id") or 0)
        if prepared_media is not None:
            data, mime = b"", prepared_media.audio_mime
        else:
            data, mime = self.cf_fetch_blob(int(track_id), field_id)
    else:
        media_key = str(source_spec.get("media_key") or "audio_file").strip() or "audio_file"
        if prepared_media is not None:
            data, mime = b"", prepared_media.audio_mime
        else:
            data, mime = self.track_fetch_media(int(track_id), media_key)
    raw_bytes = (
        b""
        if prepared_media is not None
        else self._coerce_export_bytes(data[0] if isinstance(data, tuple) else data)
    )
    track_order = self._audio_preview_navigation_track_ids(source_spec)
    if int(track_id) not in track_order:
        track_order = [int(track_id), *track_order]
    return {
        "track_id": int(track_id),
        "track_order": track_order,
        "track_queue": self._audio_preview_track_queue_items(track_order),
        "title": title,
        "artist": artist,
        "album": album,
        "audio_bytes": raw_bytes,
        "audio_mime": str(
            mime or (self._detect_mime(raw_bytes) if raw_bytes else "") or "audio/wav"
        ),
        "prepared_media": prepared_media,
        "artwork_payload": artwork,
        "window_title": f"Audio Player — {title}",
        "export_actions": self._audio_preview_export_actions_for_track(
            int(track_id),
            source_spec,
            parent_widget=parent_widget,
        ),
    }


def _audio_preview_state_for_raw_bytes(
    self,
    data: bytes,
    mime: str,
    title: str,
    *,
    parent_widget=None,
) -> dict[str, object]:
    parent = parent_widget or self
    raw_bytes = self._coerce_export_bytes(data)
    clean_mime = str(mime or self._detect_mime(raw_bytes) or "audio/wav")
    clean_title = str(title or "Audio Player").strip() or "Audio Player"
    return {
        "track_id": None,
        "track_order": [],
        "track_queue": [],
        "title": clean_title,
        "artist": "",
        "album": "",
        "audio_bytes": raw_bytes,
        "audio_mime": clean_mime,
        "artwork_payload": None,
        "window_title": f"Audio Player — {clean_title}",
        "export_actions": [
            {
                "text": "Export Current Audio…",
                "handler": lambda _checked=False: self._export_bytes_with_picker(
                    raw_bytes,
                    mime=clean_mime,
                    suggested_basename=clean_title,
                    parent_widget=parent,
                    action_label="Export Audio Player: {filename}",
                    action_type="file.export_audio_preview",
                    entity_type="Preview",
                    entity_id=self._sanitize_filename(clean_title),
                    payload={"title": clean_title, "mime_type": clean_mime},
                    dialog_title="Export Audio",
                ),
            }
        ],
    }


def _open_image_preview(self, data: bytes, title: str) -> None:
    if self.image_preview_dialog is None:
        self.image_preview_dialog = _root_attr("_ImagePreviewDialog", _ImagePreviewDialog)(
            self, parent=None
        )
    try:
        self.image_preview_dialog.set_preview(data, title)
    except ValueError:
        _message_box().warning(self, "Preview", "Could not decode image data.")
        return
    self._bring_media_window_to_front(self.image_preview_dialog)


def _media_player_default_track_id(self) -> int | None:
    source_spec = self._audio_preview_source_spec_for_standard_media("audio_file")
    playable_ids = self._audio_preview_navigation_track_ids(source_spec)
    playable_set = set(playable_ids)
    controller = self._catalog_table_controller()
    selected_ids = self._normalize_track_ids(controller.selected_track_ids())

    for track_id in playable_ids:
        if track_id in selected_ids:
            return track_id

    current_track_id = controller.current_track_id()
    if current_track_id is not None and int(current_track_id) in playable_set:
        return int(current_track_id)
    if playable_ids:
        return playable_ids[0]

    fallback_candidates = list(selected_ids)
    if current_track_id is not None:
        fallback_candidates.append(int(current_track_id))
    fallback_candidates.extend(controller.visible_track_ids())
    for track_id in self._normalize_track_ids(fallback_candidates):
        try:
            if self.track_has_media(track_id, "audio_file"):
                return track_id
        except Exception:
            continue
    return None


def open_media_player(self):
    title = "Media Player"
    existing_dialog = getattr(self, "audio_preview_dialog", None)
    if existing_dialog is not None and existing_dialog.isVisible():
        self._bring_media_window_to_front(existing_dialog)
        return
    if self.track_service is None:
        _message_box().warning(self, title, "Open a profile first.")
        return
    track_id = self._media_player_default_track_id()
    if track_id is None:
        _message_box().information(
            self,
            title,
            "Select a track with attached primary audio first.",
        )
        return
    self._open_audio_preview_for_track(
        track_id,
        self._audio_preview_source_spec_for_standard_media("audio_file"),
        autoplay=False,
    )


def _open_audio_preview_for_track(
    self,
    track_id: int,
    source_spec: dict[str, object],
    *,
    autoplay: bool = True,
) -> None:
    if self.audio_preview_dialog is None:
        self.audio_preview_dialog = _root_attr("_AudioPreviewDialog", _AudioPreviewDialog)(
            self, parent=None
        )
    try:
        self.audio_preview_dialog.open_track_preview(
            int(track_id),
            source_spec,
            autoplay=autoplay,
        )
    except Exception as exc:
        self.logger.exception("Audio preview failed: %s", exc)
        _message_box().critical(self, "Audio Player", f"Could not open the audio player:\n{exc}")
        return
    self._bring_media_window_to_front(self.audio_preview_dialog)


def _open_audio_preview(self, data: bytes, mime: str, title: str) -> None:
    if self.audio_preview_dialog is None:
        self.audio_preview_dialog = _root_attr("_AudioPreviewDialog", _AudioPreviewDialog)(
            self, parent=None
        )
    try:
        self.audio_preview_dialog.open_raw_preview(
            data,
            mime,
            title,
            autoplay=True,
        )
    except Exception as exc:
        self.logger.exception("Audio preview failed: %s", exc)
        _message_box().critical(self, "Audio Player", f"Could not open the audio player:\n{exc}")
        return
    self._bring_media_window_to_front(self.audio_preview_dialog)

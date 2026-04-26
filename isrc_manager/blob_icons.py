"""Blob icon settings, persistence helpers, and editor widgets."""

from __future__ import annotations

import base64
import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from isrc_manager.ui_common import (
    FocusWheelComboBox,
    _add_standard_dialog_header,
    _apply_standard_dialog_chrome,
    _create_standard_section,
)

BLOB_ICON_AUDIO_KEY = "blob_icon.audio"
BLOB_ICON_AUDIO_LOSSY_KEY = "blob_icon.audio_lossy"
BLOB_ICON_IMAGE_KEY = "blob_icon.image"
BLOB_ICON_AUDIO_MANAGED_KEY = "blob_icon.audio_managed"
BLOB_ICON_AUDIO_DATABASE_KEY = "blob_icon.audio_database"
BLOB_ICON_AUDIO_LOSSY_MANAGED_KEY = "blob_icon.audio_lossy_managed"
BLOB_ICON_AUDIO_LOSSY_DATABASE_KEY = "blob_icon.audio_lossy_database"
BLOB_ICON_IMAGE_MANAGED_KEY = "blob_icon.image_managed"
BLOB_ICON_IMAGE_DATABASE_KEY = "blob_icon.image_database"


@dataclass(frozen=True)
class SystemBlobIconSpec:
    name: str
    label: str
    standard_pixmap: QStyle.StandardPixmap
    kinds: tuple[str, ...]


SYSTEM_BLOB_ICON_SPECS: tuple[SystemBlobIconSpec, ...] = (
    SystemBlobIconSpec("SP_MediaVolume", "Media Volume", QStyle.SP_MediaVolume, ("audio",)),
    SystemBlobIconSpec(
        "SP_MediaVolumeMuted", "Muted Speaker", QStyle.SP_MediaVolumeMuted, ("audio",)
    ),
    SystemBlobIconSpec("SP_MediaPlay", "Play", QStyle.SP_MediaPlay, ("audio",)),
    SystemBlobIconSpec("SP_MediaPause", "Pause", QStyle.SP_MediaPause, ("audio",)),
    SystemBlobIconSpec("SP_MediaStop", "Stop", QStyle.SP_MediaStop, ("audio",)),
    SystemBlobIconSpec(
        "SP_MediaSeekForward",
        "Seek Forward",
        QStyle.SP_MediaSeekForward,
        ("audio",),
    ),
    SystemBlobIconSpec(
        "SP_MediaSeekBackward",
        "Seek Backward",
        QStyle.SP_MediaSeekBackward,
        ("audio",),
    ),
    SystemBlobIconSpec("SP_FileIcon", "Document", QStyle.SP_FileIcon, ("audio", "image")),
    SystemBlobIconSpec("SP_DirIcon", "Folder", QStyle.SP_DirIcon, ("audio", "image")),
    SystemBlobIconSpec(
        "SP_DirOpenIcon",
        "Open Folder",
        QStyle.SP_DirOpenIcon,
        ("audio", "image"),
    ),
    SystemBlobIconSpec(
        "SP_DialogOpenButton",
        "Open Button",
        QStyle.SP_DialogOpenButton,
        ("audio", "image"),
    ),
    SystemBlobIconSpec("SP_DesktopIcon", "Desktop", QStyle.SP_DesktopIcon, ("image",)),
    SystemBlobIconSpec("SP_ComputerIcon", "Computer", QStyle.SP_ComputerIcon, ("image",)),
    SystemBlobIconSpec("SP_DriveHDIcon", "Drive", QStyle.SP_DriveHDIcon, ("image",)),
)


def _keep_signal_wrapper_alive(owner: object, wrapper: Callable[..., object]) -> None:
    wrappers = getattr(owner, "_isrc_signal_wrappers", None)
    if wrappers is None:
        wrappers = []
        setattr(owner, "_isrc_signal_wrappers", wrappers)
    wrappers.append(wrapper)


def _connect_noarg_signal(signal: Any, owner: object, slot: Callable[[], object]) -> None:
    def _wrapper(_checked: bool = False, _slot: Callable[[], object] = slot) -> None:
        _slot()

    _keep_signal_wrapper_alive(owner, _wrapper)
    signal.connect(_wrapper)


def _connect_args_signal(signal: Any, owner: object, slot: Callable[..., object]) -> None:
    def _wrapper(*args: object, _slot: Callable[..., object] = slot) -> None:
        _slot(*args)

    _keep_signal_wrapper_alive(owner, _wrapper)
    signal.connect(_wrapper)


EMOJI_BLOB_ICON_PRESETS: dict[str, tuple[tuple[str, str], ...]] = {
    "audio": (
        ("🎵", "Music Note"),
        ("🎶", "Music Notes"),
        ("🎧", "Headphones"),
        ("🔊", "Loud Speaker"),
        ("🔉", "Speaker"),
        ("🎼", "Score"),
    ),
    "image": (
        ("🖼️", "Framed Picture"),
        ("🎨", "Palette"),
        ("📷", "Camera"),
        ("🌄", "Landscape"),
        ("🖌️", "Paintbrush"),
        ("✨", "Sparkle"),
    ),
}

EXACT_KIND_DEFAULT_EMOJI_LABELS: dict[str, str] = {
    "audio": "Recommended Default",
    "audio_managed": "Recommended Default - Managed Audio",
    "audio_database": "Recommended Default - Database Audio",
    "audio_lossy": "Recommended Default - Lossy Audio",
    "audio_lossy_managed": "Recommended Default - Managed Lossy Audio",
    "audio_lossy_database": "Recommended Default - Database Lossy Audio",
    "image": "Recommended Default",
    "image_managed": "Recommended Default - Managed Image",
    "image_database": "Recommended Default - Database Image",
}

FULL_LIBRARY_EMOJI_LABELS: dict[str, str] = {
    "🎚️": "Level Slider",
    "📼": "Tape",
    "💽": "Optical Disc",
    "🗃️": "Archive Box",
}


def default_blob_icon_spec(kind: str) -> dict[str, object]:
    clean_kind = str(kind or "").strip().lower()
    if clean_kind in {"audio_lossy", "audio_lossy_managed"}:
        return {"mode": "emoji", "emoji": "🎚️"}
    if clean_kind == "audio_lossy_database":
        return {"mode": "emoji", "emoji": "📼"}
    if clean_kind == "audio_database":
        return {"mode": "emoji", "emoji": "💽"}
    if _normalize_blob_icon_kind(clean_kind) == "audio":
        return {"mode": "emoji", "emoji": "🎵"}
    if clean_kind == "image_database":
        return {"mode": "emoji", "emoji": "🗃️"}
    return {"mode": "emoji", "emoji": "🖼️"}


def default_blob_icon_settings() -> dict[str, dict[str, object]]:
    return {
        "audio_managed": default_blob_icon_spec("audio_managed"),
        "audio_database": default_blob_icon_spec("audio_database"),
        "audio_lossy_managed": default_blob_icon_spec("audio_lossy_managed"),
        "audio_lossy_database": default_blob_icon_spec("audio_lossy_database"),
        "image_managed": default_blob_icon_spec("image_managed"),
        "image_database": default_blob_icon_spec("image_database"),
    }


def _normalize_blob_icon_kind(kind: str) -> str:
    clean_kind = str(kind or "").strip().lower()
    if clean_kind in {
        "audio_lossy",
        "audio_managed",
        "audio_database",
        "audio_lossy_managed",
        "audio_lossy_database",
    }:
        return "audio"
    if clean_kind in {"image_managed", "image_database"}:
        return "image"
    return clean_kind


def _display_blob_icon_kind(kind: str) -> str:
    return str(kind or "").strip().replace("_", " ")


def _system_specs_for_kind(kind: str) -> tuple[SystemBlobIconSpec, ...]:
    clean_kind = _normalize_blob_icon_kind(kind)
    return tuple(spec for spec in SYSTEM_BLOB_ICON_SPECS if clean_kind in spec.kinds)


def _ordered_unique_pairs(
    pairs: tuple[tuple[str, str], ...] | list[tuple[str, str]],
) -> tuple[tuple[str, str], ...]:
    ordered: list[tuple[str, str]] = []
    seen: set[str] = set()
    for value, label in pairs:
        clean_value = str(value or "").strip()
        if not clean_value or clean_value in seen:
            continue
        seen.add(clean_value)
        ordered.append((clean_value, str(label or clean_value).strip() or clean_value))
    return tuple(ordered)


def _ordered_unique_system_specs(
    specs: tuple[SystemBlobIconSpec, ...] | list[SystemBlobIconSpec],
) -> tuple[SystemBlobIconSpec, ...]:
    ordered: list[SystemBlobIconSpec] = []
    seen: set[str] = set()
    for spec in specs:
        if spec.name in seen:
            continue
        seen.add(spec.name)
        ordered.append(spec)
    return tuple(ordered)


def _default_emoji_choice(kind: str) -> tuple[str, str]:
    clean_kind = str(kind or "").strip().lower()
    default_emoji = str(default_blob_icon_spec(clean_kind).get("emoji") or "").strip()
    label = EXACT_KIND_DEFAULT_EMOJI_LABELS.get(
        clean_kind,
        EXACT_KIND_DEFAULT_EMOJI_LABELS.get(
            _normalize_blob_icon_kind(clean_kind),
            "Recommended Default",
        ),
    )
    return (default_emoji, label)


def recommended_system_blob_icon_choices(kind: str) -> tuple[SystemBlobIconSpec, ...]:
    return _system_specs_for_kind(kind)


def available_system_blob_icon_choices() -> tuple[SystemBlobIconSpec, ...]:
    return SYSTEM_BLOB_ICON_SPECS


def default_system_icon_name(kind: str) -> str:
    specs = recommended_system_blob_icon_choices(kind)
    if specs:
        return specs[0].name
    return "SP_FileIcon"


def system_blob_icon_choices(kind: str) -> tuple[SystemBlobIconSpec, ...]:
    return _ordered_unique_system_specs(
        [
            *recommended_system_blob_icon_choices(kind),
            *available_system_blob_icon_choices(),
        ]
    )


def recommended_emoji_blob_icon_presets(kind: str) -> tuple[tuple[str, str], ...]:
    clean_kind = str(kind or "").strip().lower()
    normalized_kind = _normalize_blob_icon_kind(clean_kind)
    return _ordered_unique_pairs(
        [
            _default_emoji_choice(clean_kind),
            *EMOJI_BLOB_ICON_PRESETS.get(normalized_kind, ()),
        ]
    )


def available_emoji_blob_icon_presets() -> tuple[tuple[str, str], ...]:
    ordered: list[tuple[str, str]] = []
    for preset_group in EMOJI_BLOB_ICON_PRESETS.values():
        ordered.extend(preset_group)
    for kind in (
        "audio_managed",
        "audio_database",
        "audio_lossy_managed",
        "audio_lossy_database",
        "image_managed",
        "image_database",
    ):
        emoji, _label = _default_emoji_choice(kind)
        ordered.append((emoji, FULL_LIBRARY_EMOJI_LABELS.get(emoji, emoji)))
    return _ordered_unique_pairs(ordered)


def emoji_blob_icon_presets(kind: str) -> tuple[tuple[str, str], ...]:
    recommended = recommended_emoji_blob_icon_presets(kind)
    recommended_values = {value for value, _label in recommended}
    remainder = tuple(
        (value, label)
        for value, label in available_emoji_blob_icon_presets()
        if value not in recommended_values
    )
    return recommended + remainder


def _coerce_image_payload(raw: object) -> dict[str, object]:
    payload = dict(raw or {}) if isinstance(raw, dict) else {}
    image_b64 = str(payload.get("image_png_base64") or "").strip()
    image_path = str(payload.get("image_path") or "").strip()
    result = {"mode": "image"}
    if image_b64:
        result["image_png_base64"] = image_b64
    if image_path:
        result["image_path"] = image_path
    label = str(payload.get("image_label") or "").strip()
    if label:
        result["image_label"] = label
    width = payload.get("image_width")
    height = payload.get("image_height")
    if width not in (None, ""):
        try:
            result["image_width"] = int(width)
        except Exception:
            pass
    if height not in (None, ""):
        try:
            result["image_height"] = int(height)
        except Exception:
            pass
    return result


def normalize_blob_icon_spec(
    spec: dict[str, object] | str | None,
    *,
    kind: str,
    allow_inherit: bool = False,
) -> dict[str, object]:
    raw: dict[str, object]
    if isinstance(spec, str):
        try:
            parsed = json.loads(spec)
        except Exception:
            parsed = {}
        raw = dict(parsed or {}) if isinstance(parsed, dict) else {}
    elif isinstance(spec, dict):
        raw = dict(spec)
    else:
        raw = {}

    mode = str(raw.get("mode") or "").strip().lower()
    if allow_inherit and mode == "inherit":
        return {"mode": "inherit"}

    if mode == "system":
        system_name = str(raw.get("system_name") or "").strip()
        valid_names = {choice.name for choice in system_blob_icon_choices(kind)}
        if system_name not in valid_names:
            system_name = default_system_icon_name(kind)
        return {"mode": "system", "system_name": system_name}

    if mode == "image":
        image_payload = _coerce_image_payload(raw)
        if image_payload.get("image_png_base64") or image_payload.get("image_path"):
            return image_payload
        if allow_inherit:
            return {"mode": "inherit"}

    emoji = str(raw.get("emoji") or "").strip()
    if not emoji:
        emoji = str(default_blob_icon_spec(kind)["emoji"])
    return {"mode": "emoji", "emoji": emoji}


def normalize_blob_icon_settings(
    settings: dict[str, object] | None,
) -> dict[str, dict[str, object]]:
    payload = dict(settings or {})

    def _payload_value(key: str, legacy_key: str | None = None):
        if key in payload:
            return payload.get(key)
        if legacy_key is not None:
            return payload.get(legacy_key)
        return None

    return {
        "audio_managed": normalize_blob_icon_spec(
            _payload_value("audio_managed", "audio"),
            kind="audio_managed",
        ),
        "audio_database": normalize_blob_icon_spec(
            _payload_value("audio_database", "audio"),
            kind="audio_database",
        ),
        "audio_lossy_managed": normalize_blob_icon_spec(
            _payload_value("audio_lossy_managed", "audio_lossy"),
            kind="audio_lossy_managed",
        ),
        "audio_lossy_database": normalize_blob_icon_spec(
            _payload_value("audio_lossy_database", "audio_lossy"),
            kind="audio_lossy_database",
        ),
        "image_managed": normalize_blob_icon_spec(
            _payload_value("image_managed", "image"),
            kind="image_managed",
        ),
        "image_database": normalize_blob_icon_spec(
            _payload_value("image_database", "image"),
            kind="image_database",
        ),
    }


def finalize_blob_icon_spec(
    spec: dict[str, object] | str | None,
    *,
    kind: str,
    allow_inherit: bool = False,
    max_edge: int = 40,
) -> dict[str, object]:
    normalized = normalize_blob_icon_spec(spec, kind=kind, allow_inherit=allow_inherit)
    if allow_inherit and normalized.get("mode") == "inherit":
        return {"mode": "inherit"}
    if normalized.get("mode") == "image" and normalized.get("image_path"):
        payload = compress_blob_icon_image(str(normalized["image_path"]), max_edge=max_edge)
        return payload
    return normalized


def blob_icon_spec_to_storage(
    spec: dict[str, object] | str | None,
    *,
    kind: str,
    allow_inherit: bool = False,
) -> str | None:
    finalized = finalize_blob_icon_spec(spec, kind=kind, allow_inherit=allow_inherit)
    if allow_inherit and finalized.get("mode") == "inherit":
        return None
    return json.dumps(finalized, sort_keys=True)


def blob_icon_spec_from_storage(
    raw_value: str | None,
    *,
    kind: str,
    allow_inherit: bool = False,
) -> dict[str, object]:
    if not raw_value:
        return {"mode": "inherit"} if allow_inherit else default_blob_icon_spec(kind)
    return normalize_blob_icon_spec(raw_value, kind=kind, allow_inherit=allow_inherit)


def describe_blob_icon_spec(
    spec: dict[str, object] | str | None,
    *,
    kind: str,
    allow_inherit: bool = False,
) -> str:
    normalized = normalize_blob_icon_spec(spec, kind=kind, allow_inherit=allow_inherit)
    mode = str(normalized.get("mode") or "").strip().lower()
    if mode == "inherit":
        return f"Uses global {_display_blob_icon_kind(kind)} icon"
    if mode == "system":
        name = str(normalized.get("system_name") or "").strip()
        label = next(
            (choice.label for choice in system_blob_icon_choices(kind) if choice.name == name), name
        )
        return f"Platform icon · {label}"
    if mode == "image":
        label = str(normalized.get("image_label") or "").strip()
        return f"Custom image · {label or 'stored artwork'}"
    return f"Emoji · {str(normalized.get('emoji') or '').strip()}"


def compress_blob_icon_image(path: str, *, max_edge: int = 40) -> dict[str, object]:
    image_path = str(path or "").strip()
    if not image_path:
        raise ValueError("Choose an image file first.")
    image = QImage(image_path)
    if image.isNull():
        raise ValueError("Could not read the selected image.")
    scaled = image.scaled(
        max(16, int(max_edge)),
        max(16, int(max_edge)),
        Qt.KeepAspectRatio,
        Qt.SmoothTransformation,
    )
    png_bytes = encode_qimage_to_png_bytes(scaled)
    return {
        "mode": "image",
        "image_png_base64": base64.b64encode(png_bytes).decode("ascii"),
        "image_width": int(scaled.width()),
        "image_height": int(scaled.height()),
        "image_label": Path(image_path).name,
    }


def encode_qimage_to_png_bytes(image: QImage) -> bytes:
    payload = QByteArray()
    buffer = QBuffer(payload)
    if not buffer.open(QIODevice.WriteOnly):
        raise ValueError("Could not prepare the icon image for storage.")
    try:
        if not image.save(buffer, "PNG"):
            raise ValueError("Could not encode the icon image.")
    finally:
        buffer.close()
    return bytes(payload)


def decode_blob_icon_image(spec: dict[str, object] | str | None) -> QImage:
    normalized = normalize_blob_icon_spec(spec, kind="image", allow_inherit=True)
    if normalized.get("mode") != "image":
        return QImage()
    encoded = str(normalized.get("image_png_base64") or "").strip()
    if encoded:
        try:
            data = base64.b64decode(encoded.encode("ascii"))
        except Exception:
            data = b""
        image = QImage.fromData(data, "PNG")
        if not image.isNull():
            return image
    path = str(normalized.get("image_path") or "").strip()
    if path:
        return QImage(path)
    return QImage()


def _render_emoji_icon(emoji: str, *, size: int = 18) -> QIcon:
    clean_emoji = str(emoji or "").strip() or "?"
    edge = max(16, int(size))
    pixmap = QPixmap(edge, edge)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.TextAntialiasing, True)
    font = QFont(QApplication.font() if QApplication.instance() is not None else QFont())
    font.setPointSize(max(10, int(edge * 0.72)))
    painter.setFont(font)
    painter.setPen(QColor("#111827"))
    painter.drawText(pixmap.rect(), Qt.AlignCenter, clean_emoji)
    painter.end()
    return QIcon(pixmap)


def icon_from_blob_icon_spec(
    spec: dict[str, object] | str | None,
    *,
    kind: str,
    style: QStyle | None = None,
    fallback_spec: dict[str, object] | None = None,
    allow_inherit: bool = False,
    size: int = 18,
) -> QIcon:
    normalized = normalize_blob_icon_spec(spec, kind=kind, allow_inherit=allow_inherit)
    if normalized.get("mode") == "inherit":
        normalized = normalize_blob_icon_spec(
            fallback_spec or default_blob_icon_spec(kind),
            kind=kind,
            allow_inherit=False,
        )

    mode = str(normalized.get("mode") or "").strip().lower()
    if mode == "system":
        style = style or (QApplication.instance().style() if QApplication.instance() else None)
        system_name = str(normalized.get("system_name") or default_system_icon_name(kind))
        if style is not None and hasattr(QStyle, system_name):
            return style.standardIcon(getattr(QStyle, system_name))
        return QIcon()

    if mode == "image":
        image = decode_blob_icon_image(normalized)
        if not image.isNull():
            if image.width() > size or image.height() > size:
                image = image.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            return QIcon(QPixmap.fromImage(image))

    return _render_emoji_icon(str(normalized.get("emoji") or ""), size=size)


class BlobIconSettingsService:
    """Stores global audio/image blob icon defaults inside the active profile DB."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def _read_kv(self, key: str) -> str:
        row = self.conn.execute("SELECT value FROM app_kv WHERE key=?", (key,)).fetchone()
        if not row or row[0] is None:
            return ""
        return str(row[0]).strip()

    def _write_kv(self, key: str, value: str) -> None:
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO app_kv(key, value) VALUES(?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (key, value),
            )

    def load_settings(self) -> dict[str, dict[str, object]]:
        return normalize_blob_icon_settings(
            {
                "audio": blob_icon_spec_from_storage(
                    self._read_kv(BLOB_ICON_AUDIO_KEY),
                    kind="audio",
                ),
                "audio_lossy": blob_icon_spec_from_storage(
                    self._read_kv(BLOB_ICON_AUDIO_LOSSY_KEY),
                    kind="audio_lossy",
                ),
                "image": blob_icon_spec_from_storage(
                    self._read_kv(BLOB_ICON_IMAGE_KEY),
                    kind="image",
                ),
                "audio_managed": blob_icon_spec_from_storage(
                    self._read_kv(BLOB_ICON_AUDIO_MANAGED_KEY),
                    kind="audio_managed",
                ),
                "audio_database": blob_icon_spec_from_storage(
                    self._read_kv(BLOB_ICON_AUDIO_DATABASE_KEY),
                    kind="audio_database",
                ),
                "audio_lossy_managed": blob_icon_spec_from_storage(
                    self._read_kv(BLOB_ICON_AUDIO_LOSSY_MANAGED_KEY),
                    kind="audio_lossy_managed",
                ),
                "audio_lossy_database": blob_icon_spec_from_storage(
                    self._read_kv(BLOB_ICON_AUDIO_LOSSY_DATABASE_KEY),
                    kind="audio_lossy_database",
                ),
                "image_managed": blob_icon_spec_from_storage(
                    self._read_kv(BLOB_ICON_IMAGE_MANAGED_KEY),
                    kind="image_managed",
                ),
                "image_database": blob_icon_spec_from_storage(
                    self._read_kv(BLOB_ICON_IMAGE_DATABASE_KEY),
                    kind="image_database",
                ),
            }
        )

    def save_settings(self, settings: dict[str, object] | None) -> dict[str, dict[str, object]]:
        normalized = normalize_blob_icon_settings(settings)
        self._write_kv(
            BLOB_ICON_AUDIO_MANAGED_KEY,
            blob_icon_spec_to_storage(normalized.get("audio_managed"), kind="audio_managed") or "",
        )
        self._write_kv(
            BLOB_ICON_AUDIO_DATABASE_KEY,
            blob_icon_spec_to_storage(normalized.get("audio_database"), kind="audio_database")
            or "",
        )
        self._write_kv(
            BLOB_ICON_AUDIO_LOSSY_MANAGED_KEY,
            blob_icon_spec_to_storage(
                normalized.get("audio_lossy_managed"),
                kind="audio_lossy_managed",
            )
            or "",
        )
        self._write_kv(
            BLOB_ICON_AUDIO_LOSSY_DATABASE_KEY,
            blob_icon_spec_to_storage(
                normalized.get("audio_lossy_database"),
                kind="audio_lossy_database",
            )
            or "",
        )
        self._write_kv(
            BLOB_ICON_IMAGE_MANAGED_KEY,
            blob_icon_spec_to_storage(normalized.get("image_managed"), kind="image_managed") or "",
        )
        self._write_kv(
            BLOB_ICON_IMAGE_DATABASE_KEY,
            blob_icon_spec_to_storage(normalized.get("image_database"), kind="image_database")
            or "",
        )
        return self.load_settings()


class BlobIconEditorWidget(QWidget):
    """Reusable editor for one blob icon specification."""

    specChanged = Signal()

    def __init__(
        self,
        *,
        kind: str,
        allow_inherit: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self.kind = str(kind or "image").strip().lower()
        self.allow_inherit = bool(allow_inherit)
        self._setting_spec = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        form = QGridLayout()
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)
        layout.addLayout(form)

        self.mode_combo = FocusWheelComboBox(self)
        if self.allow_inherit:
            self.mode_combo.addItem("Use Global Default", "inherit")
        self.mode_combo.addItem("Platform Icon", "system")
        self.mode_combo.addItem("Emoji", "emoji")
        self.mode_combo.addItem("Custom Image", "image")
        form.addWidget(QLabel("Source"), 0, 0)
        form.addWidget(self.mode_combo, 0, 1)

        preview_row = QWidget(self)
        preview_layout = QHBoxLayout(preview_row)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(10)
        self.preview_icon_label = QLabel(preview_row)
        self.preview_icon_label.setFixedSize(34, 34)
        self.preview_icon_label.setAlignment(Qt.AlignCenter)
        self.preview_icon_label.setStyleSheet(
            "border: 1px solid palette(mid); border-radius: 6px; background: palette(base);"
        )
        self.preview_summary_label = QLabel(preview_row)
        self.preview_summary_label.setWordWrap(True)
        preview_layout.addWidget(self.preview_icon_label)
        preview_layout.addWidget(self.preview_summary_label, 1)
        form.addWidget(QLabel("Preview"), 1, 0)
        form.addWidget(preview_row, 1, 1)

        self.mode_stack = QStackedWidget(self)
        layout.addWidget(self.mode_stack)

        self.system_page = QWidget(self.mode_stack)
        system_layout = QVBoxLayout(self.system_page)
        system_layout.setContentsMargins(0, 0, 0, 0)
        system_layout.setSpacing(6)
        self.system_note_label = QLabel(
            "Recommended platform icons appear first. Browse the full available platform icon list after the separator.",
            self.system_page,
        )
        self.system_note_label.setWordWrap(True)
        self.system_note_label.setProperty("role", "secondary")
        system_layout.addWidget(self.system_note_label)
        self.system_combo = FocusWheelComboBox(self.system_page)
        style = QApplication.instance().style() if QApplication.instance() is not None else None
        recommended_system_choices = recommended_system_blob_icon_choices(self.kind)
        all_system_choices = system_blob_icon_choices(self.kind)
        recommended_system_names = {choice.name for choice in recommended_system_choices}
        for choice in recommended_system_choices:
            self.system_combo.addItem(choice.label, choice.name)
            if style is not None:
                self.system_combo.setItemIcon(
                    self.system_combo.count() - 1,
                    style.standardIcon(choice.standard_pixmap),
                )
        remaining_system_choices = tuple(
            choice for choice in all_system_choices if choice.name not in recommended_system_names
        )
        if recommended_system_choices and remaining_system_choices:
            self.system_combo.insertSeparator(self.system_combo.count())
        for choice in remaining_system_choices:
            self.system_combo.addItem(choice.label, choice.name)
            if style is not None:
                self.system_combo.setItemIcon(
                    self.system_combo.count() - 1,
                    style.standardIcon(choice.standard_pixmap),
                )
        system_layout.addWidget(self.system_combo)
        self.mode_stack.addWidget(self.system_page)

        self.emoji_page = QWidget(self.mode_stack)
        emoji_layout = QGridLayout(self.emoji_page)
        emoji_layout.setContentsMargins(0, 0, 0, 0)
        emoji_layout.setHorizontalSpacing(10)
        emoji_layout.setVerticalSpacing(8)
        self.emoji_combo = FocusWheelComboBox(self.emoji_page)
        recommended_emoji_choices = recommended_emoji_blob_icon_presets(self.kind)
        all_emoji_choices = emoji_blob_icon_presets(self.kind)
        recommended_emoji_values = {emoji for emoji, _label in recommended_emoji_choices}
        for emoji, label in recommended_emoji_choices:
            self.emoji_combo.addItem(f"{emoji}  {label}", emoji)
        remaining_emoji_choices = tuple(
            (emoji, label)
            for emoji, label in all_emoji_choices
            if emoji not in recommended_emoji_values
        )
        if recommended_emoji_choices and remaining_emoji_choices:
            self.emoji_combo.insertSeparator(self.emoji_combo.count())
        for emoji, label in remaining_emoji_choices:
            self.emoji_combo.addItem(f"{emoji}  {label}", emoji)
        self.emoji_edit = QLineEdit(self.emoji_page)
        self.emoji_edit.setClearButtonEnabled(True)
        self.emoji_edit.setPlaceholderText("Type or pick an emoji")
        emoji_note = QLabel(
            "Recommended emojis appear first. Browse the full bundled emoji set after the separator, or type any emoji below.",
            self.emoji_page,
        )
        emoji_note.setWordWrap(True)
        emoji_note.setProperty("role", "secondary")
        emoji_layout.addWidget(emoji_note, 0, 0, 1, 2)
        emoji_layout.addWidget(QLabel("Recommended First"), 1, 0)
        emoji_layout.addWidget(self.emoji_combo, 1, 1)
        emoji_layout.addWidget(QLabel("Emoji"), 2, 0)
        emoji_layout.addWidget(self.emoji_edit, 2, 1)
        self.mode_stack.addWidget(self.emoji_page)

        self.image_page = QWidget(self.mode_stack)
        image_layout = QGridLayout(self.image_page)
        image_layout.setContentsMargins(0, 0, 0, 0)
        image_layout.setHorizontalSpacing(10)
        image_layout.setVerticalSpacing(8)
        self.image_path_edit = QLineEdit(self.image_page)
        self.image_path_edit.setReadOnly(True)
        self.image_path_edit.setPlaceholderText("No custom image selected")
        self.image_browse_button = QPushButton("Choose Image…", self.image_page)
        self.image_browse_button.setAutoDefault(False)
        self.image_clear_button = QPushButton("Clear", self.image_page)
        self.image_clear_button.setAutoDefault(False)
        image_button_row = QWidget(self.image_page)
        image_button_layout = QHBoxLayout(image_button_row)
        image_button_layout.setContentsMargins(0, 0, 0, 0)
        image_button_layout.setSpacing(8)
        image_button_layout.addWidget(self.image_browse_button)
        image_button_layout.addWidget(self.image_clear_button)
        image_button_layout.addStretch(1)
        self.image_note_label = QLabel(
            "Imported images are scaled down and stored as compact PNG data inside the profile database.",
            self.image_page,
        )
        self.image_note_label.setWordWrap(True)
        image_layout.addWidget(QLabel("Image"), 0, 0)
        image_layout.addWidget(self.image_path_edit, 0, 1)
        image_layout.addWidget(QLabel("Actions"), 1, 0)
        image_layout.addWidget(image_button_row, 1, 1)
        image_layout.addWidget(self.image_note_label, 2, 0, 1, 2)
        self.mode_stack.addWidget(self.image_page)

        _connect_args_signal(
            self.mode_combo.currentIndexChanged, self.mode_combo, self._on_mode_changed
        )
        _connect_args_signal(
            self.system_combo.currentIndexChanged,
            self.system_combo,
            self._emit_change,
        )
        _connect_args_signal(
            self.emoji_combo.currentIndexChanged,
            self.emoji_combo,
            self._apply_selected_emoji_preset,
        )
        _connect_args_signal(self.emoji_edit.textChanged, self.emoji_edit, self._emit_change)
        _connect_noarg_signal(
            self.image_browse_button.clicked,
            self.image_browse_button,
            self._choose_image,
        )
        _connect_noarg_signal(
            self.image_clear_button.clicked,
            self.image_clear_button,
            self._clear_image,
        )

        self.set_spec(
            {"mode": "inherit"} if self.allow_inherit else default_blob_icon_spec(self.kind)
        )

    def _emit_change(self, *_args) -> None:
        if self._setting_spec:
            return
        self._refresh_preview()
        self.specChanged.emit()

    def _page_index_for_mode(self, mode: str) -> int:
        if mode == "system":
            return 0
        if mode == "emoji":
            return 1
        return 2

    def _on_mode_changed(self, *_args) -> None:
        mode = str(self.mode_combo.currentData() or "emoji")
        if mode == "inherit":
            self.mode_stack.setCurrentIndex(self._page_index_for_mode("emoji"))
        else:
            self.mode_stack.setCurrentIndex(self._page_index_for_mode(mode))
        self._emit_change()

    def _apply_selected_emoji_preset(self, *_args) -> None:
        if self._setting_spec:
            return
        emoji = str(self.emoji_combo.currentData() or "").strip()
        if emoji:
            self.emoji_edit.setText(emoji)
        else:
            self._emit_change()

    def _choose_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose Custom Icon",
            str(Path.home()),
            "Images (*.png *.jpg *.jpeg *.webp *.bmp *.gif *.tif *.tiff *.ico);;All files (*)",
        )
        if not path:
            return
        image = QImage(path)
        if image.isNull():
            QMessageBox.warning(self, "Custom Icon", "Could not read the selected image.")
            return
        self.image_path_edit.setText(str(path))
        self.image_path_edit.setProperty("stored_png_base64", "")
        self.image_path_edit.setProperty("stored_image_label", "")
        self._emit_change()

    def _clear_image(self) -> None:
        self.image_path_edit.clear()
        self.image_path_edit.setProperty("stored_png_base64", "")
        self.image_path_edit.setProperty("stored_image_label", "")
        self._emit_change()

    def set_spec(self, spec: dict[str, object] | str | None) -> None:
        normalized = normalize_blob_icon_spec(
            spec,
            kind=self.kind,
            allow_inherit=self.allow_inherit,
        )
        self._setting_spec = True
        try:
            mode = str(normalized.get("mode") or ("inherit" if self.allow_inherit else "emoji"))
            index = self.mode_combo.findData(mode)
            if index < 0:
                index = self.mode_combo.findData("emoji")
            if index < 0:
                index = 0
            self.mode_combo.setCurrentIndex(index)
            effective_mode = str(self.mode_combo.currentData() or "emoji")
            if effective_mode == "system":
                system_name = str(
                    normalized.get("system_name") or default_system_icon_name(self.kind)
                )
                system_index = self.system_combo.findData(system_name)
                self.system_combo.setCurrentIndex(max(0, system_index))
            elif effective_mode == "emoji":
                emoji = str(normalized.get("emoji") or default_blob_icon_spec(self.kind)["emoji"])
                combo_index = self.emoji_combo.findData(emoji)
                if combo_index >= 0:
                    self.emoji_combo.setCurrentIndex(combo_index)
                self.emoji_edit.setText(emoji)
            elif effective_mode == "image" or mode == "image":
                self.image_path_edit.setText(str(normalized.get("image_path") or ""))
                self.image_path_edit.setProperty(
                    "stored_png_base64",
                    str(normalized.get("image_png_base64") or ""),
                )
                self.image_path_edit.setProperty(
                    "stored_image_label",
                    str(normalized.get("image_label") or ""),
                )
        finally:
            self._setting_spec = False
        self._on_mode_changed()
        self._refresh_preview()

    def current_spec(self) -> dict[str, object]:
        mode = str(self.mode_combo.currentData() or "emoji")
        if mode == "inherit" and self.allow_inherit:
            return {"mode": "inherit"}
        if mode == "system":
            return {
                "mode": "system",
                "system_name": str(
                    self.system_combo.currentData() or default_system_icon_name(self.kind)
                ),
            }
        if mode == "image":
            image_path = self.image_path_edit.text().strip()
            stored_png = str(self.image_path_edit.property("stored_png_base64") or "").strip()
            stored_label = str(self.image_path_edit.property("stored_image_label") or "").strip()
            if image_path:
                return {
                    "mode": "image",
                    "image_path": image_path,
                    "image_label": Path(image_path).name,
                }
            if stored_png:
                result = {"mode": "image", "image_png_base64": stored_png}
                if stored_label:
                    result["image_label"] = stored_label
                return result
            if self.allow_inherit:
                return {"mode": "inherit"}
            return default_blob_icon_spec(self.kind)
        emoji = self.emoji_edit.text().strip() or str(default_blob_icon_spec(self.kind)["emoji"])
        return {"mode": "emoji", "emoji": emoji}

    def _refresh_preview(self) -> None:
        spec = self.current_spec()
        fallback = default_blob_icon_spec(self.kind)
        icon = icon_from_blob_icon_spec(
            spec,
            kind=self.kind,
            fallback_spec=fallback,
            allow_inherit=self.allow_inherit,
            size=22,
        )
        pixmap = icon.pixmap(24, 24)
        self.preview_icon_label.setPixmap(pixmap)
        self.preview_summary_label.setText(
            describe_blob_icon_spec(spec, kind=self.kind, allow_inherit=self.allow_inherit)
        )


class BlobIconDialog(QDialog):
    """Modal blob icon picker used by custom-column configuration flows."""

    def __init__(
        self,
        *,
        kind: str,
        title: str,
        spec: dict[str, object] | str | None,
        allow_inherit: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(620, 420)
        self.setMinimumSize(560, 380)
        _apply_standard_dialog_chrome(self, "blobIconDialog")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)
        _add_standard_dialog_header(
            layout,
            self,
            title=title,
            subtitle=(
                "Choose a platform icon, a standardized emoji, or a custom image that will be compressed and stored in the profile database."
            ),
        )

        section_box, section_layout = _create_standard_section(
            self,
            "Icon Source",
            "Use the global default for this blob type, or override it for this custom field only.",
        )
        self.editor = BlobIconEditorWidget(
            kind=kind, allow_inherit=allow_inherit, parent=section_box
        )
        self.editor.set_spec(spec)
        section_layout.addWidget(self.editor)
        layout.addWidget(section_box, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel,
            Qt.Horizontal,
            self,
        )
        ok = buttons.button(QDialogButtonBox.Ok)
        if ok is not None:
            ok.setDefault(True)
        _connect_noarg_signal(buttons.accepted, buttons, self._accept_if_valid)
        _connect_noarg_signal(buttons.rejected, buttons, self.reject)
        layout.addWidget(buttons)

    def _accept_if_valid(self) -> None:
        spec = self.editor.current_spec()
        mode = str(spec.get("mode") or "")
        if mode == "emoji" and not str(spec.get("emoji") or "").strip():
            QMessageBox.warning(self, "Icon Required", "Choose or type an emoji first.")
            return
        if mode == "image" and not (
            str(spec.get("image_path") or "").strip()
            or str(spec.get("image_png_base64") or "").strip()
        ):
            QMessageBox.warning(self, "Icon Required", "Choose an image first.")
            return
        self.accept()

    def current_spec(self) -> dict[str, object]:
        return self.editor.current_spec()

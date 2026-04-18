"""Pure header-state persistence helpers for the catalog-table migration."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import TYPE_CHECKING

from PySide6.QtCore import QByteArray, QSettings

from .models import CatalogColumnSpec

if TYPE_CHECKING:
    from PySide6.QtWidgets import QHeaderView

HEADER_STATE_KEY = "header_state"
HEADER_LABELS_KEY = "header_labels"
HEADER_LABELS_JSON_KEY = "header_labels_json"
HEADER_COLUMN_KEYS_JSON_KEY = "header_column_keys_json"
HIDDEN_COLUMNS_JSON_KEY = "hidden_columns_json"
HIDDEN_COLUMN_KEYS_JSON_KEY = "hidden_column_keys_json"
COLUMNS_MOVABLE_KEY = "columns_movable"


class CatalogHeaderStateManager:
    """Persist and restore header order/visibility with key-based compatibility."""

    def __init__(
        self,
        settings: QSettings | None = None,
        *,
        settings_prefix: str = "",
    ) -> None:
        self._settings = settings
        self._settings_prefix = self._normalize_prefix(settings_prefix)

    def settings_prefix(self) -> str:
        return self._settings_prefix

    def set_settings_prefix(self, settings_prefix: str | None) -> None:
        self._settings_prefix = self._normalize_prefix(settings_prefix)

    def settings_key(self, suffix: str, *, settings_prefix: str | None = None) -> str:
        prefix = self._normalize_prefix(
            self._settings_prefix if settings_prefix is None else settings_prefix
        )
        clean_suffix = str(suffix or "").strip().lstrip("/")
        if not prefix:
            return clean_suffix
        if not clean_suffix:
            return prefix
        return f"{prefix}/{clean_suffix}"

    def save_state(
        self,
        header: "QHeaderView",
        *,
        column_specs: Sequence[CatalogColumnSpec],
        settings: QSettings | None = None,
        settings_prefix: str | None = None,
    ) -> None:
        settings_obj = self._resolve_settings(settings)
        if settings_obj is None:
            return

        normalized_specs = tuple(column_specs)
        settings_obj.setValue(
            self.settings_key(HEADER_STATE_KEY, settings_prefix=settings_prefix),
            header.saveState(),
        )

        visual_order = self._visual_order(header, len(normalized_specs))
        header_labels = [normalized_specs[index].header_text for index in visual_order]
        header_column_keys = [normalized_specs[index].key for index in visual_order]
        hidden_columns = self._capture_hidden_columns_payload(header, normalized_specs)
        hidden_column_keys = [entry["key"] for entry in hidden_columns]

        settings_obj.setValue(
            self.settings_key(HEADER_LABELS_KEY, settings_prefix=settings_prefix),
            header_labels,
        )
        settings_obj.setValue(
            self.settings_key(HEADER_LABELS_JSON_KEY, settings_prefix=settings_prefix),
            json.dumps(header_labels),
        )
        settings_obj.setValue(
            self.settings_key(HEADER_COLUMN_KEYS_JSON_KEY, settings_prefix=settings_prefix),
            json.dumps(header_column_keys),
        )
        settings_obj.setValue(
            self.settings_key(HIDDEN_COLUMNS_JSON_KEY, settings_prefix=settings_prefix),
            json.dumps(hidden_columns),
        )
        settings_obj.setValue(
            self.settings_key(HIDDEN_COLUMN_KEYS_JSON_KEY, settings_prefix=settings_prefix),
            json.dumps(hidden_column_keys),
        )
        settings_obj.setValue(
            self.settings_key(COLUMNS_MOVABLE_KEY, settings_prefix=settings_prefix),
            bool(header.sectionsMovable()),
        )
        settings_obj.sync()

    def restore_state(
        self,
        header: "QHeaderView",
        *,
        column_specs: Sequence[CatalogColumnSpec],
        settings: QSettings | None = None,
        settings_prefix: str | None = None,
    ) -> bool:
        settings_obj = self._resolve_settings(settings)
        normalized_specs = tuple(column_specs)
        if settings_obj is None:
            self._apply_default_hidden_columns(header, normalized_specs)
            return False

        current_keys = [spec.key for spec in normalized_specs]
        current_label_tokens = self._label_tokens([spec.header_text for spec in normalized_specs])
        previous_signal_state = header.blockSignals(True)
        target_sections_movable = self.load_columns_movable_state(
            settings=settings_obj,
            settings_prefix=settings_prefix,
            default=bool(header.sectionsMovable()),
        )
        restored = False
        try:
            header.setSectionsMovable(True)

            native_state = settings_obj.value(
                self.settings_key(HEADER_STATE_KEY, settings_prefix=settings_prefix),
                None,
                QByteArray,
            )
            key_order = self.load_column_key_order(
                settings=settings_obj,
                settings_prefix=settings_prefix,
            )
            legacy_labels = self.load_legacy_header_labels(
                settings=settings_obj,
                settings_prefix=settings_prefix,
            )
            hidden_column_keys = self.load_hidden_column_keys(
                settings=settings_obj,
                settings_prefix=settings_prefix,
            )
            legacy_hidden_columns = self.load_legacy_hidden_columns(
                settings=settings_obj,
                settings_prefix=settings_prefix,
            )

            native_state_restored = False
            if isinstance(native_state, QByteArray) and not native_state.isEmpty():
                if key_order and self._same_token_set(key_order, current_keys):
                    native_state_restored = bool(header.restoreState(native_state))
                elif not key_order and legacy_labels:
                    saved_label_tokens = self._label_tokens(legacy_labels)
                    if self._same_token_set(saved_label_tokens, current_label_tokens):
                        native_state_restored = bool(header.restoreState(native_state))
                restored = restored or native_state_restored

            if not native_state_restored:
                if key_order:
                    self._apply_visual_order_by_keys(header, current_keys, key_order)
                    restored = True
                elif legacy_labels:
                    self._apply_visual_order_by_label_tokens(
                        header,
                        current_label_tokens,
                        self._label_tokens(legacy_labels),
                    )
                    restored = True

            if hidden_column_keys:
                self._apply_hidden_columns_by_keys(header, normalized_specs, hidden_column_keys)
                restored = True
            elif legacy_hidden_columns:
                self._apply_hidden_columns_by_labels(
                    header,
                    normalized_specs,
                    legacy_hidden_columns,
                )
                restored = True
            else:
                self._apply_default_hidden_columns(header, normalized_specs)
        finally:
            header.setSectionsMovable(bool(target_sections_movable))
            header.blockSignals(previous_signal_state)
        return restored

    def load_columns_movable_state(
        self,
        *,
        settings: QSettings | None = None,
        settings_prefix: str | None = None,
        default: bool = False,
    ) -> bool:
        settings_obj = self._resolve_settings(settings)
        if settings_obj is None:
            return bool(default)
        return settings_obj.value(
            self.settings_key(COLUMNS_MOVABLE_KEY, settings_prefix=settings_prefix),
            bool(default),
            bool,
        )

    def load_column_key_order(
        self,
        *,
        settings: QSettings | None = None,
        settings_prefix: str | None = None,
    ) -> list[str]:
        settings_obj = self._resolve_settings(settings)
        if settings_obj is None:
            return []
        payload = self._load_json_value(
            settings_obj,
            self.settings_key(HEADER_COLUMN_KEYS_JSON_KEY, settings_prefix=settings_prefix),
            default=[],
        )
        return [str(entry).strip() for entry in payload if str(entry).strip()]

    def load_hidden_column_keys(
        self,
        *,
        settings: QSettings | None = None,
        settings_prefix: str | None = None,
    ) -> list[str]:
        settings_obj = self._resolve_settings(settings)
        if settings_obj is None:
            return []
        payload = self._load_json_value(
            settings_obj,
            self.settings_key(HIDDEN_COLUMN_KEYS_JSON_KEY, settings_prefix=settings_prefix),
            default=[],
        )
        return [str(entry).strip() for entry in payload if str(entry).strip()]

    def load_legacy_header_labels(
        self,
        *,
        settings: QSettings | None = None,
        settings_prefix: str | None = None,
    ) -> list[str]:
        settings_obj = self._resolve_settings(settings)
        if settings_obj is None:
            return []

        direct_labels = settings_obj.value(
            self.settings_key(HEADER_LABELS_KEY, settings_prefix=settings_prefix),
            [],
            list,
        )
        if isinstance(direct_labels, list) and direct_labels:
            return [str(label).strip() for label in direct_labels if str(label).strip()]

        payload = self._load_json_value(
            settings_obj,
            self.settings_key(HEADER_LABELS_JSON_KEY, settings_prefix=settings_prefix),
            default=[],
        )
        return [str(entry).strip() for entry in payload if str(entry).strip()]

    def load_legacy_hidden_columns(
        self,
        *,
        settings: QSettings | None = None,
        settings_prefix: str | None = None,
    ) -> list[tuple[str, int]]:
        settings_obj = self._resolve_settings(settings)
        if settings_obj is None:
            return []

        payload = self._load_json_value(
            settings_obj,
            self.settings_key(HIDDEN_COLUMNS_JSON_KEY, settings_prefix=settings_prefix),
            default=[],
        )
        hidden_columns: list[tuple[str, int]] = []
        for entry in payload:
            if not isinstance(entry, dict):
                continue
            label = str(entry.get("label") or "").strip()
            if not label:
                continue
            try:
                occurrence = int(entry.get("occurrence", 0))
            except (TypeError, ValueError):
                occurrence = 0
            hidden_columns.append((label, max(0, occurrence)))
        return hidden_columns

    def _capture_hidden_columns_payload(
        self,
        header: "QHeaderView",
        column_specs: Sequence[CatalogColumnSpec],
    ) -> list[dict[str, int | str]]:
        label_tokens = self._label_tokens([spec.header_text for spec in column_specs])
        payload: list[dict[str, int | str]] = []
        for logical_index, spec in enumerate(column_specs):
            if not header.isSectionHidden(logical_index):
                continue
            label, occurrence = label_tokens[logical_index]
            payload.append(
                {
                    "key": spec.key,
                    "label": label,
                    "occurrence": occurrence,
                }
            )
        return payload

    @staticmethod
    def _normalize_prefix(settings_prefix: str | None) -> str:
        return str(settings_prefix or "").strip().strip("/")

    def _resolve_settings(self, settings: QSettings | None) -> QSettings | None:
        return settings if settings is not None else self._settings

    @staticmethod
    def _visual_order(header: "QHeaderView", column_count: int) -> list[int]:
        return sorted(
            range(column_count),
            key=lambda logical_index: (
                header.visualIndex(logical_index)
                if header.visualIndex(logical_index) >= 0
                else 10_000 + logical_index
            ),
        )

    @staticmethod
    def _label_tokens(labels: Sequence[str]) -> list[tuple[str, int]]:
        occurrences: dict[str, int] = {}
        tokens: list[tuple[str, int]] = []
        for label in labels:
            normalized_label = str(label or "")
            occurrence = occurrences.get(normalized_label, 0)
            tokens.append((normalized_label, occurrence))
            occurrences[normalized_label] = occurrence + 1
        return tokens

    @staticmethod
    def _same_token_set(left: Sequence[object], right: Sequence[object]) -> bool:
        return len(left) == len(right) and sorted(left) == sorted(right)

    def _apply_visual_order_by_keys(
        self,
        header: "QHeaderView",
        current_keys: Sequence[str],
        ordered_keys: Sequence[str],
    ) -> None:
        positions: dict[str, list[int]] = {}
        for logical_index, key in enumerate(current_keys):
            positions.setdefault(key, []).append(logical_index)
        self._apply_visual_order(
            header,
            [positions.get(key, [None]).pop(0) for key in ordered_keys if positions.get(key)],
        )

    def _apply_visual_order_by_label_tokens(
        self,
        header: "QHeaderView",
        current_label_tokens: Sequence[tuple[str, int]],
        ordered_label_tokens: Sequence[tuple[str, int]],
    ) -> None:
        token_to_index = {
            token: logical_index for logical_index, token in enumerate(current_label_tokens)
        }
        self._apply_visual_order(
            header,
            [token_to_index[token] for token in ordered_label_tokens if token in token_to_index],
        )

    @staticmethod
    def _apply_visual_order(header: "QHeaderView", logical_indices: Sequence[int]) -> None:
        for visual_index, logical_index in enumerate(logical_indices):
            current_visual_index = header.visualIndex(logical_index)
            if current_visual_index >= 0 and current_visual_index != visual_index:
                header.moveSection(current_visual_index, visual_index)

    def _apply_hidden_columns_by_keys(
        self,
        header: "QHeaderView",
        column_specs: Sequence[CatalogColumnSpec],
        hidden_column_keys: Sequence[str],
    ) -> None:
        hidden_key_set = {str(key).strip() for key in hidden_column_keys if str(key).strip()}
        for logical_index, spec in enumerate(column_specs):
            header.setSectionHidden(logical_index, spec.key in hidden_key_set)

    def _apply_hidden_columns_by_labels(
        self,
        header: "QHeaderView",
        column_specs: Sequence[CatalogColumnSpec],
        hidden_columns: Sequence[tuple[str, int]],
    ) -> None:
        hidden_token_set = set(hidden_columns)
        label_tokens = self._label_tokens([spec.header_text for spec in column_specs])
        for logical_index, token in enumerate(label_tokens):
            header.setSectionHidden(logical_index, token in hidden_token_set)

    @staticmethod
    def _apply_default_hidden_columns(
        header: "QHeaderView",
        column_specs: Sequence[CatalogColumnSpec],
    ) -> None:
        for logical_index, spec in enumerate(column_specs):
            header.setSectionHidden(logical_index, bool(spec.hidden_by_default))

    @staticmethod
    def _load_json_value(
        settings: QSettings,
        key: str,
        *,
        default,
    ):
        raw_value = settings.value(key, None)
        if raw_value in (None, ""):
            return default
        if isinstance(raw_value, (list, dict)):
            return raw_value
        if isinstance(raw_value, str):
            try:
                return json.loads(raw_value)
            except Exception:
                return default
        return default


__all__ = [
    "COLUMNS_MOVABLE_KEY",
    "CatalogHeaderStateManager",
    "HEADER_COLUMN_KEYS_JSON_KEY",
    "HEADER_LABELS_JSON_KEY",
    "HEADER_LABELS_KEY",
    "HEADER_STATE_KEY",
    "HIDDEN_COLUMN_KEYS_JSON_KEY",
    "HIDDEN_COLUMNS_JSON_KEY",
]

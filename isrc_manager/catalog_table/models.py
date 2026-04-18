"""Pure snapshot and role definitions for the catalog-table migration."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Mapping

from PySide6.QtCore import Qt

SortRole = int(Qt.ItemDataRole.UserRole) + 1
SearchTextRole = SortRole + 1
TrackIdRole = SortRole + 2
ColumnKeyRole = SortRole + 3
RawValueRole = SortRole + 4
_NATURAL_SORT_PATTERN = re.compile(r"(\d+)")


def _coerce_text(value: object | None) -> str:
    return "" if value is None else str(value)


def natural_sort_key(value: object | None) -> tuple[tuple[int, object], ...]:
    """Return a deterministic natural-sort key for mixed alphanumeric text."""

    text = _coerce_text(value)
    parts = _NATURAL_SORT_PATTERN.split(text)
    return tuple((0, int(part)) if part.isdigit() else (1, part.casefold()) for part in parts)


def comparison_sort_key(value: object | None) -> tuple[int, object]:
    """Normalize supported sort payloads into one comparable key structure."""

    if value is None:
        return (4, ())
    if isinstance(value, bool):
        return (0, int(value))
    if isinstance(value, (int, float)):
        return (0, value)
    if isinstance(value, str):
        return (1, natural_sort_key(value))
    if isinstance(value, tuple):
        return (2, tuple(comparison_sort_key(item) for item in value))
    if isinstance(value, list):
        return (2, tuple(comparison_sort_key(item) for item in value))
    return (3, natural_sort_key(value))


@dataclass(frozen=True, slots=True)
class CatalogColumnSpec:
    """Stable column metadata for the future catalog table model."""

    key: str
    header_text: str
    searchable: bool = True
    sortable: bool = True
    hidden_by_default: bool = False
    legacy_header_labels: tuple[str, ...] = ()
    notes: str | None = None

    def __post_init__(self) -> None:
        key = str(self.key or "").strip()
        if not key:
            raise ValueError("Catalog column keys must be non-empty.")
        header_text = _coerce_text(self.header_text).strip()
        if not header_text:
            raise ValueError("Catalog column headers must be non-empty.")
        legacy_labels = tuple(
            str(label).strip() for label in self.legacy_header_labels if str(label).strip()
        )
        object.__setattr__(self, "key", key)
        object.__setattr__(self, "header_text", header_text)
        object.__setattr__(self, "legacy_header_labels", legacy_labels)
        object.__setattr__(
            self,
            "notes",
            str(self.notes).strip() if self.notes is not None else None,
        )

    @property
    def all_header_labels(self) -> tuple[str, ...]:
        return (self.header_text, *self.legacy_header_labels)


@dataclass(frozen=True, slots=True)
class CatalogCellValue:
    """Value bundle for one cell before it is exposed through Qt roles."""

    display_text: str = ""
    sort_value: object | None = None
    search_text: str = ""
    raw_value: object | None = None
    tooltip: str | None = None
    decoration_key: str | None = None
    decoration: object | None = None
    text_alignment: int | None = None

    def __post_init__(self) -> None:
        display_text = _coerce_text(self.display_text)
        search_text = _coerce_text(self.search_text or display_text)
        raw_value = self.raw_value if self.raw_value is not None else display_text
        sort_value = self.sort_value if self.sort_value is not None else raw_value
        tooltip = str(self.tooltip) if self.tooltip is not None else None
        decoration_key = str(self.decoration_key) if self.decoration_key is not None else None
        text_alignment = int(self.text_alignment) if self.text_alignment is not None else None
        object.__setattr__(self, "display_text", display_text)
        object.__setattr__(self, "search_text", search_text)
        object.__setattr__(self, "raw_value", raw_value)
        object.__setattr__(self, "sort_value", sort_value)
        object.__setattr__(self, "tooltip", tooltip)
        object.__setattr__(self, "decoration_key", decoration_key)
        object.__setattr__(self, "decoration", self.decoration)
        object.__setattr__(self, "text_alignment", text_alignment)

    @classmethod
    def from_value(
        cls,
        value: object | None,
        *,
        display_text: str | None = None,
        sort_value: object | None = None,
        search_text: str | None = None,
        tooltip: str | None = None,
        decoration_key: str | None = None,
        decoration: object | None = None,
        text_alignment: int | None = None,
    ) -> "CatalogCellValue":
        """Build a cell payload from one raw value while allowing overrides."""

        resolved_display = _coerce_text(value if display_text is None else display_text)
        resolved_search = search_text if search_text is not None else resolved_display
        return cls(
            display_text=resolved_display,
            sort_value=sort_value,
            search_text=resolved_search,
            raw_value=value,
            tooltip=tooltip,
            decoration_key=decoration_key,
            decoration=decoration,
            text_alignment=text_alignment,
        )


@dataclass(frozen=True, slots=True)
class CatalogRowSnapshot:
    """Row payload keyed by stable catalog column identifiers."""

    track_id: int
    cells_by_key: Mapping[str, CatalogCellValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        normalized_cells: dict[str, CatalogCellValue] = {}
        for column_key, cell in dict(self.cells_by_key).items():
            normalized_key = str(column_key or "").strip()
            if not normalized_key:
                raise ValueError("Catalog row cells must use non-empty column keys.")
            normalized_cells[normalized_key] = (
                cell if isinstance(cell, CatalogCellValue) else CatalogCellValue.from_value(cell)
            )
        object.__setattr__(self, "track_id", int(self.track_id))
        object.__setattr__(self, "cells_by_key", normalized_cells)

    def cell(self, column_key: str) -> CatalogCellValue | None:
        return self.cells_by_key.get(column_key)


@dataclass(frozen=True, slots=True)
class CatalogSnapshot:
    """Catalog table snapshot prepared for later cutover phases."""

    column_specs: tuple[CatalogColumnSpec, ...] = ()
    rows: tuple[CatalogRowSnapshot, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        normalized_column_specs = tuple(self.column_specs)
        normalized_rows = tuple(self.rows)

        seen_column_keys: set[str] = set()
        duplicate_column_keys: list[str] = []
        for column_spec in normalized_column_specs:
            if column_spec.key in seen_column_keys:
                duplicate_column_keys.append(column_spec.key)
            seen_column_keys.add(column_spec.key)
        if duplicate_column_keys:
            raise ValueError(
                "Catalog snapshot column keys must be unique: "
                + ", ".join(sorted(set(duplicate_column_keys)))
            )

        seen_track_ids: set[int] = set()
        duplicate_track_ids: list[int] = []
        for row in normalized_rows:
            if row.track_id in seen_track_ids:
                duplicate_track_ids.append(row.track_id)
            seen_track_ids.add(row.track_id)
        if duplicate_track_ids:
            raise ValueError(
                "Catalog snapshot track ids must be unique: "
                + ", ".join(str(track_id) for track_id in sorted(set(duplicate_track_ids)))
            )

        object.__setattr__(self, "column_specs", normalized_column_specs)
        object.__setattr__(self, "rows", normalized_rows)
        object.__setattr__(self, "metadata", dict(self.metadata))

    @classmethod
    def empty(cls) -> "CatalogSnapshot":
        return cls()

    @property
    def column_keys(self) -> tuple[str, ...]:
        return tuple(column.key for column in self.column_specs)

    def column_index(self, column_key: str) -> int | None:
        for index, column_spec in enumerate(self.column_specs):
            if column_spec.key == column_key:
                return index
        return None

    def column_spec(self, column_key: str) -> CatalogColumnSpec | None:
        column_index = self.column_index(column_key)
        if column_index is None:
            return None
        return self.column_specs[column_index]


__all__ = [
    "ColumnKeyRole",
    "comparison_sort_key",
    "CatalogCellValue",
    "CatalogColumnSpec",
    "CatalogRowSnapshot",
    "CatalogSnapshot",
    "natural_sort_key",
    "RawValueRole",
    "SearchTextRole",
    "SortRole",
    "TrackIdRole",
]

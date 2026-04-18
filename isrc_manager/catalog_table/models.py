"""Snapshot and role definitions for the staged catalog-table cutover."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from PySide6.QtCore import Qt

SortRole = int(Qt.ItemDataRole.UserRole) + 1
SearchTextRole = SortRole + 1
TrackIdRole = SortRole + 2
ColumnKeyRole = SortRole + 3
RawValueRole = SortRole + 4


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


@dataclass(frozen=True, slots=True)
class CatalogCellValue:
    """Value bundle for one cell before it is exposed through Qt roles."""

    display_text: str = ""
    sort_value: object | None = None
    search_text: str = ""
    raw_value: object | None = None
    tooltip: str | None = None
    decoration_key: str | None = None
    text_alignment: int | None = None


@dataclass(frozen=True, slots=True)
class CatalogRowSnapshot:
    """Row payload keyed by stable catalog column identifiers."""

    track_id: int
    cells_by_key: Mapping[str, CatalogCellValue] = field(default_factory=dict)

    def cell(self, column_key: str) -> CatalogCellValue | None:
        return self.cells_by_key.get(column_key)


@dataclass(frozen=True, slots=True)
class CatalogSnapshot:
    """Catalog table snapshot prepared for later cutover phases."""

    column_specs: tuple[CatalogColumnSpec, ...] = ()
    rows: tuple[CatalogRowSnapshot, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)

    @classmethod
    def empty(cls) -> "CatalogSnapshot":
        return cls()

    @property
    def column_keys(self) -> tuple[str, ...]:
        return tuple(column.key for column in self.column_specs)


__all__ = [
    "ColumnKeyRole",
    "CatalogCellValue",
    "CatalogColumnSpec",
    "CatalogRowSnapshot",
    "CatalogSnapshot",
    "RawValueRole",
    "SearchTextRole",
    "SortRole",
    "TrackIdRole",
]

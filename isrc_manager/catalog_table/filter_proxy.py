"""Dormant `QSortFilterProxyModel` seam for the staged catalog-table migration."""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import QModelIndex, QObject, QSortFilterProxyModel


class CatalogFilterProxyModel(QSortFilterProxyModel):
    """Filter/sort proxy scaffold reserved for the later cutover phases."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._search_text = ""
        self._search_column_key: str | None = None
        self._explicit_track_ids: frozenset[int] | None = None
        self.setDynamicSortFilter(True)

    def set_search_text(self, search_text: str | None) -> None:
        normalized = (search_text or "").strip()
        if normalized == self._search_text:
            return
        self._search_text = normalized
        self.invalidateFilter()

    def set_search_column_key(self, column_key: str | None) -> None:
        normalized = (column_key or "").strip() or None
        if normalized == self._search_column_key:
            return
        self._search_column_key = normalized
        self.invalidateFilter()

    def set_explicit_track_ids(self, track_ids: Iterable[int] | None) -> None:
        normalized = (
            frozenset(int(track_id) for track_id in track_ids)
            if track_ids is not None
            else None
        )
        if normalized == self._explicit_track_ids:
            return
        self._explicit_track_ids = normalized
        self.invalidateFilter()

    def search_text(self) -> str:
        return self._search_text

    def search_column_key(self) -> str | None:
        return self._search_column_key

    def explicit_track_ids(self) -> frozenset[int] | None:
        return self._explicit_track_ids

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        del source_row, source_parent
        # Phase A1 keeps filtering behavior unchanged by not wiring this proxy live.
        return True


__all__ = ["CatalogFilterProxyModel"]

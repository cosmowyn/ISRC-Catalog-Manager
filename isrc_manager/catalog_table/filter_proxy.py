"""Pure `QSortFilterProxyModel` for catalog-table search and sorting."""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import QModelIndex, QObject, QSortFilterProxyModel, Qt

from .models import (
    ColumnKeyRole,
    SearchTextRole,
    SortRole,
    TrackIdRole,
    comparison_sort_key,
    natural_sort_key,
)


class CatalogFilterProxyModel(QSortFilterProxyModel):
    """Own standalone catalog-table search text, search-column, and track filters."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._search_text = ""
        self._normalized_search_text = ""
        self._search_column_key: str | None = None
        self._explicit_track_ids: frozenset[int] | None = None
        self.setDynamicSortFilter(True)
        self.setSortRole(SortRole)

    def set_search_text(self, search_text: str | None) -> None:
        normalized = (search_text or "").strip()
        if normalized == self._search_text:
            return
        self._search_text = normalized
        self._normalized_search_text = normalized.casefold()
        self.invalidateFilter()

    def set_search_column_key(self, column_key: str | None) -> None:
        normalized = (column_key or "").strip() or None
        if normalized == self._search_column_key:
            return
        self._search_column_key = normalized
        self.invalidateFilter()

    def set_explicit_track_ids(self, track_ids: Iterable[int] | None) -> None:
        if track_ids is None:
            normalized = None
        else:
            collected: set[int] = set()
            for track_id in track_ids:
                try:
                    normalized_track_id = int(track_id)
                except (TypeError, ValueError):
                    continue
                if normalized_track_id > 0:
                    collected.add(normalized_track_id)
            normalized = frozenset(collected)
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
        model = self.sourceModel()
        if model is None:
            return False

        if self._explicit_track_ids is not None:
            track_id = self._track_id_for_source_row(
                source_row,
                source_parent=source_parent,
            )
            if track_id is None or track_id not in self._explicit_track_ids:
                return False

        if not self._normalized_search_text:
            return True

        for source_column in self._searchable_source_columns():
            model_index = model.index(source_row, source_column, source_parent)
            search_text = model.data(model_index, SearchTextRole)
            if self._normalized_search_text in str(search_text or "").casefold():
                return True
        return False

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:
        model = self.sourceModel()
        if model is None:
            return super().lessThan(left, right)

        left_sort_key = comparison_sort_key(model.data(left, self.sortRole()))
        right_sort_key = comparison_sort_key(model.data(right, self.sortRole()))
        if left_sort_key != right_sort_key:
            return left_sort_key < right_sort_key

        left_display_key = natural_sort_key(model.data(left, int(Qt.ItemDataRole.DisplayRole)))
        right_display_key = natural_sort_key(model.data(right, int(Qt.ItemDataRole.DisplayRole)))
        if left_display_key != right_display_key:
            return left_display_key < right_display_key

        left_track_id = model.data(left, TrackIdRole)
        right_track_id = model.data(right, TrackIdRole)
        if left_track_id != right_track_id:
            return int(left_track_id or 0) < int(right_track_id or 0)
        return left.row() < right.row()

    def _track_id_for_source_row(
        self,
        source_row: int,
        *,
        source_parent: QModelIndex,
    ) -> int | None:
        model = self.sourceModel()
        if model is None or model.columnCount(source_parent) <= 0:
            return None
        track_id = model.data(model.index(source_row, 0, source_parent), TrackIdRole)
        return int(track_id) if track_id is not None else None

    def _searchable_source_columns(self) -> tuple[int, ...]:
        model = self.sourceModel()
        if model is None:
            return ()

        explicit_column = self._source_column_for_key(self._search_column_key)
        if explicit_column is not None:
            return (explicit_column,)

        columns: list[int] = []
        column_spec_getter = getattr(model, "column_spec", None)
        for column in range(model.columnCount()):
            if callable(column_spec_getter):
                column_spec = column_spec_getter(column)
                if column_spec is not None and not column_spec.searchable:
                    continue
            columns.append(column)
        return tuple(columns)

    def _source_column_for_key(self, column_key: str | None) -> int | None:
        if not column_key:
            return None
        model = self.sourceModel()
        if model is None:
            return None
        for column in range(model.columnCount()):
            header_column_key = model.headerData(
                column,
                Qt.Orientation.Horizontal,
                ColumnKeyRole,
            )
            if str(header_column_key or "") == column_key:
                return column
        return None


__all__ = ["CatalogFilterProxyModel"]

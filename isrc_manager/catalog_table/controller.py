"""Pure controller helpers for future catalog-table model/view cutover."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QItemSelectionModel, QModelIndex, QObject, QSortFilterProxyModel

from .filter_proxy import CatalogFilterProxyModel
from .models import TrackIdRole
from .table_model import CatalogTableModel

if TYPE_CHECKING:
    from PySide6.QtCore import QAbstractItemModel
    from PySide6.QtWidgets import QAbstractItemView


class CatalogTableController(QObject):
    """Resolve selection and proxy/source mappings without live production wiring."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._view: QAbstractItemView | None = None
        self._table_model: CatalogTableModel | None = None
        self._filter_proxy: CatalogFilterProxyModel | None = None

    def bind_view(self, view: "QAbstractItemView | None") -> None:
        self._view = view

    def bind_models(
        self,
        *,
        table_model: CatalogTableModel | None,
        filter_proxy: CatalogFilterProxyModel | None = None,
    ) -> None:
        self._table_model = table_model
        self._filter_proxy = filter_proxy

    def source_model(self) -> CatalogTableModel | None:
        return self._table_model

    def proxy_model(self) -> CatalogFilterProxyModel | None:
        return self._filter_proxy

    def active_model(self) -> "QAbstractItemModel | None":
        if self._view is not None and self._view.model() is not None:
            return self._view.model()
        if self._filter_proxy is not None:
            return self._filter_proxy
        return self._table_model

    def map_to_source(self, index: QModelIndex) -> QModelIndex:
        if not index.isValid():
            return QModelIndex()
        model = index.model()
        if isinstance(model, QSortFilterProxyModel):
            return model.mapToSource(index)
        return index

    def map_from_source(self, source_index: QModelIndex) -> QModelIndex:
        if not source_index.isValid():
            return QModelIndex()
        if self._filter_proxy is not None:
            return self._filter_proxy.mapFromSource(source_index)
        return source_index

    def source_index_for_track_id(self, track_id: int, *, column: int = 0) -> QModelIndex:
        if self._table_model is None:
            return QModelIndex()
        source_row = self._table_model.source_row_for_track_id(int(track_id))
        if source_row is None or column < 0 or column >= self._table_model.columnCount():
            return QModelIndex()
        return self._table_model.index(source_row, column)

    def view_index_for_track_id(self, track_id: int, *, column: int = 0) -> QModelIndex:
        return self.map_from_source(self.source_index_for_track_id(track_id, column=column))

    def track_id_for_index(self, index: QModelIndex) -> int | None:
        if not index.isValid():
            return None
        source_index = self.map_to_source(index)
        if not source_index.isValid():
            return None
        model = source_index.model()
        track_id = model.data(source_index, TrackIdRole) if model is not None else None
        if track_id is None:
            return None
        return int(track_id)

    def track_id_for_source_row(self, source_row: int) -> int | None:
        if self._table_model is None:
            return None
        return self._table_model.track_id_for_source_row(source_row)

    def source_row_for_track_id(self, track_id: int) -> int | None:
        if self._table_model is None:
            return None
        return self._table_model.source_row_for_track_id(track_id)

    def current_track_id(self) -> int | None:
        selection_model = self._selection_model()
        if selection_model is None:
            return None
        return self.track_id_for_index(selection_model.currentIndex())

    def selected_track_ids(self) -> tuple[int, ...]:
        selection_model = self._selection_model()
        if selection_model is None:
            return ()

        candidate_indexes: list[QModelIndex] = []
        candidate_rows: set[tuple[object, int]] = set()

        for index in selection_model.selectedRows():
            if index.isValid():
                key = (index.model(), index.row())
                if key not in candidate_rows:
                    candidate_rows.add(key)
                    candidate_indexes.append(index)

        if not candidate_indexes:
            for index in selection_model.selectedIndexes():
                if not index.isValid():
                    continue
                row_index = index.siblingAtColumn(0)
                key = (row_index.model(), row_index.row())
                if key in candidate_rows:
                    continue
                candidate_rows.add(key)
                candidate_indexes.append(row_index)

        if not candidate_indexes:
            current_index = selection_model.currentIndex()
            if current_index.isValid():
                candidate_indexes.append(current_index.siblingAtColumn(0))

        return self._unique_track_ids(self.track_id_for_index(index) for index in candidate_indexes)

    def visible_track_ids(self) -> tuple[int, ...]:
        model = self.active_model()
        if model is None:
            return ()
        return self._unique_track_ids(
            self.track_id_for_index(model.index(row, 0)) for row in range(model.rowCount())
        )

    def selected_or_visible_track_ids(self) -> tuple[int, ...]:
        if (
            self._filter_proxy is not None
            and self._table_model is not None
            and self._filter_proxy.rowCount() < self._table_model.rowCount()
        ):
            visible_track_ids = self.visible_track_ids()
            if visible_track_ids:
                return visible_track_ids
        selected_track_ids = self.selected_track_ids()
        if selected_track_ids:
            return selected_track_ids
        return self.visible_track_ids()

    def effective_context_menu_track_ids(
        self,
        index: QModelIndex | None,
        *,
        selected_track_ids: tuple[int, ...] | None = None,
    ) -> tuple[int, ...]:
        clicked_track_id = self.track_id_for_index(index) if index is not None else None
        normalized_selected = (
            self._unique_track_ids(selected_track_ids)
            if selected_track_ids is not None
            else self.selected_track_ids()
        )
        if clicked_track_id is not None and clicked_track_id in normalized_selected:
            return normalized_selected
        return (clicked_track_id,) if clicked_track_id is not None else ()

    def _selection_model(self) -> QItemSelectionModel | None:
        if self._view is None:
            return None
        return self._view.selectionModel()

    @staticmethod
    def _unique_track_ids(track_ids) -> tuple[int, ...]:
        normalized: list[int] = []
        seen: set[int] = set()
        for value in track_ids or ():
            if value is None:
                continue
            try:
                track_id = int(value)
            except (TypeError, ValueError):
                continue
            if track_id <= 0 or track_id in seen:
                continue
            seen.add(track_id)
            normalized.append(track_id)
        return tuple(normalized)


__all__ = ["CatalogTableController"]

"""Controller helpers for catalog-table cutover across widget and model/view paths."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from PySide6.QtCore import QItemSelectionModel, QModelIndex, QObject, QSortFilterProxyModel, Qt

from isrc_manager.domain.standard_fields import STANDARD_FIELD_BY_KEY, standard_field_spec_for_label

from .filter_proxy import CatalogFilterProxyModel
from .models import ColumnKeyRole, TrackIdRole
from .table_model import CatalogTableModel

if TYPE_CHECKING:
    from PySide6.QtCore import QAbstractItemModel
    from PySide6.QtWidgets import QAbstractItemView


@dataclass(frozen=True, slots=True)
class CatalogCellTarget:
    """Describe the clicked/view cell without binding the shell to widget item APIs."""

    row: int = -1
    column: int = -1
    track_id: int | None = None
    kind: str = "unknown"
    header_text: str = ""
    standard_field_key: str | None = None
    standard_field_type: str | None = None
    standard_media_key: str | None = None
    custom_field: Mapping[str, object] | None = None
    custom_field_id: int | None = None
    custom_field_type: str | None = None


class CatalogTableController(QObject):
    """Resolve selection, routing, and proxy/source mappings across staged cutovers."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._view: QAbstractItemView | None = None
        self._table_model: CatalogTableModel | None = None
        self._filter_proxy: CatalogFilterProxyModel | None = None
        self._track_id_for_row: Callable[[int], int | None] | None = None
        self._is_row_hidden: Callable[[int], bool] | None = None

    def bind_view(self, view: "QAbstractItemView | None") -> None:
        self._view = view

    def bind_widget_seams(
        self,
        *,
        track_id_for_row: Callable[[int], int | None] | None = None,
        is_row_hidden: Callable[[int], bool] | None = None,
    ) -> None:
        self._track_id_for_row = track_id_for_row
        self._is_row_hidden = is_row_hidden

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

    def column_for_key(self, column_key: str | None) -> int | None:
        normalized_key = str(column_key or "").strip()
        if not normalized_key:
            return None
        model = self.active_model()
        if model is None:
            return None
        for column in range(model.columnCount()):
            header_key = model.headerData(column, Qt.Horizontal, ColumnKeyRole)
            if str(header_key or "") == normalized_key:
                return column
        return None

    def visible_indexes(self, *, column: int = 0) -> tuple[QModelIndex, ...]:
        model = self.active_model()
        if model is None:
            return ()
        normalized_column = int(column)
        if normalized_column < 0 or normalized_column >= model.columnCount():
            return ()
        return tuple(
            model.index(row, normalized_column)
            for row in range(model.rowCount())
            if not self._row_is_hidden(row)
        )

    def track_id_for_index(self, index: QModelIndex) -> int | None:
        if not index.isValid():
            return None
        source_index = self.map_to_source(index.siblingAtColumn(0))
        if not source_index.isValid():
            return None
        model = source_index.model()
        track_id = model.data(source_index, TrackIdRole) if model is not None else None
        if track_id is None and self._track_id_for_row is not None:
            try:
                track_id = self._track_id_for_row(int(source_index.row()))
            except Exception:
                track_id = None
        if track_id is None:
            return None
        return int(track_id)

    def track_id_for_source_row(self, source_row: int) -> int | None:
        if self._table_model is None:
            if self._track_id_for_row is None:
                return None
            try:
                return self._track_id_for_row(int(source_row))
            except Exception:
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

    def has_filtered_rows(self) -> bool:
        if (
            self._filter_proxy is not None
            and self._table_model is not None
            and self._filter_proxy.rowCount() < self._table_model.rowCount()
        ):
            return True
        row_count = self._active_row_count()
        return any(self._row_is_hidden(row) for row in range(row_count))

    def selected_track_ids(self) -> tuple[int, ...]:
        selection_model = self._selection_model()
        if selection_model is None:
            return ()

        candidate_indexes: list[QModelIndex] = []
        candidate_rows: set[tuple[object, int]] = set()

        for index in selection_model.selectedRows():
            if index.isValid():
                key = (index.model(), index.row())
                if key in candidate_rows or self._row_is_hidden(index.row()):
                    continue
                candidate_rows.add(key)
                candidate_indexes.append(index.siblingAtColumn(0))

        if not candidate_indexes:
            for index in selection_model.selectedIndexes():
                if not index.isValid():
                    continue
                row_index = index.siblingAtColumn(0)
                key = (row_index.model(), row_index.row())
                if key in candidate_rows or self._row_is_hidden(row_index.row()):
                    continue
                candidate_rows.add(key)
                candidate_indexes.append(row_index)

        if not candidate_indexes:
            current_index = selection_model.currentIndex()
            if current_index.isValid() and not self._row_is_hidden(current_index.row()):
                candidate_indexes.append(current_index.siblingAtColumn(0))

        return self._unique_track_ids(self.track_id_for_index(index) for index in candidate_indexes)

    def visible_track_ids(self) -> tuple[int, ...]:
        model = self.active_model()
        if model is None:
            return ()
        return self._unique_track_ids(
            self.track_id_for_index(model.index(row, 0))
            for row in range(model.rowCount())
            if not self._row_is_hidden(row)
        )

    def selected_or_visible_track_ids(self) -> tuple[int, ...]:
        if self.has_filtered_rows():
            visible_track_ids = self.visible_track_ids()
            if visible_track_ids:
                return visible_track_ids
        return self.selected_track_ids()

    def default_conversion_track_ids(self) -> tuple[int, ...]:
        selected_track_ids = self.selected_track_ids()
        if selected_track_ids:
            return selected_track_ids
        if self.has_filtered_rows():
            return self.visible_track_ids()
        return ()

    def effective_context_menu_track_ids(
        self,
        index: QModelIndex | int | None,
        *,
        selected_track_ids: tuple[int, ...] | None = None,
    ) -> tuple[int, ...]:
        clicked_track_id = self._context_track_id(index)
        normalized_selected = (
            self._unique_track_ids(selected_track_ids)
            if selected_track_ids is not None
            else self.selected_track_ids()
        )
        if clicked_track_id is not None and clicked_track_id in normalized_selected:
            return normalized_selected
        return (clicked_track_id,) if clicked_track_id is not None else ()

    def prepare_context_menu_selection(self, index: QModelIndex | None) -> QModelIndex:
        if index is None or not index.isValid():
            return QModelIndex()
        selection_model = self._selection_model()
        if selection_model is None:
            return index

        selected_rows = {selected.row() for selected in selection_model.selectedRows()}
        if not selected_rows:
            selected_rows = {selected.row() for selected in selection_model.selectedIndexes()}
        if index.row() in selected_rows:
            selection_model.setCurrentIndex(index, QItemSelectionModel.NoUpdate)
        else:
            selection_model.select(
                index, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows
            )
            selection_model.setCurrentIndex(index, QItemSelectionModel.NoUpdate)
        current_index = selection_model.currentIndex()
        return current_index if current_index.isValid() else index

    def cell_target(
        self,
        index: QModelIndex | None,
        *,
        base_column_count: int,
        custom_fields: Sequence[Mapping[str, object]] | None = None,
    ) -> CatalogCellTarget:
        if index is None or not index.isValid():
            return CatalogCellTarget()

        row = int(index.row())
        column = int(index.column())
        track_id = self.track_id_for_index(index)
        header_text = self._header_text_for_column(column)
        column_key = self._column_key_for_column(column)
        normalized_base_column_count = max(0, int(base_column_count))

        if column < normalized_base_column_count:
            standard_spec = None
            if column_key.startswith("base:"):
                standard_spec = STANDARD_FIELD_BY_KEY.get(column_key.split(":", 1)[1])
            if standard_spec is None:
                standard_spec = standard_field_spec_for_label(header_text)
            return CatalogCellTarget(
                row=row,
                column=column,
                track_id=track_id,
                kind="standard",
                header_text=header_text,
                standard_field_key=standard_spec.key if standard_spec is not None else None,
                standard_field_type=standard_spec.field_type if standard_spec is not None else None,
                standard_media_key=standard_spec.media_key if standard_spec is not None else None,
            )

        field_index = column - normalized_base_column_count
        field = None
        if custom_fields is not None:
            if column_key.startswith("custom:"):
                try:
                    column_field_id = int(column_key.split(":", 1)[1])
                except (TypeError, ValueError):
                    column_field_id = None
                if column_field_id is not None:
                    field = next(
                        (
                            candidate
                            for candidate in custom_fields
                            if int(candidate.get("id") or 0) == column_field_id
                        ),
                        None,
                    )
            if field is None and 0 <= field_index < len(custom_fields):
                field = custom_fields[field_index]
        field_id = None
        if field is not None:
            try:
                field_id = int(field.get("id"))
            except (TypeError, ValueError):
                field_id = None
        field_type = str(field.get("field_type") or "").strip() if field is not None else None
        return CatalogCellTarget(
            row=row,
            column=column,
            track_id=track_id,
            kind="custom" if field is not None else "unknown",
            header_text=header_text,
            custom_field=field,
            custom_field_id=field_id if field_id is not None and field_id > 0 else None,
            custom_field_type=field_type,
        )

    def _selection_model(self) -> QItemSelectionModel | None:
        if self._view is None:
            return None
        return self._view.selectionModel()

    def _active_row_count(self) -> int:
        model = self.active_model()
        return int(model.rowCount()) if model is not None else 0

    def _row_is_hidden(self, row: int) -> bool:
        if self._is_row_hidden is not None:
            try:
                return bool(self._is_row_hidden(int(row)))
            except Exception:
                return False
        view = self._view
        is_row_hidden = getattr(view, "isRowHidden", None)
        if callable(is_row_hidden):
            try:
                return bool(is_row_hidden(int(row)))
            except Exception:
                return False
        return False

    def _context_track_id(self, value: QModelIndex | int | None) -> int | None:
        if isinstance(value, QModelIndex):
            return self.track_id_for_index(value)
        if value is None:
            return None
        try:
            track_id = int(value)
        except (TypeError, ValueError):
            return None
        return track_id if track_id > 0 else None

    def _header_text_for_column(self, column: int) -> str:
        if column < 0:
            return ""
        view = self._view
        header_item_lookup = getattr(view, "horizontalHeaderItem", None)
        if callable(header_item_lookup):
            header_item = header_item_lookup(int(column))
            if header_item is not None:
                return str(header_item.text() or "")
        model = self.active_model()
        if model is None:
            return ""
        return str(model.headerData(int(column), Qt.Horizontal, Qt.DisplayRole) or "")

    def _column_key_for_column(self, column: int) -> str:
        if column < 0:
            return ""
        model = self.active_model()
        if model is None:
            return ""
        return str(model.headerData(int(column), Qt.Horizontal, ColumnKeyRole) or "")

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


__all__ = ["CatalogCellTarget", "CatalogTableController"]

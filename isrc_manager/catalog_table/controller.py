"""Controller scaffolding for the staged catalog-table migration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QModelIndex, QObject

from .filter_proxy import CatalogFilterProxyModel
from .table_model import CatalogTableModel

if TYPE_CHECKING:
    from PySide6.QtWidgets import QAbstractItemView


class CatalogTableController(QObject):
    """Future coordinator for selection, mapping, menus, and double-click routing."""

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

    def selected_track_ids(self) -> tuple[int, ...]:
        raise NotImplementedError(
            "Phase A1 scaffolding only; selection helpers are implemented in later phases."
        )

    def visible_track_ids(self) -> tuple[int, ...]:
        raise NotImplementedError(
            "Phase A1 scaffolding only; visible-row semantics are implemented in later phases."
        )

    def track_id_for_index(self, index: QModelIndex) -> int | None:
        del index
        raise NotImplementedError(
            "Phase A1 scaffolding only; proxy/source mapping is implemented in later phases."
        )


__all__ = ["CatalogTableController"]

"""Zoom-controller scaffolding for the staged catalog-table migration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QObject

if TYPE_CHECKING:
    from PySide6.QtWidgets import QAbstractItemView

CATALOG_ZOOM_DEFAULT_PERCENT = 100
CATALOG_ZOOM_MIN_PERCENT = 80
CATALOG_ZOOM_MAX_PERCENT = 160
CATALOG_ZOOM_STEP_PERCENT = 5


class CatalogZoomController(QObject):
    """Future home of catalog view-density zoom state and persistence hooks."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._view: QAbstractItemView | None = None
        self._zoom_percent = CATALOG_ZOOM_DEFAULT_PERCENT

    def bind_view(self, view: "QAbstractItemView | None") -> None:
        self._view = view

    def zoom_percent(self) -> int:
        return self._zoom_percent

    def set_zoom_percent(self, zoom_percent: int) -> None:
        self._zoom_percent = int(zoom_percent)
        # Phase A1 intentionally stops short of applying, clamping, or persisting zoom.

    def reset_zoom(self) -> None:
        self._zoom_percent = CATALOG_ZOOM_DEFAULT_PERCENT


__all__ = [
    "CATALOG_ZOOM_DEFAULT_PERCENT",
    "CATALOG_ZOOM_MAX_PERCENT",
    "CATALOG_ZOOM_MIN_PERCENT",
    "CATALOG_ZOOM_STEP_PERCENT",
    "CatalogZoomController",
]

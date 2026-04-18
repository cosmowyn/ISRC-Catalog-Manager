"""Catalog-table scaffolding for the staged `QTableView` migration."""

from .controller import CatalogTableController
from .filter_proxy import CatalogFilterProxyModel
from .header_state import CatalogHeaderStateManager
from .models import (
    CatalogCellValue,
    CatalogColumnSpec,
    CatalogRowSnapshot,
    CatalogSnapshot,
    ColumnKeyRole,
    RawValueRole,
    SearchTextRole,
    SortRole,
    TrackIdRole,
)
from .table_model import CatalogTableModel
from .zoom import (
    CATALOG_ZOOM_DEFAULT_PERCENT,
    CATALOG_ZOOM_MAX_PERCENT,
    CATALOG_ZOOM_MIN_PERCENT,
    CATALOG_ZOOM_STEP_PERCENT,
    CatalogZoomController,
)

__all__ = [
    "CATALOG_ZOOM_DEFAULT_PERCENT",
    "CATALOG_ZOOM_MAX_PERCENT",
    "CATALOG_ZOOM_MIN_PERCENT",
    "CATALOG_ZOOM_STEP_PERCENT",
    "ColumnKeyRole",
    "CatalogCellValue",
    "CatalogColumnSpec",
    "CatalogFilterProxyModel",
    "CatalogHeaderStateManager",
    "CatalogRowSnapshot",
    "CatalogSnapshot",
    "CatalogTableController",
    "CatalogTableModel",
    "CatalogZoomController",
    "RawValueRole",
    "SearchTextRole",
    "SortRole",
    "TrackIdRole",
]

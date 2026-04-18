"""Header-state scaffolding for the staged catalog-table migration."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from PySide6.QtCore import QSettings

from .models import CatalogColumnSpec

if TYPE_CHECKING:
    from PySide6.QtWidgets import QHeaderView


class CatalogHeaderStateManager:
    """Future home of catalog header persistence and legacy compatibility logic."""

    def __init__(self, settings: QSettings | None = None) -> None:
        self._settings = settings

    def save_state(
        self,
        header: "QHeaderView",
        *,
        column_specs: Sequence[CatalogColumnSpec],
        settings: QSettings | None = None,
    ) -> None:
        del header, column_specs, settings
        raise NotImplementedError(
            "Phase A1 scaffolding only; header persistence is implemented in Phase A3."
        )

    def restore_state(
        self,
        header: "QHeaderView",
        *,
        column_specs: Sequence[CatalogColumnSpec],
        settings: QSettings | None = None,
    ) -> bool:
        del header, column_specs, settings
        raise NotImplementedError(
            "Phase A1 scaffolding only; header persistence is implemented in Phase A3."
        )


__all__ = ["CatalogHeaderStateManager"]

"""Royalties & Accounting workspace orchestration for the application shell."""

from __future__ import annotations

import sys
from collections.abc import Callable
from typing import Any, cast

from PySide6.QtWidgets import QDockWidget, QMessageBox, QWidget

from isrc_manager.catalog_workspace import ensure_catalog_workspace_dock
from isrc_manager.invoicing.workspace import InvoiceWorkspacePanel


def _root_attr(name: str, fallback: Any) -> Any:
    main_window_module = sys.modules.get("isrc_manager.main_window")
    return (
        getattr(main_window_module, name, fallback) if main_window_module is not None else fallback
    )


def _message_box() -> Any:
    return _root_attr("QMessageBox", QMessageBox)


def _invoice_workspace_panel_class() -> type[InvoiceWorkspacePanel]:
    return cast(
        type[InvoiceWorkspacePanel], _root_attr("InvoiceWorkspacePanel", InvoiceWorkspacePanel)
    )


def _create_invoice_workspace_panel(self: Any, parent: QWidget) -> InvoiceWorkspacePanel:
    panel_class = _invoice_workspace_panel_class()
    open_contract_manager: Callable[[int | None], object] | None = None
    open_work_manager: Callable[[int | None], object] | None = None
    open_track_editor: Callable[[int | None], object] | None = None
    open_rights_matrix: Callable[[int | None], object] | None = None
    open_party_manager: Callable[[int | None], object] | None = None
    if hasattr(self, "open_contract_manager"):

        def open_contract_manager(contract_id: int | None = None) -> object:
            return self.open_contract_manager(contract_id)

    if hasattr(self, "open_work_manager"):

        def open_work_manager(work_id: int | None = None) -> object:
            return self.open_work_manager(work_id=work_id)

    if hasattr(self, "open_selected_editor"):

        def open_track_editor(track_id: int | None = None) -> object:
            return self.open_selected_editor(track_id)

    if hasattr(self, "open_rights_matrix"):

        def open_rights_matrix(right_id: int | None = None) -> object:
            return self.open_rights_matrix(right_id)

    if hasattr(self, "open_party_manager"):

        def open_party_manager(party_id: int | None = None) -> object:
            return self.open_party_manager(party_id)

    return panel_class(
        conn_provider=lambda: self.conn,
        data_root=getattr(self, "data_root", None),
        open_contract_manager=open_contract_manager,
        open_work_manager=open_work_manager,
        open_track_editor=open_track_editor,
        open_rights_matrix=open_rights_matrix,
        open_party_manager=open_party_manager,
        parent=parent,
    )


def _ensure_invoice_workspace_dock(self: Any) -> QDockWidget:
    dock = cast(
        QDockWidget,
        ensure_catalog_workspace_dock(
            self,
            key="invoice_workspace",
            title="Royalties & Accounting",
            object_name="invoiceWorkspaceDock",
            panel_factory=self._create_invoice_workspace_panel,
        ),
    )
    self.invoice_workspace_dock = dock
    return dock


def open_invoice_workspace(self: Any, *, initial_tab: str = "invoices") -> object | None:
    if self.conn is None:
        _message_box().warning(self, "Royalties & Accounting", "Open a profile first.")
        return None
    result: object | None = self._show_workspace_panel(
        self._ensure_invoice_workspace_dock,
        panel_attr="invoice_workspace_panel",
        configure=lambda panel: panel.focus_tab(initial_tab),
    )
    return result

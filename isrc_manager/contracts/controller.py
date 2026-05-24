"""Contract manager workflow orchestration for the application shell."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QDockWidget, QMessageBox, QWidget

from isrc_manager.catalog_workspace import ensure_catalog_workspace_dock
from isrc_manager.contracts import ContractPayload
from isrc_manager.contracts.dialogs import ContractBrowserPanel


def _root_attr(name: str, fallback):
    main_window_module = sys.modules.get("isrc_manager.main_window")
    return (
        getattr(main_window_module, name, fallback) if main_window_module is not None else fallback
    )


def _message_box():
    return _root_attr("QMessageBox", QMessageBox)


def _contract_browser_panel_class():
    return _root_attr("ContractBrowserPanel", ContractBrowserPanel)


def _create_contract_manager_panel(self, parent: QWidget) -> ContractBrowserPanel:
    return _contract_browser_panel_class()(
        contract_service_provider=lambda: self.contract_service,
        create_contract_handler=self._create_contract_with_history,
        update_contract_handler=self._update_contract_with_history,
        delete_contract_handler=self._delete_contract_with_history,
        parent=parent,
    )


def _ensure_contract_manager_dock(self) -> QDockWidget:
    dock = ensure_catalog_workspace_dock(
        self,
        key="contract_manager",
        title="Contract Manager",
        object_name="contractManagerDock",
        panel_factory=self._create_contract_manager_panel,
    )
    self.contract_manager_dock = dock
    return dock


def open_contract_manager(self, contract_id: int | None = None):
    if self.contract_service is None:
        _message_box().warning(self, "Contract Manager", "Open a profile first.")
        return
    return self._show_workspace_panel(
        self._ensure_contract_manager_dock,
        panel_attr="contract_manager_panel",
        legacy_attr="contract_manager_dialog",
        configure=lambda panel: panel.focus_contract(contract_id),
    )


def _create_contract_with_history(self, payload: ContractPayload) -> int:
    if self.contract_service is None or self.conn is None:
        raise ValueError("Contract service is unavailable.")

    def mutation():
        with self.conn:
            return int(self.contract_service.create_contract(payload, cursor=self.conn.cursor()))

    contract_id = int(
        self._run_snapshot_history_action(
            action_label=f"Create Contract: {str(payload.title or 'Untitled Contract').strip()}",
            action_type="contract.create",
            entity_type="Contract",
            payload={"title": str(payload.title or "").strip()},
            mutation=mutation,
        )
    )
    self._refresh_catalog_workspace_docks()
    return contract_id


def _update_contract_with_history(self, contract_id: int, payload: ContractPayload) -> None:
    if self.contract_service is None or self.conn is None:
        raise ValueError("Contract service is unavailable.")

    def mutation():
        with self.conn:
            self.contract_service.update_contract(
                int(contract_id),
                payload,
                cursor=self.conn.cursor(),
            )
            return int(contract_id)

    self._run_snapshot_history_action(
        action_label=f"Update Contract: {str(payload.title or 'Untitled Contract').strip()}",
        action_type="contract.update",
        entity_type="Contract",
        entity_id=int(contract_id),
        payload={"title": str(payload.title or "").strip()},
        mutation=mutation,
    )
    self._refresh_catalog_workspace_docks()


def _delete_contract_with_history(self, contract_id: int) -> None:
    if self.contract_service is None or self.conn is None:
        raise ValueError("Contract service is unavailable.")
    record = self.contract_service.fetch_contract(int(contract_id))
    title = "" if record is None else str(record.title or "").strip()

    def mutation():
        with self.conn:
            self.contract_service.delete_contract(int(contract_id))
            return int(contract_id)

    self._run_snapshot_history_action(
        action_label=f"Delete Contract: {title or f'#{int(contract_id)}'}",
        action_type="contract.delete",
        entity_type="Contract",
        entity_id=int(contract_id),
        payload={"title": title},
        mutation=mutation,
    )
    self._refresh_catalog_workspace_docks()

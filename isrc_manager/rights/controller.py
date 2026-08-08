"""Rights matrix workflow orchestration for the application shell."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QDockWidget, QMessageBox, QWidget

from isrc_manager.catalog_workspace import ensure_catalog_workspace_dock
from isrc_manager.rights.dialogs import RightsBrowserPanel


def _root_attr(name: str, fallback):
    main_window_module = sys.modules.get("isrc_manager.main_window")
    return (
        getattr(main_window_module, name, fallback) if main_window_module is not None else fallback
    )


def _message_box():
    return _root_attr("QMessageBox", QMessageBox)


def _rights_browser_panel_class():
    return _root_attr("RightsBrowserPanel", RightsBrowserPanel)


def _create_rights_matrix_panel(self, parent: QWidget) -> RightsBrowserPanel:
    panel = _rights_browser_panel_class()(
        rights_service_provider=lambda: self.rights_service,
        party_service_provider=lambda: self.party_service,
        contract_service_provider=lambda: self.contract_service,
        parent=parent,
    )
    panel.delete_right_handler = lambda right_id: _delete_right_with_history(self, right_id)
    return panel


def _delete_right_with_history(self, right_id: int) -> int:
    if self.rights_service is None:
        raise ValueError("Rights service is unavailable.")
    normalized_id = int(right_id)
    record = self.rights_service.fetch_right(normalized_id)
    if record is None:
        raise ValueError(f"Rights record {normalized_id} not found.")
    right_label = (
        str(record.title or "").strip()
        or f"{record.right_type.replace('_', ' ').title()} #{normalized_id}"
    )

    def mutation() -> int:
        self.rights_service.delete_right(normalized_id)
        return normalized_id

    return int(
        self._run_snapshot_history_action(
            action_label=f"Delete Rights Record: {right_label}",
            action_type="right.delete",
            entity_type="Right",
            entity_id=normalized_id,
            payload={
                "right_id": normalized_id,
                "title": record.title,
                "right_type": record.right_type,
            },
            mutation=mutation,
        )
    )


def _ensure_rights_matrix_dock(self) -> QDockWidget:
    dock = ensure_catalog_workspace_dock(
        self,
        key="rights_matrix",
        title="Rights Matrix",
        object_name="rightsMatrixDock",
        panel_factory=self._create_rights_matrix_panel,
    )
    self.rights_matrix_dock = dock
    return dock


def open_rights_matrix(self, right_id: int | None = None):
    if self.rights_service is None or self.party_service is None or self.contract_service is None:
        _message_box().warning(self, "Rights Matrix", "Open a profile first.")
        return
    return self._show_workspace_panel(
        self._ensure_rights_matrix_dock,
        panel_attr="rights_matrix_panel",
        legacy_attr="rights_browser_dialog",
        configure=lambda panel: panel.focus_right(right_id),
    )

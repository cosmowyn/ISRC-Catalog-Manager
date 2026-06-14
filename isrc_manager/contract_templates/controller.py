"""Contract template workspace orchestration for the application shell."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QDockWidget, QMessageBox, QWidget

from isrc_manager.catalog_workspace import ensure_catalog_workspace_dock
from isrc_manager.contract_templates.dialogs import ContractTemplateWorkspacePanel


def _root_attr(name: str, fallback):
    main_window_module = sys.modules.get("isrc_manager.main_window")
    return (
        getattr(main_window_module, name, fallback) if main_window_module is not None else fallback
    )


def _message_box():
    return _root_attr("QMessageBox", QMessageBox)


def _contract_template_workspace_panel_class():
    return _root_attr("ContractTemplateWorkspacePanel", ContractTemplateWorkspacePanel)


def _create_contract_template_workspace_panel(
    self, parent: QWidget
) -> ContractTemplateWorkspacePanel:
    return _contract_template_workspace_panel_class()(
        catalog_service_provider=lambda: self.contract_template_catalog_service,
        template_service_provider=lambda: self.contract_template_service,
        form_service_provider=lambda: self.contract_template_form_service,
        export_service_provider=lambda: self.contract_template_export_service,
        parent=parent,
    )


def _ensure_contract_template_workspace_dock(self) -> QDockWidget:
    dock = ensure_catalog_workspace_dock(
        self,
        key="contract_template_workspace",
        title="Template Workspace",
        object_name="contractTemplateWorkspaceDock",
        panel_factory=self._create_contract_template_workspace_panel,
    )
    self.contract_template_workspace_dock = dock
    return dock


def open_contract_template_workspace(
    self,
    *,
    initial_tab: str = "import",
    template_family: str | None = None,
    scope_entity_type: str | None = None,
    scope_entity_id: int | str | None = None,
):
    if (
        self.contract_template_catalog_service is None
        or self.contract_template_service is None
        or self.contract_template_form_service is None
        or self.contract_template_export_service is None
    ):
        _message_box().warning(self, "Template Workspace", "Open a profile first.")
        return
    return self._show_workspace_panel(
        self._ensure_contract_template_workspace_dock,
        panel_attr="contract_template_workspace_panel",
        configure=lambda panel: (
            panel.apply_external_fill_context(
                template_family=template_family,
                scope_entity_type=scope_entity_type,
                scope_entity_id=scope_entity_id,
            )
            if scope_entity_type and scope_entity_id is not None
            else panel.focus_tab(initial_tab)
        ),
    )

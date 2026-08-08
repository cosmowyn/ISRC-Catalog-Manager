"""Asset registry workflow orchestration for the application shell."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QDockWidget, QMessageBox, QWidget

from isrc_manager.assets.dialogs import AssetBrowserPanel
from isrc_manager.catalog_workspace import ensure_catalog_workspace_dock


def _root_attr(name: str, fallback):
    main_window_module = sys.modules.get("isrc_manager.main_window")
    return (
        getattr(main_window_module, name, fallback) if main_window_module is not None else fallback
    )


def _message_box():
    return _root_attr("QMessageBox", QMessageBox)


def _asset_browser_panel_class():
    return _root_attr("AssetBrowserPanel", AssetBrowserPanel)


def _delete_asset_with_history(self, asset_id: int) -> None:
    service = self.asset_service
    asset = service.fetch_asset(int(asset_id)) if service is not None else None
    if asset is None:
        raise ValueError("The selected asset could not be loaded.")
    history_action = getattr(self, "_run_snapshot_history_action", None)
    if not callable(history_action):
        raise RuntimeError("Asset history is unavailable; the asset was not deleted.")
    history_action(
        action_label=f"Delete Asset: {asset.filename or f'#{int(asset_id)}'}",
        action_type="asset.delete",
        entity_type="AssetVersion",
        entity_id=int(asset_id),
        payload={"filename": asset.filename, "asset_type": asset.asset_type},
        mutation=lambda: service.delete_asset(int(asset_id)),
    )


def _create_asset_registry_panel(self, parent: QWidget) -> AssetBrowserPanel:
    return _asset_browser_panel_class()(
        asset_service_provider=lambda: self.asset_service,
        drill_in_host_provider=lambda: self,
        delete_asset_handler=lambda asset_id: _delete_asset_with_history(self, asset_id),
        parent=parent,
    )


def _ensure_asset_registry_dock(self) -> QDockWidget:
    dock = ensure_catalog_workspace_dock(
        self,
        key="asset_registry",
        title="Deliverables and Asset Versions",
        object_name="assetRegistryDock",
        panel_factory=self._create_asset_registry_panel,
        retabify_when_shown=True,
    )
    self.asset_registry_dock = dock
    return dock


def open_asset_registry(self, asset_id: int | None = None):
    if self.asset_service is None:
        _message_box().warning(self, "Asset Registry", "Open a profile first.")
        return
    return self._show_workspace_panel(
        self._ensure_asset_registry_dock,
        panel_attr="asset_registry_panel",
        legacy_attr="asset_browser_dialog",
        configure=lambda panel: panel.focus_asset(asset_id),
    )

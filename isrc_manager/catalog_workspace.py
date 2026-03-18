"""Dock helpers for non-modal catalog workspace panels."""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDockWidget, QWidget


class CatalogWorkspaceDock(QDockWidget):
    """Lazy dock wrapper that hosts a reusable catalog workspace panel."""

    def __init__(
        self,
        app: Any,
        *,
        dock_title: str,
        dock_object_name: str,
        panel_factory: Callable[[QDockWidget], QWidget],
    ):
        super().__init__(dock_title, app)
        self.app = app
        self.panel_factory = panel_factory
        self._panel: QWidget | None = None
        self.setObjectName(dock_object_name)
        self.setProperty("role", "panel")
        self.setAllowedAreas(Qt.AllDockWidgetAreas)
        self.setFeatures(
            QDockWidget.DockWidgetClosable
            | QDockWidget.DockWidgetMovable
            | QDockWidget.DockWidgetFloatable
        )
        self.visibilityChanged.connect(self._on_visibility_changed)

    def panel(self) -> QWidget:
        if self._panel is None:
            self._panel = self.panel_factory(self)
            if self._panel.property("role") is None:
                self._panel.setProperty("role", "workspaceCanvas")
            close_requested = getattr(self._panel, "close_requested", None)
            if close_requested is not None and hasattr(close_requested, "connect"):
                close_requested.connect(self.hide)
            self.setWidget(self._panel)
        return self._panel

    def refresh_panel(self) -> None:
        if self._panel is None:
            return
        refresh = getattr(self._panel, "refresh", None)
        if callable(refresh):
            refresh()

    def show_panel(self) -> QWidget:
        panel = self.panel()
        self.setVisible(True)
        _tabify_catalog_workspace_dock(self.app, self)
        self.raise_()
        refresh = getattr(panel, "refresh", None)
        if callable(refresh):
            refresh()
        return panel

    def _on_visibility_changed(self, visible: bool) -> None:
        if visible:
            self.refresh_panel()
        save_state = getattr(self.app, "_save_main_dock_state", None)
        if callable(save_state):
            save_state()


def ensure_catalog_workspace_dock(
    app: Any,
    *,
    key: str,
    title: str,
    object_name: str,
    panel_factory: Callable[[QDockWidget], QWidget],
    default_area=Qt.RightDockWidgetArea,
) -> CatalogWorkspaceDock:
    registry = getattr(app, "_catalog_workspace_docks", None)
    if registry is None:
        registry = {}
        setattr(app, "_catalog_workspace_docks", registry)

    existing = registry.get(key)
    if isinstance(existing, CatalogWorkspaceDock):
        return existing

    dock = CatalogWorkspaceDock(
        app,
        dock_title=title,
        dock_object_name=object_name,
        panel_factory=panel_factory,
    )
    registry[key] = dock
    anchor = _default_tab_anchor(app, dock)
    area = default_area
    if anchor is not None:
        anchor_area = app.dockWidgetArea(anchor)
        if anchor_area != Qt.NoDockWidgetArea:
            area = anchor_area
    app.addDockWidget(area, dock)

    _tabify_catalog_workspace_dock(app, dock, anchor=anchor)

    dock.dockLocationChanged.connect(lambda *_args: app._save_main_dock_state())
    dock.topLevelChanged.connect(lambda *_args: app._save_main_dock_state())

    restore_state = getattr(app, "_restore_main_dock_state", None)
    if callable(restore_state):
        restore_state()
    return dock


def refresh_catalog_workspace_docks(app: Any) -> None:
    registry = getattr(app, "_catalog_workspace_docks", {})
    for dock in list(registry.values()):
        if isinstance(dock, CatalogWorkspaceDock):
            dock.refresh_panel()


def _default_tab_anchor(app: Any, new_dock: QDockWidget) -> QDockWidget | None:
    catalog_table_dock = getattr(app, "catalog_table_dock", None)
    if isinstance(catalog_table_dock, QDockWidget) and catalog_table_dock is not new_dock:
        return catalog_table_dock

    registry = getattr(app, "_catalog_workspace_docks", {})
    visible_peers = [
        dock
        for dock in registry.values()
        if isinstance(dock, QDockWidget) and dock is not new_dock and dock.isVisible()
    ]
    if visible_peers:
        return visible_peers[-1]

    add_data_dock = getattr(app, "add_data_dock", None)
    if isinstance(add_data_dock, QDockWidget):
        return add_data_dock
    return None


def _tabify_catalog_workspace_dock(
    app: Any, dock: QDockWidget, *, anchor: QDockWidget | None = None
) -> None:
    anchor = anchor or _default_tab_anchor(app, dock)
    if anchor is None or anchor is dock:
        return
    app.tabifyDockWidget(anchor, dock)

"""Dock helpers for non-modal catalog workspace panels."""

from __future__ import annotations

import copy
from typing import Any, Callable

from PySide6.QtCore import Qt, QTimer
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
        retabify_when_shown: bool = False,
    ):
        super().__init__(dock_title, app)
        self.app = app
        self.panel_factory = panel_factory
        self.retabify_when_shown = bool(retabify_when_shown)
        self._workspace_panel_key = ""
        self._panel: QWidget | None = None
        self._default_placement_pending = True
        self._pending_panel_layout_state: dict[str, object] | None = None
        self._default_dock_area = Qt.RightDockWidgetArea
        self._placeholder = QWidget(self)
        self._placeholder.setObjectName(f"{dock_object_name}Placeholder")
        self._placeholder.setProperty("role", "workspaceCanvas")
        self.setObjectName(dock_object_name)
        self.setProperty("role", "panel")
        self.setAllowedAreas(Qt.AllDockWidgetAreas)
        self.setFeatures(
            QDockWidget.DockWidgetClosable
            | QDockWidget.DockWidgetMovable
            | QDockWidget.DockWidgetFloatable
        )
        self.setWidget(self._placeholder)
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
            if self._placeholder is not None:
                self._placeholder.deleteLater()
                self._placeholder = None
            self._apply_pending_panel_layout_state()
        return self._panel

    def refresh_panel(self) -> None:
        if self._panel is None:
            return
        refresh = getattr(self._panel, "refresh", None)
        if callable(refresh):
            refresh()

    def show_panel(self) -> QWidget:
        panel = self.panel()
        apply_default_placement = bool(
            self._default_placement_pending
            or (
                self.retabify_when_shown
                and not self.isFloating()
                and not self.app.tabifiedDockWidgets(self)
                and _default_tab_anchor(self.app, self) is not None
            )
        )
        previous_suspend_state = getattr(self.app, "_suspend_dock_state_sync", False)
        setattr(self.app, "_suspend_dock_state_sync", True)
        try:
            self.setVisible(True)
            if apply_default_placement:
                _tabify_catalog_workspace_dock(self.app, self)
        finally:
            setattr(self.app, "_suspend_dock_state_sync", previous_suspend_state)

        def _finalize_show_panel() -> None:
            suspended_state = getattr(self.app, "_suspend_dock_state_sync", False)
            setattr(self.app, "_suspend_dock_state_sync", True)
            try:
                if apply_default_placement:
                    _tabify_catalog_workspace_dock(self.app, self)
                    self._default_placement_pending = False
                if self.isVisible():
                    self.raise_()
            finally:
                setattr(self.app, "_suspend_dock_state_sync", suspended_state)
            if self.isVisible():
                schedule_save = getattr(self.app, "_schedule_main_dock_state_save", None)
                if callable(schedule_save):
                    schedule_save()

        QTimer.singleShot(0, _finalize_show_panel)
        refresh = getattr(panel, "refresh", None)
        if callable(refresh):
            refresh()
        return panel

    def _on_visibility_changed(self, visible: bool) -> None:
        if visible:
            if self._panel is None:
                self.panel()
            self.refresh_panel()
        schedule_save = getattr(self.app, "_schedule_main_dock_state_save", None)
        if callable(schedule_save):
            schedule_save()

    def capture_panel_layout_state(self) -> dict[str, object] | None:
        panel = self._panel
        capture = getattr(panel, "capture_layout_state", None) if panel is not None else None
        if callable(capture):
            try:
                state = capture()
            except Exception:
                state = None
            if isinstance(state, dict):
                self._pending_panel_layout_state = copy.deepcopy(state)
        if isinstance(self._pending_panel_layout_state, dict):
            return copy.deepcopy(self._pending_panel_layout_state)
        return None

    def restore_panel_layout_state(self, state: dict[str, object] | None) -> None:
        self._pending_panel_layout_state = copy.deepcopy(state) if isinstance(state, dict) else None
        if self._panel is not None:
            restore = getattr(self._panel, "restore_layout_state", None)
            if callable(restore):
                try:
                    restore(copy.deepcopy(state) if isinstance(state, dict) else None)
                except Exception:
                    pass
        self._apply_pending_panel_layout_state()

    def _apply_pending_panel_layout_state(self) -> None:
        if self._panel is None or not isinstance(self._pending_panel_layout_state, dict):
            return
        restore = getattr(self._panel, "restore_layout_state", None)
        if not callable(restore):
            return
        try:
            restore(copy.deepcopy(self._pending_panel_layout_state))
        except Exception:
            return


def ensure_catalog_workspace_dock(
    app: Any,
    *,
    key: str,
    title: str,
    object_name: str,
    panel_factory: Callable[[QDockWidget], QWidget],
    default_area=Qt.RightDockWidgetArea,
    retabify_when_shown: bool = False,
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
        retabify_when_shown=retabify_when_shown,
    )
    dock._default_dock_area = default_area
    dock._workspace_panel_key = str(key or "")
    registry[key] = dock
    anchor = _default_tab_anchor(app, dock)
    area = default_area
    if anchor is not None:
        anchor_area = app.dockWidgetArea(anchor)
        if anchor_area != Qt.NoDockWidgetArea:
            area = anchor_area
    app.addDockWidget(area, dock)

    _tabify_catalog_workspace_dock(app, dock, anchor=anchor)
    dock.hide()

    dock.dockLocationChanged.connect(lambda *_args: app._schedule_main_dock_state_save())
    dock.topLevelChanged.connect(lambda *_args: app._schedule_main_dock_state_save())
    return dock


def refresh_catalog_workspace_docks(app: Any) -> None:
    registry = getattr(app, "_catalog_workspace_docks", {})
    for dock in list(registry.values()):
        if isinstance(dock, CatalogWorkspaceDock):
            dock.refresh_panel()


def _default_tab_anchor(app: Any, new_dock: QDockWidget) -> QDockWidget | None:
    catalog_table_dock = getattr(app, "catalog_table_dock", None)
    if _is_tab_anchor_candidate(app, catalog_table_dock, new_dock):
        return catalog_table_dock

    registry = getattr(app, "_catalog_workspace_docks", {})
    visible_peers = [
        dock for dock in registry.values() if _is_tab_anchor_candidate(app, dock, new_dock)
    ]
    if visible_peers:
        return visible_peers[-1]

    add_data_dock = getattr(app, "add_data_dock", None)
    if _is_tab_anchor_candidate(app, add_data_dock, new_dock):
        return add_data_dock
    return None


def _tabify_catalog_workspace_dock(
    app: Any, dock: QDockWidget, *, anchor: QDockWidget | None = None
) -> None:
    anchor = anchor or _default_tab_anchor(app, dock)
    if anchor is None or anchor is dock:
        return
    app.tabifyDockWidget(anchor, dock)


def _is_tab_anchor_candidate(app: Any, dock: Any, new_dock: QDockWidget) -> bool:
    return (
        isinstance(dock, QDockWidget)
        and dock is not new_dock
        and dock.widget() is not None
        and dock.isVisible()
        and not dock.isHidden()
        and not dock.isFloating()
        and app.dockWidgetArea(dock) != Qt.NoDockWidgetArea
    )

"""Dock helpers for non-modal catalog workspace panels."""

from __future__ import annotations

import copy
from typing import Any, Callable

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtWidgets import QDockWidget, QWidget

from isrc_manager.workspace_debug import (
    summarize_panel_layout_state,
    workspace_debug_log,
)


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
        self._pending_panel_layout_state_dirty = False
        self._default_dock_area = Qt.RightDockWidgetArea
        self._pending_panel_layout_timer = QTimer(self)
        self._pending_panel_layout_timer.setSingleShot(True)
        self._pending_panel_layout_timer.timeout.connect(self._apply_pending_panel_layout_state)
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
            self._panel.installEventFilter(self)
            close_requested = getattr(self._panel, "close_requested", None)
            if close_requested is not None and hasattr(close_requested, "connect"):
                close_requested.connect(self.hide)
            self.setWidget(self._panel)
            if self._placeholder is not None:
                self._placeholder.deleteLater()
                self._placeholder = None
            workspace_debug_log(
                "layout",
                "catalog_workspace_dock.panel_materialized",
                dock_object_name=str(self.objectName() or ""),
                workspace_panel_key=str(self._workspace_panel_key or ""),
            )
            self._schedule_pending_panel_layout_state_application()
        return self._panel

    def _app_layout_restore_in_progress(self) -> bool:
        return bool(getattr(self.app, "_is_restoring_workspace_layout", False))

    def refresh_panel(self) -> None:
        if self._panel is None or not self.isVisible():
            return
        if self._app_layout_restore_in_progress():
            workspace_debug_log(
                "layout",
                "catalog_workspace_dock.refresh.skipped",
                dock_object_name=str(self.objectName() or ""),
                reason="app_layout_restore",
            )
            return
        if self._pending_panel_layout_state_dirty:
            workspace_debug_log(
                "layout",
                "catalog_workspace_dock.refresh.skipped",
                dock_object_name=str(self.objectName() or ""),
                reason="pending_layout_restore",
            )
            return
        refresh = getattr(self._panel, "refresh", None)
        if callable(refresh):
            refresh()

    def show_panel(self) -> QWidget:
        panel = self.panel()
        workspace_debug_log(
            "layout",
            "catalog_workspace_dock.show_panel.begin",
            dock_object_name=str(self.objectName() or ""),
            visible=bool(self.isVisible()),
            pending_dirty=bool(self._pending_panel_layout_state_dirty),
        )
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
            self._schedule_pending_panel_layout_state_application()
            if self.isVisible():
                schedule_save = getattr(self.app, "_schedule_main_dock_state_save", None)
                if callable(schedule_save):
                    schedule_save()

        QTimer.singleShot(0, _finalize_show_panel)
        if (
            not self._pending_panel_layout_state_dirty
            and not self._app_layout_restore_in_progress()
        ):
            refresh = getattr(panel, "refresh", None)
            if callable(refresh):
                refresh()
        else:
            workspace_debug_log(
                "layout",
                "catalog_workspace_dock.show_panel.refresh_deferred",
                dock_object_name=str(self.objectName() or ""),
                reason=(
                    "app_layout_restore"
                    if self._app_layout_restore_in_progress()
                    else "pending_layout_restore"
                ),
            )
        return panel

    def _on_visibility_changed(self, visible: bool) -> None:
        workspace_debug_log(
            "layout",
            "catalog_workspace_dock.visibility_changed",
            dock_object_name=str(self.objectName() or ""),
            visible=bool(visible),
            pending_dirty=bool(self._pending_panel_layout_state_dirty),
        )
        if visible:
            if self._panel is None:
                if self._app_layout_restore_in_progress():
                    workspace_debug_log(
                        "layout",
                        "catalog_workspace_dock.visibility_materialization_deferred",
                        dock_object_name=str(self.objectName() or ""),
                    )
                else:
                    self.panel()
            self._schedule_pending_panel_layout_state_application()
            if self._panel is not None and not self._pending_panel_layout_state_dirty:
                self.refresh_panel()
            else:
                workspace_debug_log(
                    "layout",
                    "catalog_workspace_dock.visibility_refresh_deferred",
                    dock_object_name=str(self.objectName() or ""),
                )
        schedule_save = getattr(self.app, "_schedule_main_dock_state_save", None)
        if callable(schedule_save):
            schedule_save()

    def capture_panel_layout_state(self) -> dict[str, object] | None:
        workspace_debug_log(
            "layout",
            "catalog_workspace_dock.capture.begin",
            dock_object_name=str(self.objectName() or ""),
            pending_dirty=bool(self._pending_panel_layout_state_dirty),
        )
        self.stabilize_panel_layout_after_restore()
        if self._pending_panel_layout_state_dirty and isinstance(
            self._pending_panel_layout_state, dict
        ):
            workspace_debug_log(
                "layout",
                "catalog_workspace_dock.capture.pending_reused",
                dock_object_name=str(self.objectName() or ""),
                state=summarize_panel_layout_state(self._pending_panel_layout_state),
            )
            return copy.deepcopy(self._pending_panel_layout_state)
        panel = self._panel
        capture = getattr(panel, "capture_layout_state", None) if panel is not None else None
        if callable(capture):
            try:
                state = capture()
            except Exception:
                state = None
            if isinstance(state, dict):
                self._pending_panel_layout_state = copy.deepcopy(state)
                self._pending_panel_layout_state_dirty = False
        if isinstance(self._pending_panel_layout_state, dict):
            workspace_debug_log(
                "layout",
                "catalog_workspace_dock.capture.end",
                dock_object_name=str(self.objectName() or ""),
                state=summarize_panel_layout_state(self._pending_panel_layout_state),
            )
            return copy.deepcopy(self._pending_panel_layout_state)
        workspace_debug_log(
            "layout",
            "catalog_workspace_dock.capture.end",
            dock_object_name=str(self.objectName() or ""),
            state=None,
        )
        return None

    def restore_panel_layout_state(self, state: dict[str, object] | None) -> None:
        self._pending_panel_layout_state = copy.deepcopy(state) if isinstance(state, dict) else None
        self._pending_panel_layout_state_dirty = isinstance(self._pending_panel_layout_state, dict)
        workspace_debug_log(
            "layout",
            "catalog_workspace_dock.restore.requested",
            dock_object_name=str(self.objectName() or ""),
            pending_dirty=bool(self._pending_panel_layout_state_dirty),
            state=summarize_panel_layout_state(self._pending_panel_layout_state),
        )
        if not self._pending_panel_layout_state_dirty:
            return
        if self._panel_ready_for_layout_restore():
            self._apply_pending_panel_layout_state()
            return
        self._schedule_pending_panel_layout_state_application()

    def _apply_pending_panel_layout_state(self) -> None:
        if (
            not self._pending_panel_layout_state_dirty
            or self._panel is None
            or not isinstance(self._pending_panel_layout_state, dict)
            or not self._panel_ready_for_layout_restore()
        ):
            workspace_debug_log(
                "layout",
                "catalog_workspace_dock.restore.skipped",
                dock_object_name=str(self.objectName() or ""),
                pending_dirty=bool(self._pending_panel_layout_state_dirty),
                panel_ready=bool(self._panel_ready_for_layout_restore()),
                has_panel=bool(self._panel is not None),
            )
            return
        restore = getattr(self._panel, "restore_layout_state", None)
        if not callable(restore):
            return
        begin_layout_restore = getattr(self._panel, "begin_layout_restore", None)
        finish_layout_restore = getattr(self._panel, "finish_layout_restore", None)
        if callable(begin_layout_restore):
            try:
                begin_layout_restore()
            except Exception:
                pass
        restore_applied = False
        try:
            restore(copy.deepcopy(self._pending_panel_layout_state))
        except Exception:
            if callable(finish_layout_restore):
                try:
                    finish_layout_restore()
                except Exception:
                    pass
            return
        restore_applied = True
        self._pending_panel_layout_state_dirty = False
        workspace_debug_log(
            "layout",
            "catalog_workspace_dock.restore.applied",
            dock_object_name=str(self.objectName() or ""),
            state=summarize_panel_layout_state(self._pending_panel_layout_state),
        )
        self._run_panel_stabilizer()
        if restore_applied and callable(finish_layout_restore):
            try:
                finish_layout_restore()
            except Exception:
                pass

    def _schedule_pending_panel_layout_state_application(self) -> None:
        if not self._pending_panel_layout_state_dirty or self._panel is None:
            return
        if not self._panel_ready_for_layout_restore():
            return
        self._pending_panel_layout_timer.start(0)

    def _panel_ready_for_layout_restore(self) -> bool:
        panel = self._panel
        if not isinstance(panel, QWidget):
            return False
        if not self.isVisible() or not panel.isVisible():
            return False
        if bool(getattr(self.app, "_is_restoring_workspace_layout", False)):
            return False
        return panel.width() > 64 and panel.height() > 64

    def resizeEvent(self, event) -> None:  # pragma: no cover - Qt callback
        super().resizeEvent(event)
        self._schedule_pending_panel_layout_state_application()

    def showEvent(self, event) -> None:  # pragma: no cover - Qt callback
        super().showEvent(event)
        workspace_debug_log(
            "layout",
            "catalog_workspace_dock.show_event",
            dock_object_name=str(self.objectName() or ""),
            pending_dirty=bool(self._pending_panel_layout_state_dirty),
            panel_visible=bool(isinstance(self._panel, QWidget) and self._panel.isVisible()),
        )
        self._schedule_pending_panel_layout_state_application()

    def eventFilter(self, watched, event) -> bool:  # pragma: no cover - Qt callback
        if watched is self._panel and isinstance(event, QEvent):
            if event.type() in {
                QEvent.Show,
                QEvent.Resize,
                QEvent.LayoutRequest,
                QEvent.ParentChange,
            }:
                workspace_debug_log(
                    "layout",
                    "catalog_workspace_dock.panel_event",
                    dock_object_name=str(self.objectName() or ""),
                    event_type=int(event.type()),
                    pending_dirty=bool(self._pending_panel_layout_state_dirty),
                )
                self._schedule_pending_panel_layout_state_application()
        return super().eventFilter(watched, event)

    def _run_panel_stabilizer(self) -> None:
        panel = self._panel
        stabilize = getattr(panel, "stabilize_layout_after_restore", None) if panel else None
        if callable(stabilize):
            try:
                stabilize()
            except Exception:
                pass

    def stabilize_panel_layout_after_restore(self) -> None:
        workspace_debug_log(
            "layout",
            "catalog_workspace_dock.stabilize.begin",
            dock_object_name=str(self.objectName() or ""),
            pending_dirty=bool(self._pending_panel_layout_state_dirty),
            panel_ready=bool(self._panel_ready_for_layout_restore()),
        )
        if self._pending_panel_layout_state_dirty:
            if self._panel_ready_for_layout_restore():
                self._apply_pending_panel_layout_state()
                return
            self._schedule_pending_panel_layout_state_application()
            if self._pending_panel_layout_state_dirty:
                return
        self._run_panel_stabilizer()
        workspace_debug_log(
            "layout",
            "catalog_workspace_dock.stabilize.end",
            dock_object_name=str(self.objectName() or ""),
            pending_dirty=bool(self._pending_panel_layout_state_dirty),
        )


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

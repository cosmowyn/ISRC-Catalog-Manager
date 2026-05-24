"""Main-window layout and dock-state orchestration."""

from __future__ import annotations

import json
import sys
from contextlib import contextmanager

from PySide6.QtCore import QByteArray, QRect, Qt, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDockWidget,
    QInputDialog,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QToolBar,
    QWidget,
    QWidgetAction,
)

from isrc_manager import action_ribbon
from isrc_manager.app_prompts import (
    get_name_from_editable_choice_dialog as _get_name_from_editable_choice_dialog,
)
from isrc_manager.catalog_table import CATALOG_ZOOM_LAYOUT_KEY
from isrc_manager.catalog_workspace import CatalogWorkspaceDock
from isrc_manager.startup_progress import StartupPhase
from isrc_manager.tasks import TaskFailure
from isrc_manager.workspace_debug import (
    summarize_catalog_workspace_dock,
    summarize_panel_layout_snapshot,
    summarize_panel_layout_state,
    workspace_debug_enabled,
    workspace_debug_log,
)


def _root_attr(app, name: str, fallback):
    root_module = sys.modules.get(app.__class__.__module__)
    return getattr(root_module, name, fallback) if root_module is not None else fallback


def _name_choice_dialog(app):
    return _root_attr(
        app,
        "_get_name_from_editable_choice_dialog",
        _get_name_from_editable_choice_dialog,
    )


def _message_box(app):
    return _root_attr(app, "QMessageBox", QMessageBox)


def _input_dialog(app):
    return _root_attr(app, "QInputDialog", QInputDialog)


def _visible_layout_stabilization_targets(app) -> list[QWidget]:
    seen: set[int] = set()
    widgets: list[QWidget] = []
    candidates = [
        app,
        app.centralWidget(),
        *app.findChildren(QDockWidget),
        *app.findChildren(QToolBar),
        *app.findChildren(QMainWindow),
    ]
    for candidate in candidates:
        if not isinstance(candidate, QWidget):
            continue
        if not candidate.isVisible():
            continue
        widget_id = id(candidate)
        if widget_id in seen:
            continue
        seen.add(widget_id)
        widgets.append(candidate)
    return widgets


def _geometry_snapshot_for_widgets(widgets: list[QWidget]) -> tuple[tuple[object, ...], ...]:
    snapshot: list[tuple[object, ...]] = []
    for widget in widgets:
        try:
            geometry = widget.geometry()
        except Exception:
            continue
        snapshot.append(
            (
                str(widget.objectName() or widget.metaObject().className() or "widget"),
                int(geometry.x()),
                int(geometry.y()),
                int(geometry.width()),
                int(geometry.height()),
                bool(widget.isVisible()),
            )
        )
    return tuple(snapshot)


def _stabilize_visible_layout_after_restore(
    app,
    *,
    progress_callback=None,
    maximum: int | None = None,
    value: int | None = None,
    stabilization_limit: int = 6,
) -> bool:
    previous_snapshot = None
    stabilized = False
    limit = max(1, int(stabilization_limit))
    for attempt in range(1, limit + 1):
        widgets = app._visible_layout_stabilization_targets()
        for widget in widgets:
            try:
                widget.updateGeometry()
                widget.update()
                widget.repaint()
            except Exception:
                continue
        app.updateGeometry()
        app.update()
        app.repaint()
        app._drain_qt_events()
        current_snapshot = app._geometry_snapshot_for_widgets(widgets)
        if current_snapshot == previous_snapshot:
            stabilized = True
            if callable(progress_callback):
                progress_callback(
                    value,
                    maximum,
                    f"Visible workspace geometry stabilized after pass {attempt}.",
                )
            break
        previous_snapshot = current_snapshot
    if not stabilized:
        app.logger.warning(
            "Visible workspace layout stabilization hit the bounded limit (%s passes).",
            limit,
        )
        if callable(progress_callback):
            progress_callback(
                value,
                maximum,
                (
                    "Visible workspace stabilization reached the bounded limit; "
                    "continuing with the best painted state available."
                ),
            )
    return stabilized


def _dock_state_setting_key() -> str:
    return "display/main_window_dock_state"


def _window_geometry_setting_key() -> str:
    return "display/main_window_geometry"


def _window_state_setting_key() -> str:
    return "display/main_window_window_state"


def _window_normal_geometry_setting_key() -> str:
    return "display/main_window_normal_geometry"


def _saved_main_window_layouts_setting_key() -> str:
    return "display/saved_main_window_layouts_json"


def _workspace_panels_setting_key() -> str:
    return "display/main_window_workspace_panels_json"


def _serialize_qbytearray_setting(value: QByteArray | None) -> str:
    if not isinstance(value, QByteArray) or value.isEmpty():
        return ""
    try:
        return bytes(value.toBase64()).decode("ascii")
    except Exception:
        return ""


def _deserialize_qbytearray_setting(value) -> QByteArray:
    clean = str(value or "").strip()
    if not clean:
        return QByteArray()
    try:
        return QByteArray.fromBase64(clean.encode("ascii"))
    except Exception:
        return QByteArray()


def _serialize_rect_setting(value: QRect | None) -> dict[str, int] | None:
    if not isinstance(value, QRect) or not value.isValid():
        return None
    return {
        "x": int(value.x()),
        "y": int(value.y()),
        "width": int(value.width()),
        "height": int(value.height()),
    }


def _deserialize_rect_setting(value) -> QRect | None:
    if not isinstance(value, dict):
        return None
    try:
        rect = QRect(
            int(value.get("x", 0)),
            int(value.get("y", 0)),
            int(value.get("width", 0)),
            int(value.get("height", 0)),
        )
    except Exception:
        return None
    return rect if rect.isValid() else None


def _schedule_main_dock_state_save(app) -> None:
    if (
        getattr(app, "_suspend_dock_state_sync", False)
        or getattr(app, "_is_restoring_workspace_layout", False)
        or getattr(app, "_is_closing", False)
        or not getattr(app, "_workspace_layout_restore_complete", False)
    ):
        return
    timer = getattr(app, "_dock_state_save_timer", None)
    if timer is None:
        timer = QTimer(app)
        timer.setSingleShot(True)
        app._connect_noarg_signal(timer.timeout, timer, app._save_main_dock_state)
        app._dock_state_save_timer = timer
    timer.start(75)


def _schedule_main_window_geometry_save(app) -> None:
    if (
        getattr(app, "_is_restoring_workspace_layout", False)
        or getattr(app, "_is_closing", False)
        or not getattr(app, "_workspace_layout_restore_complete", False)
    ):
        return
    timer = getattr(app, "_window_geometry_save_timer", None)
    if timer is None:
        timer = QTimer(app)
        timer.setSingleShot(True)
        app._connect_noarg_signal(timer.timeout, timer, app._save_main_window_geometry)
        app._window_geometry_save_timer = timer
    timer.start(75)


def _stop_queued_main_window_layout_persistence(app) -> None:
    for timer_name in ("_dock_state_save_timer", "_window_geometry_save_timer"):
        timer = getattr(app, timer_name, None)
        if isinstance(timer, QTimer):
            timer.stop()


def _save_main_dock_state(app, *, sync: bool = True) -> None:
    if getattr(app, "_suspend_dock_state_sync", False):
        return
    try:
        snapshot = app._capture_current_workspace_panel_layout_snapshot()
        workspace_debug_log(
            "layout",
            "app.save_main_dock_state",
            sync=bool(sync),
            workspace_panels=summarize_panel_layout_snapshot(snapshot),
        )
        app.settings.setValue(app._dock_state_setting_key(), app.saveState(1))
        app._write_workspace_panel_layouts(
            snapshot,
            sync=False,
        )
        if sync:
            app.settings.sync()
    except Exception as e:
        app.logger.warning("Failed to save dock state: %s", e)


def _apply_main_dock_state_snapshot(app, state: QByteArray | None) -> bool:
    if not isinstance(state, QByteArray) or state.isEmpty():
        return False
    previous_suspend_state = app._suspend_dock_state_sync
    app._suspend_dock_state_sync = True
    restored = False
    try:
        restored = bool(app.restoreState(state, 1))
        if not restored:
            app.logger.warning("Qt rejected the saved dock state; keeping the default layout")
    except Exception as e:
        app.logger.warning("Failed to restore dock state: %s", e)
    finally:
        app._suspend_dock_state_sync = previous_suspend_state
    return restored


def _restore_main_dock_state(app) -> bool:
    try:
        state = app.settings.value(app._dock_state_setting_key(), None, QByteArray)
    except Exception:
        state = None
    return app._apply_main_dock_state_snapshot(state)


def _save_main_window_geometry(app, *, sync: bool = True) -> None:
    try:
        app.settings.setValue(app._window_geometry_setting_key(), app.saveGeometry())
        app.settings.setValue(
            app._window_state_setting_key(),
            app._current_main_window_state_marker(),
        )
        normal_geometry = app.normalGeometry()
        if isinstance(normal_geometry, QRect) and normal_geometry.isValid():
            app.settings.setValue(
                app._window_normal_geometry_setting_key(),
                normal_geometry,
            )
        if sync:
            app.settings.sync()
    except Exception as e:
        app.logger.warning("Failed to save main window geometry: %s", e)


def _apply_main_window_geometry_snapshot(
    app,
    *,
    geometry: QByteArray | None,
    normal_geometry: QRect | None,
    window_state_marker: str,
) -> bool:
    has_geometry = isinstance(geometry, QByteArray) and not geometry.isEmpty()
    marker = str(window_state_marker or "").strip().lower()
    if not has_geometry and marker not in {"normal", "maximized", "fullscreen"}:
        return False

    restored = False
    if has_geometry:
        try:
            restored = bool(app.restoreGeometry(geometry))
        except Exception as e:
            app.logger.warning("Failed to restore main window geometry: %s", e)

    if marker == "fullscreen":
        app.showFullScreen()
        return True
    if marker == "maximized":
        app.showMaximized()
        return True
    if marker == "normal":
        app.showNormal()
        if isinstance(normal_geometry, QRect) and normal_geometry.isValid():
            app.setGeometry(normal_geometry)
        return True
    return restored


def _restore_main_window_geometry(app) -> bool:
    try:
        geometry = app.settings.value(app._window_geometry_setting_key(), None, QByteArray)
    except Exception:
        geometry = None
    try:
        normal_geometry = app.settings.value(
            app._window_normal_geometry_setting_key(),
            None,
            QRect,
        )
    except Exception:
        normal_geometry = None
    try:
        window_state_marker = app.settings.value(app._window_state_setting_key(), "", str)
    except Exception:
        window_state_marker = ""
    return app._apply_main_window_geometry_snapshot(
        geometry=geometry,
        normal_geometry=normal_geometry,
        window_state_marker=window_state_marker,
    )


def _current_main_window_state_marker(app) -> str:
    window_state = app.windowState()
    if window_state & Qt.WindowFullScreen:
        return "fullscreen"
    if window_state & Qt.WindowMaximized:
        return "maximized"
    return "normal"


def _load_saved_main_window_layouts(app) -> dict[str, dict[str, object]]:
    raw_value = app.settings.value(app._saved_main_window_layouts_setting_key(), "{}")
    parsed = raw_value
    if isinstance(raw_value, str):
        try:
            parsed = json.loads(raw_value)
        except Exception:
            return {}
    if not isinstance(parsed, dict):
        return {}
    normalized: dict[str, dict[str, object]] = {}
    for name, snapshot in parsed.items():
        clean_name = str(name or "").strip()
        if not clean_name or not isinstance(snapshot, dict):
            continue
        normalized[clean_name] = dict(snapshot)
    return dict(sorted(normalized.items(), key=lambda item: item[0].casefold()))


def _write_saved_main_window_layouts(
    app,
    layouts: dict[str, dict[str, object]],
    *,
    sync: bool = True,
) -> None:
    payload = dict(sorted(layouts.items(), key=lambda item: item[0].casefold()))
    app.settings.setValue(
        app._saved_main_window_layouts_setting_key(),
        json.dumps(payload, ensure_ascii=True, sort_keys=True),
    )
    if sync:
        app.settings.sync()


def _load_workspace_panel_layouts(app) -> dict[str, dict[str, object]]:
    raw_value = app.settings.value(app._workspace_panels_setting_key(), "{}")
    parsed = raw_value
    if isinstance(raw_value, str):
        try:
            parsed = json.loads(raw_value)
        except Exception:
            return {}
    if not isinstance(parsed, dict):
        return {}
    normalized: dict[str, dict[str, object]] = {}
    for key, payload in parsed.items():
        clean_key = str(key or "").strip()
        if clean_key and isinstance(payload, dict):
            normalized[clean_key] = dict(payload)
    return normalized


def _write_workspace_panel_layouts(
    app,
    layouts: dict[str, dict[str, object]],
    *,
    sync: bool = True,
) -> None:
    payload = dict(sorted(layouts.items(), key=lambda item: item[0].casefold()))
    app.settings.setValue(
        app._workspace_panels_setting_key(),
        json.dumps(payload, ensure_ascii=True, sort_keys=True),
    )
    if sync:
        app.settings.sync()


def _capture_current_workspace_panel_layout_snapshot(app) -> dict[str, dict[str, object]]:
    registry = getattr(app, "_catalog_workspace_docks", {})
    snapshot: dict[str, dict[str, object]] = {}
    for key, dock in list(registry.items()):
        if not isinstance(dock, QDockWidget):
            continue
        capture = getattr(dock, "capture_panel_layout_state", None)
        if not callable(capture):
            continue
        try:
            state = capture()
        except Exception:
            state = None
        if isinstance(state, dict):
            snapshot[str(key)] = dict(state)
    workspace_debug_log(
        "layout",
        "app.capture_workspace_panel_layout_snapshot",
        snapshot=summarize_panel_layout_snapshot(snapshot),
    )
    return snapshot


def _contract_template_workspace_debug_summary(app) -> dict[str, object]:
    registry = getattr(app, "_catalog_workspace_docks", {})
    dock = getattr(app, "contract_template_workspace_dock", None)
    if not isinstance(dock, QDockWidget):
        candidate = registry.get("contract_template_workspace")
        if isinstance(candidate, QDockWidget):
            dock = candidate
    return summarize_catalog_workspace_dock(dock)


def _log_contract_template_restore_checkpoint(app, event: str, **payload) -> None:
    workspace_debug_log(
        "layout",
        event,
        contract_template_workspace=app._contract_template_workspace_debug_summary(),
        payload=payload,
    )


def _schedule_contract_template_restore_debug_snapshots(
    app,
    *,
    event_prefix: str,
    layout_name: str,
) -> None:
    if not workspace_debug_enabled("layout"):
        return
    for delay_ms in (0, 25, 100, 250, 1000):
        QTimer.singleShot(
            delay_ms,
            lambda _delay_ms=delay_ms: app._log_contract_template_restore_checkpoint(
                f"{event_prefix}.checkpoint",
                name=str(layout_name or ""),
                delay_ms=int(_delay_ms),
                restore_complete=bool(getattr(app, "_workspace_layout_restore_complete", False)),
                restoring=bool(getattr(app, "_is_restoring_workspace_layout", False)),
            ),
        )


def _apply_workspace_panel_layout_snapshot(
    app,
    snapshot: dict[str, object] | None,
) -> None:
    payload = dict(snapshot or {})
    workspace_debug_log(
        "layout",
        "app.apply_workspace_panel_layout_snapshot.begin",
        snapshot=summarize_panel_layout_snapshot(payload),
    )
    registry = getattr(app, "_catalog_workspace_docks", {})
    for key, dock in list(registry.items()):
        if not isinstance(dock, QDockWidget):
            continue
        restore = getattr(dock, "restore_panel_layout_state", None)
        if not callable(restore):
            continue
        panel_payload = payload.get(str(key))
        if str(key) == "contract_template_workspace":
            app._log_contract_template_restore_checkpoint(
                "app.apply_workspace_panel_layout_snapshot.contract_templates.before_restore",
                requested_panel_state=summarize_panel_layout_state(
                    panel_payload if isinstance(panel_payload, dict) else {}
                ),
            )
        restore(panel_payload if isinstance(panel_payload, dict) else None)
        if str(key) == "contract_template_workspace":
            app._log_contract_template_restore_checkpoint(
                "app.apply_workspace_panel_layout_snapshot.contract_templates.after_restore_request",
                requested_panel_state=summarize_panel_layout_state(
                    panel_payload if isinstance(panel_payload, dict) else {}
                ),
            )
    workspace_debug_log(
        "layout",
        "app.apply_workspace_panel_layout_snapshot.end",
        snapshot=summarize_panel_layout_snapshot(payload),
    )


def _saved_main_window_layout_names(app) -> list[str]:
    return list(app._load_saved_main_window_layouts().keys())


def _find_saved_main_window_layout_name(app, name: str) -> str | None:
    clean_name = str(name or "").strip()
    if not clean_name:
        return None
    for existing_name in app._saved_main_window_layout_names():
        if existing_name.casefold() == clean_name.casefold():
            return existing_name
    return None


def _default_saved_main_window_layout_name(app) -> str:
    existing_names = {name.casefold() for name in app._saved_main_window_layout_names()}
    index = 1
    while True:
        candidate = f"Layout {index}"
        if candidate.casefold() not in existing_names:
            return candidate
        index += 1


def _capture_current_main_window_layout_snapshot(app) -> dict[str, object]:
    profiles_toolbar = getattr(app, "toolbar", None)
    action_ribbon_toolbar = getattr(app, "action_ribbon_toolbar", None)
    add_data_dock = getattr(app, "add_data_dock", None)
    catalog_table_dock = getattr(app, "catalog_table_dock", None)
    action_ribbon_snapshot = app._capture_current_action_ribbon_layout_snapshot()
    snapshot = {
        "schema_version": 4,
        "geometry_b64": app._serialize_qbytearray_setting(app.saveGeometry()),
        "window_state": app._current_main_window_state_marker(),
        "normal_geometry": app._serialize_rect_setting(app.normalGeometry()),
        "dock_state_b64": app._serialize_qbytearray_setting(app.saveState(1)),
        **app._catalog_zoom_layout_state(),
        "add_data_panel": bool(
            isinstance(add_data_dock, QDockWidget) and add_data_dock.isVisible()
        ),
        "catalog_table_panel": bool(
            isinstance(catalog_table_dock, QDockWidget) and catalog_table_dock.isVisible()
        ),
        "profiles_toolbar_visible": bool(
            isinstance(profiles_toolbar, QToolBar) and profiles_toolbar.isVisible()
        ),
        "action_ribbon_visible": bool(
            isinstance(action_ribbon_toolbar, QToolBar) and action_ribbon_toolbar.isVisible()
        ),
        "action_ribbon": action_ribbon_snapshot,
        "workspace_panels": app._capture_current_workspace_panel_layout_snapshot(),
    }
    workspace_debug_log(
        "layout",
        "app.capture_named_main_window_layout_snapshot",
        name=str(getattr(app, "_active_saved_main_window_layout_name", "") or ""),
        workspace_panels=summarize_panel_layout_snapshot(snapshot.get("workspace_panels")),
        contract_template_workspace=app._contract_template_workspace_debug_summary(),
    )
    return snapshot


def _save_named_main_window_layout(app, name: str) -> str | None:
    clean_name = str(name or "").strip()
    if not clean_name:
        return None
    layouts = app._load_saved_main_window_layouts()
    existing_name = app._find_saved_main_window_layout_name(clean_name)
    if existing_name is not None and existing_name != clean_name:
        layouts.pop(existing_name, None)
    layouts[clean_name] = app._capture_current_main_window_layout_snapshot()
    app._write_saved_main_window_layouts(layouts)
    workspace_debug_log(
        "layout",
        "app.save_named_main_window_layout",
        name=clean_name,
        workspace_panels=summarize_panel_layout_snapshot(
            dict(layouts.get(clean_name, {})).get("workspace_panels")
            if isinstance(dict(layouts.get(clean_name, {})), dict)
            else {}
        ),
        contract_template_workspace=app._contract_template_workspace_debug_summary(),
    )
    app._active_saved_main_window_layout_name = clean_name
    app._refresh_saved_layout_controls()
    return clean_name


def _build_named_main_window_layout_switch_request(
    app,
    name: str,
) -> dict[str, object] | None:
    layouts = app._load_saved_main_window_layouts()
    clean_name = str(name or "").strip()
    if not clean_name:
        return None
    known_action_ids = list(getattr(app, "_action_ribbon_specs_by_id", {}).keys())
    current_action_ids = app._normalize_action_ribbon_ids(
        getattr(app, "_action_ribbon_action_ids", [])
    )
    if not current_action_ids:
        current_action_ids = list(getattr(app, "_action_ribbon_default_ids", []))
    return {
        "requested_name": clean_name,
        "layouts": layouts,
        "known_action_ids": known_action_ids,
        "default_action_ids": list(getattr(app, "_action_ribbon_default_ids", [])),
        "current_action_ids": current_action_ids,
        "current_visible": app._current_action_ribbon_visibility(),
    }


def _prepare_named_main_window_layout_switch_request(
    request: dict[str, object],
) -> dict[str, object] | None:
    layouts = request.get("layouts")
    if not isinstance(layouts, dict):
        return None
    requested_name = str(request.get("requested_name") or "").strip()
    if not requested_name:
        return None
    resolved_name = None
    for existing_name in layouts.keys():
        clean_existing_name = str(existing_name or "").strip()
        if clean_existing_name.casefold() == requested_name.casefold():
            resolved_name = clean_existing_name
            break
    if resolved_name is None:
        return None
    snapshot = layouts.get(resolved_name)
    if not isinstance(snapshot, dict):
        return None
    known_action_ids = request.get("known_action_ids")
    current_action_ids = request.get("current_action_ids")
    default_action_ids = request.get("default_action_ids")
    current_visible = bool(request.get("current_visible", True))
    ribbon_action_ids, ribbon_visible = (
        action_ribbon._resolve_saved_layout_action_ribbon_snapshot_payload(
            snapshot,
            current_action_ids=current_action_ids,
            current_visible=current_visible,
            default_action_ids=default_action_ids,
            known_action_ids=known_action_ids,
        )
    )
    return {
        "name": resolved_name,
        "geometry": _deserialize_qbytearray_setting(snapshot.get("geometry_b64")),
        "normal_geometry": _deserialize_rect_setting(snapshot.get("normal_geometry")),
        "window_state_marker": str(snapshot.get("window_state") or ""),
        "dock_state": _deserialize_qbytearray_setting(snapshot.get("dock_state_b64")),
        "workspace_panels": (
            dict(snapshot.get("workspace_panels"))
            if isinstance(snapshot.get("workspace_panels"), dict)
            else {}
        ),
        "add_data_panel": bool(snapshot.get("add_data_panel", False)),
        "catalog_table_panel": bool(snapshot.get("catalog_table_panel", True)),
        "profiles_toolbar_visible": bool(snapshot.get("profiles_toolbar_visible", True)),
        "ribbon_action_ids": ribbon_action_ids,
        "ribbon_visible": bool(ribbon_visible),
        CATALOG_ZOOM_LAYOUT_KEY: snapshot.get(CATALOG_ZOOM_LAYOUT_KEY),
    }


@contextmanager
def _suspend_saved_layout_transition_updates(app):
    widgets: list[QWidget] = []
    seen: set[int] = set()
    direct_children_only = Qt.FindChildOption.FindDirectChildrenOnly
    candidates = [
        app.centralWidget(),
        *app.findChildren(QDockWidget, options=direct_children_only),
        *app.findChildren(QToolBar, options=direct_children_only),
    ]
    for candidate in candidates:
        if not isinstance(candidate, QWidget):
            continue
        if isinstance(candidate, CatalogWorkspaceDock):
            continue
        widget_id = id(candidate)
        if widget_id in seen:
            continue
        seen.add(widget_id)
        widgets.append(candidate)

    previous_update_states: list[tuple[QWidget, bool]] = []
    for widget in widgets:
        try:
            previous_update_states.append((widget, widget.updatesEnabled()))
            widget.setUpdatesEnabled(False)
        except Exception:
            continue
    try:
        yield
    finally:
        for widget, previous_state in previous_update_states:
            try:
                widget.setUpdatesEnabled(previous_state)
                widget.updateGeometry()
                widget.update()
            except Exception:
                continue
        try:
            app.updateGeometry()
            app.update()
        except Exception:
            pass


def _apply_prepared_named_main_window_layout(
    app,
    prepared: dict[str, object],
    *,
    ui_progress=None,
) -> bool:
    resolved_name = str(prepared.get("name") or "").strip()
    if not resolved_name:
        return False

    progress_total = 10

    def _advance(value: int, message: str) -> None:
        if ui_progress is None:
            return
        app._advance_task_ui_progress(
            ui_progress,
            value=value,
            maximum=progress_total,
            message=message,
        )

    ribbon_action_ids = app._normalize_action_ribbon_ids(prepared.get("ribbon_action_ids"))
    if not ribbon_action_ids:
        ribbon_action_ids = list(getattr(app, "_action_ribbon_default_ids", []))

    app._ensure_persistent_workspace_dock_shells()
    app._log_contract_template_restore_checkpoint(
        "app.apply_named_main_window_layout.after_ensure_shells",
        name=resolved_name,
        prepared_workspace_panels=summarize_panel_layout_snapshot(
            prepared.get("workspace_panels")
            if isinstance(prepared.get("workspace_panels"), dict)
            else {}
        ),
    )
    _advance(3, f'Preparing saved layout "{resolved_name}" for restore...')
    previous_suspend_state = app._suspend_dock_state_sync
    previous_restore_state = app._is_restoring_workspace_layout
    app._suspend_dock_state_sync = True
    app._is_restoring_workspace_layout = True
    restored_dock_state = False
    workspace_debug_log(
        "layout",
        "app.apply_named_main_window_layout.begin",
        name=resolved_name,
        workspace_panels=summarize_panel_layout_snapshot(
            prepared.get("workspace_panels")
            if isinstance(prepared.get("workspace_panels"), dict)
            else {}
        ),
        contract_template_workspace=app._contract_template_workspace_debug_summary(),
    )
    try:
        with app._suspend_saved_layout_transition_updates():
            app._apply_main_window_geometry_snapshot(
                geometry=prepared.get("geometry"),
                normal_geometry=prepared.get("normal_geometry"),
                window_state_marker=str(prepared.get("window_state_marker") or ""),
            )
            app._log_contract_template_restore_checkpoint(
                "app.apply_named_main_window_layout.after_geometry",
                name=resolved_name,
            )
            _advance(4, f'Applied saved geometry for layout "{resolved_name}".')
            restored_dock_state = app._apply_main_dock_state_snapshot(prepared.get("dock_state"))
            app._log_contract_template_restore_checkpoint(
                "app.apply_named_main_window_layout.after_main_dock_state",
                name=resolved_name,
                restored_dock_state=bool(restored_dock_state),
            )
            if not restored_dock_state:
                app._apply_add_data_panel_state(bool(prepared.get("add_data_panel", False)))
                app._apply_catalog_table_panel_state(
                    bool(prepared.get("catalog_table_panel", True))
                )
            _advance(
                5,
                (
                    f'Restored saved dock layout for "{resolved_name}".'
                    if restored_dock_state
                    else f'Applied fallback panel visibility for "{resolved_name}".'
                ),
            )
            app._apply_profiles_toolbar_visibility(
                bool(prepared.get("profiles_toolbar_visible", True))
            )
            app._apply_action_ribbon_configuration(
                ribbon_action_ids,
                bool(prepared.get("ribbon_visible", True)),
            )
            if prepared.get(CATALOG_ZOOM_LAYOUT_KEY) is not None:
                app._restore_catalog_zoom_layout_state(
                    {CATALOG_ZOOM_LAYOUT_KEY: prepared.get(CATALOG_ZOOM_LAYOUT_KEY)},
                    immediate=True,
                )
            app._refresh_workspace_dock_default_placement_flags()
            _advance(7, f'Applied toolbar and Action Ribbon state for "{resolved_name}".')

        app._log_contract_template_restore_checkpoint(
            "app.apply_named_main_window_layout.after_transition_updates_resumed",
            name=resolved_name,
        )
        app._apply_workspace_panel_layout_snapshot(
            prepared.get("workspace_panels")
            if isinstance(prepared.get("workspace_panels"), dict)
            else {}
        )
        app._log_contract_template_restore_checkpoint(
            "app.apply_named_main_window_layout.after_workspace_panel_snapshot",
            name=resolved_name,
        )
        _advance(6, f'Applied nested workspace panel state for "{resolved_name}".')
        app._refresh_workspace_dock_default_placement_flags()
        app._materialize_visible_workspace_dock_panels(
            progress_callback=lambda value, maximum, message: (
                ui_progress.report_progress(value=8, maximum=progress_total, message=message)
                if ui_progress is not None
                else None
            )
        )
        app._log_contract_template_restore_checkpoint(
            "app.apply_named_main_window_layout.after_materialize_visible_panels",
            name=resolved_name,
        )
        _advance(8, f'Restored visible workspace panels for "{resolved_name}".')
    finally:
        app._is_restoring_workspace_layout = previous_restore_state
        app._suspend_dock_state_sync = previous_suspend_state

    app._active_saved_main_window_layout_name = resolved_name
    app._store_workspace_panel_visibility_preferences(sync=False)
    app._store_action_ribbon_preferences(
        ribbon_action_ids,
        bool(prepared.get("ribbon_visible", True)),
        sync=False,
    )
    app._refresh_saved_layout_controls()
    _advance(9, f'Waiting for visible workspace repaint and stabilization for "{resolved_name}".')
    app._stabilize_visible_layout_after_restore(
        progress_callback=(
            lambda value, maximum, message: (
                ui_progress.report_progress(
                    value=value,
                    maximum=maximum,
                    message=message,
                )
                if ui_progress is not None
                else None
            )
        ),
        value=9,
        maximum=progress_total,
    )
    app._log_contract_template_restore_checkpoint(
        "app.apply_named_main_window_layout.after_stabilize_visible_layout",
        name=resolved_name,
    )
    app._validate_visible_workspace_dock_panels_after_restore()
    workspace_debug_log(
        "layout",
        "app.apply_named_main_window_layout.end",
        name=resolved_name,
        restored_dock_state=bool(restored_dock_state),
        contract_template_workspace=app._contract_template_workspace_debug_summary(),
    )
    app._schedule_contract_template_restore_debug_snapshots(
        event_prefix="app.apply_named_main_window_layout",
        layout_name=resolved_name,
    )
    app._stop_queued_main_window_layout_persistence()
    app._schedule_main_window_geometry_save()
    app._schedule_main_dock_state_save()
    app._apply_top_chrome_boundary()
    app.settings.sync()
    _advance(10, f'Saved layout "{resolved_name}" is ready.')
    return True


def _apply_named_main_window_layout(app, name: str) -> bool:
    request = app._build_named_main_window_layout_switch_request(name)
    if request is None:
        return False
    prepared = app._prepare_named_main_window_layout_switch_request(request)
    if prepared is None:
        return False
    return app._apply_prepared_named_main_window_layout(prepared)


def _start_named_main_window_layout_switch(app, name: str):
    request = app._build_named_main_window_layout_switch_request(name)
    if request is None:
        app._refresh_saved_layout_controls()
        return None

    progress_total = 10
    requested_name = str(request.get("requested_name") or "").strip()
    apply_result: dict[str, bool] = {"applied": False}

    def _task(ctx):
        ctx.set_status(f'Resolving saved layout "{requested_name}"...')
        prepared = app._prepare_named_main_window_layout_switch_request(request)
        if prepared is None:
            raise RuntimeError(f'Saved layout "{requested_name}" is no longer available.')
        ctx.report_progress(
            value=1,
            maximum=progress_total,
            message=f'Resolved saved layout "{prepared["name"]}" payload.',
        )
        ctx.raise_if_cancelled()
        ctx.report_progress(
            value=2,
            maximum=progress_total,
            message=f'Prepared saved layout "{prepared["name"]}" state.',
        )
        return prepared

    def _before_cleanup(prepared, ui_progress) -> None:
        apply_result["applied"] = app._apply_prepared_named_main_window_layout(
            prepared,
            ui_progress=ui_progress,
        )

    def _after_cleanup(prepared) -> None:
        resolved_name = str(prepared.get("name") or requested_name)
        if apply_result["applied"]:
            app.statusBar().showMessage(f'Switched to layout "{resolved_name}".', 3000)
        else:
            app._refresh_saved_layout_controls()

    def _handle_error(failure: TaskFailure) -> None:
        app._refresh_saved_layout_controls()
        app._show_background_task_error(
            "Switch Layout",
            failure,
            user_message="The saved layout could not be applied.",
        )

    return app._submit_background_task(
        title="Switch Layout",
        description=f'Applying saved layout "{requested_name}"...',
        task_fn=_task,
        kind="read",
        unique_key="saved-layout-switch",
        requires_profile=False,
        show_dialog=True,
        on_success_before_cleanup=_before_cleanup,
        on_success_after_cleanup=_after_cleanup,
        on_error=_handle_error,
    )


def _delete_named_main_window_layout(app, name: str) -> bool:
    layouts = app._load_saved_main_window_layouts()
    resolved_name = app._find_saved_main_window_layout_name(name)
    if resolved_name is None or resolved_name not in layouts:
        return False
    layouts.pop(resolved_name, None)
    app._write_saved_main_window_layouts(layouts)
    if getattr(app, "_active_saved_main_window_layout_name", None) == resolved_name:
        app._active_saved_main_window_layout_name = ""
    app._refresh_saved_layout_controls()
    return True


def _refresh_saved_layout_controls(app) -> None:
    names = app._saved_main_window_layout_names()
    delete_enabled = bool(names)

    delete_action = getattr(app, "delete_layout_action", None)
    if isinstance(delete_action, QAction):
        delete_action.setEnabled(delete_enabled)

    selector = getattr(app, "saved_layout_selector", None)
    if isinstance(selector, QComboBox):
        previous_state = selector.blockSignals(True)
        try:
            selector.clear()
            if names:
                selector.addItem("Saved Layouts", "")
                for layout_name in names:
                    selector.addItem(layout_name, layout_name)
                active_name = str(
                    getattr(app, "_active_saved_main_window_layout_name", "") or ""
                ).strip()
                selector.setEnabled(True)
                active_index = selector.findData(active_name) if active_name else -1
                selector.setCurrentIndex(active_index if active_index > 0 else 0)
            else:
                selector.addItem("No Saved Layouts", "")
                selector.setCurrentIndex(0)
                selector.setEnabled(False)
        finally:
            selector.blockSignals(previous_state)

    delete_button = getattr(app, "saved_layout_delete_button", None)
    if isinstance(delete_button, QPushButton):
        delete_button.setEnabled(delete_enabled)


def _populate_saved_layouts_menu(app) -> None:
    menu = getattr(app, "saved_layouts_menu", None)
    if not isinstance(menu, QMenu):
        return
    menu.clear()
    names = app._saved_main_window_layout_names()
    if not names:
        empty_action = menu.addAction("No Saved Layouts")
        empty_action.setEnabled(False)
        return

    layout_list = QListWidget(menu)
    layout_list.setObjectName("savedLayoutsMenuList")
    layout_list.setSelectionMode(QAbstractItemView.SingleSelection)
    layout_list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
    layout_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    layout_list.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
    for layout_name in names:
        QListWidgetItem(layout_name, layout_list)
    active_name = str(getattr(app, "_active_saved_main_window_layout_name", "") or "").strip()
    if active_name:
        matching_items = layout_list.findItems(active_name, Qt.MatchExactly)
        if matching_items:
            layout_list.setCurrentItem(matching_items[0])
    row_height = layout_list.sizeHintForRow(0)
    if row_height <= 0:
        row_height = max(layout_list.fontMetrics().height() + 8, 24)
    visible_rows = min(len(names), 8)
    frame_height = layout_list.frameWidth() * 2
    layout_list.setFixedHeight((row_height * visible_rows) + frame_height + 2)
    widest_name = max(layout_list.fontMetrics().horizontalAdvance(name) for name in names)
    layout_list.setMinimumWidth(min(max(widest_name + 56, 220), 360))

    def _apply_selected_layout(item: QListWidgetItem | None) -> None:
        if item is None:
            return
        menu.close()
        QTimer.singleShot(
            0,
            lambda layout_name=str(
                item.text() or ""
            ).strip(): app._start_named_main_window_layout_switch(layout_name),
        )

    layout_list.itemClicked.connect(_apply_selected_layout)
    layout_list.itemActivated.connect(_apply_selected_layout)

    widget_action = QWidgetAction(menu)
    widget_action.setDefaultWidget(layout_list)
    menu.addAction(widget_action)


def add_named_main_window_layout(app) -> None:
    names = app._saved_main_window_layout_names()
    active_name = app._find_saved_main_window_layout_name(
        str(getattr(app, "_active_saved_main_window_layout_name", "") or "")
    )
    suggested_name = active_name or app._default_saved_main_window_layout_name()
    while True:
        name, ok = _name_choice_dialog(app)(
            app,
            title="Save Layout",
            label="Layout name:",
            choices=names,
            suggested_name=suggested_name,
            placeholder="Enter a new layout name",
        )
        if not ok:
            return
        clean_name = str(name or "").strip()
        if clean_name:
            break
        _message_box(app).warning(app, "Save Layout", "Enter a layout name before saving.")
        suggested_name = str(name or "")

    existing_name = app._find_saved_main_window_layout_name(clean_name)
    if existing_name is not None:
        message_box = _message_box(app)
        answer = message_box.question(
            app,
            "Overwrite Layout",
            f'A saved layout named "{existing_name}" already exists.\n\nOverwrite it?',
            message_box.Yes | message_box.No,
            message_box.No,
        )
        if answer != message_box.Yes:
            return

    saved_name = app._save_named_main_window_layout(clean_name)
    if saved_name is not None:
        app.statusBar().showMessage(f'Saved layout "{saved_name}".', 3000)


def delete_named_main_window_layout_interactive(app, preferred_name: str | None = None) -> None:
    names = app._saved_main_window_layout_names()
    if not names:
        _message_box(app).information(app, "Delete Layout", "No saved layouts are available yet.")
        return

    resolved_name = app._find_saved_main_window_layout_name(preferred_name or "")
    default_index = names.index(resolved_name) if resolved_name in names else 0
    selected_name, ok = _input_dialog(app).getItem(
        app,
        "Delete Layout",
        "Choose the saved layout to delete:",
        names,
        default_index,
        False,
    )
    if not ok or not selected_name:
        return

    message_box = _message_box(app)
    answer = message_box.question(
        app,
        "Delete Layout",
        f'Delete the saved layout "{selected_name}"?',
        message_box.Yes | message_box.No,
        message_box.No,
    )
    if answer != message_box.Yes:
        return

    if app._delete_named_main_window_layout(selected_name):
        app.statusBar().showMessage(f'Deleted layout "{selected_name}".', 3000)


def _on_saved_layout_selected(app, index: int) -> None:
    selector = getattr(app, "saved_layout_selector", None)
    if not isinstance(selector, QComboBox):
        return
    selected_name = str(selector.itemData(index) or "").strip()
    if not selected_name:
        return
    QTimer.singleShot(
        0,
        lambda layout_name=selected_name: app._start_named_main_window_layout_switch(layout_name),
    )


def _store_workspace_panel_visibility_preferences(app, *, sync: bool = True) -> None:
    try:
        add_data_enabled = bool(
            isinstance(getattr(app, "add_data_dock", None), QDockWidget)
            and app.add_data_dock.isVisible()
        )
        catalog_table_enabled = bool(
            isinstance(getattr(app, "catalog_table_dock", None), QDockWidget)
            and app.catalog_table_dock.isVisible()
        )
        app.settings.setValue("display/add_data_panel", add_data_enabled)
        app.settings.setValue("display/catalog_table_panel", catalog_table_enabled)
        app._set_action_checked_silently(app.add_data_action, add_data_enabled)
        app._set_action_checked_silently(
            app.catalog_table_action,
            catalog_table_enabled,
        )
        if sync:
            app.settings.sync()
    except Exception as e:
        app.logger.warning("Failed to store workspace panel visibility: %s", e)


def _sync_dock_visibility(app, action: QAction, setting_key: str, visible: bool) -> None:
    app._set_action_checked_silently(action, visible)
    if (
        getattr(app, "_suspend_dock_state_sync", False)
        or getattr(app, "_is_restoring_workspace_layout", False)
        or getattr(app, "_is_closing", False)
        or not getattr(app, "_workspace_layout_restore_complete", False)
    ):
        return
    try:
        app.settings.setValue(setting_key, bool(visible))
        app._schedule_main_dock_state_save()
        app.settings.sync()
    except Exception as e:
        app.logger.warning("Failed to sync dock visibility for %s: %s", setting_key, e)


def _apply_add_data_panel_state(app, enabled: bool):
    enabled = bool(enabled)
    dock = getattr(app, "add_data_dock", None)
    action = getattr(app, "add_data_action", None)
    if action is not None:
        app._set_action_checked_silently(action, enabled)
    if isinstance(dock, QDockWidget):
        dock.setVisible(enabled)
        if enabled:
            dock.raise_()
            app._ensure_add_track_panel_initialized()


def _apply_catalog_table_panel_state(app, enabled: bool):
    enabled = bool(enabled)
    dock = getattr(app, "catalog_table_dock", None)
    action = getattr(app, "catalog_table_action", None)
    if action is not None:
        app._set_action_checked_silently(action, enabled)
    if isinstance(dock, QDockWidget):
        dock.setVisible(enabled)
        if enabled:
            dock.raise_()


def _ensure_persistent_workspace_dock_shells(app) -> None:
    previous_suspend_state = app._suspend_dock_state_sync
    previous_restore_state = app._is_restoring_workspace_layout
    app._suspend_dock_state_sync = True
    app._is_restoring_workspace_layout = True
    try:
        for ensure_dock in (
            app._ensure_release_browser_dock,
            app._ensure_work_manager_dock,
            app._ensure_global_search_dock,
            app._ensure_party_manager_dock,
            app._ensure_contract_manager_dock,
            app._ensure_code_registry_workspace_dock,
            app._ensure_promo_code_ledger_dock,
            app._ensure_contract_template_workspace_dock,
            app._ensure_rights_matrix_dock,
            app._ensure_asset_registry_dock,
        ):
            ensure_dock()
    finally:
        app._is_restoring_workspace_layout = previous_restore_state
        app._suspend_dock_state_sync = previous_suspend_state


def _restore_workspace_layout_on_first_show(app) -> None:
    if getattr(app, "_workspace_layout_restore_complete", False):
        return
    app._report_startup_phase(StartupPhase.RESTORING_WORKSPACE)
    restore_progress = app._startup_progress_callback(StartupPhase.RESTORING_WORKSPACE)
    app._workspace_layout_restore_scheduled = False
    previous_suspend_state = app._suspend_dock_state_sync
    previous_restore_state = app._is_restoring_workspace_layout
    app._suspend_dock_state_sync = True
    app._is_restoring_workspace_layout = True
    restored_dock_state = False
    visible_lazy_docks = [
        dock
        for dock in list(getattr(app, "_catalog_workspace_docks", {}).values())
        if isinstance(dock, QDockWidget)
        and dock.isVisible()
        and getattr(dock, "_panel", None) is None
    ]
    materialize_steps = max(1, len(visible_lazy_docks))
    total_steps = 9 + materialize_steps
    completed_steps = 0

    def _advance(message: str) -> None:
        nonlocal completed_steps
        completed_steps += 1
        restore_progress(completed_steps, total_steps, message)

    try:
        app._restore_main_window_geometry()
        app._log_contract_template_restore_checkpoint(
            "app.restore_workspace_layout_on_first_show.after_geometry",
            name=str(getattr(app, "_active_saved_main_window_layout_name", "") or ""),
        )
        _advance("Restored main window geometry.")
        restored_dock_state = app._restore_main_dock_state()
        app._log_contract_template_restore_checkpoint(
            "app.restore_workspace_layout_on_first_show.after_main_dock_state",
            name=str(getattr(app, "_active_saved_main_window_layout_name", "") or ""),
            restored_dock_state=bool(restored_dock_state),
        )
        _advance("Restored saved workspace dock layout.")
        app._apply_saved_view_preferences(apply_workspace_panel_visibility=not restored_dock_state)
        _advance("Applied saved workspace panel visibility.")
        app._refresh_workspace_dock_default_placement_flags()
        _advance("Refreshed workspace dock placement defaults.")
        app._apply_workspace_panel_layout_snapshot(app._load_workspace_panel_layouts())
        app._log_contract_template_restore_checkpoint(
            "app.restore_workspace_layout_on_first_show.after_workspace_panel_snapshot",
            name=str(getattr(app, "_active_saved_main_window_layout_name", "") or ""),
        )
        _advance("Applied nested workspace panel layout state.")
        app._materialize_visible_workspace_dock_panels(
            progress_callback=lambda value, maximum, message: restore_progress(
                completed_steps + value,
                total_steps,
                message,
            )
        )
        app._log_contract_template_restore_checkpoint(
            "app.restore_workspace_layout_on_first_show.after_materialize_visible_panels",
            name=str(getattr(app, "_active_saved_main_window_layout_name", "") or ""),
        )
        completed_steps += materialize_steps
    finally:
        app._restored_main_dock_state = restored_dock_state
        app._workspace_layout_restore_complete = True
        app._is_restoring_workspace_layout = previous_restore_state
        app._suspend_dock_state_sync = previous_suspend_state
    app._store_workspace_panel_visibility_preferences(sync=False)
    _advance("Stored restored workspace visibility preferences.")
    app._schedule_main_window_geometry_save()
    _advance("Queued startup window geometry persistence.")
    app._schedule_main_dock_state_save()
    _advance("Queued startup dock layout persistence.")
    app._stabilize_visible_layout_after_restore(
        progress_callback=restore_progress,
        value=total_steps,
        maximum=total_steps,
    )
    app._log_contract_template_restore_checkpoint(
        "app.restore_workspace_layout_on_first_show.after_stabilize_visible_layout",
        name=str(getattr(app, "_active_saved_main_window_layout_name", "") or ""),
    )
    app._validate_visible_workspace_dock_panels_after_restore()
    _advance("Workspace visually stabilized and ready.")
    app._schedule_contract_template_restore_debug_snapshots(
        event_prefix="app.restore_workspace_layout_on_first_show",
        layout_name=str(getattr(app, "_active_saved_main_window_layout_name", "") or ""),
    )
    app._maybe_finish_startup_loading()


def _materialize_visible_workspace_dock_panels(app, *, progress_callback=None) -> None:
    registry = getattr(app, "_catalog_workspace_docks", {})
    docks_to_materialize = [
        dock
        for dock in list(registry.values())
        if isinstance(dock, QDockWidget)
        and dock.isVisible()
        and getattr(dock, "_panel", None) is None
    ]
    total_docks = max(1, len(docks_to_materialize))
    if not docks_to_materialize:
        if callable(progress_callback):
            progress_callback(1, total_docks, "No workspace panels needed restoration.")
        return
    for index, dock in enumerate(docks_to_materialize, start=1):
        panel_method = getattr(dock, "panel", None)
        if callable(panel_method):
            panel_method()
        refresh_method = getattr(dock, "refresh_panel", None)
        if callable(refresh_method):
            refresh_method()
        if callable(progress_callback):
            dock_title = str(dock.windowTitle() or dock.objectName() or "workspace panel")
            progress_callback(
                index,
                total_docks,
                f"Restored {dock_title} workspace panel.",
            )


def _validate_visible_workspace_dock_panels_after_restore(app) -> None:
    registry = getattr(app, "_catalog_workspace_docks", {})
    for dock in list(registry.values()):
        if not isinstance(dock, QDockWidget) or not dock.isVisible():
            continue
        stabilize = getattr(dock, "stabilize_panel_layout_after_restore", None)
        if callable(stabilize):
            try:
                stabilize()
            except Exception:
                continue
    workspace_debug_log(
        "layout",
        "app.validate_visible_workspace_dock_panels_after_restore",
        visible_docks=[
            str(dock.objectName() or "")
            for dock in list(registry.values())
            if isinstance(dock, QDockWidget) and dock.isVisible()
        ],
    )


def _refresh_workspace_dock_default_placement_flags(app) -> None:
    registry = getattr(app, "_catalog_workspace_docks", {})
    for dock in list(registry.values()):
        if not isinstance(dock, QDockWidget):
            continue
        default_area = getattr(dock, "_default_dock_area", Qt.RightDockWidgetArea)
        has_tab_peers = bool(app.tabifiedDockWidgets(dock))
        area = app.dockWidgetArea(dock)
        dock._default_placement_pending = not (
            dock.isVisible() or has_tab_peers or area != default_area
        )


def _apply_saved_view_preferences(app, *, apply_workspace_panel_visibility: bool = True):
    previous_suspend_state = app._suspend_layout_history
    app._suspend_layout_history = True
    try:
        columns_movable = app._catalog_header_state_manager().load_columns_movable_state(
            default=False
        )
        col_width_enabled = app.settings.value("display/interactive_col_width", False, bool)
        row_height_enabled = app.settings.value("display/interactive_row_height", False, bool)
        add_data_enabled = app.settings.value("display/add_data_panel", False, bool)
        catalog_table_enabled = app.settings.value("display/catalog_table_panel", True, bool)
        profiles_toolbar_visible = app.settings.value(
            "display/profiles_toolbar_visible",
            True,
            bool,
        )
        action_ribbon_visible = app.settings.value("display/action_ribbon_visible", True, bool)
        action_ribbon_ids = app._load_saved_action_ribbon_action_ids()

        if not apply_workspace_panel_visibility:
            add_data_dock = getattr(app, "add_data_dock", None)
            catalog_table_dock = getattr(app, "catalog_table_dock", None)
            if isinstance(add_data_dock, QDockWidget):
                add_data_enabled = bool(add_data_dock.isVisible())
            if isinstance(catalog_table_dock, QDockWidget):
                catalog_table_enabled = bool(catalog_table_dock.isVisible())

        app._set_action_checked_silently(app.act_reorder_columns, columns_movable)
        app._set_action_checked_silently(app.col_width_action, col_width_enabled)
        app._set_action_checked_silently(app.row_height_action, row_height_enabled)
        app._set_action_checked_silently(app.add_data_action, add_data_enabled)
        app._set_action_checked_silently(app.catalog_table_action, catalog_table_enabled)
        app._set_action_checked_silently(
            app.profiles_toolbar_visibility_action,
            profiles_toolbar_visible,
        )
        app._set_action_checked_silently(app.action_ribbon_visibility_action, action_ribbon_visible)

        app._apply_columns_movable_state(columns_movable)
        app._apply_col_width_mode(col_width_enabled)
        app._apply_row_height_mode(row_height_enabled)
        if apply_workspace_panel_visibility:
            app._apply_add_data_panel_state(add_data_enabled)
            app._apply_catalog_table_panel_state(catalog_table_enabled)
        app._apply_profiles_toolbar_visibility(profiles_toolbar_visible)
        app._apply_action_ribbon_configuration(action_ribbon_ids, action_ribbon_visible)
    finally:
        app._suspend_layout_history = previous_suspend_state


def _on_toggle_col_width(app, enabled: bool):
    enabled = bool(enabled)

    def mutation():
        app._apply_col_width_mode(enabled)
        app.settings.setValue("display/interactive_col_width", enabled)
        app.settings.sync()

    app._run_setting_bundle_history_action(
        action_label="Toggle Column Width Editing",
        setting_keys=["display/interactive_col_width"],
        mutation=mutation,
        entity_id="display/interactive_col_width",
    )


def _on_toggle_row_height(app, enabled: bool):
    enabled = bool(enabled)

    def mutation():
        app._apply_row_height_mode(enabled)
        app.settings.setValue("display/interactive_row_height", enabled)
        app.settings.sync()

    app._run_setting_bundle_history_action(
        action_label="Toggle Row Height Editing",
        setting_keys=["display/interactive_row_height"],
        mutation=mutation,
        entity_id="display/interactive_row_height",
    )


def _on_toggle_add_data(app, enabled: bool):
    enabled = bool(enabled)

    def mutation():
        app._apply_add_data_panel_state(enabled)
        app.settings.setValue("display/add_data_panel", enabled)
        app.settings.sync()

    app._run_setting_bundle_history_action(
        action_label="Toggle Add Track Panel",
        setting_keys=["display/add_data_panel"],
        mutation=mutation,
        entity_id="display/add_data_panel",
    )


def _on_toggle_catalog_table(app, enabled: bool):
    enabled = bool(enabled)

    def mutation():
        app._apply_catalog_table_panel_state(enabled)
        app.settings.setValue("display/catalog_table_panel", enabled)
        app.settings.sync()

    app._run_setting_bundle_history_action(
        action_label="Toggle Catalog Table",
        setting_keys=["display/catalog_table_panel"],
        mutation=mutation,
        entity_id="display/catalog_table_panel",
    )

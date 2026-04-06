"""Opt-in runtime debug logging for catalog workspace panels."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QComboBox, QDockWidget, QFormLayout, QLabel, QMainWindow, QScrollArea, QWidget

try:
    from shiboken6 import isValid as _qt_object_is_valid
except Exception:  # pragma: no cover - runtime guard
    def _qt_object_is_valid(_obj) -> bool:
        return True


_TRUE_VALUES = {"1", "true", "yes", "on", "debug"}
_FILE_LOCK = threading.Lock()
_LOGGER = logging.getLogger("isrc_manager.workspace_debug")


def _env_flag(name: str) -> bool:
    return str(os.environ.get(name, "")).strip().lower() in _TRUE_VALUES


def _env_topics(name: str) -> set[str]:
    raw_value = str(os.environ.get(name, "")).strip().lower()
    if not raw_value:
        return set()
    if raw_value in _TRUE_VALUES:
        return {"all"}
    return {
        token.strip()
        for token in raw_value.replace(";", ",").split(",")
        if token.strip()
    }


def workspace_debug_enabled(topic: str | None = None) -> bool:
    clean_topic = str(topic or "").strip().lower()
    configured_topics = _env_topics("ISRC_CT_WORKSPACE_DEBUG") | _env_topics(
        "ISRC_CONTRACT_TEMPLATE_DEBUG"
    )
    if configured_topics.intersection({"all", "*"}):
        return True
    if clean_topic and clean_topic in configured_topics:
        return True
    if clean_topic == "layout":
        return _env_flag("ISRC_CT_LAYOUT_DEBUG")
    if clean_topic == "preview":
        return _env_flag("ISRC_CT_PREVIEW_DEBUG")
    if clean_topic == "events":
        return _env_flag("ISRC_CT_PREVIEW_EVENT_DEBUG")
    return False


def _rect_payload(rect) -> dict[str, int] | None:
    if not isinstance(rect, QRect):
        return None
    return {
        "x": int(rect.x()),
        "y": int(rect.y()),
        "width": int(rect.width()),
        "height": int(rect.height()),
    }


def _size_payload(size) -> dict[str, int] | None:
    if not isinstance(size, QSize):
        return None
    return {
        "width": int(size.width()),
        "height": int(size.height()),
    }


def _json_safe(value: Any):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, QRect):
        return _rect_payload(value)
    if isinstance(value, QSize):
        return _size_payload(value)
    try:
        return str(value)
    except Exception:
        return repr(value)


def _widget_descriptor(widget: QWidget | None) -> dict[str, object] | None:
    if widget is None or not _qt_object_is_valid(widget):
        return None
    return {
        "class_name": widget.__class__.__name__,
        "object_name": str(widget.objectName() or ""),
        "visible": bool(widget.isVisible()),
        "enabled": bool(widget.isEnabled()),
        "geometry": _rect_payload(widget.geometry()),
        "size": _size_payload(widget.size()),
    }


def _combo_summary(combo: QComboBox | None) -> dict[str, object] | None:
    if not isinstance(combo, QComboBox) or not _qt_object_is_valid(combo):
        return None
    return {
        "count": int(combo.count()),
        "current_index": int(combo.currentIndex()),
        "current_text": str(combo.currentText() or ""),
        "enabled": bool(combo.isEnabled()),
        "visible": bool(combo.isVisible()),
    }


def _label_summary(label: QLabel | None) -> dict[str, object] | None:
    if not isinstance(label, QLabel) or not _qt_object_is_valid(label):
        return None
    return {
        "text": str(label.text() or ""),
        "visible": bool(label.isVisible()),
        "enabled": bool(label.isEnabled()),
    }


def _enum_payload(value: Any) -> int | str | None:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        pass
    raw_value = getattr(value, "value", None)
    if raw_value is not None:
        try:
            return int(raw_value)
        except Exception:
            try:
                return str(raw_value)
            except Exception:
                return repr(raw_value)
    try:
        return str(value)
    except Exception:
        return repr(value)


def _form_layout_summary(layout: QFormLayout | None) -> dict[str, object] | None:
    if not isinstance(layout, QFormLayout):
        return None
    return {
        "row_count": int(layout.rowCount()),
        "field_growth_policy": _enum_payload(layout.fieldGrowthPolicy()),
        "row_wrap_policy": _enum_payload(layout.rowWrapPolicy()),
    }


def _scroll_area_summary(scroll: QScrollArea | None) -> dict[str, object] | None:
    if not isinstance(scroll, QScrollArea) or not _qt_object_is_valid(scroll):
        return None
    content = scroll.widget()
    viewport = scroll.viewport()
    try:
        direct_child_widgets = [
            child
            for child in content.findChildren(QWidget, options=Qt.FindDirectChildrenOnly)
            if _qt_object_is_valid(child)
        ] if isinstance(content, QWidget) else []
    except Exception:
        direct_child_widgets = []
    return {
        "viewport": _widget_descriptor(viewport) if isinstance(viewport, QWidget) else None,
        "content": _widget_descriptor(content) if isinstance(content, QWidget) else None,
        "vertical_scroll": {
            "value": int(scroll.verticalScrollBar().value()),
            "maximum": int(scroll.verticalScrollBar().maximum()),
            "page_step": int(scroll.verticalScrollBar().pageStep()),
        },
        "horizontal_scroll": {
            "value": int(scroll.horizontalScrollBar().value()),
            "maximum": int(scroll.horizontalScrollBar().maximum()),
            "page_step": int(scroll.horizontalScrollBar().pageStep()),
        },
        "direct_child_widget_count": int(len(direct_child_widgets)),
        "direct_visible_child_widget_count": int(
            len([child for child in direct_child_widgets if child.isVisible()])
        ),
        "direct_visible_children": [
            {
                "class_name": child.__class__.__name__,
                "object_name": str(child.objectName() or ""),
                "geometry": _rect_payload(child.geometry()),
            }
            for child in direct_child_widgets[:8]
            if child.isVisible()
        ],
    }


def _log_path() -> Path | None:
    raw_path = str(os.environ.get("ISRC_CT_WORKSPACE_DEBUG_FILE", "")).strip()
    if not raw_path:
        return None
    return Path(raw_path).expanduser()


def workspace_debug_log(topic: str, event: str, **payload) -> None:
    if not workspace_debug_enabled(topic):
        return
    if _env_flag("ISRC_CT_DEBUG_STACKS"):
        stack_lines = traceback.format_stack(limit=10)
        payload["stack"] = [
            line.rstrip()
            for line in stack_lines[:-1]
            if "workspace_debug.py" not in line
        ]
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "topic": str(topic or "").strip().lower(),
        "event": str(event or "").strip(),
        "payload": _json_safe(payload),
    }
    line = json.dumps(record, ensure_ascii=True, sort_keys=True)
    _LOGGER.info("%s", line)
    debug_path = _log_path()
    if debug_path is None:
        return
    try:
        debug_path.parent.mkdir(parents=True, exist_ok=True)
        with _FILE_LOCK:
            with debug_path.open("a", encoding="utf-8") as handle:
                handle.write(line)
                handle.write("\n")
    except Exception:
        return


def digest_debug_value(value: object) -> str:
    text = _json_safe(value)
    payload = json.dumps(text, ensure_ascii=True, sort_keys=True)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


def summarize_panel_layout_state(state: dict[str, object] | None) -> dict[str, object]:
    payload = dict(state or {})
    tabs = dict(payload.get("tabs") or {})
    return {
        "schema_version": int(payload.get("schema_version") or 0),
        "current_tab": str(payload.get("current_tab") or ""),
        "tabs": {
            str(key): {
                "layout_locked": bool((entry or {}).get("layout_locked", True)),
                "layout_version": int((entry or {}).get("layout_version") or 0),
                "dock_state_b64_len": len(str((entry or {}).get("dock_state_b64") or "")),
                "dock_state_digest": digest_debug_value(
                    str((entry or {}).get("dock_state_b64") or "")
                ),
                "dock_object_names": list((entry or {}).get("dock_object_names") or []),
                "dock_visibility": dict((entry or {}).get("dock_visibility") or {}),
            }
            for key, entry in tabs.items()
            if isinstance(entry, dict)
        },
    }


def summarize_panel_layout_snapshot(snapshot: dict[str, object] | None) -> dict[str, object]:
    payload = dict(snapshot or {})
    return {
        str(key): summarize_panel_layout_state(value if isinstance(value, dict) else {})
        for key, value in payload.items()
    }


def summarize_qdockwidget(
    dock: QDockWidget,
    *,
    host: QMainWindow | None = None,
) -> dict[str, object]:
    if not isinstance(dock, QDockWidget) or not _qt_object_is_valid(dock):
        return {"valid": False}
    try:
        toggle_action = dock.toggleViewAction()
        area = host.dockWidgetArea(dock) if isinstance(host, QMainWindow) else None
        return {
            "valid": True,
            "object_name": str(dock.objectName() or ""),
            "title": str(dock.windowTitle() or ""),
            "visible": bool(dock.isVisible()),
            "hidden": bool(dock.isHidden()),
            "updates_enabled": bool(dock.updatesEnabled()),
            "floating": bool(dock.isFloating()),
            "toggle_checked": bool(isinstance(toggle_action, QAction) and toggle_action.isChecked()),
            "area": _enum_payload(area) or 0,
            "last_dock_area": _enum_payload(dock.property("lastDockArea")) or 0,
            "geometry": _rect_payload(dock.geometry()),
            "minimum_size": _size_payload(dock.minimumSize()),
            "widget_class_name": dock.widget().__class__.__name__ if isinstance(dock.widget(), QWidget) else "",
            "widget_visible": bool(isinstance(dock.widget(), QWidget) and dock.widget().isVisible()),
            "scroll_area": _scroll_area_summary(dock.widget()),
        }
    except Exception as exc:
        return {
            "valid": False,
            "error": f"{type(exc).__name__}: {exc}",
        }


def summarize_workspace_host(host: QWidget) -> dict[str, object]:
    if host is None or not _qt_object_is_valid(host):
        return {"valid": False}
    try:
        central_widget = getattr(host, "centralWidget", lambda: None)()
        docks = list(getattr(host, "_docks", []) or [])
        pending_state = dict(getattr(host, "_pending_state", {}) or {})
        stable_state = dict(getattr(host, "_stable_layout_state", {}) or {})
        return {
            "valid": True,
            "object_name": str(host.objectName() or ""),
            "tab_key": str(getattr(host, "tab_key", "") or ""),
            "visible": bool(host.isVisible()),
            "hidden": bool(host.isHidden()),
            "updates_enabled": bool(host.updatesEnabled()),
            "size": _size_payload(host.size()),
            "geometry": _rect_payload(host.geometry()),
            "central_geometry": _rect_payload(central_widget.geometry())
            if isinstance(central_widget, QWidget)
            else None,
            "locked": bool(getattr(host, "_locked", True)),
            "layout_normalization_pending": bool(
                getattr(host, "_layout_normalization_pending", False)
            ),
            "pending_state": {
                "layout_locked": bool(pending_state.get("layout_locked", True)),
                "layout_version": int(pending_state.get("layout_version") or 0),
                "dock_state_b64_len": len(str(pending_state.get("dock_state_b64") or "")),
                "dock_state_digest": digest_debug_value(str(pending_state.get("dock_state_b64") or "")),
                "dock_object_names": list(pending_state.get("dock_object_names") or []),
                "dock_visibility": dict(pending_state.get("dock_visibility") or {}),
            }
            if pending_state
            else None,
            "stable_state": {
                "layout_locked": bool(stable_state.get("layout_locked", True)),
                "layout_version": int(stable_state.get("layout_version") or 0),
                "dock_state_b64_len": len(str(stable_state.get("dock_state_b64") or "")),
                "dock_state_digest": digest_debug_value(str(stable_state.get("dock_state_b64") or "")),
                "dock_object_names": list(stable_state.get("dock_object_names") or []),
                "dock_visibility": dict(stable_state.get("dock_visibility") or {}),
            }
            if stable_state
            else None,
            "docks": [
                summarize_qdockwidget(dock, host=host if isinstance(host, QMainWindow) else None)
                for dock in docks
            ],
        }
    except Exception as exc:
        return {
            "valid": False,
            "error": f"{type(exc).__name__}: {exc}",
        }


def summarize_contract_template_panel(panel: QWidget | None) -> dict[str, object]:
    if panel is None or not _qt_object_is_valid(panel):
        return {"valid": False}
    try:
        tab_hosts = dict(getattr(panel, "_tab_hosts", {}) or {})
        pending_tab_layout_states = dict(getattr(panel, "_pending_tab_layout_states", {}) or {})
        workspace_tabs = getattr(panel, "workspace_tabs", None)
        current_tab_callable = getattr(panel, "_current_tab_key", None)
        selected_fill_revision_callable = getattr(panel, "_selected_fill_revision_id", None)
        current_tab = ""
        selected_fill_revision_id = None
        if callable(current_tab_callable):
            try:
                current_tab = str(current_tab_callable() or "")
            except Exception:
                current_tab = ""
        if callable(selected_fill_revision_callable):
            try:
                selected_fill_revision_id = selected_fill_revision_callable()
            except Exception:
                selected_fill_revision_id = None
        return {
            "valid": True,
            "class_name": panel.__class__.__name__,
            "object_name": str(panel.objectName() or ""),
            "visible": bool(panel.isVisible()),
            "hidden": bool(panel.isHidden()),
            "enabled": bool(panel.isEnabled()),
            "updates_enabled": bool(panel.updatesEnabled()),
            "geometry": _rect_payload(panel.geometry()),
            "size": _size_payload(panel.size()),
            "current_tab": current_tab,
            "workspace_tab_count": int(workspace_tabs.count()) if workspace_tabs is not None else 0,
            "restoring_layout_state": bool(getattr(panel, "_restoring_layout_state", False)),
            "suspend_preview_refresh": bool(getattr(panel, "_suspend_preview_refresh", False)),
            "selected_fill_revision_id": selected_fill_revision_id,
            "fill_template_combo": _combo_summary(getattr(panel, "fill_template_combo", None)),
            "fill_revision_combo": _combo_summary(getattr(panel, "fill_revision_combo", None)),
            "fill_draft_combo": _combo_summary(getattr(panel, "fill_draft_combo", None)),
            "fill_status_label": _label_summary(getattr(panel, "fill_status_label", None)),
            "fill_warning_label": _label_summary(getattr(panel, "fill_warning_label", None)),
            "fill_preview_status_label": _label_summary(
                getattr(panel, "fill_preview_status_label", None)
            ),
            "fill_preview_stale_label": _label_summary(getattr(panel, "fill_preview_stale_label", None)),
            "fill_auto_form": _form_layout_summary(getattr(panel, "fill_auto_form", None)),
            "fill_selector_form": _form_layout_summary(getattr(panel, "fill_selector_form", None)),
            "fill_manual_form": _form_layout_summary(getattr(panel, "fill_manual_form", None)),
            "pending_tab_layout_states": summarize_panel_layout_state(
                {
                    "schema_version": 1,
                    "current_tab": current_tab,
                    "tabs": {
                        str(key): value
                        for key, value in pending_tab_layout_states.items()
                        if isinstance(value, dict)
                    },
                }
            ),
            "hosts": {
                str(key): summarize_workspace_host(host)
                for key, host in tab_hosts.items()
                if isinstance(host, QWidget)
            },
        }
    except Exception as exc:
        return {
            "valid": False,
            "error": f"{type(exc).__name__}: {exc}",
        }


def summarize_catalog_workspace_dock(dock: QDockWidget | None) -> dict[str, object]:
    if not isinstance(dock, QDockWidget) or not _qt_object_is_valid(dock):
        return {"valid": False}
    try:
        host = dock.parentWidget() if isinstance(dock.parentWidget(), QMainWindow) else None
        panel = getattr(dock, "_panel", None)
        pending_panel_layout_state = getattr(dock, "_pending_panel_layout_state", None)
        summary = summarize_qdockwidget(dock, host=host)
        summary.update(
            {
                "pending_panel_layout_state_dirty": bool(
                    getattr(dock, "_pending_panel_layout_state_dirty", False)
                ),
                "pending_panel_layout_state": summarize_panel_layout_state(
                    pending_panel_layout_state if isinstance(pending_panel_layout_state, dict) else {}
                ),
                "default_placement_pending": bool(
                    getattr(dock, "_default_placement_pending", False)
                ),
                "panel_materialized": bool(isinstance(panel, QWidget)),
                "panel_class_name": panel.__class__.__name__ if isinstance(panel, QWidget) else "",
                "panel_summary": summarize_contract_template_panel(panel)
                if isinstance(panel, QWidget)
                else {"valid": False},
            }
        )
        return summary
    except Exception as exc:
        return {
            "valid": False,
            "error": f"{type(exc).__name__}: {exc}",
        }

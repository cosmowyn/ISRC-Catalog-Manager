"""Runtime UI inventory discovery for the UI PQ framework."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDockWidget,
    QLineEdit,
    QMenu,
    QTabWidget,
    QTextEdit,
    QToolBar,
    QWidget,
)

_IDENTIFIER_RE = re.compile(r"[^a-z0-9]+")


@dataclass(slots=True)
class UIInventoryItem:
    inventory_id: str
    kind: str
    ui_area: str
    object_name: str
    text: str
    class_name: str
    parent: str
    path: str
    visible: bool
    enabled: bool
    has_stable_object_name: bool


def normalize_identifier(value: object, *, fallback: str = "unnamed") -> str:
    text = str(value or "").strip().lower()
    text = text.replace("&", "")
    text = _IDENTIFIER_RE.sub("_", text).strip("_")
    return text or fallback


def classify_ui_area(*parts: object) -> str:
    text = " ".join(str(part or "").lower() for part in parts)
    keywords = (
        ("soundcloud", "soundcloud"),
        ("authenticity", "authenticity"),
        ("watermark", "authenticity"),
        ("forensic", "authenticity"),
        ("diagnostic", "diagnostics"),
        ("repair", "recovery"),
        ("restore", "recovery"),
        ("backup", "recovery"),
        ("snapshot", "history_recovery"),
        ("history", "history_recovery"),
        ("undo", "history_recovery"),
        ("redo", "history_recovery"),
        ("theme", "settings_theme_help"),
        ("qss", "settings_theme_help"),
        ("settings", "settings_theme_help"),
        ("preferences", "settings_theme_help"),
        ("help", "settings_theme_help"),
        ("about", "settings_theme_help"),
        ("profile", "startup_profile"),
        ("database", "startup_profile"),
        ("catalog", "catalog"),
        ("track", "catalog"),
        ("album", "catalog"),
        ("work", "works_releases_parties"),
        ("release", "works_releases_parties"),
        ("party", "works_releases_parties"),
        ("artist", "works_releases_parties"),
        ("asset", "assets_deliverables"),
        ("deliverable", "assets_deliverables"),
        ("contract template", "contract_templates"),
        ("template", "contract_templates"),
        ("contract", "contracts_rights"),
        ("license", "contracts_rights"),
        ("right", "contracts_rights"),
        ("royalt", "accounting_royalties"),
        ("invoice", "accounting_royalties"),
        ("ledger", "accounting_royalties"),
        ("payment", "accounting_royalties"),
        ("payout", "accounting_royalties"),
        ("statement", "accounting_royalties"),
        ("report", "reports"),
        ("import", "import_export"),
        ("export", "import_export"),
        ("media", "media_audio"),
        ("audio", "media_audio"),
        ("player", "media_audio"),
        ("gs1", "gs1"),
        ("code registry", "code_registry"),
        ("registry", "code_registry"),
        ("search", "search"),
        ("update", "update_release"),
        ("log", "logs_support"),
        ("support", "logs_support"),
    )
    for keyword, area in keywords:
        if keyword in text:
            return area
    return "unknown"


def _widget_path(widget: QWidget) -> str:
    names: list[str] = []
    current: QWidget | None = widget
    while current is not None:
        object_name = current.objectName()
        names.append(
            object_name
            or f"{current.__class__.__name__}:{normalize_identifier(current.windowTitle())}"
        )
        current = current.parentWidget()
    return "/".join(reversed(names))


def _parent_label(widget: QWidget | QAction) -> str:
    parent = widget.parent()
    if parent is None:
        return ""
    text = getattr(parent, "title", lambda: "")()
    if text:
        return str(text)
    object_name = getattr(parent, "objectName", lambda: "")()
    return str(object_name or parent.__class__.__name__)


def _action_text(action: QAction) -> str:
    return str(action.text() or action.toolTip() or action.statusTip() or "").replace("&", "")


def _widget_text(widget: QWidget) -> str:
    for attr in ("text", "title", "windowTitle", "placeholderText", "toolTip"):
        getter = getattr(widget, attr, None)
        if callable(getter):
            try:
                value = str(getter() or "").strip()
            except Exception:
                value = ""
            if value:
                return value.replace("&", "")
    return ""


def _add_item(
    items: list[UIInventoryItem],
    seen: set[str],
    *,
    kind: str,
    object_name: str,
    text: str,
    class_name: str,
    parent: str,
    path: str,
    visible: bool,
    enabled: bool,
    area_parts: tuple[object, ...],
) -> None:
    base = normalize_identifier(object_name or text or path, fallback=class_name.lower())
    inventory_id = f"{kind}:{base}"
    if inventory_id in seen:
        inventory_id = f"{inventory_id}:{len(seen) + 1}"
    seen.add(inventory_id)
    items.append(
        UIInventoryItem(
            inventory_id=inventory_id,
            kind=kind,
            ui_area=classify_ui_area(kind, object_name, text, parent, *area_parts),
            object_name=object_name,
            text=text,
            class_name=class_name,
            parent=parent,
            path=path,
            visible=bool(visible),
            enabled=bool(enabled),
            has_stable_object_name=bool(object_name),
        )
    )


def discover_ui_inventory(root: QWidget) -> list[UIInventoryItem]:
    """Discover user-facing Qt surfaces from a live application window."""

    items: list[UIInventoryItem] = []
    seen: set[str] = set()

    for action in root.findChildren(QAction):
        text = _action_text(action)
        if not text and not action.objectName():
            continue
        parent = _parent_label(action)
        _add_item(
            items,
            seen,
            kind="action",
            object_name=action.objectName(),
            text=text,
            class_name=action.__class__.__name__,
            parent=parent,
            path=f"{parent}/{action.objectName() or text}",
            visible=action.isVisible(),
            enabled=action.isEnabled(),
            area_parts=(action.toolTip(), action.statusTip()),
        )

    widget_types = (
        QMenu,
        QToolBar,
        QDockWidget,
        QDialog,
        QTabWidget,
        QAbstractItemView,
        QAbstractButton,
        QLineEdit,
        QComboBox,
        QTextEdit,
    )
    widgets: list[QWidget] = []
    seen_widgets: set[int] = set()
    for widget_type in widget_types:
        for widget in root.findChildren(widget_type):
            identity = id(widget)
            if identity in seen_widgets:
                continue
            seen_widgets.add(identity)
            widgets.append(widget)

    for widget in widgets:
        text = _widget_text(widget)
        object_name = widget.objectName()
        if (
            isinstance(widget, QAbstractItemView)
            and not object_name
            and not text
            and not widget.isVisible()
            and not widget.isEnabled()
        ):
            continue
        if not object_name and not text and not isinstance(widget, (QTabWidget, QAbstractItemView)):
            continue
        kind = widget.__class__.__name__
        if isinstance(widget, QMenu):
            kind = "menu"
        elif isinstance(widget, QToolBar):
            kind = "toolbar"
        elif isinstance(widget, QDockWidget):
            kind = "dock"
        elif isinstance(widget, QDialog):
            kind = "dialog"
        elif isinstance(widget, QTabWidget):
            kind = "tabs"
        elif isinstance(widget, QAbstractItemView):
            kind = "view"
        elif isinstance(widget, QAbstractButton):
            kind = "button"
        elif isinstance(widget, QLineEdit):
            kind = "field"
        elif isinstance(widget, QComboBox):
            kind = "field"
        elif isinstance(widget, QTextEdit):
            kind = "text_edit"
        _add_item(
            items,
            seen,
            kind=kind,
            object_name=object_name,
            text=text,
            class_name=widget.__class__.__name__,
            parent=_parent_label(widget),
            path=_widget_path(widget),
            visible=widget.isVisible(),
            enabled=widget.isEnabled(),
            area_parts=(widget.toolTip(),),
        )
        if isinstance(widget, QTabWidget):
            for index in range(widget.count()):
                tab_text = widget.tabText(index).replace("&", "")
                _add_item(
                    items,
                    seen,
                    kind="tab_page",
                    object_name=f"{object_name}_tab_{index}" if object_name else "",
                    text=tab_text,
                    class_name="QTabWidgetPage",
                    parent=object_name or widget.__class__.__name__,
                    path=f"{_widget_path(widget)}/tab:{index}:{tab_text}",
                    visible=widget.isVisible(),
                    enabled=widget.isTabEnabled(index),
                    area_parts=(tab_text,),
                )

    return sorted(items, key=lambda item: (item.ui_area, item.kind, item.inventory_id))


def write_inventory(path: Path, inventory: list[UIInventoryItem]) -> Path:
    payload: list[dict[str, Any]] = [asdict(item) for item in inventory]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path

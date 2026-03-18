"""Helpers for exposing live QSS selector targets inside the app."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from PySide6.QtWidgets import QWidget


@dataclass(frozen=True, slots=True)
class QssReferenceEntry:
    category: str
    selector: str
    details: str
    selector_kind: str = "static"
    widget_class: str | None = None
    object_name: str | None = None
    role_name: str | None = None


STATIC_QSS_REFERENCE_ENTRIES: tuple[QssReferenceEntry, ...] = (
    QssReferenceEntry(
        "Subcontrol",
        "QDockWidget::title",
        "Dock title bar area.",
        selector_kind="subcontrol_selector",
        widget_class="QDockWidget",
    ),
    QssReferenceEntry(
        "Subcontrol",
        "QHeaderView::section",
        "Table and tree header sections.",
        selector_kind="subcontrol_selector",
        widget_class="QHeaderView",
    ),
    QssReferenceEntry(
        "Subcontrol",
        "QMenu::item",
        "Individual menu rows.",
        selector_kind="subcontrol_selector",
        widget_class="QMenu",
    ),
    QssReferenceEntry(
        "Subcontrol",
        "QScrollBar::handle:vertical",
        "Vertical scrollbar handle.",
        selector_kind="subcontrol_selector",
        widget_class="QScrollBar",
    ),
    QssReferenceEntry(
        "Subcontrol",
        "QScrollBar::handle:horizontal",
        "Horizontal scrollbar handle.",
        selector_kind="subcontrol_selector",
        widget_class="QScrollBar",
    ),
    QssReferenceEntry(
        "Subcontrol",
        "QTabBar::tab",
        "Tabs inside tab widgets.",
        selector_kind="subcontrol_selector",
        widget_class="QTabBar",
    ),
    QssReferenceEntry(
        "Subcontrol",
        "QToolBar",
        "Toolbars such as the profile and action ribbon bars.",
        selector_kind="widget_type",
        widget_class="QToolBar",
    ),
    QssReferenceEntry(
        "Widget",
        "QDockWidget",
        "Dock roots, including floating catalog workspace panels.",
        selector_kind="widget_type",
        widget_class="QDockWidget",
    ),
    QssReferenceEntry(
        "Pseudo State",
        ":hover",
        "Hovered widget state.",
        selector_kind="pseudo_state",
    ),
    QssReferenceEntry(
        "Pseudo State",
        ":checked",
        "Checked state for buttons and actions.",
        selector_kind="pseudo_state",
    ),
    QssReferenceEntry(
        "Pseudo State",
        ":disabled",
        "Disabled widget state.",
        selector_kind="pseudo_state",
    ),
    QssReferenceEntry(
        "Example",
        "#mainWindow QTableWidget",
        "Tables inside the main window.",
        selector_kind="example",
    ),
    QssReferenceEntry(
        "Example",
        'QLabel[role="secondary"]',
        "Secondary helper and status text labels.",
        selector_kind="typed_role",
        widget_class="QLabel",
        role_name="secondary",
    ),
    QssReferenceEntry(
        "Example",
        '#releaseBrowserDock QWidget[role="workspaceCanvas"]',
        "Workspace canvas inside a floating or docked release browser.",
        selector_kind="example",
        object_name="releaseBrowserDock",
        role_name="workspaceCanvas",
    ),
)


def root_object_name(widget: QWidget) -> str:
    """Return a stable object name for a widget, creating one if needed."""
    name = (widget.objectName() or "").strip()
    if name:
        return name
    class_name = widget.metaObject().className() or "widget"
    base = class_name[0].lower() + class_name[1:] if class_name else "widget"
    widget.setObjectName(base)
    return base


def ensure_widget_object_names(root: QWidget | None) -> bool:
    """Assign stable object names to visible widget trees when missing."""
    if root is None:
        return False
    changed = False
    root_name = root_object_name(root)

    for attr_name, value in getattr(root, "__dict__", {}).items():
        if isinstance(value, QWidget) and value.objectName() == "":
            value.setObjectName(attr_name)
            changed = True

    counters: dict[str, int] = {}
    for child in root.findChildren(QWidget):
        if child.objectName():
            continue
        for attr_name, value in getattr(child, "__dict__", {}).items():
            if isinstance(value, QWidget) and value.objectName() == "":
                value.setObjectName(attr_name)
                changed = True
        if child.objectName():
            continue
        class_name = child.metaObject().className() or "widget"
        base = class_name[0].lower() + class_name[1:] if class_name else "widget"
        counters[base] = counters.get(base, 0) + 1
        child.setObjectName(f"{root_name}_{base}_{counters[base]}")
        changed = True
    return changed


def repolish_widget_tree(root: QWidget | None) -> None:
    """Re-apply styles after object names or selector-affecting properties change."""
    if root is None:
        return
    root.style().unpolish(root)
    root.style().polish(root)
    for child in root.findChildren(QWidget):
        child.style().unpolish(child)
        child.style().polish(child)


def _include_widget(widget: QWidget) -> bool:
    name = (widget.objectName() or "").strip()
    if name.startswith("qt_"):
        return False
    class_name = widget.metaObject().className() or ""
    if class_name.startswith("QTip"):
        return False
    return True


def collect_qss_reference_entries(widgets: Iterable[QWidget]) -> list[QssReferenceEntry]:
    """Build a searchable QSS selector catalog from the current widget tree."""
    entries: dict[tuple[str, str], QssReferenceEntry] = {}
    seen_widgets: set[int] = set()

    def add_entry(entry: QssReferenceEntry) -> None:
        clean_selector = str(entry.selector or "").strip()
        if not clean_selector:
            return
        key = (entry.category, clean_selector)
        current = entries.get(key)
        if current is None or len(entry.details) > len(current.details):
            entries[key] = entry

    for entry in STATIC_QSS_REFERENCE_ENTRIES:
        add_entry(entry)

    for root in widgets:
        if root is None:
            continue
        ensure_widget_object_names(root)
        for widget in [root, *root.findChildren(QWidget)]:
            widget_id = id(widget)
            if widget_id in seen_widgets or not _include_widget(widget):
                continue
            seen_widgets.add(widget_id)

            class_name = widget.metaObject().className() or "QWidget"
            object_name = (widget.objectName() or "").strip()
            role_name = str(widget.property("role") or "").strip()

            add_entry(
                QssReferenceEntry(
                    "Widget Type",
                    class_name,
                    f"Target all visible {class_name} controls.",
                    selector_kind="widget_type",
                    widget_class=class_name,
                )
            )
            if object_name:
                add_entry(
                    QssReferenceEntry(
                        "Object Name",
                        f"#{object_name}",
                        f"{class_name} named '{object_name}'.",
                        selector_kind="object_name",
                        widget_class=class_name,
                        object_name=object_name,
                    )
                )
                add_entry(
                    QssReferenceEntry(
                        "Typed Object",
                        f"{class_name}#{object_name}",
                        f"The {class_name} instance named '{object_name}'.",
                        selector_kind="typed_object",
                        widget_class=class_name,
                        object_name=object_name,
                    )
                )
            if role_name:
                add_entry(
                    QssReferenceEntry(
                        "Role Property",
                        f'[role="{role_name}"]',
                        f"Any widget tagged with role='{role_name}'.",
                        selector_kind="role_property",
                        role_name=role_name,
                    )
                )
                add_entry(
                    QssReferenceEntry(
                        "Typed Role",
                        f'{class_name}[role="{role_name}"]',
                        f"{class_name} widgets tagged with role='{role_name}'.",
                        selector_kind="typed_role",
                        widget_class=class_name,
                        role_name=role_name,
                    )
                )

    return sorted(entries.values(), key=lambda entry: (entry.category, entry.selector.lower()))


def build_qss_completion_tokens(entries: Iterable[QssReferenceEntry]) -> list[str]:
    """Return a compatibility token list for simple selector completion."""
    tokens = {entry.selector for entry in entries if entry.selector}
    tokens.update({":checked", ":disabled", ":hover"})
    return sorted(tokens, key=str.lower)

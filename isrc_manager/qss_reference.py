"""Helpers for exposing QSS selector targets inside the app."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from PySide6.QtCore import QStringListModel, Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QCompleter, QPlainTextEdit, QWidget


@dataclass(frozen=True, slots=True)
class QssReferenceEntry:
    category: str
    selector: str
    details: str


STATIC_QSS_REFERENCE_ENTRIES: tuple[QssReferenceEntry, ...] = (
    QssReferenceEntry("Subcontrol", "QDockWidget::title", "Dock title bar area."),
    QssReferenceEntry("Subcontrol", "QHeaderView::section", "Table and tree header sections."),
    QssReferenceEntry("Subcontrol", "QMenu::item", "Individual menu rows."),
    QssReferenceEntry("Subcontrol", "QScrollBar:vertical", "Vertical scrollbars."),
    QssReferenceEntry("Subcontrol", "QScrollBar:horizontal", "Horizontal scrollbars."),
    QssReferenceEntry("Subcontrol", "QTabBar::tab", "Tabs inside tab widgets."),
    QssReferenceEntry(
        "Subcontrol", "QToolBar", "Toolbars such as the profile and action ribbon bars."
    ),
    QssReferenceEntry("Pseudo State", ":hover", "Hovered widget state."),
    QssReferenceEntry("Pseudo State", ":checked", "Checked state for buttons and actions."),
    QssReferenceEntry("Pseudo State", ":disabled", "Disabled widget state."),
    QssReferenceEntry("Example", "#mainWindow QTableWidget", "Tables inside the main window."),
    QssReferenceEntry(
        "Example",
        'QLabel[role="secondary"]',
        "Secondary helper and status text labels.",
    ),
)


def _root_object_name(widget: QWidget) -> str:
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
    root_name = _root_object_name(root)

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

    def add_entry(category: str, selector: str, details: str) -> None:
        clean_selector = str(selector or "").strip()
        if not clean_selector:
            return
        key = (category, clean_selector)
        current = entries.get(key)
        if current is None or len(details) > len(current.details):
            entries[key] = QssReferenceEntry(category, clean_selector, details)

    for entry in STATIC_QSS_REFERENCE_ENTRIES:
        add_entry(entry.category, entry.selector, entry.details)

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

            add_entry("Widget Type", class_name, f"Target all visible {class_name} controls.")
            if object_name:
                add_entry("Object Name", f"#{object_name}", f"{class_name} named '{object_name}'.")
                add_entry(
                    "Typed Object",
                    f"{class_name}#{object_name}",
                    f"The {class_name} instance named '{object_name}'.",
                )
            if role_name:
                add_entry(
                    "Role Property",
                    f'[role="{role_name}"]',
                    f"Any widget tagged with role='{role_name}'.",
                )
                add_entry(
                    "Typed Role",
                    f'{class_name}[role="{role_name}"]',
                    f"{class_name} widgets tagged with role='{role_name}'.",
                )

    return sorted(entries.values(), key=lambda entry: (entry.category, entry.selector.lower()))


def build_qss_completion_tokens(entries: Iterable[QssReferenceEntry]) -> list[str]:
    """Return a sorted completion token list for the in-app QSS editor."""
    tokens = {
        entry.selector for entry in entries if entry.selector and not entry.selector.startswith(":")
    }
    tokens.update(
        {
            "{",
            "}",
            ":checked",
            ":disabled",
            ":hover",
            "QDockWidget::title",
            "QHeaderView::section",
            "QMenu::item",
            "QScrollBar:horizontal",
            "QScrollBar:vertical",
            "QTabBar::tab",
        }
    )
    return sorted(tokens, key=str.lower)


class QssCodeEditor(QPlainTextEdit):
    """QSS editor with lightweight selector autocomplete."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._completion_tokens: list[str] = []
        self._completer = QCompleter(self)
        self._completer.setWidget(self)
        self._completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._completer.setCompletionMode(QCompleter.PopupCompletion)
        self._completer.activated.connect(self._insert_completion)
        self._completer.setModel(QStringListModel([], self._completer))

    def set_completion_tokens(self, tokens: Iterable[str]) -> None:
        self._completion_tokens = sorted(
            {str(token).strip() for token in tokens if str(token).strip()}
        )
        model = self._completer.model()
        if isinstance(model, QStringListModel):
            model.setStringList(self._completion_tokens)

    def insertPlainText(self, text: str) -> None:  # noqa: N802 - Qt API name
        super().insertPlainText(text)

    def _completion_prefix(self) -> str:
        cursor = self.textCursor()
        block_text = cursor.block().text()
        end = cursor.positionInBlock()
        start = end
        while start > 0 and block_text[start - 1] not in " \t\r\n{}();,":
            start -= 1
        return block_text[start:end]

    def _insert_completion(self, completion: str) -> None:
        prefix = self._completion_prefix()
        if completion == prefix:
            return
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.Left, QTextCursor.KeepAnchor, len(prefix))
        cursor.insertText(completion)
        self.setTextCursor(cursor)

    def _show_completion_popup(self, prefix: str) -> None:
        if not prefix:
            self._completer.popup().hide()
            return
        self._completer.setCompletionPrefix(prefix)
        popup = self._completer.popup()
        popup.setCurrentIndex(self._completer.completionModel().index(0, 0))
        rect = self.cursorRect()
        rect.setWidth(max(320, popup.sizeHintForColumn(0) + 24))
        self._completer.complete(rect)

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt API name
        if self._completer.popup().isVisible() and event.key() in (
            Qt.Key_Enter,
            Qt.Key_Return,
            Qt.Key_Escape,
            Qt.Key_Tab,
            Qt.Key_Backtab,
        ):
            event.ignore()
            return

        ctrl_space = bool(event.modifiers() & Qt.ControlModifier and event.key() == Qt.Key_Space)
        super().keyPressEvent(event)

        prefix = self._completion_prefix()
        if ctrl_space:
            self._show_completion_popup(prefix)
            return
        if event.text().strip() and len(prefix) >= 2:
            self._show_completion_popup(prefix)
        elif self._completer.popup().isVisible():
            self._completer.popup().hide()

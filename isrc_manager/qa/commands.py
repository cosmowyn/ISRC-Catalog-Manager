"""Small deterministic UI command helpers for PQ tests."""

from __future__ import annotations

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QAbstractItemView, QMainWindow, QTableWidget


def action_label(action: QAction) -> str:
    return str(action.text() or action.objectName() or "").replace("&", "").strip()


def find_action(window: QMainWindow, label_or_object_name: str) -> QAction | None:
    needle = str(label_or_object_name or "").replace("&", "").strip().lower()
    for action in window.findChildren(QAction):
        labels = {
            action.objectName().strip().lower(),
            action_label(action).lower(),
            str(action.toolTip() or "").strip().lower(),
        }
        if needle in labels:
            return action
    return None


def safe_trigger_action(window: QMainWindow, label_or_object_name: str) -> bool:
    action = find_action(window, label_or_object_name)
    if action is None or not action.isEnabled() or not action.isVisible():
        return False
    action.trigger()
    return True


def table_contains_text(table: QAbstractItemView | QTableWidget, text: str) -> bool:
    needle = str(text)
    row_count = getattr(table, "rowCount", None)
    column_count = getattr(table, "columnCount", None)
    item_getter = getattr(table, "item", None)
    if callable(row_count) and callable(column_count) and callable(item_getter):
        for row in range(row_count()):
            for column in range(column_count()):
                item = item_getter(row, column)
                if item is not None and needle in item.text():
                    return True
        return False

    model = table.model()
    if model is None:
        return False
    for row in range(model.rowCount()):
        for column in range(model.columnCount()):
            value = model.data(model.index(row, column))
            if value is not None and needle in str(value):
                return True
    return False

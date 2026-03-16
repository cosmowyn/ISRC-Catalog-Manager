"""Dialogs for audio tag preview and conflict resolution."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

TAG_POLICY_CHOICES = (
    ("merge_blanks", "Merge blanks only"),
    ("prefer_file_tags", "Prefer file tags"),
    ("prefer_database", "Prefer database values"),
)


class TagPreviewDialog(QDialog):
    """Preview tag mapping conflicts before import or export."""

    def __init__(
        self,
        *,
        title: str,
        intro: str,
        rows: list[dict[str, object]],
        initial_policy: str = "merge_blanks",
        allow_policy_change: bool = True,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(980, 640)
        self._rows = rows

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        intro_label = QLabel(intro)
        intro_label.setWordWrap(True)
        root.addWidget(intro_label)

        policy_row = QHBoxLayout()
        policy_row.setContentsMargins(0, 0, 0, 0)
        policy_row.setSpacing(8)
        policy_row.addWidget(QLabel("Conflict policy"))
        self.policy_combo = QComboBox()
        for key, label in TAG_POLICY_CHOICES:
            self.policy_combo.addItem(label, key)
        index = self.policy_combo.findData(initial_policy)
        self.policy_combo.setCurrentIndex(index if index >= 0 else 0)
        self.policy_combo.setEnabled(allow_policy_change)
        policy_row.addWidget(self.policy_combo)
        policy_row.addStretch(1)
        root.addLayout(policy_row)

        self.table = QTableWidget(0, 6, self)
        self.table.setHorizontalHeaderLabels(
            ["Track", "Field", "Database", "File Tags", "Chosen", "Source File"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        root.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        confirm = QPushButton("Continue")
        confirm.setDefault(True)
        confirm.clicked.connect(self.accept)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(confirm)
        buttons.addWidget(cancel)
        root.addLayout(buttons)

        self.populate_rows(rows)

    def populate_rows(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows
        self.table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = [
                str(row.get("track") or ""),
                str(row.get("field") or ""),
                str(row.get("database") or ""),
                str(row.get("file") or ""),
                str(row.get("chosen") or ""),
                str(row.get("source") or ""),
            ]
            for column, value in enumerate(values):
                self.table.setItem(row_index, column, QTableWidgetItem(value))

    def selected_policy(self) -> str:
        return str(self.policy_combo.currentData() or "merge_blanks")

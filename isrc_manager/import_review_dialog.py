"""Shared import review dialog shown before write imports are applied."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from isrc_manager.ui_common import (
    _add_standard_dialog_header,
    _apply_compact_dialog_control_heights,
    _apply_standard_dialog_chrome,
)


class ImportReviewDialog(QDialog):
    """Review dry-run or inspection results before applying an import."""

    def __init__(
        self,
        *,
        title: str,
        subtitle: str,
        summary_lines: list[str],
        warnings: list[str] | None = None,
        preview_title: str = "Preview",
        preview_rows: list[dict[str, object]] | None = None,
        preview_headers: list[str] | None = None,
        confirm_label: str = "Apply Import",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(960, 700)
        _apply_standard_dialog_chrome(self, "importReviewDialog")

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)
        _add_standard_dialog_header(root, self, title=title, subtitle=subtitle)

        tabs = QTabWidget(self)
        tabs.setObjectName("importReviewTabs")
        tabs.setDocumentMode(True)
        root.addWidget(tabs, 1)

        summary_page = QWidget(tabs)
        summary_page.setProperty("role", "workspaceCanvas")
        summary_layout = QVBoxLayout(summary_page)
        summary_layout.setContentsMargins(0, 0, 0, 0)
        summary_layout.setSpacing(12)
        tabs.addTab(summary_page, "Review")

        summary_label = QLabel("\n".join(str(line) for line in summary_lines if str(line).strip()))
        summary_label.setWordWrap(True)
        summary_layout.addWidget(summary_label)

        warning_lines = [str(item).strip() for item in list(warnings or []) if str(item).strip()]
        if warning_lines:
            warning_label = QLabel("Warnings")
            warning_label.setProperty("role", "secondary")
            summary_layout.addWidget(warning_label)

            warning_table = QTableWidget(len(warning_lines), 1, self)
            warning_table.setHorizontalHeaderLabels(["Warning"])
            warning_table.verticalHeader().setVisible(False)
            warning_table.horizontalHeader().setStretchLastSection(True)
            warning_table.setEditTriggers(QTableWidget.NoEditTriggers)
            for row_index, value in enumerate(warning_lines):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                warning_table.setItem(row_index, 0, item)
            summary_layout.addWidget(warning_table, 1)
        else:
            summary_layout.addStretch(1)

        normalized_preview_rows = list(preview_rows or [])
        normalized_headers = list(preview_headers or [])
        if normalized_preview_rows:
            if not normalized_headers:
                seen_headers: set[str] = set()
                for row in normalized_preview_rows:
                    for key in row.keys():
                        name = str(key)
                        if name not in seen_headers:
                            normalized_headers.append(name)
                            seen_headers.add(name)

            preview_page = QWidget(tabs)
            preview_page.setProperty("role", "workspaceCanvas")
            preview_layout = QVBoxLayout(preview_page)
            preview_layout.setContentsMargins(0, 0, 0, 0)
            preview_layout.setSpacing(12)
            tabs.addTab(preview_page, preview_title)

            preview_table = QTableWidget(
                len(normalized_preview_rows), len(normalized_headers), self
            )
            preview_table.setHorizontalHeaderLabels(normalized_headers)
            preview_table.verticalHeader().setVisible(False)
            preview_table.horizontalHeader().setStretchLastSection(True)
            preview_table.setEditTriggers(QTableWidget.NoEditTriggers)
            for row_index, row in enumerate(normalized_preview_rows):
                for column_index, header in enumerate(normalized_headers):
                    preview_table.setItem(
                        row_index,
                        column_index,
                        QTableWidgetItem("" if row.get(header) is None else str(row.get(header))),
                    )
            preview_layout.addWidget(preview_table, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        confirm = QPushButton(confirm_label, self)
        confirm.setDefault(True)
        confirm.clicked.connect(self.accept)
        cancel = QPushButton("Cancel", self)
        cancel.clicked.connect(self.reject)
        buttons.addWidget(confirm)
        buttons.addWidget(cancel)
        root.addLayout(buttons)
        _apply_compact_dialog_control_heights(self)

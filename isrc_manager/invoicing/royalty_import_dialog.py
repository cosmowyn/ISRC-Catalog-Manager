"""Royalty source import preview and mapping dialog."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from isrc_manager.ui_common import (
    _add_standard_dialog_header,
    _apply_compact_dialog_control_heights,
    _apply_standard_dialog_chrome,
)

from .royalty_import import (
    ROYALTY_IMPORT_SKIP_TARGET,
    ROYALTY_SOURCE_IMPORT_TARGETS,
    RoyaltySourceImportInspection,
    RoyaltySourceImportReport,
)


def _configure_import_table(table: QTableWidget) -> None:
    table.setAlternatingRowColors(True)
    table.setWordWrap(False)
    table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    table.setHorizontalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
    table.setVerticalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setStretchLastSection(False)
    table.resizeColumnsToContents()


class RoyaltySourceImportDialog(QDialog):
    """Preview source columns, map them, omit fields, and inspect resolved rows."""

    def __init__(
        self,
        *,
        inspection: RoyaltySourceImportInspection,
        preview_callback: Callable[[dict[str, str]], RoyaltySourceImportReport],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.inspection = inspection
        self._preview_callback = preview_callback
        self._current_report: RoyaltySourceImportReport | None = None
        self.setWindowTitle(f"Import Royalty Source Events from {inspection.format_name.upper()}")
        self.resize(1120, 740)
        _apply_standard_dialog_chrome(self, "royaltySourceImportDialog")

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)
        _add_standard_dialog_header(
            root,
            self,
            title=self.windowTitle(),
            subtitle=(
                "Review DSP statement fields, map source columns to royalty source-event fields, "
                "or explicitly omit columns before importing."
            ),
        )

        self.content_tabs = QTabWidget(self)
        self.content_tabs.setObjectName("royaltySourceImportTabs")
        self.content_tabs.setDocumentMode(True)
        root.addWidget(self.content_tabs, 1)

        mapping_page = QWidget(self.content_tabs)
        mapping_page.setProperty("role", "workspaceCanvas")
        mapping_layout = QVBoxLayout(mapping_page)
        mapping_layout.setContentsMargins(0, 0, 0, 0)
        mapping_layout.setSpacing(12)
        self.content_tabs.addTab(mapping_page, "Setup & Mapping")

        source_page = QWidget(self.content_tabs)
        source_page.setProperty("role", "workspaceCanvas")
        source_layout = QVBoxLayout(source_page)
        source_layout.setContentsMargins(0, 0, 0, 0)
        source_layout.setSpacing(12)
        self.content_tabs.addTab(source_page, "Source Preview")

        resolved_page = QWidget(self.content_tabs)
        resolved_page.setProperty("role", "workspaceCanvas")
        resolved_layout = QVBoxLayout(resolved_page)
        resolved_layout.setContentsMargins(0, 0, 0, 0)
        resolved_layout.setSpacing(12)
        self.content_tabs.addTab(resolved_page, "Resolved Preview")

        meta = QLabel(
            f"Source: {inspection.file_path} | Rows detected: {inspection.total_rows}", self
        )
        meta.setWordWrap(True)
        mapping_layout.addWidget(meta)
        self.warning_label = QLabel(self)
        self.warning_label.setWordWrap(True)
        if inspection.warnings:
            self.warning_label.setText("Warnings: " + " | ".join(inspection.warnings))
            mapping_layout.addWidget(self.warning_label)

        self.mapping_table = QTableWidget(0, 2, self)
        self.mapping_table.setHorizontalHeaderLabels(("Source field", "Map to"))
        _configure_import_table(self.mapping_table)
        mapping_layout.addWidget(self.mapping_table, 1)

        self.source_table = QTableWidget(0, len(inspection.headers), self)
        self.source_table.setHorizontalHeaderLabels(inspection.headers)
        self.source_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        _configure_import_table(self.source_table)
        source_layout.addWidget(self.source_table, 1)

        self.summary_label = QLabel(self)
        self.summary_label.setWordWrap(True)
        resolved_layout.addWidget(self.summary_label)
        self.resolved_table = QTableWidget(0, 0, self)
        self.resolved_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        _configure_import_table(self.resolved_table)
        resolved_layout.addWidget(self.resolved_table, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        refresh = QPushButton("Refresh Preview", self)
        refresh.clicked.connect(self.refresh_resolved_preview)
        buttons.addWidget(refresh)
        self.import_button = QPushButton("Import Source Events", self)
        self.import_button.setDefault(True)
        self.import_button.clicked.connect(self.accept)
        buttons.addWidget(self.import_button)
        cancel = QPushButton("Cancel", self)
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        root.addLayout(buttons)

        self._populate_mapping_table()
        self._populate_source_table()
        self.refresh_resolved_preview()
        _apply_compact_dialog_control_heights(self)

    def mapping(self) -> dict[str, str]:
        mapped: dict[str, str] = {}
        for row in range(self.mapping_table.rowCount()):
            source_item = self.mapping_table.item(row, 0)
            combo = self.mapping_table.cellWidget(row, 1)
            if source_item is None or combo is None:
                continue
            target = str(combo.currentData() or "").strip()
            if target and target != ROYALTY_IMPORT_SKIP_TARGET:
                mapped[source_item.text()] = target
        return mapped

    def refresh_resolved_preview(self) -> None:
        self._current_report = self._preview_callback(self.mapping())
        self.summary_label.setText(" | ".join(self._current_report.summary_lines))
        preview_dicts = [row.to_preview_dict() for row in self._current_report.preview_rows[:200]]
        headers = list(preview_dicts[0].keys()) if preview_dicts else []
        self.resolved_table.clearContents()
        self.resolved_table.setColumnCount(len(headers))
        self.resolved_table.setHorizontalHeaderLabels(headers)
        self.resolved_table.setRowCount(len(preview_dicts))
        for row_index, row in enumerate(preview_dicts):
            for col_index, header in enumerate(headers):
                item = QTableWidgetItem(str(row.get(header, "")))
                if header == "Issues" and row.get(header):
                    item.setToolTip(str(row.get(header)))
                self.resolved_table.setItem(row_index, col_index, item)
        self.resolved_table.resizeColumnsToContents()
        self.import_button.setEnabled(self._current_report.passed > 0)

    def _populate_mapping_table(self) -> None:
        self.mapping_table.setRowCount(len(self.inspection.headers))
        for row, header in enumerate(self.inspection.headers):
            self.mapping_table.setItem(row, 0, QTableWidgetItem(header))
            combo = QComboBox(self.mapping_table)
            combo.addItem("", "")
            combo.addItem("Omit this field", ROYALTY_IMPORT_SKIP_TARGET)
            for label, target in ROYALTY_SOURCE_IMPORT_TARGETS:
                combo.addItem(label, target)
            suggested = self.inspection.suggested_mapping.get(header, "")
            index = combo.findData(suggested)
            combo.setCurrentIndex(index if index >= 0 else 0)
            combo.currentIndexChanged.connect(lambda *_args: self.refresh_resolved_preview())
            self.mapping_table.setCellWidget(row, 1, combo)
        self.mapping_table.resizeColumnsToContents()

    def _populate_source_table(self) -> None:
        rows = self.inspection.preview_rows
        self.source_table.clearContents()
        self.source_table.setColumnCount(len(self.inspection.headers))
        self.source_table.setHorizontalHeaderLabels(self.inspection.headers)
        self.source_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for col_index, header in enumerate(self.inspection.headers):
                self.source_table.setItem(
                    row_index,
                    col_index,
                    QTableWidgetItem("" if row.get(header) is None else str(row.get(header))),
                )
        self.source_table.resizeColumnsToContents()

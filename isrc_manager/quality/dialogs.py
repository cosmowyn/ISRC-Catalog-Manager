"""Quality dashboard dialog."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListView,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from .models import QualityIssue, QualityScanResult


def _create_filter_combo(parent=None, *, minimum_contents_length: int = 14) -> QComboBox:
    combo = QComboBox(parent)
    combo.setView(QListView(combo))
    combo.setMinimumContentsLength(max(8, int(minimum_contents_length)))
    combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    combo.setMaxVisibleItems(18)
    popup = combo.view()
    if isinstance(popup, QListView):
        popup.setUniformItemSizes(True)
        popup.setSpacing(0)
    return combo


class QualityDashboardDialog(QDialog):
    """Actionable quality scan dashboard."""

    def __init__(
        self,
        *,
        service,
        scan_callback=None,
        task_manager=None,
        release_choices_provider,
        apply_fix_callback,
        open_issue_callback,
        parent=None,
    ):
        super().__init__(parent)
        self.service = service
        self.scan_callback = scan_callback or service.scan
        self.task_manager = task_manager
        self.release_choices_provider = release_choices_provider
        self.apply_fix_callback = apply_fix_callback
        self.open_issue_callback = open_issue_callback
        self._scan_result = QualityScanResult(issues=[])
        self._active_scan_task_id: str | None = None

        self.setWindowTitle("Data Quality Dashboard")
        self.resize(1180, 780)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        header = QLabel(
            "Scan the current profile for metadata, release, media, ordering, and integrity issues."
        )
        header.setWordWrap(True)
        root.addWidget(header)

        stats_grid = QGridLayout()
        stats_grid.setHorizontalSpacing(12)
        stats_grid.setVerticalSpacing(8)
        self.total_label = QLabel("Total issues: 0")
        self.error_label = QLabel("Errors: 0")
        self.warning_label = QLabel("Warnings: 0")
        self.info_label = QLabel("Info: 0")
        stats_grid.addWidget(self.total_label, 0, 0)
        stats_grid.addWidget(self.error_label, 0, 1)
        stats_grid.addWidget(self.warning_label, 0, 2)
        stats_grid.addWidget(self.info_label, 0, 3)
        root.addLayout(stats_grid)

        filter_row = QHBoxLayout()
        filter_row.setContentsMargins(0, 0, 0, 0)
        filter_row.setSpacing(8)
        self.severity_combo = _create_filter_combo(self, minimum_contents_length=13)
        self.severity_combo.addItems(["All severities", "error", "warning", "info"])
        self.severity_combo.currentIndexChanged.connect(self._populate_issue_table)
        filter_row.addWidget(self.severity_combo)
        self.issue_type_combo = _create_filter_combo(self, minimum_contents_length=15)
        self.issue_type_combo.addItem("All issue types", "")
        self.issue_type_combo.currentIndexChanged.connect(self._populate_issue_table)
        filter_row.addWidget(self.issue_type_combo)
        self.entity_combo = _create_filter_combo(self, minimum_contents_length=11)
        self.entity_combo.addItem("All entities", "")
        self.entity_combo.addItems(["track", "release", "license"])
        self.entity_combo.currentIndexChanged.connect(self._populate_issue_table)
        filter_row.addWidget(self.entity_combo)
        self.release_combo = _create_filter_combo(self, minimum_contents_length=13)
        self.release_combo.addItem("All releases", 0)
        self.release_combo.currentIndexChanged.connect(self._populate_issue_table)
        filter_row.addWidget(self.release_combo)
        filter_row.addStretch(1)
        self.refresh_button = QPushButton("Refresh Scan")
        self.refresh_button.clicked.connect(self.refresh_scan)
        filter_row.addWidget(self.refresh_button)
        root.addLayout(filter_row)

        self.issue_table = QTableWidget(0, 7, self)
        self.issue_table.setHorizontalHeaderLabels(
            ["Severity", "Type", "Title", "Entity", "Entity ID", "Release ID", "Fix"]
        )
        self.issue_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.issue_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.issue_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.issue_table.verticalHeader().setVisible(False)
        self.issue_table.horizontalHeader().setStretchLastSection(True)
        self.issue_table.itemSelectionChanged.connect(self._load_issue_details)
        root.addWidget(self.issue_table, 1)

        self.details = QPlainTextEdit(self)
        self.details.setReadOnly(True)
        self.details.setMinimumHeight(140)
        root.addWidget(self.details)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)
        self.open_button = QPushButton("Open Record")
        self.open_button.clicked.connect(self._open_selected_issue)
        actions.addWidget(self.open_button)
        self.fix_button = QPushButton("Apply Suggested Fix")
        self.fix_button.clicked.connect(self._apply_selected_fix)
        actions.addWidget(self.fix_button)
        actions.addStretch(1)
        export_csv_button = QPushButton("Export CSV…")
        export_csv_button.clicked.connect(self._export_csv)
        actions.addWidget(export_csv_button)
        export_json_button = QPushButton("Export JSON…")
        export_json_button.clicked.connect(self._export_json)
        actions.addWidget(export_json_button)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        actions.addWidget(close_button)
        root.addLayout(actions)

        self.refresh_scan()

    def refresh_scan(self) -> None:
        if self._active_scan_task_id is not None:
            return
        self.refresh_button.setEnabled(False)
        self.details.setPlainText("Scanning the current profile...")
        self.issue_table.setRowCount(0)
        if self.task_manager is None:
            try:
                self._finish_scan(self.scan_callback())
            except Exception as exc:  # pragma: no cover - defensive UI path
                self._fail_scan(str(exc))
            finally:
                self.refresh_button.setEnabled(True)
            return

        self._active_scan_task_id = self.task_manager.submit(
            title="Data Quality Scan",
            description="Scanning the current profile for data-quality issues...",
            task_fn=lambda _ctx: self.scan_callback(),
            kind="read",
            unique_key="quality.dashboard.scan",
            owner=self,
            show_dialog=False,
            cancellable=False,
            on_success=self._finish_scan,
            on_error=lambda failure: self._fail_scan(getattr(failure, "message", str(failure))),
            on_finished=self._finish_scan_request,
        )
        if self._active_scan_task_id is None:
            self.refresh_button.setEnabled(True)
            self.details.setPlainText("A quality scan is already running.")

    def _finish_scan_request(self) -> None:
        self._active_scan_task_id = None
        self.refresh_button.setEnabled(True)

    def _finish_scan(self, result: QualityScanResult) -> None:
        self._scan_result = result
        self.total_label.setText(f"Total issues: {len(result.issues)}")
        self.error_label.setText(f"Errors: {result.counts_by_severity.get('error', 0)}")
        self.warning_label.setText(f"Warnings: {result.counts_by_severity.get('warning', 0)}")
        self.info_label.setText(f"Info: {result.counts_by_severity.get('info', 0)}")
        self.issue_type_combo.blockSignals(True)
        current_type = self.issue_type_combo.currentData()
        self.issue_type_combo.clear()
        self.issue_type_combo.addItem("All issue types", "")
        for issue_type in sorted(result.counts_by_type):
            self.issue_type_combo.addItem(issue_type.replace("_", " "), issue_type)
        restore_index = self.issue_type_combo.findData(current_type)
        self.issue_type_combo.setCurrentIndex(restore_index if restore_index >= 0 else 0)
        self.issue_type_combo.blockSignals(False)

        self.release_combo.blockSignals(True)
        current_release = self.release_combo.currentData()
        self.release_combo.clear()
        self.release_combo.addItem("All releases", 0)
        for release_id, label in self.release_choices_provider():
            self.release_combo.addItem(label, int(release_id))
        restore_release = self.release_combo.findData(current_release)
        self.release_combo.setCurrentIndex(restore_release if restore_release >= 0 else 0)
        self.release_combo.blockSignals(False)
        self._populate_issue_table()

    def _fail_scan(self, message: str) -> None:
        self.details.setPlainText(message)
        QMessageBox.critical(self, "Quality Scan", f"Could not complete the scan:\n{message}")

    def _filtered_issues(self) -> list[QualityIssue]:
        severity = self.severity_combo.currentText()
        issue_type = self.issue_type_combo.currentData()
        entity = self.entity_combo.currentData()
        release_id = int(self.release_combo.currentData() or 0)
        filtered = []
        for issue in self._scan_result.issues:
            if severity != "All severities" and issue.severity != severity:
                continue
            if issue_type and issue.issue_type != issue_type:
                continue
            if entity and issue.entity_type != entity:
                continue
            if release_id > 0 and int(issue.release_id or 0) != release_id:
                continue
            filtered.append(issue)
        return filtered

    def _populate_issue_table(self) -> None:
        issues = self._filtered_issues()
        self.issue_table.setRowCount(len(issues))
        for row, issue in enumerate(issues):
            values = [
                issue.severity,
                issue.issue_type,
                issue.title,
                issue.entity_type,
                str(issue.entity_id or ""),
                str(issue.release_id or ""),
                issue.fix_key or "",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, issue)
                self.issue_table.setItem(row, column, item)
        if issues:
            self.issue_table.selectRow(0)
        else:
            self.details.clear()

    def _selected_issue(self) -> QualityIssue | None:
        row = self.issue_table.currentRow()
        if row < 0:
            return None
        item = self.issue_table.item(row, 0)
        if item is None:
            return None
        issue = item.data(Qt.UserRole)
        return issue if isinstance(issue, QualityIssue) else None

    def _load_issue_details(self) -> None:
        issue = self._selected_issue()
        if issue is None:
            self.details.clear()
            return
        self.details.setPlainText(
            "\n".join(
                [
                    f"Rule: {issue.title}",
                    f"Severity: {issue.severity}",
                    f"Type: {issue.issue_type}",
                    f"Entity: {issue.entity_type} #{issue.entity_id or ''}",
                    f"Release ID: {issue.release_id or ''}",
                    "",
                    issue.details,
                ]
            )
        )
        self.fix_button.setEnabled(bool(issue.fix_key))

    def _open_selected_issue(self) -> None:
        issue = self._selected_issue()
        if issue is None:
            return
        self.open_issue_callback(issue)

    def _apply_selected_fix(self) -> None:
        issue = self._selected_issue()
        if issue is None or not issue.fix_key:
            return
        try:
            message = self.apply_fix_callback(issue.fix_key)
        except Exception as exc:
            QMessageBox.critical(self, "Quality Fix", f"Could not apply the suggested fix:\n{exc}")
            return
        QMessageBox.information(self, "Quality Fix", message)
        self.refresh_scan()

    def _export_csv(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export Quality Report to CSV", "quality-report.csv", "CSV (*.csv)")
        if not path:
            return
        self.service.export_csv(
            QualityScanResult(
                issues=self._filtered_issues(),
                counts_by_severity=self._scan_result.counts_by_severity,
                counts_by_type=self._scan_result.counts_by_type,
            ),
            path,
        )

    def _export_json(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Quality Report to JSON",
            "quality-report.json",
            "JSON (*.json)",
        )
        if not path:
            return
        self.service.export_json(
            QualityScanResult(
                issues=self._filtered_issues(),
                counts_by_severity=self._scan_result.counts_by_severity,
                counts_by_type=self._scan_result.counts_by_type,
            ),
            path,
        )

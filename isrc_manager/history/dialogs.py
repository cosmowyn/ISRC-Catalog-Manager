"""History and snapshot UI."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
)


class HistoryDialog(QDialog):
    """Simple history and snapshot browser."""

    def __init__(self, app, parent=None):
        super().__init__(parent or app)
        self.app = app
        self.setObjectName("historyDialog")
        self.setWindowTitle("Undo History")
        self.resize(1040, 720)
        self.setMinimumSize(940, 640)
        self.setStyleSheet(
            """
            QDialog#historyDialog QLabel[role="dialogTitle"] {
                font-size: 26px;
                font-weight: 700;
            }
            QDialog#historyDialog QLabel[role="dialogSubtitle"] {
                color: #64748b;
                font-size: 15px;
            }
            QDialog#historyDialog QLabel[role="supportingText"] {
                color: #52606d;
            }
            QDialog#historyDialog QGroupBox {
                font-size: 15px;
                font-weight: 600;
                margin-top: 10px;
            }
            QDialog#historyDialog QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 6px;
            }
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        header_row = QHBoxLayout()
        title_label = QLabel("History & Snapshots", self)
        title_label.setProperty("role", "dialogTitle")
        header_row.addWidget(title_label)
        header_row.addStretch(1)
        self.help_btn = QToolButton(self)
        self.help_btn.setText("?")
        self.help_btn.setFixedSize(28, 28)
        self.help_btn.setProperty("role", "helpButton")
        self.help_btn.setToolTip("Open help for history and snapshots")
        self.help_btn.clicked.connect(
            lambda: self.app.open_help_dialog(topic_id="history", parent=self)
        )
        header_row.addWidget(self.help_btn)
        layout.addLayout(header_row)

        subtitle_label = QLabel(
            "Review recent user actions, undo or redo meaningful changes, and manage database snapshots from one place.",
            self,
        )
        subtitle_label.setProperty("role", "dialogSubtitle")
        subtitle_label.setWordWrap(True)
        layout.addWidget(subtitle_label)

        self.tabs = QTabWidget()
        browser_box = QGroupBox("History Browser", self)
        browser_layout = QVBoxLayout(browser_box)
        browser_layout.setContentsMargins(14, 18, 14, 14)
        browser_layout.setSpacing(10)
        browser_help = QLabel(
            "The Session and History tabs show meaningful user actions. Internal sync and bookkeeping steps are hidden automatically.",
            browser_box,
        )
        browser_help.setProperty("role", "supportingText")
        browser_help.setWordWrap(True)
        browser_layout.addWidget(browser_help)
        browser_layout.addWidget(self.tabs, 1)
        layout.addWidget(browser_box, 1)

        self.session_table = self._build_table(["Current", "Time", "Action", "Type"])
        self.tabs.addTab(self.session_table, "Session")

        self.history_table = self._build_table(["Current", "Time", "Action", "Type"])
        self.tabs.addTab(self.history_table, "History")

        self.snapshot_table = self._build_table(["Time", "Kind", "Label", "Path"])
        self.tabs.addTab(self.snapshot_table, "Snapshots")

        buttons = QHBoxLayout()
        self.undo_btn = QPushButton("Undo")
        self.redo_btn = QPushButton("Redo")
        self.create_snapshot_btn = QPushButton("Create Snapshot…")
        self.restore_snapshot_btn = QPushButton("Restore Snapshot")
        self.delete_snapshot_btn = QPushButton("Delete Snapshot")
        self.refresh_btn = QPushButton("Refresh")
        self.close_btn = QPushButton("Close")

        self.undo_btn.clicked.connect(self._undo)
        self.redo_btn.clicked.connect(self._redo)
        self.create_snapshot_btn.clicked.connect(self._create_snapshot)
        self.restore_snapshot_btn.clicked.connect(self._restore_snapshot)
        self.delete_snapshot_btn.clicked.connect(self._delete_snapshot)
        self.refresh_btn.clicked.connect(self.refresh_data)
        self.close_btn.clicked.connect(self.accept)

        for button in (
            self.undo_btn,
            self.redo_btn,
            self.create_snapshot_btn,
            self.restore_snapshot_btn,
            self.delete_snapshot_btn,
            self.refresh_btn,
            self.close_btn,
        ):
            buttons.addWidget(button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self.refresh_data()

    @staticmethod
    def _build_table(headers: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        return table

    def refresh_data(self):
        self._populate_entry_table(
            self.session_table, self.app.session_history_manager.list_entries()
        )

        history_entries = (
            self.app.history_manager.list_entries() if self.app.history_manager is not None else []
        )
        self._populate_entry_table(self.history_table, history_entries)

        snapshots = (
            self.app.history_manager.list_snapshots()
            if self.app.history_manager is not None
            else []
        )
        self.snapshot_table.setRowCount(len(snapshots))
        for row_idx, snapshot in enumerate(snapshots):
            values = [
                snapshot.created_at,
                snapshot.kind,
                snapshot.label,
                snapshot.db_snapshot_path,
            ]
            for col_idx, value in enumerate(values):
                self.snapshot_table.setItem(row_idx, col_idx, QTableWidgetItem(value))
            self.snapshot_table.item(row_idx, 0).setData(Qt.UserRole, snapshot.snapshot_id)
        self.snapshot_table.resizeColumnsToContents()

        undo_source, undo_entry = self.app._get_best_history_candidate("undo")
        redo_source, redo_entry = self.app._get_best_history_candidate("redo")
        self.undo_btn.setEnabled(bool(undo_source and undo_entry))
        self.redo_btn.setEnabled(bool(redo_source and redo_entry))
        self.restore_snapshot_btn.setEnabled(
            self.app.history_manager is not None and self.snapshot_table.rowCount() > 0
        )
        self.delete_snapshot_btn.setEnabled(
            self.app.history_manager is not None and self.snapshot_table.rowCount() > 0
        )

    @staticmethod
    def _populate_entry_table(table: QTableWidget, entries):
        table.setRowCount(len(entries))
        for row_idx, entry in enumerate(entries):
            values = [
                "●" if entry.is_current else "",
                entry.created_at,
                entry.label,
                getattr(entry, "action_type", ""),
            ]
            for col_idx, value in enumerate(values):
                table.setItem(row_idx, col_idx, QTableWidgetItem(value))
            table.item(row_idx, 0).setData(Qt.UserRole, entry.entry_id)
        table.resizeColumnsToContents()

    def _selected_snapshot_id(self) -> int | None:
        row = self.snapshot_table.currentRow()
        if row < 0 or self.snapshot_table.item(row, 0) is None:
            return None
        return int(self.snapshot_table.item(row, 0).data(Qt.UserRole))

    def _undo(self):
        self.app.history_undo()
        self.refresh_data()

    def _redo(self):
        self.app.history_redo()
        self.refresh_data()

    def _create_snapshot(self):
        self.app.create_manual_snapshot()
        self.refresh_data()

    def _restore_snapshot(self):
        snapshot_id = self._selected_snapshot_id()
        if snapshot_id is None:
            QMessageBox.information(self, "Snapshots", "Select a snapshot first.")
            return
        self.app.restore_snapshot_from_history(snapshot_id)
        self.refresh_data()

    def _delete_snapshot(self):
        snapshot_id = self._selected_snapshot_id()
        if snapshot_id is None:
            QMessageBox.information(self, "Snapshots", "Select a snapshot first.")
            return
        if (
            QMessageBox.question(
                self,
                "Delete Snapshot",
                "Delete this snapshot from disk and history metadata?",
                QMessageBox.Yes | QMessageBox.No,
            )
            != QMessageBox.Yes
        ):
            return
        try:
            self.app.delete_snapshot_from_history(snapshot_id)
        except Exception as exc:
            QMessageBox.warning(self, "Delete Snapshot", str(exc))
        self.refresh_data()

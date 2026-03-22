"""History and snapshot UI."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
)

from isrc_manager.history.cleanup import HistoryCleanupBlockedError, HistoryStorageCleanupService
from isrc_manager.ui_common import _apply_standard_dialog_chrome


class HistoryDialog(QDialog):
    """Simple history and snapshot browser."""

    def __init__(self, app, parent=None):
        super().__init__(parent or app)
        self.app = app
        self.setWindowTitle("Undo History")
        self.resize(1040, 720)
        self.setMinimumSize(940, 640)
        _apply_standard_dialog_chrome(self, "historyDialog")

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

        self.backup_table = self._build_table(["Time", "Kind", "Label", "Path"])
        self.tabs.addTab(self.backup_table, "Backups")

        buttons = QHBoxLayout()
        self.undo_btn = QPushButton("Undo")
        self.redo_btn = QPushButton("Redo")
        self.create_snapshot_btn = QPushButton("Create Snapshot…")
        self.restore_snapshot_btn = QPushButton("Restore Snapshot")
        self.delete_snapshot_btn = QPushButton("Delete Snapshot")
        self.delete_backup_btn = QPushButton("Delete Backup")
        self.cleanup_btn = QPushButton("Cleanup…")
        self.refresh_btn = QPushButton("Refresh")
        self.close_btn = QPushButton("Close")

        self.undo_btn.clicked.connect(self._undo)
        self.redo_btn.clicked.connect(self._redo)
        self.create_snapshot_btn.clicked.connect(self._create_snapshot)
        self.restore_snapshot_btn.clicked.connect(self._restore_snapshot)
        self.delete_snapshot_btn.clicked.connect(self._delete_snapshot)
        self.delete_backup_btn.clicked.connect(self._delete_backup)
        self.cleanup_btn.clicked.connect(self._open_cleanup_dialog)
        self.refresh_btn.clicked.connect(self.refresh_data)
        self.close_btn.clicked.connect(self.accept)
        self.tabs.currentChanged.connect(self._update_action_state)
        self.snapshot_table.itemSelectionChanged.connect(self._update_action_state)
        self.backup_table.itemSelectionChanged.connect(self._update_action_state)

        for button in (
            self.undo_btn,
            self.redo_btn,
            self.create_snapshot_btn,
            self.restore_snapshot_btn,
            self.delete_snapshot_btn,
            self.delete_backup_btn,
            self.cleanup_btn,
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

        backups = (
            self.app.history_manager.list_backups() if self.app.history_manager is not None else []
        )
        self.backup_table.setRowCount(len(backups))
        for row_idx, backup in enumerate(backups):
            values = [
                backup.created_at,
                backup.kind,
                backup.label,
                backup.backup_path,
            ]
            for col_idx, value in enumerate(values):
                self.backup_table.setItem(row_idx, col_idx, QTableWidgetItem(value))
            self.backup_table.item(row_idx, 0).setData(Qt.UserRole, backup.backup_id)
        self.backup_table.resizeColumnsToContents()

        undo_source, undo_entry = self.app._get_best_history_candidate("undo")
        redo_source, redo_entry = self.app._get_best_history_candidate("redo")
        self.undo_btn.setEnabled(bool(undo_source and undo_entry))
        self.redo_btn.setEnabled(bool(redo_source and redo_entry))
        self._update_action_state()

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

    def _selected_backup_id(self) -> int | None:
        row = self.backup_table.currentRow()
        if row < 0 or self.backup_table.item(row, 0) is None:
            return None
        return int(self.backup_table.item(row, 0).data(Qt.UserRole))

    def _update_action_state(self):
        has_history = self.app.history_manager is not None
        snapshot_selected = self._selected_snapshot_id() is not None
        backup_selected = self._selected_backup_id() is not None
        self.restore_snapshot_btn.setEnabled(has_history and snapshot_selected)
        self.delete_snapshot_btn.setEnabled(has_history and snapshot_selected)
        self.delete_backup_btn.setEnabled(has_history and backup_selected)
        self.cleanup_btn.setEnabled(has_history)

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

    def _delete_backup(self):
        backup_id = self._selected_backup_id()
        if backup_id is None:
            QMessageBox.information(self, "Backups", "Select a backup first.")
            return
        if (
            QMessageBox.question(
                self,
                "Delete Backup",
                "Delete this backup file and its registered metadata?",
                QMessageBox.Yes | QMessageBox.No,
            )
            != QMessageBox.Yes
        ):
            return
        try:
            self.app.delete_backup_from_history(backup_id)
        except Exception as exc:
            QMessageBox.warning(self, "Delete Backup", str(exc))
        self.refresh_data()

    def _open_cleanup_dialog(self):
        dialog = HistoryCleanupDialog(self.app, parent=self)
        dialog.exec()
        self.refresh_data()


class HistoryCleanupDialog(QDialog):
    """Preview and clean eligible history storage artifacts."""

    RETENTION_MODE_LABELS = {
        "maximum_safety": "Maximum Safety",
        "balanced": "Balanced",
        "lean": "Lean",
        "custom": "Custom",
    }
    TYPE_LABELS = {
        "snapshot_record": "Snapshot",
        "backup_record": "Backup",
        "orphan_snapshot_file": "Orphan Snapshot File",
        "orphan_backup_file": "Orphan Backup File",
        "snapshot_archive": "Snapshot Archive",
        "file_state_bundle": "File-State Bundle",
        "session_snapshot": "Session Snapshot",
    }

    def __init__(self, app, parent=None):
        super().__init__(parent or app)
        self.app = app
        self.cleanup_service = (
            HistoryStorageCleanupService(app.history_manager)
            if getattr(app, "history_manager", None) is not None
            else None
        )
        self.setWindowTitle("History Cleanup")
        self.resize(1080, 760)
        self.setMinimumSize(960, 680)
        _apply_standard_dialog_chrome(self, "historyCleanupDialog")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        title_label = QLabel("Cleanup History Storage", self)
        title_label.setProperty("role", "dialogTitle")
        layout.addWidget(title_label)

        subtitle_label = QLabel(
            "Review snapshots, backup artifacts, archived snapshot bundles, file-state bundles, and session snapshots before removing older items.",
            self,
        )
        subtitle_label.setProperty("role", "dialogSubtitle")
        subtitle_label.setWordWrap(True)
        layout.addWidget(subtitle_label)

        self.summary_label = QLabel(self)
        self.summary_label.setProperty("role", "supportingText")
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        eligible_group = QGroupBox("Eligible For Cleanup", self)
        eligible_layout = QVBoxLayout(eligible_group)
        eligible_layout.setContentsMargins(14, 18, 14, 14)
        eligible_layout.setSpacing(10)
        eligible_help = QLabel(
            "Only items that are not required by retained history and restore behavior are shown here.",
            eligible_group,
        )
        eligible_help.setProperty("role", "supportingText")
        eligible_help.setWordWrap(True)
        eligible_layout.addWidget(eligible_help)
        self.eligible_table = self._build_cleanup_table()
        self.eligible_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        eligible_layout.addWidget(self.eligible_table, 1)
        layout.addWidget(eligible_group, 1)

        protected_group = QGroupBox("Protected Items", self)
        protected_layout = QVBoxLayout(protected_group)
        protected_layout.setContentsMargins(14, 18, 14, 14)
        protected_layout.setSpacing(10)
        protected_help = QLabel(
            "These items are still referenced by history, undo/redo, snapshot restore, or session restore data.",
            protected_group,
        )
        protected_help.setProperty("role", "supportingText")
        protected_help.setWordWrap(True)
        protected_layout.addWidget(protected_help)
        self.protected_table = self._build_cleanup_table()
        protected_layout.addWidget(self.protected_table, 1)
        layout.addWidget(protected_group, 1)

        buttons = QHBoxLayout()
        self.refresh_btn = QPushButton("Refresh")
        self.delete_selected_btn = QPushButton("Delete Selected")
        self.trim_history_btn = QPushButton("Trim History…")
        self.close_btn = QPushButton("Close")
        buttons.addWidget(self.refresh_btn)
        buttons.addWidget(self.delete_selected_btn)
        buttons.addWidget(self.trim_history_btn)
        buttons.addStretch(1)
        buttons.addWidget(self.close_btn)
        layout.addLayout(buttons)

        self.refresh_btn.clicked.connect(self.refresh_data)
        self.delete_selected_btn.clicked.connect(self._delete_selected)
        self.trim_history_btn.clicked.connect(self._trim_history)
        self.close_btn.clicked.connect(self.accept)

        self.refresh_data()

    @staticmethod
    def _build_cleanup_table() -> QTableWidget:
        table = QTableWidget(0, 5)
        table.setHorizontalHeaderLabels(["Type", "Time", "Label", "Path", "Reason"])
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        return table

    def refresh_data(self):
        if self.cleanup_service is None:
            self.summary_label.setText("Open a profile first to inspect cleanup candidates.")
            self.eligible_table.setRowCount(0)
            self.protected_table.setRowCount(0)
            self.delete_selected_btn.setEnabled(False)
            self.trim_history_btn.setEnabled(False)
            return

        preview = self.cleanup_service.inspect()
        budget_preview = None
        retention_settings = None
        settings_reads = getattr(self.app, "settings_reads", None)
        if settings_reads is not None:
            try:
                retention_settings = settings_reads.load_history_retention_settings()
                budget_preview = self.cleanup_service.preview_storage_budget(retention_settings)
            except Exception:
                budget_preview = None
                retention_settings = None
        if preview.repair_required:
            summary_text = (
                "Cleanup is currently blocked because history diagnostics found issues that must be repaired first.\n\n"
                + "\n".join(preview.repair_messages[:6])
            )
        else:
            summary_text = (
                f"{len(preview.eligible_items)} eligible item(s) can be removed safely. "
                f"{len(preview.protected_items)} item(s) are still protected by history references."
            )
        if budget_preview is not None and budget_preview.budget_bytes > 0:
            summary_text += (
                "\n\n"
                f"History storage is using {self._human_size(budget_preview.total_bytes)} "
                f"of a {self._human_size(budget_preview.budget_bytes)} budget."
            )
            if retention_settings is not None:
                mode_label = self.RETENTION_MODE_LABELS.get(
                    str(retention_settings.retention_mode or ""),
                    str(retention_settings.retention_mode or ""),
                )
                summary_text += f" Retention level: {mode_label}."
            if budget_preview.over_budget_bytes > 0:
                summary_text += f" The profile is over budget by {self._human_size(budget_preview.over_budget_bytes)}."
                if budget_preview.candidate_items:
                    summary_text += (
                        f" Automatic cleanup can remove {len(budget_preview.candidate_items)} "
                        "safe item(s) under the current policy."
                    )
                elif budget_preview.protected_over_budget_items:
                    summary_text += " The remaining over-budget storage is protected by retained history or manual restore points."
        self.summary_label.setText(summary_text)

        self._populate_cleanup_table(self.eligible_table, preview.eligible_items)
        self._populate_cleanup_table(self.protected_table, preview.protected_items)
        self.delete_selected_btn.setEnabled(
            not preview.repair_required and self.eligible_table.rowCount() > 0
        )
        self.trim_history_btn.setEnabled(not preview.repair_required)

    def _populate_cleanup_table(self, table: QTableWidget, items) -> None:
        table.setRowCount(len(items))
        for row_idx, item in enumerate(items):
            values = [
                self.TYPE_LABELS.get(item.item_type, item.item_type),
                item.created_at,
                item.label,
                item.path,
                item.reason,
            ]
            for col_idx, value in enumerate(values):
                table.setItem(row_idx, col_idx, QTableWidgetItem(str(value or "")))
            table.item(row_idx, 0).setData(Qt.UserRole, item.item_key)
        table.resizeColumnsToContents()

    def _selected_cleanup_keys(self) -> list[str]:
        keys: list[str] = []
        for item in self.eligible_table.selectedItems():
            if item.column() != 0:
                continue
            key = item.data(Qt.UserRole)
            if key:
                keys.append(str(key))
        return keys

    def _delete_selected(self):
        if self.cleanup_service is None:
            return
        keys = self._selected_cleanup_keys()
        if not keys:
            QMessageBox.information(self, "History Cleanup", "Select one or more eligible items.")
            return
        if (
            QMessageBox.question(
                self,
                "Delete Selected History Artifacts",
                f"Remove {len(keys)} selected cleanup item(s)?\n\nOnly eligible, unreferenced artifacts will be deleted.",
                QMessageBox.Yes | QMessageBox.No,
            )
            != QMessageBox.Yes
        ):
            return
        try:
            result = self.cleanup_service.cleanup_selected(keys)
        except HistoryCleanupBlockedError as exc:
            QMessageBox.warning(self, "History Cleanup", str(exc))
            return
        except Exception as exc:
            QMessageBox.critical(self, "History Cleanup", str(exc))
            return
        self._refresh_after_cleanup()
        QMessageBox.information(
            self,
            "History Cleanup",
            f"Removed {len(result.removed_item_keys)} cleanup item(s).",
        )
        self.refresh_data()

    def _trim_history(self):
        if self.cleanup_service is None:
            return
        keep_visible_entries, ok = QInputDialog.getInt(
            self,
            "Trim History",
            "Keep the most recent reversible history entries on the active branch:",
            25,
            1,
            10000,
        )
        if not ok:
            return
        preview = self.cleanup_service.preview_trim_history(keep_visible_entries)
        if not preview.removable_entry_ids:
            QMessageBox.information(
                self,
                "Trim History",
                "No older history rows are eligible for trimming at this retention level.",
            )
            return
        example_text = "\n".join(preview.removable_labels) if preview.removable_labels else "(none)"
        if (
            QMessageBox.question(
                self,
                "Trim History",
                f"This will remove {len(preview.removable_entry_ids)} older history row(s) and then delete newly unreferenced snapshot and artifact storage.\n\nExamples:\n{example_text}\n\nContinue?",
                QMessageBox.Yes | QMessageBox.No,
            )
            != QMessageBox.Yes
        ):
            return
        try:
            result = self.cleanup_service.trim_history(keep_visible_entries)
        except HistoryCleanupBlockedError as exc:
            QMessageBox.warning(self, "Trim History", str(exc))
            return
        except Exception as exc:
            QMessageBox.critical(self, "Trim History", str(exc))
            return
        self._refresh_after_cleanup()
        QMessageBox.information(
            self,
            "Trim History",
            f"Removed {len(result.removed_entry_ids)} history row(s) and {len(result.removed_item_keys)} storage artifact(s).",
        )
        self.refresh_data()

    def _refresh_after_cleanup(self):
        refresh_history_actions = getattr(self.app, "_refresh_history_actions", None)
        if callable(refresh_history_actions):
            refresh_history_actions()
        history_dialog = getattr(self.app, "history_dialog", None)
        if history_dialog is not None and history_dialog is not self:
            try:
                history_dialog.refresh_data()
            except Exception:
                pass

    @staticmethod
    def _human_size(size_bytes: int) -> str:
        try:
            value = float(int(size_bytes or 0))
        except Exception:
            value = 0.0
        units = ["B", "KB", "MB", "GB", "TB"]
        index = 0
        while value >= 1024.0 and index < len(units) - 1:
            value /= 1024.0
            index += 1
        return f"{value:.0f} {units[index]}" if index == 0 else f"{value:.1f} {units[index]}"

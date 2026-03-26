"""Dialogs for reviewing and repairing failed track-import rows."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from isrc_manager.services.import_repair_queue import TrackImportRepairEntry
from isrc_manager.ui_common import (
    _add_standard_dialog_header,
    _apply_compact_dialog_control_heights,
    _apply_standard_dialog_chrome,
)

_CORE_FIELD_ORDER = [
    "track_title",
    "artist_name",
    "additional_artists",
    "album_title",
    "release_date",
    "track_length_sec",
    "track_length_hms",
    "isrc",
    "iswc",
    "upc",
    "genre",
    "catalog_number",
    "buma_work_number",
    "composer",
    "publisher",
    "comments",
    "lyrics",
    "audio_file_path",
    "album_art_path",
    "release_title",
    "release_primary_artist",
    "release_album_artist",
    "release_type",
    "release_date_release",
    "release_catalog_number",
    "release_upc",
]


class TrackImportRepairEntryDialog(QDialog):
    """Repair a single failed import row and replay it through governed creation."""

    def __init__(
        self,
        *,
        entry: TrackImportRepairEntry,
        work_choices: list[tuple[int, str]],
        parent=None,
    ):
        super().__init__(parent)
        self.entry = entry
        self.work_choices = [(int(work_id), str(label)) for work_id, label in work_choices]
        self.setWindowTitle("Repair Imported Track Row")
        self.resize(920, 700)
        _apply_standard_dialog_chrome(self, "trackImportRepairEntryDialog")

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)
        _add_standard_dialog_header(
            root,
            self,
            title="Repair Imported Track Row",
            subtitle=(
                "Fix the blocked row and replay it through the governed track-creation workflow. "
                "The row will not enter the live catalog until a valid linked Work is resolved."
            ),
        )

        summary = QLabel(
            "\n".join(
                [
                    f"Source: {entry.source_format.upper()}",
                    f"Original row: {entry.row_index}",
                    f"Failure: {entry.failure_message}",
                ]
            ),
            self,
        )
        summary.setWordWrap(True)
        summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(summary)

        governance_row = QHBoxLayout()
        governance_row.setContentsMargins(0, 0, 0, 0)
        governance_row.setSpacing(8)
        governance_row.addWidget(QLabel("Governance"))
        self.governance_combo = QComboBox(self)
        self.governance_combo.addItem("Create New Work from This Row", "create_new_work")
        self.governance_combo.addItem("Link to Existing Work", "link_existing_work")
        governance_row.addWidget(self.governance_combo)
        governance_row.addWidget(QLabel("Work"))
        self.work_combo = QComboBox(self)
        self.work_combo.addItem("", None)
        for work_id, label in self.work_choices:
            self.work_combo.addItem(label, work_id)
        governance_row.addWidget(self.work_combo, 1)
        root.addLayout(governance_row)

        self.field_table = QTableWidget(0, 2, self)
        self.field_table.setHorizontalHeaderLabels(["Field", "Value"])
        self.field_table.verticalHeader().setVisible(False)
        self.field_table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.field_table, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel, self)
        repair_button = buttons.button(QDialogButtonBox.Save)
        if repair_button is not None:
            repair_button.setText("Reapply Row")
            repair_button.setDefault(True)
        buttons.accepted.connect(self._accept_with_validation)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.governance_combo.currentIndexChanged.connect(self._refresh_governance_state)
        self._populate_field_table()
        self._refresh_governance_state()
        _apply_compact_dialog_control_heights(self)

    def _ordered_fields(self) -> list[str]:
        keys = [str(key) for key in self.entry.normalized_row.keys()]
        ordered: list[str] = []
        seen: set[str] = set()
        for field_name in _CORE_FIELD_ORDER:
            if field_name in self.entry.normalized_row and field_name not in seen:
                seen.add(field_name)
                ordered.append(field_name)
        for field_name in sorted(
            [key for key in keys if str(key).startswith("custom::")],
            key=str.casefold,
        ):
            if field_name not in seen:
                seen.add(field_name)
                ordered.append(field_name)
        for field_name in keys:
            if field_name not in seen:
                seen.add(field_name)
                ordered.append(field_name)
        return ordered

    def _populate_field_table(self) -> None:
        self.field_table.setRowCount(0)
        for field_name in self._ordered_fields():
            row = self.field_table.rowCount()
            self.field_table.insertRow(row)
            field_item = QTableWidgetItem(field_name)
            field_item.setFlags(field_item.flags() & ~Qt.ItemIsEditable)
            self.field_table.setItem(row, 0, field_item)
            raw_value = self.entry.normalized_row.get(field_name)
            if isinstance(raw_value, list):
                value_text = ", ".join(str(item).strip() for item in raw_value if str(item).strip())
            else:
                value_text = str(raw_value or "")
            self.field_table.setItem(row, 1, QTableWidgetItem(value_text))
        self.field_table.resizeColumnsToContents()

    def _refresh_governance_state(self) -> None:
        link_existing = str(self.governance_combo.currentData() or "") == "link_existing_work"
        self.work_combo.setEnabled(link_existing)

    def _accept_with_validation(self) -> None:
        if str(self.governance_combo.currentData() or "") == "link_existing_work":
            if self.work_combo.currentData() in (None, ""):
                QMessageBox.information(
                    self,
                    "Repair Imported Track Row",
                    "Choose an existing Work before reapplying the row.",
                )
                return
        self.accept()

    def edited_row(self) -> dict[str, object]:
        row: dict[str, object] = {}
        for table_row in range(self.field_table.rowCount()):
            field_item = self.field_table.item(table_row, 0)
            value_item = self.field_table.item(table_row, 1)
            if field_item is None:
                continue
            row[str(field_item.text())] = str(
                value_item.text() if value_item is not None else ""
            ).strip()
        return row

    def repair_override(self) -> dict[str, object]:
        work_id = self.work_combo.currentData()
        return {
            "governance_mode": str(self.governance_combo.currentData() or "create_new_work"),
            "work_id": int(work_id) if work_id not in (None, "") else None,
        }


class TrackImportRepairQueueDialog(QDialog):
    """Browse pending or resolved failed track-import rows."""

    def __init__(
        self,
        *,
        entries_provider,
        repair_selected_handler,
        delete_selected_handler,
        parent=None,
    ):
        super().__init__(parent)
        self.entries_provider = entries_provider
        self.repair_selected_handler = repair_selected_handler
        self.delete_selected_handler = delete_selected_handler
        self.setWindowTitle("Track Import Repair Queue")
        self.resize(1120, 620)
        _apply_standard_dialog_chrome(self, "trackImportRepairQueueDialog")

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)
        _add_standard_dialog_header(
            root,
            self,
            title="Track Import Repair Queue",
            subtitle=(
                "Rows blocked by governed creation or blocking validation stay here until they are repaired "
                "and successfully replayed into the live catalog."
            ),
        )

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(8)
        self.show_resolved_checkbox = QCheckBox("Show resolved rows", self)
        self.show_resolved_checkbox.toggled.connect(self.refresh_entries)
        toolbar.addWidget(self.show_resolved_checkbox)
        toolbar.addStretch(1)
        refresh_button = QPushButton("Refresh", self)
        refresh_button.clicked.connect(self.refresh_entries)
        repair_button = QPushButton("Repair Selected...", self)
        repair_button.clicked.connect(self._repair_selected)
        delete_button = QPushButton("Delete Selected", self)
        delete_button.clicked.connect(self._delete_selected)
        toolbar.addWidget(refresh_button)
        toolbar.addWidget(repair_button)
        toolbar.addWidget(delete_button)
        root.addLayout(toolbar)

        self.table = QTableWidget(0, 7, self)
        self.table.setHorizontalHeaderLabels(
            ["ID", "Status", "Format", "Row", "Track Title", "Artist", "Failure"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.doubleClicked.connect(self._repair_selected)
        root.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        close_button = QPushButton("Close", self)
        close_button.clicked.connect(self.accept)
        buttons.addWidget(close_button)
        root.addLayout(buttons)

        self.refresh_entries()
        _apply_compact_dialog_control_heights(self)

    def refresh_entries(self) -> None:
        entries = list(self.entries_provider(bool(self.show_resolved_checkbox.isChecked())) or [])
        self.table.setRowCount(0)
        for entry in entries:
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = [
                str(entry.id),
                entry.status,
                entry.source_format.upper(),
                str(entry.row_index),
                str(entry.normalized_row.get("track_title") or ""),
                str(entry.normalized_row.get("artist_name") or ""),
                entry.failure_message,
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column in {0, 3}:
                    item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row, column, item)
        self.table.resizeColumnsToContents()

    def selected_entry_id(self) -> int | None:
        current_row = self.table.currentRow()
        if current_row < 0:
            return None
        item = self.table.item(current_row, 0)
        if item is None:
            return None
        try:
            return int(item.text())
        except Exception:
            return None

    def _repair_selected(self) -> None:
        entry_id = self.selected_entry_id()
        if entry_id is None:
            QMessageBox.information(
                self,
                "Track Import Repair Queue",
                "Select a repair row first.",
            )
            return
        self.repair_selected_handler(int(entry_id))

    def _delete_selected(self) -> None:
        entry_id = self.selected_entry_id()
        if entry_id is None:
            QMessageBox.information(
                self,
                "Track Import Repair Queue",
                "Select a repair row first.",
            )
            return
        self.delete_selected_handler([int(entry_id)])

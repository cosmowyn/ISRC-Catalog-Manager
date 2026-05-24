"""Album track ordering dialog."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from isrc_manager.services import TrackSnapshot
from isrc_manager.tracks.host_protocols import AlbumEditorHost
from isrc_manager.ui_common import (
    _add_standard_dialog_header,
    _apply_compact_dialog_control_heights,
    _apply_standard_dialog_chrome,
    _configure_standard_form_layout,
)


class _AlbumTrackOrderingTable(QTableWidget):
    orderChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(0, 4, parent)
        self.setHorizontalHeaderLabels(["Track #", "Track Title", "Artist", "ISRC"])
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropOverwriteMode(False)
        self.setDefaultDropAction(Qt.CopyAction)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.verticalHeader().setVisible(False)
        header = self.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)

    def move_current_row(self, offset: int) -> int | None:
        source_row = self.currentRow()
        if source_row < 0:
            return None
        destination_row = source_row + int(offset)
        if destination_row < 0 or destination_row >= self.rowCount():
            return None
        return self._move_row(source_row, destination_row)

    def dropEvent(self, event) -> None:
        if event.source() is not self:
            event.ignore()
            return
        selected_ranges = self.selectedRanges()
        if not selected_ranges:
            event.ignore()
            return
        event.setDropAction(Qt.CopyAction)
        source_row = int(selected_ranges[0].topRow())
        destination_row = self._drop_row_for_event(source_row, event)
        if destination_row < 0:
            event.ignore()
            return
        moved_row = self._move_row(source_row, destination_row)
        if moved_row is None:
            event.accept()
            return
        event.acceptProposedAction()

    def dragEnterEvent(self, event) -> None:
        if event.source() is self:
            event.acceptProposedAction()
            return
        event.ignore()

    def dragMoveEvent(self, event) -> None:
        if event.source() is self:
            event.setDropAction(Qt.CopyAction)
            event.accept()
            return
        event.ignore()

    def _drop_row_for_event(self, source_row: int, event) -> int:
        point = event.position().toPoint() if hasattr(event, "position") else event.pos()
        row = self.rowAt(point.y())
        if row < 0:
            return self.rowCount() - 1
        indicator = self.dropIndicatorPosition()
        if indicator == QAbstractItemView.AboveItem:
            return row - 1 if row > source_row else row
        if indicator == QAbstractItemView.BelowItem:
            return row if row > source_row else min(row + 1, self.rowCount() - 1)
        return row

    def _move_row(self, source_row: int, destination_row: int) -> int | None:
        if source_row < 0 or source_row >= self.rowCount():
            return None
        bounded_destination = max(0, min(int(destination_row), self.rowCount() - 1))
        if bounded_destination == source_row:
            return None
        row_items = [self.takeItem(source_row, column) for column in range(self.columnCount())]
        self.removeRow(source_row)
        insert_row = max(0, min(bounded_destination, self.rowCount()))
        self.insertRow(insert_row)
        for column, item in enumerate(row_items):
            if item is not None:
                self.setItem(insert_row, column, item)
        self.selectRow(insert_row)
        self.setCurrentCell(insert_row, 0)
        self.orderChanged.emit()
        return insert_row


class AlbumTrackOrderingDialog(QDialog):
    def __init__(
        self,
        app: AlbumEditorHost,
        *,
        album_title: str,
        snapshots: list[TrackSnapshot],
        parent=None,
    ):
        super().__init__(parent or app)
        self.app = app
        self.album_title = str(album_title or "").strip()
        self._snapshots = list(snapshots)
        self.setObjectName("albumTrackOrderingDialog")
        self.setWindowTitle("Album Track Ordering")
        self.setModal(True)
        self.resize(860, 560)
        self.setMinimumSize(760, 480)
        _apply_standard_dialog_chrome(self, "albumTrackOrderingDialog")

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        _add_standard_dialog_header(
            root,
            self,
            title="Album Track Ordering",
            subtitle=(
                "Review the stored album order, move the selected track up or down, "
                "or drag rows directly before saving the new sequence."
            ),
        )

        album_group = QGroupBox("Album", self)
        album_layout = QFormLayout(album_group)
        album_layout.setContentsMargins(12, 12, 12, 12)
        _configure_standard_form_layout(album_layout)
        album_value = QLabel(self.album_title or "Unnamed Album", album_group)
        album_value.setWordWrap(True)
        album_layout.addRow("Album Title", album_value)
        root.addWidget(album_group)

        table_group = QGroupBox("Album Tracks", self)
        table_layout = QVBoxLayout(table_group)
        table_layout.setContentsMargins(12, 12, 12, 12)
        table_layout.setSpacing(10)

        controls_row = QHBoxLayout()
        controls_row.setContentsMargins(0, 0, 0, 0)
        controls_row.setSpacing(8)
        self.move_up_button = QPushButton("Move Up", table_group)
        self.move_up_button.clicked.connect(lambda: self._move_selected_row(-1))
        self.move_down_button = QPushButton("Move Down", table_group)
        self.move_down_button.clicked.connect(lambda: self._move_selected_row(1))
        controls_row.addWidget(self.move_up_button)
        controls_row.addWidget(self.move_down_button)
        controls_row.addStretch(1)
        table_layout.addLayout(controls_row)

        self.table = _AlbumTrackOrderingTable(table_group)
        self.table.orderChanged.connect(self._refresh_row_numbers)
        self.table.itemSelectionChanged.connect(self._update_button_states)
        table_layout.addWidget(self.table, 1)
        root.addWidget(table_group, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel,
            Qt.Horizontal,
            self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._populate()
        _apply_compact_dialog_control_heights(self)

    def ordered_track_ids(self) -> list[int]:
        ordered_ids: list[int] = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is None:
                continue
            try:
                ordered_ids.append(int(item.data(Qt.UserRole)))
            except (TypeError, ValueError):
                continue
        return ordered_ids

    def _populate(self) -> None:
        self.table.setRowCount(0)
        for row, snapshot in enumerate(self._snapshots):
            self.table.insertRow(row)
            number_item = QTableWidgetItem(str(row + 1))
            number_item.setTextAlignment(Qt.AlignCenter)
            number_item.setData(Qt.UserRole, int(snapshot.track_id))
            title_item = QTableWidgetItem(str(snapshot.track_title or "").strip())
            artist_item = QTableWidgetItem(str(snapshot.artist_name or "").strip())
            isrc_item = QTableWidgetItem(str(snapshot.isrc or "").strip())
            for column, item in enumerate((number_item, title_item, artist_item, isrc_item)):
                self.table.setItem(row, column, item)
        if self.table.rowCount() > 0:
            self.table.selectRow(0)
            self.table.setCurrentCell(0, 0)
        self._update_button_states()

    def _refresh_row_numbers(self) -> None:
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is not None:
                item.setText(str(row + 1))
        self._update_button_states()

    def _move_selected_row(self, offset: int) -> None:
        self.table.move_current_row(int(offset))

    def _update_button_states(self) -> None:
        current_row = self.table.currentRow()
        row_count = self.table.rowCount()
        has_selection = current_row >= 0 and row_count > 0
        self.move_up_button.setEnabled(has_selection and current_row > 0)
        self.move_down_button.setEnabled(has_selection and current_row < (row_count - 1))


__all__ = ["AlbumTrackOrderingDialog", "_AlbumTrackOrderingTable"]

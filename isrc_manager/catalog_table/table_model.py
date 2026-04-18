"""Pure `QAbstractTableModel` for catalog-table snapshot data."""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, Qt

from .models import (
    CatalogCellValue,
    CatalogColumnSpec,
    CatalogSnapshot,
    ColumnKeyRole,
    RawValueRole,
    SearchTextRole,
    SortRole,
    TrackIdRole,
)


class CatalogTableModel(QAbstractTableModel):
    """Expose pure snapshot data through stable catalog-specific Qt roles."""

    def __init__(
        self,
        snapshot: CatalogSnapshot | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._snapshot = snapshot or CatalogSnapshot.empty()
        self._track_id_to_source_row = self._build_track_id_index(self._snapshot)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._snapshot.rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._snapshot.column_specs)

    def data(self, index: QModelIndex, role: int = int(Qt.ItemDataRole.DisplayRole)):
        if not index.isValid():
            return None

        row = index.row()
        column = index.column()
        if not (
            0 <= row < len(self._snapshot.rows) and 0 <= column < len(self._snapshot.column_specs)
        ):
            return None

        column_spec = self._snapshot.column_specs[column]
        row_snapshot = self._snapshot.rows[row]
        cell_value = row_snapshot.cell(column_spec.key) or CatalogCellValue()

        if role in (
            int(Qt.ItemDataRole.DisplayRole),
            int(Qt.ItemDataRole.EditRole),
        ):
            return cell_value.display_text
        if role == int(Qt.ItemDataRole.ToolTipRole):
            return cell_value.tooltip
        if role == int(Qt.ItemDataRole.DecorationRole):
            return (
                cell_value.decoration
                if cell_value.decoration is not None
                else cell_value.decoration_key
            )
        if role == int(Qt.ItemDataRole.TextAlignmentRole):
            return cell_value.text_alignment
        if role == SortRole:
            return cell_value.sort_value
        if role == SearchTextRole:
            return cell_value.search_text
        if role == TrackIdRole:
            return row_snapshot.track_id
        if role == ColumnKeyRole:
            return column_spec.key
        if role == RawValueRole:
            return cell_value.raw_value
        return None

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = int(Qt.ItemDataRole.DisplayRole),
    ):
        if orientation != Qt.Orientation.Horizontal:
            return None
        spec = self.column_spec(section)
        if spec is None:
            return None
        if role == int(Qt.ItemDataRole.DisplayRole):
            return spec.header_text
        if role == int(Qt.ItemDataRole.ToolTipRole):
            return spec.notes
        if role == ColumnKeyRole:
            return spec.key
        return None

    def set_snapshot(self, snapshot: CatalogSnapshot | None) -> None:
        """Replace the pure source snapshot and reset role-backed row mappings."""

        self.beginResetModel()
        self._snapshot = snapshot or CatalogSnapshot.empty()
        self._track_id_to_source_row = self._build_track_id_index(self._snapshot)
        self.endResetModel()

    def column_spec(self, section: int) -> CatalogColumnSpec | None:
        if 0 <= section < len(self._snapshot.column_specs):
            return self._snapshot.column_specs[section]
        return None

    def track_id_for_source_row(self, source_row: int) -> int | None:
        if 0 <= source_row < len(self._snapshot.rows):
            return self._snapshot.rows[source_row].track_id
        return None

    def source_row_for_track_id(self, track_id: int) -> int | None:
        return self._track_id_to_source_row.get(int(track_id))

    @staticmethod
    def _build_track_id_index(snapshot: CatalogSnapshot) -> dict[int, int]:
        return {row.track_id: source_row for source_row, row in enumerate(snapshot.rows)}

    def roleNames(self) -> dict[int, bytes]:
        role_names = dict(super().roleNames())
        role_names.update(
            {
                SortRole: b"sortValue",
                SearchTextRole: b"searchText",
                TrackIdRole: b"trackId",
                ColumnKeyRole: b"columnKey",
                RawValueRole: b"rawValue",
            }
        )
        return role_names


__all__ = ["CatalogTableModel"]

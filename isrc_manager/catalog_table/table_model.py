"""Dormant `QAbstractTableModel` seam for the staged catalog-table migration."""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, Qt

from .models import CatalogColumnSpec, CatalogSnapshot


class CatalogTableModel(QAbstractTableModel):
    """Snapshot-aware table-model scaffold kept intentionally inert in Phase A1."""

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
        # Phase A1 keeps the model structurally real but intentionally dormant.
        # A2 will expose CatalogCellValue fields through Qt roles.
        return None

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = int(Qt.ItemDataRole.DisplayRole),
    ):
        if orientation != Qt.Orientation.Horizontal:
            return None
        if role != int(Qt.ItemDataRole.DisplayRole):
            return None
        spec = self.column_spec(section)
        return spec.header_text if spec is not None else None

    def set_snapshot(self, snapshot: CatalogSnapshot | None) -> None:
        """Store the future source snapshot without wiring in live behavior yet."""

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
        return {
            row.track_id: source_row
            for source_row, row in enumerate(snapshot.rows)
        }


__all__ = ["CatalogTableModel"]

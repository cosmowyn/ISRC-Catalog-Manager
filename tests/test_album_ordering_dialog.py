from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtWidgets import QAbstractItemView, QTableWidgetItem, QWidget

from isrc_manager.services import TrackSnapshot
from isrc_manager.tracks.album_ordering_dialog import (
    AlbumTrackOrderingDialog,
    _AlbumTrackOrderingTable,
)
from tests.qt_test_helpers import require_qapplication


def _snapshot(track_id: int, title: str, artist: str = "Artist") -> TrackSnapshot:
    return TrackSnapshot(
        track_id=track_id,
        db_entry_date=None,
        isrc=f"NL-TST-26-{track_id:05d}",
        track_title=title,
        artist_name=artist,
        additional_artists=[],
        album_title="Album",
        release_date=None,
        track_length_sec=180,
        iswc=None,
        upc=None,
        genre=None,
        catalog_number=None,
        buma_work_number=None,
        composer=None,
        publisher=None,
        comments=None,
        lyrics=None,
    )


def _populate_table(table: _AlbumTrackOrderingTable) -> None:
    for row, track_id in enumerate((1, 2, 3)):
        table.insertRow(row)
        item = QTableWidgetItem(str(row + 1))
        item.setData(Qt.UserRole, track_id)
        table.setItem(row, 0, item)
        table.setItem(row, 1, QTableWidgetItem(f"Track {track_id}"))
        table.setItem(row, 2, QTableWidgetItem("Artist"))
        table.setItem(row, 3, QTableWidgetItem(f"ISRC-{track_id}"))


def test_album_ordering_table_moves_rows_and_emits_order_changed() -> None:
    require_qapplication()
    table = _AlbumTrackOrderingTable()
    _populate_table(table)
    changed: list[None] = []
    table.orderChanged.connect(lambda: changed.append(None))

    assert table.move_current_row(1) is None

    table.selectRow(0)
    table.setCurrentCell(0, 0)
    assert table.move_current_row(-1) is None
    assert table.move_current_row(1) == 1

    assert [table.item(row, 0).data(Qt.UserRole) for row in range(3)] == [2, 1, 3]
    assert table.currentRow() == 1
    assert len(changed) == 1
    assert table._move_row(99, 0) is None
    assert table._move_row(1, 1) is None


def test_album_ordering_table_drag_drop_helpers_handle_bounds_and_external_events() -> None:
    require_qapplication()
    table = _AlbumTrackOrderingTable()
    _populate_table(table)

    external_event = SimpleNamespace(
        source=lambda: QWidget(),
        ignore=lambda: setattr(external_event, "ignored", True),
    )
    table.dragEnterEvent(external_event)
    assert external_event.ignored is True

    accepted: list[str] = []
    internal_event = SimpleNamespace(
        source=lambda: table,
        setDropAction=lambda action: accepted.append(f"drop:{action.name}"),
        accept=lambda: accepted.append("accept"),
        acceptProposedAction=lambda: accepted.append("accept-proposed"),
    )
    table.dragMoveEvent(internal_event)
    assert "accept" in accepted

    position_event = SimpleNamespace(position=lambda: QPointF(1, 10))
    fallback_event = SimpleNamespace(pos=lambda: QPoint(1, 10))
    table.dropIndicatorPosition = lambda: QAbstractItemView.AboveItem
    assert table._drop_row_for_event(1, position_event) >= 0
    table.dropIndicatorPosition = lambda: QAbstractItemView.BelowItem
    assert table._drop_row_for_event(0, fallback_event) >= 0


def test_album_track_ordering_dialog_reports_ids_and_button_states() -> None:
    require_qapplication()
    parent = QWidget()
    dialog = AlbumTrackOrderingDialog(
        parent,
        album_title="Album",
        snapshots=[_snapshot(1, "One"), _snapshot(2, "Two"), _snapshot(3, "Three")],
        parent=parent,
    )

    assert dialog.ordered_track_ids() == [1, 2, 3]
    assert not dialog.move_up_button.isEnabled()
    assert dialog.move_down_button.isEnabled()

    dialog._move_selected_row(1)
    assert dialog.ordered_track_ids() == [2, 1, 3]
    assert dialog.move_up_button.isEnabled()
    assert dialog.move_down_button.isEnabled()

    dialog.table.selectRow(2)
    dialog.table.setCurrentCell(2, 0)
    dialog._update_button_states()
    assert dialog.move_up_button.isEnabled()
    assert not dialog.move_down_button.isEnabled()

    dialog.table.item(1, 0).setData(Qt.UserRole, "not-an-int")
    assert dialog.ordered_track_ids() == [2, 3]


def test_album_track_ordering_dialog_handles_empty_album() -> None:
    require_qapplication()
    parent = QWidget()
    dialog = AlbumTrackOrderingDialog(parent, album_title="", snapshots=[], parent=parent)

    assert dialog.ordered_track_ids() == []
    assert not dialog.move_up_button.isEnabled()
    assert not dialog.move_down_button.isEnabled()

import unittest
from unittest import mock

from tests.qt_test_helpers import require_qapplication

try:

    from isrc_manager.exchange.repair_dialogs import (
        TrackImportRepairEntryDialog,
        TrackImportRepairQueueDialog,
    )
    from isrc_manager.services.import_repair_queue import TrackImportRepairEntry
except Exception as exc:  # pragma: no cover - environment-specific fallback
    REPAIR_DIALOG_IMPORT_ERROR = exc
else:
    REPAIR_DIALOG_IMPORT_ERROR = None


def _track_import_repair_entry(row_id: int) -> TrackImportRepairEntry:
    return TrackImportRepairEntry(
        id=row_id,
        source_format="csv",
        source_path="/tmp/import.csv",
        row_index=row_id,
        import_mode="create",
        normalized_row={
            "track_title": "Morning Light",
            "artist_name": "Bluebird",
            "custom::Mood": "chill",
            "custom::Artwork": "",
            "release_date": "2024-01-02",
            999: "ignored-key",
            "custom::Notes": "none",
        },
        mapping={"track_title": "track_title"},
        options={"mode": "append"},
        failure_category="validation",
        failure_message=f"Row {row_id} was malformed",
        status="pending",
        created_at=None,
        updated_at=None,
        resolved_at=None,
        resolved_track_id=None,
        resolved_work_id=None,
    )


class _RepairDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if REPAIR_DIALOG_IMPORT_ERROR is not None:
            raise unittest.SkipTest(
                f"Exchange repair dialog modules unavailable: {REPAIR_DIALOG_IMPORT_ERROR}"
            )
        cls.app = require_qapplication()

    def test_entry_dialog_orders_fields_and_populates_table_rows(self):
        entry = _track_import_repair_entry(11)
        dialog = TrackImportRepairEntryDialog(
            entry=entry, work_choices=[(7, "Existing Master"), (3, "Alternate")]
        )
        try:
            self.assertGreater(dialog.field_table.rowCount(), 0)
            fields = [
                dialog.field_table.item(row, 0).text()
                for row in range(dialog.field_table.rowCount())
            ]
            self.assertEqual(fields[0], "track_title")
            self.assertEqual(fields[1], "artist_name")
            self.assertIn("release_date", fields)
            self.assertEqual(fields[2], "release_date")
            self.assertEqual(fields[3], "custom::Artwork")
            self.assertEqual(fields[4], "custom::Mood")
            self.assertEqual(
                fields,
                [
                    "track_title",
                    "artist_name",
                    "release_date",
                    "custom::Artwork",
                    "custom::Mood",
                    "custom::Notes",
                    "999",
                ],
            )

            edited = dialog.edited_row()
            self.assertEqual(edited["track_title"], "Morning Light")
            self.assertEqual(edited["custom::Mood"], "chill")
        finally:
            dialog.close()

    def test_entry_dialog_validate_link_existing_requires_work_choice(self):
        entry = _track_import_repair_entry(12)
        dialog = TrackImportRepairEntryDialog(entry=entry, work_choices=[(7, "Existing Master")])
        try:
            link_index = dialog.governance_combo.findData("link_existing_work")
            self.assertNotEqual(link_index, -1)
            dialog.governance_combo.setCurrentIndex(link_index)
            dialog.work_combo.setCurrentIndex(0)

            with mock.patch("isrc_manager.exchange.repair_dialogs.QMessageBox.information") as info:
                dialog._accept_with_validation()
                info.assert_called_once()

            dialog.work_combo.setCurrentIndex(dialog.work_combo.findData(7))
            with mock.patch.object(dialog, "accept") as accept:
                dialog._accept_with_validation()
                accept.assert_called_once()
        finally:
            dialog.close()

    def test_entry_dialog_repair_override_returns_governance_and_work(self):
        entry = _track_import_repair_entry(13)
        dialog = TrackImportRepairEntryDialog(entry=entry, work_choices=[(11, "Alternate Work")])
        try:
            dialog.governance_combo.setCurrentIndex(
                dialog.governance_combo.findData("link_existing_work")
            )
            dialog.work_combo.setCurrentIndex(dialog.work_combo.findData(11))
            self.assertEqual(
                dialog.repair_override(), {"governance_mode": "link_existing_work", "work_id": 11}
            )

            dialog.governance_combo.setCurrentIndex(
                dialog.governance_combo.findData("create_new_work")
            )
            dialog.work_combo.setCurrentIndex(dialog.work_combo.findData(None))
            self.assertEqual(
                dialog.repair_override(), {"governance_mode": "create_new_work", "work_id": None}
            )
        finally:
            dialog.close()

    def test_entry_dialog_refreshes_governance_state(self):
        entry = _track_import_repair_entry(14)
        dialog = TrackImportRepairEntryDialog(entry=entry, work_choices=[])
        try:
            dialog.governance_combo.setCurrentIndex(
                dialog.governance_combo.findData("create_new_work")
            )
            dialog._refresh_governance_state()
            self.assertFalse(dialog.work_combo.isEnabled())

            dialog.governance_combo.setCurrentIndex(
                dialog.governance_combo.findData("link_existing_work")
            )
            dialog._refresh_governance_state()
            self.assertTrue(dialog.work_combo.isEnabled())
        finally:
            dialog.close()


class _RepairQueueDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if REPAIR_DIALOG_IMPORT_ERROR is not None:
            raise unittest.SkipTest(
                f"Exchange repair dialog modules unavailable: {REPAIR_DIALOG_IMPORT_ERROR}"
            )
        cls.app = require_qapplication()

    def test_queue_dialog_refreshes_and_selects_rows(self):
        entries = [_track_import_repair_entry(1), _track_import_repair_entry(2)]
        dialog = TrackImportRepairQueueDialog(
            entries_provider=lambda *_args, **_kwargs: entries,
            repair_selected_handler=lambda _entry_id: None,
            delete_selected_handler=lambda *_ids: None,
        )
        try:
            self.assertEqual(dialog.table.rowCount(), len(entries))
            with mock.patch("isrc_manager.exchange.repair_dialogs.QMessageBox.information") as info:
                dialog._repair_selected()
                info.assert_called_once()

            dialog.table.selectRow(dialog.table.rowCount() - 1)
            self.assertEqual(dialog.selected_entry_id(), 2)
            with mock.patch("isrc_manager.exchange.repair_dialogs.QMessageBox.information") as info:
                dialog._repair_selected()
                info.assert_not_called()
        finally:
            dialog.close()

    def test_queue_dialog_refresh_selected_behavior_calls_handlers(self):
        entries = [_track_import_repair_entry(21)]
        repair_called: list[int] = []
        delete_called: list[list[int]] = []
        dialog = TrackImportRepairQueueDialog(
            entries_provider=lambda *_args, **_kwargs: entries,
            repair_selected_handler=lambda entry_id: repair_called.append(int(entry_id)),
            delete_selected_handler=lambda entry_ids: delete_called.append(list(entry_ids)),
        )
        try:
            dialog.table.selectRow(0)
            dialog._repair_selected()
            self.assertEqual(repair_called, [21])

            dialog._delete_selected()
            self.assertEqual(delete_called, [[21]])
        finally:
            dialog.close()

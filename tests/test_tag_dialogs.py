import unittest
from unittest import mock

try:
    from PySide6.QtWidgets import QApplication
except ImportError as exc:  # pragma: no cover - environment-specific fallback
    QApplication = None
    QT_IMPORT_ERROR = exc
else:
    QT_IMPORT_ERROR = None

from isrc_manager.file_storage import STORAGE_MODE_DATABASE, STORAGE_MODE_MANAGED_FILE
from isrc_manager.tags.dialogs import BulkAudioAttachDialog, TagPreviewDialog


class TagDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if QApplication is None:
            raise unittest.SkipTest(f"PySide6 QtWidgets unavailable: {QT_IMPORT_ERROR}")
        cls.app = QApplication.instance() or QApplication([])

    def test_tag_preview_dialog_uses_themed_panel_root(self):
        dialog = TagPreviewDialog(
            title="Review Tags",
            intro="Compare database and file tags before continuing.",
            rows=[
                {
                    "track": "Orbit",
                    "field": "genre",
                    "database": "Ambient",
                    "file": "Electronica",
                    "chosen": "Ambient",
                    "source": "/tmp/orbit.wav",
                }
            ],
        )
        try:
            self.assertEqual(dialog.property("role"), "panel")
            self.assertEqual(dialog.table.rowCount(), 1)
            self.assertEqual(dialog.selected_policy(), "merge_blanks")
        finally:
            dialog.close()

    def test_bulk_audio_attach_dialog_tracks_manual_reassignment_and_artist_choice(self):
        dialog = BulkAudioAttachDialog(
            title="Bulk Attach Audio Files",
            intro="Review filename matches before attaching.",
            items=[
                {
                    "source_path": "/tmp/orbit.mp3",
                    "source_name": "orbit.mp3",
                    "detected_title": "Orbit",
                    "detected_artist": "Artist One",
                    "matched_track_id": 1,
                    "matched_track_artist": "Artist One",
                    "match_basis": "Filename + artist",
                    "status": "matched",
                    "warning": "Lossy primary audio selected (MP3).",
                },
                {
                    "source_path": "/tmp/aurora.wav",
                    "source_name": "aurora.wav",
                    "detected_title": "Aurora",
                    "detected_artist": "Artist One",
                    "matched_track_id": None,
                    "matched_track_artist": "",
                    "match_basis": "No confident catalog match",
                    "status": "unmatched",
                    "warning": "",
                },
            ],
            track_choices=[
                (1, "1 - Orbit / Artist One", "Artist One"),
                (2, "2 - Aurora / Artist One", "Artist One"),
            ],
            suggested_artist="Artist One",
            allow_create_track=True,
        )
        try:
            self.assertEqual(len(dialog.selected_matches()), 1)
            self.assertEqual(dialog.selected_artist_name(), "Artist One")
            self.assertEqual(dialog.selected_storage_mode(), STORAGE_MODE_MANAGED_FILE)
            dialog.storage_combo.setCurrentIndex(
                dialog.storage_combo.findData(STORAGE_MODE_DATABASE)
            )
            self.assertEqual(dialog.selected_storage_mode(), STORAGE_MODE_DATABASE)
            self.assertEqual(dialog.table.columnCount(), 6)
            self.assertEqual(dialog.table.item(0, 4).text(), "Lossy primary audio selected (MP3).")
            self.assertEqual(dialog.table.item(0, 3).text(), "1 - Orbit / Artist One")
            dialog._match_combos[1].setCurrentIndex(dialog._match_combos[1].findData(2))
            self.assertEqual([item["track_id"] for item in dialog.selected_matches()], [1, 2])
            self.assertIn("2 of 2", dialog.summary_label.text())
            self.assertNotIn("still needs a target", dialog.summary_label.text())
            dialog._request_create_track()
            self.assertTrue(dialog.create_track_requested())
        finally:
            dialog.close()

    def test_bulk_audio_attach_dialog_blocks_duplicate_track_assignments(self):
        dialog = BulkAudioAttachDialog(
            title="Bulk Attach Audio Files",
            intro="Review filename matches before attaching.",
            items=[
                {
                    "source_path": "/tmp/orbit.wav",
                    "source_name": "orbit.wav",
                    "detected_title": "Orbit",
                    "detected_artist": None,
                    "matched_track_id": 1,
                    "matched_track_artist": "Artist One",
                    "match_basis": "Filename",
                    "status": "matched",
                    "warning": "",
                },
                {
                    "source_path": "/tmp/orbit-live.wav",
                    "source_name": "orbit-live.wav",
                    "detected_title": "Orbit Live",
                    "detected_artist": None,
                    "matched_track_id": None,
                    "matched_track_artist": "",
                    "match_basis": "No confident catalog match",
                    "status": "unmatched",
                    "warning": "",
                },
            ],
            track_choices=[(1, "1 - Orbit / Artist One", "Artist One")],
        )
        try:
            dialog._match_combos[1].setCurrentIndex(dialog._match_combos[1].findData(1))
            with mock.patch("isrc_manager.tags.dialogs.QMessageBox.warning") as warning_mock:
                dialog.accept()
            warning_mock.assert_called_once()
        finally:
            dialog.close()


if __name__ == "__main__":
    unittest.main()

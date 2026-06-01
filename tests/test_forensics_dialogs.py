import unittest

from PySide6.QtWidgets import QTextEdit

from isrc_manager.forensics.dialogs import ForensicExportDialog, ForensicInspectionDialog
from isrc_manager.forensics.models import ForensicInspectionReport
from tests.qt_test_helpers import require_qapplication


class ForensicsDialogsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = require_qapplication()

    def test_export_dialog_returns_selected_fields_and_optional_inputs(self):
        dialog = ForensicExportDialog(
            format_labels=[("mp3", "MP3"), ("ogg", "Ogg Vorbis")],
            parent=None,
        )
        try:
            dialog.format_combo.setCurrentIndex(0)
            self.assertEqual(dialog.selected_format_id(), "mp3")

            dialog.recipient_edit.setText("  Team Alpha  ")
            dialog.share_edit.setText("  Campaign 123  ")
            self.assertEqual(dialog.recipient_label(), "Team Alpha")
            self.assertEqual(dialog.share_label(), "Campaign 123")
        finally:
            dialog.close()

    def test_export_dialog_handles_missing_optional_labels(self):
        dialog = ForensicExportDialog(
            format_labels=[("wav", "WAV")],
            parent=None,
        )
        try:
            dialog.format_combo.setCurrentIndex(0)
            self.assertEqual(dialog.selected_format_id(), "wav")
            dialog.recipient_edit.setText("\n\t  ")
            dialog.share_edit.setText("")
            self.assertIsNone(dialog.recipient_label())
            self.assertIsNone(dialog.share_label())
        finally:
            dialog.close()

    def test_export_dialog_can_fix_recipient_for_soundcloud_workflow(self):
        dialog = ForensicExportDialog(
            format_labels=[("wav", "WAV")],
            fixed_recipient_label="SoundCloud",
            share_label_caption="SoundCloud Label",
            share_label_placeholder="Optional upload label",
            parent=None,
        )
        try:
            self.assertTrue(dialog.recipient_edit.isReadOnly())
            dialog.recipient_edit.setText("Edited")
            dialog.share_edit.setText("  Public upload  ")
            self.assertEqual(dialog.recipient_label(), "SoundCloud")
            self.assertEqual(dialog.share_label(), "Public upload")
        finally:
            dialog.close()

    def test_inspection_dialog_formats_optional_fields_and_confidence(self):
        report = ForensicInspectionReport(
            status="ok",
            message="Verified",
            inspected_path="/tmp/audio.wav",
            forensic_export_id="exp-1",
            batch_id="batch-1",
            derivative_export_id="deriv-1",
            track_id=12,
            recipient_label="Acme",
            share_label="release",
            output_format="mp3",
            token_id=77,
            exact_hash_match=True,
            confidence_score=0.9876,
            resolution_basis="match-basis",
            details=["Signature found", "Hash match"],
        )
        dialog = ForensicInspectionDialog(report=report, parent=None)
        try:
            text_areas = dialog.findChildren(QTextEdit)
            text = text_areas[0].toPlainText()
            self.assertIn("Forensic Export ID: exp-1", text)
            self.assertIn("Track ID: 12", text)
            self.assertIn("Recipient: Acme", text)
            self.assertIn("Exact Hash Match: True", text)
            self.assertIn("Confidence: 0.988", text)
            self.assertIn("Resolution Basis: match-basis", text)
            self.assertIn("Details:", text)
        finally:
            dialog.close()

    def test_inspection_dialog_handles_minimal_report(self):
        report = ForensicInspectionReport(
            status="missing",
            message="No watermark",
            inspected_path="/tmp/original.wav",
        )
        dialog = ForensicInspectionDialog(report=report, parent=None)
        try:
            text_areas = dialog.findChildren(QTextEdit)
            text = text_areas[0].toPlainText()
            self.assertIn("Status: missing", text)
            self.assertIn("Message: No watermark", text)
            self.assertIn("Path: /tmp/original.wav", text)
            self.assertNotIn("Forensic Export ID", text)
            self.assertNotIn("Details:", text)
        finally:
            dialog.close()


if __name__ == "__main__":
    unittest.main()

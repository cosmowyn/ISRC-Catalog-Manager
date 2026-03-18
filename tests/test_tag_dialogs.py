import unittest

try:
    from PySide6.QtWidgets import QApplication
except ImportError as exc:  # pragma: no cover - environment-specific fallback
    QApplication = None
    QT_IMPORT_ERROR = exc
else:
    QT_IMPORT_ERROR = None

from isrc_manager.tags.dialogs import TagPreviewDialog


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


if __name__ == "__main__":
    unittest.main()

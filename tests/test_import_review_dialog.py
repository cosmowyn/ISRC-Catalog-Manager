import unittest

from PySide6.QtWidgets import QDialog, QPushButton, QTableWidget, QTabWidget

from isrc_manager.import_review_dialog import ImportReviewDialog
from tests.qt_test_helpers import require_qapplication


class ImportReviewDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = require_qapplication()

    def test_dialog_renders_warnings_and_preview_with_inferred_headers(self):
        dialog = ImportReviewDialog(
            title="Review exchange import",
            subtitle="Inspect rows before applying",
            summary_lines=["Rows ready: 1", "", "  "],
            warnings=["", "Missing album", " Duplicate ISRC "],
            preview_title="Rows",
            preview_rows=[
                {"ISRC": "AA6Q72000001", "Title": None},
                {"Title": "Second title", "Artist": "Artist A"},
            ],
            confirm_label="Apply",
        )
        self.addCleanup(dialog.deleteLater)

        tabs = dialog.findChild(QTabWidget, "importReviewTabs")
        self.assertIsNotNone(tabs)
        self.assertEqual(tabs.count(), 2)
        self.assertEqual(tabs.tabText(1), "Rows")

        tables = dialog.findChildren(QTableWidget)
        warning_table = next(table for table in tables if table.columnCount() == 1)
        preview_table = next(table for table in tables if table.columnCount() == 3)
        self.assertEqual(warning_table.rowCount(), 2)
        self.assertEqual(warning_table.item(0, 0).text(), "Missing album")
        self.assertEqual(warning_table.item(1, 0).toolTip(), "Duplicate ISRC")
        self.assertEqual(preview_table.columnCount(), 3)
        self.assertEqual(
            [preview_table.horizontalHeaderItem(index).text() for index in range(3)],
            ["ISRC", "Title", "Artist"],
        )
        self.assertEqual(preview_table.item(0, 1).text(), "")
        self.assertEqual(preview_table.item(1, 2).text(), "Artist A")

        buttons = {button.text(): button for button in dialog.findChildren(QPushButton)}
        buttons["Apply"].click()
        self.assertEqual(dialog.result(), QDialog.Accepted)

    def test_dialog_without_warnings_or_preview_uses_review_only_and_rejects(self):
        dialog = ImportReviewDialog(
            title="Review import",
            subtitle="No preview",
            summary_lines=["Rows ready: 0"],
            warnings=[],
            preview_rows=[],
        )
        self.addCleanup(dialog.deleteLater)

        tabs = dialog.findChild(QTabWidget, "importReviewTabs")
        self.assertIsNotNone(tabs)
        self.assertEqual(tabs.count(), 1)
        self.assertEqual(dialog.findChildren(QTableWidget), [])

        buttons = {button.text(): button for button in dialog.findChildren(QPushButton)}
        buttons["Cancel"].click()
        self.assertEqual(dialog.result(), QDialog.Rejected)


if __name__ == "__main__":
    unittest.main()

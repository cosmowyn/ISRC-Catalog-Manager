import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QDialog, QWidget
except ImportError as exc:  # pragma: no cover - environment-specific fallback
    Qt = None
    QApplication = None
    QDialog = None
    QWidget = None
    QT_IMPORT_ERROR = exc
else:
    QT_IMPORT_ERROR = None

from isrc_manager.app_dialogs import ActionRibbonDialog, CustomColumnsDialog, HelpContentsDialog
from isrc_manager.help_content import HELP_CHAPTERS_BY_ID, render_help_html


class _HelpDialogHost(QWidget):
    def __init__(self, help_path: Path):
        super().__init__()
        self._help_path = help_path
        self.opened_paths = []

    def _ensure_help_file(self) -> Path:
        return self._help_path

    def _help_html(self) -> str:
        return render_help_html("ISRC Catalog Manager", "test")

    def _open_local_path(self, path, _title):
        self.opened_paths.append(Path(path))


class AppDialogsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if QApplication is None:
            raise unittest.SkipTest(f"PySide6 QtWidgets unavailable: {QT_IMPORT_ERROR}")
        cls.app = QApplication.instance() or QApplication([])

    def test_action_ribbon_dialog_updates_selected_actions(self):
        dialog = ActionRibbonDialog(
            [
                {"id": "import", "label": "Import", "category": "File", "default": True},
                {"id": "export", "label": "Export", "category": "File"},
                {"id": "search", "label": "Search", "category": "Tools"},
            ],
            ["import"],
            ribbon_visible=True,
        )
        try:
            self.assertEqual(dialog.selected_action_ids(), ["import"])
            dialog.available_list.setCurrentRow(1)
            dialog._add_current_available_action()
            self.assertEqual(dialog.selected_action_ids(), ["import", "export"])

            dialog.selected_list.setCurrentRow(1)
            dialog._move_selected_action(-1)
            self.assertEqual(dialog.selected_action_ids(), ["export", "import"])

            dialog.show_ribbon_checkbox.setChecked(False)
            self.assertFalse(dialog.ribbon_visible())
        finally:
            dialog.close()

    def test_custom_columns_dialog_copies_field_definitions(self):
        fields = [
            {"id": 1, "name": "Mood", "field_type": "dropdown", "options": '["Warm"]'},
        ]
        dialog = CustomColumnsDialog(fields)
        try:
            dialog.fields[0]["name"] = "Energy"
            self.assertEqual(fields[0]["name"], "Mood")
            self.assertEqual(dialog.get_fields()[0]["name"], "Energy")
        finally:
            dialog.close()

    def test_custom_columns_dialog_enables_blob_icon_overrides_for_blob_fields(self):
        fields = [
            {
                "id": 2,
                "name": "Artwork",
                "field_type": "blob_image",
                "options": None,
                "blob_icon_payload": {"mode": "inherit"},
            }
        ]
        dialog = CustomColumnsDialog(fields)
        try:
            dialog.listw.setCurrentRow(0)
            self.assertTrue(dialog.btn_blob_icon.isEnabled())
            with (
                mock.patch(
                    "isrc_manager.app_dialogs.BlobIconDialog.exec", return_value=QDialog.Accepted
                ),
                mock.patch(
                    "isrc_manager.app_dialogs.BlobIconDialog.current_spec",
                    return_value={"mode": "emoji", "emoji": "🖼️"},
                ),
            ):
                dialog._edit_blob_icon()
            self.assertEqual(dialog.get_fields()[0]["blob_icon_payload"]["emoji"], "🖼️")
        finally:
            dialog.close()

    def test_help_contents_dialog_filters_and_opens_topics(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            help_path = Path(tmpdir) / "help.html"
            help_path.write_text(
                render_help_html("ISRC Catalog Manager", "test"),
                encoding="utf-8",
            )
            host = _HelpDialogHost(help_path)
            dialog = HelpContentsDialog(host)
            try:
                dialog.open_topic("repertoire-knowledge")
                self.assertEqual(dialog._current_topic_id, "repertoire-knowledge")
                self.assertEqual(
                    dialog.match_status_label.text(),
                    HELP_CHAPTERS_BY_ID["repertoire-knowledge"].summary,
                )

                dialog._filter_chapters("contract")
                self.assertGreater(dialog.chapter_list.count(), 0)
                chapter_ids = {
                    str(dialog.chapter_list.item(row).data(Qt.UserRole))
                    for row in range(dialog.chapter_list.count())
                }
                self.assertIn("repertoire-knowledge", chapter_ids)

                dialog._open_help_file()
                self.assertEqual(host.opened_paths, [help_path])
            finally:
                dialog.close()
                host.close()


if __name__ == "__main__":
    unittest.main()

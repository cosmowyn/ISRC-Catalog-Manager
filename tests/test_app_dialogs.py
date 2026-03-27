import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (
        QApplication,
        QDialog,
        QMessageBox,
        QTabWidget,
        QVBoxLayout,
        QWidget,
    )
except ImportError as exc:  # pragma: no cover - environment-specific fallback
    Qt = None
    QApplication = None
    QDialog = None
    QMessageBox = None
    QTabWidget = None
    QVBoxLayout = None
    QWidget = None
    QT_IMPORT_ERROR = exc
else:
    QT_IMPORT_ERROR = None

from isrc_manager.app_dialogs import (
    ActionRibbonDialog,
    CustomColumnsDialog,
    DiagnosticsDialog,
    HelpContentsDialog,
)
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


class _DiagnosticsDialogHost(QWidget):
    def __init__(self):
        super().__init__()
        self.logs_dir = Path("/tmp/test-logs")
        self.data_root = Path("/tmp/test-data")
        self.opened_paths = []
        self.load_calls = 0
        self.repair_calls = []
        self.history_cleanup_open_count = 0
        self.background_errors = []
        self._report = {
            "environment": {
                "App version": "3.1.0",
                "Schema version": "77",
                "Current profile": "catalog.db",
                "Database path": "/tmp/catalog.db",
                "Data folder": str(self.data_root),
                "Log folder": str(self.logs_dir),
                "Restore points": "2 snapshot(s), latest: Snapshot @ now",
                "Platform": "TestOS",
                "Python": "3.12.0",
            },
            "checks": [
                {
                    "title": "Schema layout",
                    "status": "warning",
                    "summary": "Missing promoted columns.",
                    "details": "Tracks is missing one promoted column.",
                    "repair_key": "schema_migrate",
                    "repair_label": "Repair Schema Layout",
                }
            ],
            "history_storage_budget": {
                "available": True,
                "usage_text": "1.8 GB",
                "budget_text": "1.0 GB",
                "over_budget_text": "820.0 MB",
                "reclaimable_text": "512.0 MB",
                "retention_mode_label": "Balanced",
                "auto_cleanup_text": "Enabled",
                "candidate_count": 3,
                "summary": (
                    "History storage is using 1.8 GB of a 1.0 GB budget "
                    "and is over budget by 820.0 MB."
                ),
                "within_budget": False,
            },
        }

    def _create_diagnostics_catalog_cleanup_panel(self, parent):
        panel = QWidget(parent)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        tabs = QTabWidget(panel)
        artists_tab = QWidget(tabs)
        albums_tab = QWidget(tabs)
        tabs.addTab(artists_tab, "Artists")
        tabs.addTab(albums_tab, "Albums")
        layout.addWidget(tabs)
        panel.tabs = tabs
        panel.artists_tab = artists_tab
        panel.albums_tab = albums_tab
        panel._refresh_calls = 0

        def _focus_tab(tab_name="artists"):
            tabs.setCurrentWidget(albums_tab if tab_name == "albums" else artists_tab)

        def _refresh():
            panel._refresh_calls += 1

        panel.focus_tab = _focus_tab
        panel.refresh = _refresh
        return panel

    def _load_diagnostics_report_async(
        self,
        *,
        owner=None,
        on_success=None,
        on_error=None,
        on_cancelled=None,
        on_finished=None,
        on_status=None,
    ):
        del owner, on_error, on_cancelled
        self.load_calls += 1
        if on_status is not None:
            on_status("Inspecting schema layout...")
        if on_success is not None:
            on_success(self._report)
        if on_finished is not None:
            on_finished()
        return f"load-{self.load_calls}"

    def _preview_diagnostics_repair(self, repair_key, check=None):
        del check
        return f"Preview for {repair_key}"

    def _run_diagnostics_repair_async(
        self,
        repair_key,
        check=None,
        *,
        owner=None,
        on_success=None,
        on_error=None,
        on_cancelled=None,
        on_finished=None,
        on_status=None,
    ):
        del check, owner, on_error, on_cancelled
        self.repair_calls.append(repair_key)
        if on_status is not None:
            on_status("Applying repair...")
        if on_success is not None:
            on_success("Schema bootstrap and migration completed successfully.")
        if on_finished is not None:
            on_finished()
        return f"repair-{len(self.repair_calls)}"

    def _show_background_task_error(self, title, failure, *, user_message):
        self.background_errors.append(
            (title, user_message, getattr(failure, "message", str(failure)))
        )

    def _open_local_path(self, path, _title):
        self.opened_paths.append(Path(path))
        return True

    def open_history_cleanup_dialog(self):
        self.history_cleanup_open_count += 1


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

    def test_diagnostics_dialog_uses_async_loader(self):
        host = _DiagnosticsDialogHost()
        dialog = DiagnosticsDialog(host)
        try:
            self.assertEqual(host.load_calls, 1)
            self.assertFalse(dialog.loading_panel.isVisible())
            self.assertEqual(
                [
                    dialog.surface_tabs.tabText(index)
                    for index in range(dialog.surface_tabs.count())
                ],
                ["Health", "Catalog Cleanup"],
            )
            self.assertIsNotNone(dialog.body_scroll.widget())
            self.assertEqual(dialog.environment_labels["App version"].text(), "3.1.0")
            self.assertIn("1.8 GB", dialog.history_storage_summary_label.text())
            self.assertEqual(dialog.history_storage_metric_labels["budget"].text(), "1.0 GB")
            self.assertEqual(
                dialog.history_storage_metric_labels["over_budget"].text(),
                "820.0 MB",
            )
            self.assertTrue(dialog.open_cleanup_button.isEnabled())
            self.assertEqual(dialog.checks_list.count(), 1)
            self.assertIn("Schema layout", dialog.details_edit.toPlainText())
            self.assertTrue(dialog.repair_button.isEnabled())
            self.assertEqual(dialog.repair_button.text(), "Repair Schema Layout")
            self.assertEqual(dialog.catalog_cleanup_panel._refresh_calls, 1)
            dialog.open_cleanup_button.click()
            self.assertEqual(host.history_cleanup_open_count, 1)
        finally:
            dialog.close()
            host.close()

    def test_diagnostics_dialog_can_focus_catalog_cleanup_tabs(self):
        host = _DiagnosticsDialogHost()
        dialog = DiagnosticsDialog(host)
        try:
            cleanup_panel = dialog.catalog_cleanup_panel
            self.assertIsNotNone(cleanup_panel)
            assert cleanup_panel is not None
            dialog.focus_cleanup_tab("albums")
            self.assertIs(dialog.surface_tabs.currentWidget(), cleanup_panel)
            self.assertIs(cleanup_panel.tabs.currentWidget(), cleanup_panel.albums_tab)
        finally:
            dialog.close()
            host.close()

    def test_diagnostics_dialog_runs_async_repair(self):
        host = _DiagnosticsDialogHost()
        dialog = DiagnosticsDialog(host)
        try:
            with (
                mock.patch(
                    "isrc_manager.app_dialogs.QMessageBox.question",
                    return_value=QMessageBox.Yes,
                ),
                mock.patch("isrc_manager.app_dialogs.QMessageBox.information") as info_mock,
            ):
                dialog._run_selected_repair()

            self.assertEqual(host.repair_calls, ["schema_migrate"])
            self.assertEqual(host.load_calls, 2)
            info_mock.assert_called_once()
        finally:
            dialog.close()
            host.close()

    def test_diagnostics_dialog_loading_strip_scales_with_window_width(self):
        host = _DiagnosticsDialogHost()
        dialog = DiagnosticsDialog(host)
        try:
            dialog.show()
            self.app.processEvents()
            dialog.resize(980, 680)
            dialog._set_busy(True, "Loading diagnostics with a longer status message.")
            self.app.processEvents()

            dialog.resize(1280, 820)
            self.app.processEvents()

            self.assertGreaterEqual(dialog.loading_bar.width(), 220)
            self.assertLessEqual(dialog.loading_bar.width(), 320)
            self.assertGreaterEqual(dialog.loading_status_label.minimumWidth(), 260)
        finally:
            dialog.close()
            host.close()


if __name__ == "__main__":
    unittest.main()

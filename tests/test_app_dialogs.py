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
    ApplicationStorageAdminDialog,
    CustomColumnsDialog,
    DiagnosticsDialog,
    HelpContentsDialog,
    MasterTransferExportDialog,
)
from isrc_manager.help_content import HELP_CHAPTERS_BY_ID, render_help_html
from isrc_manager.tasks.models import TaskProgressUpdate


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
        self.application_storage_admin_open_count = 0
        self.storage_audit_load_calls = 0
        self.storage_cleanup_calls = []
        self.background_errors = []
        self.progress_updates = []
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
            "application_storage": {
                "available": True,
                "summary": (
                    "The application is using 3.2 GB in 12 tracked storage item(s). "
                    "5 item(s) appear reclaimable now, covering 1.1 GB."
                ),
                "total_text": "3.2 GB",
                "current_profile_text": "1.4 GB",
                "reclaimable_text": "1.1 GB",
                "deleted_profile_text": "512.0 MB",
                "orphaned_text": "420.0 MB",
                "warning_text": "640.0 MB",
            },
        }
        self._storage_audit_payload = {
            "summary": {
                "summary": (
                    "The application is using 3.2 GB in 12 tracked storage item(s). "
                    "5 item(s) appear reclaimable now, covering 1.1 GB."
                ),
                "total_text": "3.2 GB",
                "current_profile_text": "1.4 GB",
                "reclaimable_text": "1.1 GB",
                "deleted_profile_text": "512.0 MB",
                "orphaned_text": "420.0 MB",
                "warning_text": "640.0 MB",
            },
            "items": [
                {
                    "item_key": "orphan-file",
                    "status_label": "Orphaned / Unreferenced",
                    "category_label": "Track / Album Media",
                    "label": "orphan_audio.wav",
                    "size_text": "420.0 MB",
                    "bytes_on_disk": 420 * 1024 * 1024,
                    "profile_name": "",
                    "path": "/tmp/test-data/track_media/orphan_audio.wav",
                    "reason": "No active profile references this application-managed file.",
                    "warning_required": False,
                    "warning": "",
                    "references_text": "",
                },
                {
                    "item_key": "in-use-file",
                    "status_label": "In Use by Active Profile",
                    "category_label": "Track / Album Media",
                    "label": "live_audio.wav",
                    "size_text": "640.0 MB",
                    "bytes_on_disk": 640 * 1024 * 1024,
                    "profile_name": "catalog.db",
                    "path": "/tmp/test-data/track_media/live_audio.wav",
                    "reason": "Referenced by active profile catalog.db.",
                    "warning_required": True,
                    "warning": "Deleting this file permanently removes media still referenced by active profiles.",
                    "references_text": "Track #1 'Live Track' audio",
                },
            ],
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
        on_progress=None,
        on_status=None,
    ):
        del owner, on_error, on_cancelled
        self.load_calls += 1
        if on_status is not None:
            on_status("Checking managed audio references (1/3)...")
        if on_progress is not None:
            update = TaskProgressUpdate(
                value=6,
                maximum=7,
                message="Inspecting application-wide storage...",
            )
            self.progress_updates.append(update)
            on_progress(update)
        if on_success is not None:
            on_success(self._report)
        if on_progress is not None:
            update = TaskProgressUpdate(
                value=7,
                maximum=7,
                message="Diagnostics ready.",
            )
            self.progress_updates.append(update)
            on_progress(update)
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

    def open_application_storage_admin_dialog(self):
        self.application_storage_admin_open_count += 1

    def _load_application_storage_audit_async(
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
        self.storage_audit_load_calls += 1
        if on_status is not None:
            on_status("Inspecting application-wide storage...")
        if on_success is not None:
            on_success(self._storage_audit_payload)
        if on_finished is not None:
            on_finished()
        return f"storage-audit-{self.storage_audit_load_calls}"

    def _run_application_storage_cleanup_async(
        self,
        item_keys,
        *,
        allow_warning_deletes=False,
        owner=None,
        on_success=None,
        on_error=None,
        on_cancelled=None,
        on_finished=None,
        on_status=None,
    ):
        del owner, on_error, on_cancelled
        self.storage_cleanup_calls.append((list(item_keys), bool(allow_warning_deletes)))
        if on_status is not None:
            on_status("Deleting selected application storage items...")
        if on_success is not None:
            on_success(
                {
                    "removed_count": len(item_keys),
                    "removed_text": "1.1 GB",
                    "removed_history_entry_count": 0,
                    "removed_session_entry_count": 0,
                    "skipped_count": 0,
                }
            )
        if on_finished is not None:
            on_finished()
        return f"storage-cleanup-{len(self.storage_cleanup_calls)}"


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

    def test_master_transfer_export_dialog_checks_all_sections_by_default(self):
        dialog = MasterTransferExportDialog(
            [
                {
                    "section_id": "catalog",
                    "label": "Catalog Exchange Package",
                    "description": "Tracks and packaged media.",
                    "depends_on": [],
                    "entity_counts": {"tracks": 2},
                    "default_selected": True,
                },
                {
                    "section_id": "repertoire",
                    "label": "Contracts and Rights Package",
                    "description": "Parties, works, contracts, rights, and assets.",
                    "depends_on": ["catalog"],
                    "entity_counts": {"contracts": 2},
                    "default_selected": True,
                },
                {
                    "section_id": "contract_templates",
                    "label": "Contract Templates",
                    "description": "Template families and revision sources.",
                    "depends_on": [],
                    "entity_counts": {"templates": 1},
                    "default_selected": True,
                },
            ]
        )
        try:
            self.assertEqual(
                dialog.selected_section_ids(), ["catalog", "repertoire", "contract_templates"]
            )
            self.assertEqual(dialog.section_table.item(0, 0).checkState(), Qt.Checked)
            self.assertEqual(dialog.section_table.item(1, 0).checkState(), Qt.Checked)
            self.assertEqual(dialog.section_table.item(2, 0).checkState(), Qt.Checked)
            self.assertTrue(dialog.export_button.isEnabled())
        finally:
            dialog.close()

    def test_master_transfer_export_dialog_disables_dependent_sections_when_required_section_is_unchecked(
        self,
    ):
        dialog = MasterTransferExportDialog(
            [
                {
                    "section_id": "catalog",
                    "label": "Catalog Exchange Package",
                    "description": "Tracks and packaged media.",
                    "depends_on": [],
                    "entity_counts": {"tracks": 2},
                    "default_selected": True,
                },
                {
                    "section_id": "repertoire",
                    "label": "Contracts and Rights Package",
                    "description": "Parties, works, contracts, rights, and assets.",
                    "depends_on": ["catalog"],
                    "entity_counts": {"contracts": 2},
                    "default_selected": True,
                },
                {
                    "section_id": "licenses",
                    "label": "License Archive",
                    "description": "License PDFs.",
                    "depends_on": ["catalog"],
                    "entity_counts": {"licenses": 1},
                    "default_selected": True,
                },
            ]
        )
        try:
            dialog.section_table.item(0, 0).setCheckState(Qt.Unchecked)
            self.app.processEvents()

            self.assertEqual(dialog.selected_section_ids(), [])
            self.assertEqual(dialog.section_table.item(1, 0).checkState(), Qt.Unchecked)
            self.assertEqual(dialog.section_table.item(2, 0).checkState(), Qt.Unchecked)
            self.assertFalse(bool(dialog.section_table.item(1, 0).flags() & Qt.ItemIsUserCheckable))
            self.assertIn(
                "Requires: Catalog Exchange Package", dialog.section_table.item(1, 3).text()
            )
            self.assertFalse(dialog.export_button.isEnabled())
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
            self.assertEqual(
                [update.message for update in host.progress_updates],
                [
                    "Inspecting application-wide storage...",
                    "Diagnostics ready.",
                ],
            )
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
            self.assertIn("3.2 GB", dialog.application_storage_summary_label.text())
            self.assertEqual(dialog.history_storage_metric_labels["budget"].text(), "1.0 GB")
            self.assertEqual(
                dialog.history_storage_metric_labels["over_budget"].text(),
                "820.0 MB",
            )
            self.assertTrue(dialog.open_cleanup_button.isEnabled())
            self.assertTrue(dialog.open_storage_admin_button.isEnabled())
            self.assertEqual(dialog.checks_list.count(), 1)
            self.assertIn("Schema layout", dialog.details_edit.toPlainText())
            self.assertTrue(dialog.repair_button.isEnabled())
            self.assertEqual(dialog.repair_button.text(), "Repair Schema Layout")
            self.assertEqual(dialog.catalog_cleanup_panel._refresh_calls, 1)
            dialog.open_cleanup_button.click()
            self.assertEqual(host.history_cleanup_open_count, 1)
            dialog.open_storage_admin_button.click()
            self.assertEqual(host.application_storage_admin_open_count, 1)
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

    def test_diagnostics_dialog_busy_progress_uses_reported_work_units(self):
        host = _DiagnosticsDialogHost()
        dialog = DiagnosticsDialog(host)
        try:
            dialog._set_busy(True, "Loading diagnostics...")
            dialog._apply_busy_progress(
                TaskProgressUpdate(
                    value=6,
                    maximum=7,
                    message="Inspecting application-wide storage...",
                )
            )

            self.assertFalse(dialog.loading_panel.isHidden())
            self.assertEqual(dialog.loading_bar.minimum(), 0)
            self.assertEqual(dialog.loading_bar.maximum(), 7)
            self.assertEqual(dialog.loading_bar.value(), 6)
            self.assertEqual(
                dialog.loading_status_label.text(),
                "Inspecting application-wide storage...",
            )
        finally:
            dialog.close()
            host.close()

    def test_diagnostics_dialog_reaches_completion_only_after_final_progress_update(self):
        host = _DiagnosticsDialogHost()
        dialog = DiagnosticsDialog(host)
        try:
            dialog._set_busy(True, "Loading diagnostics...")
            dialog._apply_busy_progress(
                TaskProgressUpdate(
                    value=6,
                    maximum=7,
                    message="Inspecting application-wide storage...",
                )
            )
            dialog._populate_loaded_report(host._report)
            self.assertEqual(dialog.loading_bar.maximum(), 7)
            self.assertEqual(dialog.loading_bar.value(), 6)

            dialog._apply_busy_progress(
                TaskProgressUpdate(
                    value=7,
                    maximum=7,
                    message="Diagnostics ready.",
                )
            )
            self.assertEqual(dialog.loading_bar.value(), 7)
            self.assertEqual(dialog.loading_status_label.text(), "Diagnostics ready.")

            dialog._finish_loaded_report()
            self.assertFalse(dialog.loading_panel.isVisible())
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

    def test_application_storage_admin_dialog_uses_async_loader_and_strong_delete_confirmations(
        self,
    ):
        host = _DiagnosticsDialogHost()
        dialog = ApplicationStorageAdminDialog(host)
        try:
            self.assertEqual(host.storage_audit_load_calls, 1)
            self.assertFalse(dialog.loading_panel.isVisible())
            self.assertEqual(dialog.surface_tabs.tabText(0), "Cleanup Candidates")
            self.assertEqual(dialog.surface_tabs.tabText(1), "Warnings & In Use")
            self.assertIn("3.2 GB", dialog.summary_label.text())
            self.assertEqual(dialog.cleanup_table.rowCount(), 1)
            self.assertEqual(dialog.warning_table.rowCount(), 1)

            dialog.surface_tabs.setCurrentWidget(dialog.warning_table)
            dialog.warning_table.selectRow(0)
            self.assertIn(
                "Deleting this file permanently removes media", dialog.details_edit.toPlainText()
            )

            with (
                mock.patch(
                    "isrc_manager.app_dialogs.QMessageBox.question",
                    return_value=QMessageBox.Yes,
                ),
                mock.patch(
                    "isrc_manager.app_dialogs.QInputDialog.getText",
                    return_value=("DELETE", True),
                ),
                mock.patch("isrc_manager.app_dialogs.QMessageBox.information") as info_mock,
            ):
                dialog._delete_selected()

            self.assertEqual(host.storage_cleanup_calls, [(["in-use-file"], True)])
            self.assertEqual(host.storage_audit_load_calls, 2)
            info_mock.assert_called_once()
        finally:
            dialog.close()
            host.close()


if __name__ == "__main__":
    unittest.main()

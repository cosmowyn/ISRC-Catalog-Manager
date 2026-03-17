import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from isrc_manager.constants import APP_NAME
from isrc_manager.services import (
    DatabaseSchemaService,
    DatabaseSessionService,
    TrackCreatePayload,
)
from isrc_manager.starter_themes import starter_theme_names
from tests.qt_test_helpers import require_qapplication

try:
    from PySide6.QtWidgets import QScrollArea

    import ISRC_manager as app_module
except Exception as exc:  # pragma: no cover - environment-specific fallback
    app_module = None
    APP_IMPORT_ERROR = exc
else:
    APP_IMPORT_ERROR = None


def _no_catalog_background_refresh(self, *args, **kwargs):
    on_finished = kwargs.get("on_finished")
    if callable(on_finished):
        on_finished()
    return None


class AppShellIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if app_module is None:
            raise unittest.SkipTest(f"ISRC_manager import unavailable: {APP_IMPORT_ERROR}")
        cls.app = require_qapplication()

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.local_appdata = self.root / "local-appdata"
        self.qt_settings_root = self.root / "qt-settings"
        self._patchers = [
            mock.patch.dict(os.environ, {"LOCALAPPDATA": str(self.local_appdata)}, clear=False),
            mock.patch.object(
                app_module.QStandardPaths,
                "writableLocation",
                side_effect=self._fake_writable_location,
            ),
            mock.patch.object(
                app_module.App,
                "_refresh_catalog_ui_in_background",
                _no_catalog_background_refresh,
            ),
        ]
        for patcher in self._patchers:
            patcher.start()
        self.window = app_module.App()
        self.app.processEvents()

    def tearDown(self):
        try:
            if getattr(self, "window", None) is not None:
                self.window.close()
                self.window._close_database_connection()
                self.window.deleteLater()
                self.app.processEvents()
        finally:
            for patcher in reversed(getattr(self, "_patchers", [])):
                patcher.stop()
            self.tmpdir.cleanup()

    def _fake_writable_location(self, location):
        location_name = getattr(location, "name", str(location)).replace("/", "_")
        path = self.qt_settings_root / location_name
        path.mkdir(parents=True, exist_ok=True)
        return str(path)

    def _create_profile_database(self, path: Path) -> None:
        session = DatabaseSessionService().open(path)
        try:
            schema = DatabaseSchemaService(session.conn, data_root=self.local_appdata / APP_NAME)
            schema.init_db()
            schema.migrate_schema()
        finally:
            DatabaseSessionService.close(session.conn)

    def test_startup_builds_main_window_with_core_actions(self):
        self.assertIsNotNone(self.window.conn)
        self.assertTrue(Path(self.window.current_db_path).exists())
        self.assertEqual(self.window.menuBar(), self.window.menu_bar)
        self.assertGreaterEqual(self.window.profile_combo.count(), 1)
        self.assertEqual(self.window.profile_combo.itemData(0), self.window.current_db_path)
        self.assertEqual(self.window.windowTitle(), self.window.identity["window_title"])
        self.assertEqual(self.window.toolbar.objectName(), "profilesToolbar")
        self.assertEqual(self.window.statusBar().currentMessage(), "")

        expected_actions = {
            "New Profile…": self.window.new_profile_action,
            "Open Profile…": self.window.open_profile_action,
            "Release Browser…": self.window.release_browser_action,
            "Work Manager…": self.window.work_manager_action,
            "Contract Manager…": self.window.contract_manager_action,
            "Global Search and Relationships…": self.window.global_search_action,
            "Create Snapshot…": self.window.create_snapshot_action,
        }
        self.assertEqual(
            {text: action.text() for text, action in expected_actions.items()},
            {text: text for text in expected_actions},
        )
        self.assertTrue(self.window.close())
        self.app.processEvents()
        self.assertFalse(self.window.isVisible())

    def test_bundled_themes_are_available_and_not_persisted_as_user_library_entries(self):
        library = self.window._load_theme_library()
        for name in starter_theme_names():
            self.assertIn(name, library)

        self.window._save_theme_library(library)
        stored_payload = json.loads(self.window.settings.value("theme/library_json", "{}", str))
        for name in starter_theme_names():
            self.assertNotIn(name, stored_payload)

    def test_create_new_profile_and_browse_profile_switch_workspace(self):
        created_path = self.window.database_dir / "Label_Test.db"
        external_path = self.root / "external-profile.db"
        self._create_profile_database(external_path)

        def _activate_now(path, **kwargs):
            prepared_path = str(Path(path))
            self.window._activate_profile(prepared_path)
            on_activated = kwargs.get("on_activated")
            if callable(on_activated):
                on_activated(prepared_path)
            return "sync-profile-activation"

        with (
            mock.patch.object(
                self.window,
                "_activate_profile_in_background",
                side_effect=_activate_now,
            ),
            mock.patch.object(
                app_module.QInputDialog,
                "getText",
                return_value=("Label Test", True),
            ),
            mock.patch.object(app_module.QMessageBox, "information", return_value=None),
        ):
            self.window.create_new_profile()

        self.assertEqual(self.window.current_db_path, str(created_path))
        self.assertTrue(created_path.exists())
        self.assertGreaterEqual(self.window.profile_combo.findData(str(created_path)), 0)

        with (
            mock.patch.object(
                self.window,
                "_activate_profile_in_background",
                side_effect=_activate_now,
            ),
            mock.patch.object(
                app_module.QFileDialog,
                "getOpenFileName",
                return_value=(str(external_path), "SQLite DB (*.db)"),
            ),
        ):
            self.window.browse_profile()

        self.assertEqual(self.window.current_db_path, str(external_path))
        self.assertGreaterEqual(self.window.profile_combo.findData(str(external_path)), 0)

    def test_cancelled_profile_creation_and_restore_leave_shell_idle(self):
        initial_path = self.window.current_db_path

        with mock.patch.object(
            app_module.QInputDialog,
            "getText",
            return_value=("", False),
        ):
            self.window.create_new_profile()

        with mock.patch.object(
            app_module.QFileDialog,
            "getOpenFileName",
            return_value=("", ""),
        ):
            self.window.restore_database()

        self.assertEqual(self.window.current_db_path, initial_path)
        self.assertFalse(self.window.background_tasks.has_running_tasks())
        profiles = [
            Path(self.window.profile_combo.itemData(i)).name
            for i in range(self.window.profile_combo.count())
        ]
        self.assertEqual(profiles, [Path(initial_path).name])

    def test_filtered_select_all_counts_only_visible_tracks(self):
        titles = [
            "Crossroads of the Unwritten Self",
            "Crossroads of the Unwritten Self (Remix)",
            "Crossroads of the Unwritten Self - Live",
            "Orbit Drift",
        ]
        for index, title in enumerate(titles, start=1):
            self.window.track_service.create_track(
                TrackCreatePayload(
                    isrc=f"NL-TST-26-{index:05d}",
                    track_title=title,
                    artist_name="Cosmowyn",
                    additional_artists=[],
                    album_title="Selection Test",
                    release_date="2026-03-17",
                    track_length_sec=180,
                    iswc=None,
                    upc=None,
                    genre="Ambient",
                    catalog_number=None,
                )
            )

        self.window.refresh_table()
        self.window.search_field.setText("Crossroads of the Unwritten Self")
        self.window.apply_search_filter()
        self.app.processEvents()

        visible_rows = [
            row
            for row in range(self.window.table.rowCount())
            if not self.window.table.isRowHidden(row)
        ]
        self.assertEqual(len(visible_rows), 3)

        self.window.table.selectAll()
        self.app.processEvents()

        selected_ids = self.window._selected_track_ids()
        self.assertEqual(len(selected_ids), len(visible_rows))

    def test_add_data_panel_uses_tabbed_sections(self):
        tabs = self.window.findChild(app_module.QTabWidget, "addDataTabs")
        self.assertIsNotNone(tabs)
        self.assertEqual(
            [tabs.tabText(index) for index in range(tabs.count())],
            [
                "Track",
                "Release",
                "Codes",
                "Media",
            ],
        )
        self.assertEqual(self.window.left_widget_container.property("role"), "workspaceCanvas")
        self.assertEqual(self.window.table_panel_widget.property("role"), "workspaceCanvas")
        self.assertEqual(self.window.centralWidget().property("role"), "workspaceCanvas")

    def test_track_editor_uses_tabbed_sections(self):
        track_id = self.window.track_service.create_track(
            TrackCreatePayload(
                isrc="NL-TST-26-09001",
                track_title="Tabbed Editor",
                artist_name="Cosmowyn",
                additional_artists=[],
                album_title="Editor Layout",
                release_date="2026-03-17",
                track_length_sec=205,
                iswc=None,
                upc=None,
                genre="Ambient",
                catalog_number=None,
            )
        )

        dialog = app_module.EditDialog(track_id, self.window)
        try:
            tabs = dialog.findChild(app_module.QTabWidget, "editDialogTabs")
            self.assertIsNotNone(tabs)
            self.assertEqual(
                [tabs.tabText(index) for index in range(tabs.count())],
                [
                    "Track",
                    "Release",
                    "Codes",
                    "Media",
                ],
            )
            self.assertEqual(tabs.currentWidget().property("role"), "workspaceCanvas")
            scroll_areas = dialog.findChildren(QScrollArea)
            self.assertTrue(scroll_areas)
            self.assertTrue(
                any(area.property("role") == "workspaceCanvas" for area in scroll_areas)
            )
        finally:
            dialog.close()

    def test_album_entry_track_sections_use_internal_tabs(self):
        dialog = app_module.AlbumEntryDialog(self.window)
        try:
            section_tabs = dialog.findChildren(app_module.QTabWidget, "albumTrackSectionTabs")
            self.assertGreaterEqual(len(section_tabs), 1)
            self.assertEqual(
                [section_tabs[0].tabText(index) for index in range(section_tabs[0].count())],
                [
                    "Details",
                    "Codes",
                    "Media",
                ],
            )
            current_page = dialog.primary_tabs.currentWidget()
            self.assertEqual(current_page.property("role"), "workspaceCanvas")
        finally:
            dialog.close()

    def test_gs1_dialog_uses_top_level_workflow_tabs(self):
        track_id = self.window.track_service.create_track(
            TrackCreatePayload(
                isrc="NL-TST-26-09002",
                track_title="GS1 Layout",
                artist_name="Cosmowyn",
                additional_artists=[],
                album_title="GS1 Layout",
                release_date="2026-03-17",
                track_length_sec=185,
                iswc=None,
                upc="8720892724649",
                genre="Ambient",
                catalog_number=None,
            )
        )

        with mock.patch.object(
            app_module.GS1MetadataDialog, "_refresh_template_status", return_value=False
        ):
            dialog = app_module.GS1MetadataDialog(
                app=self.window,
                track_id=track_id,
                batch_track_ids=[track_id],
                parent=self.window,
            )
        try:
            tabs = dialog.findChild(app_module.QTabWidget, "gs1MetadataDialogTabs")
            self.assertIsNotNone(tabs)
            self.assertEqual(
                [tabs.tabText(index) for index in range(tabs.count())],
                [
                    "Overview",
                    "Workbook",
                    "Product Groups",
                    "Readiness",
                ],
            )
        finally:
            dialog.close()


if __name__ == "__main__":
    unittest.main()

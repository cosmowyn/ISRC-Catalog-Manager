import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from isrc_manager.constants import APP_NAME
from isrc_manager.services import (
    AssetVersionPayload,
    ContractPayload,
    DatabaseSchemaService,
    DatabaseSessionService,
    PartyPayload,
    RightPayload,
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
        self.window.show()
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

    def _create_track(self, *, index: int, title: str, album_title: str = "Workspace Tests") -> int:
        return self.window.track_service.create_track(
            TrackCreatePayload(
                isrc=f"NL-TST-26-{index:05d}",
                track_title=title,
                artist_name="Cosmowyn",
                additional_artists=[],
                album_title=album_title,
                release_date="2026-03-17",
                track_length_sec=180 + index,
                iswc=None,
                upc=None,
                genre="Ambient",
                catalog_number=None,
            )
        )

    def _select_track_ids(self, track_ids: list[int]) -> None:
        track_id_set = {int(track_id) for track_id in track_ids}
        self.window.table.clearSelection()
        selection_model = self.window.table.selectionModel()
        for row in range(self.window.table.rowCount()):
            item = self.window.table.item(row, 0)
            if item is None:
                continue
            try:
                current_track_id = int(item.text())
            except Exception:
                continue
            if current_track_id not in track_id_set:
                continue
            index = self.window.table.model().index(row, 0)
            selection_model.select(
                index,
                app_module.QItemSelectionModel.Select | app_module.QItemSelectionModel.Rows,
            )
        self.app.processEvents()

    def _assert_tabified_workspace_dock(self, dock, *, dock_name: str, panel_name: str):
        panel = dock.widget()
        self.assertFalse(dock.isHidden())
        self.assertEqual(dock.objectName(), dock_name)
        self.assertIsNotNone(panel)
        self.assertEqual(panel.objectName(), panel_name)
        self.assertIn(dock, self.window.tabifiedDockWidgets(self.window.catalog_table_dock))
        return panel

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

    def test_delete_entry_history_stays_a_single_visible_user_action(self):
        track_id = self._create_track(index=121, title="Delete History Song")
        self.window.refresh_table()
        row = self.window._row_for_id(track_id)
        self.assertGreaterEqual(row, 0)
        self.window.table.setCurrentCell(row, 0)
        self.app.processEvents()

        original_rebuild = self.window._rebuild_table_headers

        def _rebuild_with_internal_layout_ping():
            original_rebuild()
            self.window._on_header_layout_changed()

        with (
            mock.patch.object(
                self.window,
                "_rebuild_table_headers",
                side_effect=_rebuild_with_internal_layout_ping,
            ),
            mock.patch.object(
                app_module.QMessageBox,
                "exec",
                return_value=app_module.QMessageBox.Yes,
            ),
            mock.patch.object(app_module.QMessageBox, "critical") as critical_mock,
        ):
            self.window.delete_entry()

        self.app.processEvents()
        critical_mock.assert_not_called()
        self.assertIsNone(self.window.track_service.fetch_track_snapshot(track_id))
        self.assertEqual(
            self.window.undo_action.text(),
            "Undo Delete Track: Delete History Song",
        )

        visible_history = self.window.history_manager.list_entries(limit=20)
        all_history = self.window.history_manager.list_entries(limit=20, include_hidden=True)
        self.assertEqual(
            [entry.label for entry in visible_history], ["Delete Track: Delete History Song"]
        )
        self.assertEqual(
            [entry.label for entry in all_history], ["Delete Track: Delete History Song"]
        )

        dialog = app_module.HistoryDialog(self.window, parent=self.window)
        try:
            self.assertEqual(dialog.history_table.rowCount(), 1)
            self.assertEqual(
                dialog.history_table.item(0, 2).text(), "Delete Track: Delete History Song"
            )
        finally:
            dialog.close()
            self.app.processEvents()

        self.window.history_undo()
        self.app.processEvents()
        self.assertIsNotNone(self.window.track_service.fetch_track_snapshot(track_id))
        self.assertEqual(
            self.window.redo_action.text(),
            "Redo Delete Track: Delete History Song",
        )

        self.window.history_redo()
        self.app.processEvents()
        self.assertIsNone(self.window.track_service.fetch_track_snapshot(track_id))
        self.assertEqual(
            self.window.history_manager.list_entries(limit=20)[0].label,
            "Delete Track: Delete History Song",
        )

    def test_catalog_release_browser_opens_as_tabified_dock(self):
        track_id = self._create_track(index=101, title="Release Dock Track")
        self.window.release_service.create_release(
            app_module.ReleasePayload(
                title="Release Dock Test",
                primary_artist="Cosmowyn",
                release_type="single",
                release_date="2026-03-17",
                placements=[
                    app_module.ReleaseTrackPlacement(
                        track_id=track_id,
                        disc_number=1,
                        track_number=1,
                        sequence_number=1,
                    )
                ],
            )
        )
        self.window.refresh_table()

        self.window.open_release_browser()
        self.app.processEvents()

        dock = self.window.release_browser_dock
        panel = dock.widget()
        self.assertFalse(dock.isHidden())
        self.assertEqual(dock.objectName(), "releaseBrowserDock")
        self.assertEqual(panel.objectName(), "releaseBrowserPanel")
        self.assertIn(dock, self.window.tabifiedDockWidgets(self.window.catalog_table_dock))

        panel.release_table.selectRow(0)
        panel._emit_filter_current()
        self.app.processEvents()

        visible_rows = [
            row
            for row in range(self.window.table.rowCount())
            if not self.window.table.isRowHidden(row)
        ]
        self.assertEqual(len(visible_rows), 1)
        self.assertFalse(dock.isHidden())

    def test_work_manager_dock_uses_live_track_selection(self):
        track_ids = [
            self._create_track(index=111, title="Work Dock One"),
            self._create_track(index=112, title="Work Dock Two"),
            self._create_track(index=113, title="Work Dock Three"),
        ]
        work_id = self.window.work_service.create_work(
            app_module.WorkPayload(title="Docked Work Manager")
        )

        self.window.refresh_table()
        self._select_track_ids(track_ids[:2])

        self.window.open_work_manager()
        self.app.processEvents()

        dock = self.window.work_manager_dock
        panel = dock.widget()
        self.assertFalse(dock.isHidden())
        self.assertEqual(dock.objectName(), "workManagerDock")
        self.assertEqual(panel.objectName(), "workBrowserPanel")
        self.assertIn(dock, self.window.tabifiedDockWidgets(self.window.catalog_table_dock))

        panel.table.selectRow(0)
        panel.link_selected_tracks()
        detail = self.window.work_service.fetch_work_detail(work_id)
        self.assertEqual(set(detail.track_ids), set(track_ids[:2]))

        self._select_track_ids([track_ids[2]])
        panel.link_selected_tracks()
        detail = self.window.work_service.fetch_work_detail(work_id)
        self.assertEqual(set(detail.track_ids), set(track_ids))
        self.assertFalse(dock.isHidden())

    def test_global_search_opens_as_dock_and_keeps_entity_navigation_live(self):
        track_id = self._create_track(index=121, title="Searchable Dock Track")
        self.window.refresh_table()

        self.window.open_global_search()
        self.app.processEvents()

        dock = self.window.global_search_dock
        panel = dock.widget()
        self.assertFalse(dock.isHidden())
        self.assertEqual(dock.objectName(), "globalSearchDock")
        self.assertEqual(panel.objectName(), "globalSearchPanel")
        self.assertIn(dock, self.window.tabifiedDockWidgets(self.window.catalog_table_dock))

        panel.entity_combo.setCurrentText("Tracks")
        panel.search_edit.setText("Searchable Dock Track")
        panel.refresh_results()
        self.app.processEvents()
        self.assertGreaterEqual(panel.results_table.rowCount(), 1)
        panel.results_table.selectRow(0)

        with mock.patch.object(self.window, "open_selected_editor") as open_selected_editor:
            panel.open_selected_result()

        open_selected_editor.assert_called_once_with(track_id)
        self.assertTrue(dock.isVisible())

    def test_catalog_managers_open_as_tabified_dock_and_focus_requested_tab(self):
        self.window.open_catalog_managers_dialog(initial_tab="licensees")
        self.app.processEvents()

        panel = self._assert_tabified_workspace_dock(
            self.window.catalog_managers_dock,
            dock_name="catalogManagersDock",
            panel_name="catalogManagersPanel",
        )

        self.assertEqual(panel.tabs.currentWidget(), panel.licensees_tab)
        self.assertEqual(panel.tabs.tabText(panel.tabs.currentIndex()), "Licensees")
        self.assertTrue(panel.isVisible())

    def test_license_browser_opens_as_tabified_dock_and_applies_track_filter(self):
        track_id = self._create_track(index=131, title="Licensed Track")
        other_track_id = self._create_track(index=132, title="Other Licensed Track")
        pdf_one = self.root / "license-one.pdf"
        pdf_two = self.root / "license-two.pdf"
        pdf_one.write_bytes(b"%PDF-1.4\n%stub license one\n")
        pdf_two.write_bytes(b"%PDF-1.4\n%stub license two\n")

        self.window.license_service.add_license(
            track_id=track_id,
            licensee_name="Aurora Licensing",
            source_pdf_path=pdf_one,
        )
        self.window.license_service.add_license(
            track_id=other_track_id,
            licensee_name="Aurora Licensing",
            source_pdf_path=pdf_two,
        )

        self.window.open_licenses_browser(track_filter_id=track_id)
        self.app.processEvents()

        panel = self._assert_tabified_workspace_dock(
            self.window.license_browser_dock,
            dock_name="licenseBrowserDock",
            panel_name="licensesBrowserPanel",
        )

        self.assertEqual(panel.model.rowCount(), 1)
        self.assertEqual(panel._track_filter_id, track_id)
        self.assertEqual(panel.model.item(0, 1).text(), "Licensed Track")

    def test_party_contract_rights_and_asset_windows_open_as_tabified_docks(self):
        track_id = self._create_track(index=141, title="Docked Rights Track")
        party_id = self.window.party_service.create_party(
            PartyPayload(
                legal_name="North Star Music",
                display_name="North Star",
                party_type="label",
            )
        )
        contract_id = self.window.contract_service.create_contract(
            ContractPayload(
                title="North Star Agreement",
                contract_type="license",
                status="active",
                track_ids=[track_id],
            )
        )
        right_id = self.window.rights_service.create_right(
            RightPayload(
                title="North Star Master Rights",
                right_type="master",
                track_id=track_id,
                granted_to_party_id=party_id,
                source_contract_id=contract_id,
            )
        )
        asset_id = self.window.asset_service.create_asset(
            AssetVersionPayload(
                asset_type="main_master",
                filename="north-star-master.wav",
                track_id=track_id,
                approved_for_use=True,
                primary_flag=True,
                version_status="approved",
            )
        )

        self.window.open_party_manager(party_id)
        self.app.processEvents()
        party_panel = self._assert_tabified_workspace_dock(
            self.window.party_manager_dock,
            dock_name="partyManagerDock",
            panel_name="partyManagerPanel",
        )
        self.assertEqual(party_panel._selected_party_ids(), [party_id])

        self.window.open_contract_manager(contract_id)
        self.app.processEvents()
        contract_panel = self._assert_tabified_workspace_dock(
            self.window.contract_manager_dock,
            dock_name="contractManagerDock",
            panel_name="contractBrowserPanel",
        )
        self.assertEqual(contract_panel._selected_contract_id(), contract_id)

        self.window.open_rights_matrix(right_id)
        self.app.processEvents()
        rights_panel = self._assert_tabified_workspace_dock(
            self.window.rights_matrix_dock,
            dock_name="rightsMatrixDock",
            panel_name="rightsBrowserPanel",
        )
        self.assertEqual(rights_panel._selected_right_id(), right_id)

        self.window.open_asset_registry(asset_id)
        self.app.processEvents()
        asset_panel = self._assert_tabified_workspace_dock(
            self.window.asset_registry_dock,
            dock_name="assetRegistryDock",
            panel_name="assetBrowserPanel",
        )
        self.assertEqual(asset_panel._selected_asset_id(), asset_id)

        tabified = set(self.window.tabifiedDockWidgets(self.window.catalog_table_dock))
        self.assertIn(self.window.party_manager_dock, tabified)
        self.assertIn(self.window.contract_manager_dock, tabified)
        self.assertIn(self.window.rights_matrix_dock, tabified)
        self.assertIn(self.window.asset_registry_dock, tabified)

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
            self.assertEqual(section_tabs[0].currentWidget().property("role"), "tabPaneCanvas")
            section_widget = dialog.findChild(app_module.QWidget, "albumTrackSection")
            self.assertIsNotNone(section_widget)
            self.assertEqual(section_widget.property("role"), "tabPaneCanvas")
            compact_groups = [
                frame
                for frame in dialog.findChildren(app_module.QFrame)
                if frame.property("role") == "compactControlGroup"
            ]
            self.assertTrue(compact_groups)
            self.assertTrue(
                any(
                    group.testAttribute(app_module.Qt.WA_StyledBackground)
                    for group in compact_groups
                )
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

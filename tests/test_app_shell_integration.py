import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from isrc_manager.constants import APP_NAME
from isrc_manager.paths import AppStorageLayout
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
    from PySide6.QtWidgets import QScrollArea, QTabBar

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


class _DeferredMigrationMessageBox:
    Warning = object()
    AcceptRole = object()
    RejectRole = object()
    last_text = ""

    def __init__(self, *_args, **_kwargs):
        self._migrate_button = None
        self._keep_button = None
        self._clicked_button = None

    def setWindowTitle(self, _title):
        return None

    def setIcon(self, _icon):
        return None

    def setText(self, text):
        type(self).last_text = str(text)

    def addButton(self, label, _role):
        button = object()
        if "Keep Current Folder For Now" in label:
            self._keep_button = button
        else:
            self._migrate_button = button
        return button

    def setDefaultButton(self, _button):
        return None

    def exec(self):
        self._clicked_button = self._keep_button

    def clickedButton(self):
        return self._clicked_button

    @staticmethod
    def warning(*_args, **_kwargs):
        return None

    @staticmethod
    def information(*_args, **_kwargs):
        return None


class _AcceptMigrationMessageBox(_DeferredMigrationMessageBox):
    warning_calls: list[str] = []
    information_calls: list[str] = []

    def exec(self):
        self._clicked_button = self._migrate_button

    @staticmethod
    def warning(*args, **_kwargs):
        text = str(args[2]) if len(args) > 2 else ""
        _AcceptMigrationMessageBox.warning_calls.append(text)
        return None

    @staticmethod
    def information(*args, **_kwargs):
        text = str(args[2]) if len(args) > 2 else ""
        _AcceptMigrationMessageBox.information_calls.append(text)
        return None


class _FakeStartupSplashController:
    def __init__(self):
        self.messages: list[str] = []
        self.finish_calls: list[object] = []

    def set_status(self, message: str):
        self.messages.append(str(message))

    def finish(self, window):
        self.finish_calls.append(window)


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
            app = getattr(self, "app", None)
            if app is not None and hasattr(app, "_startup_splash_controller"):
                delattr(app, "_startup_splash_controller")
            for patcher in reversed(getattr(self, "_patchers", [])):
                patcher.stop()
            self.tmpdir.cleanup()

    def _fake_writable_location(self, location):
        location_name = getattr(location, "name", str(location)).replace("/", "_")
        path = self.qt_settings_root / location_name
        path.mkdir(parents=True, exist_ok=True)
        return str(path)

    def _drain_events(self, cycles: int = 4) -> None:
        for _ in range(cycles):
            self.app.processEvents()

    def _close_window(self) -> str:
        window = getattr(self, "window", None)
        if window is None:
            return ""
        settings_path = window.settings.fileName()
        window.close()
        self._drain_events()
        window._close_database_connection()
        window.deleteLater()
        self._drain_events()
        self.window = None
        return settings_path

    def _reopen_window(self):
        self._close_window()
        self.window = app_module.App()
        self.window.show()
        self._drain_events()
        return self.window

    def _settings_path(self) -> Path:
        return self.qt_settings_root / "AppDataLocation" / "settings.ini"

    def _settings(self):
        settings = app_module.QSettings(str(self._settings_path()), app_module.QSettings.IniFormat)
        settings.setFallbacksEnabled(False)
        return settings

    def _seed_startup_settings_for_legacy_db(self, legacy_db: Path) -> None:
        settings = self._settings()
        settings.setValue("storage/legacy_data_root", str(legacy_db.parent.parent.resolve()))
        settings.setValue("storage/active_data_root", str(legacy_db.parent.parent.resolve()))
        settings.setValue("db/last_path", str(legacy_db.resolve()))
        settings.setValue("paths/database_dir", str(legacy_db.parent.resolve()))
        settings.sync()
        settings.deleteLater() if hasattr(settings, "deleteLater") else None

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

    @staticmethod
    def _is_within_scroll_content(scroll_area, widget) -> bool:
        content = scroll_area.widget()
        return content is widget or (content is not None and content.isAncestorOf(widget))

    @staticmethod
    def _button_by_text(container, text: str):
        for button in container.findChildren(app_module.QPushButton):
            if button.text() == text:
                return button
        raise AssertionError(f"Button not found: {text}")

    def _menu_by_text(self, text: str):
        for menu in self.window.menuBar().findChildren(app_module.QMenu):
            if menu.title() == text:
                return menu
        raise AssertionError(f"Menu not found: {text}")

    def _workspace_dock_tab_bar(self) -> QTabBar:
        expected_titles = {
            dock.windowTitle()
            for dock in (
                getattr(self.window, "catalog_table_dock", None),
                getattr(self.window, "release_browser_dock", None),
                getattr(self.window, "work_manager_dock", None),
                getattr(self.window, "global_search_dock", None),
                getattr(self.window, "catalog_managers_dock", None),
            )
            if dock is not None
        }
        for tab_bar in self.window.findChildren(QTabBar):
            texts = {tab_bar.tabText(index) for index in range(tab_bar.count())}
            if texts & expected_titles:
                return tab_bar
        raise AssertionError("Workspace dock tab bar not found")

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

    def test_startup_status_messages_cover_real_bootstrap_phases_and_ready_boundary(self):
        self._close_window()
        splash = _FakeStartupSplashController()
        self.app._startup_splash_controller = splash

        self.window = app_module.App()
        self.window.startupReady.connect(lambda: splash.finish(self.window))

        self.assertEqual(
            splash.messages,
            [
                "Resolving storage layout…",
                "Initializing settings…",
                "Opening profile database…",
                "Loading services…",
                "Finalizing interface…",
            ],
        )
        self.assertEqual(splash.finish_calls, [])

        self.window.show()
        self.assertEqual(splash.finish_calls, [])
        self._drain_events()

        self.assertEqual(
            splash.messages,
            [
                "Resolving storage layout…",
                "Initializing settings…",
                "Opening profile database…",
                "Loading services…",
                "Finalizing interface…",
                "Restoring workspace…",
            ],
        )
        self.assertEqual(splash.finish_calls, [self.window])

    def test_file_menu_groups_xml_import_under_import_exchange_and_preserves_wiring(self):
        file_menu = self._menu_by_text("File")
        file_texts = [action.text() for action in file_menu.actions() if action.text()]
        self.assertNotIn("Import XML…", file_texts)

        import_exchange_action = next(
            action
            for action in file_menu.actions()
            if action.menu() is not None and action.text() == "Import Exchange"
        )
        import_exchange_menu = import_exchange_action.menu()
        assert import_exchange_menu is not None
        submenu_actions = [
            action for action in import_exchange_menu.actions() if not action.isSeparator()
        ]
        self.assertEqual(
            submenu_actions[:5],
            [
                self.window.import_xml_action,
                self.window.import_csv_action,
                self.window.import_xlsx_action,
                self.window.import_json_action,
                self.window.import_package_action,
            ],
        )
        self.assertTrue(
            any(not shortcut.isEmpty() for shortcut in self.window.import_xml_action.shortcuts())
        )

        with mock.patch.object(
            app_module.QFileDialog,
            "getOpenFileName",
            return_value=("", ""),
        ) as get_open_file_name:
            self.window.import_xml_action.trigger()
            self.app.processEvents()

        get_open_file_name.assert_called_once_with(
            self.window,
            "Import from XML",
            "",
            "XML Files (*.xml)",
        )

    def test_startup_can_defer_legacy_storage_migration_and_keep_current_folder(self):
        self._close_window()
        preferred_root = self.qt_settings_root / "AppLocalDataLocation"
        if preferred_root.exists():
            for child in preferred_root.iterdir():
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
        legacy_root = self.local_appdata / APP_NAME
        (legacy_root / "history").mkdir(parents=True, exist_ok=True)
        (legacy_root / "Database").mkdir(parents=True, exist_ok=True)

        with mock.patch.object(app_module, "QMessageBox", _DeferredMigrationMessageBox):
            self.window = app_module.App()
            self.window.show()
            self._drain_events()

        self.assertEqual(self.window.data_root, legacy_root.resolve())
        self.assertEqual(
            self.window.settings.value("storage/active_data_root", "", str),
            str(legacy_root.resolve()),
        )
        self.assertTrue(
            str(Path(self.window.current_db_path).resolve()).startswith(str(legacy_root.resolve()))
        )
        self.assertEqual(
            self.window.settings.value("storage/migration_state", "", str),
            "deferred",
        )
        self.assertIn("legacy app-data folder", _DeferredMigrationMessageBox.last_text.lower())

    def test_startup_migrate_now_bootstraps_logging_and_uses_preferred_root(self):
        self._close_window()
        _AcceptMigrationMessageBox.warning_calls = []
        _AcceptMigrationMessageBox.information_calls = []
        preferred_root = self.qt_settings_root / "AppLocalDataLocation"
        if preferred_root.exists():
            shutil.rmtree(preferred_root)

        legacy_root = self.local_appdata / APP_NAME
        legacy_db = legacy_root / "Database" / "legacy_startup.db"
        self._create_profile_database(legacy_db)
        self._seed_startup_settings_for_legacy_db(legacy_db)

        with mock.patch.object(app_module, "QMessageBox", _AcceptMigrationMessageBox):
            self.window = app_module.App()
            self.window.show()
            self._drain_events()

        self.assertEqual(self.window.data_root, preferred_root.resolve())
        self.assertEqual(
            self.window.settings.value("storage/migration_state", "", str),
            "complete",
        )
        self.assertEqual(
            self.window.settings.value("storage/active_data_root", "", str),
            str(preferred_root.resolve()),
        )
        self.assertEqual(
            self.window.settings.value("db/last_path", "", str),
            str((preferred_root / "Database" / legacy_db.name).resolve()),
        )
        self.assertEqual(Path(self.window.current_db_path).resolve(), (preferred_root / "Database" / legacy_db.name).resolve())
        log_files = sorted(preferred_root.joinpath("logs").glob("isrc_manager_*.log"))
        trace_files = sorted(preferred_root.joinpath("logs").glob("isrc_manager_trace_*.jsonl"))
        self.assertTrue(log_files)
        self.assertTrue(trace_files)
        self.assertEqual(_AcceptMigrationMessageBox.warning_calls, [])

    def test_startup_adopts_valid_preferred_root_when_settings_still_pin_legacy(self):
        self._close_window()
        preferred_root = self.qt_settings_root / "AppLocalDataLocation"
        if preferred_root.exists():
            shutil.rmtree(preferred_root)

        legacy_root = self.local_appdata / APP_NAME
        legacy_db = legacy_root / "Database" / "legacy_adopt.db"
        self._create_profile_database(legacy_db)
        self._seed_startup_settings_for_legacy_db(legacy_db)

        settings = self._settings()
        layout = app_module.resolve_app_storage_layout(settings=settings)
        app_module.StorageMigrationService(layout, settings=settings).migrate()
        settings.setValue("storage/migration_state", "failed")
        settings.setValue("storage/legacy_data_root", str(legacy_root.resolve()))
        settings.setValue("storage/active_data_root", str(legacy_root.resolve()))
        settings.setValue("db/last_path", str(legacy_db.resolve()))
        settings.setValue("paths/database_dir", str((legacy_root / "Database").resolve()))
        settings.sync()

        with mock.patch.object(app_module, "QMessageBox") as message_box:
            self.window = app_module.App()
            self.window.show()
            self._drain_events()

        migrated_db = preferred_root / "Database" / legacy_db.name
        self.assertEqual(self.window.data_root, preferred_root.resolve())
        self.assertEqual(Path(self.window.current_db_path).resolve(), migrated_db.resolve())
        self.assertEqual(
            self.window.settings.value("storage/active_data_root", "", str),
            str(preferred_root.resolve()),
        )
        self.assertEqual(
            self.window.settings.value("storage/migration_state", "", str),
            "complete",
        )
        self.assertEqual(
            self.window.settings.value("db/last_path", "", str),
            str(migrated_db.resolve()),
        )
        self.assertFalse(message_box.called)

    def test_storage_migration_reopens_active_managed_profile_in_new_root(self):
        self._close_window()
        preferred_root = self.qt_settings_root / "AppLocalDataLocation"
        if preferred_root.exists():
            shutil.rmtree(preferred_root)

        legacy_root = self.local_appdata / APP_NAME
        legacy_db = legacy_root / "Database" / "legacy_active.db"
        self._create_profile_database(legacy_db)

        settings_path = self.qt_settings_root / "AppDataLocation" / "settings.ini"
        settings = app_module.QSettings(str(settings_path), app_module.QSettings.IniFormat)
        settings.setFallbacksEnabled(False)
        settings.setValue("storage/migration_state", "deferred")
        settings.setValue("storage/legacy_data_root", str(legacy_root.resolve()))
        settings.setValue("storage/active_data_root", str(legacy_root.resolve()))
        settings.setValue("db/last_path", str(legacy_db.resolve()))
        settings.setValue("paths/database_dir", str((legacy_root / "Database").resolve()))
        settings.sync()

        self.window = app_module.App()
        self.window.show()
        self._drain_events()

        self.assertEqual(self.window.data_root, legacy_root.resolve())
        self.assertEqual(Path(self.window.current_db_path).resolve(), legacy_db.resolve())

        track_id = self._create_track(index=404, title="Migrated Managed Profile")

        result = self.window._run_storage_layout_migration()
        self._drain_events()

        migrated_db = preferred_root / "Database" / legacy_db.name
        self.assertEqual(result.target_root, preferred_root.resolve())
        self.assertEqual(Path(self.window.current_db_path).resolve(), migrated_db.resolve())
        self.assertTrue(migrated_db.exists())
        self.assertEqual(
            self.window.settings.value("db/last_path", "", str),
            str(migrated_db.resolve()),
        )
        self.assertEqual(
            self.window.settings.value("storage/active_data_root", "", str),
            str(preferred_root.resolve()),
        )
        self.assertEqual(
            self.window.settings.value("storage/migration_state", "", str),
            "complete",
        )
        self.assertTrue((legacy_root / "Database" / legacy_db.name).exists())
        self.assertIsNotNone(self.window.track_service.fetch_track_snapshot(track_id))

    def test_manual_legacy_cleanup_after_adoption_does_not_recreate_legacy_root(self):
        self._close_window()
        preferred_root = self.qt_settings_root / "AppLocalDataLocation"
        if preferred_root.exists():
            shutil.rmtree(preferred_root)

        legacy_root = self.local_appdata / APP_NAME
        legacy_db = legacy_root / "Database" / "legacy_cleanup.db"
        self._create_profile_database(legacy_db)
        self._seed_startup_settings_for_legacy_db(legacy_db)

        settings = self._settings()
        layout = app_module.resolve_app_storage_layout(settings=settings)
        app_module.StorageMigrationService(layout, settings=settings).migrate()
        settings.setValue("storage/migration_state", "failed")
        settings.setValue("storage/legacy_data_root", str(legacy_root.resolve()))
        settings.setValue("storage/active_data_root", str(legacy_root.resolve()))
        settings.setValue("db/last_path", str(legacy_db.resolve()))
        settings.setValue("paths/database_dir", str((legacy_root / "Database").resolve()))
        settings.sync()

        shutil.rmtree(legacy_root)
        self.assertFalse(legacy_root.exists())

        self.window = app_module.App()
        self.window.show()
        self._drain_events()

        self.assertEqual(self.window.data_root, preferred_root.resolve())
        self.assertFalse(legacy_root.exists())
        self.assertFalse((legacy_root / "Database" / "default.db").exists())
        self.assertFalse((legacy_root / "history").exists())
        self.assertFalse((legacy_root / "help").exists())
        self.assertFalse((legacy_root / "logs").exists())

    def test_portable_mode_skips_storage_migration_and_legacy_adoption(self):
        self._close_window()
        portable_root = self.root / "portable-root"
        legacy_root = self.local_appdata / APP_NAME
        legacy_db = legacy_root / "Database" / "portable_legacy.db"
        self._create_profile_database(legacy_db)

        def _portable_layout(*, settings=None, app_name=APP_NAME, portable=None, active_data_root=None):
            chosen_root = Path(active_data_root).resolve() if active_data_root is not None else portable_root.resolve()
            return AppStorageLayout(
                app_name=app_name,
                portable=True,
                settings_root=portable_root.resolve(),
                settings_path=(portable_root / "settings.ini").resolve(),
                lock_path=(portable_root / f"{app_name}.lock").resolve(),
                preferred_data_root=portable_root.resolve(),
                active_data_root=chosen_root,
                legacy_data_roots=(),
                database_dir=chosen_root / "Database",
                exports_dir=chosen_root / "exports",
                logs_dir=chosen_root / "logs",
                backups_dir=chosen_root / "backups",
                history_dir=chosen_root / "history",
                help_dir=chosen_root / "help",
            )

        with (
            mock.patch.object(app_module, "settings_path", return_value=portable_root / "settings.ini"),
            mock.patch.object(app_module, "resolve_app_storage_layout", side_effect=_portable_layout),
            mock.patch.object(app_module, "QMessageBox") as message_box,
        ):
            self.window = app_module.App()
            self.window.show()
            self._drain_events()

        self.assertEqual(self.window.data_root, portable_root.resolve())
        self.assertNotEqual(self.window.data_root, legacy_root.resolve())
        self.assertFalse(message_box.called)

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

    def test_release_browser_filter_replaces_active_search_filter(self):
        release_track_ids = [
            self._create_track(index=141, title="Release Filter One", album_title="Filter Release"),
            self._create_track(index=142, title="Release Filter Two", album_title="Filter Release"),
        ]
        other_track_id = self._create_track(index=143, title="Unrelated Search Match")
        self.window.release_service.create_release(
            app_module.ReleasePayload(
                title="Filter Release",
                primary_artist="Cosmowyn",
                release_type="album",
                release_date="2026-03-17",
                placements=[
                    app_module.ReleaseTrackPlacement(
                        track_id=track_id,
                        disc_number=1,
                        track_number=index + 1,
                        sequence_number=index + 1,
                    )
                    for index, track_id in enumerate(release_track_ids)
                ],
            )
        )
        self.window.refresh_table()
        self.window.search_field.setText("Unrelated Search Match")
        self.window.apply_search_filter()
        self.app.processEvents()
        visible_before = [
            int(self.window.table.item(row, 0).text())
            for row in range(self.window.table.rowCount())
            if not self.window.table.isRowHidden(row)
        ]
        self.assertEqual(visible_before, [other_track_id])

        self.window.open_release_browser()
        self.app.processEvents()
        panel = self.window.release_browser_dock.widget()
        panel.release_table.selectRow(0)
        panel._emit_filter_current()
        self.app.processEvents()

        visible_after = {
            int(self.window.table.item(row, 0).text())
            for row in range(self.window.table.rowCount())
            if not self.window.table.isRowHidden(row)
        }
        self.assertEqual(visible_after, set(release_track_ids))
        self.assertEqual(self.window.search_field.text(), "")
        self.assertEqual(set(self.window._selected_track_ids()), set(release_track_ids))

    def test_release_browser_selection_scope_tracks_catalog_selection_and_override(self):
        track_ids = [
            self._create_track(index=151, title="Selection Orbit One"),
            self._create_track(index=152, title="Selection Orbit Two"),
            self._create_track(index=153, title="Selection Orbit Three"),
        ]
        self.window.refresh_table()
        self._select_track_ids(track_ids[:2])

        self.window.open_release_browser()
        self.app.processEvents()

        panel = self.window.release_browser_dock.widget()
        state = panel.selection_scope_state()
        self.assertEqual(state.track_ids, tuple(track_ids[:2]))
        self.assertEqual(state.source_label, "Catalog selection")
        self.assertIn("Selection Orbit One", state.preview_text)
        self.assertFalse(state.override_active)

        panel._selection_override_track_ids = [track_ids[2]]
        panel.refresh_selection_scope()
        override_state = panel.selection_scope_state()
        self.assertEqual(override_state.track_ids, (track_ids[2],))
        self.assertTrue(override_state.override_active)
        self.assertEqual(panel.selection_banner.scope_label.text(), "Pinned chooser override")

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
        self.assertEqual(panel.selection_scope_state().track_ids, tuple(track_ids[:2]))

        panel.table.selectRow(0)
        panel.link_selected_tracks()
        detail = self.window.work_service.fetch_work_detail(work_id)
        self.assertEqual(set(detail.track_ids), set(track_ids[:2]))

        panel._selection_override_track_ids = [track_ids[2]]
        panel.refresh_selection_scope()
        panel.link_selected_tracks()
        detail = self.window.work_service.fetch_work_detail(work_id)
        self.assertEqual(set(detail.track_ids), set(track_ids))
        self.assertTrue(panel.selection_scope_state().override_active)
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
        self.assertGreaterEqual(panel.results_table.rowCount(), 1)
        self.assertEqual(panel.results_table.currentRow(), -1)
        self.assertIn("catalog overview", panel.results_status_label.text().lower())

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

    def test_workspace_docks_use_north_tabs_and_remain_tabified_across_fullscreen_cycle(self):
        track_id = self._create_track(index=166, title="Dock Tab Visibility Track")
        self.window.release_service.create_release(
            app_module.ReleasePayload(
                title="Dock Tab Visibility Release",
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
        self.assertEqual(
            self.window.tabPosition(app_module.Qt.RightDockWidgetArea),
            app_module.QTabWidget.North,
        )
        self.assertTrue(self.window.release_browser_dock.widget().isVisible())

        self.window.open_work_manager()
        self.app.processEvents()
        self.assertTrue(self.window.work_manager_dock.widget().isVisible())
        self.assertIn(
            self.window.work_manager_dock,
            self.window.tabifiedDockWidgets(self.window.catalog_table_dock),
        )

        self.window.open_global_search()
        self.app.processEvents()
        self.assertTrue(self.window.global_search_dock.widget().isVisible())
        self.assertIn(
            self.window.global_search_dock,
            self.window.tabifiedDockWidgets(self.window.catalog_table_dock),
        )

        self.window.showFullScreen()
        self.app.processEvents()
        self.window.showNormal()
        self.app.processEvents()

        self.assertEqual(
            self.window.tabPosition(app_module.Qt.RightDockWidgetArea),
            app_module.QTabWidget.North,
        )
        self.assertIn(
            self.window.release_browser_dock,
            self.window.tabifiedDockWidgets(self.window.catalog_table_dock),
        )
        self.assertIn(
            self.window.work_manager_dock,
            self.window.tabifiedDockWidgets(self.window.catalog_table_dock),
        )
        self.assertIn(
            self.window.global_search_dock,
            self.window.tabifiedDockWidgets(self.window.catalog_table_dock),
        )
        self.assertTrue(self.window.global_search_dock.widget().isVisible())

    def test_top_chrome_boundary_persists_across_ribbon_visibility_and_window_state_changes(self):
        track_id = self._create_track(index=168, title="Boundary Validation Track")
        self.window.release_service.create_release(
            app_module.ReleasePayload(
                title="Boundary Validation Release",
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

        tab_bar = self._workspace_dock_tab_bar()
        self.assertEqual(self.window.toolbar.contentsMargins().bottom(), 5)
        self.assertGreaterEqual(tab_bar.geometry().top(), self.window.toolbar.geometry().bottom())
        self.assertEqual(self.window.action_ribbon_toolbar.property("role"), "actionRibbonToolbar")

        self.window.showFullScreen()
        self.app.processEvents()
        self.window.showNormal()
        self.app.processEvents()
        self.assertEqual(self.window.toolbar.contentsMargins().bottom(), 5)
        self.assertGreaterEqual(tab_bar.geometry().top(), self.window.toolbar.geometry().bottom())

        self.window.action_ribbon_visibility_action.trigger()
        self.app.processEvents()
        self.assertFalse(self.window.action_ribbon_toolbar.isVisible())
        self.assertEqual(self.window.toolbar.contentsMargins().bottom(), 5)

        self.window.action_ribbon_visibility_action.trigger()
        self.app.processEvents()
        self.assertTrue(self.window.action_ribbon_toolbar.isVisible())
        self.assertEqual(self.window.toolbar.contentsMargins().bottom(), 5)

        self.window.open_global_search()
        self.app.processEvents()
        self.window.global_search_dock.raise_()
        self.app.processEvents()
        self.window.release_browser_dock.raise_()
        self.app.processEvents()
        self.assertEqual(self.window.toolbar.contentsMargins().bottom(), 5)

    def test_workspace_panels_keep_actions_and_saved_search_controls_inside_scroll_safe_surfaces(
        self,
    ):
        track_id = self._create_track(index=167, title="Reachable Action Track")
        self.window.release_service.create_release(
            app_module.ReleasePayload(
                title="Reachable Action Release",
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

        self.window.resize(980, 620)
        self.window.open_release_browser()
        self.app.processEvents()
        release_panel = self.window.release_browser_dock.widget()
        self.assertEqual(release_panel.overview_tab.property("role"), "workspaceCanvas")
        self.assertEqual(release_panel.tracks_tab.property("role"), "workspaceCanvas")
        self.assertTrue(
            self._is_within_scroll_content(
                release_panel.detail_scroll_area, release_panel.actions_cluster
            )
        )

        self.window.open_global_search()
        self.app.processEvents()
        search_panel = self.window.global_search_dock.widget()
        self.assertEqual(search_panel.right_container.property("role"), "workspaceCanvas")
        self.assertEqual(search_panel.results_tab.property("role"), "workspaceCanvas")
        self.assertEqual(search_panel.relationships_tab.property("role"), "workspaceCanvas")
        self.assertTrue(
            self._is_within_scroll_content(
                search_panel.saved_searches_scroll_area, search_panel.delete_saved_button
            )
        )

        self.window.open_work_manager()
        self.app.processEvents()
        work_panel = self.window.work_manager_dock.widget()
        add_button = self._button_by_text(work_panel.manage_actions_cluster, "Add")
        edit_button = self._button_by_text(work_panel.manage_actions_cluster, "Edit")
        duplicate_button = self._button_by_text(work_panel.manage_actions_cluster, "Duplicate")

        self.assertGreater(edit_button.geometry().left() - add_button.geometry().right(), 0)
        self.assertGreater(duplicate_button.geometry().top() - add_button.geometry().bottom(), 0)
        for button in (add_button, edit_button, duplicate_button):
            self.assertGreaterEqual(button.width(), button.minimumSizeHint().width())

    def test_catalog_managers_open_as_tabified_dock_and_focus_requested_tab(self):
        self.window.open_catalog_managers_dialog(initial_tab="licensees")
        self.app.processEvents()

        panel = self._assert_tabified_workspace_dock(
            self.window.catalog_managers_dock,
            dock_name="catalogManagersDock",
            panel_name="catalogManagersPanel",
        )

        self.assertEqual(panel.tabs.currentWidget(), panel.licensees_tab)
        self.assertEqual(panel.tabs.tabText(panel.tabs.currentIndex()), "Legacy Licensees")
        self.assertTrue(panel.isVisible())

    def test_catalog_managers_tabs_keep_bottom_actions_inside_themed_scroll_surfaces(self):
        self.window.resize(980, 620)
        self.window.open_catalog_managers_dialog(initial_tab="artists")
        self.app.processEvents()

        panel = self.window.catalog_managers_dock.widget()
        for pane, controls in (
            (panel.artists_tab, (panel.artists_tab.refresh_btn, panel.artists_tab.delete_btn)),
            (panel.albums_tab, (panel.albums_tab.refresh_btn, panel.albums_tab.delete_btn)),
            (
                panel.licensees_tab,
                (
                    panel.licensees_tab.add_btn,
                    panel.licensees_tab.rename_btn,
                    panel.licensees_tab.delete_btn,
                ),
            ),
        ):
            panel.tabs.setCurrentWidget(pane)
            self.app.processEvents()
            self.assertIs(panel.tabs.currentWidget(), pane)
            self.assertEqual(pane.property("role"), "workspaceCanvas")
            self.assertEqual(pane.scroll_area.property("role"), "workspaceCanvas")
            self.assertEqual(pane.scroll_area.viewport().property("role"), "workspaceCanvas")
            self.assertEqual(pane.scroll_content.property("role"), "workspaceCanvas")
            for control in controls:
                self.assertTrue(self._is_within_scroll_content(pane.scroll_area, control))

    def test_catalog_menu_hides_top_level_release_creation_and_groups_legacy_tools(self):
        catalog_action = next(
            action for action in self.window.menuBar().actions() if action.text() == "Catalog"
        )
        catalog_menu = catalog_action.menu()
        menu_texts = [action.text() for action in catalog_menu.actions() if action.text()]
        self.assertNotIn("Create Release from Selection…", menu_texts)
        self.assertNotIn("Add Selected Tracks to Release…", menu_texts)
        legacy_action = next(
            action
            for action in catalog_menu.actions()
            if action.menu() is not None and action.text() == "Legacy License Archive"
        )
        legacy_menu = legacy_action.menu()
        legacy_texts = [action.text() for action in legacy_menu.actions() if action.text()]
        self.assertIn("License Browser…", legacy_texts)
        self.assertIn("Migrate Legacy Licenses to Contracts…", legacy_texts)
        self.assertNotIn("create_release", self.window._action_ribbon_specs_by_id)
        self.assertNotIn("add_selected_to_release", self.window._action_ribbon_specs_by_id)

    def test_catalog_menu_hosts_panel_toggle_actions_and_preserves_existing_behavior(self):
        catalog_action = next(
            action for action in self.window.menuBar().actions() if action.text() == "Catalog"
        )
        view_action = next(
            action for action in self.window.menuBar().actions() if action.text() == "View"
        )
        catalog_menu = catalog_action.menu()
        view_menu = view_action.menu()
        catalog_texts = [action.text() for action in catalog_menu.actions() if action.text()]
        view_texts = [action.text() for action in view_menu.actions() if action.text()]

        self.assertIn("Show Add Data Panel", catalog_texts)
        self.assertIn("Show Catalog Table", catalog_texts)
        self.assertNotIn("Show Add Data Panel", view_texts)
        self.assertNotIn("Show Catalog Table", view_texts)
        self.assertEqual(
            self.window._action_ribbon_specs_by_id["show_add_data"]["category"], "Catalog"
        )
        self.assertEqual(
            self.window._action_ribbon_specs_by_id["show_catalog_table"]["category"], "Catalog"
        )

        self.assertFalse(self.window.add_data_dock.isVisible())
        self.window.add_data_action.trigger()
        self.app.processEvents()
        self.assertTrue(self.window.add_data_dock.isVisible())
        self.assertTrue(self.window.settings.value("display/add_data_panel", False, bool))

        self.assertTrue(self.window.catalog_table_dock.isVisible())
        self.window.catalog_table_action.trigger()
        self.app.processEvents()
        self.assertFalse(self.window.catalog_table_dock.isVisible())
        self.assertFalse(self.window.settings.value("display/catalog_table_panel", True, bool))
        self.window.catalog_table_action.trigger()
        self.app.processEvents()
        self.assertTrue(self.window.catalog_table_dock.isVisible())
        self.assertTrue(self.window.settings.value("display/catalog_table_panel", False, bool))

    def test_hidden_catalog_table_does_not_block_workspace_dock_access_or_peer_tabifying(self):
        self.assertTrue(self.window.catalog_table_dock.isVisible())
        self.window.catalog_table_action.trigger()
        self.app.processEvents()
        self.assertFalse(self.window.catalog_table_dock.isVisible())

        self.window.open_release_browser()
        self.app.processEvents()
        self.assertTrue(self.window.release_browser_dock.isVisible())
        self.assertFalse(self.window.release_browser_dock.isHidden())

        self.window.open_work_manager()
        self.app.processEvents()
        self.window.open_global_search()
        self.app.processEvents()
        self.window.open_catalog_managers_dialog()
        self.app.processEvents()

        peer_tabs = set(self.window.tabifiedDockWidgets(self.window.release_browser_dock))
        self.assertIn(self.window.work_manager_dock, peer_tabs)
        self.assertIn(self.window.global_search_dock, peer_tabs)
        self.assertIn(self.window.catalog_managers_dock, peer_tabs)
        self.assertTrue(self.window.work_manager_dock.isVisible())
        self.assertTrue(self.window.global_search_dock.isVisible())
        self.assertTrue(self.window.catalog_managers_dock.isVisible())

    def test_workspace_layout_round_trip_restores_tabified_non_floating_docks(self):
        self.window.open_release_browser()
        self.window.open_work_manager()
        self.window.open_global_search()
        self._drain_events()

        self._reopen_window()

        tabified = set(self.window.tabifiedDockWidgets(self.window.catalog_table_dock))
        self.assertIn(self.window.release_browser_dock, tabified)
        self.assertIn(self.window.work_manager_dock, tabified)
        self.assertIn(self.window.global_search_dock, tabified)
        self.assertFalse(self.window.release_browser_dock.isFloating())
        self.assertFalse(self.window.work_manager_dock.isFloating())
        self.assertFalse(self.window.global_search_dock.isFloating())

    def test_layout_change_persists_latest_arrangement_not_default_arrangement(self):
        self.assertFalse(self.window.add_data_dock.isVisible())
        self.window.add_data_action.trigger()
        self.window.open_release_browser()
        self._drain_events()

        self.window.addDockWidget(
            app_module.Qt.LeftDockWidgetArea, self.window.release_browser_dock
        )
        self.window.tabifyDockWidget(self.window.add_data_dock, self.window.release_browser_dock)
        self.window.release_browser_dock.raise_()
        self._drain_events()

        self._reopen_window()

        self.assertEqual(
            self.window.dockWidgetArea(self.window.release_browser_dock),
            app_module.Qt.LeftDockWidgetArea,
        )
        self.assertIn(
            self.window.release_browser_dock,
            set(self.window.tabifiedDockWidgets(self.window.add_data_dock)),
        )
        self.assertNotIn(
            self.window.release_browser_dock,
            set(self.window.tabifiedDockWidgets(self.window.catalog_table_dock)),
        )

    def test_hidden_catalog_table_round_trip_preserves_peer_tab_group(self):
        self.window.catalog_table_action.trigger()
        self.window.open_release_browser()
        self.window.open_work_manager()
        self.window.open_global_search()
        self._drain_events()

        self._reopen_window()

        self.assertFalse(self.window.catalog_table_dock.isVisible())
        peer_tabs = set(self.window.tabifiedDockWidgets(self.window.release_browser_dock))
        self.assertIn(self.window.work_manager_dock, peer_tabs)
        self.assertIn(self.window.global_search_dock, peer_tabs)
        self.assertFalse(self.window.release_browser_dock.isFloating())

    def test_startup_restore_is_not_overwritten_by_post_init_visibility_sync(self):
        self.window.open_release_browser()
        self._drain_events()

        settings_path = self._close_window()
        settings = app_module.QSettings(str(settings_path), app_module.QSettings.IniFormat)
        settings.setFallbacksEnabled(False)
        settings.setValue("display/catalog_table_panel", False)
        settings.sync()

        self.window = app_module.App()
        self.window.show()
        self._drain_events()

        self.assertTrue(self.window.catalog_table_dock.isVisible())
        self.assertIn(
            self.window.release_browser_dock,
            set(self.window.tabifiedDockWidgets(self.window.catalog_table_dock)),
        )

    def test_close_reopen_round_trip_preserves_core_panel_visibility_without_shutdown_corruption(
        self,
    ):
        self.window.add_data_action.trigger()
        self._drain_events()
        self.assertTrue(self.window.add_data_dock.isVisible())
        self.assertTrue(self.window.catalog_table_dock.isVisible())

        settings_path = self._close_window()
        settings = app_module.QSettings(str(settings_path), app_module.QSettings.IniFormat)
        settings.setFallbacksEnabled(False)
        self.assertTrue(settings.value("display/add_data_panel", False, bool))
        self.assertTrue(settings.value("display/catalog_table_panel", False, bool))

        self.window = app_module.App()
        self.window.show()
        self._drain_events()

        self.assertTrue(self.window.add_data_dock.isVisible())
        self.assertTrue(self.window.catalog_table_dock.isVisible())

    def test_main_window_geometry_round_trip_restores_non_default_outer_state(self):
        self.window.showNormal()
        self.window.resize(1111, 777)
        self._drain_events()

        self._reopen_window()

        self.assertFalse(self.window.isMaximized())
        self.assertEqual(self.window.width(), 1111)
        self.assertEqual(self.window.height(), 777)

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
            self.assertIsInstance(dialog.upc, app_module.QComboBox)
            self.assertTrue(dialog.upc.isEditable())
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
            self.assertIsInstance(dialog.catalog_number, app_module.QComboBox)
            self.assertTrue(dialog.catalog_number.isEditable())
        finally:
            dialog.close()

    def test_add_data_comboboxes_include_release_level_catalog_values(self):
        with self.window.conn:
            self.window.conn.execute(
                """
                INSERT INTO Releases(title, release_type, upc, catalog_number)
                VALUES (?, ?, ?, ?)
                """,
                ("Overview Release", "album", "8720892724990", "CAT-REL-900"),
            )

        self.window.populate_all_comboboxes()

        upc_values = [
            self.window.upc_field.itemText(index) for index in range(self.window.upc_field.count())
        ]
        catalog_values = [
            self.window.catalog_number_field.itemText(index)
            for index in range(self.window.catalog_number_field.count())
        ]
        self.assertIn("8720892724990", upc_values)
        self.assertIn("CAT-REL-900", catalog_values)

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

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
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
from isrc_manager.startup_progress import StartupPhase, startup_phase_label
from tests.qt_test_helpers import pump_events, require_qapplication, wait_for

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
    Information = object()
    Critical = object()
    AcceptRole = object()
    RejectRole = object()
    last_text = ""
    active_splash = None
    suspended_during_exec = False
    messages_during_exec: list[str] = []
    exec_count = 0

    def __init__(self, *_args, **_kwargs):
        self._migrate_button = None
        self._keep_button = None
        self._clicked_button = None

    def setWindowTitle(self, _title):
        return None

    def setWindowModality(self, _modality):
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
        type(self).exec_count += 1
        splash = type(self).active_splash
        type(self).suspended_during_exec = bool(
            getattr(splash, "suspended", False) if splash is not None else False
        )
        type(self).messages_during_exec = list(getattr(splash, "messages", []))
        self._clicked_button = self._keep_button

    def clickedButton(self):
        return self._clicked_button


class _AcceptMigrationMessageBox(_DeferredMigrationMessageBox):
    def exec(self):
        type(self).exec_count += 1
        splash = type(self).active_splash
        type(self).suspended_during_exec = bool(
            getattr(splash, "suspended", False) if splash is not None else False
        )
        type(self).messages_during_exec = list(getattr(splash, "messages", []))
        self._clicked_button = self._migrate_button


class _FakeStartupSplashController:
    def __init__(self):
        self.phase_updates: list[tuple[object, str]] = []
        self.messages: list[str] = []
        self.finish_calls: list[object] = []
        self.show_calls = 0
        self.suspend_calls = 0
        self.resume_calls = 0
        self.suspended = False
        self._finished = False

    def show(self):
        self.show_calls += 1

    def set_phase(self, phase, message_override=None):
        message = str(message_override or startup_phase_label(StartupPhase(phase)))
        self.phase_updates.append((phase, message))
        self.messages.append(message)

    def suspend(self):
        self.suspended = True
        self.suspend_calls += 1

    def resume(self):
        self.suspended = False
        self.resume_calls += 1

    def finish(self, window):
        if self._finished:
            return
        self._finished = True
        self.finish_calls.append(window)


class AppShellTestCase(unittest.TestCase):
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
        self._set_first_launch_prompt_pending(False)
        self.window = app_module.App()
        self.window.show()
        pump_events(app=self.app)

    def tearDown(self):
        try:
            if getattr(self, "window", None) is not None:
                self._close_window()
        finally:
            for patcher in reversed(getattr(self, "_patchers", [])):
                patcher.stop()
            self.tmpdir.cleanup()

    def _fake_writable_location(self, location):
        location_name = getattr(location, "name", str(location)).replace("/", "_")
        path = self.qt_settings_root / location_name
        path.mkdir(parents=True, exist_ok=True)
        return str(path)

    def _drain_events(self, cycles: int = 4) -> None:
        pump_events(app=self.app, cycles=cycles)

    def _cancel_background_tasks(self, window) -> None:
        task_manager = getattr(window, "background_tasks", None)
        if task_manager is None:
            return
        for record in list(getattr(task_manager, "_tasks", {}).values()):
            record.context.cancel()
        if task_manager.has_running_tasks():
            wait_for(
                lambda: not task_manager.has_running_tasks(),
                timeout_ms=1500,
                interval_ms=10,
                app=self.app,
                description="app shell background tasks to finish",
            )

    def _close_window(self) -> str:
        window = getattr(self, "window", None)
        if window is None:
            return ""
        settings_path = window.settings.fileName()
        self._cancel_background_tasks(window)
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

    def _run_bundle_task_inline(self, window, **kwargs):
        class _InlineTaskContext:
            def set_status(self, _message):
                return None

            def report_progress(self, *args, **kwargs):
                del args, kwargs
                return None

            def raise_if_cancelled(self):
                return None

        with window.background_service_factory.open_bundle() as bundle:
            result = kwargs["task_fn"](bundle, _InlineTaskContext())
        on_success = kwargs.get("on_success")
        if callable(on_success):
            on_success(result)
        on_finished = kwargs.get("on_finished")
        if callable(on_finished):
            on_finished()
        return "inline-task"

    def _set_first_launch_prompt_pending(self, pending: bool) -> None:
        settings = self._settings()
        settings.setValue("startup/offer_open_settings_on_first_launch_pending", bool(pending))
        settings.sync()
        settings.deleteLater() if hasattr(settings, "deleteLater") else None

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

    def _create_media_file(self, name: str, payload: bytes) -> Path:
        path = self.root / name
        path.write_bytes(payload)
        return path

    def _table_row_for_track_id(self, track_id: int) -> int:
        for row in range(self.window.table.rowCount()):
            item = self.window.table.item(row, 0)
            if item is None:
                continue
            try:
                current_track_id = int(item.text())
            except Exception:
                continue
            if current_track_id == int(track_id):
                return row
        raise AssertionError(f"Track row not found: {track_id}")

    def _table_context_action_texts(self, row: int, col: int) -> list[str]:
        captured: dict[str, list[str]] = {}

        def _fake_exec(menu_self, *_args, **_kwargs):
            captured["texts"] = [action.text() for action in menu_self.actions() if action.text()]
            return None

        with mock.patch.object(app_module.QMenu, "exec", new=_fake_exec):
            index = self.window.table.model().index(row, col)
            rect = self.window.table.visualRect(index)
            self.window._on_table_context_menu(rect.center())
            self.app.processEvents()
        return captured.get("texts", [])

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

    def case_startup_builds_main_window_with_core_actions(self):
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

    def case_startup_status_messages_cover_real_bootstrap_phases_and_ready_boundary(self):
        self._close_window()
        splash = _FakeStartupSplashController()
        splash.show()

        self.window = app_module.App(startup_feedback=splash)

        self.assertEqual(
            [phase for phase, _message in splash.phase_updates],
            [
                StartupPhase.RESOLVING_STORAGE,
                StartupPhase.INITIALIZING_SETTINGS,
                StartupPhase.OPENING_PROFILE_DB,
                StartupPhase.LOADING_SERVICES,
                StartupPhase.PREPARING_DATABASE,
                StartupPhase.FINALIZING_INTERFACE,
            ],
        )
        self.assertEqual(splash.finish_calls, [])

        self.window.show()
        self.assertEqual(splash.finish_calls, [])
        self._drain_events()

        self.assertEqual(
            [phase for phase, _message in splash.phase_updates[-2:]],
            [StartupPhase.RESTORING_WORKSPACE, StartupPhase.READY],
        )
        self.assertEqual(splash.finish_calls, [self.window])

    def case_startup_first_launch_prompt_can_open_settings_and_clears_pending_flag(self):
        self._close_window()
        self._set_first_launch_prompt_pending(True)

        prompts: list[tuple[str, str]] = []

        class _FakePromptBox:
            def __init__(self):
                self._buttons = {}
                self._clicked_button = None

            def addButton(self, label, _role):
                button = object()
                self._buttons[str(label)] = button
                return button

            def setDefaultButton(self, _button):
                return None

            def clickedButton(self):
                return self._clicked_button

        def _fake_startup_message_box(
            window,
            *,
            title,
            icon,
            text,
            configure=None,
        ):
            _ = icon
            prompts.append((str(title), str(text)))
            box = _FakePromptBox()
            if callable(configure):
                configure(box)
            box._clicked_button = box._buttons.get("Open Settings")
            return box

        with (
            mock.patch.object(
                app_module.App,
                "_run_startup_message_box",
                new=_fake_startup_message_box,
            ),
            mock.patch.object(
                app_module.App, "open_settings_dialog", autospec=True
            ) as open_settings,
        ):
            self.window = app_module.App()
            self.window.show()
            self._drain_events()

        self.assertEqual(len(prompts), 1)
        self.assertEqual(prompts[0][0], "Open Settings")
        self.assertIn("first time", prompts[0][1])
        self.assertFalse(
            self.window.settings.value(
                "startup/offer_open_settings_on_first_launch_pending",
                True,
                bool,
            )
        )
        open_settings.assert_called_once_with(self.window)

        with mock.patch.object(app_module.App, "_run_startup_message_box") as prompt_again:
            self._reopen_window()
            prompt_again.assert_not_called()

    def case_file_menu_groups_xml_import_under_import_exchange_and_preserves_wiring(self):
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
        self.assertIs(submenu_actions[-1], self.window.reset_saved_import_choices_action)
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

    def case_file_menu_groups_exchange_exports_and_saved_import_reset(self):
        file_menu = self._menu_by_text("File")

        export_action = next(
            action
            for action in file_menu.actions()
            if action.menu() is not None and action.text() == "Export Files"
        )
        export_menu = export_action.menu()
        assert export_menu is not None
        export_texts = [action.text() for action in export_menu.actions() if action.text()]
        self.assertEqual(
            export_texts[:3],
            [
                "Export Selected Catalog XML…",
                "Export Full Catalog XML…",
                "Exchange Data",
            ],
        )

        exchange_action = next(
            action
            for action in export_menu.actions()
            if action.menu() is not None and action.text() == "Exchange Data"
        )
        exchange_menu = exchange_action.menu()
        assert exchange_menu is not None
        exchange_texts = [action.text() for action in exchange_menu.actions() if action.text()]
        self.assertIn("Export Selected Exchange CSV…", exchange_texts)
        self.assertIn("Export Full Exchange ZIP Package…", exchange_texts)

        contracts_action = next(
            action
            for action in file_menu.actions()
            if action.menu() is not None and action.text() == "Contracts and Rights Exchange"
        )
        contracts_menu = contracts_action.menu()
        assert contracts_menu is not None
        contracts_texts = [action.text() for action in contracts_menu.actions() if action.text()]
        self.assertIn("Export Contracts and Rights JSON…", contracts_texts)
        self.assertIn("Import Contracts and Rights ZIP Package…", contracts_texts)

    def case_startup_can_defer_legacy_storage_migration_and_keep_current_folder(self):
        self._close_window()
        splash = _FakeStartupSplashController()
        splash.show()
        _DeferredMigrationMessageBox.active_splash = splash
        _DeferredMigrationMessageBox.suspended_during_exec = False
        _DeferredMigrationMessageBox.messages_during_exec = []
        _DeferredMigrationMessageBox.exec_count = 0
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
            self.window = app_module.App(startup_feedback=splash)
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
        self.assertEqual(_DeferredMigrationMessageBox.exec_count, 1)
        self.assertTrue(_DeferredMigrationMessageBox.suspended_during_exec)
        self.assertNotIn(
            "Opening profile database…",
            _DeferredMigrationMessageBox.messages_during_exec,
        )
        self.assertEqual(splash.suspend_calls, 1)
        self.assertEqual(splash.resume_calls, 1)

    def case_startup_migrate_now_bootstraps_logging_and_uses_preferred_root(self):
        self._close_window()
        splash = _FakeStartupSplashController()
        splash.show()
        _AcceptMigrationMessageBox.active_splash = splash
        _AcceptMigrationMessageBox.suspended_during_exec = False
        _AcceptMigrationMessageBox.messages_during_exec = []
        _AcceptMigrationMessageBox.exec_count = 0
        preferred_root = self.qt_settings_root / "AppLocalDataLocation"
        if preferred_root.exists():
            shutil.rmtree(preferred_root)

        legacy_root = self.local_appdata / APP_NAME
        legacy_db = legacy_root / "Database" / "legacy_startup.db"
        self._create_profile_database(legacy_db)
        self._seed_startup_settings_for_legacy_db(legacy_db)

        with mock.patch.object(app_module, "QMessageBox", _AcceptMigrationMessageBox):
            self.window = app_module.App(startup_feedback=splash)
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
        self.assertEqual(
            Path(self.window.current_db_path).resolve(),
            (preferred_root / "Database" / legacy_db.name).resolve(),
        )
        log_files = sorted(preferred_root.joinpath("logs").glob("isrc_manager_*.log"))
        trace_files = sorted(preferred_root.joinpath("logs").glob("isrc_manager_trace_*.jsonl"))
        self.assertTrue(log_files)
        self.assertTrue(trace_files)
        self.assertEqual(_AcceptMigrationMessageBox.exec_count, 2)
        self.assertTrue(_AcceptMigrationMessageBox.suspended_during_exec)
        self.assertEqual(splash.suspend_calls, 2)
        self.assertEqual(splash.resume_calls, 2)

    def case_schema_migration_error_dialog_suspends_splash_during_startup(self):
        self._close_window()
        splash = _FakeStartupSplashController()
        splash.show()
        _DeferredMigrationMessageBox.active_splash = splash
        _DeferredMigrationMessageBox.suspended_during_exec = False
        _DeferredMigrationMessageBox.exec_count = 0
        _DeferredMigrationMessageBox.last_text = ""

        with (
            mock.patch.object(app_module, "QMessageBox", _DeferredMigrationMessageBox),
            mock.patch.object(app_module.App, "migrate_schema", side_effect=RuntimeError("boom")),
        ):
            self.window = app_module.App(startup_feedback=splash)
            self.window.show()
            self._drain_events()

        self.assertTrue(_DeferredMigrationMessageBox.suspended_during_exec)
        self.assertEqual(_DeferredMigrationMessageBox.exec_count, 1)
        self.assertIn("Database migration failed", _DeferredMigrationMessageBox.last_text)
        self.assertEqual(splash.suspend_calls, 1)
        self.assertEqual(splash.resume_calls, 1)

    def case_startup_adopts_valid_preferred_root_when_settings_still_pin_legacy(self):
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

    def case_storage_migration_reopens_active_managed_profile_in_new_root(self):
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

    def case_manual_legacy_cleanup_after_adoption_does_not_recreate_legacy_root(self):
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

    def case_portable_mode_skips_storage_migration_and_legacy_adoption(self):
        self._close_window()
        portable_root = self.root / "portable-root"
        legacy_root = self.local_appdata / APP_NAME
        legacy_db = legacy_root / "Database" / "portable_legacy.db"
        self._create_profile_database(legacy_db)

        def _portable_layout(
            *, settings=None, app_name=APP_NAME, portable=None, active_data_root=None
        ):
            chosen_root = (
                Path(active_data_root).resolve()
                if active_data_root is not None
                else portable_root.resolve()
            )
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
            mock.patch.object(
                app_module, "settings_path", return_value=portable_root / "settings.ini"
            ),
            mock.patch.object(
                app_module, "resolve_app_storage_layout", side_effect=_portable_layout
            ),
            mock.patch.object(app_module, "QMessageBox") as message_box,
        ):
            self.window = app_module.App()
            self.window.show()
            self._drain_events()

        self.assertEqual(self.window.data_root, portable_root.resolve())
        self.assertNotEqual(self.window.data_root, legacy_root.resolve())
        self.assertFalse(message_box.called)

    def case_bundled_themes_are_available_and_not_persisted_as_user_library_entries(self):
        library = self.window._load_theme_library()
        for name in starter_theme_names():
            self.assertIn(name, library)

        self.window._save_theme_library(library)
        stored_payload = json.loads(self.window.settings.value("theme/library_json", "{}", str))
        for name in starter_theme_names():
            self.assertNotIn(name, stored_payload)

    def case_create_new_profile_and_browse_profile_switch_workspace(self):
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

    def case_cancelled_profile_creation_and_restore_leave_shell_idle(self):
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

    def case_filtered_select_all_counts_only_visible_tracks(self):
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

    def case_delete_entry_history_stays_a_single_visible_user_action(self):
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

    def case_catalog_release_browser_opens_as_tabified_dock(self):
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

    def case_release_browser_filter_replaces_active_search_filter(self):
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

    def case_release_browser_selection_scope_tracks_catalog_selection_and_override(self):
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

    def case_work_manager_dock_uses_live_track_selection(self):
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

    def case_global_search_opens_as_dock_and_keeps_entity_navigation_live(self):
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

    def case_workspace_docks_use_north_tabs_and_remain_tabified_across_fullscreen_cycle(self):
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

    def case_top_chrome_boundary_persists_across_ribbon_visibility_and_window_state_changes(self):
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

    def case_workspace_panels_keep_actions_and_saved_search_controls_inside_scroll_safe_surfaces(
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

    def case_catalog_managers_open_as_tabified_dock_and_focus_requested_tab(self):
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

    def case_catalog_managers_tabs_keep_bottom_actions_inside_themed_scroll_surfaces(self):
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

    def case_catalog_menu_hides_top_level_release_creation_and_groups_legacy_tools(self):
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

    def case_catalog_menu_hosts_panel_toggle_actions_and_preserves_existing_behavior(self):
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

    def case_profiles_toolbar_visibility_persists_in_view_preferences(self):
        view_action = next(
            action for action in self.window.menuBar().actions() if action.text() == "View"
        )
        view_menu = view_action.menu()
        view_texts = [action.text() for action in view_menu.actions() if action.text()]

        self.assertIn("Show Profiles Ribbon", view_texts)
        self.assertTrue(self.window.toolbar.isVisible())

        self.window.profiles_toolbar_visibility_action.trigger()
        self.app.processEvents()
        self.assertFalse(self.window.toolbar.isVisible())
        self.assertFalse(self.window.settings.value("display/profiles_toolbar_visible", True, bool))

        self._reopen_window()
        self.assertFalse(self.window.toolbar.isVisible())

        self.window.profiles_toolbar_visibility_action.trigger()
        self.app.processEvents()
        self.assertTrue(self.window.toolbar.isVisible())
        self.assertTrue(self.window.settings.value("display/profiles_toolbar_visible", False, bool))

    def case_album_art_export_uses_album_title_and_bulk_export_stays_on_focused_column(self):
        track_one = self._create_track(
            index=151, title="Comet Signal", album_title="Aurora Heights"
        )
        track_two = self._create_track(index=152, title="Harbor Glow", album_title="Neon Tides")
        cover_one = self._create_media_file("aurora.png", b"\x89PNG\r\n\x1a\naurora")
        cover_two = self._create_media_file("neon.png", b"\x89PNG\r\n\x1a\nneon")
        audio_one = self._create_media_file("aurora.wav", b"RIFFaurora")
        audio_two = self._create_media_file("neon.wav", b"RIFFneon")

        self.window.track_service.set_media_path(
            track_one,
            "album_art",
            cover_one,
            storage_mode=app_module.STORAGE_MODE_DATABASE,
            cursor=self.window.cursor,
        )
        self.window.track_service.set_media_path(
            track_two,
            "album_art",
            cover_two,
            storage_mode=app_module.STORAGE_MODE_DATABASE,
            cursor=self.window.cursor,
        )
        self.window.track_service.set_media_path(
            track_one,
            "audio_file",
            audio_one,
            storage_mode=app_module.STORAGE_MODE_DATABASE,
            cursor=self.window.cursor,
        )
        self.window.track_service.set_media_path(
            track_two,
            "audio_file",
            audio_two,
            storage_mode=app_module.STORAGE_MODE_DATABASE,
            cursor=self.window.cursor,
        )
        self.window.refresh_table_preserve_view(focus_id=track_one)
        self.app.processEvents()

        with mock.patch.object(
            app_module.QFileDialog,
            "getSaveFileName",
            return_value=("", ""),
        ) as get_save_file_name:
            self.window._export_standard_media_for_track(track_one, "album_art")

        suggested_filename = get_save_file_name.call_args.args[2]
        self.assertTrue(suggested_filename.startswith("Aurora Heights"))
        self.assertFalse(suggested_filename.startswith("Comet Signal"))

        self._select_track_ids([track_one, track_two])
        album_art_col = self.window._column_index_by_header("Album Art")
        self.assertGreaterEqual(album_art_col, 0)
        self.assertEqual(
            self.window._focused_media_export_spec(album_art_col),
            {
                "kind": "standard",
                "column_label": "Album Art",
                "media_key": "album_art",
            },
        )
        track_title_col = self.window._column_index_by_header("Track Title")
        self.assertIsNone(self.window._focused_media_export_spec(track_title_col))

        output_dir = self.root / "album-art-export"
        output_dir.mkdir()
        with (
            mock.patch.object(
                app_module.QFileDialog,
                "getExistingDirectory",
                return_value=str(output_dir),
            ),
            mock.patch.object(app_module.QMessageBox, "information"),
        ):
            self.window._export_focused_media_column(
                album_art_col,
                track_ids=[track_one, track_two],
            )

        exported_names = sorted(path.name for path in output_dir.iterdir() if path.is_file())
        self.assertEqual(
            exported_names,
            [
                "Aurora Heights.png",
                "Neon Tides.png",
            ],
        )
        self.assertFalse(any(name.endswith(".wav") for name in exported_names))

    def case_bulk_audio_attach_workflow_matches_files_updates_artists_and_records_history(self):
        track_one = self._create_track(index=401, title="Orbit Lines")
        track_two = self._create_track(index=402, title="Aurora Bloom")
        self.window.refresh_table_preserve_view(focus_id=track_one)
        self.app.processEvents()

        audio_one = self._create_media_file("Orbit Lines.wav", b"RIFForbit")
        audio_two = self._create_media_file("Aurora Bloom.wav", b"RIFFaurora")

        with (
            mock.patch.object(
                app_module.App,
                "_submit_background_bundle_task",
                autospec=True,
                side_effect=self._run_bundle_task_inline,
            ),
            mock.patch.object(
                app_module.QFileDialog,
                "getOpenFileNames",
                return_value=([str(audio_one), str(audio_two)], ""),
            ),
            mock.patch.object(
                app_module.AudioTagService,
                "read_tags",
                return_value=SimpleNamespace(title=None, artist=None),
            ),
            mock.patch.object(
                app_module.BulkAudioAttachDialog,
                "exec",
                return_value=app_module.QDialog.Accepted,
            ),
            mock.patch.object(
                app_module.BulkAudioAttachDialog,
                "selected_artist_name",
                return_value="Synth Unit",
            ),
            mock.patch.object(
                app_module,
                "_prompt_storage_mode_choice",
                return_value=app_module.STORAGE_MODE_DATABASE,
            ),
            mock.patch.object(app_module.QMessageBox, "information") as info_mock,
        ):
            self.window.bulk_attach_audio_files(track_ids=[track_one, track_two])

        audio_one_bytes, _mime_one = self.window.track_service.fetch_media_bytes(
            track_one, "audio_file"
        )
        audio_two_bytes, _mime_two = self.window.track_service.fetch_media_bytes(
            track_two, "audio_file"
        )
        self.assertEqual(audio_one_bytes, b"RIFForbit")
        self.assertEqual(audio_two_bytes, b"RIFFaurora")

        snapshot_one = self.window.track_service.fetch_track_snapshot(track_one)
        snapshot_two = self.window.track_service.fetch_track_snapshot(track_two)
        self.assertEqual(snapshot_one.artist_name, "Synth Unit")
        self.assertEqual(snapshot_two.artist_name, "Synth Unit")

        visible_history = self.window.history_manager.list_entries(limit=5)
        self.assertEqual(visible_history[0].label, "Bulk Attach Audio Files (2 files)")
        info_mock.assert_called_once()
        self.assertIn("Attached audio to 2 track(s).", info_mock.call_args.args[2])
        self.assertIn("Updated the main artist on 2 matched track(s).", info_mock.call_args.args[2])

    def case_history_budget_preflight_can_open_cleanup_dialog(self):
        self.window.settings_mutations.set_history_retention_mode("lean")
        self.window.settings_mutations.set_history_storage_budget_mb(1)

        class _CleanupPromptBox:
            Warning = object()
            AcceptRole = object()
            ActionRole = object()
            Cancel = object()
            last_text = ""

            def __init__(self, *_args, **_kwargs):
                self._cleanup_button = None
                self._clicked_button = None

            def setIcon(self, _icon):
                return None

            def setWindowTitle(self, _title):
                return None

            def setText(self, text):
                type(self).last_text = str(text)

            def addButton(self, label, _role=None):
                button = object()
                if label == "Open Cleanup":
                    self._cleanup_button = button
                return button

            def setDefaultButton(self, _button):
                return None

            def exec(self):
                self._clicked_button = self._cleanup_button

            def clickedButton(self):
                return self._clicked_button

        with (
            mock.patch.object(app_module, "QMessageBox", _CleanupPromptBox),
            mock.patch.object(self.window, "open_history_cleanup_dialog") as open_cleanup,
        ):
            allowed = self.window._prepare_history_storage_for_projected_growth(
                trigger_label="manual snapshot",
                additional_bytes=256 * 1024 * 1024,
                interactive=True,
            )

        self.assertFalse(allowed)
        open_cleanup.assert_called_once_with()
        self.assertIn("Projected usage", _CleanupPromptBox.last_text)
        self.assertIn(
            "Continue anyway, or review History Cleanup first?",
            _CleanupPromptBox.last_text,
        )

    def case_hidden_catalog_table_does_not_block_workspace_dock_access_or_peer_tabifying(self):
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

    def case_workspace_layout_round_trip_restores_tabified_non_floating_docks(self):
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

    def case_layout_change_persists_latest_arrangement_not_default_arrangement(self):
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

    def case_hidden_catalog_table_round_trip_preserves_peer_tab_group(self):
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

    def case_startup_restore_is_not_overwritten_by_post_init_visibility_sync(self):
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

    def case_close_reopen_round_trip_preserves_core_panel_visibility_without_shutdown_corruption(
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

    def case_main_window_geometry_round_trip_restores_non_default_outer_state(self):
        self.window.showNormal()
        self.window.resize(1111, 777)
        self._drain_events()

        self._reopen_window()

        self.assertFalse(self.window.isMaximized())
        self.assertEqual(self.window.width(), 1111)
        self.assertEqual(self.window.height(), 777)

    def case_license_browser_opens_as_tabified_dock_and_applies_track_filter(self):
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

    def case_party_contract_rights_and_asset_windows_open_as_tabified_docks(self):
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

    def case_add_data_panel_uses_tabbed_sections(self):
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

    def case_track_editor_uses_tabbed_sections(self):
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

    def case_track_editor_save_succeeds_without_album_propagation(self):
        track_id = self._create_track(
            index=188, title="Single Edit Source", album_title="Solo Album"
        )

        dialog = app_module.EditDialog(track_id, self.window)
        try:
            dialog.track_title.setText("Single Edit Updated")
            dialog.save_changes()
            wait_for(
                lambda: (
                    not self.window.background_tasks.has_running_tasks()
                    and self.window.track_service.fetch_track_snapshot(track_id).track_title
                    == "Single Edit Updated"
                ),
                timeout_ms=5000,
                interval_ms=25,
                app=self.app,
                description="single-track edit save to finish",
            )
            snapshot = self.window.track_service.fetch_track_snapshot(track_id)
            self.assertIsNotNone(snapshot)
            assert snapshot is not None
            self.assertEqual(snapshot.track_title, "Single Edit Updated")
        finally:
            dialog.close()

    def case_album_entry_track_sections_use_internal_tabs(self):
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

    def case_add_data_comboboxes_include_release_level_catalog_values(self):
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

    def case_gs1_dialog_uses_top_level_workflow_tabs(self):
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


def load_tests(loader, tests, pattern):
    return unittest.TestSuite()

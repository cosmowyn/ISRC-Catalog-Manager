import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    from PySide6.QtWidgets import QApplication
except ImportError as exc:  # pragma: no cover - environment-specific fallback
    QApplication = None
    QT_IMPORT_ERROR = exc
else:
    QT_IMPORT_ERROR = None

import ISRC_manager as app_module
from isrc_manager.constants import APP_NAME
from isrc_manager.services import DatabaseSchemaService, DatabaseSessionService


def _no_catalog_background_refresh(self, *args, **kwargs):
    on_finished = kwargs.get("on_finished")
    if callable(on_finished):
        on_finished()
    return None


class AppShellIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if QApplication is None:
            raise unittest.SkipTest(f"PySide6 QtWidgets unavailable: {QT_IMPORT_ERROR}")
        cls.app = QApplication.instance() or QApplication([])

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


if __name__ == "__main__":
    unittest.main()

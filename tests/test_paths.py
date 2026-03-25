import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PySide6.QtCore import QSettings

from isrc_manager import paths as path_helpers
from isrc_manager.constants import APP_NAME, APP_ORG, SETTINGS_BASENAME
from tests.qt_test_helpers import require_qapplication


class PathLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = require_qapplication()

    def test_portable_layout_uses_binary_directory(self):
        layout = path_helpers.resolve_app_storage_layout(portable=True)

        self.assertTrue(layout.portable)
        self.assertEqual(layout.data_root, path_helpers.BIN_DIR())
        self.assertEqual(layout.settings_root, path_helpers.BIN_DIR())
        self.assertEqual(layout.settings_path, path_helpers.BIN_DIR() / SETTINGS_BASENAME)

    def test_managed_storage_roots_include_contract_template_directories(self):
        layout = path_helpers.resolve_app_storage_layout(portable=True)

        managed_dirs = {path.name for path in layout.iter_standard_dirs()}
        self.assertIn("contract_template_sources", managed_dirs)
        self.assertIn("contract_template_drafts", managed_dirs)
        self.assertIn("contract_template_artifacts", managed_dirs)
        self.assertEqual(
            layout.managed_storage_dir("contract_template_sources"),
            layout.active_data_root / "contract_template_sources",
        )
        self.assertEqual(
            layout.managed_storage_dir("contract_template_drafts"),
            layout.active_data_root / "contract_template_drafts",
        )
        self.assertEqual(
            layout.managed_storage_dir("contract_template_artifacts"),
            layout.active_data_root / "contract_template_artifacts",
        )

    def test_resolve_layout_uses_qt_roots_and_stored_active_data_root(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            qt_settings_root = root / "qt-settings" / APP_NAME
            qt_local_root = root / "qt-local" / APP_NAME
            legacy_root = root / "legacy-root"
            preferred_override = root / "preferred-override"

            settings = QSettings(str(root / "settings.ini"), QSettings.IniFormat)
            settings.setFallbacksEnabled(False)
            settings.setValue(path_helpers.STORAGE_ACTIVE_DATA_ROOT_KEY, str(preferred_override))
            settings.sync()

            def _fake_writable_location(location):
                location_name = getattr(location, "name", str(location))
                if location_name.endswith("AppDataLocation"):
                    return str(qt_settings_root)
                if location_name.endswith("AppLocalDataLocation"):
                    return str(qt_local_root)
                return str(root / location_name)

            with (
                mock.patch.object(
                    path_helpers.QStandardPaths,
                    "writableLocation",
                    side_effect=_fake_writable_location,
                ),
                mock.patch.object(
                    path_helpers,
                    "legacy_data_root",
                    return_value=legacy_root,
                ),
            ):
                layout = path_helpers.resolve_app_storage_layout(settings=settings)

        self.assertEqual(layout.settings_root, qt_settings_root.resolve())
        self.assertEqual(layout.settings_path, qt_settings_root.resolve() / SETTINGS_BASENAME)
        self.assertEqual(layout.preferred_data_root, qt_local_root.resolve())
        self.assertEqual(layout.active_data_root, preferred_override.resolve())
        self.assertEqual(layout.database_dir, preferred_override.resolve() / "Database")
        self.assertEqual(layout.history_dir, preferred_override.resolve() / "history")
        self.assertEqual(layout.backups_dir, preferred_override.resolve() / "backups")
        self.assertEqual(layout.legacy_data_roots, (legacy_root.resolve(),))

    def test_platform_fallback_roots_use_app_named_directories(self):
        cases = (
            (
                "darwin",
                {},
                Path.home() / "Library" / "Application Support" / APP_ORG / APP_NAME,
                Path.home() / "Library" / "Application Support" / APP_ORG / APP_NAME,
            ),
            (
                "linux",
                {},
                Path.home() / ".config" / APP_ORG / APP_NAME,
                Path.home() / ".local" / "share" / APP_ORG / APP_NAME,
            ),
        )

        for platform_name, env_patch, expected_settings, expected_local in cases:
            with self.subTest(platform=platform_name):
                with (
                    mock.patch.object(path_helpers, "QStandardPaths", None),
                    mock.patch.object(
                        path_helpers.sys,
                        "platform",
                        platform_name,
                    ),
                    mock.patch.dict(os.environ, env_patch, clear=False),
                ):
                    self.assertEqual(path_helpers.settings_root(), expected_settings.resolve())
                    self.assertEqual(path_helpers.preferred_data_root(), expected_local.resolve())

        with tempfile.TemporaryDirectory() as tmpdir:
            env_patch = {
                "LOCALAPPDATA": str(Path(tmpdir) / "LocalAppData"),
                "APPDATA": str(Path(tmpdir) / "RoamingAppData"),
            }
            with (
                mock.patch.object(path_helpers, "QStandardPaths", None),
                mock.patch.object(
                    path_helpers.sys,
                    "platform",
                    "win32",
                ),
                mock.patch.dict(os.environ, env_patch, clear=False),
            ):
                self.assertEqual(
                    path_helpers.settings_root(),
                    (Path(env_patch["APPDATA"]) / APP_ORG / APP_NAME).resolve(),
                )
                self.assertEqual(
                    path_helpers.preferred_data_root(),
                    (Path(env_patch["LOCALAPPDATA"]) / APP_ORG / APP_NAME).resolve(),
                )


if __name__ == "__main__":
    unittest.main()

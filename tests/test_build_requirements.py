import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import build


class BuildMetadataTests(unittest.TestCase):
    def test_project_version_reads_from_pyproject(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pyproject = Path(tmpdir) / "pyproject.toml"
            pyproject.write_text(
                '[project]\nname = "isrc-catalog-manager"\nversion = "9.8.7"\n',
                encoding="utf-8",
            )

            version = build._project_version(pyproject)

        self.assertEqual(version, "9.8.7")


class IconResolutionTests(unittest.TestCase):
    def test_windows_prefers_native_ico(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            icons_dir = root / "build_assets" / "icons"
            icons_dir.mkdir(parents=True, exist_ok=True)
            ico = icons_dir / "app_logo.ico"
            ico.write_bytes(b"ico")
            (icons_dir / "app_logo.png").write_bytes(b"png")

            with (
                mock.patch.object(build, "_is_windows", return_value=True),
                mock.patch.object(build, "_is_macos", return_value=False),
            ):
                resolved = build._resolve_icon(root)

        self.assertEqual(resolved, str(ico))

    def test_windows_converts_png_when_ico_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            icons_dir = root / "build_assets" / "icons"
            icons_dir.mkdir(parents=True, exist_ok=True)
            png = icons_dir / "app_logo.png"
            png.write_bytes(b"png")
            converted = root / "build" / "generated_assets" / "icons" / "app_logo.ico"

            with (
                mock.patch.object(build, "_is_windows", return_value=True),
                mock.patch.object(build, "_is_macos", return_value=False),
                mock.patch.object(build, "_convert_image_to_ico_qt", return_value=converted) as convert,
            ):
                resolved = build._resolve_icon(root)

        convert.assert_called_once_with(png, root)
        self.assertEqual(resolved, str(converted))

    def test_macos_converts_png_when_icns_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            icons_dir = root / "build_assets" / "icons"
            icons_dir.mkdir(parents=True, exist_ok=True)
            png = icons_dir / "app_logo.png"
            png.write_bytes(b"png")
            converted = root / "build" / "generated_assets" / "icons" / "app_logo.icns"

            with (
                mock.patch.object(build, "_is_windows", return_value=False),
                mock.patch.object(build, "_is_macos", return_value=True),
                mock.patch.object(
                    build, "_convert_image_to_icns_mac", return_value=converted
                ) as convert,
            ):
                resolved = build._resolve_icon(root)

        convert.assert_called_once_with(png, root)
        self.assertEqual(resolved, str(converted))

    def test_linux_uses_png(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            icons_dir = root / "build_assets" / "icons"
            icons_dir.mkdir(parents=True, exist_ok=True)
            png = icons_dir / "app_logo.png"
            png.write_bytes(b"png")

            with (
                mock.patch.object(build, "_is_windows", return_value=False),
                mock.patch.object(build, "_is_macos", return_value=False),
            ):
                resolved = build._resolve_icon(root)

        self.assertEqual(resolved, str(png))


class SplashResolutionTests(unittest.TestCase):
    def test_resolve_runtime_splash_asset_works_on_macos(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "build_assets").mkdir(parents=True, exist_ok=True)
            png = root / "build_assets" / "splash.png"
            png.write_bytes(b"png")

            with mock.patch.object(build, "_is_macos", return_value=True):
                resolved = build._resolve_runtime_splash_asset(root)

        self.assertEqual(resolved, str(png))


class CommandConstructionTests(unittest.TestCase):
    def test_windows_pyinstaller_command_uses_onefile_and_runtime_splash_only(self):
        build_python = Path("/python")
        entry_script = Path("/project/ISRC_manager.py")

        with (
            mock.patch.object(build, "_is_windows", return_value=True),
            mock.patch.object(build, "_is_macos", return_value=False),
        ):
            cmd = build._pyinstaller_cmd(
                build_python=build_python,
                entry_script=entry_script,
                app_name=build.APP_NAME,
                icon="/project/build_assets/icons/app_logo.ico",
                runtime_splash_asset="/project/build_assets/splash.png",
            )

        self.assertIn("--onefile", cmd)
        self.assertNotIn("--onedir", cmd)
        self.assertNotIn("--splash", cmd)
        self.assertIn("--add-data", cmd)
        self.assertIn("/project/build_assets/splash.png;build_assets", cmd)
        self.assertIn("--icon", cmd)
        self.assertIn("/project/build_assets/icons/app_logo.ico", cmd)

    def test_linux_pyinstaller_command_uses_onedir_and_runtime_splash_only(self):
        build_python = Path("/python")
        entry_script = Path("/project/ISRC_manager.py")

        with (
            mock.patch.object(build, "_is_windows", return_value=False),
            mock.patch.object(build, "_is_macos", return_value=False),
        ):
            cmd = build._pyinstaller_cmd(
                build_python=build_python,
                entry_script=entry_script,
                app_name=build.APP_NAME,
                icon="/project/build_assets/icons/app_logo.png",
                runtime_splash_asset="/project/build_assets/splash.png",
            )

        self.assertIn("--onedir", cmd)
        self.assertNotIn("--onefile", cmd)
        self.assertNotIn("--splash", cmd)
        self.assertIn("--add-data", cmd)
        self.assertIn("/project/build_assets/splash.png:build_assets", cmd)

    def test_macos_pyinstaller_command_keeps_runtime_splash_without_bootloader_splash(self):
        build_python = Path("/python")
        entry_script = Path("/project/ISRC_manager.py")

        with (
            mock.patch.object(build, "_is_windows", return_value=False),
            mock.patch.object(build, "_is_macos", return_value=True),
        ):
            cmd = build._pyinstaller_cmd(
                build_python=build_python,
                entry_script=entry_script,
                app_name=build.APP_NAME,
                icon="/project/build_assets/icons/app_logo.icns",
                runtime_splash_asset="/project/build_assets/splash.png",
            )

        self.assertIn("--onedir", cmd)
        self.assertNotIn("--splash", cmd)
        self.assertIn("--add-data", cmd)
        self.assertIn("/project/build_assets/splash.png:build_assets", cmd)


class ArtifactStagingTests(unittest.TestCase):
    def test_find_built_artifact_prefers_macos_app_bundle(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            app_bundle = root / "dist" / f"{build.APP_NAME}.app"
            app_bundle.mkdir(parents=True, exist_ok=True)

            with (
                mock.patch.object(build, "_is_windows", return_value=False),
                mock.patch.object(build, "_is_macos", return_value=True),
            ):
                artifact = build._find_built_artifact(root)

        self.assertEqual(artifact, app_bundle)

    def test_stage_release_artifact_copies_file_and_writes_manifest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            dist_dir = root / "dist"
            dist_dir.mkdir(parents=True, exist_ok=True)
            artifact = dist_dir / f"{build.APP_NAME}.exe"
            artifact.write_bytes(b"binary")

            with (
                mock.patch.object(build, "_is_windows", return_value=True),
                mock.patch.object(build, "_is_macos", return_value=False),
            ):
                staged = build._stage_release_artifact(
                    artifact,
                    dist_dir,
                    app_version="2.0.0",
                )

            manifest = json.loads((dist_dir / "release_manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(staged.exists())
            self.assertEqual(staged.name, f"{build.APP_NAME}-2.0.0-windows.exe")
            self.assertEqual(manifest["app_version"], "2.0.0")
            self.assertEqual(manifest["platform"], "windows")
            self.assertEqual(manifest["source_artifact"], str(artifact))
            self.assertEqual(manifest["release_artifact"], str(staged))


if __name__ == "__main__":
    unittest.main()

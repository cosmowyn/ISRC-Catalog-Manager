import json
import os
import stat
import subprocess
import tarfile
import tempfile
import unittest
import zipfile
from datetime import datetime
from pathlib import Path
from unittest import mock

import build


def _completed_process(args, returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(
        args=args,
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


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

    def test_build_splash_version_label_appends_integer_date(self):
        label = build._build_splash_version_label(
            "3.1.1",
            build_timestamp=datetime(2026, 4, 17, 1, 2, 3),
        )

        self.assertEqual(label, "Version: 3.1.1-17042026.3723")


class BuildPythonResolutionTests(unittest.TestCase):
    def test_prefers_repo_local_venv_python_before_parent_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "project"
            root.mkdir()
            repo_local = root / ".venv" / "bin" / "python"
            parent = root.parent / ".venv" / "bin" / "python"
            repo_local.parent.mkdir(parents=True, exist_ok=True)
            parent.parent.mkdir(parents=True, exist_ok=True)
            repo_local.write_text("", encoding="utf-8")
            parent.write_text("", encoding="utf-8")

            with (
                mock.patch.object(build, "_is_windows", return_value=False),
                mock.patch.object(build.sys, "executable", "/system/python"),
            ):
                resolved = build._resolve_build_python(root)

        self.assertEqual(resolved, repo_local)

    def test_falls_back_to_parent_directory_venv_python(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "project"
            root.mkdir()
            parent = root.parent / ".venv" / "bin" / "python"
            parent.parent.mkdir(parents=True, exist_ok=True)
            parent.write_text("", encoding="utf-8")

            with (
                mock.patch.object(build, "_is_windows", return_value=False),
                mock.patch.object(build.sys, "executable", "/system/python"),
            ):
                resolved = build._resolve_build_python(root)

        self.assertEqual(resolved, parent)

    def test_preserves_repo_local_symlink_path_instead_of_resolving_base_interpreter(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "project"
            root.mkdir()
            system_python = root / "python3.14"
            system_python.write_text("", encoding="utf-8")
            repo_local = root / ".venv" / "bin" / "python"
            repo_local.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.symlink(system_python, repo_local)
            except (AttributeError, NotImplementedError, OSError) as exc:
                self.skipTest(f"symlinks unavailable in test environment: {exc}")

            with (
                mock.patch.object(build, "_is_windows", return_value=False),
                mock.patch.object(build.sys, "executable", str(system_python.resolve())),
            ):
                resolved = build._resolve_build_python(root)

        self.assertEqual(resolved, repo_local)


class PyInstallerDiscoveryTests(unittest.TestCase):
    def test_posix_prefers_repo_local_venv_executable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            local_exe = root / ".venv" / "bin" / "pyinstaller"
            local_exe.parent.mkdir(parents=True, exist_ok=True)
            local_exe.write_text("", encoding="utf-8")

            with (
                mock.patch.object(build, "_is_windows", return_value=False),
                mock.patch.object(build, "_is_macos", return_value=True),
                mock.patch.object(build.shutil, "which", return_value=None),
                mock.patch.object(
                    build.subprocess,
                    "run",
                    return_value=_completed_process(
                        [str(local_exe), "--version"],
                        stdout="6.15.0\n",
                    ),
                ) as run,
            ):
                selection = build._select_pyinstaller(root, Path("/python"))

        self.assertEqual(selection.launcher_prefix, (str(local_exe),))
        self.assertEqual(selection.label, "repo-local venv executable")
        self.assertEqual(selection.version_text, "6.15.0")
        self.assertIsNone(selection.fallback_reason)
        run.assert_called_once_with(
            [str(local_exe), "--version"],
            capture_output=True,
            text=True,
        )

    def test_windows_prefers_repo_local_executable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            local_exe = root / ".venv" / "Scripts" / "pyinstaller.exe"
            local_exe.parent.mkdir(parents=True, exist_ok=True)
            local_exe.write_bytes(b"exe")

            with (
                mock.patch.object(build, "_is_windows", return_value=True),
                mock.patch.object(build, "_is_macos", return_value=False),
                mock.patch.object(build.shutil, "which", return_value=None),
                mock.patch.object(
                    build.subprocess,
                    "run",
                    return_value=_completed_process(
                        [str(local_exe), "--version"],
                        stdout="6.15.0\n",
                    ),
                ) as run,
            ):
                selection = build._select_pyinstaller(root, Path("/python"))

        self.assertEqual(selection.launcher_prefix, (str(local_exe),))
        self.assertEqual(selection.label, "repo-local Windows executable")
        self.assertEqual(selection.version_text, "6.15.0")
        self.assertIsNone(selection.fallback_reason)
        run.assert_called_once_with(
            [str(local_exe), "--version"],
            capture_output=True,
            text=True,
        )

    def test_windows_falls_back_to_parent_directory_executable_before_module(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "project"
            root.mkdir()
            parent_exe = root.parent / ".venv" / "Scripts" / "pyinstaller.exe"
            parent_exe.parent.mkdir(parents=True, exist_ok=True)
            parent_exe.write_bytes(b"exe")

            with (
                mock.patch.object(build, "_is_windows", return_value=True),
                mock.patch.object(build, "_is_macos", return_value=False),
                mock.patch.object(build.shutil, "which", return_value=None),
                mock.patch.object(
                    build.subprocess,
                    "run",
                    return_value=_completed_process(
                        [str(parent_exe), "--version"],
                        stdout="6.15.0\n",
                    ),
                ) as run,
            ):
                selection = build._select_pyinstaller(root, Path("/python"))

        self.assertEqual(selection.launcher_prefix, (str(parent_exe),))
        self.assertEqual(selection.label, "parent-directory Windows executable")
        self.assertIn("repo-local Windows executable", selection.fallback_reason)
        run.assert_called_once_with(
            [str(parent_exe), "--version"],
            capture_output=True,
            text=True,
        )

    def test_windows_falls_back_to_python_module_when_local_exe_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            build_python = Path("/python")

            with (
                mock.patch.object(build, "_is_windows", return_value=True),
                mock.patch.object(build, "_is_macos", return_value=False),
                mock.patch.object(build.shutil, "which", return_value=None),
                mock.patch.object(
                    build.subprocess,
                    "run",
                    return_value=_completed_process(
                        [str(build_python), "-m", "PyInstaller", "--version"],
                        stdout="6.15.0\n",
                    ),
                ) as run,
            ):
                selection = build._select_pyinstaller(root, build_python)

        self.assertEqual(
            selection.launcher_prefix,
            (str(build_python), "-m", "PyInstaller"),
        )
        self.assertEqual(selection.label, "current interpreter module")
        self.assertIn("repo-local Windows executable", selection.fallback_reason)
        run.assert_called_once_with(
            [str(build_python), "-m", "PyInstaller", "--version"],
            capture_output=True,
            text=True,
        )

    def test_windows_raises_clear_error_when_no_candidate_works(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            build_python = Path("/python")

            with (
                mock.patch.object(build, "_is_windows", return_value=True),
                mock.patch.object(build, "_is_macos", return_value=False),
                mock.patch.object(build.shutil, "which", return_value="/usr/bin/pyinstaller"),
                mock.patch.object(
                    build.subprocess,
                    "run",
                    side_effect=[
                        _completed_process(
                            [str(build_python), "-m", "PyInstaller", "--version"],
                            returncode=1,
                            stderr="No module named PyInstaller",
                        ),
                        _completed_process(
                            ["pyinstaller", "--version"],
                            returncode=1,
                            stderr="pyinstaller failed",
                        ),
                    ],
                ),
            ):
                with self.assertRaises(RuntimeError) as ctx:
                    build._select_pyinstaller(root, build_python)

        message = str(ctx.exception)
        self.assertIn("repo-local Windows executable", message)
        self.assertIn("current interpreter module", message)
        self.assertIn("PATH fallback", message)
        self.assertIn("No module named PyInstaller", message)
        self.assertIn("Action:", message)


class EntryScriptResolutionTests(unittest.TestCase):
    def test_missing_entry_script_mentions_expected_path_and_main_py(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "main.py").write_text("print('legacy')\n", encoding="utf-8")

            with self.assertRaises(FileNotFoundError) as ctx:
                build._resolve_entry_script(root)

        message = str(ctx.exception)
        self.assertIn("ISRC_manager.py", message)
        self.assertIn("main.py", message)
        self.assertIn("No automatic fallback entry script was used", message)


class IconResolutionTests(unittest.TestCase):
    def test_canonical_icon_wins_over_fallback_assets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            icons_dir = root / "build_assets" / "icons"
            resources_dir = root / "resources"
            icons_dir.mkdir(parents=True, exist_ok=True)
            resources_dir.mkdir(parents=True, exist_ok=True)
            canonical = icons_dir / "app_logo.ico"
            canonical.write_bytes(b"ico")
            (resources_dir / "icon.ico").write_bytes(b"ico")
            (root / "icon.ico").write_bytes(b"ico")

            with (
                mock.patch.object(build, "_is_windows", return_value=True),
                mock.patch.object(build, "_is_macos", return_value=False),
            ):
                resolved = build._resolve_icon(root)

        self.assertEqual(resolved.path, canonical.resolve())
        self.assertEqual(resolved.kind, "canonical")
        self.assertIn("selected canonical icon asset", resolved.detail)

    def test_windows_fallback_icon_from_resources_png_is_converted(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            resources_dir = root / "resources"
            resources_dir.mkdir(parents=True, exist_ok=True)
            source_png = (resources_dir / "icon.png").resolve()
            source_png.write_bytes(b"png")
            converted = (root / "build" / "generated_assets" / "icons" / "app_logo.ico").resolve()

            with (
                mock.patch.object(build, "_is_windows", return_value=True),
                mock.patch.object(build, "_is_macos", return_value=False),
                mock.patch.object(
                    build,
                    "_convert_image_to_ico_qt",
                    return_value=converted,
                ) as convert,
            ):
                resolved = build._resolve_icon(root)

        convert.assert_called_once_with(source_png, root)
        self.assertEqual(resolved.path, converted)
        self.assertEqual(resolved.kind, "fallback")
        self.assertIn("resources", resolved.detail)
        self.assertIn("converted", resolved.detail)

    def test_macos_fallback_icon_from_repo_root_png_is_converted(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_png = (root / "icon.png").resolve()
            source_png.write_bytes(b"png")
            converted = (root / "build" / "generated_assets" / "icons" / "app_logo.icns").resolve()

            with (
                mock.patch.object(build, "_is_windows", return_value=False),
                mock.patch.object(build, "_is_macos", return_value=True),
                mock.patch.object(
                    build,
                    "_convert_image_to_icns_mac",
                    return_value=converted,
                ) as convert,
            ):
                resolved = build._resolve_icon(root)

        convert.assert_called_once_with(source_png, root)
        self.assertEqual(resolved.path, converted)
        self.assertEqual(resolved.kind, "fallback")
        self.assertIn("repo root", resolved.detail)
        self.assertIn("converted", resolved.detail)

    def test_linux_uses_canonical_png(self):
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

        self.assertEqual(resolved.path, png.resolve())
        self.assertEqual(resolved.kind, "canonical")


class SplashResolutionTests(unittest.TestCase):
    def test_canonical_splash_wins_over_fallback_resources(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            build_assets = root / "build_assets"
            resources_dir = root / "resources"
            build_assets.mkdir(parents=True, exist_ok=True)
            resources_dir.mkdir(parents=True, exist_ok=True)
            canonical = build_assets / "splash.png"
            canonical.write_bytes(b"png")
            (resources_dir / "splash.png").write_bytes(b"png")

            resolved = build._resolve_runtime_splash_asset(root)

        self.assertEqual(resolved.path, canonical.resolve())
        self.assertEqual(resolved.kind, "canonical")

    def test_fallback_splash_from_resources_is_used(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            resources_dir = root / "resources"
            resources_dir.mkdir(parents=True, exist_ok=True)
            fallback = resources_dir / "splash.png"
            fallback.write_bytes(b"png")

            resolved = build._resolve_runtime_splash_asset(root)

        self.assertEqual(resolved.path, fallback.resolve())
        self.assertEqual(resolved.kind, "fallback")
        self.assertIn("resources", resolved.detail)

    def test_fallback_splash_from_repo_root_is_used(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fallback = root / "splash.png"
            fallback.write_bytes(b"png")

            resolved = build._resolve_runtime_splash_asset(root)

        self.assertEqual(resolved.path, fallback.resolve())
        self.assertEqual(resolved.kind, "fallback")
        self.assertIn("repo root", resolved.detail)

    def test_missing_splash_returns_missing_resolution(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)

            resolved = build._resolve_runtime_splash_asset(root)

        self.assertIsNone(resolved.path)
        self.assertEqual(resolved.kind, "missing")
        self.assertIn("no splash asset found", resolved.detail)

    def test_locate_splash_divider_returns_longest_title_band_run(self):
        from PIL import Image, ImageDraw

        image = Image.new("RGBA", (900, 600), (255, 255, 255, 255))
        draw = ImageDraw.Draw(image)
        draw.line((364, 329, 726, 329), fill=(188, 215, 247, 255), width=1)

        line_start, line_end, line_y = build._locate_splash_divider(image)

        self.assertEqual((line_start, line_end, line_y), (364, 726, 329))

    def test_stamp_runtime_splash_asset_writes_generated_png_above_divider(self):
        from PIL import Image, ImageChops, ImageDraw

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            splash_path = root / "build_assets" / "splash.png"
            splash_path.parent.mkdir(parents=True, exist_ok=True)

            source_image = Image.new("RGBA", (900, 600), (255, 255, 255, 255))
            draw = ImageDraw.Draw(source_image)
            draw.line((364, 329, 726, 329), fill=(188, 215, 247, 255), width=1)
            source_image.save(splash_path, format="PNG")

            stamped = build._stamp_runtime_splash_asset(
                root,
                build.ResolutionResult(
                    path=splash_path.resolve(),
                    kind="canonical",
                    source_label="build_assets",
                    detail="selected canonical splash asset build_assets/splash.png",
                ),
                app_version="3.1.1",
                build_timestamp=datetime(2026, 4, 17, 1, 2, 3),
            )

            original = Image.open(splash_path).convert("RGB")
            generated = Image.open(stamped.path).convert("RGB")
            difference_bbox = ImageChops.difference(original, generated).getbbox()

        self.assertEqual(
            stamped.path,
            (root / "build" / "generated_assets" / "splash.png").resolve(),
        )
        self.assertIsNotNone(difference_bbox)
        self.assertLessEqual(difference_bbox[0], 364)
        self.assertLess(difference_bbox[3], 329)
        self.assertIn("Version: 3.1.1-17042026.3723", stamped.detail)


class CommandConstructionTests(unittest.TestCase):
    def test_windows_pyinstaller_command_uses_selected_executable_and_onefile(self):
        entry_script = Path("/project/ISRC_manager.py")
        launcher = ("C:/repo/.venv/Scripts/pyinstaller.exe",)

        with (
            mock.patch.object(build, "_is_windows", return_value=True),
            mock.patch.object(build, "_is_macos", return_value=False),
        ):
            cmd = build._pyinstaller_cmd(
                pyinstaller_launcher=launcher,
                entry_script=entry_script,
                app_name=build.APP_NAME,
                icon="/project/build_assets/icons/app_logo.ico",
                runtime_splash_asset="/project/build_assets/splash.png",
            )

        self.assertEqual(cmd[0], launcher[0])
        self.assertIn("--onefile", cmd)
        self.assertNotIn("--onedir", cmd)
        self.assertNotIn("--splash", cmd)
        self.assertIn("--add-data", cmd)
        self.assertIn("/project/build_assets/splash.png;build_assets", cmd)
        self.assertIn("--icon", cmd)
        self.assertIn("/project/build_assets/icons/app_logo.ico", cmd)

    def test_linux_pyinstaller_command_uses_module_launcher_and_onedir(self):
        entry_script = Path("/project/ISRC_manager.py")
        launcher = ("/python", "-m", "PyInstaller")

        with (
            mock.patch.object(build, "_is_windows", return_value=False),
            mock.patch.object(build, "_is_macos", return_value=False),
        ):
            cmd = build._pyinstaller_cmd(
                pyinstaller_launcher=launcher,
                entry_script=entry_script,
                app_name=build.APP_NAME,
                icon="/project/build_assets/icons/app_logo.png",
                runtime_splash_asset="/project/build_assets/splash.png",
            )

        self.assertEqual(cmd[:3], list(launcher))
        self.assertIn("--onedir", cmd)
        self.assertNotIn("--onefile", cmd)
        self.assertNotIn("--splash", cmd)
        self.assertIn("--add-data", cmd)
        self.assertIn("/project/build_assets/splash.png:build_assets", cmd)

    def test_macos_pyinstaller_command_keeps_runtime_splash_without_bootloader_splash(self):
        entry_script = Path("/project/ISRC_manager.py")
        launcher = ("/python", "-m", "PyInstaller")

        with (
            mock.patch.object(build, "_is_windows", return_value=False),
            mock.patch.object(build, "_is_macos", return_value=True),
        ):
            cmd = build._pyinstaller_cmd(
                pyinstaller_launcher=launcher,
                entry_script=entry_script,
                app_name=build.APP_NAME,
                icon="/project/build_assets/icons/app_logo.icns",
                runtime_splash_asset="/project/build_assets/splash.png",
            )

        self.assertEqual(cmd[:3], list(launcher))
        self.assertIn("--onedir", cmd)
        self.assertNotIn("--splash", cmd)
        self.assertIn("--add-data", cmd)
        self.assertIn("/project/build_assets/splash.png:build_assets", cmd)


class MainFlowTests(unittest.TestCase):
    def test_main_cleans_build_directories_before_icon_resolution(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            build_dir = root / "build"
            dist_dir = root / "dist"
            build_dir.mkdir(parents=True, exist_ok=True)
            dist_dir.mkdir(parents=True, exist_ok=True)
            (build_dir / "stale.txt").write_text("stale", encoding="utf-8")
            (dist_dir / "stale.txt").write_text("stale", encoding="utf-8")
            artifact = root / "dist" / build.APP_NAME
            staged = root / "dist" / "release" / build.APP_NAME

            selection = build.PyInstallerSelection(
                launcher_prefix=("pyinstaller",),
                verify_cmd=("pyinstaller", "--version"),
                label="PATH fallback",
                version_text="6.15.0",
                fallback_reason="repo-local Windows executable and current interpreter module were unavailable or failed verification",
            )

            def resolve_icon(project_root):
                self.assertFalse((project_root / "build").exists())
                self.assertFalse((project_root / "dist").exists())
                return build.ResolutionResult(
                    path=None,
                    kind="missing",
                    source_label="not found",
                    detail="no icon asset found",
                )

            def run_pyinstaller(cmd, cwd, text, capture_output):
                artifact.parent.mkdir(parents=True, exist_ok=True)
                artifact.write_bytes(b"binary")
                return _completed_process(cmd, stdout="", stderr="")

            with (
                mock.patch.object(build, "PROJECT_ROOT", root),
                mock.patch.object(
                    build, "_resolve_entry_script", return_value=root / build.ENTRY_SCRIPT
                ),
                mock.patch.object(build, "_project_version", return_value="3.1.1"),
                mock.patch.object(build, "_resolve_build_python", return_value=Path("/python")),
                mock.patch.object(build, "_select_pyinstaller", return_value=selection),
                mock.patch.object(
                    build, "_resolve_icon", side_effect=resolve_icon
                ) as resolve_icon_mock,
                mock.patch.object(
                    build,
                    "_resolve_runtime_splash_asset",
                    return_value=build.ResolutionResult(
                        path=None,
                        kind="missing",
                        source_label="not found",
                        detail="no splash asset found",
                    ),
                ),
                mock.patch.object(build, "_print_build_diagnostics"),
                mock.patch.object(build.os, "chdir"),
                mock.patch.object(build.subprocess, "run", side_effect=run_pyinstaller),
                mock.patch.object(build, "_stage_release_artifact", return_value=staged),
                mock.patch.object(
                    build,
                    "_package_release_artifact",
                    return_value=root / "dist" / "release" / "packages" / "app.tar.gz",
                ),
                mock.patch.object(build, "_write_release_manifest"),
                mock.patch.object(build, "_is_windows", return_value=False),
                mock.patch.object(build, "_is_macos", return_value=False),
                mock.patch("builtins.print"),
            ):
                exit_code = build.main()

        self.assertEqual(exit_code, 0)
        resolve_icon_mock.assert_called_once_with(root)

    def test_main_stops_on_missing_pyinstaller_module_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            selection = build.PyInstallerSelection(
                launcher_prefix=("pyinstaller",),
                verify_cmd=("pyinstaller", "--version"),
                label="repo-local venv executable",
                version_text="6.15.0",
                fallback_reason=None,
            )

            with (
                mock.patch.object(build, "PROJECT_ROOT", root),
                mock.patch.object(
                    build, "_resolve_entry_script", return_value=root / build.ENTRY_SCRIPT
                ),
                mock.patch.object(build, "_project_version", return_value="3.1.1"),
                mock.patch.object(build, "_resolve_build_python", return_value=Path("/python")),
                mock.patch.object(build, "_select_pyinstaller", return_value=selection),
                mock.patch.object(
                    build,
                    "_resolve_icon",
                    return_value=build.ResolutionResult(
                        path=None,
                        kind="missing",
                        source_label="not found",
                        detail="no icon asset found",
                    ),
                ),
                mock.patch.object(
                    build,
                    "_resolve_runtime_splash_asset",
                    return_value=build.ResolutionResult(
                        path=None,
                        kind="missing",
                        source_label="not found",
                        detail="no splash asset found",
                    ),
                ),
                mock.patch.object(build, "_print_build_diagnostics"),
                mock.patch.object(build.os, "chdir"),
                mock.patch.object(
                    build.subprocess,
                    "run",
                    return_value=_completed_process(
                        ("pyinstaller",),
                        stdout="",
                        stderr="No module named PyInstaller",
                    ),
                ),
                mock.patch.object(build, "_is_windows", return_value=False),
                mock.patch.object(build, "_is_macos", return_value=True),
                mock.patch("builtins.print"),
            ):
                exit_code = build.main()

        self.assertEqual(exit_code, 1)


class ArtifactStagingTests(unittest.TestCase):
    def test_architecture_tag_normalizes_common_runner_architectures(self):
        self.assertEqual(build._architecture_tag("x86_64"), "x64")
        self.assertEqual(build._architecture_tag("AMD64"), "x64")
        self.assertEqual(build._architecture_tag("arm64"), "arm64")
        self.assertEqual(build._architecture_tag("aarch64"), "arm64")

    def test_release_asset_basename_includes_tagged_version_platform_and_architecture(self):
        with (
            mock.patch.object(build, "_platform_tag", return_value="linux"),
            mock.patch.object(build, "_architecture_tag", return_value="x64"),
        ):
            basename = build._release_asset_basename("3.1.1")

        self.assertEqual(basename, f"{build.APP_NAME}-v3.1.1-linux-x64")

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

    def test_stage_release_artifact_copies_file_without_writing_manifest(self):
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
                    app_version="3.1.1",
                )

            self.assertTrue(staged.exists())
            self.assertEqual(staged.name, f"{build.APP_NAME}-3.1.1-windows.exe")
            self.assertFalse((dist_dir / "release_manifest.json").exists())

    def test_stage_release_artifact_preserves_macos_app_bundle_suffix(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            dist_dir = Path(tmpdir) / "dist"
            app_bundle = dist_dir / f"{build.APP_NAME}.app"
            contents = app_bundle / "Contents"
            contents.mkdir(parents=True)
            (contents / "Info.plist").write_text("plist", encoding="utf-8")

            with (
                mock.patch.object(build, "_is_windows", return_value=False),
                mock.patch.object(build, "_is_macos", return_value=True),
                mock.patch.object(build, "_platform_tag", return_value="macos"),
            ):
                staged = build._stage_release_artifact(
                    app_bundle,
                    dist_dir,
                    app_version="3.1.1",
                )

            self.assertEqual(staged.name, f"{build.APP_NAME}-3.1.1-macos.app")
            self.assertTrue((staged / "Contents" / "Info.plist").is_file())

    def test_write_release_manifest_includes_package_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            dist_dir = Path(tmpdir) / "dist"
            dist_dir.mkdir()
            source = dist_dir / f"{build.APP_NAME}.exe"
            staged = dist_dir / "release" / f"{build.APP_NAME}-3.1.1-windows.exe"
            package = dist_dir / "release" / "packages" / f"{build.APP_NAME}-v3.1.1-windows-x64.zip"

            with (
                mock.patch.object(build, "_platform_tag", return_value="windows"),
                mock.patch.object(build, "_architecture_tag", return_value="x64"),
            ):
                manifest_path = build._write_release_manifest(
                    dist_dir,
                    source,
                    staged,
                    app_version="3.1.1",
                    release_package=package,
                )

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["app_version"], "3.1.1")
            self.assertEqual(manifest["platform"], "windows")
            self.assertEqual(manifest["architecture"], "x64")
            self.assertEqual(manifest["source_artifact"], str(source))
            self.assertEqual(manifest["release_artifact"], str(staged))
            self.assertEqual(manifest["release_package"], str(package))
            self.assertEqual(manifest["release_asset_name"], package.name)

    def test_package_release_artifact_zips_macos_bundle(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            dist_dir = Path(tmpdir) / "dist"
            bundle = dist_dir / "release" / f"{build.APP_NAME}-3.1.1-macos.app"
            contents = bundle / "Contents"
            contents.mkdir(parents=True)
            (contents / "Info.plist").write_text("plist", encoding="utf-8")
            versions_dir = contents / "Frameworks" / "Example.framework" / "Versions"
            real_version_dir = versions_dir / "A"
            real_version_dir.mkdir(parents=True)
            (real_version_dir / "Example").write_text("framework", encoding="utf-8")
            symlink_path = versions_dir / "Current"
            try:
                os.symlink("A", symlink_path, target_is_directory=True)
            except (AttributeError, NotImplementedError, OSError) as exc:
                self.skipTest(f"symlinks unavailable in test environment: {exc}")

            with (
                mock.patch.object(build, "_is_windows", return_value=False),
                mock.patch.object(build, "_is_macos", return_value=True),
                mock.patch.object(build, "_platform_tag", return_value="macos"),
                mock.patch.object(build, "_architecture_tag", return_value="arm64"),
            ):
                package = build._package_release_artifact(
                    bundle,
                    dist_dir,
                    app_version="3.1.1",
                )

            self.assertEqual(package.name, f"{build.APP_NAME}-v3.1.1-macos-arm64.zip")
            self.assertGreater(package.stat().st_size, 0)
            with zipfile.ZipFile(package) as archive:
                self.assertIn(
                    f"{build.APP_NAME}-3.1.1-macos.app/Contents/Info.plist",
                    archive.namelist(),
                )
                symlink_info = archive.getinfo(
                    f"{build.APP_NAME}-3.1.1-macos.app/Contents/Frameworks/"
                    "Example.framework/Versions/Current"
                )
                self.assertEqual(stat.S_IFMT(symlink_info.external_attr >> 16), stat.S_IFLNK)
                self.assertEqual(
                    archive.read(symlink_info.filename).decode("utf-8"),
                    "A",
                )

    def test_stage_release_artifact_preserves_macos_bundle_symlinks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            dist_dir = Path(tmpdir) / "dist"
            bundle = dist_dir / f"{build.APP_NAME}.app"
            versions_dir = bundle / "Contents" / "Frameworks" / "Example.framework" / "Versions"
            real_version_dir = versions_dir / "A"
            real_version_dir.mkdir(parents=True)
            (real_version_dir / "Example").write_text("framework", encoding="utf-8")
            symlink_path = versions_dir / "Current"
            try:
                os.symlink("A", symlink_path, target_is_directory=True)
            except (AttributeError, NotImplementedError, OSError) as exc:
                self.skipTest(f"symlinks unavailable in test environment: {exc}")

            staged = build._stage_release_artifact(bundle, dist_dir, app_version="3.1.1")

            staged_symlink = (
                staged / "Contents" / "Frameworks" / "Example.framework" / "Versions" / "Current"
            )
            self.assertTrue(staged_symlink.is_symlink())
            self.assertEqual(os.readlink(staged_symlink), "A")

    def test_package_release_artifact_creates_linux_tarball(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            dist_dir = Path(tmpdir) / "dist"
            bundle = dist_dir / "release" / f"{build.APP_NAME}-3.1.1-linux"
            bundle.mkdir(parents=True)
            (bundle / build.APP_NAME).write_text("binary", encoding="utf-8")

            with (
                mock.patch.object(build, "_is_windows", return_value=False),
                mock.patch.object(build, "_is_macos", return_value=False),
                mock.patch.object(build, "_platform_tag", return_value="linux"),
                mock.patch.object(build, "_architecture_tag", return_value="x64"),
            ):
                package = build._package_release_artifact(
                    bundle,
                    dist_dir,
                    app_version="3.1.1",
                )

            self.assertEqual(package.name, f"{build.APP_NAME}-v3.1.1-linux-x64.tar.gz")
            self.assertGreater(package.stat().st_size, 0)
            with tarfile.open(package, "r:gz") as archive:
                self.assertIn(
                    f"{build.APP_NAME}-3.1.1-linux/{build.APP_NAME}",
                    archive.getnames(),
                )


if __name__ == "__main__":
    unittest.main()

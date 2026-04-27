import hashlib
import os
import stat
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from isrc_manager.update_checker import ReleaseAsset, ReleaseManifest
from isrc_manager.update_installer import (
    HELPER_MODE_ARGUMENT,
    StagedUpdatePackage,
    UpdateInstallerError,
    backup_path_for_target,
    build_helper_command,
    detect_platform_key,
    download_update_asset,
    extract_update_package,
    launch_update_helper,
    locate_replacement_candidate,
    prepare_update_install_plan,
    resolve_installed_target_path,
    restart_command_for_target,
    select_platform_asset,
)


def _asset(name, url, data=b"package"):
    return ReleaseAsset(name=name, url=url, sha256=hashlib.sha256(data).hexdigest())


def _manifest(version="3.5.4"):
    tag = f"v{version}"
    return ReleaseManifest.from_mapping(
        {
            "version": version,
            "released_at": "2026-04-26",
            "summary": "Update summary.",
            "release_notes_url": (
                "https://github.com/cosmowyn/ISRC-Catalog-Manager/"
                f"blob/main/docs/releases/{tag}.md"
            ),
            "assets": {
                "windows": {
                    "name": f"ISRCManager-{tag}-windows-x64.zip",
                    "url": (
                        "https://github.com/cosmowyn/ISRC-Catalog-Manager/"
                        f"releases/download/{tag}/ISRCManager-{tag}-windows-x64.zip"
                    ),
                    "sha256": "a" * 64,
                },
                "macos": {
                    "name": f"ISRCManager-{tag}-macos-arm64.zip",
                    "url": (
                        "https://github.com/cosmowyn/ISRC-Catalog-Manager/"
                        f"releases/download/{tag}/ISRCManager-{tag}-macos-arm64.zip"
                    ),
                    "sha256": "b" * 64,
                },
                "linux": {
                    "name": f"ISRCManager-{tag}-linux-x64.tar.gz",
                    "url": (
                        "https://github.com/cosmowyn/ISRC-Catalog-Manager/"
                        f"releases/download/{tag}/ISRCManager-{tag}-linux-x64.tar.gz"
                    ),
                    "sha256": "c" * 64,
                },
            },
        }
    )


def _write_zip_file(archive, name, data=b"file", mode=0o644):
    info = zipfile.ZipInfo(name)
    info.create_system = 3
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (stat.S_IFREG | mode) << 16
    archive.writestr(info, data)


def _write_zip_symlink(archive, name, target):
    info = zipfile.ZipInfo(name)
    info.create_system = 3
    info.compress_type = zipfile.ZIP_STORED
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    archive.writestr(info, target)


class UpdateInstallerTests(unittest.TestCase):
    def test_detect_platform_key_normalizes_supported_system_names(self):
        self.assertEqual(detect_platform_key("Windows"), "windows")
        self.assertEqual(detect_platform_key("Darwin"), "macos")
        self.assertEqual(detect_platform_key("Linux"), "linux")
        with self.assertRaises(UpdateInstallerError):
            detect_platform_key("Plan9")

    def test_select_platform_asset_uses_manifest_platform_entry(self):
        asset = select_platform_asset(_manifest(), platform_key="linux")

        self.assertEqual(asset.name, "ISRCManager-v3.5.4-linux-x64.tar.gz")

    def test_download_update_asset_verifies_checksum(self):
        data = b"package"
        asset = _asset(
            "ISRCManager-v3.5.4-linux-x64.tar.gz",
            "https://github.com/cosmowyn/ISRC-Catalog-Manager/releases/download/v3.5.4/pkg",
            data=data,
        )
        with tempfile.TemporaryDirectory() as tmp:
            progress = []
            downloaded = download_update_asset(
                asset,
                Path(tmp),
                fetcher=lambda _url, _timeout: data,
                progress_callback=lambda value, maximum, message: progress.append(
                    (value, maximum, message)
                ),
            )

            self.assertEqual(downloaded.package_path.read_bytes(), data)
            self.assertEqual(downloaded.sha256, hashlib.sha256(data).hexdigest())
            self.assertTrue(progress)

    def test_download_update_asset_rejects_checksum_mismatch(self):
        asset = ReleaseAsset(
            name="ISRCManager-v3.5.4-linux-x64.tar.gz",
            url="https://github.com/cosmowyn/ISRC-Catalog-Manager/releases/download/v3.5.4/pkg",
            sha256="a" * 64,
        )
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(UpdateInstallerError):
                download_update_asset(asset, Path(tmp), fetcher=lambda _url, _timeout: b"bad")
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_safe_zip_extract_finds_windows_executable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "ISRCManager-v3.5.4-windows-x64.zip"
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr("ISRCManager-v3.5.4-windows.exe", b"exe")

            staged = extract_update_package(package, root / "stage", platform_key="windows")

            self.assertEqual(staged.replacement_path.name, "ISRCManager-v3.5.4-windows.exe")

    def test_safe_zip_extract_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "ISRCManager-v3.5.4-windows-x64.zip"
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr("../evil.exe", b"exe")

            with self.assertRaises(UpdateInstallerError):
                extract_update_package(package, root / "stage", platform_key="windows")

    def test_safe_zip_extract_preserves_macos_bundle_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "ISRCManager-v3.5.4-macos-arm64.zip"
            app_name = "ISRCManager-v3.5.4-macos.app"
            executable_name = f"{app_name}/Contents/MacOS/ISRCManager"
            framework_name = f"{app_name}/Contents/Frameworks/libexample.dylib"
            link_name = f"{app_name}/Contents/Resources/libexample.dylib"
            with zipfile.ZipFile(package, "w") as archive:
                _write_zip_file(archive, executable_name, b"#!/bin/sh\n", mode=0o755)
                _write_zip_file(archive, framework_name, b"framework")
                _write_zip_symlink(archive, link_name, "../Frameworks/libexample.dylib")

            staged = extract_update_package(package, root / "stage", platform_key="macos")

            link_path = staged.replacement_path / "Contents" / "Resources" / "libexample.dylib"
            executable_path = staged.replacement_path / "Contents" / "MacOS" / "ISRCManager"
            self.assertTrue(link_path.is_symlink())
            self.assertEqual(os.readlink(link_path), "../Frameworks/libexample.dylib")
            self.assertTrue(os.access(executable_path, os.X_OK))

    def test_safe_zip_extract_rejects_symlink_outside_package_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "ISRCManager-v3.5.4-macos-arm64.zip"
            with zipfile.ZipFile(package, "w") as archive:
                _write_zip_symlink(
                    archive,
                    "ISRCManager-v3.5.4-macos.app/Contents/Resources/escape",
                    "../../../outside",
                )

            with self.assertRaisesRegex(UpdateInstallerError, "outside its package root"):
                extract_update_package(package, root / "stage", platform_key="macos")

    def test_safe_tar_extract_finds_linux_app_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_dir = root / "payload" / "ISRCManager-v3.5.4-linux"
            source_dir.mkdir(parents=True)
            executable = source_dir / "ISRCManager"
            executable.write_text("#!/bin/sh\n", encoding="utf-8")
            executable.chmod(0o755)
            package = root / "ISRCManager-v3.5.4-linux-x64.tar.gz"
            with tarfile.open(package, "w:gz") as archive:
                archive.add(source_dir, arcname=source_dir.name)

            staged = extract_update_package(package, root / "stage", platform_key="linux")

            self.assertEqual(staged.replacement_path.name, "ISRCManager-v3.5.4-linux")

    def test_locate_replacement_candidate_finds_macos_app_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "ISRCManager-v3.5.4-macos.app"
            macos_dir = app / "Contents" / "MacOS"
            macos_dir.mkdir(parents=True)
            executable = macos_dir / "ISRCManager"
            executable.write_text("#!/bin/sh\n", encoding="utf-8")
            executable.chmod(0o755)

            self.assertEqual(locate_replacement_candidate(Path(tmp), "macos"), app)

    def test_installed_target_detection_handles_platform_shapes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mac_exe = root / "ISRCManager.app" / "Contents" / "MacOS" / "ISRCManager"
            mac_exe.parent.mkdir(parents=True)
            mac_exe.write_text("", encoding="utf-8")
            win_exe = root / "ISRCManager.exe"
            win_exe.write_text("", encoding="utf-8")
            linux_dir = root / "ISRCManager"
            linux_dir.mkdir()
            linux_exe = linux_dir / "ISRCManager"
            linux_exe.write_text("", encoding="utf-8")
            (linux_dir / "_internal").mkdir()

            self.assertEqual(
                resolve_installed_target_path(executable=mac_exe, platform_key="macos"),
                (root / "ISRCManager.app").resolve(),
            )
            self.assertEqual(
                resolve_installed_target_path(executable=win_exe, platform_key="windows"),
                win_exe.resolve(),
            )
            self.assertEqual(
                resolve_installed_target_path(executable=linux_exe, platform_key="linux"),
                linux_dir.resolve(),
            )

    def test_restart_command_and_backup_path_are_predictable(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "ISRCManager.app"
            app.mkdir()
            target = Path(tmp) / "ISRCManager"
            target.write_text("#!/bin/sh\n", encoding="utf-8")
            target.chmod(0o755)

            self.assertEqual(
                restart_command_for_target(app, platform_key="macos"),
                ("open", "-n", str(app.resolve())),
            )
            self.assertEqual(
                restart_command_for_target(target, platform_key="linux"), (str(target.resolve()),)
            )
            self.assertEqual(
                backup_path_for_target(target, "3.5.4", timestamp="20260426").name,
                "ISRCManager.backup-before-v3.5.4-20260426",
            )

    def test_helper_command_contains_required_arguments(self):
        command = build_helper_command(
            Path("/tmp/helper"),
            current_pid=123,
            target_path=Path("/Applications/ISRCManager.app"),
            replacement_path=Path("/tmp/new.app"),
            expected_version="3.5.4",
            backup_path=Path("/Applications/ISRCManager.app.backup"),
            restart_command=("open", "-n", "/Applications/ISRCManager.app"),
            log_path=Path("/tmp/update.log"),
        )

        self.assertEqual(command[0], "/tmp/helper")
        self.assertIn(HELPER_MODE_ARGUMENT, command)
        self.assertIn("--restart-json", command)

    def test_prepare_update_plan_rejects_macos_app_translocation_target(self):
        manifest = _manifest()
        translocated_target = Path(
            "/private/var/folders/example/AppTranslocation/UUID/d/ISRCManager.app"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            staged = StagedUpdatePackage(
                package_path=root / "package.zip",
                staging_dir=root / "staging",
                replacement_path=root / "staging" / "ISRCManager.app",
                platform_key="macos",
            )

            with (
                mock.patch("isrc_manager.update_installer.sys.frozen", True, create=True),
                mock.patch(
                    "isrc_manager.update_installer.extract_update_package",
                    return_value=staged,
                ),
                mock.patch(
                    "isrc_manager.update_installer.resolve_installed_target_path",
                    return_value=translocated_target,
                ),
            ):
                with self.assertRaisesRegex(UpdateInstallerError, "App Translocation"):
                    prepare_update_install_plan(
                        manifest,
                        root / "package.zip",
                        cache_root=root,
                        platform_key="macos",
                    )

    def test_launch_update_helper_detaches_process(self):
        calls = []

        def _popen(command, **kwargs):
            calls.append((command, kwargs))
            return mock.Mock()

        launch_update_helper(["/tmp/helper", HELPER_MODE_ARGUMENT], popen_factory=_popen)

        self.assertEqual(calls[0][0], ["/tmp/helper", HELPER_MODE_ARGUMENT])
        self.assertIn("stdin", calls[0][1])


if __name__ == "__main__":
    unittest.main()

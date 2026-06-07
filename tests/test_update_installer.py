import hashlib
import io
import os
import stat
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from isrc_manager import update_installer
from isrc_manager.constants import PACKAGED_APP_NAME
from isrc_manager.update_checker import ReleaseAsset, ReleaseManifest
from isrc_manager.update_installer import (
    HELPER_MODE_ARGUMENT,
    StagedUpdatePackage,
    UpdateInstallerError,
    backup_path_for_target,
    build_helper_command,
    create_helper_runtime_copy,
    detect_platform_key,
    download_update_asset,
    extract_update_package,
    file_sha256,
    install_target_for_replacement,
    launch_update_helper,
    locate_replacement_candidate,
    prepare_update_install_plan,
    resolve_installed_target_path,
    restart_command_for_prepared_install,
    restart_command_for_target,
    select_platform_asset,
    validate_install_destination_is_available,
    validate_install_target_is_replaceable,
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

    def test_select_platform_asset_wraps_missing_platform_error(self):
        with self.assertRaisesRegex(UpdateInstallerError, "No update package"):
            select_platform_asset(_manifest(), platform_key="freebsd")

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

    def test_download_update_asset_can_cancel_before_fetch(self):
        asset = _asset(
            "ISRCManager-v3.5.4-linux-x64.tar.gz",
            "https://github.com/cosmowyn/ISRC-Catalog-Manager/releases/download/v3.5.4/pkg",
        )
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(InterruptedError):
                download_update_asset(
                    asset,
                    Path(tmp),
                    fetcher=mock.Mock(side_effect=AssertionError("fetch should not start")),
                    is_cancelled=lambda: True,
                )
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_download_update_asset_rejects_invalid_empty_large_and_cancelled_fetch(self):
        valid_asset = _asset(
            "ISRCManager-v3.5.4-linux-x64.tar.gz",
            "https://github.com/cosmowyn/ISRC-Catalog-Manager/releases/download/v3.5.4/pkg",
            data=b"package",
        )
        invalid_url_asset = ReleaseAsset(
            name="pkg.zip",
            url="http://example.test/pkg.zip",
            sha256="a" * 64,
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(UpdateInstallerError, "HTTPS"):
                download_update_asset(invalid_url_asset, root, fetcher=lambda *_args: b"data")
            with self.assertRaisesRegex(UpdateInstallerError, "empty"):
                download_update_asset(valid_asset, root, fetcher=lambda *_args: b"")
            with mock.patch.object(update_installer, "MAX_UPDATE_PACKAGE_BYTES", 3):
                with self.assertRaisesRegex(UpdateInstallerError, "unexpectedly large"):
                    download_update_asset(valid_asset, root, fetcher=lambda *_args: b"package")

            cancel_states = iter([False, False, True])
            with self.assertRaises(InterruptedError):
                download_update_asset(
                    valid_asset,
                    root,
                    fetcher=lambda *_args: b"package",
                    is_cancelled=lambda: next(cancel_states),
                )
            self.assertFalse((root / valid_asset.name).exists())

    def test_file_sha256_can_cancel_between_chunks(self):
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / "pkg.bin"
            package.write_bytes(b"x" * (1024 * 1024 + 1))
            cancel_states = iter([False, True])

            with self.assertRaises(InterruptedError):
                file_sha256(package, is_cancelled=lambda: next(cancel_states))

    def test_streaming_update_download_cancels_between_chunks_and_removes_partial_file(self):
        chunks = [b"first", b"second"]

        class _FakeResponse:
            headers = {"Content-Length": str(sum(len(chunk) for chunk in chunks))}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _size):
                if chunks:
                    return chunks.pop(0)
                return b""

        asset = _asset(
            "ISRCManager-v3.5.4-linux-x64.tar.gz",
            "https://github.com/cosmowyn/ISRC-Catalog-Manager/releases/download/v3.5.4/pkg",
            data=b"firstsecond",
        )
        cancelled = False

        def _progress(_value, _maximum, message):
            nonlocal cancelled
            if "Downloading" in str(message):
                cancelled = True

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch(
                "isrc_manager.update_installer.urllib.request.urlopen",
                return_value=_FakeResponse(),
            ) as urlopen:
                with self.assertRaises(InterruptedError):
                    download_update_asset(
                        asset,
                        Path(tmp),
                        progress_callback=_progress,
                        is_cancelled=lambda: cancelled,
                    )

            self.assertFalse((Path(tmp) / asset.name).exists())
            self.assertEqual(urlopen.call_args.kwargs["timeout"], 5.0)

    def test_streaming_update_download_rejects_oversize_and_url_errors(self):
        class _FakeResponse:
            def __init__(self, chunks, *, headers=None):
                self._chunks = list(chunks)
                self.headers = headers or {}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _size):
                if self._chunks:
                    return self._chunks.pop(0)
                return b""

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "pkg.zip"
            with mock.patch.object(update_installer, "MAX_UPDATE_PACKAGE_BYTES", 3):
                with mock.patch(
                    "isrc_manager.update_installer.urllib.request.urlopen",
                    return_value=_FakeResponse(
                        [],
                        headers={"Content-Length": "4"},
                    ),
                ):
                    with self.assertRaisesRegex(UpdateInstallerError, "unexpectedly large"):
                        update_installer._stream_download(
                            "https://example.test/pkg.zip",
                            package,
                            timeout_seconds=45.0,
                            read_timeout_seconds=5.0,
                            progress_callback=None,
                            is_cancelled=None,
                        )
                self.assertFalse(package.exists())

                with mock.patch(
                    "isrc_manager.update_installer.urllib.request.urlopen",
                    return_value=_FakeResponse([b"ab", b"cd"]),
                ):
                    with self.assertRaisesRegex(UpdateInstallerError, "unexpectedly large"):
                        update_installer._stream_download(
                            "https://example.test/pkg.zip",
                            package,
                            timeout_seconds=45.0,
                            read_timeout_seconds=5.0,
                            progress_callback=None,
                            is_cancelled=None,
                        )
                self.assertFalse(package.exists())

            with mock.patch(
                "isrc_manager.update_installer.urllib.request.urlopen",
                side_effect=OSError("network down"),
            ):
                with self.assertRaisesRegex(UpdateInstallerError, "could not be downloaded"):
                    update_installer._stream_download(
                        "https://example.test/pkg.zip",
                        package,
                        timeout_seconds=45.0,
                        read_timeout_seconds=5.0,
                        progress_callback=None,
                        is_cancelled=None,
                    )
            self.assertFalse(package.exists())

    def test_extract_update_package_can_cancel_and_removes_partial_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "ISRCManager-v3.5.4-windows-x64.zip"
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr(f"{PACKAGED_APP_NAME}.exe", b"exe")
            cancelled = False

            def _progress(_value, _maximum, _message):
                nonlocal cancelled
                cancelled = True

            with self.assertRaises(InterruptedError):
                extract_update_package(
                    package,
                    root / "stage",
                    platform_key="windows",
                    progress_callback=_progress,
                    is_cancelled=lambda: cancelled,
                )
            self.assertFalse((root / "stage" / "extracted").exists())

    def test_safe_zip_extract_finds_windows_executable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "ISRCManager-v3.5.4-windows-x64.zip"
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr(f"{PACKAGED_APP_NAME}.exe", b"exe")

            staged = extract_update_package(package, root / "stage", platform_key="windows")

            self.assertEqual(staged.replacement_path.name, f"{PACKAGED_APP_NAME}.exe")

    def test_safe_zip_extract_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "ISRCManager-v3.5.4-windows-x64.zip"
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr("../evil.exe", b"exe")

            with self.assertRaises(UpdateInstallerError):
                extract_update_package(package, root / "stage", platform_key="windows")

    def test_extract_update_package_rejects_missing_and_unsupported_packages(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(UpdateInstallerError, "was not found"):
                extract_update_package(root / "missing.zip", root / "stage", platform_key="linux")

            unsupported = root / "update.dmg"
            unsupported.write_bytes(b"package")
            with self.assertRaisesRegex(UpdateInstallerError, "Unsupported update package type"):
                extract_update_package(unsupported, root / "stage", platform_key="macos")

    def test_safe_zip_extract_preserves_macos_bundle_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "ISRCManager-v3.5.4-macos-arm64.zip"
            app_name = f"{PACKAGED_APP_NAME}.app"
            executable_name = f"{app_name}/Contents/MacOS/{PACKAGED_APP_NAME}"
            framework_name = f"{app_name}/Contents/Frameworks/libexample.dylib"
            link_name = f"{app_name}/Contents/Resources/libexample.dylib"
            with zipfile.ZipFile(package, "w") as archive:
                _write_zip_file(archive, executable_name, b"#!/bin/sh\n", mode=0o755)
                _write_zip_file(archive, framework_name, b"framework")
                _write_zip_symlink(archive, link_name, "../Frameworks/libexample.dylib")

            staged = extract_update_package(package, root / "stage", platform_key="macos")

            link_path = staged.replacement_path / "Contents" / "Resources" / "libexample.dylib"
            executable_path = staged.replacement_path / "Contents" / "MacOS" / PACKAGED_APP_NAME
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
                    f"{PACKAGED_APP_NAME}.app/Contents/Resources/escape",
                    "../../../outside",
                )

            with self.assertRaisesRegex(UpdateInstallerError, "outside its package root"):
                extract_update_package(package, root / "stage", platform_key="macos")

    def test_safe_tar_extract_finds_linux_app_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_dir = root / "payload" / PACKAGED_APP_NAME
            source_dir.mkdir(parents=True)
            executable = source_dir / PACKAGED_APP_NAME
            executable.write_text("#!/bin/sh\n", encoding="utf-8")
            executable.chmod(0o755)
            package = root / "ISRCManager-v3.5.4-linux-x64.tar.gz"
            with tarfile.open(package, "w:gz") as archive:
                archive.add(source_dir, arcname=source_dir.name)

            staged = extract_update_package(package, root / "stage", platform_key="linux")

            self.assertEqual(staged.replacement_path.name, PACKAGED_APP_NAME)

    def test_locate_replacement_candidate_errors_and_linux_direct_executable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            linux_exe = root / PACKAGED_APP_NAME
            linux_exe.write_text("#!/bin/sh\n", encoding="utf-8")
            linux_exe.chmod(0o755)
            self.assertEqual(locate_replacement_candidate(root, "linux"), linux_exe)

            linux_exe.unlink()
            with self.assertRaisesRegex(UpdateInstallerError, "runnable application"):
                locate_replacement_candidate(root, "linux")

            win_root = root / "win"
            win_root.mkdir()
            with self.assertRaisesRegex(UpdateInstallerError, "Windows update package"):
                locate_replacement_candidate(win_root, "windows")

            mac_root = root / "mac"
            (mac_root / f"{PACKAGED_APP_NAME}.app").mkdir(parents=True)
            with self.assertRaisesRegex(UpdateInstallerError, "valid app bundle"):
                locate_replacement_candidate(mac_root, "macos")

    def test_locate_replacement_candidate_finds_macos_app_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / f"{PACKAGED_APP_NAME}.app"
            macos_dir = app / "Contents" / "MacOS"
            macos_dir.mkdir(parents=True)
            executable = macos_dir / PACKAGED_APP_NAME
            executable.write_text("#!/bin/sh\n", encoding="utf-8")
            executable.chmod(0o755)

            self.assertEqual(locate_replacement_candidate(Path(tmp), "macos"), app)

    def test_path_resolution_and_restart_helpers_cover_platform_fallbacks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(UpdateInstallerError, "did not extract correctly"):
                locate_replacement_candidate(root / "missing", "linux")

            mac_exe = root / "python"
            mac_exe.write_text("#!/bin/sh\n", encoding="utf-8")
            self.assertEqual(
                resolve_installed_target_path(executable=mac_exe, platform_key="macos"),
                mac_exe.resolve(),
            )

            linux_exe = root / PACKAGED_APP_NAME
            linux_exe.write_text("#!/bin/sh\n", encoding="utf-8")
            self.assertEqual(
                resolve_installed_target_path(executable=linux_exe, platform_key="linux"),
                linux_exe.resolve(),
            )

            target_dir = root / "replacement"
            replacement_dir = root / "stage" / "replacement"
            replacement_bin = replacement_dir / PACKAGED_APP_NAME
            replacement_bin.parent.mkdir(parents=True)
            replacement_bin.write_text("#!/bin/sh\n", encoding="utf-8")
            replacement_bin.chmod(0o755)
            self.assertEqual(
                restart_command_for_prepared_install(
                    target_dir,
                    replacement_dir,
                    platform_key="linux",
                ),
                (str((target_dir / PACKAGED_APP_NAME).resolve()),),
            )

    def test_installed_target_detection_handles_platform_shapes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mac_exe = root / f"{PACKAGED_APP_NAME}.app" / "Contents" / "MacOS" / PACKAGED_APP_NAME
            mac_exe.parent.mkdir(parents=True)
            mac_exe.write_text("", encoding="utf-8")
            win_exe = root / f"{PACKAGED_APP_NAME}.exe"
            win_exe.write_text("", encoding="utf-8")
            linux_dir = root / PACKAGED_APP_NAME
            linux_dir.mkdir()
            linux_exe = linux_dir / PACKAGED_APP_NAME
            linux_exe.write_text("", encoding="utf-8")
            (linux_dir / "_internal").mkdir()

            self.assertEqual(
                resolve_installed_target_path(executable=mac_exe, platform_key="macos"),
                (root / f"{PACKAGED_APP_NAME}.app").resolve(),
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
            app = Path(tmp) / f"{PACKAGED_APP_NAME}.app"
            app.mkdir()
            target = Path(tmp) / PACKAGED_APP_NAME
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
                f"{PACKAGED_APP_NAME}.backup-before-v3.5.4-20260426",
            )

    def test_restart_commands_raise_when_directory_has_no_executable(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / PACKAGED_APP_NAME
            replacement = Path(tmp) / "replacement"
            target.mkdir()
            replacement.mkdir()

            with self.assertRaisesRegex(UpdateInstallerError, "No restart executable"):
                restart_command_for_target(target, platform_key="linux")
            with self.assertRaisesRegex(UpdateInstallerError, "No restart executable"):
                restart_command_for_prepared_install(
                    target,
                    replacement,
                    platform_key="linux",
                )

    def test_backup_path_deduplicates_and_reports_exhausted_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / PACKAGED_APP_NAME
            target.write_text("app", encoding="utf-8")
            first = backup_path_for_target(target, "3/5/4", timestamp="stamp")
            first.write_text("existing", encoding="utf-8")

            self.assertEqual(
                backup_path_for_target(target, "3/5/4", timestamp="stamp").name,
                f"{PACKAGED_APP_NAME}.backup-before-v3-5-4-stamp-2",
            )
            for index in range(2, 100):
                (target.parent / f"{first.name}-{index}").write_text("existing", encoding="utf-8")
            with self.assertRaisesRegex(UpdateInstallerError, "unique backup path"):
                backup_path_for_target(target, "3/5/4", timestamp="stamp")

    def test_prepared_install_renames_versioned_target_to_packaged_app_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "ISRCManager-3.6.10-macos.app"
            replacement = root / "stage" / f"{PACKAGED_APP_NAME}.app"
            replacement_exe = replacement / "Contents" / "MacOS" / PACKAGED_APP_NAME
            replacement_exe.parent.mkdir(parents=True)
            replacement_exe.write_text("#!/bin/sh\n", encoding="utf-8")
            replacement_exe.chmod(0o755)

            install_target = install_target_for_replacement(target, replacement)

            self.assertEqual(install_target, (root / f"{PACKAGED_APP_NAME}.app").resolve())
            self.assertEqual(
                restart_command_for_prepared_install(target, replacement, platform_key="macos"),
                ("open", "-n", str(install_target)),
            )

    def test_helper_command_contains_required_arguments(self):
        command = build_helper_command(
            Path("/tmp/helper"),
            current_pid=123,
            target_path=Path(f"/Applications/{PACKAGED_APP_NAME}.app"),
            replacement_path=Path(f"/tmp/{PACKAGED_APP_NAME}.app"),
            expected_version="3.5.4",
            backup_path=Path(f"/Applications/{PACKAGED_APP_NAME}.app.backup"),
            handoff_path=Path("/tmp/update-handoff.json"),
            restart_command=("open", "-n", f"/Applications/{PACKAGED_APP_NAME}.app"),
            log_path=Path("/tmp/update.log"),
        )

        self.assertEqual(command[0], "/tmp/helper")
        self.assertIn(HELPER_MODE_ARGUMENT, command)
        self.assertIn("--handoff-json", command)
        self.assertIn("/tmp/update-handoff.json", command)
        self.assertIn("--restart-json", command)

    def test_prepare_update_plan_rejects_macos_app_translocation_target(self):
        manifest = _manifest()
        translocated_target = Path(
            f"/private/var/folders/example/AppTranslocation/UUID/d/{PACKAGED_APP_NAME}.app"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            staged = StagedUpdatePackage(
                package_path=root / "package.zip",
                staging_dir=root / "staging",
                replacement_path=root / "staging" / f"{PACKAGED_APP_NAME}.app",
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

    def test_prepare_update_plan_happy_path_uses_staging_pipeline(self):
        manifest = _manifest()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "package.zip"
            package.write_bytes(b"package")
            target = root / PACKAGED_APP_NAME
            target.write_text("app", encoding="utf-8")
            replacement = root / "staged" / PACKAGED_APP_NAME
            replacement.parent.mkdir()
            replacement.write_text("new app", encoding="utf-8")
            staged = StagedUpdatePackage(
                package_path=package,
                staging_dir=root / "staging",
                replacement_path=replacement,
                platform_key="linux",
            )
            helper = root / "helper"
            helper.write_text("#!/bin/sh\n", encoding="utf-8")
            progress = []

            with (
                mock.patch("isrc_manager.update_installer.sys.frozen", True, create=True),
                mock.patch(
                    "isrc_manager.update_installer.update_workspace_root",
                    return_value=root / "workspace",
                ),
                mock.patch(
                    "isrc_manager.update_installer.extract_update_package",
                    return_value=staged,
                ),
                mock.patch(
                    "isrc_manager.update_installer.resolve_installed_target_path",
                    return_value=target,
                ),
                mock.patch(
                    "isrc_manager.update_installer.validate_install_target_is_replaceable"
                ) as validate_target,
                mock.patch(
                    "isrc_manager.update_installer.validate_install_destination_is_available"
                ) as validate_destination,
                mock.patch(
                    "isrc_manager.update_installer.restart_command_for_prepared_install",
                    return_value=(str(target),),
                ),
                mock.patch(
                    "isrc_manager.update_installer.update_backup_handoff_path",
                    return_value=root / "handoff.json",
                ),
                mock.patch(
                    "isrc_manager.update_installer.create_helper_runtime_copy",
                    return_value=helper,
                ),
            ):
                plan = prepare_update_install_plan(
                    manifest,
                    package,
                    current_pid=1234,
                    cache_root=root,
                    platform_key="linux",
                    progress_callback=lambda *args: progress.append(args),
                )

            validate_target.assert_called_once_with(target, platform_key="linux")
            validate_destination.assert_called_once()
            self.assertEqual(plan.replacement_path, replacement)
            self.assertEqual(plan.handoff_path, root / "handoff.json")
            self.assertEqual(plan.helper_command[0], str(helper))
            self.assertIn("--current-pid", plan.helper_command)
            self.assertIn("1234", plan.helper_command)
            self.assertEqual(progress[-1], (90, 100, "Update installer prepared."))

    def test_prepare_update_plan_rejects_unfrozen_builds(self):
        with mock.patch("isrc_manager.update_installer.sys.frozen", False, create=True):
            with self.assertRaisesRegex(UpdateInstallerError, "packaged builds"):
                prepare_update_install_plan(
                    _manifest(),
                    Path("/tmp/package.zip"),
                    platform_key="linux",
                )

    def test_install_target_validation_and_destination_conflicts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / PACKAGED_APP_NAME
            target.write_text("app", encoding="utf-8")
            validate_install_target_is_replaceable(target, platform_key="linux")

            with self.assertRaisesRegex(UpdateInstallerError, "could not be found"):
                validate_install_target_is_replaceable(root / "missing", platform_key="linux")

            with mock.patch("isrc_manager.update_installer.os.access", return_value=False):
                with self.assertRaisesRegex(UpdateInstallerError, "not writable"):
                    validate_install_target_is_replaceable(target, platform_key="linux")

            destination = root / "renamed"
            destination.write_text("other app", encoding="utf-8")
            with self.assertRaisesRegex(UpdateInstallerError, "target name already exists"):
                validate_install_destination_is_available(target, destination)

    def test_create_helper_runtime_copy_file_and_error_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_exe = root / "python"
            source_exe.write_text("#!/bin/sh\n", encoding="utf-8")
            source_exe.chmod(0o755)
            target = root / "installed.exe"
            target.write_text("app", encoding="utf-8")

            helper = create_helper_runtime_copy(
                target,
                root / "helper",
                platform_key="windows",
                executable=source_exe,
            )
            self.assertTrue(helper.is_file())
            self.assertTrue(os.access(helper, os.X_OK))

            app_dir = root / "app-dir"
            app_dir.mkdir()
            with self.assertRaisesRegex(UpdateInstallerError, "not runnable"):
                create_helper_runtime_copy(
                    app_dir,
                    root / "helper2",
                    platform_key="linux",
                )

            with self.assertRaisesRegex(UpdateInstallerError, "executable was not found"):
                create_helper_runtime_copy(
                    target,
                    root / "helper3",
                    platform_key="windows",
                    executable=root / "missing-python",
                )

    def test_create_helper_runtime_copy_macos_bundle_and_existing_run_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / f"{PACKAGED_APP_NAME}.app"
            executable = app / "Contents" / "MacOS" / PACKAGED_APP_NAME
            executable.parent.mkdir(parents=True)
            executable.write_text("#!/bin/sh\n", encoding="utf-8")
            executable.chmod(0o755)
            helper_root = root / "helper"
            stale_run = helper_root / "run-321-654"
            stale_run.mkdir(parents=True)
            (stale_run / "stale").write_text("old", encoding="utf-8")

            with (
                mock.patch("isrc_manager.update_installer.os.getpid", return_value=321),
                mock.patch("isrc_manager.update_installer.time.time", return_value=654.9),
            ):
                helper_executable = create_helper_runtime_copy(
                    app,
                    helper_root,
                    platform_key="macos",
                )

            self.assertTrue(helper_executable.is_file())
            self.assertIn(f"{PACKAGED_APP_NAME}-updater.app", str(helper_executable))
            self.assertFalse((stale_run / "stale").exists())

            broken_app = root / "Broken.app"
            broken_app.mkdir()
            with self.assertRaisesRegex(UpdateInstallerError, "app bundle is not runnable"):
                create_helper_runtime_copy(
                    broken_app,
                    root / "helper-broken",
                    platform_key="macos",
                )

    def test_archive_private_validation_helpers_cover_unsafe_paths(self):
        with self.assertRaisesRegex(UpdateInstallerError, "absolute path"):
            update_installer._validate_archive_member("/absolute")
        with self.assertRaisesRegex(UpdateInstallerError, "relative path"):
            update_installer._validate_archive_member("app/../evil")
        with self.assertRaisesRegex(UpdateInstallerError, "drive-qualified"):
            update_installer._validate_archive_member("C:/evil")
        with self.assertRaisesRegex(UpdateInstallerError, "unsafe symbolic link"):
            update_installer._collapse_archive_path(("..", "escape"))
        with self.assertRaisesRegex(UpdateInstallerError, "entries below a symbolic link"):
            update_installer._reject_entries_below_symlinks(
                {update_installer.PurePosixPath("app/link/file")},
                {update_installer.PurePosixPath("app/link")},
            )
        with self.assertRaisesRegex(UpdateInstallerError, "invalid target"):
            update_installer._validate_archive_link_target(
                update_installer.PurePosixPath("app/link"),
                "bad\x00target",
            )
        with self.assertRaisesRegex(UpdateInstallerError, "unsafe symbolic link"):
            update_installer._validate_archive_link_target(
                update_installer.PurePosixPath("app/link"),
                "/absolute",
            )
        with self.assertRaisesRegex(UpdateInstallerError, "unsafe symbolic link"):
            update_installer._validate_archive_link_target(
                update_installer.PurePosixPath("app/link"),
                "C:/absolute",
            )
        with self.assertRaisesRegex(UpdateInstallerError, "unsafe symbolic link"):
            update_installer._collapse_archive_path(("app", ".."))

    def test_archive_extract_rejects_duplicate_special_and_invalid_link_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            duplicate_zip = root / "duplicate.zip"
            with zipfile.ZipFile(duplicate_zip, "w") as archive:
                _write_zip_file(archive, f"{PACKAGED_APP_NAME}.exe", b"one")
                with self.assertWarns(UserWarning):
                    _write_zip_file(archive, f"{PACKAGED_APP_NAME}.exe", b"two")
            with self.assertRaisesRegex(UpdateInstallerError, "duplicate archive paths"):
                extract_update_package(
                    duplicate_zip, root / "stage-duplicate", platform_key="windows"
                )

            invalid_link_zip = root / "invalid-link.zip"
            with zipfile.ZipFile(invalid_link_zip, "w") as archive:
                info = zipfile.ZipInfo("app/link")
                info.create_system = 3
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                archive.writestr(info, b"\xff")
            with self.assertRaisesRegex(UpdateInstallerError, "invalid target"):
                extract_update_package(
                    invalid_link_zip, root / "stage-invalid-link", platform_key="linux"
                )

            special_zip = root / "special.zip"
            with zipfile.ZipFile(special_zip, "w") as archive:
                info = zipfile.ZipInfo("app/fifo")
                info.create_system = 3
                info.external_attr = (stat.S_IFIFO | 0o644) << 16
                archive.writestr(info, b"")
            with self.assertRaisesRegex(UpdateInstallerError, "safe symbolic links"):
                extract_update_package(special_zip, root / "stage-special", platform_key="linux")

            duplicate_tar = root / "duplicate.tar.gz"
            payload = b"data"
            with tarfile.open(duplicate_tar, "w:gz") as archive:
                for _index in range(2):
                    info = tarfile.TarInfo("app/file")
                    info.size = len(payload)
                    archive.addfile(info, io.BytesIO(payload))
            with self.assertRaisesRegex(UpdateInstallerError, "duplicate archive paths"):
                extract_update_package(
                    duplicate_tar, root / "stage-duplicate-tar", platform_key="linux"
                )

            hardlink_tar = root / "hardlink.tar.gz"
            with tarfile.open(hardlink_tar, "w:gz") as archive:
                info = tarfile.TarInfo("app/hardlink")
                info.type = tarfile.LNKTYPE
                info.linkname = "app/file"
                archive.addfile(info)
            with self.assertRaisesRegex(UpdateInstallerError, "unsafe tar entries"):
                extract_update_package(hardlink_tar, root / "stage-hardlink", platform_key="linux")

    def test_archive_destination_and_write_conflicts_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            extract_dir = root / "extract"
            extract_dir.mkdir()
            (extract_dir / "app-link").symlink_to("app")
            with self.assertRaisesRegex(UpdateInstallerError, "entries below a symbolic link"):
                update_installer._prepare_archive_destination(
                    extract_dir,
                    update_installer.PurePosixPath("app-link/file"),
                )

            (extract_dir / "conflict").write_text("file", encoding="utf-8")
            with self.assertRaisesRegex(UpdateInstallerError, "conflicting archive paths"):
                update_installer._prepare_archive_destination(
                    extract_dir,
                    update_installer.PurePosixPath("conflict/file"),
                )

            directory_conflict = extract_dir / "directory-conflict"
            directory_conflict.write_text("file", encoding="utf-8")
            with self.assertRaisesRegex(UpdateInstallerError, "conflicting archive paths"):
                update_installer._create_archive_directory(directory_conflict, 0o755)

            symlink_conflict = extract_dir / "symlink-conflict"
            symlink_conflict.write_text("existing", encoding="utf-8")
            with self.assertRaisesRegex(UpdateInstallerError, "conflicting archive paths"):
                update_installer._create_archive_symlink(symlink_conflict, "target")

            zip_destination = extract_dir / "zip-destination"
            zip_destination.mkdir()
            with zipfile.ZipFile(root / "one.zip", "w") as archive:
                _write_zip_file(archive, "file", b"content")
                info = archive.infolist()[0]
                with self.assertRaisesRegex(UpdateInstallerError, "conflicting archive paths"):
                    update_installer._write_zip_file(archive, info, zip_destination, 0o644)

            unreadable_archive = mock.Mock()
            unreadable_archive.extractfile.return_value = None
            with self.assertRaisesRegex(UpdateInstallerError, "unreadable file entry"):
                update_installer._write_tar_file(
                    unreadable_archive,
                    tarfile.TarInfo("file"),
                    extract_dir / "tar-file",
                )

    def test_cache_roots_launch_flags_and_private_name_helpers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch(
                "isrc_manager.update_installer.preferred_data_root",
                return_value=root,
            ):
                cache_root = update_installer.update_cache_root()
                self.assertEqual(cache_root, root / "updates")
                self.assertTrue(cache_root.is_dir())
                workspace = update_installer.update_workspace_root(
                    "3.5.4",
                    platform_key="linux",
                    cache_root=cache_root,
                )
                self.assertEqual(workspace, cache_root / "v3.5.4-linux")

            calls = []

            def _popen(command, **kwargs):
                calls.append((command, kwargs))
                return mock.Mock()

            with (
                mock.patch.object(update_installer.os, "name", "nt"),
                mock.patch.object(
                    update_installer.subprocess, "CREATE_NEW_PROCESS_GROUP", 1, create=True
                ),
                mock.patch.object(update_installer.subprocess, "DETACHED_PROCESS", 2, create=True),
            ):
                launch_update_helper(["helper", HELPER_MODE_ARGUMENT], popen_factory=_popen)

            self.assertEqual(calls[0][1]["creationflags"], 3)
            self.assertIn(
                f"{PACKAGED_APP_NAME}.exe",
                update_installer._preferred_executable_names(include_windows_suffix=True),
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

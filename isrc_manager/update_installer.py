"""Download, verify, stage, and launch packaged application updates."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import IO, cast
from urllib.parse import urlparse

from .constants import APP_NAME, PACKAGED_APP_NAME
from .paths import preferred_data_root
from .update_checker import ReleaseAsset, ReleaseManifest, UpdateCheckError
from .update_handoff import update_backup_handoff_path

APP_NAME_TEXT = str(APP_NAME)
PACKAGED_APP_NAME_TEXT = str(PACKAGED_APP_NAME)
HELPER_MODE_ARGUMENT = "--run-updater-helper"
DEFAULT_UPDATE_DOWNLOAD_TIMEOUT_SECONDS = 45.0
DEFAULT_UPDATE_DOWNLOAD_READ_TIMEOUT_SECONDS = 5.0
MAX_UPDATE_PACKAGE_BYTES = 5 * 1024 * 1024 * 1024
SUPPORTED_PACKAGE_SUFFIXES = (".zip", ".tar.gz", ".tgz")

ProgressCallback = Callable[[int, int, str], None]
DownloadFetcher = Callable[[str, float], bytes]
CancellationCallback = Callable[[], bool]


class UpdateInstallerError(RuntimeError):
    """Raised when a packaged update cannot be installed safely."""


@dataclass(frozen=True, slots=True)
class DownloadedUpdatePackage:
    asset: ReleaseAsset
    package_path: Path
    sha256: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class StagedUpdatePackage:
    package_path: Path
    staging_dir: Path
    replacement_path: Path
    platform_key: str


@dataclass(frozen=True, slots=True)
class UpdateInstallPlan:
    helper_command: tuple[str, ...]
    target_path: Path
    replacement_path: Path
    backup_path: Path
    handoff_path: Path
    restart_command: tuple[str, ...]
    log_path: Path
    expected_version: str


def detect_platform_key(system_name: str | None = None) -> str:
    system = (system_name or platform.system() or "").strip().lower()
    if system in {"windows", "win32"}:
        return "windows"
    if system in {"darwin", "macos", "mac"}:
        return "macos"
    if system == "linux":
        return "linux"
    raise UpdateInstallerError("Automatic updates are not available for this operating system.")


def select_platform_asset(
    manifest: ReleaseManifest,
    *,
    platform_key: str | None = None,
) -> ReleaseAsset:
    key = platform_key or detect_platform_key()
    try:
        return manifest.asset_for_platform(key)
    except UpdateCheckError as exc:
        raise UpdateInstallerError(str(exc)) from exc


def update_cache_root() -> Path:
    root = cast(Path, preferred_data_root(APP_NAME_TEXT)) / "updates"
    root.mkdir(parents=True, exist_ok=True)
    return root


def update_workspace_root(
    version: str,
    *,
    platform_key: str | None = None,
    cache_root: Path | None = None,
) -> Path:
    key = platform_key or detect_platform_key()
    workspace = (cache_root or update_cache_root()) / f"v{version}-{key}"
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


def download_update_asset(
    asset: ReleaseAsset,
    destination_dir: Path,
    *,
    timeout_seconds: float = DEFAULT_UPDATE_DOWNLOAD_TIMEOUT_SECONDS,
    read_timeout_seconds: float = DEFAULT_UPDATE_DOWNLOAD_READ_TIMEOUT_SECONDS,
    fetcher: DownloadFetcher | None = None,
    progress_callback: ProgressCallback | None = None,
    is_cancelled: CancellationCallback | None = None,
) -> DownloadedUpdatePackage:
    _validate_download_url(asset.url)
    destination_dir.mkdir(parents=True, exist_ok=True)
    package_path = destination_dir / asset.name
    package_path.unlink(missing_ok=True)

    try:
        _raise_if_cancelled(is_cancelled)
        _report(progress_callback, 0, 100, "Starting update download...")
        if fetcher is not None:
            data = fetcher(asset.url, float(timeout_seconds))
            _raise_if_cancelled(is_cancelled)
            _reject_unusable_download_size(len(data))
            package_path.write_bytes(data)
        else:
            _stream_download(
                asset.url,
                package_path,
                timeout_seconds=float(timeout_seconds),
                read_timeout_seconds=float(read_timeout_seconds),
                progress_callback=progress_callback,
                is_cancelled=is_cancelled,
            )

        _raise_if_cancelled(is_cancelled)
        size_bytes = package_path.stat().st_size if package_path.exists() else 0
        _reject_unusable_download_size(size_bytes)
        digest = file_sha256(package_path, is_cancelled=is_cancelled)
        _raise_if_cancelled(is_cancelled)
    except InterruptedError:
        package_path.unlink(missing_ok=True)
        raise

    if digest != asset.sha256.lower():
        package_path.unlink(missing_ok=True)
        raise UpdateInstallerError("The downloaded update package did not match its checksum.")
    _report(progress_callback, 40, 100, "Update package verified.")
    return DownloadedUpdatePackage(
        asset=asset,
        package_path=package_path,
        sha256=digest,
        size_bytes=size_bytes,
    )


def file_sha256(path: Path, *, is_cancelled: CancellationCallback | None = None) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            _raise_if_cancelled(is_cancelled)
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def extract_update_package(
    package_path: Path,
    staging_root: Path,
    *,
    platform_key: str | None = None,
    progress_callback: ProgressCallback | None = None,
    is_cancelled: CancellationCallback | None = None,
) -> StagedUpdatePackage:
    _raise_if_cancelled(is_cancelled)
    key = platform_key or detect_platform_key()
    if not package_path.is_file():
        raise UpdateInstallerError(f"Update package was not found: {package_path}")
    if not _supported_package_name(package_path.name):
        raise UpdateInstallerError(f"Unsupported update package type: {package_path.name}")

    extract_dir = staging_root / "extracted"
    if extract_dir.exists():
        shutil.rmtree(extract_dir, ignore_errors=True)
    extract_dir.mkdir(parents=True, exist_ok=True)

    _report(progress_callback, 45, 100, "Extracting update package...")
    try:
        suffixes = "".join(package_path.suffixes[-2:]).lower()
        if package_path.suffix.lower() == ".zip":
            _safe_extract_zip(package_path, extract_dir, is_cancelled=is_cancelled)
        elif suffixes == ".tar.gz" or package_path.suffix.lower() == ".tgz":
            _safe_extract_tar(package_path, extract_dir, is_cancelled=is_cancelled)
        else:
            raise UpdateInstallerError(f"Unsupported update package type: {package_path.name}")
    except InterruptedError:
        shutil.rmtree(extract_dir, ignore_errors=True)
        raise

    _raise_if_cancelled(is_cancelled)
    replacement = locate_replacement_candidate(extract_dir, key)
    _report(progress_callback, 70, 100, "Update package staged.")
    return StagedUpdatePackage(
        package_path=package_path,
        staging_dir=extract_dir,
        replacement_path=replacement,
        platform_key=key,
    )


def locate_replacement_candidate(extract_dir: Path, platform_key: str) -> Path:
    if not extract_dir.is_dir():
        raise UpdateInstallerError("The update package did not extract correctly.")
    key = detect_platform_key(platform_key)
    if key == "macos":
        candidates = sorted(path for path in extract_dir.rglob("*.app") if path.is_dir())
        for candidate in candidates:
            if _macos_app_executable(candidate) is not None:
                return candidate
        raise UpdateInstallerError("The macOS update package did not contain a valid app bundle.")
    if key == "windows":
        candidates = sorted(path for path in extract_dir.rglob("*.exe") if path.is_file())
        if not candidates:
            raise UpdateInstallerError("The Windows update package did not contain an executable.")
        return _prefer_app_named_path(candidates)

    direct_children = sorted(extract_dir.iterdir())
    directory_candidates = [path for path in direct_children if path.is_dir()]
    for candidate in directory_candidates:
        if _find_executable_in_directory(candidate) is not None:
            return candidate
    executable_files = [
        path for path in direct_children if path.is_file() and os.access(path, os.X_OK)
    ]
    if executable_files:
        return _prefer_app_named_path(executable_files)
    raise UpdateInstallerError("The Linux update package did not contain a runnable application.")


def resolve_installed_target_path(
    *,
    executable: Path | None = None,
    platform_key: str | None = None,
) -> Path:
    key = platform_key or detect_platform_key()
    exe_path = (executable or Path(sys.executable)).resolve()
    if key == "macos":
        for parent in (exe_path, *exe_path.parents):
            if parent.suffix == ".app" and parent.is_dir():
                return parent
        return exe_path
    if key == "windows":
        return exe_path
    if key == "linux" and (exe_path.parent / "_internal").exists():
        return exe_path.parent
    return exe_path


def restart_command_for_target(
    target_path: Path, *, platform_key: str | None = None
) -> tuple[str, ...]:
    key = platform_key or detect_platform_key()
    target = target_path.resolve()
    if key == "macos" and target.suffix == ".app":
        return ("open", "-n", str(target))
    if target.is_dir():
        executable = _find_executable_in_directory(target)
        if executable is None:
            raise UpdateInstallerError(f"No restart executable was found inside {target}.")
        return (str(executable),)
    return (str(target),)


def install_target_for_replacement(target_path: Path, replacement_path: Path) -> Path:
    target = target_path.resolve()
    replacement_name = str(replacement_path.name or "").strip()
    if replacement_name and replacement_name != target.name:
        return (target.parent / replacement_name).resolve()
    return target


def restart_command_for_prepared_install(
    target_path: Path,
    replacement_path: Path,
    *,
    platform_key: str | None = None,
) -> tuple[str, ...]:
    key = platform_key or detect_platform_key()
    install_target = install_target_for_replacement(target_path, replacement_path)
    if key == "macos" and install_target.suffix == ".app":
        return ("open", "-n", str(install_target))
    if replacement_path.is_dir():
        executable = _find_executable_in_directory(replacement_path)
        if executable is None:
            raise UpdateInstallerError(
                f"No restart executable was found inside {replacement_path}."
            )
        relative_executable = executable.relative_to(replacement_path)
        return (str((install_target / relative_executable).resolve()),)
    return (str(install_target),)


def backup_path_for_target(
    target_path: Path,
    expected_version: str,
    *,
    timestamp: str | None = None,
) -> Path:
    clean_version = "".join(
        char if char.isalnum() or char in {".", "-", "_"} else "-" for char in expected_version
    ).strip(".-_")
    stamp = timestamp or time.strftime("%Y%m%d-%H%M%S")
    candidate = target_path.parent / f"{target_path.name}.backup-before-v{clean_version}-{stamp}"
    if not candidate.exists():
        return candidate
    for index in range(2, 100):
        indexed = target_path.parent / f"{candidate.name}-{index}"
        if not indexed.exists():
            return indexed
    raise UpdateInstallerError("Could not choose a unique backup path for the current app.")


def prepare_update_install_plan(
    manifest: ReleaseManifest,
    package_path: Path,
    *,
    current_pid: int | None = None,
    cache_root: Path | None = None,
    platform_key: str | None = None,
    progress_callback: ProgressCallback | None = None,
    is_cancelled: CancellationCallback | None = None,
) -> UpdateInstallPlan:
    if not getattr(sys, "frozen", False):
        raise UpdateInstallerError("Automatic installation is only available in packaged builds.")

    _raise_if_cancelled(is_cancelled)
    key = platform_key or detect_platform_key()
    select_platform_asset(manifest, platform_key=key)
    workspace = update_workspace_root(manifest.version, platform_key=key, cache_root=cache_root)
    staged = extract_update_package(
        package_path,
        workspace / "staging",
        platform_key=key,
        progress_callback=progress_callback,
        is_cancelled=is_cancelled,
    )
    _raise_if_cancelled(is_cancelled)
    target = resolve_installed_target_path(platform_key=key)
    validate_install_target_is_replaceable(target, platform_key=key)
    install_target = install_target_for_replacement(target, staged.replacement_path)
    validate_install_destination_is_available(target, install_target)
    restart_command = restart_command_for_prepared_install(
        target,
        staged.replacement_path,
        platform_key=key,
    )
    backup_path = backup_path_for_target(target, manifest.version)
    handoff_path = update_backup_handoff_path(workspace.parent)
    log_path = workspace / "install.log"
    _raise_if_cancelled(is_cancelled)
    helper_executable = create_helper_runtime_copy(
        target,
        workspace / "helper",
        platform_key=key,
    )
    _raise_if_cancelled(is_cancelled)
    helper_command = build_helper_command(
        helper_executable,
        current_pid=current_pid or os.getpid(),
        target_path=target,
        replacement_path=staged.replacement_path,
        expected_version=manifest.version,
        backup_path=backup_path,
        handoff_path=handoff_path,
        restart_command=restart_command,
        log_path=log_path,
    )
    _report(progress_callback, 90, 100, "Update installer prepared.")
    return UpdateInstallPlan(
        helper_command=helper_command,
        target_path=install_target,
        replacement_path=staged.replacement_path,
        backup_path=backup_path,
        handoff_path=handoff_path,
        restart_command=restart_command,
        log_path=log_path,
        expected_version=manifest.version,
    )


def validate_install_target_is_replaceable(
    target_path: Path,
    *,
    platform_key: str | None = None,
) -> None:
    key = platform_key or detect_platform_key()
    target = target_path.resolve()
    if key == "macos" and _is_macos_app_translocation_path(target):
        raise UpdateInstallerError(
            "Automatic updates cannot replace an app running from macOS App Translocation. "
            "Move ISRC Catalog Manager to /Applications, or another writable install folder, "
            "launch it from there, then check for updates again."
        )
    if not target.exists():
        raise UpdateInstallerError(f"The installed application could not be found: {target}")
    if not os.access(target.parent, os.W_OK):
        raise UpdateInstallerError(
            "Automatic updates cannot replace the installed application because its folder is "
            f"not writable: {target.parent}. Move the app to a writable install folder, then "
            "check for updates again."
        )


def validate_install_destination_is_available(current_target: Path, install_target: Path) -> None:
    current = current_target.resolve()
    destination = install_target.resolve()
    if destination != current and destination.exists():
        raise UpdateInstallerError(
            "Automatic updates cannot rename the installed application because the target name "
            f"already exists: {destination}. Move or remove that app, then check for updates "
            "again."
        )


def create_helper_runtime_copy(
    target_path: Path,
    helper_root: Path,
    *,
    platform_key: str | None = None,
    executable: Path | None = None,
) -> Path:
    key = platform_key or detect_platform_key()
    helper_root.mkdir(parents=True, exist_ok=True)
    run_dir = helper_root / f"run-{os.getpid()}-{int(time.time())}"
    if run_dir.exists():
        shutil.rmtree(run_dir, ignore_errors=True)
    run_dir.mkdir(parents=True, exist_ok=True)

    target = target_path.resolve()
    if key == "macos" and target.suffix == ".app" and target.is_dir():
        helper_app = run_dir / f"{target.stem}-updater{target.suffix}"
        shutil.copytree(target, helper_app, symlinks=True)
        helper_executable = _macos_app_executable(helper_app)
        if helper_executable is None:
            raise UpdateInstallerError("The copied updater app bundle is not runnable.")
        return helper_executable

    if target.is_dir():
        helper_dir = run_dir / f"{target.name}-updater"
        shutil.copytree(target, helper_dir, symlinks=True)
        helper_executable = _find_executable_in_directory(helper_dir)
        if helper_executable is None:
            raise UpdateInstallerError("The copied updater application folder is not runnable.")
        return helper_executable

    source_executable = (executable or Path(sys.executable)).resolve()
    if not source_executable.is_file():
        raise UpdateInstallerError(
            f"The updater helper executable was not found: {source_executable}"
        )
    helper_executable = run_dir / source_executable.name
    shutil.copy2(source_executable, helper_executable)
    helper_executable.chmod(helper_executable.stat().st_mode | stat.S_IXUSR)
    return helper_executable


def _is_macos_app_translocation_path(path: Path) -> bool:
    return any(part.lower() == "apptranslocation" for part in path.parts)


def build_helper_command(
    helper_executable: Path,
    *,
    current_pid: int,
    target_path: Path,
    replacement_path: Path,
    expected_version: str,
    backup_path: Path,
    handoff_path: Path,
    restart_command: Sequence[str],
    log_path: Path,
) -> tuple[str, ...]:
    return (
        str(helper_executable),
        HELPER_MODE_ARGUMENT,
        "--current-pid",
        str(int(current_pid)),
        "--target",
        str(target_path),
        "--replacement",
        str(replacement_path),
        "--expected-version",
        str(expected_version),
        "--backup",
        str(backup_path),
        "--handoff-json",
        str(handoff_path),
        "--restart-json",
        json.dumps(list(restart_command)),
        "--log",
        str(log_path),
    )


def launch_update_helper(
    command: Sequence[str],
    *,
    popen_factory: Callable[..., subprocess.Popen] = subprocess.Popen,
) -> None:
    kwargs: dict[str, object] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if os.name == "nt":
        creationflags = int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)) | int(
            getattr(subprocess, "DETACHED_PROCESS", 0)
        )
        kwargs["creationflags"] = creationflags
    else:
        kwargs["start_new_session"] = True
    popen_factory(list(command), **kwargs)


def _stream_download(
    url: str,
    package_path: Path,
    *,
    timeout_seconds: float,
    read_timeout_seconds: float,
    progress_callback: ProgressCallback | None,
    is_cancelled: CancellationCallback | None,
) -> None:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/octet-stream, */*",
            "User-Agent": "ISRC-Catalog-Manager-Updater",
        },
    )
    request_timeout = max(0.5, min(float(timeout_seconds), float(read_timeout_seconds)))
    try:
        _raise_if_cancelled(is_cancelled)
        with urllib.request.urlopen(request, timeout=request_timeout) as response:
            length_header = response.headers.get("Content-Length")
            expected_size = int(length_header) if length_header and length_header.isdigit() else 0
            if expected_size > MAX_UPDATE_PACKAGE_BYTES:
                raise UpdateInstallerError("The update package is unexpectedly large.")
            downloaded = 0
            with package_path.open("wb") as handle:
                while True:
                    _raise_if_cancelled(is_cancelled)
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    downloaded += len(chunk)
                    if downloaded > MAX_UPDATE_PACKAGE_BYTES:
                        raise UpdateInstallerError("The update package is unexpectedly large.")
                    handle.write(chunk)
                    if expected_size:
                        percent = 1 + int(min(downloaded / expected_size, 1.0) * 34)
                        _report(progress_callback, percent, 100, "Downloading update package...")
                    _raise_if_cancelled(is_cancelled)
    except InterruptedError:
        package_path.unlink(missing_ok=True)
        raise
    except UpdateInstallerError:
        package_path.unlink(missing_ok=True)
        raise
    except (OSError, TimeoutError, urllib.error.URLError) as exc:
        package_path.unlink(missing_ok=True)
        _raise_if_cancelled(is_cancelled)
        raise UpdateInstallerError("The update package could not be downloaded.") from exc


def _safe_extract_zip(
    package_path: Path,
    extract_dir: Path,
    *,
    is_cancelled: CancellationCallback | None = None,
) -> None:
    with zipfile.ZipFile(package_path) as archive:
        members: list[tuple[zipfile.ZipInfo, PurePosixPath, int, str | None]] = []
        seen_paths: set[PurePosixPath] = set()
        symlink_paths: set[PurePosixPath] = set()
        for info in archive.infolist():
            _raise_if_cancelled(is_cancelled)
            member_path = _validate_archive_member(info.filename)
            if member_path in seen_paths:
                raise UpdateInstallerError("Update package contains duplicate archive paths.")
            seen_paths.add(member_path)
            mode = info.external_attr >> 16
            file_type = stat.S_IFMT(mode)
            link_target: str | None = None
            if stat.S_ISLNK(mode):
                link_target = _read_zip_symlink_target(archive, info)
                _validate_archive_link_target(member_path, link_target)
                symlink_paths.add(member_path)
            elif not info.is_dir() and file_type and not stat.S_ISREG(mode):
                raise UpdateInstallerError(
                    "Update packages can only contain files, directories, and safe symbolic links."
                )
            members.append((info, member_path, mode, link_target))

        _reject_entries_below_symlinks(seen_paths, symlink_paths)
        for info, member_path, mode, link_target in members:
            _raise_if_cancelled(is_cancelled)
            destination = _prepare_archive_destination(extract_dir, member_path)
            if link_target is not None:
                _create_archive_symlink(destination, link_target)
            elif info.is_dir():
                _create_archive_directory(destination, mode)
            else:
                _write_zip_file(archive, info, destination, mode, is_cancelled=is_cancelled)


def _safe_extract_tar(
    package_path: Path,
    extract_dir: Path,
    *,
    is_cancelled: CancellationCallback | None = None,
) -> None:
    with tarfile.open(package_path, "r:*") as archive:
        members = archive.getmembers()
        seen_paths: set[PurePosixPath] = set()
        symlink_paths: set[PurePosixPath] = set()
        prepared_members: list[tuple[tarfile.TarInfo, PurePosixPath]] = []
        for member in members:
            _raise_if_cancelled(is_cancelled)
            member_path = _validate_archive_member(member.name)
            if member_path in seen_paths:
                raise UpdateInstallerError("Update package contains duplicate archive paths.")
            seen_paths.add(member_path)
            if member.issym():
                _validate_archive_link_target(member_path, member.linkname)
                symlink_paths.add(member_path)
            elif member.islnk() or not (member.isdir() or member.isfile()):
                raise UpdateInstallerError("Update packages cannot contain unsafe tar entries.")
            prepared_members.append((member, member_path))

        _reject_entries_below_symlinks(seen_paths, symlink_paths)
        for member, member_path in prepared_members:
            _raise_if_cancelled(is_cancelled)
            destination = _prepare_archive_destination(extract_dir, member_path)
            if member.issym():
                _create_archive_symlink(destination, member.linkname)
            elif member.isdir():
                _create_archive_directory(destination, member.mode)
            else:
                _write_tar_file(archive, member, destination, is_cancelled=is_cancelled)


def _validate_archive_member(name: str) -> PurePosixPath:
    normalized = str(name or "").replace("\\", "/")
    path = PurePosixPath(normalized)
    if not normalized or normalized.startswith("/") or path.is_absolute():
        raise UpdateInstallerError("Update package contains an unsafe absolute path.")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise UpdateInstallerError("Update package contains an unsafe relative path.")
    if path.parts and ":" in path.parts[0]:
        raise UpdateInstallerError("Update package contains an unsafe drive-qualified path.")
    return path


def _read_zip_symlink_target(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> str:
    try:
        return archive.read(info).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise UpdateInstallerError(
            "Update package contains a symbolic link with an invalid target."
        ) from exc


def _validate_archive_link_target(member_path: PurePosixPath, target: str) -> None:
    normalized = str(target or "").replace("\\", "/")
    target_path = PurePosixPath(normalized)
    if "\x00" in normalized:
        raise UpdateInstallerError(
            "Update package contains a symbolic link with an invalid target."
        )
    if not normalized or normalized.startswith("/") or target_path.is_absolute():
        raise UpdateInstallerError("Update package contains an unsafe symbolic link.")
    if target_path.parts and ":" in target_path.parts[0]:
        raise UpdateInstallerError("Update package contains an unsafe symbolic link.")
    resolved_target = _collapse_archive_path((*member_path.parent.parts, *target_path.parts))
    if not member_path.parts or resolved_target.parts[0] != member_path.parts[0]:
        raise UpdateInstallerError(
            "Update package contains a symbolic link outside its package root."
        )


def _collapse_archive_path(parts: Sequence[str]) -> PurePosixPath:
    collapsed: list[str] = []
    for part in parts:
        if part in {"", "."}:
            continue
        if part == "..":
            if not collapsed:
                raise UpdateInstallerError("Update package contains an unsafe symbolic link.")
            collapsed.pop()
            continue
        collapsed.append(part)
    if not collapsed:
        raise UpdateInstallerError("Update package contains an unsafe symbolic link.")
    return PurePosixPath(*collapsed)


def _reject_entries_below_symlinks(
    member_paths: set[PurePosixPath],
    symlink_paths: set[PurePosixPath],
) -> None:
    for member_path in member_paths:
        for symlink_path in symlink_paths:
            if _archive_path_is_descendant(member_path, symlink_path):
                raise UpdateInstallerError("Update package contains entries below a symbolic link.")


def _archive_path_is_descendant(
    member_path: PurePosixPath,
    parent_path: PurePosixPath,
) -> bool:
    return (
        len(member_path.parts) > len(parent_path.parts)
        and member_path.parts[: len(parent_path.parts)] == parent_path.parts
    )


def _prepare_archive_destination(extract_dir: Path, member_path: PurePosixPath) -> Path:
    root = extract_dir.resolve()
    destination = root.joinpath(*member_path.parts)
    try:
        destination.resolve(strict=False).relative_to(root)
    except ValueError as exc:
        raise UpdateInstallerError(
            "Update package contains a path outside the staging folder."
        ) from exc

    parent = root
    for part in member_path.parts[:-1]:
        parent = parent / part
        if parent.is_symlink():
            raise UpdateInstallerError("Update package contains entries below a symbolic link.")
        if parent.exists() and not parent.is_dir():
            raise UpdateInstallerError("Update package contains conflicting archive paths.")
        parent.mkdir(exist_ok=True)
    return destination


def _create_archive_directory(destination: Path, mode: int) -> None:
    if destination.is_symlink() or (destination.exists() and not destination.is_dir()):
        raise UpdateInstallerError("Update package contains conflicting archive paths.")
    destination.mkdir(exist_ok=True)
    _apply_archive_mode(destination, mode)


def _create_archive_symlink(destination: Path, link_target: str) -> None:
    if destination.exists() or destination.is_symlink():
        raise UpdateInstallerError("Update package contains conflicting archive paths.")
    os.symlink(link_target, destination)


def _write_zip_file(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    destination: Path,
    mode: int,
    *,
    is_cancelled: CancellationCallback | None = None,
) -> None:
    if destination.is_symlink() or destination.is_dir():
        raise UpdateInstallerError("Update package contains conflicting archive paths.")
    with archive.open(info) as source, destination.open("wb") as target:
        _copy_fileobj(source, target, is_cancelled=is_cancelled)
    _apply_archive_mode(destination, mode)


def _write_tar_file(
    archive: tarfile.TarFile,
    member: tarfile.TarInfo,
    destination: Path,
    *,
    is_cancelled: CancellationCallback | None = None,
) -> None:
    if destination.is_symlink() or destination.is_dir():
        raise UpdateInstallerError("Update package contains conflicting archive paths.")
    source = archive.extractfile(member)
    if source is None:
        raise UpdateInstallerError("Update package contains an unreadable file entry.")
    with source, destination.open("wb") as target:
        _copy_fileobj(source, target, is_cancelled=is_cancelled)
    _apply_archive_mode(destination, member.mode)


def _copy_fileobj(
    source: IO[bytes],
    target: IO[bytes],
    *,
    is_cancelled: CancellationCallback | None = None,
) -> None:
    while True:
        _raise_if_cancelled(is_cancelled)
        chunk = source.read(1024 * 1024)
        if not chunk:
            return
        target.write(chunk)


def _apply_archive_mode(destination: Path, mode: int) -> None:
    permissions = mode & 0o777
    if permissions:
        destination.chmod(permissions)


def _macos_app_executable(app_bundle: Path) -> Path | None:
    macos_dir = app_bundle / "Contents" / "MacOS"
    if not macos_dir.is_dir():
        return None
    for preferred_name in _preferred_executable_names():
        preferred = macos_dir / preferred_name
        if preferred.is_file():
            return preferred
    executables = sorted(
        path for path in macos_dir.iterdir() if path.is_file() and os.access(path, os.X_OK)
    )
    return executables[0] if executables else None


def _find_executable_in_directory(directory: Path) -> Path | None:
    for name in _preferred_executable_names(include_windows_suffix=True):
        candidate = directory / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    candidates = sorted(
        path for path in directory.iterdir() if path.is_file() and os.access(path, os.X_OK)
    )
    return candidates[0] if candidates else None


def _prefer_app_named_path(candidates: Sequence[Path]) -> Path:
    preferred_fragments = (
        PACKAGED_APP_NAME_TEXT.lower(),
        APP_NAME_TEXT.lower(),
    )
    for candidate in candidates:
        candidate_name = candidate.name.lower()
        if any(fragment in candidate_name for fragment in preferred_fragments):
            return candidate
    return candidates[0]


def _preferred_executable_names(*, include_windows_suffix: bool = False) -> tuple[str, ...]:
    names = [PACKAGED_APP_NAME_TEXT, APP_NAME_TEXT]
    if include_windows_suffix:
        names.extend(f"{name}.exe" for name in (PACKAGED_APP_NAME_TEXT, APP_NAME_TEXT))
    deduped: list[str] = []
    for name in names:
        if name and name not in deduped:
            deduped.append(name)
    return tuple(deduped)


def _supported_package_name(name: str) -> bool:
    return any(str(name).lower().endswith(suffix) for suffix in SUPPORTED_PACKAGE_SUFFIXES)


def _validate_download_url(url: str) -> None:
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme != "https" or not parsed.netloc:
        raise UpdateInstallerError("Update packages must be downloaded over HTTPS.")


def _reject_unusable_download_size(size_bytes: int) -> None:
    if size_bytes <= 0:
        raise UpdateInstallerError("The update package was empty.")
    if size_bytes > MAX_UPDATE_PACKAGE_BYTES:
        raise UpdateInstallerError("The update package is unexpectedly large.")


def _report(
    callback: ProgressCallback | None,
    value: int,
    maximum: int,
    message: str,
) -> None:
    if callback is not None:
        callback(value, maximum, message)


def _raise_if_cancelled(callback: CancellationCallback | None) -> None:
    if callback is not None and callback():
        raise InterruptedError("Update installation cancelled.")

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
from typing import cast
from urllib.parse import urlparse

from .constants import APP_NAME
from .paths import preferred_data_root
from .update_checker import ReleaseAsset, ReleaseManifest, UpdateCheckError

HELPER_MODE_ARGUMENT = "--run-updater-helper"
DEFAULT_UPDATE_DOWNLOAD_TIMEOUT_SECONDS = 45.0
MAX_UPDATE_PACKAGE_BYTES = 5 * 1024 * 1024 * 1024
SUPPORTED_PACKAGE_SUFFIXES = (".zip", ".tar.gz", ".tgz")

ProgressCallback = Callable[[int, int, str], None]
DownloadFetcher = Callable[[str, float], bytes]


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
    root = cast(Path, preferred_data_root(APP_NAME)) / "updates"
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
    fetcher: DownloadFetcher | None = None,
    progress_callback: ProgressCallback | None = None,
) -> DownloadedUpdatePackage:
    _validate_download_url(asset.url)
    destination_dir.mkdir(parents=True, exist_ok=True)
    package_path = destination_dir / asset.name
    package_path.unlink(missing_ok=True)

    _report(progress_callback, 0, 100, "Starting update download...")
    if fetcher is not None:
        data = fetcher(asset.url, float(timeout_seconds))
        _reject_unusable_download_size(len(data))
        package_path.write_bytes(data)
    else:
        _stream_download(
            asset.url,
            package_path,
            timeout_seconds=float(timeout_seconds),
            progress_callback=progress_callback,
        )

    size_bytes = package_path.stat().st_size if package_path.exists() else 0
    _reject_unusable_download_size(size_bytes)
    digest = file_sha256(package_path)
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


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extract_update_package(
    package_path: Path,
    staging_root: Path,
    *,
    platform_key: str | None = None,
    progress_callback: ProgressCallback | None = None,
) -> StagedUpdatePackage:
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
    suffixes = "".join(package_path.suffixes[-2:]).lower()
    if package_path.suffix.lower() == ".zip":
        _safe_extract_zip(package_path, extract_dir)
    elif suffixes == ".tar.gz" or package_path.suffix.lower() == ".tgz":
        _safe_extract_tar(package_path, extract_dir)
    else:
        raise UpdateInstallerError(f"Unsupported update package type: {package_path.name}")

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
) -> UpdateInstallPlan:
    if not getattr(sys, "frozen", False):
        raise UpdateInstallerError("Automatic installation is only available in packaged builds.")

    key = platform_key or detect_platform_key()
    select_platform_asset(manifest, platform_key=key)
    workspace = update_workspace_root(manifest.version, platform_key=key, cache_root=cache_root)
    staged = extract_update_package(
        package_path,
        workspace / "staging",
        platform_key=key,
        progress_callback=progress_callback,
    )
    target = resolve_installed_target_path(platform_key=key)
    if not target.exists():
        raise UpdateInstallerError(f"The installed application could not be found: {target}")
    restart_command = restart_command_for_target(target, platform_key=key)
    backup_path = backup_path_for_target(target, manifest.version)
    log_path = workspace / "install.log"
    helper_executable = create_helper_runtime_copy(
        target,
        workspace / "helper",
        platform_key=key,
    )
    helper_command = build_helper_command(
        helper_executable,
        current_pid=current_pid or os.getpid(),
        target_path=target,
        replacement_path=staged.replacement_path,
        expected_version=manifest.version,
        backup_path=backup_path,
        restart_command=restart_command,
        log_path=log_path,
    )
    _report(progress_callback, 90, 100, "Update installer prepared.")
    return UpdateInstallPlan(
        helper_command=helper_command,
        target_path=target,
        replacement_path=staged.replacement_path,
        backup_path=backup_path,
        restart_command=restart_command,
        log_path=log_path,
        expected_version=manifest.version,
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


def build_helper_command(
    helper_executable: Path,
    *,
    current_pid: int,
    target_path: Path,
    replacement_path: Path,
    expected_version: str,
    backup_path: Path,
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
    progress_callback: ProgressCallback | None,
) -> None:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/octet-stream, */*",
            "User-Agent": "ISRC-Catalog-Manager-Updater",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            length_header = response.headers.get("Content-Length")
            expected_size = int(length_header) if length_header and length_header.isdigit() else 0
            if expected_size > MAX_UPDATE_PACKAGE_BYTES:
                raise UpdateInstallerError("The update package is unexpectedly large.")
            downloaded = 0
            with package_path.open("wb") as handle:
                while True:
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
    except UpdateInstallerError:
        package_path.unlink(missing_ok=True)
        raise
    except (OSError, TimeoutError, urllib.error.URLError) as exc:
        package_path.unlink(missing_ok=True)
        raise UpdateInstallerError("The update package could not be downloaded.") from exc


def _safe_extract_zip(package_path: Path, extract_dir: Path) -> None:
    with zipfile.ZipFile(package_path) as archive:
        for info in archive.infolist():
            _validate_archive_member(info.filename)
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise UpdateInstallerError("Update packages cannot contain symbolic links.")
        archive.extractall(extract_dir)


def _safe_extract_tar(package_path: Path, extract_dir: Path) -> None:
    with tarfile.open(package_path, "r:*") as archive:
        members = archive.getmembers()
        for member in members:
            _validate_archive_member(member.name)
            if member.issym() or member.islnk() or not (member.isdir() or member.isfile()):
                raise UpdateInstallerError("Update packages cannot contain unsafe tar entries.")
        archive.extractall(extract_dir, members=members)


def _validate_archive_member(name: str) -> None:
    normalized = str(name or "").replace("\\", "/")
    path = PurePosixPath(normalized)
    if not normalized or normalized.startswith("/") or path.is_absolute():
        raise UpdateInstallerError("Update package contains an unsafe absolute path.")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise UpdateInstallerError("Update package contains an unsafe relative path.")
    if path.parts and ":" in path.parts[0]:
        raise UpdateInstallerError("Update package contains an unsafe drive-qualified path.")


def _macos_app_executable(app_bundle: Path) -> Path | None:
    macos_dir = app_bundle / "Contents" / "MacOS"
    if not macos_dir.is_dir():
        return None
    preferred = macos_dir / APP_NAME
    if preferred.is_file():
        return preferred
    executables = sorted(
        path for path in macos_dir.iterdir() if path.is_file() and os.access(path, os.X_OK)
    )
    return executables[0] if executables else None


def _find_executable_in_directory(directory: Path) -> Path | None:
    preferred_names = (APP_NAME, f"{APP_NAME}.exe")
    for name in preferred_names:
        candidate = directory / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    candidates = sorted(
        path for path in directory.iterdir() if path.is_file() and os.access(path, os.X_OK)
    )
    return candidates[0] if candidates else None


def _prefer_app_named_path(candidates: Sequence[Path]) -> Path:
    for candidate in candidates:
        if APP_NAME.lower() in candidate.name.lower():
            return candidate
    return candidates[0]


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

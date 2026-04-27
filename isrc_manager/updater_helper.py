"""Detached helper used to replace a packaged app after the main process exits."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import TextIO

EXIT_SUCCESS = 0
EXIT_INVALID_ARGUMENTS = 2
EXIT_WAIT_TIMEOUT = 3
EXIT_VALIDATION_FAILED = 4
EXIT_REPLACEMENT_FAILED = 5
EXIT_RESTART_FAILED = 6


class UpdaterHelperError(RuntimeError):
    """Raised for controlled helper failures."""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current-pid", required=True, type=int)
    parser.add_argument("--target", required=True)
    parser.add_argument("--replacement", required=True)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--backup", required=True)
    parser.add_argument("--restart-json", required=True)
    parser.add_argument("--log", required=True)
    parser.add_argument("--wait-timeout", type=float, default=120.0)
    return parser.parse_args(argv)


def wait_for_process_exit(
    pid: int, *, timeout_seconds: float = 120.0, poll_seconds: float = 0.25
) -> None:
    if pid <= 0 or pid == os.getpid():
        return
    deadline = time.monotonic() + max(0.0, float(timeout_seconds))
    while time.monotonic() <= deadline:
        if not _process_exists(pid):
            return
        time.sleep(max(0.05, float(poll_seconds)))
    raise UpdaterHelperError("The application did not exit before the update timeout.")


def replace_installation(target: Path, replacement: Path, backup: Path, log: TextIO) -> Path:
    if not target.exists():
        raise UpdaterHelperError(f"Installed application was not found: {target}")
    if not replacement.exists():
        raise UpdaterHelperError(f"Staged replacement was not found: {replacement}")
    install_target = _install_target_for_replacement(target, replacement)
    if install_target != target and install_target.exists():
        raise UpdaterHelperError(f"The renamed install target already exists: {install_target}")
    if backup.exists():
        _remove_path(backup)

    _log(log, f"Moving current installation to backup: {backup}")
    try:
        shutil.move(str(target), str(backup))
    except Exception as exc:
        raise UpdaterHelperError(f"Could not create update backup: {exc}") from exc

    try:
        _log(log, f"Moving staged replacement into place: {install_target}")
        shutil.move(str(replacement), str(install_target))
    except Exception as exc:
        _log(log, f"Replacement failed, attempting rollback: {exc}")
        if install_target != target and install_target.exists():
            _remove_path(install_target)
        _restore_backup(target, backup, log)
        raise UpdaterHelperError(f"Could not install update: {exc}") from exc
    return install_target


def restart_application(restart_command: list[str], log: TextIO) -> None:
    if not restart_command:
        raise UpdaterHelperError("Restart command was empty.")
    _log(log, "Restarting application: " + " ".join(restart_command))
    try:
        subprocess.Popen(
            restart_command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=(os.name != "nt"),
        )
    except Exception as exc:
        raise UpdaterHelperError(f"Could not restart the updated application: {exc}") from exc


def run_update(args: argparse.Namespace) -> int:
    log_path = Path(args.log).expanduser().resolve()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    target = Path(args.target).expanduser().resolve()
    replacement = Path(args.replacement).expanduser().resolve()
    backup = Path(args.backup).expanduser().resolve()
    try:
        restart_command = _parse_restart_command(args.restart_json)
    except ValueError as exc:
        with log_path.open("a", encoding="utf-8") as log:
            _log(log, f"Invalid restart command: {exc}")
        return EXIT_INVALID_ARGUMENTS

    with log_path.open("a", encoding="utf-8") as log:
        _log(log, f"Starting update helper for version {args.expected_version}.")
        _log(log, f"Target: {target}")
        _log(log, f"Replacement: {replacement}")
        _log(log, f"Backup: {backup}")
        try:
            wait_for_process_exit(args.current_pid, timeout_seconds=args.wait_timeout)
        except UpdaterHelperError as exc:
            _log(log, str(exc))
            return EXIT_WAIT_TIMEOUT

        try:
            install_target = replace_installation(target, replacement, backup, log)
        except UpdaterHelperError as exc:
            _log(log, str(exc))
            return EXIT_REPLACEMENT_FAILED

        try:
            restart_application(restart_command, log)
        except UpdaterHelperError as exc:
            _log(log, str(exc))
            try:
                _restore_backup(target, backup, log, installed_target=install_target)
            except UpdaterHelperError as rollback_exc:
                _log(log, f"Rollback after restart failure also failed: {rollback_exc}")
            return EXIT_RESTART_FAILED

        _remove_successful_backup(backup, log)
        _log(log, "Update helper completed successfully.")
        return EXIT_SUCCESS


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or EXIT_INVALID_ARGUMENTS)
    try:
        return run_update(args)
    except Exception as exc:  # pragma: no cover - defensive helper boundary
        try:
            log_path = Path(getattr(args, "log", "update-helper.log")).expanduser().resolve()
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as log:
                _log(log, f"Unexpected updater failure: {exc}")
        except Exception:
            pass
        return EXIT_REPLACEMENT_FAILED


def _parse_restart_command(value: str) -> list[str]:
    parsed = json.loads(value)
    if not isinstance(parsed, list) or not parsed:
        raise ValueError("restart command must be a non-empty JSON list")
    command = [str(part) for part in parsed]
    if any(not part.strip() for part in command):
        raise ValueError("restart command contains an empty argument")
    return command


def _restore_backup(
    target: Path,
    backup: Path,
    log: TextIO,
    *,
    installed_target: Path | None = None,
) -> None:
    if not backup.exists():
        raise UpdaterHelperError("Backup was not available for rollback.")
    if installed_target is not None and installed_target != target and installed_target.exists():
        _remove_path(installed_target)
    if target.exists():
        _remove_path(target)
    _log(log, f"Restoring backup: {backup} -> {target}")
    try:
        shutil.move(str(backup), str(target))
    except Exception as exc:
        raise UpdaterHelperError(f"Could not restore the previous installation: {exc}") from exc


def _remove_successful_backup(backup: Path, log: TextIO) -> None:
    if not backup.exists():
        _log(log, "Update backup was already removed.")
        return
    _log(log, f"Removing successful update backup: {backup}")
    try:
        _remove_path(backup)
    except Exception as exc:
        _log(log, f"Update backup cleanup failed: {exc}")


def _remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


def _install_target_for_replacement(target: Path, replacement: Path) -> Path:
    replacement_name = str(replacement.name or "").strip()
    if replacement_name and replacement_name != target.name:
        return target.parent / replacement_name
    return target


def _process_exists(pid: int) -> bool:
    if os.name == "nt":
        return _windows_process_exists(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _windows_process_exists(pid: int) -> bool:
    try:
        windll = getattr(ctypes, "windll", None)
        if windll is None:
            return True
        kernel32 = windll.kernel32
        handle = kernel32.OpenProcess(0x00100000, False, int(pid))
        if not handle:
            return False
        try:
            WAIT_TIMEOUT = 0x00000102
            result = int(kernel32.WaitForSingleObject(handle, 0))
            return result == WAIT_TIMEOUT
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return True


def _log(log: TextIO, message: str) -> None:
    log.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
    log.flush()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

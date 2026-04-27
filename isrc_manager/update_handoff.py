"""Persistent handoff state for update backup cleanup."""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any

from .constants import APP_NAME
from .paths import preferred_data_root

UPDATE_BACKUP_HANDOFF_FILENAME = "update_backup_handoff.json"
UPDATE_BACKUP_STATUS_CREATED = "created"
UPDATE_BACKUP_STATUS_READY_FOR_DELETION = "ready_for_deletion"
UPDATE_BACKUP_STATUS_DESTROYED = "destroyed"


def update_backup_handoff_path(update_root: Path | None = None) -> Path:
    root = (
        Path(update_root) if update_root is not None else preferred_data_root(APP_NAME) / "updates"
    )
    root.mkdir(parents=True, exist_ok=True)
    return root / UPDATE_BACKUP_HANDOFF_FILENAME


def read_update_backup_handoff(*, state_path: str | Path | None = None) -> dict[str, Any] | None:
    path = _state_path(state_path)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def record_update_backup_created(
    backup_path: str | Path,
    *,
    expected_version: str = "",
    target_path: str | Path | None = None,
    installed_path: str | Path | None = None,
    state_path: str | Path | None = None,
) -> dict[str, Any]:
    state = {
        "status": UPDATE_BACKUP_STATUS_CREATED,
        "backup_path": _exact_path_text(backup_path),
        "expected_version": str(expected_version or ""),
        "target_path": _optional_path_text(target_path),
        "installed_path": _optional_path_text(installed_path),
        "created_at": _timestamp(),
        "ready_at": "",
        "destroyed_at": "",
        "error": "",
    }
    _write_state(_state_path(state_path), state)
    return state


def mark_update_backup_ready_for_deletion(
    *, state_path: str | Path | None = None
) -> dict[str, Any] | None:
    path = _state_path(state_path)
    state = read_update_backup_handoff(state_path=path)
    if not state:
        return None
    status = str(state.get("status") or "")
    if status == UPDATE_BACKUP_STATUS_CREATED:
        state["status"] = UPDATE_BACKUP_STATUS_READY_FOR_DELETION
        state["ready_at"] = _timestamp()
        state["error"] = ""
        _write_state(path, state)
    return state


def mark_update_backup_destroyed(
    *,
    state_path: str | Path | None = None,
    reason: str = "",
) -> dict[str, Any] | None:
    path = _state_path(state_path)
    state = read_update_backup_handoff(state_path=path)
    if not state:
        return None
    state["status"] = UPDATE_BACKUP_STATUS_DESTROYED
    state["destroyed_at"] = _timestamp()
    state["error"] = str(reason or "")
    _write_state(path, state)
    return state


def cleanup_ready_update_backup(*, state_path: str | Path | None = None) -> dict[str, Any] | None:
    path = _state_path(state_path)
    state = read_update_backup_handoff(state_path=path)
    if not state or state.get("status") != UPDATE_BACKUP_STATUS_READY_FOR_DELETION:
        return state

    raw_backup_path = str(state.get("backup_path") or "").strip()
    if not raw_backup_path:
        state["status"] = UPDATE_BACKUP_STATUS_DESTROYED
        state["destroyed_at"] = _timestamp()
        state["error"] = "Backup path was empty."
        _write_state(path, state)
        return state

    backup_path = Path(raw_backup_path).expanduser()
    try:
        if backup_path.exists() or backup_path.is_symlink():
            _remove_path(backup_path)
        state["status"] = UPDATE_BACKUP_STATUS_DESTROYED
        state["destroyed_at"] = _timestamp()
        state["error"] = ""
        _write_state(path, state)
    except Exception as exc:
        state["error"] = str(exc)
        _write_state(path, state)
        raise
    return state


def cleanup_legacy_update_backups_for_version(
    installed_target: str | Path,
    version: str,
) -> list[Path]:
    version_text = str(version or "").strip().removeprefix("v")
    if not version_text:
        return []
    target = Path(installed_target).expanduser().resolve()
    parent = target.parent
    if not parent.is_dir():
        return []

    marker = f".backup-before-v{version_text}-"
    removed: list[Path] = []
    for candidate in sorted(parent.iterdir()):
        if marker not in candidate.name:
            continue
        if candidate.resolve() == target:
            continue
        _remove_path(candidate)
        removed.append(candidate)
    return removed


def cleanup_update_backup_siblings(installed_target: str | Path) -> list[Path]:
    target = Path(installed_target).expanduser().resolve()
    parent = target.parent
    if not parent.is_dir():
        return []

    removed: list[Path] = []
    for candidate in sorted(parent.iterdir()):
        if ".backup-before-v" not in candidate.name:
            continue
        try:
            if candidate.resolve() == target:
                continue
        except OSError:
            pass
        _remove_path(candidate)
        removed.append(candidate)
    return removed


def cleanup_update_cache_artifacts(*, update_root: str | Path | None = None) -> list[Path]:
    root = (
        Path(update_root).expanduser().resolve()
        if update_root is not None
        else preferred_data_root(APP_NAME) / "updates"
    )
    if not root.is_dir():
        return []

    removed: list[Path] = []
    for candidate in sorted(root.iterdir()):
        if candidate.name == UPDATE_BACKUP_HANDOFF_FILENAME:
            continue
        _remove_path(candidate)
        removed.append(candidate)
    return removed


def _state_path(state_path: str | Path | None) -> Path:
    if state_path is None:
        return update_backup_handoff_path()
    return Path(state_path).expanduser().resolve()


def _write_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


def _exact_path_text(path: str | Path) -> str:
    return str(Path(path).expanduser().resolve())


def _optional_path_text(path: str | Path | None) -> str:
    if path is None:
        return ""
    return _exact_path_text(path)


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

"""Password rotation for encrypted databases referenced by persistent history."""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from isrc_manager.services.database_security import (
    DatabaseSecurityError,
    is_plaintext_sqlite_database,
)

_DATABASE_COMPANION_SUFFIXES = ("-wal", "-shm", "-journal")
_HISTORY_ENTRY_SCAN_LIMIT = 1_000_000


class HistorySnapshotPasswordError(DatabaseSecurityError):
    """Raised when history artifacts cannot be rekeyed as one safe batch."""


@dataclass(frozen=True, slots=True)
class HistorySnapshotRekeyResult:
    """Summary of one history-artifact password rotation."""

    encrypted_artifacts_rekeyed: int
    plaintext_artifacts_unchanged: int


class _DatabasePasswordChanger(Protocol):
    def change_password(
        self,
        path: str | Path,
        current_password: str,
        new_password: str,
    ) -> None: ...


class _ProfileHistory(Protocol):
    def list_snapshots(self, limit: int = 250) -> list[Any]: ...

    def list_entries(
        self,
        limit: int = 250,
        *,
        include_hidden: bool = False,
    ) -> list[Any]: ...


class _SessionHistory(Protocol):
    def snapshot_references(self) -> list[dict]: ...

    def refresh_snapshot_inventories(
        self,
        snapshot_paths: Iterable[str | Path],
    ) -> int: ...


def referenced_profile_history_databases(
    *,
    history_root: str | Path,
    profile_path: str | Path,
    history_manager: _ProfileHistory | None,
    session_history_manager: _SessionHistory | None,
) -> tuple[Path, ...]:
    """Return existing, app-owned history databases for one exact profile path."""

    root = Path(history_root).absolute()
    profile = Path(profile_path).absolute()
    candidates: set[Path] = set()

    if history_manager is not None:
        for snapshot in history_manager.list_snapshots(limit=_HISTORY_ENTRY_SCAN_LIMIT):
            raw_path = str(getattr(snapshot, "db_snapshot_path", "") or "").strip()
            if raw_path:
                candidates.add(Path(raw_path))
        for entry in history_manager.list_entries(
            limit=_HISTORY_ENTRY_SCAN_LIMIT,
            include_hidden=True,
        ):
            for payload in (
                getattr(entry, "payload", None),
                getattr(entry, "inverse_payload", None),
                getattr(entry, "redo_payload", None),
            ):
                archive_path = _archived_snapshot_path(payload)
                if archive_path is not None:
                    candidates.add(archive_path)

    if session_history_manager is not None:
        for reference in session_history_manager.snapshot_references():
            if not isinstance(reference, Mapping):
                continue
            reference_profile = str(reference.get("profile_path") or "").strip()
            snapshot_path = str(reference.get("snapshot_path") or "").strip()
            if (
                reference_profile
                and snapshot_path
                and Path(reference_profile).absolute() == profile
            ):
                candidates.add(Path(snapshot_path))

    allowed_roots = (
        root / "snapshots" / profile.stem,
        root / "snapshot_archives" / profile.stem,
        root / "session_profile_snapshots",
    )
    selected: list[Path] = []
    for candidate in sorted(candidates, key=lambda value: str(value)):
        absolute_candidate = candidate.absolute()
        if not absolute_candidate.exists():
            continue
        artifact_root = _artifact_root_for_path(absolute_candidate, allowed_roots)
        if artifact_root is None:
            raise HistorySnapshotPasswordError(
                "History metadata points outside this profile's snapshot directories."
            )
        _validate_allowed_artifact_root(
            artifact_root.absolute(),
            history_root=root,
        )
        _validate_history_artifact_path(
            absolute_candidate,
            lexical_root=artifact_root.absolute(),
            resolved_root=artifact_root.resolve(strict=False),
        )
        selected.append(absolute_candidate)
    return tuple(selected)


class HistorySnapshotPasswordService:
    """Rekey encrypted history databases without leaving a partially rotated batch."""

    def __init__(self, database_security_service: _DatabasePasswordChanger) -> None:
        self.database_security_service = database_security_service

    def rekey(
        self,
        artifact_paths: Iterable[str | Path],
        *,
        current_password: str,
        new_password: str,
    ) -> HistorySnapshotRekeyResult:
        paths = tuple(dict.fromkeys(Path(path).absolute() for path in artifact_paths))
        encrypted_paths = tuple(path for path in paths if not is_plaintext_sqlite_database(path))
        plaintext_count = len(paths) - len(encrypted_paths)
        if not encrypted_paths:
            return HistorySnapshotRekeyResult(0, plaintext_count)

        with tempfile.TemporaryDirectory(prefix="isrc-history-rekey-") as temp_value:
            backup_root = Path(temp_value)
            backups = self._capture_backups(encrypted_paths, backup_root)
            try:
                for path in encrypted_paths:
                    if path.is_symlink() or not path.is_file():
                        raise HistorySnapshotPasswordError(
                            "A history database artifact changed during password rotation."
                        )
                    self.database_security_service.change_password(
                        path,
                        current_password,
                        new_password,
                    )
            except Exception as exc:
                try:
                    self._restore_backups(backups)
                except Exception as rollback_exc:
                    raise HistorySnapshotPasswordError(
                        "Could not update history snapshot passwords, and their encrypted "
                        "rollback copies could not be restored."
                    ) from rollback_exc
                raise HistorySnapshotPasswordError(
                    "Could not update history snapshot passwords; no history artifact was changed."
                ) from exc

        return HistorySnapshotRekeyResult(len(encrypted_paths), plaintext_count)

    @staticmethod
    def _capture_backups(
        paths: tuple[Path, ...],
        backup_root: Path,
    ) -> dict[Path, dict[str, Path]]:
        backups: dict[Path, dict[str, Path]] = {}
        for index, path in enumerate(paths):
            artifact_backups: dict[str, Path] = {}
            for suffix in ("", *_DATABASE_COMPANION_SUFFIXES):
                source = Path(f"{path}{suffix}")
                if not source.exists():
                    continue
                if source.is_symlink() or not source.is_file():
                    raise HistorySnapshotPasswordError(
                        "A history database bundle contains an unsafe filesystem entry."
                    )
                backup = backup_root / f"{index}{_backup_suffix(suffix)}"
                shutil.copy2(source, backup)
                artifact_backups[suffix] = backup
            if "" not in artifact_backups:
                raise HistorySnapshotPasswordError("A history database artifact is missing.")
            backups[path] = artifact_backups
        return backups

    @staticmethod
    def _restore_backups(backups: Mapping[Path, Mapping[str, Path]]) -> None:
        for path, artifact_backups in backups.items():
            for suffix in ("", *_DATABASE_COMPANION_SUFFIXES):
                target = Path(f"{path}{suffix}")
                backup = artifact_backups.get(suffix)
                if backup is None:
                    if target.is_symlink() or target.is_file():
                        target.unlink()
                    elif target.exists():
                        raise HistorySnapshotPasswordError(
                            "A history database rollback target is not a regular file."
                        )
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.is_symlink():
                    target.unlink()
                elif target.exists() and not target.is_file():
                    raise HistorySnapshotPasswordError(
                        "A history database rollback target is not a regular file."
                    )
                shutil.copy2(backup, target)


def change_profile_password_with_history(
    database_security_service: _DatabasePasswordChanger,
    profile_path: str | Path,
    current_password: str,
    new_password: str,
    *,
    history_root: str | Path | None = None,
    history_manager: _ProfileHistory | None = None,
    session_history_manager: _SessionHistory | None = None,
    live_connection: Any | None = None,
) -> HistorySnapshotRekeyResult:
    """Rotate one profile and every encrypted artifact required by its Undo history."""

    artifact_paths = (
        referenced_profile_history_databases(
            history_root=history_root,
            profile_path=profile_path,
            history_manager=history_manager,
            session_history_manager=session_history_manager,
        )
        if history_root is not None
        else ()
    )
    snapshot_passwords = HistorySnapshotPasswordService(database_security_service)
    result = snapshot_passwords.rekey(
        artifact_paths,
        current_password=current_password,
        new_password=new_password,
    )
    live_profile_changed = False
    try:
        _change_profile_password(
            database_security_service,
            profile_path,
            current_password,
            new_password,
            live_connection=live_connection,
        )
        live_profile_changed = True
        _refresh_session_snapshot_inventories(
            session_history_manager,
            artifact_paths,
        )
    except Exception as exc:
        rollback_errors: list[Exception] = []
        if live_profile_changed:
            try:
                _change_profile_password(
                    database_security_service,
                    profile_path,
                    new_password,
                    current_password,
                    live_connection=live_connection,
                )
            except Exception as rollback_exc:
                rollback_errors.append(rollback_exc)
        if result.encrypted_artifacts_rekeyed:
            try:
                snapshot_passwords.rekey(
                    artifact_paths,
                    current_password=new_password,
                    new_password=current_password,
                )
            except Exception as rollback_exc:
                rollback_errors.append(rollback_exc)
        if not rollback_errors:
            try:
                _refresh_session_snapshot_inventories(
                    session_history_manager,
                    artifact_paths,
                )
            except Exception as rollback_exc:
                rollback_errors.append(rollback_exc)
        if rollback_errors:
            raise HistorySnapshotPasswordError(
                "The profile password change failed, and its profile/history integrity "
                "metadata could not be returned safely to the previous state."
            ) from rollback_errors[0]
        if live_profile_changed:
            raise HistorySnapshotPasswordError(
                "The profile and history passwords were returned to the previous password "
                "because session Undo metadata could not be updated safely."
            ) from exc
        raise
    return result


def _change_profile_password(
    database_security_service: _DatabasePasswordChanger,
    profile_path: str | Path,
    current_password: str,
    new_password: str,
    *,
    live_connection: Any | None,
) -> None:
    change_open_password = getattr(
        database_security_service,
        "change_open_database_password",
        None,
    )
    if live_connection is not None and callable(change_open_password):
        change_open_password(
            profile_path,
            live_connection,
            current_password,
            new_password,
        )
        return
    database_security_service.change_password(
        profile_path,
        current_password,
        new_password,
    )


def _refresh_session_snapshot_inventories(
    session_history_manager: _SessionHistory | None,
    artifact_paths: Iterable[str | Path],
) -> None:
    if session_history_manager is None:
        return
    refresh = getattr(session_history_manager, "refresh_snapshot_inventories", None)
    if callable(refresh):
        refresh(artifact_paths)


def _archived_snapshot_path(payload: object) -> Path | None:
    if not isinstance(payload, Mapping):
        return None
    archived = payload.get("archived_snapshot")
    if not isinstance(archived, Mapping):
        return None
    raw_path = str(archived.get("db_snapshot_path") or "").strip()
    return Path(raw_path) if raw_path else None


def _validate_history_artifact_path(
    path: Path,
    *,
    lexical_root: Path,
    resolved_root: Path,
) -> None:
    try:
        path.resolve(strict=True).relative_to(resolved_root)
    except (OSError, ValueError) as exc:
        raise HistorySnapshotPasswordError(
            "History metadata points outside the application history directory."
        ) from exc

    current = path
    while current != lexical_root:
        if current.is_symlink():
            raise HistorySnapshotPasswordError(
                "History database password rotation does not follow symbolic links."
            )
        if lexical_root not in current.parents:
            raise HistorySnapshotPasswordError(
                "History metadata points outside the application history directory."
            )
        current = current.parent
    if not path.is_file():
        raise HistorySnapshotPasswordError("A history database artifact is not a regular file.")


def _validate_allowed_artifact_root(path: Path, *, history_root: Path) -> None:
    current = path
    while True:
        if current.is_symlink():
            raise HistorySnapshotPasswordError(
                "History database password rotation does not follow symbolic links."
            )
        if current == history_root:
            return
        if history_root not in current.parents:
            raise HistorySnapshotPasswordError(
                "History metadata points outside the application history directory."
            )
        current = current.parent


def _artifact_root_for_path(path: Path, allowed_roots: tuple[Path, ...]) -> Path | None:
    resolved_path = path.resolve(strict=False)
    for root in allowed_roots:
        try:
            resolved_path.relative_to(root.resolve(strict=False))
        except ValueError:
            continue
        return root
    return None


def _backup_suffix(suffix: str) -> str:
    return ".db" if not suffix else suffix

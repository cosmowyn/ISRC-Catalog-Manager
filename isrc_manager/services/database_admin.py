"""Database file lifecycle and maintenance services."""

from __future__ import annotations

import re
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable


@dataclass(slots=True)
class BackupResult:
    backup_path: Path
    method: str


@dataclass(slots=True)
class RestoreResult:
    restored_path: Path
    integrity_result: str
    safety_copy_path: Path | None


class ProfileStoreService:
    """Manages profile database files inside the app database directory."""

    def __init__(self, database_dir: str | Path):
        self.database_dir = Path(database_dir)

    @staticmethod
    def sanitize_profile_name(name: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", (name or "").strip())
        if safe and not safe.lower().endswith(".db"):
            safe += ".db"
        return safe

    def build_profile_path(self, name: str) -> Path:
        safe = self.sanitize_profile_name(name)
        if not safe:
            raise ValueError("Profile name is required")
        return self.database_dir / safe

    def list_profiles(self) -> list[str]:
        if not self.database_dir.exists():
            return []
        return [str(path) for path in sorted(self.database_dir.glob("*.db"))]

    def delete_profile(self, path: str | Path) -> None:
        profile_path = Path(path)
        try:
            profile_path.unlink()
        except FileNotFoundError:
            pass


class DatabaseMaintenanceService:
    """Manages backup, restore, and integrity operations for SQLite files."""

    def __init__(self, backups_dir: str | Path):
        self.backups_dir = Path(backups_dir)

    def create_backup(
        self,
        conn: sqlite3.Connection,
        src_path: str | Path,
        *,
        close_connection: Callable[[], None] | None = None,
        reopen_connection: Callable[[], None] | None = None,
    ) -> BackupResult:
        src = Path(src_path)
        if not src.exists():
            raise FileNotFoundError(src)

        self.backups_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dst = self.backups_dir / f"{src.stem}_{timestamp}.db"

        try:
            conn.commit()
        except Exception:
            pass

        try:
            backup_conn = sqlite3.connect(str(dst))
            try:
                conn.backup(backup_conn)
                backup_conn.commit()
            finally:
                backup_conn.close()
            method = "backup_api"
        except Exception as backup_error:
            try:
                conn.execute(f"VACUUM INTO '{dst.as_posix()}'")
                method = "vacuum_into"
            except Exception as vacuum_error:
                if close_connection is None or reopen_connection is None:
                    raise RuntimeError(
                        f"Backup failed using backup API ({backup_error}) and VACUUM INTO ({vacuum_error})"
                    ) from vacuum_error
                close_connection()
                try:
                    shutil.copy2(src, dst)
                    for ext in (".wal", ".shm"):
                        companion = src.with_suffix(src.suffix + ext)
                        if companion.exists():
                            shutil.copy2(companion, dst.with_suffix(dst.suffix + ext))
                    method = "file_copy"
                finally:
                    reopen_connection()

        integrity = self.verify_integrity(dst)
        if integrity.lower() != "ok":
            raise RuntimeError(f"Integrity check failed for backup: {integrity}")
        return BackupResult(backup_path=dst, method=method)

    def verify_integrity(self, db_path: str | Path) -> str:
        conn = sqlite3.connect(str(db_path))
        try:
            row = conn.execute("PRAGMA integrity_check").fetchone()
            return row[0] if row else "unknown"
        finally:
            conn.close()

    def restore_database(self, backup_path: str | Path, current_db_path: str | Path) -> RestoreResult:
        src = Path(backup_path)
        dst = Path(current_db_path)
        if not src.exists():
            raise FileNotFoundError(src)

        safety_copy_path = None
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            pre_restore_dir = self.backups_dir / "pre_restore"
            pre_restore_dir.mkdir(parents=True, exist_ok=True)
            safety_copy_path = pre_restore_dir / f"{dst.stem}_pre_restore_{timestamp}.db"
            if dst.exists():
                shutil.copy2(dst, safety_copy_path)
                for ext in (".wal", ".shm"):
                    companion = dst.with_suffix(dst.suffix + ext)
                    if companion.exists():
                        shutil.copy2(companion, safety_copy_path.with_suffix(safety_copy_path.suffix + ext))
        except Exception:
            safety_copy_path = None

        shutil.copy2(src, dst)
        for ext in (".wal", ".shm"):
            stale = dst.with_suffix(dst.suffix + ext)
            if stale.exists():
                try:
                    stale.unlink()
                except Exception:
                    pass

        integrity = self.verify_integrity(dst)
        if integrity.lower() != "ok":
            raise RuntimeError(f"Integrity check failed after restore: {integrity}")
        return RestoreResult(restored_path=dst, integrity_result=integrity, safety_copy_path=safety_copy_path)

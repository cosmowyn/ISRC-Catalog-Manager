"""Thread-aware SQLite connection and coordination helpers."""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

SQLITE_TIMEOUT_SECONDS = 30.0
SQLITE_BUSY_TIMEOUT_MS = 30_000


def configure_sqlite_connection(
    conn: sqlite3.Connection,
    *,
    busy_timeout_ms: int = SQLITE_BUSY_TIMEOUT_MS,
) -> sqlite3.Connection:
    """Apply the app's standard SQLite safety pragmas to a connection."""

    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute(f"PRAGMA busy_timeout = {max(1, int(busy_timeout_ms))}")
    return conn


def is_lock_error(exc: BaseException) -> bool:
    text = str(exc or "").lower()
    return "locked" in text or "busy" in text


@dataclass(slots=True)
class SQLiteConnectionFactory:
    """Creates consistently configured SQLite connections for each thread."""

    timeout_seconds: float = SQLITE_TIMEOUT_SECONDS
    busy_timeout_ms: int = SQLITE_BUSY_TIMEOUT_MS

    def open(self, path: str | Path) -> sqlite3.Connection:
        db_path = Path(path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path), timeout=float(self.timeout_seconds))
        return configure_sqlite_connection(conn, busy_timeout_ms=self.busy_timeout_ms)


class DatabaseWriteCoordinator:
    """Serializes write-heavy background work per database path."""

    _registry_guard = threading.Lock()
    _locks: dict[str, threading.RLock] = {}

    def __init__(self, db_path: str | Path):
        self.db_path = str(Path(db_path))

    @classmethod
    def for_path(cls, db_path: str | Path) -> "DatabaseWriteCoordinator":
        normalized = str(Path(db_path))
        with cls._registry_guard:
            if normalized not in cls._locks:
                cls._locks[normalized] = threading.RLock()
        return cls(normalized)

    @contextmanager
    def acquire(self):
        lock = self._locks[self.db_path]
        lock.acquire()
        try:
            yield
        finally:
            lock.release()

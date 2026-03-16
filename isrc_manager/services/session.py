"""Database session bootstrap and profile-scoped key/value helpers."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QSettings

from .db_access import SQLiteConnectionFactory


@dataclass(slots=True)
class OpenDatabaseSession:
    conn: sqlite3.Connection
    cursor: sqlite3.Cursor


class ProfileKVService:
    """Manages the per-profile app_kv store."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def ensure_store(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS app_kv (
                key   TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )
        self.conn.commit()

    def get(self, key: str, default: object = None) -> object:
        row = self.conn.execute("SELECT value FROM app_kv WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set(self, key: str, value: object) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO app_kv(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, str(value)),
            )


class DatabaseSessionService:
    """Handles opening, closing, and remembering database sessions."""

    def __init__(self, connection_factory: SQLiteConnectionFactory | None = None):
        self.connection_factory = connection_factory or SQLiteConnectionFactory()

    def open(self, path: str | Path) -> OpenDatabaseSession:
        db_path = Path(path)
        db_path.parent.mkdir(parents=True, exist_ok=True)

        conn = self.connection_factory.open(db_path)
        cursor = conn.cursor()

        profile_kv = ProfileKVService(conn)
        profile_kv.ensure_store()

        return OpenDatabaseSession(conn=conn, cursor=cursor)

    @staticmethod
    def close(conn: sqlite3.Connection | None) -> None:
        if conn is None:
            return
        try:
            conn.commit()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass

    @staticmethod
    def remember_last_path(settings: QSettings, path: str) -> None:
        settings.setValue("db/last_path", path)
        settings.sync()

"""Persistent settings mutation services used by the UI layer."""

from __future__ import annotations

import sqlite3

from PySide6.QtCore import QSettings


class SettingsMutationService:
    """Centralizes writes to QSettings and profile-scoped singleton tables."""

    def __init__(self, conn: sqlite3.Connection, settings: QSettings):
        self.conn = conn
        self.settings = settings

    def _profile_set(self, key: str, value) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO app_kv(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, str(value)),
            )

    def set_identity(self, *, window_title: str, icon_path: str) -> dict[str, str]:
        identity = {
            "window_title": window_title,
            "icon_path": icon_path,
        }
        self.settings.setValue("identity/window_title", identity["window_title"])
        self.settings.setValue("identity/icon_path", identity["icon_path"])
        self.settings.sync()
        return identity

    def set_artist_code(self, value: str) -> None:
        self._profile_set("isrc_artist_code", value)

    def set_isrc_prefix(self, prefix: str) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO ISRC_Prefix (id, prefix) VALUES (1, ?) "
                "ON CONFLICT(id) DO UPDATE SET prefix=excluded.prefix",
                (prefix,),
            )

    def set_sena_number(self, value: str) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO SENA (id, number) VALUES (1, ?) "
                "ON CONFLICT(id) DO UPDATE SET number=excluded.number",
                (value,),
            )

    def set_btw_number(self, value: str) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO BTW (id, nr) VALUES (1, ?) "
                "ON CONFLICT(id) DO UPDATE SET nr=excluded.nr",
                (value,),
            )

    def set_buma_relatie_nummer(self, value: str) -> None:
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO BUMA_STEMRA (id, relatie_nummer, ipi)
                VALUES (1, ?, COALESCE((SELECT ipi FROM BUMA_STEMRA WHERE id=1), NULL))
                ON CONFLICT(id) DO UPDATE SET relatie_nummer=excluded.relatie_nummer
                """,
                (value,),
            )

    def set_buma_ipi(self, value: str) -> None:
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO BUMA_STEMRA (id, relatie_nummer, ipi)
                VALUES (1, COALESCE((SELECT relatie_nummer FROM BUMA_STEMRA WHERE id=1), NULL), ?)
                ON CONFLICT(id) DO UPDATE SET ipi=excluded.ipi
                """,
                (value,),
            )

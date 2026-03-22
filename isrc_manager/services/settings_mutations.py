"""Persistent settings mutation services used by the UI layer."""

from __future__ import annotations

import sqlite3

from PySide6.QtCore import QSettings

from isrc_manager.constants import (
    DEFAULT_AUTO_SNAPSHOT_INTERVAL_MINUTES,
    DEFAULT_HISTORY_AUTO_SNAPSHOT_KEEP_LATEST,
    DEFAULT_HISTORY_STORAGE_BUDGET_MB,
    MAX_AUTO_SNAPSHOT_INTERVAL_MINUTES,
    MAX_HISTORY_AUTO_SNAPSHOT_KEEP_LATEST,
    MAX_HISTORY_PRUNE_PRE_RESTORE_COPIES_AFTER_DAYS,
    MAX_HISTORY_STORAGE_BUDGET_MB,
    MIN_AUTO_SNAPSHOT_INTERVAL_MINUTES,
    MIN_HISTORY_AUTO_SNAPSHOT_KEEP_LATEST,
    MIN_HISTORY_PRUNE_PRE_RESTORE_COPIES_AFTER_DAYS,
    MIN_HISTORY_STORAGE_BUDGET_MB,
)


class SettingsMutationService:
    """Centralizes writes to QSettings and profile-scoped singleton tables."""

    def __init__(self, conn: sqlite3.Connection, settings: QSettings):
        self.conn = conn
        self.settings = settings

    def _profile_set(self, key: str, value: object) -> None:
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

    def set_auto_snapshot_enabled(self, enabled: bool) -> None:
        self._profile_set("auto_snapshot_enabled", "1" if bool(enabled) else "0")

    def set_auto_snapshot_interval_minutes(self, minutes: int) -> None:
        value = int(minutes)
        value = max(
            MIN_AUTO_SNAPSHOT_INTERVAL_MINUTES, min(MAX_AUTO_SNAPSHOT_INTERVAL_MINUTES, value)
        )
        if value <= 0:
            value = DEFAULT_AUTO_SNAPSHOT_INTERVAL_MINUTES
        self._profile_set("auto_snapshot_interval_minutes", value)

    def set_history_auto_cleanup_enabled(self, enabled: bool) -> None:
        self._profile_set("history_auto_cleanup_enabled", "1" if bool(enabled) else "0")

    def set_history_storage_budget_mb(self, megabytes: int) -> None:
        value = int(megabytes)
        value = max(MIN_HISTORY_STORAGE_BUDGET_MB, min(MAX_HISTORY_STORAGE_BUDGET_MB, value))
        if value <= 0:
            value = DEFAULT_HISTORY_STORAGE_BUDGET_MB
        self._profile_set("history_storage_budget_mb", value)

    def set_history_auto_snapshot_keep_latest(self, keep_latest: int) -> None:
        value = int(keep_latest)
        value = max(
            MIN_HISTORY_AUTO_SNAPSHOT_KEEP_LATEST,
            min(MAX_HISTORY_AUTO_SNAPSHOT_KEEP_LATEST, value),
        )
        if value <= 0:
            value = DEFAULT_HISTORY_AUTO_SNAPSHOT_KEEP_LATEST
        self._profile_set("history_auto_snapshot_keep_latest", value)

    def set_history_prune_pre_restore_copies_after_days(self, days: int) -> None:
        value = int(days)
        value = max(
            MIN_HISTORY_PRUNE_PRE_RESTORE_COPIES_AFTER_DAYS,
            min(MAX_HISTORY_PRUNE_PRE_RESTORE_COPIES_AFTER_DAYS, value),
        )
        self._profile_set("history_prune_pre_restore_copies_after_days", value)

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

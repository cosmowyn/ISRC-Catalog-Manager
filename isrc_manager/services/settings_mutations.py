"""Persistent settings mutation services used by the UI layer."""

from __future__ import annotations

import sqlite3

from PySide6.QtCore import QSettings

from isrc_manager.constants import (
    DEFAULT_AUTO_SNAPSHOT_INTERVAL_MINUTES,
    DEFAULT_HISTORY_AUTO_SNAPSHOT_KEEP_LATEST,
    DEFAULT_HISTORY_RETENTION_MODE,
    DEFAULT_HISTORY_STORAGE_BUDGET_MB,
    HISTORY_RETENTION_MODE_CHOICES,
    MAX_AUTO_SNAPSHOT_INTERVAL_MINUTES,
    MAX_HISTORY_AUTO_SNAPSHOT_KEEP_LATEST,
    MAX_HISTORY_PRUNE_PRE_RESTORE_COPIES_AFTER_DAYS,
    MAX_HISTORY_STORAGE_BUDGET_MB,
    MIN_AUTO_SNAPSHOT_INTERVAL_MINUTES,
    MIN_HISTORY_AUTO_SNAPSHOT_KEEP_LATEST,
    MIN_HISTORY_PRUNE_PRE_RESTORE_COPIES_AFTER_DAYS,
    MIN_HISTORY_STORAGE_BUDGET_MB,
)
from isrc_manager.storage_sizes import clamp_history_storage_budget_mb

from .settings_reads import OwnerPartySettings


class SettingsMutationService:
    """Centralizes writes to QSettings and profile-scoped singleton tables."""

    def __init__(self, conn: sqlite3.Connection, settings: QSettings):
        self.conn = conn
        self.settings = settings

    def _ensure_profile_store(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS app_kv (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )

    def _ensure_owner_binding_table(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ApplicationOwnerBinding (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                party_id INTEGER NOT NULL UNIQUE,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (party_id) REFERENCES Parties(id) ON DELETE RESTRICT
            )
            """
        )

    def _profile_set(self, key: str, value: object) -> None:
        with self.conn:
            self._ensure_profile_store()
            self.conn.execute(
                "INSERT INTO app_kv(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, str(value)),
            )

    @staticmethod
    def _clean_text(value: object | None) -> str:
        return str(value or "").strip()

    @staticmethod
    def _clean_party_id(value: object | None) -> int | None:
        if value is None:
            return None
        text = str(value).strip()
        if text == "":
            return None
        try:
            clean_value = int(text)
        except ValueError:
            return None
        return clean_value if clean_value > 0 else None

    def _current_owner_party_id(self) -> int | None:
        try:
            self._ensure_owner_binding_table()
            row = self.conn.execute(
                "SELECT party_id FROM ApplicationOwnerBinding WHERE id=1"
            ).fetchone()
        except sqlite3.OperationalError:
            row = None
        if row and row[0] is not None:
            return self._clean_party_id(row[0])
        try:
            row = self.conn.execute(
                "SELECT value FROM app_kv WHERE key='owner_party_id'"
            ).fetchone()
        except sqlite3.OperationalError:
            row = None
        return self._clean_party_id(row[0] if row else None)

    def _clear_legacy_owner_snapshot_locked(self) -> None:
        self._ensure_profile_store()
        owner_keys = [
            f"owner_{field_name}" for field_name in OwnerPartySettings.PROFILE_FIELD_NAMES
        ]
        owner_keys.append("owner_party_id")
        self.conn.executemany("DELETE FROM app_kv WHERE key=?", ((key,) for key in owner_keys))

    def _write_owner_party_field(self, field_name: str, value: str) -> bool:
        owner_party_id = self._current_owner_party_id()
        if owner_party_id is None:
            return False
        row = self.conn.execute(
            "SELECT id FROM Parties WHERE id=?",
            (int(owner_party_id),),
        ).fetchone()
        if row is None:
            return False
        with self.conn:
            self.conn.execute(
                f"UPDATE Parties SET {field_name}=?, updated_at=datetime('now') WHERE id=?",
                (self._clean_text(value), int(owner_party_id)),
            )
        return True

    def set_identity(self, *, window_title_override: str, icon_path: str) -> dict[str, str]:
        identity = {
            "window_title_override": window_title_override,
            "icon_path": icon_path,
        }
        self.settings.setValue("identity/window_title_override", identity["window_title_override"])
        # Keep the legacy key aligned with the raw override so older builds still read a safe value.
        self.settings.setValue("identity/window_title", identity["window_title_override"])
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

    def set_history_retention_mode(self, mode: str) -> None:
        normalized = str(mode or "").strip().lower()
        if normalized not in HISTORY_RETENTION_MODE_CHOICES:
            normalized = DEFAULT_HISTORY_RETENTION_MODE
        self._profile_set("history_retention_mode", normalized)

    def set_history_storage_budget_mb(self, megabytes: int) -> None:
        value = clamp_history_storage_budget_mb(int(megabytes))
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
        if self._write_owner_party_field("vat_number", value):
            with self.conn:
                self.conn.execute("DELETE FROM BTW WHERE id=1")
            return
        with self.conn:
            self.conn.execute(
                "INSERT INTO BTW (id, nr) VALUES (1, ?) "
                "ON CONFLICT(id) DO UPDATE SET nr=excluded.nr",
                (value,),
            )

    def set_buma_relatie_nummer(self, value: str) -> None:
        if self._write_owner_party_field("pro_number", value):
            with self.conn:
                self.conn.execute("DELETE FROM BUMA_STEMRA WHERE id=1")
            return
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
        if self._write_owner_party_field("ipi_cae", value):
            with self.conn:
                self.conn.execute("DELETE FROM BUMA_STEMRA WHERE id=1")
            return
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO BUMA_STEMRA (id, relatie_nummer, ipi)
                VALUES (1, COALESCE((SELECT relatie_nummer FROM BUMA_STEMRA WHERE id=1), NULL), ?)
                ON CONFLICT(id) DO UPDATE SET ipi=excluded.ipi
                """,
                (value,),
            )

    def set_owner_party_id(self, party_id: int | None) -> int | None:
        clean_party_id = self._clean_party_id(party_id)
        with self.conn:
            self._ensure_owner_binding_table()
            self._clear_legacy_owner_snapshot_locked()
            if clean_party_id is None:
                self.conn.execute("DELETE FROM ApplicationOwnerBinding WHERE id=1")
            else:
                self.conn.execute(
                    """
                    INSERT INTO ApplicationOwnerBinding(id, party_id)
                    VALUES (1, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        party_id=excluded.party_id,
                        updated_at=datetime('now')
                    """,
                    (int(clean_party_id),),
                )
        return clean_party_id

    def set_owner_party_settings(self, settings: OwnerPartySettings) -> OwnerPartySettings:
        clean_party_id = self.set_owner_party_id(getattr(settings, "party_id", None))
        return OwnerPartySettings(party_id=clean_party_id)

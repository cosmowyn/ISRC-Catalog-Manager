"""Persistent settings read services used by the UI layer."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from isrc_manager.constants import (
    DEFAULT_AUTO_SNAPSHOT_ENABLED,
    DEFAULT_AUTO_SNAPSHOT_INTERVAL_MINUTES,
    MAX_AUTO_SNAPSHOT_INTERVAL_MINUTES,
    MIN_AUTO_SNAPSHOT_INTERVAL_MINUTES,
)


@dataclass(slots=True)
class RegistrationSettings:
    isrc_prefix: str = ""
    sena_number: str = ""
    btw_number: str = ""
    buma_relatie_nummer: str = ""
    buma_ipi: str = ""


@dataclass(slots=True)
class AutoSnapshotSettings:
    enabled: bool = DEFAULT_AUTO_SNAPSHOT_ENABLED
    interval_minutes: int = DEFAULT_AUTO_SNAPSHOT_INTERVAL_MINUTES


class SettingsReadService:
    """Centralizes reads from profile-scoped singleton tables."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def _read_scalar(self, query: str) -> str:
        row = self.conn.execute(query).fetchone()
        if not row or row[0] is None:
            return ""
        return str(row[0]).strip()

    def _read_profile_value(self, key: str) -> str:
        row = self.conn.execute("SELECT value FROM app_kv WHERE key=?", (key,)).fetchone()
        if not row or row[0] is None:
            return ""
        return str(row[0]).strip()

    def load_isrc_prefix(self) -> str:
        return self._read_scalar("SELECT prefix FROM ISRC_Prefix WHERE id = 1")

    def load_sena_number(self) -> str:
        return self._read_scalar("SELECT number FROM SENA WHERE id = 1")

    def load_btw_number(self) -> str:
        return self._read_scalar("SELECT nr FROM BTW WHERE id = 1")

    def load_buma_relatie_nummer(self) -> str:
        return self._read_scalar("SELECT relatie_nummer FROM BUMA_STEMRA WHERE id = 1")

    def load_buma_ipi(self) -> str:
        return self._read_scalar("SELECT ipi FROM BUMA_STEMRA WHERE id = 1")

    def load_registration_settings(self) -> RegistrationSettings:
        row = self.conn.execute(
            "SELECT relatie_nummer, ipi FROM BUMA_STEMRA WHERE id = 1"
        ).fetchone()
        return RegistrationSettings(
            isrc_prefix=self.load_isrc_prefix(),
            sena_number=self.load_sena_number(),
            btw_number=self.load_btw_number(),
            buma_relatie_nummer=str(row[0]).strip() if row and row[0] is not None else "",
            buma_ipi=str(row[1]).strip() if row and row[1] is not None else "",
        )

    def load_auto_snapshot_enabled(self) -> bool:
        raw = self._read_profile_value("auto_snapshot_enabled")
        if raw == "":
            return bool(DEFAULT_AUTO_SNAPSHOT_ENABLED)
        return raw.strip().lower() not in {"0", "false", "off", "no"}

    def load_auto_snapshot_interval_minutes(self) -> int:
        raw = self._read_profile_value("auto_snapshot_interval_minutes")
        try:
            value = int(raw)
        except Exception:
            value = DEFAULT_AUTO_SNAPSHOT_INTERVAL_MINUTES
        return max(
            MIN_AUTO_SNAPSHOT_INTERVAL_MINUTES, min(MAX_AUTO_SNAPSHOT_INTERVAL_MINUTES, value)
        )

    def load_auto_snapshot_settings(self) -> AutoSnapshotSettings:
        return AutoSnapshotSettings(
            enabled=self.load_auto_snapshot_enabled(),
            interval_minutes=self.load_auto_snapshot_interval_minutes(),
        )

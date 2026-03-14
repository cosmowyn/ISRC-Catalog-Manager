"""Persistent GS1 settings stored across QSettings and the profile app_kv table."""

from __future__ import annotations

import sqlite3

from PySide6.QtCore import QSettings

from .gs1_models import GS1ProfileDefaults


class GS1SettingsService:
    """Owns app-wide template settings and profile-scoped GS1 defaults."""

    TEMPLATE_PATH_KEY = "gs1/template_path"

    PROFILE_KEY_MAP = {
        "target_market": "gs1/default_target_market",
        "language": "gs1/default_language",
        "brand": "gs1/default_brand",
        "subbrand": "gs1/default_subbrand",
        "packaging_type": "gs1/default_packaging_type",
        "product_classification": "gs1/default_product_classification",
    }

    def __init__(self, conn: sqlite3.Connection, settings: QSettings):
        self.conn = conn
        self.settings = settings

    def _profile_get(self, key: str) -> str:
        row = self.conn.execute("SELECT value FROM app_kv WHERE key=?", (key,)).fetchone()
        if not row or row[0] is None:
            return ""
        return str(row[0]).strip()

    def _profile_set(self, key: str, value: str) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO app_kv(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, str(value or "").strip()),
            )

    def load_template_path(self) -> str:
        return str(self.settings.value(self.TEMPLATE_PATH_KEY, "", str) or "").strip()

    def set_template_path(self, path: str) -> str:
        clean_path = str(path or "").strip()
        self.settings.setValue(self.TEMPLATE_PATH_KEY, clean_path)
        self.settings.sync()
        return clean_path

    def load_profile_defaults(self) -> GS1ProfileDefaults:
        return GS1ProfileDefaults(
            target_market=self._profile_get(self.PROFILE_KEY_MAP["target_market"]),
            language=self._profile_get(self.PROFILE_KEY_MAP["language"]),
            brand=self._profile_get(self.PROFILE_KEY_MAP["brand"]),
            subbrand=self._profile_get(self.PROFILE_KEY_MAP["subbrand"]),
            packaging_type=self._profile_get(self.PROFILE_KEY_MAP["packaging_type"]),
            product_classification=self._profile_get(self.PROFILE_KEY_MAP["product_classification"]),
        )

    def set_profile_defaults(self, defaults: GS1ProfileDefaults) -> GS1ProfileDefaults:
        self._profile_set(self.PROFILE_KEY_MAP["target_market"], defaults.target_market)
        self._profile_set(self.PROFILE_KEY_MAP["language"], defaults.language)
        self._profile_set(self.PROFILE_KEY_MAP["brand"], defaults.brand)
        self._profile_set(self.PROFILE_KEY_MAP["subbrand"], defaults.subbrand)
        self._profile_set(self.PROFILE_KEY_MAP["packaging_type"], defaults.packaging_type)
        self._profile_set(self.PROFILE_KEY_MAP["product_classification"], defaults.product_classification)
        return self.load_profile_defaults()


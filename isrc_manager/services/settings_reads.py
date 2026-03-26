"""Persistent settings read services used by the UI layer."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from isrc_manager.constants import (
    DEFAULT_AUTO_SNAPSHOT_ENABLED,
    DEFAULT_AUTO_SNAPSHOT_INTERVAL_MINUTES,
    DEFAULT_HISTORY_AUTO_CLEANUP_ENABLED,
    DEFAULT_HISTORY_AUTO_SNAPSHOT_KEEP_LATEST,
    DEFAULT_HISTORY_PRUNE_PRE_RESTORE_COPIES_AFTER_DAYS,
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


@dataclass(slots=True)
class RegistrationSettings:
    isrc_prefix: str = ""
    sena_number: str = ""
    btw_number: str = ""
    buma_relatie_nummer: str = ""
    buma_ipi: str = ""


@dataclass(slots=True)
class OwnerPartySettings:
    party_id: int | None = None
    legal_name: str = ""
    display_name: str = ""
    artist_name: str = ""
    company_name: str = ""
    first_name: str = ""
    middle_name: str = ""
    last_name: str = ""
    contact_person: str = ""
    email: str = ""
    alternative_email: str = ""
    phone: str = ""
    website: str = ""
    street_name: str = ""
    street_number: str = ""
    address_line1: str = ""
    address_line2: str = ""
    city: str = ""
    region: str = ""
    postal_code: str = ""
    country: str = ""
    bank_account_number: str = ""
    chamber_of_commerce_number: str = ""
    tax_id: str = ""
    vat_number: str = ""
    pro_affiliation: str = ""
    pro_number: str = ""
    ipi_cae: str = ""
    notes: str = ""

    PROFILE_FIELD_NAMES = (
        "legal_name",
        "display_name",
        "artist_name",
        "company_name",
        "first_name",
        "middle_name",
        "last_name",
        "contact_person",
        "email",
        "alternative_email",
        "phone",
        "website",
        "street_name",
        "street_number",
        "address_line1",
        "address_line2",
        "city",
        "region",
        "postal_code",
        "country",
        "bank_account_number",
        "chamber_of_commerce_number",
        "tax_id",
        "pro_affiliation",
        "notes",
    )

    def to_profile_payload(self) -> dict[str, str]:
        payload = {
            field_name: str(getattr(self, field_name, "") or "").strip()
            for field_name in self.PROFILE_FIELD_NAMES
        }
        party_id = self.party_id
        payload["party_id"] = str(party_id) if party_id is not None else ""
        return payload


@dataclass(slots=True)
class AutoSnapshotSettings:
    enabled: bool = DEFAULT_AUTO_SNAPSHOT_ENABLED
    interval_minutes: int = DEFAULT_AUTO_SNAPSHOT_INTERVAL_MINUTES


@dataclass(slots=True)
class HistoryRetentionSettings:
    retention_mode: str = DEFAULT_HISTORY_RETENTION_MODE
    auto_cleanup_enabled: bool = DEFAULT_HISTORY_AUTO_CLEANUP_ENABLED
    storage_budget_mb: int = DEFAULT_HISTORY_STORAGE_BUDGET_MB
    auto_snapshot_keep_latest: int = DEFAULT_HISTORY_AUTO_SNAPSHOT_KEEP_LATEST
    prune_pre_restore_copies_after_days: int = DEFAULT_HISTORY_PRUNE_PRE_RESTORE_COPIES_AFTER_DAYS


class SettingsReadService:
    """Centralizes reads from profile-scoped singleton tables."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    @staticmethod
    def _owner_binding_table_sql() -> str:
        return """
            CREATE TABLE IF NOT EXISTS ApplicationOwnerBinding (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                party_id INTEGER NOT NULL UNIQUE,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (party_id) REFERENCES Parties(id) ON DELETE RESTRICT
            )
        """

    def _read_scalar(self, query: str) -> str:
        row = self.conn.execute(query).fetchone()
        if not row or row[0] is None:
            return ""
        return str(row[0]).strip()

    def _read_profile_value(self, key: str) -> str:
        try:
            row = self.conn.execute("SELECT value FROM app_kv WHERE key=?", (key,)).fetchone()
        except sqlite3.OperationalError:
            return ""
        if not row or row[0] is None:
            return ""
        return str(row[0]).strip()

    def _read_profile_int(self, key: str) -> int | None:
        raw = self._read_profile_value(key)
        if raw == "":
            return None
        try:
            value = int(raw)
        except Exception:
            return None
        return value if value > 0 else None

    def load_owner_party_id(self) -> int | None:
        try:
            self.conn.execute(self._owner_binding_table_sql())
            row = self.conn.execute(
                "SELECT party_id FROM ApplicationOwnerBinding WHERE id=1"
            ).fetchone()
        except sqlite3.OperationalError:
            row = None
        if row and row[0] is not None:
            try:
                party_id = int(row[0])
            except Exception:
                party_id = None
            if party_id and party_id > 0:
                return party_id
        return self._read_profile_int("owner_party_id")

    def load_legacy_owner_party_snapshot(self) -> OwnerPartySettings:
        registration = self._load_legacy_registration_settings()
        return OwnerPartySettings(
            party_id=self._read_profile_int("owner_party_id"),
            legal_name=self._read_profile_value("owner_legal_name"),
            display_name=self._read_profile_value("owner_display_name"),
            artist_name=self._read_profile_value("owner_artist_name"),
            company_name=self._read_profile_value("owner_company_name"),
            first_name=self._read_profile_value("owner_first_name"),
            middle_name=self._read_profile_value("owner_middle_name"),
            last_name=self._read_profile_value("owner_last_name"),
            contact_person=self._read_profile_value("owner_contact_person"),
            email=self._read_profile_value("owner_email"),
            alternative_email=self._read_profile_value("owner_alternative_email"),
            phone=self._read_profile_value("owner_phone"),
            website=self._read_profile_value("owner_website"),
            street_name=self._read_profile_value("owner_street_name"),
            street_number=self._read_profile_value("owner_street_number"),
            address_line1=self._read_profile_value("owner_address_line1"),
            address_line2=self._read_profile_value("owner_address_line2"),
            city=self._read_profile_value("owner_city"),
            region=self._read_profile_value("owner_region"),
            postal_code=self._read_profile_value("owner_postal_code"),
            country=self._read_profile_value("owner_country"),
            bank_account_number=self._read_profile_value("owner_bank_account_number"),
            chamber_of_commerce_number=self._read_profile_value("owner_chamber_of_commerce_number"),
            tax_id=self._read_profile_value("owner_tax_id"),
            vat_number=registration.btw_number,
            pro_affiliation=self._read_profile_value("owner_pro_affiliation"),
            pro_number=registration.buma_relatie_nummer,
            ipi_cae=registration.buma_ipi,
            notes=self._read_profile_value("owner_notes"),
        )

    def _load_owner_party_from_record(
        self,
        party_id: int,
    ) -> OwnerPartySettings | None:
        try:
            row = self.conn.execute(
                """
                SELECT
                    id,
                    legal_name,
                    display_name,
                    artist_name,
                    company_name,
                    first_name,
                    middle_name,
                    last_name,
                    contact_person,
                    email,
                    alternative_email,
                    phone,
                    website,
                    street_name,
                    street_number,
                    address_line1,
                    address_line2,
                    city,
                    region,
                    postal_code,
                    country,
                    bank_account_number,
                    chamber_of_commerce_number,
                    tax_id,
                    vat_number,
                    pro_affiliation,
                    pro_number,
                    ipi_cae,
                    notes
                FROM Parties
                WHERE id=?
                """,
                (int(party_id),),
            ).fetchone()
        except sqlite3.OperationalError:
            return None
        if row is None:
            return None
        return OwnerPartySettings(
            party_id=int(row[0]),
            legal_name=str(row[1] or "").strip(),
            display_name=str(row[2] or "").strip(),
            artist_name=str(row[3] or "").strip(),
            company_name=str(row[4] or "").strip(),
            first_name=str(row[5] or "").strip(),
            middle_name=str(row[6] or "").strip(),
            last_name=str(row[7] or "").strip(),
            contact_person=str(row[8] or "").strip(),
            email=str(row[9] or "").strip(),
            alternative_email=str(row[10] or "").strip(),
            phone=str(row[11] or "").strip(),
            website=str(row[12] or "").strip(),
            street_name=str(row[13] or "").strip(),
            street_number=str(row[14] or "").strip(),
            address_line1=str(row[15] or "").strip(),
            address_line2=str(row[16] or "").strip(),
            city=str(row[17] or "").strip(),
            region=str(row[18] or "").strip(),
            postal_code=str(row[19] or "").strip(),
            country=str(row[20] or "").strip(),
            bank_account_number=str(row[21] or "").strip(),
            chamber_of_commerce_number=str(row[22] or "").strip(),
            tax_id=str(row[23] or "").strip(),
            vat_number=str(row[24] or "").strip(),
            pro_affiliation=str(row[25] or "").strip(),
            pro_number=str(row[26] or "").strip(),
            ipi_cae=str(row[27] or "").strip(),
            notes=str(row[28] or "").strip(),
        )

    def load_isrc_prefix(self) -> str:
        return self._read_scalar("SELECT prefix FROM ISRC_Prefix WHERE id = 1")

    def load_sena_number(self) -> str:
        return self._read_scalar("SELECT number FROM SENA WHERE id = 1")

    def _load_legacy_registration_settings(self) -> RegistrationSettings:
        row = self.conn.execute(
            "SELECT relatie_nummer, ipi FROM BUMA_STEMRA WHERE id = 1"
        ).fetchone()
        return RegistrationSettings(
            isrc_prefix=self.load_isrc_prefix(),
            sena_number=self.load_sena_number(),
            btw_number=self._read_scalar("SELECT nr FROM BTW WHERE id = 1"),
            buma_relatie_nummer=str(row[0]).strip() if row and row[0] is not None else "",
            buma_ipi=str(row[1]).strip() if row and row[1] is not None else "",
        )

    def load_btw_number(self) -> str:
        owner_settings = self.load_owner_party_settings()
        if owner_settings.party_id is not None and owner_settings.vat_number:
            return owner_settings.vat_number
        return self._read_scalar("SELECT nr FROM BTW WHERE id = 1")

    def load_buma_relatie_nummer(self) -> str:
        owner_settings = self.load_owner_party_settings()
        if owner_settings.party_id is not None and owner_settings.pro_number:
            return owner_settings.pro_number
        return self._read_scalar("SELECT relatie_nummer FROM BUMA_STEMRA WHERE id = 1")

    def load_buma_ipi(self) -> str:
        owner_settings = self.load_owner_party_settings()
        if owner_settings.party_id is not None and owner_settings.ipi_cae:
            return owner_settings.ipi_cae
        return self._read_scalar("SELECT ipi FROM BUMA_STEMRA WHERE id = 1")

    def load_registration_settings(self) -> RegistrationSettings:
        return RegistrationSettings(
            isrc_prefix=self.load_isrc_prefix(),
            sena_number=self.load_sena_number(),
            btw_number=self.load_btw_number(),
            buma_relatie_nummer=self.load_buma_relatie_nummer(),
            buma_ipi=self.load_buma_ipi(),
        )

    def load_owner_party_settings(self) -> OwnerPartySettings:
        party_id = self.load_owner_party_id()
        if party_id is None:
            return OwnerPartySettings()
        party_backed = self._load_owner_party_from_record(party_id)
        if party_backed is not None:
            return party_backed
        return OwnerPartySettings()

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

    def load_history_auto_cleanup_enabled(self) -> bool:
        raw = self._read_profile_value("history_auto_cleanup_enabled")
        if raw == "":
            return bool(DEFAULT_HISTORY_AUTO_CLEANUP_ENABLED)
        return raw.strip().lower() not in {"0", "false", "off", "no"}

    def load_history_retention_mode(self) -> str:
        raw = self._read_profile_value("history_retention_mode").strip().lower()
        if raw not in HISTORY_RETENTION_MODE_CHOICES:
            return DEFAULT_HISTORY_RETENTION_MODE
        return raw

    def load_history_storage_budget_mb(self) -> int:
        raw = self._read_profile_value("history_storage_budget_mb")
        try:
            value = int(raw)
        except Exception:
            value = DEFAULT_HISTORY_STORAGE_BUDGET_MB
        return max(MIN_HISTORY_STORAGE_BUDGET_MB, min(MAX_HISTORY_STORAGE_BUDGET_MB, value))

    def load_history_auto_snapshot_keep_latest(self) -> int:
        raw = self._read_profile_value("history_auto_snapshot_keep_latest")
        try:
            value = int(raw)
        except Exception:
            value = DEFAULT_HISTORY_AUTO_SNAPSHOT_KEEP_LATEST
        return max(
            MIN_HISTORY_AUTO_SNAPSHOT_KEEP_LATEST,
            min(MAX_HISTORY_AUTO_SNAPSHOT_KEEP_LATEST, value),
        )

    def load_history_prune_pre_restore_copies_after_days(self) -> int:
        raw = self._read_profile_value("history_prune_pre_restore_copies_after_days")
        try:
            value = int(raw)
        except Exception:
            value = DEFAULT_HISTORY_PRUNE_PRE_RESTORE_COPIES_AFTER_DAYS
        return max(
            MIN_HISTORY_PRUNE_PRE_RESTORE_COPIES_AFTER_DAYS,
            min(MAX_HISTORY_PRUNE_PRE_RESTORE_COPIES_AFTER_DAYS, value),
        )

    def load_history_retention_settings(self) -> HistoryRetentionSettings:
        return HistoryRetentionSettings(
            retention_mode=self.load_history_retention_mode(),
            auto_cleanup_enabled=self.load_history_auto_cleanup_enabled(),
            storage_budget_mb=self.load_history_storage_budget_mb(),
            auto_snapshot_keep_latest=self.load_history_auto_snapshot_keep_latest(),
            prune_pre_restore_copies_after_days=(
                self.load_history_prune_pre_restore_copies_after_days()
            ),
        )

"""Persistent GS1 settings stored across the profile DB and app_kv table."""

from __future__ import annotations

import json
import mimetypes
import sqlite3
from pathlib import Path

from PySide6.QtCore import QSettings

from isrc_manager.media.blob_files import _read_blob_from_path

from .gs1_models import (
    GS1ContractEntry,
    GS1ProfileDefaults,
    GS1TemplateAsset,
    GS1TemplateVerificationError,
)


class GS1SettingsService:
    """Owns GS1 workbook storage plus profile-scoped defaults."""

    TEMPLATE_PATH_KEY = "gs1/template_path"
    CONTRACTS_JSON_KEY = "gs1/contracts_json"
    CONTRACTS_CSV_PATH_KEY = "gs1/contracts_csv_path"
    TEMPLATE_STORAGE_TABLE = "GS1TemplateStorage"
    ALLOWED_TEMPLATE_SUFFIXES = {".xlsx", ".xlsm", ".xltx", ".xltm"}

    PROFILE_KEY_MAP = {
        "contract_number": "gs1/default_contract_number",
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
        self._ensure_template_storage_table()

    def _ensure_template_storage_table(self) -> None:
        with self.conn:
            self.conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self.TEMPLATE_STORAGE_TABLE} (
                    id INTEGER PRIMARY KEY CHECK(id = 1),
                    filename TEXT NOT NULL,
                    source_path TEXT,
                    workbook_blob BLOB NOT NULL,
                    mime_type TEXT,
                    size_bytes INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )

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

    def load_stored_template_info(self) -> GS1TemplateAsset | None:
        row = self.conn.execute(
            f"""
            SELECT filename, source_path, mime_type, size_bytes, created_at, updated_at
            FROM {self.TEMPLATE_STORAGE_TABLE}
            WHERE id = 1
            """
        ).fetchone()
        if not row:
            return None
        return GS1TemplateAsset(
            filename=str(row[0] or "").strip(),
            source_path=str(row[1] or "").strip(),
            mime_type=str(row[2] or "").strip(),
            size_bytes=int(row[3] or 0),
            created_at=str(row[4] or "").strip() or None,
            updated_at=str(row[5] or "").strip() or None,
            stored_in_database=True,
        )

    def load_template_asset(self) -> GS1TemplateAsset | None:
        stored = self.load_stored_template_info()
        if stored is not None:
            return stored
        legacy_path = self.load_template_path()
        if not legacy_path:
            return None
        path = Path(legacy_path)
        size_bytes = 0
        try:
            if path.exists():
                size_bytes = int(path.stat().st_size)
        except OSError:
            size_bytes = 0
        return GS1TemplateAsset(
            filename=path.name,
            source_path=str(path),
            mime_type=str(mimetypes.guess_type(path.name)[0] or "").strip(),
            size_bytes=size_bytes,
            stored_in_database=False,
        )

    def has_stored_template(self) -> bool:
        row = self.conn.execute(
            f"SELECT 1 FROM {self.TEMPLATE_STORAGE_TABLE} WHERE id = 1 LIMIT 1"
        ).fetchone()
        return row is not None

    def load_stored_template_bytes(self) -> bytes | None:
        row = self.conn.execute(
            f"SELECT workbook_blob FROM {self.TEMPLATE_STORAGE_TABLE} WHERE id = 1"
        ).fetchone()
        if not row or row[0] is None:
            return None
        blob = row[0]
        return blob if isinstance(blob, bytes) else bytes(blob)

    def import_template_from_path(self, template_path: str | Path) -> GS1TemplateAsset:
        source = Path(str(template_path or "").strip())
        if not str(source):
            raise GS1TemplateVerificationError("Choose an official GS1 workbook first.")
        if not source.exists():
            raise GS1TemplateVerificationError(f"Configured GS1 workbook was not found:\n{source}")
        if source.suffix.lower() not in self.ALLOWED_TEMPLATE_SUFFIXES:
            raise GS1TemplateVerificationError(
                "The selected file is not a supported Excel workbook. Choose an .xlsx, .xlsm, .xltx, or .xltm file."
            )

        workbook_bytes = _read_blob_from_path(str(source))
        mime_type = str(mimetypes.guess_type(source.name)[0] or "").strip()
        with self.conn:
            self.conn.execute(
                f"""
                INSERT INTO {self.TEMPLATE_STORAGE_TABLE} (
                    id,
                    filename,
                    source_path,
                    workbook_blob,
                    mime_type,
                    size_bytes,
                    created_at,
                    updated_at
                )
                VALUES (
                    1,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    COALESCE(
                        (SELECT created_at FROM {self.TEMPLATE_STORAGE_TABLE} WHERE id = 1),
                        datetime('now')
                    ),
                    datetime('now')
                )
                ON CONFLICT(id) DO UPDATE SET
                    filename = excluded.filename,
                    source_path = excluded.source_path,
                    workbook_blob = excluded.workbook_blob,
                    mime_type = excluded.mime_type,
                    size_bytes = excluded.size_bytes,
                    updated_at = datetime('now')
                """,
                (
                    source.name,
                    str(source),
                    sqlite3.Binary(workbook_bytes),
                    mime_type,
                    len(workbook_bytes),
                ),
            )
        self.set_template_path("")
        stored = self.load_stored_template_info()
        if stored is None:
            raise RuntimeError("Failed to store the GS1 workbook in the profile database.")
        return stored

    def export_stored_template(self, destination_path: str | Path) -> Path:
        workbook_bytes = self.load_stored_template_bytes()
        if workbook_bytes is None:
            raise GS1TemplateVerificationError(
                "No official GS1 workbook has been stored in this profile yet."
            )
        destination = Path(destination_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(workbook_bytes)
        return destination

    def load_profile_defaults(self) -> GS1ProfileDefaults:
        return GS1ProfileDefaults(
            contract_number=self._profile_get(self.PROFILE_KEY_MAP["contract_number"]),
            target_market=self._profile_get(self.PROFILE_KEY_MAP["target_market"]),
            language=self._profile_get(self.PROFILE_KEY_MAP["language"]),
            brand=self._profile_get(self.PROFILE_KEY_MAP["brand"]),
            subbrand=self._profile_get(self.PROFILE_KEY_MAP["subbrand"]),
            packaging_type=self._profile_get(self.PROFILE_KEY_MAP["packaging_type"]),
            product_classification=self._profile_get(
                self.PROFILE_KEY_MAP["product_classification"]
            ),
        )

    def set_profile_defaults(self, defaults: GS1ProfileDefaults) -> GS1ProfileDefaults:
        self._profile_set(self.PROFILE_KEY_MAP["contract_number"], defaults.contract_number)
        self._profile_set(self.PROFILE_KEY_MAP["target_market"], defaults.target_market)
        self._profile_set(self.PROFILE_KEY_MAP["language"], defaults.language)
        self._profile_set(self.PROFILE_KEY_MAP["brand"], defaults.brand)
        self._profile_set(self.PROFILE_KEY_MAP["subbrand"], defaults.subbrand)
        self._profile_set(self.PROFILE_KEY_MAP["packaging_type"], defaults.packaging_type)
        self._profile_set(
            self.PROFILE_KEY_MAP["product_classification"], defaults.product_classification
        )
        return self.load_profile_defaults()

    def load_contracts(self) -> tuple[GS1ContractEntry, ...]:
        raw_payload = self._profile_get(self.CONTRACTS_JSON_KEY)
        if not raw_payload:
            return ()
        try:
            payload = json.loads(raw_payload)
        except json.JSONDecodeError:
            return ()
        contracts: list[GS1ContractEntry] = []
        for item in payload if isinstance(payload, list) else []:
            if not isinstance(item, dict):
                continue
            contract_number = str(item.get("contract_number") or "").strip()
            if not contract_number:
                continue
            contracts.append(
                GS1ContractEntry(
                    contract_number=contract_number,
                    product=str(item.get("product") or "").strip(),
                    company_number=str(item.get("company_number") or "").strip(),
                    start_number=str(item.get("start_number") or "").strip(),
                    end_number=str(item.get("end_number") or "").strip(),
                    renewal_date=str(item.get("renewal_date") or "").strip(),
                    end_date=str(item.get("end_date") or "").strip(),
                    status=str(item.get("status") or "").strip(),
                    tier=str(item.get("tier") or "").strip(),
                )
            )
        return tuple(contracts)

    def set_contracts(
        self,
        contracts: tuple[GS1ContractEntry, ...] | list[GS1ContractEntry],
        *,
        source_path: str = "",
    ) -> tuple[GS1ContractEntry, ...]:
        normalized = tuple(
            GS1ContractEntry(
                contract_number=str(contract.contract_number or "").strip(),
                product=str(contract.product or "").strip(),
                company_number=str(contract.company_number or "").strip(),
                start_number=str(contract.start_number or "").strip(),
                end_number=str(contract.end_number or "").strip(),
                renewal_date=str(contract.renewal_date or "").strip(),
                end_date=str(contract.end_date or "").strip(),
                status=str(contract.status or "").strip(),
                tier=str(contract.tier or "").strip(),
            )
            for contract in contracts
            if str(contract.contract_number or "").strip()
        )
        payload = json.dumps(
            [
                {
                    "contract_number": contract.contract_number,
                    "product": contract.product,
                    "company_number": contract.company_number,
                    "start_number": contract.start_number,
                    "end_number": contract.end_number,
                    "renewal_date": contract.renewal_date,
                    "end_date": contract.end_date,
                    "status": contract.status,
                    "tier": contract.tier,
                }
                for contract in normalized
            ],
            ensure_ascii=True,
            separators=(",", ":"),
        )
        self._profile_set(self.CONTRACTS_JSON_KEY, payload)
        self._profile_set(self.CONTRACTS_CSV_PATH_KEY, source_path)
        return self.load_contracts()

    def clear_contracts(self) -> None:
        self._profile_set(self.CONTRACTS_JSON_KEY, "")
        self._profile_set(self.CONTRACTS_CSV_PATH_KEY, "")

    def load_contracts_csv_path(self) -> str:
        return self._profile_get(self.CONTRACTS_CSV_PATH_KEY)

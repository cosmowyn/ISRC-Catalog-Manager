"""Persistent GS1 settings stored across QSettings and the profile app_kv table."""

from __future__ import annotations

import json
import sqlite3

from PySide6.QtCore import QSettings

from .gs1_models import GS1ContractEntry, GS1ProfileDefaults


class GS1SettingsService:
    """Owns app-wide template settings and profile-scoped GS1 defaults."""

    TEMPLATE_PATH_KEY = "gs1/template_path"
    CONTRACTS_JSON_KEY = "gs1/contracts_json"
    CONTRACTS_CSV_PATH_KEY = "gs1/contracts_csv_path"

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
            contract_number=self._profile_get(self.PROFILE_KEY_MAP["contract_number"]),
            target_market=self._profile_get(self.PROFILE_KEY_MAP["target_market"]),
            language=self._profile_get(self.PROFILE_KEY_MAP["language"]),
            brand=self._profile_get(self.PROFILE_KEY_MAP["brand"]),
            subbrand=self._profile_get(self.PROFILE_KEY_MAP["subbrand"]),
            packaging_type=self._profile_get(self.PROFILE_KEY_MAP["packaging_type"]),
            product_classification=self._profile_get(self.PROFILE_KEY_MAP["product_classification"]),
        )

    def set_profile_defaults(self, defaults: GS1ProfileDefaults) -> GS1ProfileDefaults:
        self._profile_set(self.PROFILE_KEY_MAP["contract_number"], defaults.contract_number)
        self._profile_set(self.PROFILE_KEY_MAP["target_market"], defaults.target_market)
        self._profile_set(self.PROFILE_KEY_MAP["language"], defaults.language)
        self._profile_set(self.PROFILE_KEY_MAP["brand"], defaults.brand)
        self._profile_set(self.PROFILE_KEY_MAP["subbrand"], defaults.subbrand)
        self._profile_set(self.PROFILE_KEY_MAP["packaging_type"], defaults.packaging_type)
        self._profile_set(self.PROFILE_KEY_MAP["product_classification"], defaults.product_classification)
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

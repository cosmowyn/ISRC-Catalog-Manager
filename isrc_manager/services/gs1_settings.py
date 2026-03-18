"""Persistent GS1 settings stored across the profile DB and app_kv table."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from PySide6.QtCore import QSettings

from isrc_manager.file_storage import (
    STORAGE_MODE_DATABASE,
    STORAGE_MODE_MANAGED_FILE,
    ManagedFileStorage,
    coalesce_filename,
    guess_mime_type,
    infer_storage_mode,
    normalize_storage_mode,
)
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

    def __init__(
        self,
        conn: sqlite3.Connection,
        settings: QSettings,
        data_root: str | Path | None = None,
    ):
        self.conn = conn
        self.settings = settings
        self.data_root = self._resolve_data_root(data_root)
        self.template_store = ManagedFileStorage(
            data_root=self.data_root, relative_root="gs1_templates"
        )
        self._ensure_template_storage_table()

    def _resolve_data_root(self, data_root: str | Path | None) -> Path | None:
        if data_root is not None:
            return Path(data_root).resolve()
        try:
            settings_file = str(self.settings.fileName() or "").strip()
        except Exception:
            settings_file = ""
        if settings_file:
            path = Path(settings_file)
            if path.suffix.lower() == ".ini":
                return path.resolve().parent
        return None

    def _ensure_template_storage_table(self) -> None:
        with self.conn:
            self.conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self.TEMPLATE_STORAGE_TABLE} (
                    id INTEGER PRIMARY KEY CHECK(id = 1),
                    filename TEXT NOT NULL,
                    source_path TEXT,
                    managed_file_path TEXT,
                    storage_mode TEXT,
                    workbook_blob BLOB,
                    mime_type TEXT,
                    size_bytes INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            columns = {
                str(row[1])
                for row in self.conn.execute(
                    f"PRAGMA table_info({self.TEMPLATE_STORAGE_TABLE})"
                ).fetchall()
                if row and row[1]
            }
            for column_name, column_sql in (
                ("managed_file_path", "TEXT"),
                ("storage_mode", "TEXT"),
            ):
                if column_name not in columns:
                    self.conn.execute(
                        f"ALTER TABLE {self.TEMPLATE_STORAGE_TABLE} ADD COLUMN {column_name} {column_sql}"
                    )
            if "workbook_blob" not in columns:
                self.conn.execute(
                    f"ALTER TABLE {self.TEMPLATE_STORAGE_TABLE} ADD COLUMN workbook_blob BLOB"
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
            SELECT
                filename,
                source_path,
                managed_file_path,
                storage_mode,
                mime_type,
                size_bytes,
                created_at,
                updated_at,
                CASE WHEN workbook_blob IS NOT NULL THEN 1 ELSE 0 END AS has_blob
            FROM {self.TEMPLATE_STORAGE_TABLE}
            WHERE id = 1
            """
        ).fetchone()
        if not row:
            return None
        mode = infer_storage_mode(
            explicit_mode=row[3],
            stored_path=row[2] or row[1],
            blob_value=b"x" if row[8] else None,
            default=STORAGE_MODE_DATABASE,
        )
        return GS1TemplateAsset(
            filename=str(row[0] or "").strip(),
            source_path=str(row[1] or "").strip(),
            managed_file_path=str(row[2] or "").strip(),
            storage_mode=mode or STORAGE_MODE_DATABASE,
            mime_type=str(row[4] or "").strip(),
            size_bytes=int(row[5] or 0),
            created_at=str(row[6] or "").strip() or None,
            updated_at=str(row[7] or "").strip() or None,
            stored_in_database=(mode == STORAGE_MODE_DATABASE),
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
            managed_file_path="",
            storage_mode=STORAGE_MODE_MANAGED_FILE if path.exists() else STORAGE_MODE_DATABASE,
            mime_type=guess_mime_type(path.name),
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
            f"""
            SELECT workbook_blob, managed_file_path, storage_mode, source_path, filename
            FROM {self.TEMPLATE_STORAGE_TABLE}
            WHERE id = 1
            """
        ).fetchone()
        if not row:
            return None
        blob, managed_file_path, storage_mode, source_path, filename = row
        mode = infer_storage_mode(
            explicit_mode=storage_mode,
            stored_path=managed_file_path or source_path,
            blob_value=blob,
            default=STORAGE_MODE_DATABASE,
        )
        if mode == STORAGE_MODE_DATABASE:
            if blob is None:
                return None
            return bytes(blob)
        path = self.template_store.resolve(managed_file_path or source_path)
        if path is None or not path.exists():
            return None
        return Path(path).read_bytes()

    def import_template_from_path(
        self,
        template_path: str | Path,
        *,
        storage_mode: str | None = None,
    ) -> GS1TemplateAsset:
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
        mime_type = guess_mime_type(source.name)
        clean_mode = normalize_storage_mode(storage_mode, default=STORAGE_MODE_DATABASE)
        managed_file_path = None
        if clean_mode == STORAGE_MODE_MANAGED_FILE:
            if self.template_store.data_root is None:
                raise GS1TemplateVerificationError(
                    "Managed GS1 template storage is not configured."
                )
            managed_file_path = self.template_store.write_bytes(
                workbook_bytes,
                filename=coalesce_filename(source.name, default_stem="gs1-template"),
                subdir="templates",
            )
        with self.conn:
            self.conn.execute(
                f"""
                INSERT INTO {self.TEMPLATE_STORAGE_TABLE} (
                    id,
                    filename,
                    source_path,
                    managed_file_path,
                    storage_mode,
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
                    managed_file_path = excluded.managed_file_path,
                    storage_mode = excluded.storage_mode,
                    workbook_blob = excluded.workbook_blob,
                    mime_type = excluded.mime_type,
                    size_bytes = excluded.size_bytes,
                    updated_at = datetime('now')
                """,
                (
                    source.name,
                    str(source),
                    managed_file_path,
                    clean_mode,
                    sqlite3.Binary(workbook_bytes) if clean_mode == STORAGE_MODE_DATABASE else None,
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

    def convert_template_storage_mode(self, target_mode: str) -> GS1TemplateAsset:
        stored = self.load_stored_template_info()
        if stored is None:
            raise GS1TemplateVerificationError(
                "No official GS1 workbook has been stored in this profile yet."
            )
        clean_target = normalize_storage_mode(target_mode)
        current_mode = infer_storage_mode(
            explicit_mode=stored.storage_mode,
            stored_path=stored.managed_file_path or stored.source_path,
            blob_value=self.load_stored_template_bytes(),
            default=STORAGE_MODE_DATABASE,
        )
        if current_mode == clean_target:
            return stored
        workbook_bytes = self.load_stored_template_bytes()
        if workbook_bytes is None:
            raise GS1TemplateVerificationError("The stored GS1 workbook is missing or unreadable.")
        managed_file_path = stored.managed_file_path
        old_managed_path = managed_file_path
        blob_value = None
        if clean_target == STORAGE_MODE_DATABASE:
            blob_value = sqlite3.Binary(workbook_bytes)
            managed_file_path = ""
        else:
            if self.template_store.data_root is None:
                raise GS1TemplateVerificationError(
                    "Managed GS1 template storage is not configured."
                )
            managed_file_path = self.template_store.write_bytes(
                workbook_bytes,
                filename=coalesce_filename(stored.filename, default_stem="gs1-template"),
                subdir="templates",
            )
        with self.conn:
            self.conn.execute(
                f"""
                UPDATE {self.TEMPLATE_STORAGE_TABLE}
                SET managed_file_path=?,
                    storage_mode=?,
                    workbook_blob=?,
                    updated_at=datetime('now')
                WHERE id = 1
                """,
                (
                    managed_file_path,
                    clean_target,
                    blob_value,
                ),
            )
        if clean_target == STORAGE_MODE_DATABASE and old_managed_path:
            path = self.template_store.resolve(old_managed_path)
            if path is not None and path.exists():
                try:
                    path.unlink(missing_ok=True)
                except Exception:
                    pass
        updated = self.load_stored_template_info()
        if updated is None:
            raise RuntimeError("Failed to convert GS1 workbook storage mode.")
        return updated

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

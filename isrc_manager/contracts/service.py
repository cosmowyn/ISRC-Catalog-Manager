"""Contract lifecycle, obligations, and document versioning services."""

from __future__ import annotations

import hashlib
import mimetypes
import sqlite3
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path

from isrc_manager.code_registry import (
    BUILTIN_CATEGORY_CONTRACT_NUMBER,
    BUILTIN_CATEGORY_LICENSE_NUMBER,
    BUILTIN_CATEGORY_REGISTRY_SHA256_KEY,
    CATALOG_MODE_EMPTY,
    CATALOG_MODE_EXTERNAL,
    CATALOG_MODE_INTERNAL,
    ENTRY_KIND_MANUAL_CAPTURE,
    GENERATION_STRATEGY_SHA256,
    CodeRegistryEntryRecord,
    CodeRegistryService,
)
from isrc_manager.domain.repertoire import clean_text, parse_iso_date
from isrc_manager.file_storage import (
    STORAGE_MODE_DATABASE,
    STORAGE_MODE_MANAGED_FILE,
    ManagedFileStorage,
    bytes_from_blob,
    coalesce_filename,
    infer_storage_mode,
    normalize_storage_mode,
    sha256_digest,
)
from isrc_manager.parties import PartyService

from .models import (
    CONTRACT_STATUS_CHOICES,
    DOCUMENT_TYPE_CHOICES,
    OBLIGATION_TYPE_CHOICES,
    ContractDeadline,
    ContractDetail,
    ContractDocumentPayload,
    ContractDocumentRecord,
    ContractObligationPayload,
    ContractObligationRecord,
    ContractPartyPayload,
    ContractPartyRecord,
    ContractPayload,
    ContractRecord,
    ContractValidationIssue,
)


class ContractService:
    """Owns first-class contract records, obligations, and document storage."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        data_root: str | Path | None = None,
        *,
        party_service: PartyService | None = None,
    ):
        self.conn = conn
        self.data_root = Path(data_root) if data_root is not None else None
        self.documents_root = (
            self.data_root / "contract_documents" if self.data_root is not None else None
        )
        self.document_store = ManagedFileStorage(
            data_root=data_root, relative_root="contract_documents"
        )
        self.party_service = party_service
        self._code_registry_service_instance: CodeRegistryService | None = None
        self._ensure_storage_columns()

    @staticmethod
    def _clean_status(value: str | None) -> str:
        clean = str(value or "draft").strip().lower().replace(" ", "_")
        if clean not in CONTRACT_STATUS_CHOICES:
            return "draft"
        return clean

    @staticmethod
    def _clean_obligation_type(value: str | None) -> str:
        clean = str(value or "other").strip().lower().replace(" ", "_")
        if clean not in OBLIGATION_TYPE_CHOICES:
            return "other"
        return clean

    @staticmethod
    def _clean_document_type(value: str | None) -> str:
        clean = str(value or "other").strip().lower().replace(" ", "_")
        if clean not in DOCUMENT_TYPE_CHOICES:
            return "other"
        return clean

    def _code_registry_service(self) -> CodeRegistryService | None:
        tables = {
            str(row[0])
            for row in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            if row and row[0]
        }
        if "CodeRegistryCategories" not in tables:
            return None
        if self._code_registry_service_instance is None:
            self._code_registry_service_instance = CodeRegistryService(self.conn)
        return self._code_registry_service_instance

    def code_registry_service(self) -> CodeRegistryService | None:
        return self._code_registry_service()

    @staticmethod
    def _contract_identifier_spec(system_key: str) -> tuple[str, str, str, str, str]:
        column_map = {
            BUILTIN_CATEGORY_CONTRACT_NUMBER: (
                "contract_number",
                "contract_number_mode",
                "contract_registry_entry_id",
                "contract_external_code_identifier_id",
                "Contract Number",
            ),
            BUILTIN_CATEGORY_LICENSE_NUMBER: (
                "license_number",
                "license_number_mode",
                "license_registry_entry_id",
                "license_external_code_identifier_id",
                "License Number",
            ),
            BUILTIN_CATEGORY_REGISTRY_SHA256_KEY: (
                "registry_sha256_key",
                "registry_sha256_key_mode",
                "registry_sha256_key_entry_id",
                "registry_sha256_key_external_code_identifier_id",
                "Registry SHA-256 Key",
            ),
        }
        spec = column_map.get(system_key)
        if spec is None:
            raise ValueError(f"Unsupported contract registry category '{system_key}'.")
        return spec

    def _contract_columns(self) -> set[str]:
        return {
            str(row[1] or "")
            for row in self.conn.execute("PRAGMA table_info(Contracts)").fetchall()
            if row and row[1]
        }

    def _contract_external_column_name(self, system_key: str) -> str | None:
        _text_column, _mode_attr, _internal_column, external_column, _label = (
            self._contract_identifier_spec(system_key)
        )
        return external_column if external_column in self._contract_columns() else None

    def _contract_identifier_mode_sql(self, system_key: str, alias: str = "c") -> str:
        text_column, _mode_attr, internal_column, declared_external_column, _label = (
            self._contract_identifier_spec(system_key)
        )
        external_column = self._contract_external_column_name(system_key)
        external_predicate = (
            f"{alias}.{external_column} IS NOT NULL" if external_column is not None else "0"
        )
        return f"""
            CASE
                WHEN {alias}.{internal_column} IS NOT NULL THEN '{CATALOG_MODE_INTERNAL}'
                WHEN {external_predicate} THEN '{CATALOG_MODE_EXTERNAL}'
                WHEN COALESCE(trim({alias}.{text_column}), '') != '' THEN '{CATALOG_MODE_EXTERNAL}'
                ELSE '{CATALOG_MODE_EMPTY}'
            END
        """

    def _contract_identifier_select_sql(self, system_key: str, alias: str = "c") -> str:
        external_column = self._contract_external_column_name(system_key)
        if external_column is None:
            return "NULL"
        return f"{alias}.{external_column}"

    @staticmethod
    def _resolve_identifier_mode(
        *,
        mode: str | None,
        registry_entry_id: int | None,
        external_identifier_id: int | None,
        value: str | None,
    ) -> str:
        clean_mode = str(mode or "").strip().lower()
        if clean_mode in {CATALOG_MODE_INTERNAL, CATALOG_MODE_EXTERNAL, CATALOG_MODE_EMPTY}:
            return clean_mode
        if registry_entry_id is not None:
            return CATALOG_MODE_INTERNAL
        if external_identifier_id is not None:
            return CATALOG_MODE_EXTERNAL
        if clean_text(value):
            return ""
        return CATALOG_MODE_EMPTY

    def _assign_contract_registry_entry(
        self,
        *,
        contract_id: int,
        system_key: str,
        entry: CodeRegistryEntryRecord,
        cursor: sqlite3.Cursor | None = None,
    ) -> None:
        service = self._code_registry_service()
        if service is None:
            raise ValueError("Code registry service is unavailable.")
        resolution = service.resolve_identifier_input(
            system_key=system_key,
            mode=CATALOG_MODE_INTERNAL,
            value=entry.value,
            registry_entry_id=entry.id,
        )
        service.assign_identifier_to_owner(
            owner_kind="contract",
            owner_id=int(contract_id),
            system_key=system_key,
            resolution=resolution,
            provenance_kind="internal_registry",
            source_label="contract.ensure",
            cursor=cursor,
        )

    def ensure_registry_value_for_contract(
        self,
        contract_id: int,
        *,
        system_key: str,
        created_via: str = "contract.template.ensure",
    ) -> CodeRegistryEntryRecord:
        service = self._code_registry_service()
        if service is None:
            raise ValueError("Code registry service is unavailable.")
        contract = self.fetch_contract(int(contract_id))
        if contract is None:
            raise ValueError(f"Contract #{int(contract_id)} was not found.")
        category = service.fetch_category_by_system_key(system_key)
        if category is None:
            raise ValueError(f"Registry category '{system_key}' is not available.")
        text_column, mode_attr, link_column, external_column, label = self._contract_identifier_spec(
            system_key
        )
        existing_entry_id = getattr(contract, link_column, None)
        existing_external_id = getattr(contract, external_column, None)
        existing_mode = getattr(contract, mode_attr, None)
        existing_value = clean_text(getattr(contract, text_column, None))
        if existing_entry_id is not None:
            entry = service.fetch_entry(int(existing_entry_id))
            if entry is None:
                raise ValueError(f"{label} entry #{int(existing_entry_id)} is no longer available.")
            if int(entry.category_id) != int(category.id):
                raise ValueError(
                    f"{label} entry #{int(existing_entry_id)} does not belong to '{category.display_name}'."
                )
            if existing_value != entry.value:
                with self.conn:
                    self._assign_contract_registry_entry(
                        contract_id=int(contract_id),
                        system_key=system_key,
                        entry=entry,
                    )
            return entry
        if existing_external_id is not None:
            existing_value = None
        if existing_value:
            try:
                entry = service.capture_value_for_category(
                    category_id=category.id,
                    value=existing_value,
                    created_via=f"{created_via}.capture",
                    entry_kind=ENTRY_KIND_MANUAL_CAPTURE,
                )
            except ValueError as exc:
                raise ValueError(
                    f"{label} for contract #{int(contract_id)} is not valid for the configured registry rules: {exc}"
                ) from exc
            with self.conn:
                self._assign_contract_registry_entry(
                    contract_id=int(contract_id),
                    system_key=system_key,
                    entry=entry,
                )
            return entry
        result = (
            service.generate_sha256_key(
                category_id=category.id,
                created_via=created_via,
            )
            if category.generation_strategy == GENERATION_STRATEGY_SHA256
            else service.generate_next_code(
                category_id=category.id,
                created_via=created_via,
            )
        )
        with self.conn:
            self._assign_contract_registry_entry(
                contract_id=int(contract_id),
                system_key=system_key,
                entry=result.entry,
            )
        return result.entry

    def generate_registry_value_for_contract(
        self,
        contract_id: int,
        *,
        system_key: str,
        created_via: str = "contract.template.generate",
    ) -> CodeRegistryEntryRecord:
        service = self._code_registry_service()
        if service is None:
            raise ValueError("Code registry service is unavailable.")
        contract = self.fetch_contract(int(contract_id))
        if contract is None:
            raise ValueError(f"Contract #{int(contract_id)} was not found.")
        category = service.fetch_category_by_system_key(system_key)
        if category is None:
            raise ValueError(f"Registry category '{system_key}' is not available.")
        result = (
            service.generate_sha256_key(
                category_id=category.id,
                created_via=created_via,
            )
            if category.generation_strategy == GENERATION_STRATEGY_SHA256
            else service.generate_next_code(
                category_id=category.id,
                created_via=created_via,
            )
        )
        with self.conn:
            self._assign_contract_registry_entry(
                contract_id=int(contract_id),
                system_key=system_key,
                entry=result.entry,
            )
        return result.entry

    def _resolve_contract_identifier_resolution(
        self,
        *,
        payload: ContractPayload,
        system_key: str,
        created_via: str,
        cursor: sqlite3.Cursor | None = None,
    ):
        service = self._code_registry_service()
        if service is None:
            raise ValueError("Code registry service is unavailable.")
        text_attr, mode_attr, internal_attr, external_attr, label = self._contract_identifier_spec(
            system_key
        )
        internal_id = getattr(payload, internal_attr, None)
        external_id = getattr(payload, external_attr, None)
        resolution_mode = self._resolve_identifier_mode(
            mode=getattr(payload, mode_attr, None),
            registry_entry_id=int(internal_id) if internal_id is not None else None,
            external_identifier_id=int(external_id) if external_id is not None else None,
            value=getattr(payload, text_attr, None),
        )
        try:
            return service.resolve_identifier_input(
                system_key=system_key,
                mode=resolution_mode,
                value=getattr(payload, text_attr, None),
                registry_entry_id=int(internal_id) if internal_id is not None else None,
                external_identifier_id=int(external_id) if external_id is not None else None,
                created_via=created_via,
                cursor=cursor,
            )
        except ValueError as exc:
            raise ValueError(f"{label}: {exc}") from exc

    def _apply_registry_assignments(
        self,
        *,
        contract_id: int,
        payload: ContractPayload,
        cursor: sqlite3.Cursor,
        created_via: str,
    ) -> None:
        service = self._code_registry_service()
        if service is None:
            has_identifier_state = any(
                clean_text(getattr(payload, text_attr, None))
                or getattr(payload, internal_attr, None) is not None
                or getattr(payload, external_attr, None) is not None
                for text_attr, _mode_attr, internal_attr, external_attr, _label in (
                    self._contract_identifier_spec(BUILTIN_CATEGORY_CONTRACT_NUMBER),
                    self._contract_identifier_spec(BUILTIN_CATEGORY_LICENSE_NUMBER),
                    self._contract_identifier_spec(BUILTIN_CATEGORY_REGISTRY_SHA256_KEY),
                )
            )
            if has_identifier_state:
                raise ValueError("Code registry service is unavailable.")
            return
        for system_key in (
            BUILTIN_CATEGORY_CONTRACT_NUMBER,
            BUILTIN_CATEGORY_LICENSE_NUMBER,
            BUILTIN_CATEGORY_REGISTRY_SHA256_KEY,
        ):
            resolution = self._resolve_contract_identifier_resolution(
                payload=payload,
                system_key=system_key,
                created_via=f"{created_via}.{system_key}",
                cursor=cursor,
            )
            service.assign_identifier_to_owner(
                owner_kind="contract",
                owner_id=int(contract_id),
                system_key=system_key,
                resolution=resolution,
                provenance_kind="manual",
                source_label=created_via,
                cursor=cursor,
            )

    def _row_to_contract(self, row) -> ContractRecord:
        return ContractRecord(
            id=int(row[0]),
            title=str(row[1] or ""),
            contract_type=clean_text(row[2]),
            contract_number=clean_text(row[3]),
            contract_number_mode=str(row[4] or "").strip() or None,
            contract_registry_entry_id=int(row[5]) if row[5] is not None else None,
            contract_external_code_identifier_id=int(row[6]) if row[6] is not None else None,
            license_number=clean_text(row[7]),
            license_number_mode=str(row[8] or "").strip() or None,
            license_registry_entry_id=int(row[9]) if row[9] is not None else None,
            license_external_code_identifier_id=int(row[10]) if row[10] is not None else None,
            registry_sha256_key=clean_text(row[11]),
            registry_sha256_key_mode=str(row[12] or "").strip() or None,
            registry_sha256_key_entry_id=int(row[13]) if row[13] is not None else None,
            registry_sha256_key_external_code_identifier_id=int(row[14])
            if row[14] is not None
            else None,
            draft_date=clean_text(row[15]),
            signature_date=clean_text(row[16]),
            effective_date=clean_text(row[17]),
            start_date=clean_text(row[18]),
            end_date=clean_text(row[19]),
            renewal_date=clean_text(row[20]),
            notice_deadline=clean_text(row[21]),
            option_periods=clean_text(row[22]),
            reversion_date=clean_text(row[23]),
            termination_date=clean_text(row[24]),
            status=str(row[25] or "draft"),
            supersedes_contract_id=int(row[26]) if row[26] is not None else None,
            superseded_by_contract_id=int(row[27]) if row[27] is not None else None,
            summary=clean_text(row[28]),
            notes=clean_text(row[29]),
            profile_name=clean_text(row[30]),
            created_at=clean_text(row[31]),
            updated_at=clean_text(row[32]),
            obligation_count=int(row[33] or 0),
            document_count=int(row[34] or 0),
        )

    @staticmethod
    def _row_to_party(row) -> ContractPartyRecord:
        return ContractPartyRecord(
            party_id=int(row[0]),
            party_name=str(row[1] or ""),
            role_label=str(row[2] or "counterparty"),
            is_primary=bool(row[3]),
            notes=clean_text(row[4]),
        )

    @staticmethod
    def _row_to_obligation(row) -> ContractObligationRecord:
        return ContractObligationRecord(
            id=int(row[0]),
            contract_id=int(row[1]),
            obligation_type=str(row[2] or "other"),
            title=str(row[3] or ""),
            due_date=clean_text(row[4]),
            follow_up_date=clean_text(row[5]),
            reminder_date=clean_text(row[6]),
            completed=bool(row[7]),
            completed_at=clean_text(row[8]),
            notes=clean_text(row[9]),
        )

    @staticmethod
    def _row_to_document(row) -> ContractDocumentRecord:
        return ContractDocumentRecord(
            id=int(row[0]),
            contract_id=int(row[1]),
            title=str(row[2] or ""),
            document_type=str(row[3] or "other"),
            version_label=clean_text(row[4]),
            created_date=clean_text(row[5]),
            received_date=clean_text(row[6]),
            signed_status=clean_text(row[7]),
            signed_by_all_parties=bool(row[8]),
            active_flag=bool(row[9]),
            supersedes_document_id=int(row[10]) if row[10] is not None else None,
            superseded_by_document_id=int(row[11]) if row[11] is not None else None,
            file_path=clean_text(row[12]),
            filename=clean_text(row[13]),
            storage_mode=clean_text(row[14]),
            checksum_sha256=clean_text(row[16]),
            notes=clean_text(row[17]),
            uploaded_at=clean_text(row[18]),
        )

    def _ensure_storage_columns(self) -> None:
        table_names = {
            str(row[0])
            for row in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            if row and row[0]
        }
        if "ContractDocuments" not in table_names:
            return
        columns = {
            str(row[1])
            for row in self.conn.execute("PRAGMA table_info(ContractDocuments)").fetchall()
            if row and row[1]
        }
        additions = (
            ("storage_mode", "TEXT"),
            ("file_blob", "BLOB"),
        )
        with self.conn:
            for column_name, column_sql in additions:
                if column_name not in columns:
                    self.conn.execute(
                        f"ALTER TABLE ContractDocuments ADD COLUMN {column_name} {column_sql}"
                    )

    def _fetch_document_row(self, document_id: int):
        return self.conn.execute(
            """
            SELECT
                id,
                contract_id,
                title,
                document_type,
                version_label,
                created_date,
                received_date,
                signed_status,
                signed_by_all_parties,
                active_flag,
                supersedes_document_id,
                superseded_by_document_id,
                file_path,
                filename,
                storage_mode,
                file_blob,
                checksum_sha256,
                notes,
                uploaded_at
            FROM ContractDocuments
            WHERE id=?
            """,
            (int(document_id),),
        ).fetchone()

    def _document_blob_bytes(self, document_id: int) -> bytes | None:
        row = self.conn.execute(
            "SELECT file_blob FROM ContractDocuments WHERE id=?",
            (int(document_id),),
        ).fetchone()
        if not row or row[0] is None:
            return None
        return bytes_from_blob(row[0])

    def fetch_document_bytes(self, document_id: int) -> tuple[bytes, str]:
        row = self._fetch_document_row(document_id)
        if row is None:
            raise FileNotFoundError(document_id)
        storage_mode = infer_storage_mode(
            explicit_mode=row[14],
            stored_path=row[12],
            blob_value=row[15],
        )
        filename = clean_text(row[13]) or Path(str(row[12] or "")).name or "contract-document"
        mime_type = mimetypes.guess_type(filename)[0] or ""
        if storage_mode == STORAGE_MODE_DATABASE:
            blob_data = self._document_blob_bytes(document_id)
            if blob_data is None:
                raise FileNotFoundError(filename or document_id)
            return blob_data, mime_type
        resolved = self.resolve_document_path(row[12])
        if resolved is None or not resolved.exists():
            raise FileNotFoundError(row[12] or filename or document_id)
        return resolved.read_bytes(), mime_type


    def _hash_file(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _is_managed_document_path(self, stored_path: str | None) -> bool:
        return self.document_store.is_managed(stored_path)

    def resolve_document_path(self, stored_path: str | None) -> Path | None:
        return self.document_store.resolve(stored_path)

    def _write_document_file(self, source_path: str | Path) -> tuple[str, str, str]:
        source = Path(source_path)
        if not source.exists():
            raise FileNotFoundError(source)
        if self.documents_root is None or self.data_root is None:
            raise ValueError("Contract document storage is not configured.")
        data = source.read_bytes()
        filename = coalesce_filename(source.name, default_stem="contract-document")
        rel_path = self.document_store.write_bytes(
            data,
            filename=filename,
            subdir=None,
        )
        destination = self.data_root / rel_path
        return rel_path, filename, self._hash_file(destination)

    def _write_document_blob(self, source_path: str | Path) -> tuple[bytes, str, str]:
        source = Path(source_path)
        if not source.exists():
            raise FileNotFoundError(source)
        data = source.read_bytes()
        filename = coalesce_filename(source.name, default_stem="contract-document")
        return data, filename, sha256_digest(data)

    def _build_document_storage_payload(
        self,
        *,
        source_path: str | Path | None = None,
        stored_path: str | None = None,
        filename: str | None = None,
        checksum_sha256: str | None = None,
        storage_mode: str | None = None,
        existing_file_blob: object | None = None,
    ) -> tuple[str | None, bytes | None, str, str | None, str | None]:
        clean_mode = normalize_storage_mode(storage_mode, default=STORAGE_MODE_MANAGED_FILE)
        if source_path:
            source = Path(source_path)
            if clean_mode == STORAGE_MODE_DATABASE:
                blob_data, resolved_filename, resolved_checksum = self._write_document_blob(source)
                resolved_mime = mimetypes.guess_type(resolved_filename)[0] or ""
                return None, blob_data, resolved_filename, resolved_checksum, resolved_mime
            rel_path, resolved_filename, resolved_checksum = self._write_document_file(source)
            resolved_mime = mimetypes.guess_type(resolved_filename)[0] or ""
            return rel_path, None, resolved_filename, resolved_checksum, resolved_mime

        clean_stored_path = clean_text(stored_path)
        clean_filename = coalesce_filename(
            filename,
            stored_path=clean_stored_path,
            default_stem="contract-document",
        )
        clean_checksum = clean_text(checksum_sha256)
        if clean_mode == STORAGE_MODE_DATABASE:
            blob_data = bytes_from_blob(existing_file_blob)
            if existing_file_blob is None:
                raise FileNotFoundError("No document blob is stored for this record.")
            resolved_checksum = clean_checksum or sha256_digest(blob_data)
            resolved_mime = mimetypes.guess_type(clean_filename)[0] or ""
            return None, blob_data, clean_filename, resolved_checksum, resolved_mime

        if not clean_stored_path:
            raise FileNotFoundError("No managed document path is stored for this record.")
        resolved_path = self.resolve_document_path(clean_stored_path)
        if resolved_path is None or not resolved_path.exists():
            raise FileNotFoundError(clean_stored_path)
        resolved_checksum = clean_checksum or self._hash_file(resolved_path)
        resolved_mime = mimetypes.guess_type(clean_filename)[0] or ""
        return clean_stored_path, None, clean_filename, resolved_checksum, resolved_mime

    def _delete_document_if_unreferenced(
        self,
        stored_path: str | None,
        *,
        cursor: sqlite3.Cursor,
    ) -> None:
        clean_path = clean_text(stored_path)
        if not clean_path:
            return
        row = cursor.execute(
            "SELECT 1 FROM ContractDocuments WHERE file_path=? LIMIT 1",
            (clean_path,),
        ).fetchone()
        if row:
            return
        if not self._is_managed_document_path(clean_path):
            return
        resolved = self.resolve_document_path(clean_path)
        if resolved is None:
            return
        try:
            resolved.unlink(missing_ok=True)
        except Exception:
            pass

    def _document_current_storage_mode(self, document_id: int) -> str | None:
        row = self.conn.execute(
            "SELECT storage_mode, file_path, file_blob FROM ContractDocuments WHERE id=?",
            (int(document_id),),
        ).fetchone()
        if not row:
            return None
        return infer_storage_mode(
            explicit_mode=row[0],
            stored_path=row[1],
            blob_value=row[2],
        )

    def convert_document_storage_mode(
        self, document_id: int, target_mode: str, *, cursor: sqlite3.Cursor | None = None
    ) -> ContractDocumentRecord:
        clean_mode = normalize_storage_mode(target_mode)
        cur = cursor or self.conn.cursor()
        row = self._fetch_document_row(document_id)
        if row is None:
            raise ValueError(f"Contract document {document_id} not found")
        current_mode = infer_storage_mode(
            explicit_mode=row[14],
            stored_path=row[12],
            blob_value=row[15],
        )
        if current_mode == clean_mode:
            return self._row_to_document(row)

        old_path = clean_text(row[12])
        filename = clean_text(row[13]) or (Path(old_path).name if old_path else "contract-document")
        checksum = clean_text(row[16])

        if clean_mode == STORAGE_MODE_DATABASE:
            if current_mode == STORAGE_MODE_DATABASE:
                return self._row_to_document(row)
            managed_path = clean_text(row[12])
            resolved = self.resolve_document_path(managed_path)
            if resolved is None or not resolved.exists():
                raise FileNotFoundError(managed_path or f"contract document {document_id}")
            data = resolved.read_bytes()
            verified_checksum = sha256_digest(data)
            with self.conn:
                cur.execute(
                    """
                    UPDATE ContractDocuments
                    SET file_path=NULL,
                        storage_mode=?,
                        file_blob=?,
                        filename=?,
                        checksum_sha256=?
                    WHERE id=?
                    """,
                    (
                        clean_mode,
                        sqlite3.Binary(data),
                        filename,
                        verified_checksum,
                        int(document_id),
                    ),
                )
            if managed_path and self._is_managed_document_path(managed_path):
                self._delete_document_if_unreferenced(managed_path, cursor=cur)
            updated = self._fetch_document_row(document_id)
            if updated is None:
                raise RuntimeError(f"Contract document {document_id} disappeared after conversion")
            return self._row_to_document(updated)

        if current_mode == STORAGE_MODE_DATABASE:
            blob_data = bytes_from_blob(row[15])
            if blob_data is None:
                raise FileNotFoundError(f"Contract document {document_id} has no stored blob")
            if self.documents_root is None or self.data_root is None:
                raise ValueError("Contract document storage is not configured.")
            rel_path = self.document_store.write_bytes(
                blob_data,
                filename=filename,
                subdir=None,
            )
            resolved = self.resolve_document_path(rel_path)
            if resolved is None or not resolved.exists() or resolved.read_bytes() != blob_data:
                raise RuntimeError("Managed document conversion verification failed")
            with self.conn:
                cur.execute(
                    """
                    UPDATE ContractDocuments
                    SET file_path=?,
                        storage_mode=?,
                        file_blob=NULL,
                        filename=?,
                        checksum_sha256=?
                    WHERE id=?
                    """,
                    (
                        rel_path,
                        clean_mode,
                        filename,
                        checksum or sha256_digest(blob_data),
                        int(document_id),
                    ),
                )
            updated = self._fetch_document_row(document_id)
            if updated is None:
                raise RuntimeError(f"Contract document {document_id} disappeared after conversion")
            return self._row_to_document(updated)

        if not old_path:
            raise FileNotFoundError(f"Contract document {document_id} has no stored path")
        resolved = self.resolve_document_path(old_path)
        if resolved is None or not resolved.exists():
            raise FileNotFoundError(old_path)
        data = resolved.read_bytes()
        verified_checksum = sha256_digest(data)
        with self.conn:
            cur.execute(
                """
                UPDATE ContractDocuments
                SET storage_mode=?,
                    file_blob=?,
                    checksum_sha256=?
                WHERE id=?
                """,
                (
                    clean_mode,
                    sqlite3.Binary(data),
                    verified_checksum,
                    int(document_id),
                ),
            )
        if old_path and self._is_managed_document_path(old_path):
            self._delete_document_if_unreferenced(old_path, cursor=cur)
        updated = self._fetch_document_row(document_id)
        if updated is None:
            raise RuntimeError(f"Contract document {document_id} disappeared after conversion")
        return self._row_to_document(updated)

    def _resolve_party_id(
        self, item: ContractPartyPayload, *, cursor: sqlite3.Cursor
    ) -> int | None:
        if item.party_id:
            return int(item.party_id)
        if self.party_service is None or not clean_text(item.name):
            return None
        return self.party_service.ensure_party_by_name(str(clean_text(item.name)), cursor=cursor)

    def validate_contract(
        self,
        payload: ContractPayload,
        *,
        contract_id: int | None = None,
    ) -> list[ContractValidationIssue]:
        issues: list[ContractValidationIssue] = []
        if not clean_text(payload.title):
            issues.append(ContractValidationIssue("error", "title", "Contract title is required."))
        if self._clean_status(payload.status) in {"pending_signature", "active"} and not clean_text(
            payload.signature_date
        ):
            issues.append(
                ContractValidationIssue(
                    "warning",
                    "signature_date",
                    "Pending or active contracts should include a signature date.",
                )
            )
        if self._clean_status(payload.status) == "active" and not payload.parties:
            issues.append(
                ContractValidationIssue(
                    "warning",
                    "parties",
                    "Active contracts should be linked to at least one party.",
                )
            )
        start_date = parse_iso_date(payload.start_date)
        end_date = parse_iso_date(payload.end_date)
        if start_date and end_date and start_date > end_date:
            issues.append(
                ContractValidationIssue(
                    "error",
                    "end_date",
                    "Contract end date cannot be earlier than the start date.",
                )
            )
        final_docs = [
            doc
            for doc in payload.documents
            if self._clean_document_type(doc.document_type) == "signed_agreement"
            and doc.active_flag
        ]
        if self._clean_status(payload.status) == "active" and not any(
            doc.signed_by_all_parties for doc in final_docs
        ):
            issues.append(
                ContractValidationIssue(
                    "warning",
                    "documents",
                    "Active contracts should have an active signed-agreement document marked as signed by all parties.",
                )
            )
        if len(final_docs) > 1:
            issues.append(
                ContractValidationIssue(
                    "warning",
                    "documents",
                    "Contract has multiple active signed-agreement document versions.",
                )
            )
        for document in payload.documents:
            if (
                self._clean_document_type(document.document_type) == "amendment"
                and document.supersedes_document_id is None
            ):
                issues.append(
                    ContractValidationIssue(
                        "warning",
                        "documents",
                        f"Amendment document '{document.title or 'Untitled'}' does not declare which version it supersedes.",
                    )
                )
        registry_service = self._code_registry_service()
        for system_key in (
            BUILTIN_CATEGORY_CONTRACT_NUMBER,
            BUILTIN_CATEGORY_LICENSE_NUMBER,
            BUILTIN_CATEGORY_REGISTRY_SHA256_KEY,
        ):
            text_attr, mode_attr, internal_attr, external_attr, label = self._contract_identifier_spec(
                system_key
            )
            internal_id = getattr(payload, internal_attr, None)
            external_id = getattr(payload, external_attr, None)
            clean_value = clean_text(getattr(payload, text_attr, None))
            resolved_mode = self._resolve_identifier_mode(
                mode=getattr(payload, mode_attr, None),
                registry_entry_id=int(internal_id) if internal_id is not None else None,
                external_identifier_id=int(external_id) if external_id is not None else None,
                value=clean_value,
            )
            if internal_id is not None and external_id is not None:
                issues.append(
                    ContractValidationIssue(
                        "error",
                        text_attr,
                        f"{label} cannot carry both an internal registry link and an external identifier link.",
                    )
                )
            if resolved_mode == CATALOG_MODE_INTERNAL and internal_id is None and not clean_value:
                issues.append(
                    ContractValidationIssue(
                        "error",
                        text_attr,
                        f"{label} is set to Internal Registry but no value is selected.",
                    )
                )
            if registry_service is None:
                continue
            if internal_id is not None:
                entry = registry_service.fetch_entry(int(internal_id))
                if entry is None:
                    issues.append(
                        ContractValidationIssue(
                            "error",
                            text_attr,
                            f"{label} entry #{int(internal_id)} was not found.",
                        )
                    )
                elif str(entry.category_system_key or "").strip() != system_key:
                    issues.append(
                        ContractValidationIssue(
                            "error",
                            text_attr,
                            f"{label} entry #{int(internal_id)} belongs to a different registry category.",
                        )
                    )
            if external_id is not None:
                record = registry_service.fetch_external_code_identifier(int(external_id))
                if record is None:
                    issues.append(
                        ContractValidationIssue(
                            "error",
                            text_attr,
                            f"{label} external identifier #{int(external_id)} was not found.",
                        )
                    )
                elif str(record.category_system_key or "").strip() != system_key:
                    issues.append(
                        ContractValidationIssue(
                            "error",
                            text_attr,
                            f"{label} external identifier #{int(external_id)} belongs to a different identifier type.",
                        )
                    )
        return issues

    def create_contract(
        self,
        payload: ContractPayload,
        *,
        cursor: sqlite3.Cursor | None = None,
    ) -> int:
        issues = self.validate_contract(payload)
        errors = [issue.message for issue in issues if issue.severity == "error"]
        if errors:
            raise ValueError("\n".join(errors))
        cur = cursor or self.conn.cursor()
        cur.execute(
            """
            INSERT INTO Contracts (
                title,
                contract_type,
                contract_number,
                license_number,
                registry_sha256_key,
                contract_registry_entry_id,
                license_registry_entry_id,
                registry_sha256_key_entry_id,
                draft_date,
                signature_date,
                effective_date,
                start_date,
                end_date,
                renewal_date,
                notice_deadline,
                option_periods,
                reversion_date,
                termination_date,
                status,
                supersedes_contract_id,
                superseded_by_contract_id,
                summary,
                notes,
                profile_name
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(clean_text(payload.title) or ""),
                clean_text(payload.contract_type),
                None,
                None,
                None,
                None,
                None,
                None,
                clean_text(payload.draft_date),
                clean_text(payload.signature_date),
                clean_text(payload.effective_date),
                clean_text(payload.start_date),
                clean_text(payload.end_date),
                clean_text(payload.renewal_date),
                clean_text(payload.notice_deadline),
                clean_text(payload.option_periods),
                clean_text(payload.reversion_date),
                clean_text(payload.termination_date),
                self._clean_status(payload.status),
                payload.supersedes_contract_id,
                payload.superseded_by_contract_id,
                clean_text(payload.summary),
                clean_text(payload.notes),
                clean_text(payload.profile_name),
            ),
        )
        contract_id = int(cur.lastrowid)
        self._replace_parties(contract_id, payload.parties, cursor=cur)
        self._replace_obligations(contract_id, payload.obligations, cursor=cur)
        self._replace_links(
            contract_id, "ContractWorkLinks", "work_id", payload.work_ids, cursor=cur
        )
        self._replace_links(
            contract_id, "ContractTrackLinks", "track_id", payload.track_ids, cursor=cur
        )
        self._replace_links(
            contract_id, "ContractReleaseLinks", "release_id", payload.release_ids, cursor=cur
        )
        self._replace_documents(contract_id, payload.documents, cursor=cur)
        self._apply_registry_assignments(
            contract_id=contract_id,
            payload=payload,
            cursor=cur,
            created_via="contract.create",
        )
        if cursor is None:
            self.conn.commit()
        return contract_id

    def update_contract(
        self,
        contract_id: int,
        payload: ContractPayload,
        *,
        cursor: sqlite3.Cursor | None = None,
    ) -> None:
        issues = self.validate_contract(payload, contract_id=int(contract_id))
        errors = [issue.message for issue in issues if issue.severity == "error"]
        if errors:
            raise ValueError("\n".join(errors))
        cur = cursor or self.conn.cursor()
        cur.execute(
            """
            UPDATE Contracts
            SET title=?,
                contract_type=?,
                contract_number=NULL,
                license_number=NULL,
                registry_sha256_key=NULL,
                contract_registry_entry_id=NULL,
                license_registry_entry_id=NULL,
                registry_sha256_key_entry_id=NULL,
                draft_date=?,
                signature_date=?,
                effective_date=?,
                start_date=?,
                end_date=?,
                renewal_date=?,
                notice_deadline=?,
                option_periods=?,
                reversion_date=?,
                termination_date=?,
                status=?,
                supersedes_contract_id=?,
                superseded_by_contract_id=?,
                summary=?,
                notes=?,
                profile_name=?,
                updated_at=datetime('now')
            WHERE id=?
            """,
            (
                str(clean_text(payload.title) or ""),
                clean_text(payload.contract_type),
                clean_text(payload.draft_date),
                clean_text(payload.signature_date),
                clean_text(payload.effective_date),
                clean_text(payload.start_date),
                clean_text(payload.end_date),
                clean_text(payload.renewal_date),
                clean_text(payload.notice_deadline),
                clean_text(payload.option_periods),
                clean_text(payload.reversion_date),
                clean_text(payload.termination_date),
                self._clean_status(payload.status),
                payload.supersedes_contract_id,
                payload.superseded_by_contract_id,
                clean_text(payload.summary),
                clean_text(payload.notes),
                clean_text(payload.profile_name),
                int(contract_id),
            ),
        )
        self._replace_parties(int(contract_id), payload.parties, cursor=cur)
        self._replace_obligations(int(contract_id), payload.obligations, cursor=cur)
        self._replace_links(
            int(contract_id), "ContractWorkLinks", "work_id", payload.work_ids, cursor=cur
        )
        self._replace_links(
            int(contract_id), "ContractTrackLinks", "track_id", payload.track_ids, cursor=cur
        )
        self._replace_links(
            int(contract_id), "ContractReleaseLinks", "release_id", payload.release_ids, cursor=cur
        )
        self._replace_documents(int(contract_id), payload.documents, cursor=cur)
        self._apply_registry_assignments(
            contract_id=int(contract_id),
            payload=payload,
            cursor=cur,
            created_via="contract.update",
        )
        if cursor is None:
            self.conn.commit()

    def _replace_parties(
        self,
        contract_id: int,
        parties: list[ContractPartyPayload],
        *,
        cursor: sqlite3.Cursor,
    ) -> None:
        cursor.execute("DELETE FROM ContractParties WHERE contract_id=?", (int(contract_id),))
        for item in parties:
            party_id = self._resolve_party_id(item, cursor=cursor)
            if not party_id:
                continue
            cursor.execute(
                """
                INSERT OR IGNORE INTO ContractParties(
                    contract_id,
                    party_id,
                    role_label,
                    is_primary,
                    notes
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    int(contract_id),
                    int(party_id),
                    str(clean_text(item.role_label) or "counterparty"),
                    1 if item.is_primary else 0,
                    clean_text(item.notes),
                ),
            )

    def _replace_obligations(
        self,
        contract_id: int,
        obligations: list[ContractObligationPayload],
        *,
        cursor: sqlite3.Cursor,
    ) -> None:
        cursor.execute("DELETE FROM ContractObligations WHERE contract_id=?", (int(contract_id),))
        for item in obligations:
            title = clean_text(item.title)
            if not title:
                continue
            cursor.execute(
                """
                INSERT INTO ContractObligations(
                    contract_id,
                    obligation_type,
                    title,
                    due_date,
                    follow_up_date,
                    reminder_date,
                    completed,
                    completed_at,
                    notes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(contract_id),
                    self._clean_obligation_type(item.obligation_type),
                    title,
                    clean_text(item.due_date),
                    clean_text(item.follow_up_date),
                    clean_text(item.reminder_date),
                    1 if item.completed else 0,
                    clean_text(item.completed_at),
                    clean_text(item.notes),
                ),
            )

    def _replace_links(
        self,
        contract_id: int,
        table_name: str,
        column_name: str,
        ids: list[int],
        *,
        cursor: sqlite3.Cursor,
    ) -> None:
        cursor.execute(f"DELETE FROM {table_name} WHERE contract_id=?", (int(contract_id),))
        seen: set[int] = set()
        for raw_id in ids:
            try:
                item_id = int(raw_id)
            except Exception:
                continue
            if item_id <= 0 or item_id in seen:
                continue
            seen.add(item_id)
            cursor.execute(
                f"INSERT OR IGNORE INTO {table_name}(contract_id, {column_name}) VALUES (?, ?)",
                (int(contract_id), item_id),
            )

    def _replace_documents(
        self,
        contract_id: int,
        documents: list[ContractDocumentPayload],
        *,
        cursor: sqlite3.Cursor,
    ) -> None:
        existing_rows = cursor.execute(
            "SELECT id, file_path, storage_mode, file_blob, filename, checksum_sha256 FROM ContractDocuments WHERE contract_id=?",
            (int(contract_id),),
        ).fetchall()
        existing_by_id = {
            int(row[0]): {
                "file_path": clean_text(row[1]),
                "storage_mode": clean_text(row[2]),
                "file_blob": row[3],
                "filename": clean_text(row[4]),
                "checksum_sha256": clean_text(row[5]),
            }
            for row in existing_rows
        }
        seen_ids: set[int] = set()
        for item in documents:
            title = clean_text(item.title)
            if not title:
                continue
            current = existing_by_id.get(int(item.document_id)) if item.document_id else None
            requested_mode = normalize_storage_mode(item.storage_mode, default=None)
            current_mode = infer_storage_mode(
                explicit_mode=current["storage_mode"] if current else None,
                stored_path=current["file_path"] if current else None,
                blob_value=current["file_blob"] if current else None,
            )
            desired_mode = requested_mode or current_mode or STORAGE_MODE_MANAGED_FILE
            stored_path = clean_text(item.stored_path) if item.stored_path else None
            filename = clean_text(item.filename)
            checksum = clean_text(item.checksum_sha256)
            file_blob = None
            if clean_text(item.source_path):
                stored_path, file_blob, filename, checksum, _ = (
                    self._build_document_storage_payload(
                        source_path=item.source_path,
                        storage_mode=desired_mode,
                    )
                )
            elif current is not None:
                stored_path = stored_path or current["file_path"]
                filename = filename or current["filename"]
                checksum = checksum or current["checksum_sha256"]
                if desired_mode == STORAGE_MODE_DATABASE and current_mode != STORAGE_MODE_DATABASE:
                    source_path = None
                    if current_mode == STORAGE_MODE_MANAGED_FILE:
                        resolved = self.resolve_document_path(current["file_path"])
                        if resolved is None or not resolved.exists():
                            raise FileNotFoundError(current["file_path"])
                        source_path = resolved
                    payload = self._build_document_storage_payload(
                        source_path=source_path,
                        stored_path=current["file_path"],
                        filename=filename,
                        checksum_sha256=checksum,
                        storage_mode=STORAGE_MODE_DATABASE,
                        existing_file_blob=current["file_blob"],
                    )
                    stored_path, file_blob, filename, checksum, _ = payload
                elif (
                    desired_mode == STORAGE_MODE_MANAGED_FILE
                    and current_mode == STORAGE_MODE_DATABASE
                ):
                    blob_data = bytes_from_blob(current["file_blob"])
                    if not blob_data:
                        raise FileNotFoundError("No document blob is stored for this record.")
                    if self.documents_root is None or self.data_root is None:
                        raise ValueError("Contract document storage is not configured.")
                    filename = filename or current["filename"]
                    stored_path = self.document_store.write_bytes(
                        blob_data,
                        filename=filename or "contract-document",
                        subdir=None,
                    )
                    checksum = checksum or sha256_digest(blob_data)
                    file_blob = None
                else:
                    file_blob = current["file_blob"]
            else:
                if not stored_path:
                    desired_mode = None
                    filename = filename or None
                    checksum = checksum or None
                elif not filename:
                    filename = Path(stored_path).name

            if item.document_id and int(item.document_id) in existing_by_id:
                document_id = int(item.document_id)
                old = existing_by_id.get(document_id) or {}
                old_path = old.get("file_path")
                cursor.execute(
                    """
                    UPDATE ContractDocuments
                    SET title=?,
                        document_type=?,
                        version_label=?,
                        created_date=?,
                        received_date=?,
                        signed_status=?,
                        signed_by_all_parties=?,
                        active_flag=?,
                        supersedes_document_id=?,
                        superseded_by_document_id=?,
                        file_path=?,
                        filename=?,
                        storage_mode=?,
                        file_blob=?,
                        checksum_sha256=?,
                        notes=?
                    WHERE id=?
                    """,
                    (
                        title,
                        self._clean_document_type(item.document_type),
                        clean_text(item.version_label),
                        clean_text(item.created_date),
                        clean_text(item.received_date),
                        clean_text(item.signed_status),
                        1 if item.signed_by_all_parties else 0,
                        1 if item.active_flag else 0,
                        item.supersedes_document_id,
                        item.superseded_by_document_id,
                        stored_path,
                        filename,
                        desired_mode,
                        sqlite3.Binary(file_blob) if file_blob is not None else None,
                        checksum,
                        clean_text(item.notes),
                        document_id,
                    ),
                )
                seen_ids.add(document_id)
                if (
                    old_path
                    and old_path != stored_path
                    and self._is_managed_document_path(old_path)
                ):
                    self._delete_document_if_unreferenced(old_path, cursor=cursor)
                continue
            cursor.execute(
                """
                INSERT INTO ContractDocuments(
                    contract_id,
                    title,
                    document_type,
                    version_label,
                    created_date,
                    received_date,
                    signed_status,
                    signed_by_all_parties,
                    active_flag,
                    supersedes_document_id,
                    superseded_by_document_id,
                    file_path,
                    filename,
                    storage_mode,
                    file_blob,
                    checksum_sha256,
                    notes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(contract_id),
                    title,
                    self._clean_document_type(item.document_type),
                    clean_text(item.version_label),
                    clean_text(item.created_date),
                    clean_text(item.received_date),
                    clean_text(item.signed_status),
                    1 if item.signed_by_all_parties else 0,
                    1 if item.active_flag else 0,
                    item.supersedes_document_id,
                    item.superseded_by_document_id,
                    stored_path,
                    filename,
                    desired_mode,
                    sqlite3.Binary(file_blob) if file_blob is not None else None,
                    checksum,
                    clean_text(item.notes),
                ),
            )
            seen_ids.add(int(cursor.lastrowid))
        stale_ids = set(existing_by_id) - seen_ids
        for document_id in stale_ids:
            stale_path = existing_by_id.get(document_id, {}).get("file_path")
            cursor.execute("DELETE FROM ContractDocuments WHERE id=?", (int(document_id),))
            self._delete_document_if_unreferenced(stale_path, cursor=cursor)

    def fetch_contract(self, contract_id: int) -> ContractRecord | None:
        contract_external_sql = self._contract_identifier_select_sql(
            BUILTIN_CATEGORY_CONTRACT_NUMBER, "c"
        )
        contract_mode_sql = self._contract_identifier_mode_sql(
            BUILTIN_CATEGORY_CONTRACT_NUMBER, "c"
        )
        license_external_sql = self._contract_identifier_select_sql(
            BUILTIN_CATEGORY_LICENSE_NUMBER, "c"
        )
        license_mode_sql = self._contract_identifier_mode_sql(
            BUILTIN_CATEGORY_LICENSE_NUMBER, "c"
        )
        key_external_sql = self._contract_identifier_select_sql(
            BUILTIN_CATEGORY_REGISTRY_SHA256_KEY, "c"
        )
        key_mode_sql = self._contract_identifier_mode_sql(
            BUILTIN_CATEGORY_REGISTRY_SHA256_KEY, "c"
        )
        row = self.conn.execute(
            f"""
            SELECT
                c.id,
                c.title,
                c.contract_type,
                c.contract_number,
                {contract_mode_sql} AS contract_number_mode,
                c.contract_registry_entry_id,
                {contract_external_sql} AS contract_external_code_identifier_id,
                c.license_number,
                {license_mode_sql} AS license_number_mode,
                c.license_registry_entry_id,
                {license_external_sql} AS license_external_code_identifier_id,
                c.registry_sha256_key,
                {key_mode_sql} AS registry_sha256_key_mode,
                c.registry_sha256_key_entry_id,
                {key_external_sql} AS registry_sha256_key_external_code_identifier_id,
                c.draft_date,
                c.signature_date,
                c.effective_date,
                c.start_date,
                c.end_date,
                c.renewal_date,
                c.notice_deadline,
                c.option_periods,
                c.reversion_date,
                c.termination_date,
                c.status,
                c.supersedes_contract_id,
                c.superseded_by_contract_id,
                c.summary,
                c.notes,
                c.profile_name,
                c.created_at,
                c.updated_at,
                COUNT(DISTINCT o.id) AS obligation_count,
                COUNT(DISTINCT d.id) AS document_count
            FROM Contracts c
            LEFT JOIN ContractObligations o ON o.contract_id = c.id
            LEFT JOIN ContractDocuments d ON d.contract_id = c.id
            WHERE c.id=?
            GROUP BY c.id
            """,
            (int(contract_id),),
        ).fetchone()
        return self._row_to_contract(row) if row else None

    def fetch_contract_detail(self, contract_id: int) -> ContractDetail | None:
        contract = self.fetch_contract(int(contract_id))
        if contract is None:
            return None
        parties = self.conn.execute(
            """
            SELECT
                cp.party_id,
                COALESCE(p.display_name, p.legal_name, 'Unknown Party'),
                cp.role_label,
                cp.is_primary,
                cp.notes
            FROM ContractParties cp
            LEFT JOIN Parties p ON p.id = cp.party_id
            WHERE cp.contract_id=?
            ORDER BY cp.is_primary DESC, p.legal_name, cp.role_label
            """,
            (int(contract_id),),
        ).fetchall()
        obligations = self.conn.execute(
            """
            SELECT
                id,
                contract_id,
                obligation_type,
                title,
                due_date,
                follow_up_date,
                reminder_date,
                completed,
                completed_at,
                notes
            FROM ContractObligations
            WHERE contract_id=?
            ORDER BY COALESCE(due_date, follow_up_date, reminder_date, ''), id
            """,
            (int(contract_id),),
        ).fetchall()
        documents = self.conn.execute(
            """
            SELECT
                id,
                contract_id,
                title,
                document_type,
                version_label,
                created_date,
                received_date,
                signed_status,
                signed_by_all_parties,
                active_flag,
                supersedes_document_id,
                superseded_by_document_id,
                file_path,
                filename,
                storage_mode,
                NULL AS file_blob,
                checksum_sha256,
                notes,
                uploaded_at
            FROM ContractDocuments
            WHERE contract_id=?
            ORDER BY active_flag DESC, uploaded_at DESC, id DESC
            """,
            (int(contract_id),),
        ).fetchall()
        work_rows = self.conn.execute(
            "SELECT work_id FROM ContractWorkLinks WHERE contract_id=? ORDER BY work_id",
            (int(contract_id),),
        ).fetchall()
        track_rows = self.conn.execute(
            "SELECT track_id FROM ContractTrackLinks WHERE contract_id=? ORDER BY track_id",
            (int(contract_id),),
        ).fetchall()
        release_rows = self.conn.execute(
            "SELECT release_id FROM ContractReleaseLinks WHERE contract_id=? ORDER BY release_id",
            (int(contract_id),),
        ).fetchall()
        return ContractDetail(
            contract=contract,
            parties=[self._row_to_party(row) for row in parties],
            obligations=[self._row_to_obligation(row) for row in obligations],
            documents=[self._row_to_document(row) for row in documents],
            work_ids=[int(row[0]) for row in work_rows],
            track_ids=[int(row[0]) for row in track_rows],
            release_ids=[int(row[0]) for row in release_rows],
        )

    def list_contracts(
        self,
        *,
        search_text: str | None = None,
        status: str | None = None,
    ) -> list[ContractRecord]:
        clauses: list[str] = []
        params: list[object] = []
        clean_search = clean_text(search_text)
        if clean_search:
            like = f"%{clean_search}%"
            clauses.append(
                """
                (
                    c.title LIKE ?
                    OR COALESCE(c.contract_type, '') LIKE ?
                    OR COALESCE(c.summary, '') LIKE ?
                    OR EXISTS (
                        SELECT 1
                        FROM ContractParties cp
                        JOIN Parties p ON p.id = cp.party_id
                        WHERE cp.contract_id = c.id
                          AND (
                              p.legal_name LIKE ?
                              OR COALESCE(p.display_name, '') LIKE ?
                          )
                    )
                )
                """
            )
            params.extend([like, like, like, like, like])
        clean_status = clean_text(status)
        if clean_status:
            clauses.append("c.status=?")
            params.append(self._clean_status(clean_status))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        contract_external_sql = self._contract_identifier_select_sql(
            BUILTIN_CATEGORY_CONTRACT_NUMBER, "c"
        )
        contract_mode_sql = self._contract_identifier_mode_sql(
            BUILTIN_CATEGORY_CONTRACT_NUMBER, "c"
        )
        license_external_sql = self._contract_identifier_select_sql(
            BUILTIN_CATEGORY_LICENSE_NUMBER, "c"
        )
        license_mode_sql = self._contract_identifier_mode_sql(
            BUILTIN_CATEGORY_LICENSE_NUMBER, "c"
        )
        key_external_sql = self._contract_identifier_select_sql(
            BUILTIN_CATEGORY_REGISTRY_SHA256_KEY, "c"
        )
        key_mode_sql = self._contract_identifier_mode_sql(
            BUILTIN_CATEGORY_REGISTRY_SHA256_KEY, "c"
        )
        rows = self.conn.execute(
            f"""
            SELECT
                c.id,
                c.title,
                c.contract_type,
                c.contract_number,
                {contract_mode_sql} AS contract_number_mode,
                c.contract_registry_entry_id,
                {contract_external_sql} AS contract_external_code_identifier_id,
                c.license_number,
                {license_mode_sql} AS license_number_mode,
                c.license_registry_entry_id,
                {license_external_sql} AS license_external_code_identifier_id,
                c.registry_sha256_key,
                {key_mode_sql} AS registry_sha256_key_mode,
                c.registry_sha256_key_entry_id,
                {key_external_sql} AS registry_sha256_key_external_code_identifier_id,
                c.draft_date,
                c.signature_date,
                c.effective_date,
                c.start_date,
                c.end_date,
                c.renewal_date,
                c.notice_deadline,
                c.option_periods,
                c.reversion_date,
                c.termination_date,
                c.status,
                c.supersedes_contract_id,
                c.superseded_by_contract_id,
                c.summary,
                c.notes,
                c.profile_name,
                c.created_at,
                c.updated_at,
                COUNT(DISTINCT o.id) AS obligation_count,
                COUNT(DISTINCT d.id) AS document_count
            FROM Contracts c
            LEFT JOIN ContractObligations o ON o.contract_id = c.id
            LEFT JOIN ContractDocuments d ON d.contract_id = c.id
            {where}
            GROUP BY c.id
            ORDER BY COALESCE(c.notice_deadline, c.end_date, c.start_date, c.created_at), c.title, c.id
            """,
            params,
        ).fetchall()
        return [self._row_to_contract(row) for row in rows]

    def delete_contract(self, contract_id: int) -> None:
        detail = self.fetch_contract_detail(int(contract_id))
        with self.conn:
            self.conn.execute("DELETE FROM Contracts WHERE id=?", (int(contract_id),))
            if detail is not None:
                for document in detail.documents:
                    if self._is_managed_document_path(document.file_path):
                        self._delete_document_if_unreferenced(
                            document.file_path, cursor=self.conn.cursor()
                        )

    def upcoming_deadlines(self, *, within_days: int = 60) -> list[ContractDeadline]:
        today = date.today()
        cutoff = today + timedelta(days=max(0, int(within_days)))
        deadlines: list[ContractDeadline] = []
        rows = self.conn.execute(
            """
            SELECT
                id,
                title,
                notice_deadline,
                renewal_date,
                end_date,
                reversion_date,
                termination_date
            FROM Contracts
            WHERE status IN ('active', 'pending_signature', 'draft')
            ORDER BY id
            """
        ).fetchall()
        for row in rows:
            contract_id = int(row[0])
            title = str(row[1] or "")
            for field_name, raw_value in (
                ("notice_deadline", row[2]),
                ("renewal_date", row[3]),
                ("end_date", row[4]),
                ("reversion_date", row[5]),
                ("termination_date", row[6]),
            ):
                due = parse_iso_date(raw_value)
                if due is None or due < today or due > cutoff:
                    continue
                deadlines.append(
                    ContractDeadline(
                        contract_id=contract_id,
                        title=title,
                        date_field=field_name,
                        due_date=due.isoformat(),
                    )
                )
        obligation_rows = self.conn.execute(
            """
            SELECT
                c.id,
                c.title,
                o.due_date
            FROM ContractObligations o
            JOIN Contracts c ON c.id = o.contract_id
            WHERE o.completed = 0
              AND o.due_date IS NOT NULL
              AND trim(o.due_date) != ''
            ORDER BY o.due_date, o.id
            """
        ).fetchall()
        for contract_id, title, due_date in obligation_rows:
            due = parse_iso_date(due_date)
            if due is None or due < today or due > cutoff:
                continue
            deadlines.append(
                ContractDeadline(
                    contract_id=int(contract_id),
                    title=str(title or ""),
                    date_field="obligation_due_date",
                    due_date=due.isoformat(),
                )
            )
        deadlines.sort(key=lambda item: (item.due_date, item.title.casefold(), item.contract_id))
        return deadlines

    def export_deadlines_csv(self, path: str | Path, *, within_days: int = 60) -> None:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        rows = self.upcoming_deadlines(within_days=within_days)
        lines = ["contract_id,title,date_field,due_date"]
        for row in rows:
            safe_title = row.title.replace('"', '""')
            lines.append(f'{row.contract_id},"{safe_title}",{row.date_field},{row.due_date}')
        output.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def export_rows(self) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for contract in self.list_contracts():
            detail = self.fetch_contract_detail(contract.id)
            if detail is None:
                continue
            payload = contract.to_dict()
            payload["parties"] = [asdict(item) for item in detail.parties]
            payload["obligations"] = [asdict(item) for item in detail.obligations]
            payload["documents"] = [asdict(item) for item in detail.documents]
            payload["work_ids"] = list(detail.work_ids)
            payload["track_ids"] = list(detail.track_ids)
            payload["release_ids"] = list(detail.release_ids)
            rows.append(payload)
        return rows

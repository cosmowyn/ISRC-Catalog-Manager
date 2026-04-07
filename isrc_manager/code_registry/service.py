"""Central registry service for app-managed internal codes and external catalog IDs."""

from __future__ import annotations

import hashlib
import re
import secrets
import sqlite3
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime

from .models import (
    BUILTIN_CATEGORY_CATALOG_NUMBER,
    BUILTIN_CATEGORY_CONTRACT_NUMBER,
    BUILTIN_CATEGORY_LICENSE_NUMBER,
    BUILTIN_CATEGORY_REGISTRY_SHA256_KEY,
    CATALOG_MODE_EMPTY,
    CATALOG_MODE_EXTERNAL,
    CATALOG_MODE_INTERNAL,
    CLASSIFICATION_CANONICAL_CANDIDATE,
    CLASSIFICATION_EXTERNAL,
    CLASSIFICATION_INTERNAL,
    CLASSIFICATION_MISMATCH,
    ENTRY_KIND_GENERATED,
    ENTRY_KIND_MANUAL_CAPTURE,
    ENTRY_KIND_SHA256_GENERATED,
    GENERATION_STRATEGY_MANUAL,
    GENERATION_STRATEGY_SEQUENTIAL,
    GENERATION_STRATEGY_SHA256,
    SUBJECT_KIND_CATALOG,
    SUBJECT_KIND_CONTRACT,
    SUBJECT_KIND_GENERIC,
    SUBJECT_KIND_KEY,
    SUBJECT_KIND_LICENSE,
    CatalogIdentifierClassification,
    CatalogIdentifierResolution,
    CodeRegistryAssignmentTarget,
    CodeRegistryCategoryPayload,
    CodeRegistryCategoryRecord,
    CodeRegistryChoice,
    CodeRegistryEntryGenerationResult,
    CodeRegistryEntryRecord,
    CodeRegistryUsageLink,
    ExternalCatalogIdentifierRecord,
)

_SEQUENTIAL_REMAINDER_RE = re.compile(r"^(?P<yy>\d{2})(?P<seq>\d{4})$")
_GENERIC_CODE_RE = re.compile(r"^[A-Z][A-Z0-9]{1,24}\d{6}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

_BUILTIN_CATEGORIES = (
    {
        "system_key": BUILTIN_CATEGORY_CATALOG_NUMBER,
        "display_name": "Catalog Number",
        "subject_kind": SUBJECT_KIND_CATALOG,
        "generation_strategy": GENERATION_STRATEGY_SEQUENTIAL,
        "prefix": "",
        "sort_order": 10,
    },
    {
        "system_key": BUILTIN_CATEGORY_CONTRACT_NUMBER,
        "display_name": "Contract Number",
        "subject_kind": SUBJECT_KIND_CONTRACT,
        "generation_strategy": GENERATION_STRATEGY_SEQUENTIAL,
        "prefix": "",
        "sort_order": 20,
    },
    {
        "system_key": BUILTIN_CATEGORY_LICENSE_NUMBER,
        "display_name": "License Number",
        "subject_kind": SUBJECT_KIND_LICENSE,
        "generation_strategy": GENERATION_STRATEGY_SEQUENTIAL,
        "prefix": "",
        "sort_order": 30,
    },
    {
        "system_key": BUILTIN_CATEGORY_REGISTRY_SHA256_KEY,
        "display_name": "Registry SHA-256 Key",
        "subject_kind": SUBJECT_KIND_KEY,
        "generation_strategy": GENERATION_STRATEGY_SHA256,
        "prefix": "",
        "sort_order": 40,
    },
)

_OWNER_TABLES = {
    "track": ("Tracks", "track_title"),
    "release": ("Releases", "title"),
    "contract": ("Contracts", "title"),
}


class CodeRegistryService:
    """Owns internal registry categories, immutable entries, and external catalog IDs."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.ensure_default_categories()

    def _registry_schema_ready(self, *, cursor: sqlite3.Cursor | None = None) -> bool:
        cur = cursor or self.conn.cursor()
        required_tables = (
            "CodeRegistryCategories",
            "CodeRegistrySequences",
            "CodeRegistryEntries",
            "ExternalCatalogIdentifiers",
        )
        rows = cur.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type='table'
              AND name IN (?, ?, ?, ?)
            """,
            required_tables,
        ).fetchall()
        present = {str(row[0]) for row in rows}
        return all(table_name in present for table_name in required_tables)

    @staticmethod
    def _clean_text(value: object | None) -> str | None:
        text = str(value or "").strip()
        return text or None

    @classmethod
    def normalize_prefix(cls, value: str | None) -> str | None:
        clean = "".join(ch for ch in str(value or "").upper().strip() if ch.isalnum())
        return clean or None

    @classmethod
    def normalize_internal_value(cls, value: str | None) -> str:
        text = "".join(ch for ch in str(value or "").upper().strip() if ch.isalnum())
        return text

    @classmethod
    def normalize_external_value(cls, value: str | None) -> str:
        return " ".join(str(value or "").split()).casefold()

    def ensure_default_categories(self, *, cursor: sqlite3.Cursor | None = None) -> None:
        cur = cursor or self.conn.cursor()
        if not self._registry_schema_ready(cursor=cur):
            return
        for payload in _BUILTIN_CATEGORIES:
            cur.execute(
                """
                INSERT INTO CodeRegistryCategories(
                    system_key,
                    display_name,
                    subject_kind,
                    generation_strategy,
                    prefix,
                    normalized_prefix,
                    active_flag,
                    sort_order,
                    is_system
                )
                VALUES (?, ?, ?, ?, ?, ?, 1, ?, 1)
                ON CONFLICT(system_key) DO UPDATE SET
                    display_name=excluded.display_name,
                    subject_kind=excluded.subject_kind,
                    generation_strategy=excluded.generation_strategy,
                    sort_order=excluded.sort_order,
                    is_system=1,
                    updated_at=datetime('now')
                """,
                (
                    payload["system_key"],
                    payload["display_name"],
                    payload["subject_kind"],
                    payload["generation_strategy"],
                    payload["prefix"],
                    self.normalize_prefix(str(payload["prefix"] or "")),
                    int(payload["sort_order"]),
                ),
            )
        if cursor is None:
            self.conn.commit()

    @contextmanager
    def _immediate_transaction(self):
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield self.conn.cursor()
        except Exception:
            self.conn.rollback()
            raise
        else:
            self.conn.commit()

    def _row_to_category(self, row) -> CodeRegistryCategoryRecord:
        return CodeRegistryCategoryRecord(
            id=int(row[0]),
            system_key=self._clean_text(row[1]),
            display_name=str(row[2] or ""),
            subject_kind=str(row[3] or SUBJECT_KIND_GENERIC),
            generation_strategy=str(row[4] or GENERATION_STRATEGY_MANUAL),
            prefix=self._clean_text(row[5]),
            normalized_prefix=self._clean_text(row[6]),
            active_flag=bool(row[7]),
            sort_order=int(row[8] or 0),
            is_system=bool(row[9]),
            created_at=self._clean_text(row[10]),
            updated_at=self._clean_text(row[11]),
        )

    def _row_to_entry(self, row) -> CodeRegistryEntryRecord:
        return CodeRegistryEntryRecord(
            id=int(row[0]),
            category_id=int(row[1]),
            category_system_key=self._clean_text(row[2]),
            category_display_name=str(row[3] or ""),
            subject_kind=str(row[4] or SUBJECT_KIND_GENERIC),
            generation_strategy=str(row[5] or GENERATION_STRATEGY_MANUAL),
            value=str(row[6] or ""),
            normalized_value=str(row[7] or ""),
            entry_kind=str(row[8] or ENTRY_KIND_MANUAL_CAPTURE),
            prefix_snapshot=self._clean_text(row[9]),
            sequence_year=int(row[10]) if row[10] is not None else None,
            sequence_number=int(row[11]) if row[11] is not None else None,
            immutable_flag=bool(row[12]),
            created_at=self._clean_text(row[13]),
            created_via=self._clean_text(row[14]),
            notes=self._clean_text(row[15]),
            usage_count=int(row[16] or 0) if len(row) > 16 else 0,
        )

    def _row_to_external(self, row) -> ExternalCatalogIdentifierRecord:
        return ExternalCatalogIdentifierRecord(
            id=int(row[0]),
            subject_kind=str(row[1] or ""),
            subject_id=int(row[2] or 0),
            value=str(row[3] or ""),
            normalized_value=str(row[4] or ""),
            provenance_kind=str(row[5] or "manual"),
            classification_status=str(row[6] or CLASSIFICATION_EXTERNAL),
            classification_reason=self._clean_text(row[7]),
            source_label=self._clean_text(row[8]),
            created_at=self._clean_text(row[9]),
            updated_at=self._clean_text(row[10]),
            usage_count=int(row[11] or 0) if len(row) > 11 else 0,
            linked_flag=bool(row[12]) if len(row) > 12 else False,
        )

    @staticmethod
    def _external_usage_counts_cte() -> str:
        return """
            WITH usage_counts AS (
                SELECT external_catalog_identifier_id AS external_id, COUNT(*) AS usage_count
                FROM Tracks
                WHERE external_catalog_identifier_id IS NOT NULL
                GROUP BY external_catalog_identifier_id
                UNION ALL
                SELECT external_catalog_identifier_id AS external_id, COUNT(*) AS usage_count
                FROM Releases
                WHERE external_catalog_identifier_id IS NOT NULL
                GROUP BY external_catalog_identifier_id
            ),
            usage_totals AS (
                SELECT external_id, SUM(usage_count) AS usage_count
                FROM usage_counts
                GROUP BY external_id
            )
        """

    def list_categories(
        self,
        *,
        subject_kind: str | None = None,
        active_only: bool = False,
    ) -> list[CodeRegistryCategoryRecord]:
        params: list[object] = []
        where: list[str] = []
        if subject_kind:
            where.append("subject_kind=?")
            params.append(str(subject_kind))
        if active_only:
            where.append("active_flag=1")
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        rows = self.conn.execute(
            f"""
            SELECT
                id,
                system_key,
                display_name,
                subject_kind,
                generation_strategy,
                prefix,
                normalized_prefix,
                active_flag,
                sort_order,
                is_system,
                created_at,
                updated_at
            FROM CodeRegistryCategories
            {where_sql}
            ORDER BY sort_order, lower(display_name), id
            """,
            params,
        ).fetchall()
        return [self._row_to_category(row) for row in rows]

    def fetch_category(self, category_id: int) -> CodeRegistryCategoryRecord | None:
        row = self.conn.execute(
            """
            SELECT
                id,
                system_key,
                display_name,
                subject_kind,
                generation_strategy,
                prefix,
                normalized_prefix,
                active_flag,
                sort_order,
                is_system,
                created_at,
                updated_at
            FROM CodeRegistryCategories
            WHERE id=?
            """,
            (int(category_id),),
        ).fetchone()
        return self._row_to_category(row) if row else None

    def fetch_category_by_system_key(self, system_key: str) -> CodeRegistryCategoryRecord | None:
        row = self.conn.execute(
            """
            SELECT
                id,
                system_key,
                display_name,
                subject_kind,
                generation_strategy,
                prefix,
                normalized_prefix,
                active_flag,
                sort_order,
                is_system,
                created_at,
                updated_at
            FROM CodeRegistryCategories
            WHERE system_key=?
            """,
            (str(system_key or "").strip(),),
        ).fetchone()
        return self._row_to_category(row) if row else None

    def _validate_prefix_uniqueness(
        self,
        *,
        normalized_prefix: str | None,
        generation_strategy: str,
        category_id: int | None = None,
        cursor: sqlite3.Cursor | None = None,
    ) -> None:
        if generation_strategy != GENERATION_STRATEGY_SEQUENTIAL or not normalized_prefix:
            return
        cur = cursor or self.conn.cursor()
        params: list[object] = [normalized_prefix, normalized_prefix]
        sql = """
            SELECT id, display_name, normalized_prefix
            FROM CodeRegistryCategories
            WHERE generation_strategy=?
              AND active_flag=1
              AND normalized_prefix IS NOT NULL
              AND normalized_prefix != ''
              AND (? LIKE normalized_prefix || '%' OR normalized_prefix LIKE ? || '%')
        """
        params.insert(0, GENERATION_STRATEGY_SEQUENTIAL)
        if category_id is not None:
            sql += " AND id != ?"
            params.append(int(category_id))
        row = cur.execute(sql, params).fetchone()
        if row is not None:
            raise ValueError(
                f"Prefix '{normalized_prefix}' conflicts with existing category "
                f"'{str(row[1] or '').strip() or row[2]}'."
            )

    def create_category(
        self,
        payload: CodeRegistryCategoryPayload,
        *,
        cursor: sqlite3.Cursor | None = None,
    ) -> int:
        normalized_prefix = self.normalize_prefix(payload.prefix)
        self._validate_prefix_uniqueness(
            normalized_prefix=normalized_prefix,
            generation_strategy=str(payload.generation_strategy or GENERATION_STRATEGY_MANUAL),
            cursor=cursor,
        )
        cur = cursor or self.conn.cursor()
        cur.execute(
            """
            INSERT INTO CodeRegistryCategories(
                system_key,
                display_name,
                subject_kind,
                generation_strategy,
                prefix,
                normalized_prefix,
                active_flag,
                sort_order,
                is_system
            )
            VALUES (NULL, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                str(payload.display_name or "").strip(),
                str(payload.subject_kind or SUBJECT_KIND_GENERIC),
                str(payload.generation_strategy or GENERATION_STRATEGY_MANUAL),
                self._clean_text(payload.prefix),
                normalized_prefix,
                1 if payload.active_flag else 0,
                int(payload.sort_order or 0),
            ),
        )
        category_id = int(cur.lastrowid)
        if cursor is None:
            self.conn.commit()
        return category_id

    def update_category(
        self,
        category_id: int,
        *,
        display_name: str | None = None,
        prefix: str | None | object = ...,
        active_flag: bool | None = None,
        sort_order: int | None = None,
    ) -> CodeRegistryCategoryRecord:
        current = self.fetch_category(int(category_id))
        if current is None:
            raise ValueError(f"Code registry category {int(category_id)} not found.")
        clean_display_name = current.display_name
        if display_name is not None:
            requested_display_name = str(display_name or "").strip() or current.display_name
            if current.is_system and requested_display_name != current.display_name:
                raise ValueError("Built-in category labels are fixed.")
            clean_display_name = requested_display_name
        clean_prefix = current.prefix
        normalized_prefix = current.normalized_prefix
        if prefix is not ...:
            clean_prefix = self._clean_text(prefix)
            normalized_prefix = self.normalize_prefix(clean_prefix)
        next_active_flag = current.active_flag if active_flag is None else bool(active_flag)
        next_sort_order = current.sort_order if sort_order is None else int(sort_order)
        self._validate_prefix_uniqueness(
            normalized_prefix=normalized_prefix if next_active_flag else None,
            generation_strategy=current.generation_strategy,
            category_id=current.id,
        )
        with self.conn:
            self.conn.execute(
                """
                UPDATE CodeRegistryCategories
                SET display_name=?,
                    prefix=?,
                    normalized_prefix=?,
                    active_flag=?,
                    sort_order=?,
                    updated_at=datetime('now')
                WHERE id=?
                """,
                (
                    clean_display_name,
                    clean_prefix,
                    normalized_prefix,
                    1 if next_active_flag else 0,
                    next_sort_order,
                    int(category_id),
                ),
            )
        updated = self.fetch_category(int(category_id))
        if updated is None:
            raise RuntimeError(f"Category {int(category_id)} disappeared after update.")
        return updated

    def delete_category(self, category_id: int) -> None:
        current = self.fetch_category(int(category_id))
        if current is None:
            raise ValueError(f"Code registry category {int(category_id)} not found.")
        if current.is_system:
            raise ValueError("Built-in categories cannot be deleted.")
        entry_count = int(
            self.conn.execute(
                "SELECT COUNT(*) FROM CodeRegistryEntries WHERE category_id=?",
                (int(category_id),),
            ).fetchone()[0]
            or 0
        )
        if entry_count:
            raise ValueError(
                f"Cannot delete '{current.display_name}' because it already has immutable registry entries."
            )
        with self.conn:
            self.conn.execute(
                "DELETE FROM CodeRegistryCategories WHERE id=?",
                (int(category_id),),
            )

    def delete_entry(self, entry_id: int) -> None:
        entry = self.fetch_entry(int(entry_id))
        if entry is None:
            raise ValueError(f"Registry entry {int(entry_id)} was not found.")
        if entry.category_system_key != BUILTIN_CATEGORY_REGISTRY_SHA256_KEY:
            raise ValueError("Only unused Registry SHA-256 Keys can be deleted.")
        if self.usage_for_entry(int(entry_id)):
            raise ValueError(
                "Registry SHA-256 Keys can only be deleted when they are not linked to any contract."
            )
        try:
            with self.conn:
                self.conn.execute(
                    "DELETE FROM CodeRegistryEntries WHERE id=?",
                    (int(entry_id),),
                )
        except sqlite3.DatabaseError as exc:
            raise ValueError(
                "Registry SHA-256 Key could not be deleted. It may still be in use."
            ) from exc

    def _category_or_raise(
        self,
        *,
        category_id: int | None = None,
        system_key: str | None = None,
    ) -> CodeRegistryCategoryRecord:
        category = (
            self.fetch_category(int(category_id))
            if category_id is not None
            else self.fetch_category_by_system_key(str(system_key or ""))
        )
        if category is None:
            raise ValueError("Code registry category was not found.")
        if not category.active_flag:
            raise ValueError(f"Code registry category '{category.display_name}' is inactive.")
        return category

    def fetch_entry(self, entry_id: int) -> CodeRegistryEntryRecord | None:
        row = self.conn.execute(
            """
            SELECT
                e.id,
                e.category_id,
                c.system_key,
                c.display_name,
                c.subject_kind,
                c.generation_strategy,
                e.value,
                e.normalized_value,
                e.entry_kind,
                e.prefix_snapshot,
                e.sequence_year,
                e.sequence_number,
                e.immutable_flag,
                e.created_at,
                e.created_via,
                e.notes
            FROM CodeRegistryEntries e
            JOIN CodeRegistryCategories c ON c.id = e.category_id
            WHERE e.id=?
            """,
            (int(entry_id),),
        ).fetchone()
        return self._row_to_entry(row) if row else None

    def fetch_entry_by_value(self, value: str) -> CodeRegistryEntryRecord | None:
        normalized = self.normalize_internal_value(value)
        if not normalized:
            return None
        row = self.conn.execute(
            """
            SELECT
                e.id,
                e.category_id,
                c.system_key,
                c.display_name,
                c.subject_kind,
                c.generation_strategy,
                e.value,
                e.normalized_value,
                e.entry_kind,
                e.prefix_snapshot,
                e.sequence_year,
                e.sequence_number,
                e.immutable_flag,
                e.created_at,
                e.created_via,
                e.notes
            FROM CodeRegistryEntries e
            JOIN CodeRegistryCategories c ON c.id = e.category_id
            WHERE e.normalized_value=?
            """,
            (normalized,),
        ).fetchone()
        return self._row_to_entry(row) if row else None

    def list_entries(
        self,
        *,
        category_id: int | None = None,
        subject_kind: str | None = None,
        search_text: str | None = None,
        include_unused: bool = True,
    ) -> list[CodeRegistryEntryRecord]:
        params: list[object] = []
        where: list[str] = []
        if category_id is not None:
            where.append("e.category_id=?")
            params.append(int(category_id))
        if subject_kind:
            where.append("c.subject_kind=?")
            params.append(str(subject_kind))
        if search_text:
            where.append("(e.value LIKE ? OR c.display_name LIKE ?)")
            needle = f"%{str(search_text).strip()}%"
            params.extend([needle, needle])
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        rows = self.conn.execute(
            f"""
            WITH usage_counts AS (
                SELECT catalog_registry_entry_id AS entry_id, COUNT(*) AS usage_count
                FROM Tracks
                WHERE catalog_registry_entry_id IS NOT NULL
                GROUP BY catalog_registry_entry_id
                UNION ALL
                SELECT catalog_registry_entry_id AS entry_id, COUNT(*) AS usage_count
                FROM Releases
                WHERE catalog_registry_entry_id IS NOT NULL
                GROUP BY catalog_registry_entry_id
                UNION ALL
                SELECT contract_registry_entry_id AS entry_id, COUNT(*) AS usage_count
                FROM Contracts
                WHERE contract_registry_entry_id IS NOT NULL
                GROUP BY contract_registry_entry_id
                UNION ALL
                SELECT license_registry_entry_id AS entry_id, COUNT(*) AS usage_count
                FROM Contracts
                WHERE license_registry_entry_id IS NOT NULL
                GROUP BY license_registry_entry_id
                UNION ALL
                SELECT registry_sha256_key_entry_id AS entry_id, COUNT(*) AS usage_count
                FROM Contracts
                WHERE registry_sha256_key_entry_id IS NOT NULL
                GROUP BY registry_sha256_key_entry_id
            ),
            usage_totals AS (
                SELECT entry_id, SUM(usage_count) AS usage_count
                FROM usage_counts
                GROUP BY entry_id
            )
            SELECT
                e.id,
                e.category_id,
                c.system_key,
                c.display_name,
                c.subject_kind,
                c.generation_strategy,
                e.value,
                e.normalized_value,
                e.entry_kind,
                e.prefix_snapshot,
                e.sequence_year,
                e.sequence_number,
                e.immutable_flag,
                e.created_at,
                e.created_via,
                e.notes,
                COALESCE(u.usage_count, 0) AS usage_count
            FROM CodeRegistryEntries e
            JOIN CodeRegistryCategories c ON c.id = e.category_id
            LEFT JOIN usage_totals u ON u.entry_id = e.id
            {where_sql}
            ORDER BY c.sort_order, COALESCE(e.sequence_year, 0) DESC, COALESCE(e.sequence_number, 0) DESC, lower(e.value), e.id DESC
            """,
            params,
        ).fetchall()
        entries = [self._row_to_entry(row) for row in rows]
        if include_unused:
            return entries
        return [entry for entry in entries if entry.usage_count > 0]

    def list_choices_for_subject(
        self,
        *,
        subject_kind: str,
        category_id: int | None = None,
    ) -> list[CodeRegistryChoice]:
        entries = self.list_entries(category_id=category_id, subject_kind=subject_kind)
        return [
            CodeRegistryChoice(
                entry_id=entry.id,
                category_id=entry.category_id,
                category_label=entry.category_display_name,
                value=entry.value,
                label=(
                    entry.value
                    if subject_kind != SUBJECT_KIND_CATALOG
                    else f"{entry.category_display_name}: {entry.value}"
                ),
            )
            for entry in entries
        ]

    def list_external_catalog_identifiers(
        self,
        *,
        search_text: str | None = None,
    ) -> list[ExternalCatalogIdentifierRecord]:
        params: list[object] = []
        where_sql = ""
        if search_text:
            where_sql = "WHERE value LIKE ? OR source_label LIKE ? OR classification_status LIKE ?"
            needle = f"%{str(search_text).strip()}%"
            params.extend([needle, needle, needle])
        rows = self.conn.execute(
            f"""
            {self._external_usage_counts_cte()}
            SELECT
                e.id,
                e.subject_kind,
                e.subject_id,
                e.value,
                e.normalized_value,
                e.provenance_kind,
                e.classification_status,
                e.classification_reason,
                e.source_label,
                e.created_at,
                e.updated_at,
                COALESCE(u.usage_count, 0) AS usage_count,
                CASE WHEN COALESCE(u.usage_count, 0) > 0 THEN 1 ELSE 0 END AS linked_flag
            FROM ExternalCatalogIdentifiers e
            LEFT JOIN usage_totals u ON u.external_id = e.id
            {where_sql}
            ORDER BY COALESCE(u.usage_count, 0) DESC, e.updated_at DESC, lower(e.value), e.id DESC
            """,
            params,
        ).fetchall()
        return [self._row_to_external(row) for row in rows]

    def external_catalog_suggestions(self, *, limit: int = 250) -> list[str]:
        rows = self.conn.execute(
            """
            SELECT value
            FROM ExternalCatalogIdentifiers
            WHERE value IS NOT NULL AND value != ''
            GROUP BY normalized_value, value
            ORDER BY lower(value), value
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
        return [str(row[0] or "").strip() for row in rows if str(row[0] or "").strip()]

    def classify_catalog_identifier(self, value: str | None) -> CatalogIdentifierClassification:
        clean_value = self._clean_text(value) or ""
        normalized_value = self.normalize_internal_value(clean_value)
        if not clean_value:
            return CatalogIdentifierClassification(
                input_value="",
                normalized_value="",
                classification=CATALOG_MODE_EMPTY,
                reason="blank",
            )
        matching_categories = [
            category
            for category in self.list_categories(
                subject_kind=SUBJECT_KIND_CATALOG,
                active_only=True,
            )
            if category.generation_strategy == GENERATION_STRATEGY_SEQUENTIAL
            and category.normalized_prefix
            and normalized_value.startswith(str(category.normalized_prefix))
        ]
        if not matching_categories:
            classification = (
                CLASSIFICATION_CANONICAL_CANDIDATE
                if _GENERIC_CODE_RE.fullmatch(normalized_value)
                else CLASSIFICATION_EXTERNAL
            )
            return CatalogIdentifierClassification(
                input_value=clean_value,
                normalized_value=normalized_value,
                classification=classification,
                canonical_value=clean_value,
                reason=(
                    "No configured internal catalog prefix matched this value."
                    if classification == CLASSIFICATION_CANONICAL_CANDIDATE
                    else "Value does not match any configured internal catalog prefix."
                ),
            )
        category = matching_categories[0]
        prefix = str(category.normalized_prefix or "")
        remainder = normalized_value[len(prefix) :]
        match = _SEQUENTIAL_REMAINDER_RE.fullmatch(remainder)
        if not match:
            return CatalogIdentifierClassification(
                input_value=clean_value,
                normalized_value=normalized_value,
                classification=CLASSIFICATION_MISMATCH,
                category_id=category.id,
                category_system_key=category.system_key,
                category_display_name=category.display_name,
                matched_prefix=prefix,
                reason="Value uses a known internal prefix but not the canonical <PREFIX><YY><NNNN> format.",
            )
        sequence_year = int(match.group("yy"))
        sequence_number = int(match.group("seq"))
        if sequence_number < 1 or sequence_number > 9999:
            return CatalogIdentifierClassification(
                input_value=clean_value,
                normalized_value=normalized_value,
                classification=CLASSIFICATION_MISMATCH,
                category_id=category.id,
                category_system_key=category.system_key,
                category_display_name=category.display_name,
                matched_prefix=prefix,
                reason="Parsed sequence is outside the supported 0001-9999 range.",
            )
        canonical_value = f"{prefix}{sequence_year:02d}{sequence_number:04d}"
        existing_entry = self.fetch_entry_by_value(canonical_value)
        return CatalogIdentifierClassification(
            input_value=clean_value,
            normalized_value=normalized_value,
            classification=CLASSIFICATION_INTERNAL,
            category_id=category.id,
            category_system_key=category.system_key,
            category_display_name=category.display_name,
            canonical_value=canonical_value,
            matched_prefix=prefix,
            sequence_year=sequence_year,
            sequence_number=sequence_number,
            existing_entry_id=existing_entry.id if existing_entry is not None else None,
            reason="Accepted as an internal catalog identifier.",
        )

    def _upsert_sequence_state(
        self,
        category_id: int,
        sequence_year: int,
        sequence_number: int,
        *,
        cursor: sqlite3.Cursor,
    ) -> None:
        cursor.execute(
            """
            INSERT INTO CodeRegistrySequences(category_id, sequence_year, last_sequence_number)
            VALUES (?, ?, ?)
            ON CONFLICT(category_id, sequence_year) DO UPDATE SET
                last_sequence_number=MAX(last_sequence_number, excluded.last_sequence_number),
                updated_at=datetime('now')
            """,
            (int(category_id), int(sequence_year), int(sequence_number)),
        )

    def _create_sequential_entry(
        self,
        *,
        category: CodeRegistryCategoryRecord,
        canonical_value: str,
        sequence_year: int,
        sequence_number: int,
        entry_kind: str,
        created_via: str | None,
        cursor: sqlite3.Cursor,
    ) -> CodeRegistryEntryRecord:
        existing = self.fetch_entry_by_value(canonical_value)
        if existing is not None:
            self._upsert_sequence_state(
                category.id,
                sequence_year,
                sequence_number,
                cursor=cursor,
            )
            return existing
        cursor.execute(
            """
            INSERT INTO CodeRegistryEntries(
                category_id,
                value,
                normalized_value,
                entry_kind,
                prefix_snapshot,
                sequence_year,
                sequence_number,
                immutable_flag,
                created_via,
                notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, NULL)
            """,
            (
                int(category.id),
                canonical_value,
                self.normalize_internal_value(canonical_value),
                entry_kind,
                category.normalized_prefix,
                int(sequence_year),
                int(sequence_number),
                self._clean_text(created_via),
            ),
        )
        entry_id = int(cursor.lastrowid)
        self._upsert_sequence_state(
            category.id,
            sequence_year,
            sequence_number,
            cursor=cursor,
        )
        entry = self.fetch_entry(entry_id)
        if entry is None:
            raise RuntimeError("New code-registry entry could not be reloaded.")
        return entry

    def create_or_capture_catalog_entry(
        self,
        value: str,
        *,
        created_via: str | None,
        entry_kind: str = ENTRY_KIND_MANUAL_CAPTURE,
        cursor: sqlite3.Cursor | None = None,
    ) -> CodeRegistryEntryRecord:
        classification = self.classify_catalog_identifier(value)
        if classification.classification != CLASSIFICATION_INTERNAL:
            raise ValueError(
                classification.reason or "Catalog value is not a valid internal identifier."
            )
        if classification.existing_entry_id is not None:
            entry = self.fetch_entry(int(classification.existing_entry_id))
            if entry is None:
                raise RuntimeError("Catalog entry disappeared while loading.")
            return entry
        category = self._category_or_raise(category_id=classification.category_id)
        if cursor is not None:
            return self._create_sequential_entry(
                category=category,
                canonical_value=str(classification.canonical_value or ""),
                sequence_year=int(classification.sequence_year or 0),
                sequence_number=int(classification.sequence_number or 0),
                entry_kind=entry_kind,
                created_via=created_via,
                cursor=cursor,
            )
        with self._immediate_transaction() as cur:
            return self._create_sequential_entry(
                category=category,
                canonical_value=str(classification.canonical_value or ""),
                sequence_year=int(classification.sequence_year or 0),
                sequence_number=int(classification.sequence_number or 0),
                entry_kind=entry_kind,
                created_via=created_via,
                cursor=cur,
            )

    def capture_value_for_category(
        self,
        *,
        category_id: int | None = None,
        system_key: str | None = None,
        value: str,
        created_via: str | None = None,
        entry_kind: str = ENTRY_KIND_MANUAL_CAPTURE,
        cursor: sqlite3.Cursor | None = None,
    ) -> CodeRegistryEntryRecord:
        category = self._category_or_raise(category_id=category_id, system_key=system_key)
        clean_value = self._clean_text(value)
        if not clean_value:
            raise ValueError("A value is required.")
        if category.generation_strategy == GENERATION_STRATEGY_SHA256:
            normalized = str(clean_value).strip().lower()
            if not _SHA256_RE.fullmatch(normalized):
                raise ValueError(
                    "Registry SHA-256 keys must be 64 lowercase hexadecimal characters."
                )
            existing = self.fetch_entry_by_value(normalized)
            if existing is not None:
                return existing
            if cursor is not None:
                cursor.execute(
                    """
                    INSERT INTO CodeRegistryEntries(
                        category_id,
                        value,
                        normalized_value,
                        entry_kind,
                        prefix_snapshot,
                        sequence_year,
                        sequence_number,
                        immutable_flag,
                        created_via,
                        notes
                    )
                    VALUES (?, ?, ?, ?, NULL, NULL, NULL, 1, ?, NULL)
                    """,
                    (
                        int(category.id),
                        normalized,
                        normalized,
                        entry_kind,
                        self._clean_text(created_via),
                    ),
                )
                entry = self.fetch_entry(int(cursor.lastrowid))
                if entry is None:
                    raise RuntimeError("New SHA-256 registry key could not be reloaded.")
                return entry
            with self._immediate_transaction() as cur:
                return self.capture_value_for_category(
                    category_id=category.id,
                    value=normalized,
                    created_via=created_via,
                    entry_kind=entry_kind,
                    cursor=cur,
                )
        if category.subject_kind == SUBJECT_KIND_CATALOG:
            classification = self.classify_catalog_identifier(clean_value)
            if (
                classification.classification != CLASSIFICATION_INTERNAL
                or classification.category_id != category.id
            ):
                raise ValueError(
                    classification.reason
                    or f"Value does not match the configured rules for '{category.display_name}'."
                )
            if classification.existing_entry_id is not None:
                existing = self.fetch_entry(int(classification.existing_entry_id))
                if existing is None:
                    raise RuntimeError("Matching catalog entry disappeared.")
                return existing
            if cursor is not None:
                return self._create_sequential_entry(
                    category=category,
                    canonical_value=str(classification.canonical_value or ""),
                    sequence_year=int(classification.sequence_year or 0),
                    sequence_number=int(classification.sequence_number or 0),
                    entry_kind=entry_kind,
                    created_via=created_via,
                    cursor=cursor,
                )
            with self._immediate_transaction() as cur:
                return self.capture_value_for_category(
                    category_id=category.id,
                    value=clean_value,
                    created_via=created_via,
                    entry_kind=entry_kind,
                    cursor=cur,
                )
        prefix = self.normalize_prefix(category.prefix)
        if not prefix:
            raise ValueError(
                f"Set a prefix for '{category.display_name}' before capturing new internal codes."
            )
        normalized = self.normalize_internal_value(clean_value)
        remainder = normalized[len(prefix) :] if normalized.startswith(prefix) else ""
        match = _SEQUENTIAL_REMAINDER_RE.fullmatch(remainder)
        if not match:
            raise ValueError(
                f"Value must use the canonical {prefix}<YY><NNNN> structure for '{category.display_name}'."
            )
        sequence_year = int(match.group("yy"))
        sequence_number = int(match.group("seq"))
        if sequence_number < 1 or sequence_number > 9999:
            raise ValueError("Internal sequence is outside the supported 0001-9999 range.")
        if cursor is not None:
            return self._create_sequential_entry(
                category=category,
                canonical_value=normalized,
                sequence_year=sequence_year,
                sequence_number=sequence_number,
                entry_kind=entry_kind,
                created_via=created_via,
                cursor=cursor,
            )
        with self._immediate_transaction() as cur:
            return self.capture_value_for_category(
                category_id=category.id,
                value=normalized,
                created_via=created_via,
                entry_kind=entry_kind,
                cursor=cur,
            )

    def generate_next_code(
        self,
        *,
        category_id: int | None = None,
        system_key: str | None = None,
        created_via: str | None = "ui.generate",
    ) -> CodeRegistryEntryGenerationResult:
        category = self._category_or_raise(category_id=category_id, system_key=system_key)
        if category.generation_strategy != GENERATION_STRATEGY_SEQUENTIAL:
            raise ValueError(f"'{category.display_name}' does not use sequential generation.")
        prefix = self.normalize_prefix(category.prefix)
        if not prefix:
            raise ValueError(
                f"Set a prefix for '{category.display_name}' before generating values."
            )
        sequence_year = datetime.now().year % 100
        with self._immediate_transaction() as cur:
            last_row = cur.execute(
                """
                SELECT COALESCE(MAX(last_sequence_number), 0)
                FROM CodeRegistrySequences
                WHERE category_id=? AND sequence_year=?
                """,
                (int(category.id), int(sequence_year)),
            ).fetchone()
            existing_row = cur.execute(
                """
                SELECT COALESCE(MAX(sequence_number), 0)
                FROM CodeRegistryEntries
                WHERE category_id=? AND sequence_year=?
                """,
                (int(category.id), int(sequence_year)),
            ).fetchone()
            next_sequence = max(int(last_row[0] or 0), int(existing_row[0] or 0)) + 1
            if next_sequence > 9999:
                raise ValueError(
                    f"No free internal sequence remains for '{category.display_name}' in {sequence_year:02d}."
                )
            value = f"{prefix}{sequence_year:02d}{next_sequence:04d}"
            entry = self._create_sequential_entry(
                category=replace(category, normalized_prefix=prefix),
                canonical_value=value,
                sequence_year=sequence_year,
                sequence_number=next_sequence,
                entry_kind=ENTRY_KIND_GENERATED,
                created_via=created_via,
                cursor=cur,
            )
        return CodeRegistryEntryGenerationResult(entry=entry, category=category)

    def generate_sha256_key(
        self,
        *,
        category_id: int | None = None,
        system_key: str | None = BUILTIN_CATEGORY_REGISTRY_SHA256_KEY,
        created_via: str | None = "ui.generate",
    ) -> CodeRegistryEntryGenerationResult:
        category = self._category_or_raise(category_id=category_id, system_key=system_key)
        if category.generation_strategy != GENERATION_STRATEGY_SHA256:
            raise ValueError(f"'{category.display_name}' does not generate SHA-256 registry keys.")
        with self._immediate_transaction() as cur:
            while True:
                value = hashlib.sha256(secrets.token_bytes(32)).hexdigest()
                existing = self.fetch_entry_by_value(value)
                if existing is not None:
                    continue
                cur.execute(
                    """
                    INSERT INTO CodeRegistryEntries(
                        category_id,
                        value,
                        normalized_value,
                        entry_kind,
                        prefix_snapshot,
                        sequence_year,
                        sequence_number,
                        immutable_flag,
                        created_via,
                        notes
                    )
                    VALUES (?, ?, ?, ?, NULL, NULL, NULL, 1, ?, NULL)
                    """,
                    (
                        int(category.id),
                        value,
                        value,
                        ENTRY_KIND_SHA256_GENERATED,
                        self._clean_text(created_via),
                    ),
                )
                entry = self.fetch_entry(int(cur.lastrowid))
                if entry is None:
                    raise RuntimeError("Generated Registry SHA-256 Key could not be reloaded.")
                return CodeRegistryEntryGenerationResult(entry=entry, category=category)

    def resolve_catalog_input(
        self,
        *,
        mode: str,
        value: str | None,
        registry_entry_id: int | None = None,
        created_via: str | None = None,
    ) -> CatalogIdentifierResolution:
        clean_mode = str(mode or CATALOG_MODE_EMPTY).strip().lower()
        if clean_mode not in {CATALOG_MODE_INTERNAL, CATALOG_MODE_EXTERNAL, CATALOG_MODE_EMPTY}:
            clean_mode = CATALOG_MODE_EMPTY
        if clean_mode == CATALOG_MODE_EMPTY:
            return CatalogIdentifierResolution(mode=CATALOG_MODE_EMPTY)
        if clean_mode == CATALOG_MODE_INTERNAL:
            if registry_entry_id is not None:
                entry = self.fetch_entry(int(registry_entry_id))
                if entry is None:
                    raise ValueError("Selected internal code was not found.")
                return CatalogIdentifierResolution(
                    mode=CATALOG_MODE_INTERNAL,
                    value=entry.value,
                    registry_entry_id=entry.id,
                    category_id=entry.category_id,
                    classification_status=CLASSIFICATION_INTERNAL,
                    classification_reason="Selected existing internal registry value.",
                )
            entry = self.create_or_capture_catalog_entry(
                str(value or ""),
                created_via=created_via,
                entry_kind=ENTRY_KIND_MANUAL_CAPTURE,
            )
            return CatalogIdentifierResolution(
                mode=CATALOG_MODE_INTERNAL,
                value=entry.value,
                registry_entry_id=entry.id,
                category_id=entry.category_id,
                classification_status=CLASSIFICATION_INTERNAL,
                classification_reason="Captured as an internal catalog identifier.",
            )
        clean_value = self._clean_text(value)
        classification = self.classify_catalog_identifier(clean_value)
        if not clean_value:
            return CatalogIdentifierResolution(mode=CATALOG_MODE_EMPTY)
        return CatalogIdentifierResolution(
            mode=CATALOG_MODE_EXTERNAL,
            value=clean_value,
            external_value=clean_value,
            classification_status=classification.classification,
            classification_reason=classification.reason,
        )

    def _upsert_external_catalog_identifier(
        self,
        *,
        subject_kind: str,
        subject_id: int,
        value: str,
        provenance_kind: str,
        classification_status: str,
        classification_reason: str | None,
        source_label: str | None,
        cursor: sqlite3.Cursor,
    ) -> int:
        clean_value = self._clean_text(value)
        if not clean_value:
            raise ValueError("External catalog identifiers require a value.")
        normalized = self.normalize_external_value(clean_value)
        existing = cursor.execute(
            """
            SELECT id
            FROM ExternalCatalogIdentifiers
            WHERE normalized_value=?
            ORDER BY id
            LIMIT 1
            """,
            (normalized,),
        ).fetchone()
        if existing is not None:
            external_id = int(existing[0])
            cursor.execute(
                """
                UPDATE ExternalCatalogIdentifiers
                SET value=?,
                    provenance_kind=?,
                    classification_status=?,
                    classification_reason=?,
                    source_label=?,
                    updated_at=datetime('now')
                WHERE id=?
                """,
                (
                    clean_value,
                    str(provenance_kind or "manual"),
                    str(classification_status or CLASSIFICATION_EXTERNAL),
                    self._clean_text(classification_reason),
                    self._clean_text(source_label),
                    external_id,
                ),
            )
            return external_id
        next_shared_anchor_id = int(
            cursor.execute(
                """
                SELECT COALESCE(MIN(subject_id), 0) - 1
                FROM ExternalCatalogIdentifiers
                WHERE subject_kind='shared'
                """
            ).fetchone()[0]
            or -1
        )
        cursor.execute(
            """
            INSERT INTO ExternalCatalogIdentifiers(
                subject_kind,
                subject_id,
                value,
                normalized_value,
                provenance_kind,
                classification_status,
                classification_reason,
                source_label
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "shared",
                next_shared_anchor_id,
                clean_value,
                normalized,
                str(provenance_kind or "manual"),
                str(classification_status or CLASSIFICATION_EXTERNAL),
                self._clean_text(classification_reason),
                self._clean_text(source_label),
            ),
        )
        return int(cursor.lastrowid)

    def assign_catalog_to_owner(
        self,
        *,
        owner_kind: str,
        owner_id: int,
        resolution: CatalogIdentifierResolution,
        provenance_kind: str = "manual",
        source_label: str | None = None,
        cursor: sqlite3.Cursor | None = None,
    ) -> tuple[int | None, int | None, str | None]:
        clean_owner_kind = str(owner_kind or "").strip().lower()
        table_name = _OWNER_TABLES.get(clean_owner_kind, (None, None))[0]
        if not table_name:
            raise ValueError(f"Unsupported catalog owner kind '{owner_kind}'.")
        cur = cursor or self.conn.cursor()
        if resolution.mode == CATALOG_MODE_EMPTY:
            cur.execute(
                f"""
                UPDATE {table_name}
                SET catalog_registry_entry_id=NULL,
                    external_catalog_identifier_id=NULL,
                    catalog_number=NULL
                WHERE id=?
                """,
                (int(owner_id),),
            )
            if cursor is None:
                self.conn.commit()
            return None, None, None
        if resolution.mode == CATALOG_MODE_INTERNAL:
            entry = self.fetch_entry(int(resolution.registry_entry_id or 0))
            if entry is None:
                raise ValueError("Selected internal catalog value no longer exists.")
            cur.execute(
                f"""
                UPDATE {table_name}
                SET catalog_registry_entry_id=?,
                    external_catalog_identifier_id=NULL,
                    catalog_number=?
                WHERE id=?
                """,
                (entry.id, entry.value, int(owner_id)),
            )
            if cursor is None:
                self.conn.commit()
            return entry.id, None, entry.value
        external_id = self._upsert_external_catalog_identifier(
            subject_kind=clean_owner_kind,
            subject_id=int(owner_id),
            value=str(resolution.external_value or resolution.value or ""),
            provenance_kind=provenance_kind,
            classification_status=str(resolution.classification_status or CLASSIFICATION_EXTERNAL),
            classification_reason=resolution.classification_reason,
            source_label=source_label,
            cursor=cur,
        )
        clean_value = self._clean_text(resolution.external_value or resolution.value)
        cur.execute(
            f"""
            UPDATE {table_name}
            SET catalog_registry_entry_id=NULL,
                external_catalog_identifier_id=?,
                catalog_number=?
            WHERE id=?
            """,
            (external_id, clean_value, int(owner_id)),
        )
        if cursor is None:
            self.conn.commit()
        return None, external_id, clean_value

    def fetch_external_catalog_identifier(
        self, external_id: int
    ) -> ExternalCatalogIdentifierRecord | None:
        row = self.conn.execute(
            """
            WITH usage_counts AS (
                SELECT external_catalog_identifier_id AS external_id, COUNT(*) AS usage_count
                FROM Tracks
                WHERE external_catalog_identifier_id IS NOT NULL
                GROUP BY external_catalog_identifier_id
                UNION ALL
                SELECT external_catalog_identifier_id AS external_id, COUNT(*) AS usage_count
                FROM Releases
                WHERE external_catalog_identifier_id IS NOT NULL
                GROUP BY external_catalog_identifier_id
            ),
            usage_totals AS (
                SELECT external_id, SUM(usage_count) AS usage_count
                FROM usage_counts
                GROUP BY external_id
            )
            SELECT
                e.id,
                e.subject_kind,
                e.subject_id,
                e.value,
                e.normalized_value,
                e.provenance_kind,
                e.classification_status,
                e.classification_reason,
                e.source_label,
                e.created_at,
                e.updated_at,
                COALESCE(u.usage_count, 0) AS usage_count,
                CASE WHEN COALESCE(u.usage_count, 0) > 0 THEN 1 ELSE 0 END AS linked_flag
            FROM ExternalCatalogIdentifiers e
            LEFT JOIN usage_totals u ON u.external_id = e.id
            WHERE e.id=?
            """,
            (int(external_id),),
        ).fetchone()
        return self._row_to_external(row) if row else None

    def promote_external_catalog_identifier(
        self,
        external_id: int,
        *,
        created_via: str | None = "workspace.promote",
    ) -> CodeRegistryEntryRecord:
        record = self.fetch_external_catalog_identifier(int(external_id))
        if record is None:
            raise ValueError(f"External catalog identifier {int(external_id)} was not found.")
        entry = self.create_or_capture_catalog_entry(
            record.value,
            created_via=created_via,
            entry_kind=ENTRY_KIND_MANUAL_CAPTURE,
        )
        usage = self.usage_for_external_identifier(int(external_id))
        with self.conn:
            for link in usage:
                self.assign_catalog_to_owner(
                    owner_kind=link.subject_kind,
                    owner_id=link.subject_id,
                    resolution=CatalogIdentifierResolution(
                        mode=CATALOG_MODE_INTERNAL,
                        value=entry.value,
                        registry_entry_id=entry.id,
                        category_id=entry.category_id,
                        classification_status=CLASSIFICATION_INTERNAL,
                    ),
                    provenance_kind="promoted",
                    source_label=created_via,
                    cursor=self.conn.cursor(),
                )
            self.conn.execute(
                """
                UPDATE ExternalCatalogIdentifiers
                SET classification_status='promoted',
                    classification_reason='Promoted to an internal registry entry.',
                    updated_at=datetime('now')
                WHERE id=?
                """,
                (int(external_id),),
            )
        return entry

    def reclassify_external_catalog_identifiers(self) -> dict[str, int]:
        promoted = 0
        retained = 0
        mismatched = 0
        candidates = 0
        for record in self.list_external_catalog_identifiers():
            classification = self.classify_catalog_identifier(record.value)
            if classification.classification == CLASSIFICATION_INTERNAL:
                self.promote_external_catalog_identifier(
                    record.id, created_via="workspace.reclassify"
                )
                promoted += 1
            elif classification.classification == CLASSIFICATION_MISMATCH:
                mismatched += 1
                with self.conn:
                    self.conn.execute(
                        """
                        UPDATE ExternalCatalogIdentifiers
                        SET classification_status=?,
                            classification_reason=?,
                            updated_at=datetime('now')
                        WHERE id=?
                        """,
                        (
                            CLASSIFICATION_MISMATCH,
                            classification.reason,
                            int(record.id),
                        ),
                    )
            elif classification.classification == CLASSIFICATION_CANONICAL_CANDIDATE:
                candidates += 1
                with self.conn:
                    self.conn.execute(
                        """
                        UPDATE ExternalCatalogIdentifiers
                        SET classification_status=?,
                            classification_reason=?,
                            updated_at=datetime('now')
                        WHERE id=?
                        """,
                        (
                            CLASSIFICATION_CANONICAL_CANDIDATE,
                            classification.reason,
                            int(record.id),
                        ),
                    )
            else:
                retained += 1
                with self.conn:
                    self.conn.execute(
                        """
                        UPDATE ExternalCatalogIdentifiers
                        SET classification_status=?,
                            classification_reason=?,
                            updated_at=datetime('now')
                        WHERE id=?
                        """,
                        (
                            CLASSIFICATION_EXTERNAL,
                            classification.reason,
                            int(record.id),
                        ),
                    )
        return {
            "promoted": promoted,
            "retained_external": retained,
            "mismatched": mismatched,
            "canonical_candidates": candidates,
        }

    def assignment_owner_kinds_for_entry(self, entry_id: int) -> list[str]:
        entry = self.fetch_entry(int(entry_id))
        if entry is None:
            return []
        if entry.category_system_key == BUILTIN_CATEGORY_CATALOG_NUMBER or (
            entry.subject_kind == SUBJECT_KIND_CATALOG
        ):
            return ["track", "release"]
        if entry.category_system_key in {
            BUILTIN_CATEGORY_CONTRACT_NUMBER,
            BUILTIN_CATEGORY_LICENSE_NUMBER,
            BUILTIN_CATEGORY_REGISTRY_SHA256_KEY,
        }:
            return ["contract"]
        return []

    def list_assignment_targets_for_entry(
        self,
        entry_id: int,
        *,
        owner_kind: str | None = None,
        search_text: str | None = None,
        limit: int = 250,
    ) -> list[CodeRegistryAssignmentTarget]:
        allowed_owner_kinds = self.assignment_owner_kinds_for_entry(int(entry_id))
        if not allowed_owner_kinds:
            return []
        clean_owner_kind = str(owner_kind or "").strip().lower()
        owner_kinds = (
            [clean_owner_kind]
            if clean_owner_kind in allowed_owner_kinds
            else list(allowed_owner_kinds)
        )
        clean_search = self._clean_text(search_text)
        targets: list[CodeRegistryAssignmentTarget] = []
        for current_owner_kind in owner_kinds:
            if current_owner_kind == "track":
                params: list[object] = []
                where = ""
                if clean_search:
                    needle = f"%{clean_search}%"
                    where = (
                        "WHERE CAST(t.id AS TEXT) LIKE ?"
                        " OR COALESCE(t.track_title, '') LIKE ?"
                        " OR COALESCE(t.isrc, '') LIKE ?"
                        " OR COALESCE(t.catalog_number, '') LIKE ?"
                    )
                    params.extend([needle, needle, needle, needle])
                rows = self.conn.execute(
                    f"""
                    SELECT t.id, COALESCE(t.track_title, ''), COALESCE(t.isrc, '')
                    FROM Tracks t
                    {where}
                    ORDER BY lower(COALESCE(t.track_title, '')), t.id
                    LIMIT ?
                    """,
                    [*params, int(limit)],
                ).fetchall()
                targets.extend(
                    CodeRegistryAssignmentTarget(
                        owner_kind="track",
                        owner_id=int(row[0]),
                        label=str(row[1] or "").strip() or f"Track #{int(row[0])}",
                        detail=str(row[2] or "").strip() or f"Track #{int(row[0])}",
                    )
                    for row in rows
                )
            elif current_owner_kind == "release":
                params = []
                where = ""
                if clean_search:
                    needle = f"%{clean_search}%"
                    where = (
                        "WHERE CAST(r.id AS TEXT) LIKE ?"
                        " OR COALESCE(r.title, '') LIKE ?"
                        " OR COALESCE(r.primary_artist, '') LIKE ?"
                        " OR COALESCE(r.catalog_number, '') LIKE ?"
                    )
                    params.extend([needle, needle, needle, needle])
                rows = self.conn.execute(
                    f"""
                    SELECT r.id, COALESCE(r.title, ''), COALESCE(r.primary_artist, '')
                    FROM Releases r
                    {where}
                    ORDER BY lower(COALESCE(r.title, '')), r.id
                    LIMIT ?
                    """,
                    [*params, int(limit)],
                ).fetchall()
                targets.extend(
                    CodeRegistryAssignmentTarget(
                        owner_kind="release",
                        owner_id=int(row[0]),
                        label=str(row[1] or "").strip() or f"Release #{int(row[0])}",
                        detail=str(row[2] or "").strip() or f"Release #{int(row[0])}",
                    )
                    for row in rows
                )
            elif current_owner_kind == "contract":
                params = []
                where = ""
                if clean_search:
                    needle = f"%{clean_search}%"
                    where = (
                        "WHERE CAST(c.id AS TEXT) LIKE ?"
                        " OR COALESCE(c.title, '') LIKE ?"
                        " OR COALESCE(c.contract_number, '') LIKE ?"
                        " OR COALESCE(c.license_number, '') LIKE ?"
                    )
                    params.extend([needle, needle, needle, needle])
                rows = self.conn.execute(
                    f"""
                    SELECT c.id, COALESCE(c.title, ''), COALESCE(c.status, '')
                    FROM Contracts c
                    {where}
                    ORDER BY lower(COALESCE(c.title, '')), c.id
                    LIMIT ?
                    """,
                    [*params, int(limit)],
                ).fetchall()
                targets.extend(
                    CodeRegistryAssignmentTarget(
                        owner_kind="contract",
                        owner_id=int(row[0]),
                        label=str(row[1] or "").strip() or f"Contract #{int(row[0])}",
                        detail=str(row[2] or "").strip() or f"Contract #{int(row[0])}",
                    )
                    for row in rows
                )
        return targets

    def assign_entry_to_owner(self, entry_id: int, *, owner_kind: str, owner_id: int) -> None:
        entry = self.fetch_entry(int(entry_id))
        if entry is None:
            raise ValueError(f"Registry entry {int(entry_id)} was not found.")
        clean_owner_kind = str(owner_kind or "").strip().lower()
        allowed_owner_kinds = self.assignment_owner_kinds_for_entry(int(entry_id))
        if clean_owner_kind not in allowed_owner_kinds:
            raise ValueError("This registry value cannot be linked to that owner type.")
        if entry.category_system_key == BUILTIN_CATEGORY_CATALOG_NUMBER or (
            entry.subject_kind == SUBJECT_KIND_CATALOG
        ):
            self.assign_catalog_to_owner(
                owner_kind=clean_owner_kind,
                owner_id=int(owner_id),
                resolution=CatalogIdentifierResolution(
                    mode=CATALOG_MODE_INTERNAL,
                    value=entry.value,
                    registry_entry_id=entry.id,
                    category_id=entry.category_id,
                    classification_status=CLASSIFICATION_INTERNAL,
                    classification_reason="Linked from Code Registry workspace.",
                ),
                provenance_kind="workspace_link",
                source_label="workspace.assign",
            )
            return
        contract_field_map = {
            BUILTIN_CATEGORY_CONTRACT_NUMBER: (
                "contract_registry_entry_id",
                "contract_number",
                "Contract Number",
            ),
            BUILTIN_CATEGORY_LICENSE_NUMBER: (
                "license_registry_entry_id",
                "license_number",
                "License Number",
            ),
            BUILTIN_CATEGORY_REGISTRY_SHA256_KEY: (
                "registry_sha256_key_entry_id",
                "registry_sha256_key",
                "Registry SHA-256 Key",
            ),
        }
        field_config = contract_field_map.get(str(entry.category_system_key or ""))
        if field_config is None or clean_owner_kind != "contract":
            raise ValueError("This registry value does not support direct workspace assignment.")
        entry_field, text_field, field_label = field_config
        try:
            with self.conn:
                self.conn.execute(
                    f"""
                    UPDATE Contracts
                    SET {entry_field}=?,
                        {text_field}=?
                    WHERE id=?
                    """,
                    (int(entry.id), entry.value, int(owner_id)),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError(
                f"{field_label} '{entry.value}' is already linked to another contract."
            ) from exc

    def usage_for_entry(self, entry_id: int) -> list[CodeRegistryUsageLink]:
        rows = self.conn.execute(
            """
            SELECT 'track' AS subject_kind, t.id, COALESCE(t.track_title, ''), 'Catalog Number'
            FROM Tracks t
            WHERE t.catalog_registry_entry_id=?
            UNION ALL
            SELECT 'release' AS subject_kind, r.id, COALESCE(r.title, ''), 'Catalog Number'
            FROM Releases r
            WHERE r.catalog_registry_entry_id=?
            UNION ALL
            SELECT 'contract' AS subject_kind, c.id, COALESCE(c.title, ''), 'Contract Number'
            FROM Contracts c
            WHERE c.contract_registry_entry_id=?
            UNION ALL
            SELECT 'contract' AS subject_kind, c.id, COALESCE(c.title, ''), 'License Number'
            FROM Contracts c
            WHERE c.license_registry_entry_id=?
            UNION ALL
            SELECT 'contract' AS subject_kind, c.id, COALESCE(c.title, ''), 'Registry SHA-256 Key'
            FROM Contracts c
            WHERE c.registry_sha256_key_entry_id=?
            ORDER BY 1, 4, 2
            """,
            (int(entry_id), int(entry_id), int(entry_id), int(entry_id), int(entry_id)),
        ).fetchall()
        return [
            CodeRegistryUsageLink(
                subject_kind=str(row[0] or ""),
                subject_id=int(row[1] or 0),
                label=str(row[2] or "").strip()
                or f"{str(row[0] or '').title()} #{int(row[1] or 0)}",
                field_name=str(row[3] or ""),
            )
            for row in rows
        ]

    def usage_for_external_identifier(self, external_id: int) -> list[CodeRegistryUsageLink]:
        rows = self.conn.execute(
            """
            SELECT 'track' AS subject_kind, t.id, COALESCE(t.track_title, ''), 'External Catalog'
            FROM Tracks t
            WHERE t.external_catalog_identifier_id=?
            UNION ALL
            SELECT 'release' AS subject_kind, r.id, COALESCE(r.title, ''), 'External Catalog'
            FROM Releases r
            WHERE r.external_catalog_identifier_id=?
            ORDER BY 1, 4, 2
            """,
            (int(external_id), int(external_id)),
        ).fetchall()
        return [
            CodeRegistryUsageLink(
                subject_kind=str(row[0] or ""),
                subject_id=int(row[1] or 0),
                label=str(row[2] or "").strip()
                or f"{str(row[0] or '').title()} #{int(row[1] or 0)}",
                field_name=str(row[3] or ""),
            )
            for row in rows
        ]

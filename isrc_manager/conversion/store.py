"""Profile-scoped saved template storage for conversion workflows."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .models import ConversionTemplateProfile, SavedConversionTemplateRecord


class ConversionTemplateStoreService:
    """Stores reusable conversion templates and optional mapping payloads in the profile DB."""

    TABLE_NAME = "ConversionSavedTemplates"

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self._ensure_table()

    def _ensure_table(self) -> None:
        with self.conn:
            self.conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self.TABLE_NAME} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    filename TEXT NOT NULL,
                    format_name TEXT NOT NULL,
                    source_path TEXT,
                    chosen_scope TEXT,
                    source_mode TEXT,
                    mapping_payload TEXT,
                    template_blob BLOB NOT NULL,
                    size_bytes INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )

    def list_saved_templates(self) -> tuple[SavedConversionTemplateRecord, ...]:
        rows = self.conn.execute(
            f"""
            SELECT
                id,
                name,
                filename,
                format_name,
                source_path,
                chosen_scope,
                source_mode,
                mapping_payload,
                size_bytes,
                created_at,
                updated_at
            FROM {self.TABLE_NAME}
            ORDER BY lower(name), id
            """
        ).fetchall()
        return tuple(self._record_from_row(row) for row in rows)

    def load_saved_template(self, template_id: int) -> SavedConversionTemplateRecord:
        row = self.conn.execute(
            f"""
            SELECT
                id,
                name,
                filename,
                format_name,
                source_path,
                chosen_scope,
                source_mode,
                mapping_payload,
                size_bytes,
                created_at,
                updated_at,
                template_blob
            FROM {self.TABLE_NAME}
            WHERE id = ?
            """,
            (int(template_id),),
        ).fetchone()
        if row is None:
            raise ValueError("The saved conversion template no longer exists.")
        return self._record_from_row(row, include_bytes=True)

    def save_template(
        self,
        *,
        name: str,
        template_profile: ConversionTemplateProfile,
        mapping_payload: str = "",
        source_mode: str = "",
    ) -> SavedConversionTemplateRecord:
        clean_name = str(name or "").strip()
        if not clean_name:
            raise ValueError("Enter a profile template name first.")
        template_bytes = self._template_bytes_for_profile(template_profile)
        filename = str(template_profile.template_path.name or "").strip() or "conversion-template"
        format_name = str(template_profile.format_name or "").strip().lower() or "unknown"
        source_path = self._source_path_for_profile(template_profile)
        chosen_scope = str(template_profile.chosen_scope or "").strip()
        mapping_text = str(mapping_payload or "")
        with self.conn:
            self.conn.execute(
                f"""
                INSERT INTO {self.TABLE_NAME} (
                    name,
                    filename,
                    format_name,
                    source_path,
                    chosen_scope,
                    source_mode,
                    mapping_payload,
                    template_blob,
                    size_bytes,
                    created_at,
                    updated_at
                )
                VALUES (
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    COALESCE(
                        (SELECT created_at FROM {self.TABLE_NAME} WHERE name = ?),
                        datetime('now')
                    ),
                    datetime('now')
                )
                ON CONFLICT(name) DO UPDATE SET
                    filename = excluded.filename,
                    format_name = excluded.format_name,
                    source_path = excluded.source_path,
                    chosen_scope = excluded.chosen_scope,
                    source_mode = excluded.source_mode,
                    mapping_payload = excluded.mapping_payload,
                    template_blob = excluded.template_blob,
                    size_bytes = excluded.size_bytes,
                    updated_at = datetime('now')
                """,
                (
                    clean_name,
                    filename,
                    format_name,
                    source_path,
                    chosen_scope,
                    str(source_mode or "").strip(),
                    mapping_text,
                    sqlite3.Binary(template_bytes),
                    len(template_bytes),
                    clean_name,
                ),
            )
        row = self.conn.execute(
            f"""
            SELECT
                id,
                name,
                filename,
                format_name,
                source_path,
                chosen_scope,
                source_mode,
                mapping_payload,
                size_bytes,
                created_at,
                updated_at
            FROM {self.TABLE_NAME}
            WHERE name = ?
            """,
            (clean_name,),
        ).fetchone()
        if row is None:
            raise RuntimeError("Failed to store the conversion template in the profile database.")
        return self._record_from_row(row)

    @staticmethod
    def _record_from_row(
        row,
        *,
        include_bytes: bool = False,
    ) -> SavedConversionTemplateRecord:
        return SavedConversionTemplateRecord(
            id=int(row[0]),
            name=str(row[1] or "").strip(),
            filename=str(row[2] or "").strip(),
            format_name=str(row[3] or "").strip(),
            source_path=str(row[4] or "").strip(),
            chosen_scope=str(row[5] or "").strip(),
            source_mode=str(row[6] or "").strip(),
            mapping_payload=str(row[7] or ""),
            size_bytes=int(row[8] or 0),
            created_at=str(row[9] or "").strip() or None,
            updated_at=str(row[10] or "").strip() or None,
            template_bytes=bytes(row[11]) if include_bytes and row[11] is not None else None,
        )

    @staticmethod
    def _source_path_for_profile(profile: ConversionTemplateProfile) -> str:
        source_path = str(profile.adapter_state.get("source_path") or "").strip()
        if source_path:
            return source_path
        if profile.template_bytes is not None:
            return ""
        return str(Path(profile.template_path))

    @staticmethod
    def _template_bytes_for_profile(profile: ConversionTemplateProfile) -> bytes:
        if profile.template_bytes is not None:
            return bytes(profile.template_bytes)
        template_path = Path(profile.template_path)
        if not template_path.exists():
            raise ValueError("The selected template file is no longer available on disk.")
        return template_path.read_bytes()

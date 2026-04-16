"""Custom field definition and value services."""

from __future__ import annotations

import json
import mimetypes
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from isrc_manager.blob_icons import blob_icon_spec_from_storage, blob_icon_spec_to_storage
from isrc_manager.domain.standard_fields import promoted_field_spec_by_label_lower
from isrc_manager.file_storage import (
    STORAGE_MODE_DATABASE,
    STORAGE_MODE_MANAGED_FILE,
    ManagedFileStorage,
    bytes_from_blob,
    coalesce_filename,
    infer_storage_mode,
    normalize_storage_mode,
)
from isrc_manager.media.blob_files import (
    _is_valid_audio_path,
    _is_valid_image_path,
    _read_blob_from_path,
)


@dataclass(slots=True)
class LegacyPromotedFieldRepairCandidate:
    field_def_id: int
    field_name: str
    custom_field_type: str
    default_field_type: str
    target_column: str
    non_empty_value_count: int
    blank_target_count: int
    matching_target_count: int
    conflicting_track_ids: tuple[int, ...]

    @property
    def eligible(self) -> bool:
        return not self.conflicting_track_ids


@dataclass(slots=True)
class LegacyPromotedFieldRepairResult:
    repaired_field_names: tuple[str, ...]
    skipped_field_names: tuple[str, ...]
    merged_value_count: int
    removed_value_count: int
    removed_field_count: int


class CustomFieldDefinitionService:
    """Centralizes writes to custom field definitions and option sets."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def _table_columns(self, table: str) -> set[str]:
        return {
            str(row[1])
            for row in self.conn.execute(f"PRAGMA table_info({table})").fetchall()
            if row and row[1]
        }

    def _has_blob_icon_payload_column(self) -> bool:
        return "blob_icon_payload" in self._table_columns("CustomFieldDefs")

    def list_active_fields(self) -> list[dict]:
        blob_icon_sql = (
            "blob_icon_payload"
            if self._has_blob_icon_payload_column()
            else "NULL AS blob_icon_payload"
        )
        rows = self.conn.execute(
            f"""
            SELECT id, name, field_type, options, {blob_icon_sql}
            FROM CustomFieldDefs
            WHERE active=1
            ORDER BY COALESCE(sort_order, 999999), name
            """
        ).fetchall()
        return [
            {
                "id": row[0],
                "name": row[1],
                "field_type": row[2] or "text",
                "options": row[3],
                "blob_icon_payload": (
                    blob_icon_spec_from_storage(
                        row[4],
                        kind=(
                            "audio"
                            if str(row[2] or "").strip().lower() == "blob_audio"
                            else "image"
                        ),
                        allow_inherit=True,
                    )
                    if (row[2] or "").strip().lower() in {"blob_audio", "blob_image"}
                    else None
                ),
            }
            for row in rows
        ]

    def sync_fields(self, existing_fields: list[dict], new_fields: list[dict]) -> None:
        keep_ids = {field["id"] for field in new_fields if field["id"] is not None}
        supports_blob_icon_payload = self._has_blob_icon_payload_column()
        with self.conn:
            for old in existing_fields:
                if old["id"] not in keep_ids:
                    self.conn.execute("DELETE FROM CustomFieldDefs WHERE id=?", (old["id"],))

            order = 0
            for field in new_fields:
                name = field["name"].strip()
                field_type = (field.get("field_type") or "text").strip()
                options = field.get("options")
                blob_icon_payload = None
                if field_type in {"blob_audio", "blob_image"}:
                    blob_icon_payload = blob_icon_spec_to_storage(
                        field.get("blob_icon_payload"),
                        kind="audio" if field_type == "blob_audio" else "image",
                        allow_inherit=True,
                    )
                if field["id"] is None:
                    if supports_blob_icon_payload:
                        self.conn.execute(
                            """
                            INSERT INTO CustomFieldDefs
                                (name, active, sort_order, field_type, options, blob_icon_payload)
                            VALUES (?, 1, ?, ?, ?, ?)
                            """,
                            (name, order, field_type, options, blob_icon_payload),
                        )
                    else:
                        self.conn.execute(
                            """
                            INSERT INTO CustomFieldDefs (name, active, sort_order, field_type, options)
                            VALUES (?, 1, ?, ?, ?)
                            """,
                            (name, order, field_type, options),
                        )
                else:
                    if supports_blob_icon_payload:
                        self.conn.execute(
                            """
                            UPDATE CustomFieldDefs
                            SET name=?, active=1, sort_order=?, field_type=?, options=?, blob_icon_payload=?
                            WHERE id=?
                            """,
                            (name, order, field_type, options, blob_icon_payload, field["id"]),
                        )
                    else:
                        self.conn.execute(
                            """
                            UPDATE CustomFieldDefs
                            SET name=?, active=1, sort_order=?, field_type=?, options=?
                            WHERE id=?
                            """,
                            (name, order, field_type, options, field["id"]),
                        )
                order += 1

    def ensure_fields(
        self, fields: list[dict], *, cursor: sqlite3.Cursor | None = None
    ) -> list[dict]:
        normalized_fields: list[dict] = []
        seen: set[tuple[str, str]] = set()
        for field in fields:
            name = (field.get("name") or "").strip()
            field_type = (field.get("field_type") or "text").strip()
            if not name:
                continue
            key = (name, field_type)
            if key in seen:
                continue
            seen.add(key)
            normalized_fields.append(
                {
                    "name": name,
                    "field_type": field_type,
                    "options": field.get("options"),
                    "blob_icon_payload": field.get("blob_icon_payload"),
                }
            )
        if not normalized_fields:
            return []

        def _apply(cur: sqlite3.Cursor) -> list[dict]:
            supports_blob_icon_payload = self._has_blob_icon_payload_column()
            blob_icon_sql = (
                "blob_icon_payload" if supports_blob_icon_payload else "NULL AS blob_icon_payload"
            )
            rows = cur.execute(
                f"""
                SELECT id, name, active, sort_order, field_type, options, {blob_icon_sql}
                FROM CustomFieldDefs
                ORDER BY COALESCE(sort_order, 999999), id
                """
            ).fetchall()
            by_name = {
                str(row[1]): {
                    "id": int(row[0]),
                    "active": int(row[2] or 0),
                    "sort_order": row[3],
                    "field_type": row[4] or "text",
                    "options": row[5],
                    "blob_icon_payload": row[6],
                }
                for row in rows
                if row[1]
            }
            max_sort = cur.execute(
                "SELECT COALESCE(MAX(sort_order), -1) FROM CustomFieldDefs"
            ).fetchone()
            next_sort_order = int(max_sort[0] if max_sort and max_sort[0] is not None else -1)
            ensured: list[dict] = []

            for field in normalized_fields:
                existing = by_name.get(field["name"])
                field_blob_icon_payload = None
                if field["field_type"] in {"blob_audio", "blob_image"}:
                    field_blob_icon_payload = blob_icon_spec_to_storage(
                        field.get("blob_icon_payload"),
                        kind="audio" if field["field_type"] == "blob_audio" else "image",
                        allow_inherit=True,
                    )
                if existing is None:
                    next_sort_order += 1
                    if supports_blob_icon_payload:
                        cur.execute(
                            """
                            INSERT INTO CustomFieldDefs
                                (name, active, sort_order, field_type, options, blob_icon_payload)
                            VALUES (?, 1, ?, ?, ?, ?)
                            """,
                            (
                                field["name"],
                                next_sort_order,
                                field["field_type"],
                                field.get("options"),
                                field_blob_icon_payload,
                            ),
                        )
                    else:
                        cur.execute(
                            """
                            INSERT INTO CustomFieldDefs (name, active, sort_order, field_type, options)
                            VALUES (?, 1, ?, ?, ?)
                            """,
                            (
                                field["name"],
                                next_sort_order,
                                field["field_type"],
                                field.get("options"),
                            ),
                        )
                    ensured.append(
                        {
                            "id": int(cur.lastrowid),
                            "name": field["name"],
                            "field_type": field["field_type"],
                            "options": field.get("options"),
                            "blob_icon_payload": field.get("blob_icon_payload"),
                            "created": True,
                        }
                    )
                    continue

                existing_type = str(existing["field_type"] or "text")
                if existing_type != field["field_type"]:
                    raise ValueError(
                        f"Custom field '{field['name']}' already exists as type '{existing_type}', "
                        f"not '{field['field_type']}'"
                    )

                merged_options = (
                    existing["options"]
                    if existing["options"] not in (None, "")
                    else field.get("options")
                )
                merged_blob_icon_payload = (
                    existing["blob_icon_payload"]
                    if existing["blob_icon_payload"] not in (None, "")
                    else field_blob_icon_payload
                )
                if (
                    int(existing["active"]) != 1
                    or merged_options != existing["options"]
                    or (
                        supports_blob_icon_payload
                        and merged_blob_icon_payload != existing["blob_icon_payload"]
                    )
                ):
                    if supports_blob_icon_payload:
                        cur.execute(
                            """
                            UPDATE CustomFieldDefs
                            SET active=1, options=?, blob_icon_payload=?
                            WHERE id=?
                            """,
                            (merged_options, merged_blob_icon_payload, int(existing["id"])),
                        )
                    else:
                        cur.execute(
                            """
                            UPDATE CustomFieldDefs
                            SET active=1, options=?
                            WHERE id=?
                            """,
                            (merged_options, int(existing["id"])),
                        )
                ensured.append(
                    {
                        "id": int(existing["id"]),
                        "name": field["name"],
                        "field_type": field["field_type"],
                        "options": merged_options,
                        "blob_icon_payload": (
                            blob_icon_spec_from_storage(
                                merged_blob_icon_payload,
                                kind="audio" if field["field_type"] == "blob_audio" else "image",
                                allow_inherit=True,
                            )
                            if field["field_type"] in {"blob_audio", "blob_image"}
                            else None
                        ),
                        "created": False,
                    }
                )
            return ensured

        if cursor is not None:
            return _apply(cursor)

        with self.conn:
            return _apply(self.conn.cursor())

    def update_dropdown_options(self, field_def_id: int, options: list[str]) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE CustomFieldDefs SET options=? WHERE id=?",
                (json.dumps(options), int(field_def_id)),
            )

    def get_field_type(self, field_def_id: int) -> str:
        row = self.conn.execute(
            "SELECT field_type FROM CustomFieldDefs WHERE id=?",
            (int(field_def_id),),
        ).fetchone()
        return row[0] if row else "text"

    def get_field_name(self, field_def_id: int) -> str:
        row = self.conn.execute(
            "SELECT name FROM CustomFieldDefs WHERE id=?",
            (int(field_def_id),),
        ).fetchone()
        if row and row[0]:
            return str(row[0])
        return "file"


class LegacyPromotedFieldRepairService:
    """Repairs legacy custom fields that now map to promoted default columns."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self._promoted_specs = promoted_field_spec_by_label_lower()

    def inspect_candidates(self) -> list[LegacyPromotedFieldRepairCandidate]:
        if not self._promoted_specs:
            return []
        placeholders = ",".join("?" for _ in self._promoted_specs)
        rows = self.conn.execute(
            f"""
            SELECT id, name, field_type
            FROM CustomFieldDefs
            WHERE lower(name) IN ({placeholders})
            ORDER BY lower(name), id
            """,
            tuple(self._promoted_specs.keys()),
        ).fetchall()
        candidates: list[LegacyPromotedFieldRepairCandidate] = []
        for field_id, field_name, field_type in rows:
            spec = self._promoted_specs.get(str(field_name or "").strip().lower())
            if spec is None or not spec.value_column:
                continue
            value_rows = self.conn.execute(
                """
                SELECT track_id, value
                FROM CustomFieldValues
                WHERE field_def_id=?
                ORDER BY track_id
                """,
                (int(field_id),),
            ).fetchall()
            non_empty_value_count = 0
            blank_target_count = 0
            matching_target_count = 0
            conflicting_track_ids: list[int] = []
            for track_id, value in value_rows:
                text = str(value or "").strip()
                if not text:
                    continue
                non_empty_value_count += 1
                row = self.conn.execute(
                    f"SELECT {spec.value_column} FROM Tracks WHERE id=?",
                    (int(track_id),),
                ).fetchone()
                current_text = str(row[0] or "").strip() if row else ""
                if not current_text:
                    blank_target_count += 1
                elif current_text == text:
                    matching_target_count += 1
                else:
                    conflicting_track_ids.append(int(track_id))
            candidates.append(
                LegacyPromotedFieldRepairCandidate(
                    field_def_id=int(field_id),
                    field_name=str(field_name or ""),
                    custom_field_type=str(field_type or "text"),
                    default_field_type=str(spec.field_type or "text"),
                    target_column=str(spec.value_column),
                    non_empty_value_count=non_empty_value_count,
                    blank_target_count=blank_target_count,
                    matching_target_count=matching_target_count,
                    conflicting_track_ids=tuple(conflicting_track_ids),
                )
            )
        return candidates

    def repair_candidates(self) -> LegacyPromotedFieldRepairResult:
        candidates = self.inspect_candidates()
        repaired_field_names: list[str] = []
        skipped_field_names: list[str] = []
        merged_value_count = 0
        removed_value_count = 0
        removed_field_count = 0

        with self.conn:
            for candidate in candidates:
                if not candidate.eligible:
                    skipped_field_names.append(candidate.field_name)
                    continue
                rows = self.conn.execute(
                    """
                    SELECT track_id, value
                    FROM CustomFieldValues
                    WHERE field_def_id=?
                    ORDER BY track_id
                    """,
                    (candidate.field_def_id,),
                ).fetchall()
                for track_id, value in rows:
                    text = str(value or "").strip()
                    if not text:
                        continue
                    current = self.conn.execute(
                        f"SELECT {candidate.target_column} FROM Tracks WHERE id=?",
                        (int(track_id),),
                    ).fetchone()
                    current_text = str(current[0] or "").strip() if current else ""
                    if not current_text:
                        self.conn.execute(
                            f"UPDATE Tracks SET {candidate.target_column}=? WHERE id=?",
                            (text, int(track_id)),
                        )
                        merged_value_count += 1
                deleted_rows = self.conn.execute(
                    "DELETE FROM CustomFieldValues WHERE field_def_id=?",
                    (candidate.field_def_id,),
                ).rowcount
                self.conn.execute(
                    "DELETE FROM CustomFieldDefs WHERE id=?",
                    (candidate.field_def_id,),
                )
                repaired_field_names.append(candidate.field_name)
                removed_value_count += max(0, int(deleted_rows or 0))
                removed_field_count += 1

        return LegacyPromotedFieldRepairResult(
            repaired_field_names=tuple(repaired_field_names),
            skipped_field_names=tuple(skipped_field_names),
            merged_value_count=merged_value_count,
            removed_value_count=removed_value_count,
            removed_field_count=removed_field_count,
        )


class CustomFieldValueService:
    """Centralizes custom field value and blob persistence."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        definitions: CustomFieldDefinitionService,
        data_root: str | Path | None = None,
    ):
        self.conn = conn
        self.definitions = definitions
        self.file_store = ManagedFileStorage(
            data_root=data_root, relative_root="custom_field_media"
        )
        self._ensure_storage_columns()

    def _ensure_storage_columns(self) -> None:
        table_names = {
            str(row[0])
            for row in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            if row and row[0]
        }
        if "CustomFieldValues" not in table_names:
            return
        columns = {
            str(row[1])
            for row in self.conn.execute("PRAGMA table_info(CustomFieldValues)").fetchall()
            if row and row[1]
        }
        additions = (
            ("blob_value", "BLOB"),
            ("managed_file_path", "TEXT"),
            ("storage_mode", "TEXT"),
            ("filename", "TEXT"),
            ("mime_type", "TEXT"),
            ("size_bytes", "INTEGER NOT NULL DEFAULT 0"),
        )
        for column_name, column_sql in additions:
            if column_name not in columns:
                with self.conn:
                    self.conn.execute(
                        f"ALTER TABLE CustomFieldValues ADD COLUMN {column_name} {column_sql}"
                    )
        self._normalize_text_field_attachment_state()

    def _normalize_text_field_attachment_state(self) -> None:
        rows = self.conn.execute(
            """
            SELECT DISTINCT
                cfv.track_id,
                cfv.field_def_id,
                cfv.managed_file_path
            FROM CustomFieldValues cfv
            JOIN CustomFieldDefs cfd ON cfd.id = cfv.field_def_id
            WHERE cfd.field_type NOT IN ('blob_image', 'blob_audio')
              AND (
                  cfv.blob_value IS NOT NULL
                  OR COALESCE(trim(cfv.managed_file_path), '') != ''
                  OR COALESCE(trim(cfv.storage_mode), '') != ''
                  OR COALESCE(trim(cfv.filename), '') != ''
                  OR COALESCE(trim(cfv.mime_type), '') != ''
                  OR COALESCE(cfv.size_bytes, 0) != 0
              )
            """
        ).fetchall()
        if not rows:
            return
        stale_paths = {str(row[2] or "").strip() for row in rows if str(row[2] or "").strip()}
        with self.conn:
            self.conn.execute(
                """
                UPDATE CustomFieldValues
                SET blob_value=NULL,
                    managed_file_path='',
                    storage_mode='',
                    filename='',
                    mime_type='',
                    size_bytes=0
                WHERE EXISTS (
                    SELECT 1
                    FROM CustomFieldDefs cfd
                    WHERE cfd.id = CustomFieldValues.field_def_id
                      AND cfd.field_type NOT IN ('blob_image', 'blob_audio')
                )
                  AND (
                      blob_value IS NOT NULL
                      OR COALESCE(trim(managed_file_path), '') != ''
                      OR COALESCE(trim(storage_mode), '') != ''
                      OR COALESCE(trim(filename), '') != ''
                      OR COALESCE(trim(mime_type), '') != ''
                      OR COALESCE(size_bytes, 0) != 0
                  )
                """
            )
            cleanup_cursor = self.conn.cursor()
            for stale_path in stale_paths:
                self._delete_managed_file_if_unreferenced(stale_path, cursor=cleanup_cursor)

    @staticmethod
    def _blob_subdir(field_type: str) -> str:
        return "audio" if field_type == "blob_audio" else "images"

    def _validate_blob_source(self, field_type: str, blob_path: str) -> None:
        if field_type == "blob_image":
            if not _is_valid_image_path(blob_path):
                raise ValueError("Selected file is not a recognized image")
            return
        if not _is_valid_audio_path(blob_path):
            raise ValueError("Selected file is not a recognized audio format")

    def _resolve_managed_path(self, stored_path: str | None) -> Path | None:
        return self.file_store.resolve(stored_path)

    def _delete_managed_file_if_unreferenced(
        self,
        stored_path: str | None,
        *,
        cursor: sqlite3.Cursor,
    ) -> None:
        clean_path = str(stored_path or "").strip()
        if not clean_path or not self.file_store.is_managed(clean_path):
            return
        row = cursor.execute(
            """
            SELECT 1
            FROM CustomFieldValues
            WHERE managed_file_path=?
            LIMIT 1
            """,
            (clean_path,),
        ).fetchone()
        if row:
            return
        resolved = self._resolve_managed_path(clean_path)
        if resolved is None:
            return
        try:
            resolved.unlink(missing_ok=True)
        except Exception:
            pass

    def _fetch_blob_row(self, track_id: int, field_def_id: int):
        return self.conn.execute(
            """
            SELECT
                value,
                blob_value,
                managed_file_path,
                storage_mode,
                filename,
                size_bytes,
                mime_type
            FROM CustomFieldValues
            WHERE track_id=? AND field_def_id=?
            """,
            (int(track_id), int(field_def_id)),
        ).fetchone()

    def save_value(
        self,
        track_id: int,
        field_def_id: int,
        *,
        value=None,
        blob_path: str | None = None,
        storage_mode: str | None = None,
    ) -> None:
        field_type = self.definitions.get_field_type(field_def_id)
        if field_type in ("blob_image", "blob_audio"):
            if blob_path is None:
                return
            self._validate_blob_source(field_type, blob_path)
            clean_mode = normalize_storage_mode(storage_mode, default=STORAGE_MODE_DATABASE)
            source = Path(blob_path)
            mime = mimetypes.guess_type(source.name)[0]
            filename = coalesce_filename(
                source.name, default_stem=self.definitions.get_field_name(field_def_id)
            )
            if clean_mode == STORAGE_MODE_DATABASE:
                blob_data = _read_blob_from_path(blob_path)
                rel_path = None
                sqlite_blob = sqlite3.Binary(blob_data)
            else:
                if self.file_store.data_root is None:
                    raise ValueError("Managed custom-field storage is not configured")
                blob_data = source.read_bytes()
                rel_path = self.file_store.write_bytes(
                    blob_data,
                    filename=filename,
                    subdir=self._blob_subdir(field_type),
                )
                sqlite_blob = None
            size = len(blob_data)
            with self.conn:
                current = self._fetch_blob_row(track_id, field_def_id)
                self.conn.execute(
                    """
                    INSERT INTO CustomFieldValues (
                        track_id,
                        field_def_id,
                        value,
                        blob_value,
                        managed_file_path,
                        storage_mode,
                        filename,
                        mime_type,
                        size_bytes
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(track_id, field_def_id) DO UPDATE SET
                    value=excluded.value,
                    blob_value=excluded.blob_value,
                    managed_file_path=excluded.managed_file_path,
                    storage_mode=excluded.storage_mode,
                    filename=excluded.filename,
                    mime_type=excluded.mime_type,
                    size_bytes=excluded.size_bytes
                    """,
                    (
                        int(track_id),
                        int(field_def_id),
                        None,
                        sqlite_blob,
                        rel_path,
                        clean_mode,
                        filename,
                        mime,
                        size,
                    ),
                )
                if current:
                    stale_path = str(current[2] or "").strip()
                    if stale_path and stale_path != str(rel_path or "").strip():
                        self._delete_managed_file_if_unreferenced(
                            stale_path, cursor=self.conn.cursor()
                        )
            return

        with self.conn:
            self.conn.execute(
                """
                INSERT INTO CustomFieldValues (
                    track_id,
                    field_def_id,
                    value,
                    blob_value,
                    managed_file_path,
                    storage_mode,
                    filename,
                    mime_type,
                    size_bytes
                )
                VALUES (?, ?, ?, NULL, '', '', '', '', 0)
                ON CONFLICT(track_id, field_def_id) DO UPDATE SET
                value=excluded.value,
                blob_value=NULL,
                managed_file_path=excluded.managed_file_path,
                storage_mode=excluded.storage_mode,
                filename=excluded.filename,
                mime_type=excluded.mime_type,
                size_bytes=0
                """,
                (int(track_id), int(field_def_id), value),
            )

    def get_text_value(self, track_id: int, field_def_id: int) -> str:
        row = self.conn.execute(
            "SELECT value FROM CustomFieldValues WHERE track_id=? AND field_def_id=?",
            (int(track_id), int(field_def_id)),
        ).fetchone()
        return row[0] if row and row[0] is not None else ""

    def get_value_meta(
        self,
        track_id: int,
        field_def_id: int,
        *,
        include_storage_details: bool = False,
    ) -> dict:
        row = self._fetch_blob_row(track_id, field_def_id)
        if not row:
            meta = {
                "value": None,
                "has_blob": False,
                "size_bytes": 0,
                "mime_type": None,
            }
            if include_storage_details:
                meta["storage_mode"] = None
                meta["filename"] = None
            return meta
        value, blob_value, managed_file_path, storage_mode, filename, size_bytes, mime_type = row
        effective_mode = infer_storage_mode(
            explicit_mode=storage_mode,
            stored_path=managed_file_path,
            blob_value=blob_value,
        )
        meta = {
            "value": value,
            "has_blob": bool(blob_value is not None or str(managed_file_path or "").strip()),
            "size_bytes": int(size_bytes or 0) if size_bytes is not None else 0,
            "mime_type": mime_type or None,
        }
        if include_storage_details:
            meta["storage_mode"] = effective_mode
            meta["filename"] = filename
        return meta

    def get_value_meta_map(
        self,
        field_def_ids,
        *,
        track_ids=None,
        include_storage_details: bool = False,
    ) -> dict[tuple[int, int], dict]:
        normalized_field_ids: list[int] = []
        seen_field_ids: set[int] = set()
        for raw_field_id in field_def_ids or []:
            try:
                field_id = int(raw_field_id)
            except Exception:
                continue
            if field_id in seen_field_ids:
                continue
            seen_field_ids.add(field_id)
            normalized_field_ids.append(field_id)
        if not normalized_field_ids:
            return {}

        query_parts = [
            """
            SELECT
                track_id,
                field_def_id,
                value,
                blob_value,
                managed_file_path,
                storage_mode,
                filename,
                size_bytes,
                mime_type
            FROM CustomFieldValues
            WHERE field_def_id IN ({field_placeholders})
            """
        ]
        params: list[int] = list(normalized_field_ids)
        normalized_track_ids: list[int] = []
        if track_ids is not None:
            seen_track_ids: set[int] = set()
            for raw_track_id in track_ids:
                try:
                    track_id = int(raw_track_id)
                except Exception:
                    continue
                if track_id in seen_track_ids:
                    continue
                seen_track_ids.add(track_id)
                normalized_track_ids.append(track_id)
            if not normalized_track_ids:
                return {}
            query_parts.append("AND track_id IN ({track_placeholders})")
            params.extend(normalized_track_ids)

        query = "".join(query_parts).format(
            field_placeholders=",".join("?" for _ in normalized_field_ids),
            track_placeholders=",".join("?" for _ in normalized_track_ids),
        )
        rows = self.conn.execute(query, tuple(params)).fetchall()
        result: dict[tuple[int, int], dict] = {}
        for row in rows:
            track_id = int(row[0])
            field_def_id = int(row[1])
            value, blob_value, managed_file_path, storage_mode, filename, size_bytes, mime_type = (
                row[2],
                row[3],
                row[4],
                row[5],
                row[6],
                row[7],
                row[8],
            )
            effective_mode = infer_storage_mode(
                explicit_mode=storage_mode,
                stored_path=managed_file_path,
                blob_value=blob_value,
            )
            meta = {
                "value": value,
                "has_blob": bool(blob_value is not None or str(managed_file_path or "").strip()),
                "size_bytes": int(size_bytes or 0) if size_bytes is not None else 0,
                "mime_type": mime_type or None,
            }
            if include_storage_details:
                meta["storage_mode"] = effective_mode
                meta["filename"] = filename
            result[(track_id, field_def_id)] = meta
        return result

    def has_blob(self, track_id: int, field_def_id: int) -> bool:
        meta = self.get_value_meta(track_id, field_def_id)
        return bool(meta["has_blob"])

    def blob_size(self, track_id: int, field_def_id: int) -> int:
        row = self.conn.execute(
            "SELECT size_bytes FROM CustomFieldValues WHERE track_id=? AND field_def_id=?",
            (int(track_id), int(field_def_id)),
        ).fetchone()
        return int(row[0] or 0) if row else 0

    def fetch_blob(self, track_id: int, field_def_id: int):
        row = self._fetch_blob_row(track_id, field_def_id)
        if not row:
            raise FileNotFoundError("No file stored for this field.")
        _, blob_value, managed_file_path, storage_mode, filename, _, mime_type = row
        effective_mode = infer_storage_mode(
            explicit_mode=storage_mode,
            stored_path=managed_file_path,
            blob_value=blob_value,
        )
        if effective_mode == STORAGE_MODE_MANAGED_FILE:
            resolved = self._resolve_managed_path(managed_file_path)
            if resolved is None or not resolved.exists():
                raise FileNotFoundError(
                    managed_file_path or filename or "managed custom field file"
                )
            return resolved.read_bytes(), mime_type
        if blob_value is None:
            raise FileNotFoundError("No file stored for this field.")
        return bytes_from_blob(blob_value), mime_type

    def convert_storage_mode(
        self,
        track_id: int,
        field_def_id: int,
        target_mode: str,
    ) -> dict:
        clean_mode = normalize_storage_mode(target_mode)
        row = self._fetch_blob_row(track_id, field_def_id)
        if not row:
            raise FileNotFoundError("No file stored for this field.")
        value, blob_value, managed_file_path, storage_mode, filename, size_bytes, mime_type = row
        current_mode = infer_storage_mode(
            explicit_mode=storage_mode,
            stored_path=managed_file_path,
            blob_value=blob_value,
        )
        if current_mode is None:
            raise FileNotFoundError("No file stored for this field.")
        if current_mode == clean_mode:
            return self.get_value_meta(track_id, field_def_id)

        data, resolved_mime = self.fetch_blob(track_id, field_def_id)
        clean_filename = coalesce_filename(
            filename,
            stored_path=managed_file_path,
            default_stem=self.definitions.get_field_name(field_def_id),
        )
        stale_path = str(managed_file_path or "").strip()
        if clean_mode == STORAGE_MODE_DATABASE:
            with self.conn:
                self.conn.execute(
                    """
                    UPDATE CustomFieldValues
                    SET blob_value=?,
                        managed_file_path=NULL,
                        storage_mode=?,
                        filename=?,
                        mime_type=?,
                        size_bytes=?
                    WHERE track_id=? AND field_def_id=?
                    """,
                    (
                        sqlite3.Binary(data),
                        clean_mode,
                        clean_filename,
                        resolved_mime,
                        int(size_bytes or len(data)),
                        int(track_id),
                        int(field_def_id),
                    ),
                )
                if stale_path:
                    self._delete_managed_file_if_unreferenced(stale_path, cursor=self.conn.cursor())
            return self.get_value_meta(track_id, field_def_id)

        if self.file_store.data_root is None:
            raise ValueError("Managed custom-field storage is not configured")
        rel_path = self.file_store.write_bytes(
            data,
            filename=clean_filename,
            subdir=self._blob_subdir(self.definitions.get_field_type(field_def_id)),
        )
        with self.conn:
            self.conn.execute(
                """
                UPDATE CustomFieldValues
                SET blob_value=NULL,
                    managed_file_path=?,
                    storage_mode=?,
                    filename=?,
                    mime_type=?,
                    size_bytes=?
                WHERE track_id=? AND field_def_id=?
                """,
                (
                    rel_path,
                    clean_mode,
                    clean_filename,
                    resolved_mime,
                    int(size_bytes or len(data)),
                    int(track_id),
                    int(field_def_id),
                ),
            )
            if stale_path and stale_path != rel_path:
                self._delete_managed_file_if_unreferenced(stale_path, cursor=self.conn.cursor())
        return self.get_value_meta(track_id, field_def_id)

    def delete_blob(self, track_id: int, field_def_id: int) -> None:
        row = self._fetch_blob_row(track_id, field_def_id)
        stale_path = str(row[2] or "").strip() if row else ""
        with self.conn:
            self.conn.execute(
                "DELETE FROM CustomFieldValues WHERE track_id=? AND field_def_id=?",
                (int(track_id), int(field_def_id)),
            )
            if stale_path:
                self._delete_managed_file_if_unreferenced(stale_path, cursor=self.conn.cursor())

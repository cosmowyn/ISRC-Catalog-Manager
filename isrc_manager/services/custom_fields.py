"""Custom field definition and value services."""

from __future__ import annotations

import json
import mimetypes
import sqlite3

from isrc_manager.blob_icons import blob_icon_spec_from_storage, blob_icon_spec_to_storage
from isrc_manager.media.blob_files import (
    _is_valid_audio_path,
    _is_valid_image_path,
    _read_blob_from_path,
)


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


class CustomFieldValueService:
    """Centralizes custom field value and blob persistence."""

    def __init__(self, conn: sqlite3.Connection, definitions: CustomFieldDefinitionService):
        self.conn = conn
        self.definitions = definitions

    def save_value(
        self, track_id: int, field_def_id: int, *, value=None, blob_path: str | None = None
    ) -> None:
        field_type = self.definitions.get_field_type(field_def_id)
        if field_type in ("blob_image", "blob_audio"):
            if blob_path is None:
                return
            if field_type == "blob_image":
                if not _is_valid_image_path(blob_path):
                    raise ValueError("Selected file is not a recognized image")
            else:
                if not _is_valid_audio_path(blob_path):
                    raise ValueError("Selected file is not a recognized audio format")

            blob_data = _read_blob_from_path(blob_path)
            mime, _ = mimetypes.guess_type(blob_path)
            size = len(blob_data)
            with self.conn:
                self.conn.execute(
                    """
                    INSERT INTO CustomFieldValues (track_id, field_def_id, value, blob_value, mime_type, size_bytes)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(track_id, field_def_id) DO UPDATE SET
                    value=excluded.value, blob_value=excluded.blob_value, mime_type=excluded.mime_type, size_bytes=excluded.size_bytes
                    """,
                    (int(track_id), int(field_def_id), None, sqlite3.Binary(blob_data), mime, size),
                )
            return

        with self.conn:
            self.conn.execute(
                """
                INSERT INTO CustomFieldValues (track_id, field_def_id, value, blob_value, mime_type, size_bytes)
                VALUES (?, ?, ?, NULL, NULL, 0)
                ON CONFLICT(track_id, field_def_id) DO UPDATE SET
                value=excluded.value, blob_value=NULL, mime_type=NULL, size_bytes=0
                """,
                (int(track_id), int(field_def_id), value),
            )

    def get_text_value(self, track_id: int, field_def_id: int) -> str:
        row = self.conn.execute(
            "SELECT value FROM CustomFieldValues WHERE track_id=? AND field_def_id=?",
            (int(track_id), int(field_def_id)),
        ).fetchone()
        return row[0] if row and row[0] is not None else ""

    def get_value_meta(self, track_id: int, field_def_id: int) -> dict:
        row = self.conn.execute(
            """
            SELECT value, blob_value, size_bytes, mime_type
            FROM CustomFieldValues
            WHERE track_id=? AND field_def_id=?
            """,
            (int(track_id), int(field_def_id)),
        ).fetchone()
        if not row:
            return {"value": None, "has_blob": False, "size_bytes": 0, "mime_type": None}
        value, blob_value, size_bytes, mime_type = row
        return {
            "value": value,
            "has_blob": blob_value is not None,
            "size_bytes": int(size_bytes or 0) if size_bytes is not None else 0,
            "mime_type": mime_type,
        }

    def has_blob(self, track_id: int, field_def_id: int) -> bool:
        row = self.conn.execute(
            "SELECT blob_value FROM CustomFieldValues WHERE track_id=? AND field_def_id=?",
            (int(track_id), int(field_def_id)),
        ).fetchone()
        return bool(row and row[0] is not None)

    def blob_size(self, track_id: int, field_def_id: int) -> int:
        row = self.conn.execute(
            "SELECT size_bytes FROM CustomFieldValues WHERE track_id=? AND field_def_id=?",
            (int(track_id), int(field_def_id)),
        ).fetchone()
        return int(row[0] or 0) if row else 0

    def fetch_blob(self, track_id: int, field_def_id: int):
        row = self.conn.execute(
            "SELECT blob_value, mime_type FROM CustomFieldValues WHERE track_id=? AND field_def_id=?",
            (int(track_id), int(field_def_id)),
        ).fetchone()
        if not row or row[0] is None:
            raise FileNotFoundError("No file stored for this field.")
        return row[0], row[1]

    def delete_blob(self, track_id: int, field_def_id: int) -> None:
        with self.conn:
            self.conn.execute(
                "DELETE FROM CustomFieldValues WHERE track_id=? AND field_def_id=?",
                (int(track_id), int(field_def_id)),
            )

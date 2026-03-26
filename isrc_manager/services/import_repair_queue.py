"""Persist and manage failed track-import rows that require repair before reapply."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime


def _json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True)


def _json_loads(value: object) -> object:
    text = str(value or "").strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except Exception:
        return {}


def _clean_text(value: object | None) -> str | None:
    text = str(value or "").strip()
    return text or None


@dataclass(slots=True)
class TrackImportRepairEntry:
    id: int
    source_format: str
    source_path: str | None
    row_index: int
    import_mode: str
    normalized_row: dict[str, object]
    mapping: dict[str, str]
    options: dict[str, object]
    failure_category: str
    failure_message: str
    status: str
    created_at: str | None
    updated_at: str | None
    resolved_at: str | None
    resolved_track_id: int | None = None
    resolved_work_id: int | None = None


class TrackImportRepairQueueService:
    """Owns persisted review/repair rows for failed track imports."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    @staticmethod
    def _row_to_entry(row) -> TrackImportRepairEntry:
        return TrackImportRepairEntry(
            id=int(row[0]),
            source_format=str(row[1] or "").strip(),
            source_path=_clean_text(row[2]),
            row_index=int(row[3] or 0),
            import_mode=str(row[4] or "").strip() or "create",
            normalized_row=dict(_json_loads(row[5]) or {}),
            mapping={
                str(key): str(value)
                for key, value in dict(_json_loads(row[6]) or {}).items()
                if str(key).strip() and str(value).strip()
            },
            options=dict(_json_loads(row[7]) or {}),
            failure_category=str(row[8] or "").strip() or "validation",
            failure_message=str(row[9] or "").strip(),
            status=str(row[10] or "").strip() or "pending",
            created_at=_clean_text(row[11]),
            updated_at=_clean_text(row[12]),
            resolved_at=_clean_text(row[13]),
            resolved_track_id=int(row[14]) if row[14] is not None else None,
            resolved_work_id=int(row[15]) if row[15] is not None else None,
        )

    def list_entries(self, *, status: str | None = "pending") -> list[TrackImportRepairEntry]:
        params: list[object] = []
        where_sql = ""
        if status is not None:
            where_sql = "WHERE status=?"
            params.append(str(status))
        rows = self.conn.execute(
            f"""
            SELECT
                id,
                source_format,
                source_path,
                row_index,
                import_mode,
                normalized_row_json,
                mapping_json,
                options_json,
                failure_category,
                failure_message,
                status,
                created_at,
                updated_at,
                resolved_at,
                resolved_track_id,
                resolved_work_id
            FROM TrackImportRepairQueue
            {where_sql}
            ORDER BY status='pending' DESC, created_at DESC, id DESC
            """,
            params,
        ).fetchall()
        return [self._row_to_entry(row) for row in rows]

    def fetch_entry(self, entry_id: int) -> TrackImportRepairEntry | None:
        row = self.conn.execute(
            """
            SELECT
                id,
                source_format,
                source_path,
                row_index,
                import_mode,
                normalized_row_json,
                mapping_json,
                options_json,
                failure_category,
                failure_message,
                status,
                created_at,
                updated_at,
                resolved_at,
                resolved_track_id,
                resolved_work_id
            FROM TrackImportRepairQueue
            WHERE id=?
            """,
            (int(entry_id),),
        ).fetchone()
        return self._row_to_entry(row) if row is not None else None

    def queue_failed_row(
        self,
        *,
        source_format: str,
        source_path: str | None,
        row_index: int,
        import_mode: str,
        normalized_row: dict[str, object],
        mapping: dict[str, str] | None,
        options: dict[str, object] | None,
        failure_category: str,
        failure_message: str,
    ) -> int:
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO TrackImportRepairQueue(
                source_format,
                source_path,
                row_index,
                import_mode,
                normalized_row_json,
                mapping_json,
                options_json,
                failure_category,
                failure_message,
                status,
                created_at,
                updated_at,
                resolved_at,
                resolved_track_id,
                resolved_work_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, NULL, NULL, NULL)
            """,
            (
                str(source_format or "").strip().lower(),
                _clean_text(source_path),
                int(row_index),
                str(import_mode or "").strip() or "create",
                _json_dumps(dict(normalized_row or {})),
                _json_dumps(dict(mapping or {})),
                _json_dumps(dict(options or {})),
                str(failure_category or "validation").strip() or "validation",
                str(failure_message or "").strip(),
            ),
        )
        return int(cur.lastrowid)

    def update_entry(
        self,
        entry_id: int,
        *,
        normalized_row: dict[str, object],
        failure_category: str,
        failure_message: str,
        mapping: dict[str, str] | None = None,
        options: dict[str, object] | None = None,
    ) -> None:
        assignments = [
            "normalized_row_json=?",
            "failure_category=?",
            "failure_message=?",
            "status='pending'",
            "updated_at=CURRENT_TIMESTAMP",
            "resolved_at=NULL",
            "resolved_track_id=NULL",
            "resolved_work_id=NULL",
        ]
        params: list[object] = [
            _json_dumps(dict(normalized_row or {})),
            str(failure_category or "validation").strip() or "validation",
            str(failure_message or "").strip(),
        ]
        if mapping is not None:
            assignments.append("mapping_json=?")
            params.append(_json_dumps(dict(mapping or {})))
        if options is not None:
            assignments.append("options_json=?")
            params.append(_json_dumps(dict(options or {})))
        params.append(int(entry_id))
        self.conn.execute(
            f"UPDATE TrackImportRepairQueue SET {', '.join(assignments)} WHERE id=?",
            params,
        )

    def mark_resolved(self, entry_id: int, *, track_id: int, work_id: int) -> None:
        self.conn.execute(
            """
            UPDATE TrackImportRepairQueue
            SET status='resolved',
                updated_at=CURRENT_TIMESTAMP,
                resolved_at=CURRENT_TIMESTAMP,
                resolved_track_id=?,
                resolved_work_id=?,
                failure_message=''
            WHERE id=?
            """,
            (int(track_id), int(work_id), int(entry_id)),
        )

    def delete_entries(self, entry_ids: list[int]) -> int:
        normalized_ids = sorted({int(entry_id) for entry_id in entry_ids if int(entry_id) > 0})
        if not normalized_ids:
            return 0
        placeholders = ",".join("?" for _ in normalized_ids)
        self.conn.execute(
            f"DELETE FROM TrackImportRepairQueue WHERE id IN ({placeholders})",
            normalized_ids,
        )
        return len(normalized_ids)

    def pending_count(self) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) FROM TrackImportRepairQueue WHERE status='pending'"
        ).fetchone()
        return int(row[0] or 0) if row else 0

    def touch_entry(self, entry_id: int) -> None:
        self.conn.execute(
            "UPDATE TrackImportRepairQueue SET updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (int(entry_id),),
        )

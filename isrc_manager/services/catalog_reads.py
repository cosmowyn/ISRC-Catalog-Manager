"""Read-only catalog queries used by the UI layer."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import TYPE_CHECKING

from .track_artist_sql import track_additional_artists_expr, track_main_artist_join_sql

if TYPE_CHECKING:
    from .custom_fields import CustomFieldValueService
    from .tracks import TrackService


class CatalogReadService:
    """Centralizes common read-only catalog queries."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def _table_names(self) -> set[str]:
        return {
            str(row[0])
            for row in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            if row and row[0]
        }

    def _table_columns(self, table: str) -> set[str]:
        if table not in self._table_names():
            return set()
        return {
            str(row[1])
            for row in self.conn.execute(f"PRAGMA table_info({table})").fetchall()
            if row and row[1]
        }

    def fetch_rows_with_customs(
        self,
        active_custom_fields: list[dict[str, object]],
        *,
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> tuple[list[tuple], dict[tuple[int, int], str]]:
        work_columns = self._table_columns("Works")
        if callable(progress_callback):
            progress_callback(1, 4, "Inspected Work schema columns for catalog rows.")
        work_registration_sql = (
            "COALESCE(NULLIF(w.registration_number, ''), t.buma_work_number, '') AS buma_work_number"
            if "registration_number" in work_columns
            else "COALESCE(t.buma_work_number, '') AS buma_work_number"
        )
        work_iswc_sql = (
            "COALESCE(NULLIF(w.iswc, ''), t.iswc, '') AS iswc"
            if "iswc" in work_columns
            else "COALESCE(t.iswc, '') AS iswc"
        )
        main_artist_join_sql, main_artist_name_expr = track_main_artist_join_sql(
            self.conn,
            track_alias="t",
            artist_alias="main_artist",
        )
        additional_artists_sql = track_additional_artists_expr(self.conn, track_id_expr="t.id")
        base_rows = self.conn.execute(
            f"""
            SELECT
                t.id,
                '' AS audio_file,
                t.track_title,
                COALESCE(t.track_length_sec, 0) AS track_length_sec,
                COALESCE(al.title, '') AS album_title,
                '' AS album_art,
                COALESCE({main_artist_name_expr}, '') AS artist_name,
                {additional_artists_sql} AS additional_artists,
                t.isrc,
                {work_registration_sql},
                {work_iswc_sql},
                COALESCE(t.upc, '') AS upc,
                COALESCE(t.catalog_number, '') AS catalog_number,
                COALESCE(t.db_entry_date, '') AS db_entry_date,
                COALESCE(t.release_date, '') AS release_date,
                COALESCE(t.genre, '') AS genre
            FROM Tracks t
            {main_artist_join_sql}
            LEFT JOIN Albums al ON al.id = t.album_id
            LEFT JOIN Works w ON w.id = t.work_id
            ORDER BY t.id
            """
        ).fetchall()
        if callable(progress_callback):
            progress_callback(2, 4, f"Loaded {len(base_rows)} catalog track rows.")

        custom_field_map: dict[tuple[int, int], str] = {}
        if active_custom_fields:
            active_ids = tuple(field["id"] for field in active_custom_fields)
            if len(active_ids) == 1:
                rows = self.conn.execute(
                    "SELECT track_id, field_def_id, value FROM CustomFieldValues WHERE field_def_id=?",
                    (active_ids[0],),
                ).fetchall()
            else:
                placeholders = ",".join("?" * len(active_ids))
                rows = self.conn.execute(
                    f"SELECT track_id, field_def_id, value FROM CustomFieldValues WHERE field_def_id IN ({placeholders})",
                    active_ids,
                ).fetchall()
            for track_id, field_id, value in rows:
                custom_field_map[(track_id, field_id)] = "" if value is None else str(value)
            if callable(progress_callback):
                progress_callback(
                    3,
                    4,
                    f"Loaded {len(rows)} active custom-field values.",
                )
        elif callable(progress_callback):
            progress_callback(3, 4, "No active custom-field values needed loading.")

        if callable(progress_callback):
            progress_callback(4, 4, "Prepared catalog row payload for the UI.")

        return base_rows, custom_field_map

    def fetch_blob_badge_payload(
        self,
        track_ids,
        active_custom_fields: list[dict[str, object]],
        *,
        track_service: TrackService | None,
        custom_field_values: CustomFieldValueService | None,
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> dict[str, object]:
        normalized_track_ids: list[int] = []
        seen_track_ids: set[int] = set()
        for raw_track_id in track_ids or []:
            try:
                track_id = int(raw_track_id)
            except Exception:
                continue
            if track_id in seen_track_ids:
                continue
            seen_track_ids.add(track_id)
            normalized_track_ids.append(track_id)
        if not normalized_track_ids:
            if callable(progress_callback):
                progress_callback(1, 1, "No catalog media badges needed preparation.")
            return {"standard_media": {}, "custom_fields": {}}

        if callable(progress_callback):
            progress_callback(
                1,
                4,
                f"Preparing media badges for {len(normalized_track_ids)} catalog rows.",
            )
        standard_media = (
            track_service.get_media_meta_map(
                normalized_track_ids,
                media_keys=("audio_file", "album_art"),
            )
            if track_service is not None
            else {}
        )
        if callable(progress_callback):
            progress_callback(
                2,
                4,
                f"Loaded standard media badge metadata for {len(standard_media)} catalog cells.",
            )
        blob_field_ids = [
            int(field["id"])
            for field in active_custom_fields
            if str(field.get("field_type") or "").strip().lower() in {"blob_audio", "blob_image"}
            and field.get("id") is not None
        ]
        custom_fields = (
            custom_field_values.get_value_meta_map(
                blob_field_ids,
                track_ids=normalized_track_ids,
                include_storage_details=True,
            )
            if custom_field_values is not None and blob_field_ids
            else {}
        )
        if callable(progress_callback):
            progress_callback(
                3,
                4,
                f"Loaded custom media badge metadata for {len(custom_fields)} catalog cells.",
            )
            progress_callback(4, 4, "Prepared catalog media badge payload.")
        return {
            "standard_media": standard_media,
            "custom_fields": custom_fields,
        }

    def find_album_metadata(self, title: str) -> tuple[str | None, str | None, str | None] | None:
        clean_title = (title or "").strip()
        if not clean_title:
            return None
        row = self.conn.execute(
            """
            SELECT t.release_date, t.upc, t.genre
            FROM Tracks t
            JOIN Albums a ON a.id = t.album_id
            WHERE a.title = ?
            LIMIT 1
            """,
            (clean_title,),
        ).fetchone()
        if not row:
            return None
        return row[0], row[1], row[2]

    def list_tracks(self) -> list[tuple[int, str]]:
        return self.conn.execute(
            "SELECT id, track_title FROM Tracks ORDER BY track_title COLLATE NOCASE"
        ).fetchall()

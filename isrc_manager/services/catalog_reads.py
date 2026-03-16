"""Read-only catalog queries used by the UI layer."""

from __future__ import annotations

import sqlite3


class CatalogReadService:
    """Centralizes common read-only catalog queries."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def fetch_rows_with_customs(
        self, active_custom_fields: list[dict]
    ) -> tuple[list[tuple], dict[tuple[int, int], str]]:
        base_rows = self.conn.execute(
            """
            SELECT
                t.id,
                '' AS audio_file,
                t.track_title,
                COALESCE(t.track_length_sec, 0) AS track_length_sec,
                COALESCE(al.title, '') AS album_title,
                '' AS album_art,
                COALESCE(a.name, '') AS artist_name,
                COALESCE((
                    SELECT GROUP_CONCAT(ar.name, ', ')
                    FROM TrackArtists ta
                    JOIN Artists ar ON ar.id = ta.artist_id
                    WHERE ta.track_id = t.id AND ta.role = 'additional'
                ), '') AS additional_artists,
                t.isrc,
                COALESCE(t.buma_work_number, '') AS buma_work_number,
                COALESCE(t.iswc, '') AS iswc,
                COALESCE(t.upc, '') AS upc,
                COALESCE(t.catalog_number, '') AS catalog_number,
                COALESCE(t.db_entry_date, '') AS db_entry_date,
                COALESCE(t.release_date, '') AS release_date,
                COALESCE(t.genre, '') AS genre
            FROM Tracks t
            LEFT JOIN Artists a ON a.id = t.main_artist_id
            LEFT JOIN Albums al ON al.id = t.album_id
            ORDER BY t.id
            """
        ).fetchall()

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

        return base_rows, custom_field_map

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

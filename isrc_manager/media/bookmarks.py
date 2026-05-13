"""Persistent audio preview bookmarks."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class AudioBookmark:
    id: int
    track_id: int
    position_ms: int
    label: str
    created_at: str
    updated_at: str


def ensure_audio_bookmark_schema(conn: sqlite3.Connection) -> None:
    table_names = {
        str(row[0])
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        if row and row[0]
    }
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS TrackAudioBookmarks (
            id INTEGER PRIMARY KEY,
            track_id INTEGER NOT NULL,
            position_ms INTEGER NOT NULL,
            label TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(track_id, position_ms),
            FOREIGN KEY(track_id) REFERENCES Tracks(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_track_audio_bookmarks_track_position
        ON TrackAudioBookmarks(track_id, position_ms)
        """
    )
    if "Tracks" in table_names:
        conn.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_tracks_audio_bookmarks_delete
            AFTER DELETE ON Tracks
            FOR EACH ROW
            BEGIN
                DELETE FROM TrackAudioBookmarks WHERE track_id = OLD.id;
            END
            """
        )


def _coerce_positive_track_id(track_id: Any) -> int:
    try:
        clean_track_id = int(track_id)
    except (TypeError, ValueError):
        clean_track_id = 0
    if clean_track_id <= 0:
        raise ValueError("track_id must be a positive integer")
    return clean_track_id


def _coerce_position_ms(position_ms: Any, *, duration_ms: Any = None) -> int:
    try:
        clean_position = int(round(float(position_ms)))
    except (TypeError, ValueError):
        clean_position = 0
    clean_position = max(0, clean_position)
    try:
        clean_duration = int(round(float(duration_ms)))
    except (TypeError, ValueError):
        clean_duration = 0
    if clean_duration > 0:
        clean_position = min(clean_position, clean_duration)
    return clean_position


def _row_to_bookmark(row: sqlite3.Row | tuple[Any, ...]) -> AudioBookmark:
    if isinstance(row, sqlite3.Row):
        return AudioBookmark(
            id=int(row["id"]),
            track_id=int(row["track_id"]),
            position_ms=int(row["position_ms"]),
            label=str(row["label"] or ""),
            created_at=str(row["created_at"] or ""),
            updated_at=str(row["updated_at"] or ""),
        )
    return AudioBookmark(
        id=int(row[0]),
        track_id=int(row[1]),
        position_ms=int(row[2]),
        label=str(row[3] or ""),
        created_at=str(row[4] or ""),
        updated_at=str(row[5] or ""),
    )


def load_audio_bookmarks(
    conn: sqlite3.Connection,
    track_id: Any,
    *,
    cursor: sqlite3.Cursor | None = None,
) -> list[AudioBookmark]:
    ensure_audio_bookmark_schema(conn)
    clean_track_id = _coerce_positive_track_id(track_id)
    cur = cursor or conn.cursor()
    rows = cur.execute(
        """
        SELECT id, track_id, position_ms, label, created_at, updated_at
        FROM TrackAudioBookmarks
        WHERE track_id=?
        ORDER BY position_ms, id
        """,
        (clean_track_id,),
    ).fetchall()
    return [_row_to_bookmark(row) for row in rows]


def add_audio_bookmark(
    conn: sqlite3.Connection,
    track_id: Any,
    position_ms: Any,
    *,
    duration_ms: Any = None,
    label: str | None = None,
) -> AudioBookmark:
    ensure_audio_bookmark_schema(conn)
    clean_track_id = _coerce_positive_track_id(track_id)
    clean_position = _coerce_position_ms(position_ms, duration_ms=duration_ms)
    clean_label = str(label or "").strip()
    with conn:
        conn.execute(
            """
            INSERT INTO TrackAudioBookmarks(track_id, position_ms, label)
            VALUES (?, ?, ?)
            ON CONFLICT(track_id, position_ms) DO UPDATE SET
                label=excluded.label,
                updated_at=datetime('now')
            """,
            (clean_track_id, clean_position, clean_label),
        )
    row = conn.execute(
        """
        SELECT id, track_id, position_ms, label, created_at, updated_at
        FROM TrackAudioBookmarks
        WHERE track_id=? AND position_ms=?
        """,
        (clean_track_id, clean_position),
    ).fetchone()
    if row is None:
        raise RuntimeError("audio bookmark was not saved")
    return _row_to_bookmark(row)


def delete_audio_bookmark(
    conn: sqlite3.Connection,
    bookmark_id: Any,
    *,
    track_id: Any | None = None,
) -> int:
    ensure_audio_bookmark_schema(conn)
    try:
        clean_bookmark_id = int(bookmark_id)
    except (TypeError, ValueError):
        return 0
    if clean_bookmark_id <= 0:
        return 0
    params: tuple[Any, ...]
    sql = "DELETE FROM TrackAudioBookmarks WHERE id=?"
    params = (clean_bookmark_id,)
    if track_id is not None:
        try:
            clean_track_id = int(track_id)
        except (TypeError, ValueError):
            return 0
        sql += " AND track_id=?"
        params = (clean_bookmark_id, clean_track_id)
    with conn:
        cur = conn.execute(sql, params)
    return int(cur.rowcount or 0)


def delete_audio_bookmarks_for_track(conn: sqlite3.Connection, track_id: Any) -> int:
    ensure_audio_bookmark_schema(conn)
    clean_track_id = _coerce_positive_track_id(track_id)
    with conn:
        cur = conn.execute("DELETE FROM TrackAudioBookmarks WHERE track_id=?", (clean_track_id,))
    return int(cur.rowcount or 0)

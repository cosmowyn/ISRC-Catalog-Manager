"""Track mutation services used by the UI layer."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Iterable

from isrc_manager.domain.codes import is_blank, to_compact_isrc


@dataclass(slots=True)
class TrackCreatePayload:
    isrc: str
    track_title: str
    artist_name: str
    additional_artists: list[str]
    album_title: str | None
    release_date: str | None
    track_length_sec: int
    iswc: str | None
    upc: str | None
    genre: str | None


@dataclass(slots=True)
class TrackUpdatePayload:
    track_id: int
    isrc: str
    track_title: str
    artist_name: str
    additional_artists: list[str]
    album_title: str | None
    release_date: str | None
    track_length_sec: int
    iswc: str | None
    upc: str | None
    genre: str | None


class TrackService:
    """Centralizes track mutations and related catalog row creation."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    @staticmethod
    def parse_additional_artists(text: str) -> list[str]:
        parts = [part.strip() for part in (text or "").split(",")]
        return [part for part in parts if part]

    def get_or_create_artist(self, name: str, *, cursor: sqlite3.Cursor | None = None) -> int:
        name = (name or "").strip()
        if is_blank(name):
            raise ValueError("Artist name is required")
        cur = cursor or self.conn.cursor()
        row = cur.execute("SELECT id FROM Artists WHERE name=? ORDER BY id LIMIT 1", (name,)).fetchone()
        if row:
            return int(row[0])
        cur.execute("INSERT INTO Artists (name) VALUES (?)", (name,))
        return int(cur.lastrowid)

    def get_or_create_album(self, title: str | None, *, cursor: sqlite3.Cursor | None = None) -> int | None:
        title = (title or "").strip()
        if is_blank(title):
            return None
        cur = cursor or self.conn.cursor()
        row = cur.execute("SELECT id FROM Albums WHERE title=? ORDER BY id LIMIT 1", (title,)).fetchone()
        if row:
            return int(row[0])
        cur.execute("INSERT INTO Albums (title) VALUES (?)", (title,))
        return int(cur.lastrowid)

    def replace_additional_artists(
        self,
        track_id: int,
        names: Iterable[str],
        *,
        cursor: sqlite3.Cursor | None = None,
    ) -> None:
        cur = cursor or self.conn.cursor()
        cur.execute("DELETE FROM TrackArtists WHERE track_id=? AND role='additional'", (track_id,))
        for name in names:
            try:
                artist_id = self.get_or_create_artist(name, cursor=cur)
                cur.execute(
                    "INSERT OR IGNORE INTO TrackArtists (track_id, artist_id, role) VALUES (?, ?, 'additional')",
                    (track_id, artist_id),
                )
            except ValueError:
                pass

    def is_isrc_taken_normalized(
        self,
        candidate: str,
        *,
        exclude_track_id: int | None = None,
        cursor: sqlite3.Cursor | None = None,
    ) -> bool:
        norm = to_compact_isrc(candidate)
        if not norm:
            return False
        cur = cursor or self.conn.cursor()
        if exclude_track_id is None:
            row = cur.execute("SELECT 1 FROM Tracks WHERE isrc_compact = ? LIMIT 1", (norm,)).fetchone()
        else:
            row = cur.execute(
                "SELECT 1 FROM Tracks WHERE isrc_compact = ? AND id != ? LIMIT 1",
                (norm, exclude_track_id),
            ).fetchone()
        return bool(row)

    def fetch_track_title(self, track_id: int, *, cursor: sqlite3.Cursor | None = None) -> str:
        cur = cursor or self.conn.cursor()
        row = cur.execute("SELECT track_title FROM Tracks WHERE id=?", (track_id,)).fetchone()
        if row and row[0]:
            return str(row[0])
        return f"track_{track_id}"

    def create_track(self, payload: TrackCreatePayload) -> int:
        with self.conn:
            cur = self.conn.cursor()
            main_artist_id = self.get_or_create_artist(payload.artist_name, cursor=cur)
            album_id = self.get_or_create_album(payload.album_title, cursor=cur)
            compact_isrc = to_compact_isrc(payload.isrc)
            cur.execute(
                """
                INSERT INTO Tracks (isrc, isrc_compact, track_title, main_artist_id, album_id, release_date, track_length_sec, iswc, upc, genre)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.isrc,
                    compact_isrc,
                    payload.track_title.strip(),
                    main_artist_id,
                    album_id,
                    payload.release_date,
                    int(payload.track_length_sec or 0),
                    payload.iswc,
                    payload.upc,
                    payload.genre,
                ),
            )
            track_id = int(cur.lastrowid)
            self.replace_additional_artists(track_id, payload.additional_artists, cursor=cur)
            return track_id

    def update_track(self, payload: TrackUpdatePayload) -> None:
        with self.conn:
            cur = self.conn.cursor()
            main_artist_id = self.get_or_create_artist(payload.artist_name, cursor=cur)
            album_id = self.get_or_create_album(payload.album_title, cursor=cur)
            compact_isrc = to_compact_isrc(payload.isrc)
            cur.execute(
                """
                UPDATE Tracks SET
                    isrc=?, isrc_compact=?, track_title=?, main_artist_id=?, album_id=?, release_date=?,
                    track_length_sec=?, iswc=?, upc=?, genre=?
                WHERE id=?
                """,
                (
                    payload.isrc,
                    compact_isrc,
                    payload.track_title.strip(),
                    main_artist_id,
                    album_id,
                    payload.release_date,
                    int(payload.track_length_sec or 0),
                    payload.iswc,
                    payload.upc,
                    payload.genre,
                    payload.track_id,
                ),
            )
            self.replace_additional_artists(payload.track_id, payload.additional_artists, cursor=cur)

    def delete_track(self, track_id: int) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM Tracks WHERE id=?", (track_id,))


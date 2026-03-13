"""Track mutation services used by the UI layer."""

from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
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


@dataclass(slots=True)
class TrackSnapshot:
    track_id: int
    db_entry_date: str | None
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

    def to_dict(self) -> dict:
        return asdict(self)


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

    def artist_exists(self, name: str, *, cursor: sqlite3.Cursor | None = None) -> bool:
        clean_name = (name or "").strip()
        if is_blank(clean_name):
            return False
        cur = cursor or self.conn.cursor()
        row = cur.execute("SELECT 1 FROM Artists WHERE name=? LIMIT 1", (clean_name,)).fetchone()
        return bool(row)

    def album_exists(self, title: str | None, *, cursor: sqlite3.Cursor | None = None) -> bool:
        clean_title = (title or "").strip()
        if is_blank(clean_title):
            return False
        cur = cursor or self.conn.cursor()
        row = cur.execute("SELECT 1 FROM Albums WHERE title=? LIMIT 1", (clean_title,)).fetchone()
        return bool(row)

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

    def fetch_track_snapshot(self, track_id: int, *, cursor: sqlite3.Cursor | None = None) -> TrackSnapshot | None:
        cur = cursor or self.conn.cursor()
        row = cur.execute(
            """
            SELECT
                t.id,
                t.db_entry_date,
                t.isrc,
                t.track_title,
                main_artist.name,
                album.title,
                t.release_date,
                t.track_length_sec,
                t.iswc,
                t.upc,
                t.genre
            FROM Tracks t
            JOIN Artists main_artist ON main_artist.id = t.main_artist_id
            LEFT JOIN Albums album ON album.id = t.album_id
            WHERE t.id=?
            """,
            (int(track_id),),
        ).fetchone()
        if not row:
            return None

        additional_rows = cur.execute(
            """
            SELECT a.name
            FROM TrackArtists ta
            JOIN Artists a ON a.id = ta.artist_id
            WHERE ta.track_id=? AND ta.role='additional'
            ORDER BY a.name
            """,
            (int(track_id),),
        ).fetchall()

        return TrackSnapshot(
            track_id=int(row[0]),
            db_entry_date=row[1],
            isrc=row[2] or "",
            track_title=row[3] or "",
            artist_name=row[4] or "",
            additional_artists=[name for (name,) in additional_rows if name],
            album_title=row[5],
            release_date=row[6],
            track_length_sec=int(row[7] or 0),
            iswc=row[8],
            upc=row[9],
            genre=row[10],
        )

    def restore_track_snapshot(self, snapshot: TrackSnapshot, *, cursor: sqlite3.Cursor | None = None) -> None:
        cur = cursor or self.conn.cursor()
        main_artist_id = self.get_or_create_artist(snapshot.artist_name, cursor=cur)
        album_id = self.get_or_create_album(snapshot.album_title, cursor=cur)
        compact_isrc = to_compact_isrc(snapshot.isrc)
        existing = cur.execute("SELECT 1 FROM Tracks WHERE id=?", (int(snapshot.track_id),)).fetchone()
        if existing:
            cur.execute(
                """
                UPDATE Tracks SET
                    db_entry_date=?,
                    isrc=?,
                    isrc_compact=?,
                    track_title=?,
                    main_artist_id=?,
                    album_id=?,
                    release_date=?,
                    track_length_sec=?,
                    iswc=?,
                    upc=?,
                    genre=?
                WHERE id=?
                """,
                (
                    snapshot.db_entry_date,
                    snapshot.isrc,
                    compact_isrc,
                    snapshot.track_title,
                    main_artist_id,
                    album_id,
                    snapshot.release_date,
                    int(snapshot.track_length_sec or 0),
                    snapshot.iswc,
                    snapshot.upc,
                    snapshot.genre,
                    int(snapshot.track_id),
                ),
            )
        else:
            cur.execute(
                """
                INSERT INTO Tracks (
                    id, db_entry_date, isrc, isrc_compact, track_title, main_artist_id, album_id,
                    release_date, track_length_sec, iswc, upc, genre
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(snapshot.track_id),
                    snapshot.db_entry_date,
                    snapshot.isrc,
                    compact_isrc,
                    snapshot.track_title,
                    main_artist_id,
                    album_id,
                    snapshot.release_date,
                    int(snapshot.track_length_sec or 0),
                    snapshot.iswc,
                    snapshot.upc,
                    snapshot.genre,
                ),
            )
        self.replace_additional_artists(snapshot.track_id, snapshot.additional_artists, cursor=cur)

    def delete_unused_artists_by_names(self, names: Iterable[str], *, cursor: sqlite3.Cursor | None = None) -> None:
        cur = cursor or self.conn.cursor()
        cleaned_names = sorted({(name or "").strip() for name in names if not is_blank(name)})
        for name in cleaned_names:
            cur.execute(
                """
                DELETE FROM Artists
                WHERE name=?
                  AND id NOT IN (SELECT main_artist_id FROM Tracks WHERE main_artist_id IS NOT NULL)
                  AND id NOT IN (SELECT artist_id FROM TrackArtists)
                """,
                (name,),
            )

    def delete_unused_albums_by_titles(self, titles: Iterable[str], *, cursor: sqlite3.Cursor | None = None) -> None:
        cur = cursor or self.conn.cursor()
        cleaned_titles = sorted({(title or "").strip() for title in titles if not is_blank(title)})
        for title in cleaned_titles:
            cur.execute(
                """
                DELETE FROM Albums
                WHERE title=?
                  AND id NOT IN (SELECT album_id FROM Tracks WHERE album_id IS NOT NULL)
                """,
                (title,),
            )

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

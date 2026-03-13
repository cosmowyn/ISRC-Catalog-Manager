"""Track mutation services used by the UI layer."""

from __future__ import annotations

import mimetypes
import sqlite3
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from isrc_manager.domain.codes import is_blank, to_compact_isrc
from isrc_manager.media.blob_files import _is_valid_audio_path, _is_valid_image_path


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
    catalog_number: str | None = None
    buma_work_number: str | None = None
    audio_file_source_path: str | None = None
    album_art_source_path: str | None = None


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
    catalog_number: str | None = None
    buma_work_number: str | None = None
    audio_file_source_path: str | None = None
    album_art_source_path: str | None = None
    clear_audio_file: bool = False
    clear_album_art: bool = False


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
    catalog_number: str | None
    buma_work_number: str | None
    audio_file_path: str | None
    audio_file_mime_type: str | None
    audio_file_size_bytes: int
    album_art_path: str | None
    album_art_mime_type: str | None
    album_art_size_bytes: int

    def to_dict(self) -> dict:
        return asdict(self)


class TrackService:
    """Centralizes track mutations and related catalog row creation."""

    MEDIA_FIELDS = {
        "audio_file": {
            "path_column": "audio_file_path",
            "mime_column": "audio_file_mime_type",
            "size_column": "audio_file_size_bytes",
            "subdir": "audio",
            "validator": staticmethod(_is_valid_audio_path),
        },
        "album_art": {
            "path_column": "album_art_path",
            "mime_column": "album_art_mime_type",
            "size_column": "album_art_size_bytes",
            "subdir": "images",
            "validator": staticmethod(_is_valid_image_path),
        },
    }

    def __init__(self, conn: sqlite3.Connection, data_root: str | Path | None = None):
        self.conn = conn
        self.data_root = Path(data_root) if data_root is not None else None
        self.media_root = self.data_root / "track_media" if self.data_root is not None else None

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

    def resolve_media_path(self, stored_path: str | None) -> Path | None:
        clean_path = (stored_path or "").strip()
        if not clean_path:
            return None
        path = Path(clean_path)
        if path.is_absolute():
            return path
        if self.data_root is None:
            raise ValueError("Track media root is not configured")
        return self.data_root / path

    def get_media_meta(
        self,
        track_id: int,
        media_key: str,
        *,
        cursor: sqlite3.Cursor | None = None,
    ) -> dict[str, str | int | bool]:
        config = self.MEDIA_FIELDS[media_key]
        cur = cursor or self.conn.cursor()
        row = cur.execute(
            f"""
            SELECT {config['path_column']}, {config['mime_column']}, {config['size_column']}
            FROM Tracks
            WHERE id=?
            """,
            (int(track_id),),
        ).fetchone()
        if not row:
            return {"has_media": False, "path": "", "mime_type": "", "size_bytes": 0}
        path_value = row[0] or ""
        return {
            "has_media": bool(path_value),
            "path": path_value,
            "mime_type": row[1] or "",
            "size_bytes": int(row[2] or 0),
        }

    def has_media(self, track_id: int, media_key: str, *, cursor: sqlite3.Cursor | None = None) -> bool:
        return bool(self.get_media_meta(track_id, media_key, cursor=cursor).get("has_media"))

    def fetch_media_bytes(
        self,
        track_id: int,
        media_key: str,
        *,
        cursor: sqlite3.Cursor | None = None,
    ) -> tuple[bytes, str]:
        meta = self.get_media_meta(track_id, media_key, cursor=cursor)
        stored_path = str(meta.get("path") or "")
        resolved = self.resolve_media_path(stored_path)
        if not resolved or not resolved.exists():
            raise FileNotFoundError(stored_path or f"{media_key} for track {track_id}")
        return resolved.read_bytes(), str(meta.get("mime_type") or "")

    def set_media_path(
        self,
        track_id: int,
        media_key: str,
        source_path: str | Path,
        *,
        cursor: sqlite3.Cursor | None = None,
    ) -> dict[str, str | int | bool]:
        config = self.MEDIA_FIELDS[media_key]
        source = Path(source_path)
        if not source.exists():
            raise FileNotFoundError(source)
        if not config["validator"](str(source)):
            raise ValueError(f"Selected file is not a valid {media_key.replace('_', ' ')}")
        if self.media_root is None or self.data_root is None:
            raise ValueError("Track media root is not configured")

        destination_dir = self.media_root / config["subdir"]
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / f"{int(time.time_ns())}_{source.name}"
        destination.write_bytes(source.read_bytes())

        mime_type = mimetypes.guess_type(source.name)[0] or ""
        size_bytes = destination.stat().st_size
        rel_path = str(destination.relative_to(self.data_root))

        cur = cursor or self.conn.cursor()
        cur.execute(
            f"""
            UPDATE Tracks
            SET {config['path_column']}=?, {config['mime_column']}=?, {config['size_column']}=?
            WHERE id=?
            """,
            (rel_path, mime_type, int(size_bytes), int(track_id)),
        )
        return {
            "has_media": True,
            "path": rel_path,
            "mime_type": mime_type,
            "size_bytes": int(size_bytes),
        }

    def clear_media(self, track_id: int, media_key: str, *, cursor: sqlite3.Cursor | None = None) -> None:
        config = self.MEDIA_FIELDS[media_key]
        cur = cursor or self.conn.cursor()
        cur.execute(
            f"""
            UPDATE Tracks
            SET {config['path_column']}=NULL, {config['mime_column']}=NULL, {config['size_column']}=0
            WHERE id=?
            """,
            (int(track_id),),
        )

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
                t.audio_file_path,
                t.audio_file_mime_type,
                t.audio_file_size_bytes,
                t.track_title,
                t.catalog_number,
                t.album_art_path,
                t.album_art_mime_type,
                t.album_art_size_bytes,
                main_artist.name,
                t.buma_work_number,
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
            track_title=row[6] or "",
            artist_name=row[11] or "",
            additional_artists=[name for (name,) in additional_rows if name],
            album_title=row[13],
            release_date=row[14],
            track_length_sec=int(row[15] or 0),
            iswc=row[16],
            upc=row[17],
            genre=row[18],
            catalog_number=row[7],
            buma_work_number=row[12],
            audio_file_path=row[3],
            audio_file_mime_type=row[4],
            audio_file_size_bytes=int(row[5] or 0),
            album_art_path=row[8],
            album_art_mime_type=row[9],
            album_art_size_bytes=int(row[10] or 0),
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
                    audio_file_path=?,
                    audio_file_mime_type=?,
                    audio_file_size_bytes=?,
                    track_title=?,
                    catalog_number=?,
                    album_art_path=?,
                    album_art_mime_type=?,
                    album_art_size_bytes=?,
                    main_artist_id=?,
                    buma_work_number=?,
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
                    snapshot.audio_file_path,
                    snapshot.audio_file_mime_type,
                    int(snapshot.audio_file_size_bytes or 0),
                    snapshot.track_title,
                    snapshot.catalog_number,
                    snapshot.album_art_path,
                    snapshot.album_art_mime_type,
                    int(snapshot.album_art_size_bytes or 0),
                    main_artist_id,
                    snapshot.buma_work_number,
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
                    id, db_entry_date, isrc, isrc_compact,
                    audio_file_path, audio_file_mime_type, audio_file_size_bytes,
                    track_title, catalog_number,
                    album_art_path, album_art_mime_type, album_art_size_bytes,
                    main_artist_id, buma_work_number, album_id,
                    release_date, track_length_sec, iswc, upc, genre
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(snapshot.track_id),
                    snapshot.db_entry_date,
                    snapshot.isrc,
                    compact_isrc,
                    snapshot.audio_file_path,
                    snapshot.audio_file_mime_type,
                    int(snapshot.audio_file_size_bytes or 0),
                    snapshot.track_title,
                    snapshot.catalog_number,
                    snapshot.album_art_path,
                    snapshot.album_art_mime_type,
                    int(snapshot.album_art_size_bytes or 0),
                    main_artist_id,
                    snapshot.buma_work_number,
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
                INSERT INTO Tracks (
                    isrc, isrc_compact,
                    audio_file_path, audio_file_mime_type, audio_file_size_bytes,
                    track_title, catalog_number,
                    album_art_path, album_art_mime_type, album_art_size_bytes,
                    main_artist_id, buma_work_number, album_id,
                    release_date, track_length_sec, iswc, upc, genre
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.isrc,
                    compact_isrc,
                    None,
                    None,
                    0,
                    payload.track_title.strip(),
                    payload.catalog_number,
                    None,
                    None,
                    0,
                    main_artist_id,
                    payload.buma_work_number,
                    album_id,
                    payload.release_date,
                    int(payload.track_length_sec or 0),
                    payload.iswc,
                    payload.upc,
                    payload.genre,
                ),
            )
            track_id = int(cur.lastrowid)
            if payload.audio_file_source_path:
                self.set_media_path(track_id, "audio_file", payload.audio_file_source_path, cursor=cur)
            if payload.album_art_source_path:
                self.set_media_path(track_id, "album_art", payload.album_art_source_path, cursor=cur)
            self.replace_additional_artists(track_id, payload.additional_artists, cursor=cur)
            return track_id

    def update_track(self, payload: TrackUpdatePayload) -> None:
        with self.conn:
            cur = self.conn.cursor()
            main_artist_id = self.get_or_create_artist(payload.artist_name, cursor=cur)
            album_id = self.get_or_create_album(payload.album_title, cursor=cur)
            compact_isrc = to_compact_isrc(payload.isrc)
            current_audio = self.get_media_meta(payload.track_id, "audio_file", cursor=cur)
            current_art = self.get_media_meta(payload.track_id, "album_art", cursor=cur)
            audio_path = current_audio["path"] or None
            audio_mime = current_audio["mime_type"] or None
            audio_size = int(current_audio["size_bytes"] or 0)
            album_art_path = current_art["path"] or None
            album_art_mime = current_art["mime_type"] or None
            album_art_size = int(current_art["size_bytes"] or 0)

            if payload.clear_audio_file:
                audio_path = None
                audio_mime = None
                audio_size = 0
            elif payload.audio_file_source_path:
                audio_meta = self.set_media_path(payload.track_id, "audio_file", payload.audio_file_source_path, cursor=cur)
                audio_path = str(audio_meta["path"] or "") or None
                audio_mime = str(audio_meta["mime_type"] or "") or None
                audio_size = int(audio_meta["size_bytes"] or 0)

            if payload.clear_album_art:
                album_art_path = None
                album_art_mime = None
                album_art_size = 0
            elif payload.album_art_source_path:
                art_meta = self.set_media_path(payload.track_id, "album_art", payload.album_art_source_path, cursor=cur)
                album_art_path = str(art_meta["path"] or "") or None
                album_art_mime = str(art_meta["mime_type"] or "") or None
                album_art_size = int(art_meta["size_bytes"] or 0)

            cur.execute(
                """
                UPDATE Tracks SET
                    isrc=?, isrc_compact=?,
                    audio_file_path=?, audio_file_mime_type=?, audio_file_size_bytes=?,
                    track_title=?, catalog_number=?,
                    album_art_path=?, album_art_mime_type=?, album_art_size_bytes=?,
                    main_artist_id=?, buma_work_number=?, album_id=?, release_date=?,
                    track_length_sec=?, iswc=?, upc=?, genre=?
                WHERE id=?
                """,
                (
                    payload.isrc,
                    compact_isrc,
                    audio_path,
                    audio_mime,
                    int(audio_size),
                    payload.track_title.strip(),
                    payload.catalog_number,
                    album_art_path,
                    album_art_mime,
                    int(album_art_size),
                    main_artist_id,
                    payload.buma_work_number,
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

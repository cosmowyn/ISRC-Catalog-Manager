"""Track mutation services used by the UI layer."""

from __future__ import annotations

import mimetypes
import sqlite3
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from isrc_manager.domain.codes import is_blank, to_compact_isrc
from isrc_manager.domain.standard_fields import standard_media_specs_by_key
from isrc_manager.media.blob_files import _is_valid_audio_path, _is_valid_image_path


def _build_media_fields() -> dict[str, dict[str, object]]:
    validators = {
        "blob_audio": _is_valid_audio_path,
        "blob_image": _is_valid_image_path,
    }
    return {
        media_key: {
            "path_column": spec.path_column,
            "mime_column": spec.mime_column,
            "size_column": spec.size_column,
            "subdir": "audio" if spec.field_type == "blob_audio" else "images",
            "validator": validators[spec.field_type],
        }
        for media_key, spec in standard_media_specs_by_key().items()
    }


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
    composer: str | None = None
    publisher: str | None = None
    comments: str | None = None
    lyrics: str | None = None
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
    composer: str | None = None
    publisher: str | None = None
    comments: str | None = None
    lyrics: str | None = None
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
    composer: str | None
    publisher: str | None
    comments: str | None
    lyrics: str | None
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

    MEDIA_FIELDS = _build_media_fields()
    ALBUM_SHARED_FIELD_NAMES = frozenset(
        {
            "artist_name",
            "album_title",
            "release_date",
            "upc",
            "genre",
            "catalog_number",
        }
    )

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

    @staticmethod
    def _normalize_media_meta(
        path_value: str | None,
        mime_type: str | None,
        size_bytes: int | None,
        **extra: object,
    ) -> dict[str, str | int | bool | object]:
        clean_path = str(path_value or "").strip()
        payload: dict[str, str | int | bool | object] = {
            "has_media": bool(clean_path),
            "path": clean_path,
            "mime_type": str(mime_type or "").strip(),
            "size_bytes": int(size_bytes or 0),
        }
        payload.update(extra)
        return payload

    def _fetch_album_context(
        self,
        track_id: int,
        *,
        cursor: sqlite3.Cursor | None = None,
    ) -> tuple[int | None, str]:
        cur = cursor or self.conn.cursor()
        row = cur.execute(
            """
            SELECT t.album_id, COALESCE(al.title, '')
            FROM Tracks t
            LEFT JOIN Albums al ON al.id = t.album_id
            WHERE t.id=?
            """,
            (int(track_id),),
        ).fetchone()
        if not row:
            return None, ""
        album_id = int(row[0]) if row[0] is not None else None
        return album_id, str(row[1] or "")

    @staticmethod
    def _album_supports_shared_art(album_id: int | None, album_title: str | None) -> bool:
        clean_title = str(album_title or "").strip()
        return album_id is not None and not is_blank(clean_title) and clean_title.casefold() != "single"

    def _get_track_row_media_meta(
        self,
        track_id: int,
        media_key: str,
        *,
        cursor: sqlite3.Cursor | None = None,
    ) -> dict[str, str | int | bool | object]:
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
            return self._normalize_media_meta("", "", 0, owner_scope="track", owner_id=int(track_id))
        return self._normalize_media_meta(
            row[0],
            row[1],
            row[2],
            owner_scope="track",
            owner_id=int(track_id),
        )

    def _get_album_art_meta(
        self,
        album_id: int,
        *,
        cursor: sqlite3.Cursor | None = None,
    ) -> dict[str, str | int | bool | object]:
        cur = cursor or self.conn.cursor()
        row = cur.execute(
            """
            SELECT album_art_path, album_art_mime_type, album_art_size_bytes
            FROM Albums
            WHERE id=?
            """,
            (int(album_id),),
        ).fetchone()
        if not row:
            return self._normalize_media_meta("", "", 0, owner_scope="album", owner_id=int(album_id))
        return self._normalize_media_meta(
            row[0],
            row[1],
            row[2],
            owner_scope="album",
            owner_id=int(album_id),
        )

    def _get_album_track_art_fallback(
        self,
        album_id: int,
        *,
        cursor: sqlite3.Cursor | None = None,
    ) -> dict[str, str | int | bool | object]:
        cur = cursor or self.conn.cursor()
        row = cur.execute(
            """
            SELECT id, album_art_path, album_art_mime_type, album_art_size_bytes
            FROM Tracks
            WHERE album_id=?
              AND album_art_path IS NOT NULL
              AND album_art_path != ''
            ORDER BY id
            LIMIT 1
            """,
            (int(album_id),),
        ).fetchone()
        if not row:
            return self._normalize_media_meta("", "", 0, owner_scope="album_track", owner_id=None, album_id=int(album_id))
        return self._normalize_media_meta(
            row[1],
            row[2],
            row[3],
            owner_scope="album_track",
            owner_id=int(row[0]),
            album_id=int(album_id),
        )

    def _update_track_media_reference(
        self,
        track_id: int,
        media_key: str,
        *,
        stored_path: str | None,
        mime_type: str | None,
        size_bytes: int,
        cursor: sqlite3.Cursor,
    ) -> None:
        config = self.MEDIA_FIELDS[media_key]
        cursor.execute(
            f"""
            UPDATE Tracks
            SET {config['path_column']}=?, {config['mime_column']}=?, {config['size_column']}=?
            WHERE id=?
            """,
            (
                str(stored_path or "").strip() or None,
                str(mime_type or "").strip() or None,
                int(size_bytes or 0),
                int(track_id),
            ),
        )

    def _update_album_art_reference(
        self,
        album_id: int,
        *,
        stored_path: str | None,
        mime_type: str | None,
        size_bytes: int,
        cursor: sqlite3.Cursor,
    ) -> None:
        cursor.execute(
            """
            UPDATE Albums
            SET album_art_path=?, album_art_mime_type=?, album_art_size_bytes=?
            WHERE id=?
            """,
            (
                str(stored_path or "").strip() or None,
                str(mime_type or "").strip() or None,
                int(size_bytes or 0),
                int(album_id),
            ),
        )

    def _clear_album_track_art_references(
        self,
        album_id: int,
        *,
        cursor: sqlite3.Cursor,
    ) -> None:
        cursor.execute(
            """
            UPDATE Tracks
            SET album_art_path=NULL, album_art_mime_type=NULL, album_art_size_bytes=0
            WHERE album_id=?
            """,
            (int(album_id),),
        )

    def _collect_album_art_paths_for_album(
        self,
        album_id: int,
        *,
        cursor: sqlite3.Cursor | None = None,
    ) -> list[str]:
        cur = cursor or self.conn.cursor()
        paths: list[str] = []
        album_row = cur.execute(
            "SELECT album_art_path FROM Albums WHERE id=?",
            (int(album_id),),
        ).fetchone()
        if album_row and album_row[0]:
            paths.append(str(album_row[0]))
        track_rows = cur.execute(
            """
            SELECT album_art_path
            FROM Tracks
            WHERE album_id=?
              AND album_art_path IS NOT NULL
              AND album_art_path != ''
            """,
            (int(album_id),),
        ).fetchall()
        paths.extend(str(path) for (path,) in track_rows if path)
        return paths

    def _write_media_file(
        self,
        media_key: str,
        source_path: str | Path,
    ) -> tuple[str, str, int]:
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
        return rel_path, mime_type, int(size_bytes)

    def _is_managed_media_path(self, stored_path: str) -> bool:
        clean_path = str(stored_path or "").strip()
        if not clean_path or self.media_root is None or self.data_root is None:
            return False
        if Path(clean_path).is_absolute():
            return False
        resolved = (self.data_root / clean_path).resolve()
        media_root = self.media_root.resolve()
        try:
            resolved.relative_to(media_root)
            return True
        except ValueError:
            return False

    def _delete_unreferenced_media_files(
        self,
        stored_paths: Iterable[str | None],
        *,
        cursor: sqlite3.Cursor,
    ) -> None:
        seen: set[str] = set()
        for stored_path in stored_paths:
            clean_path = str(stored_path or "").strip()
            if not clean_path or clean_path in seen:
                continue
            seen.add(clean_path)
            still_track_ref = cursor.execute(
                """
                SELECT 1
                FROM Tracks
                WHERE audio_file_path=? OR album_art_path=?
                LIMIT 1
                """,
                (clean_path, clean_path),
            ).fetchone()
            if still_track_ref:
                continue
            still_album_ref = cursor.execute(
                "SELECT 1 FROM Albums WHERE album_art_path=? LIMIT 1",
                (clean_path,),
            ).fetchone()
            if still_album_ref:
                continue
            if not self._is_managed_media_path(clean_path):
                continue
            resolved = self.resolve_media_path(clean_path)
            if resolved is None:
                continue
            try:
                resolved.unlink(missing_ok=True)
            except Exception:
                pass

    def get_media_meta(
        self,
        track_id: int,
        media_key: str,
        *,
        cursor: sqlite3.Cursor | None = None,
    ) -> dict[str, str | int | bool]:
        cur = cursor or self.conn.cursor()
        if media_key == "album_art":
            album_id, album_title = self._fetch_album_context(track_id, cursor=cur)
            if self._album_supports_shared_art(album_id, album_title):
                shared_meta = self._get_album_art_meta(int(album_id), cursor=cur)
                if bool(shared_meta.get("has_media")):
                    return shared_meta
                fallback_meta = self._get_album_track_art_fallback(int(album_id), cursor=cur)
                if bool(fallback_meta.get("has_media")):
                    return fallback_meta
        return self._get_track_row_media_meta(track_id, media_key, cursor=cur)

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
        cur = cursor or self.conn.cursor()

        if media_key == "album_art":
            album_id, album_title = self._fetch_album_context(track_id, cursor=cur)
            if self._album_supports_shared_art(album_id, album_title):
                current_shared_meta = self._get_album_art_meta(int(album_id), cursor=cur)
                current_shared_path = str(current_shared_meta.get("path") or "")
                if current_shared_path:
                    current_resolved = self.resolve_media_path(current_shared_path)
                    source = Path(source_path)
                    if current_resolved is not None and current_resolved.exists():
                        try:
                            if current_resolved.read_bytes() == source.read_bytes():
                                self._clear_album_track_art_references(int(album_id), cursor=cur)
                                return self._normalize_media_meta(
                                    current_shared_path,
                                    str(current_shared_meta.get("mime_type") or ""),
                                    int(current_shared_meta.get("size_bytes") or 0),
                                    owner_scope="album",
                                    owner_id=int(album_id),
                                )
                        except Exception:
                            pass
                rel_path, mime_type, size_bytes = self._write_media_file(media_key, source_path)
                stale_paths = self._collect_album_art_paths_for_album(int(album_id), cursor=cur)
                self._update_album_art_reference(
                    int(album_id),
                    stored_path=rel_path,
                    mime_type=mime_type,
                    size_bytes=size_bytes,
                    cursor=cur,
                )
                self._clear_album_track_art_references(int(album_id), cursor=cur)
                self._delete_unreferenced_media_files(stale_paths, cursor=cur)
                return self._normalize_media_meta(
                    rel_path,
                    mime_type,
                    size_bytes,
                    owner_scope="album",
                    owner_id=int(album_id),
                )

        rel_path, mime_type, size_bytes = self._write_media_file(media_key, source_path)
        stale_meta = self._get_track_row_media_meta(track_id, media_key, cursor=cur)
        self._update_track_media_reference(
            track_id,
            media_key,
            stored_path=rel_path,
            mime_type=mime_type,
            size_bytes=size_bytes,
            cursor=cur,
        )
        self._delete_unreferenced_media_files([str(stale_meta.get("path") or "")], cursor=cur)
        return self._normalize_media_meta(
            rel_path,
            mime_type,
            size_bytes,
            owner_scope="track",
            owner_id=int(track_id),
        )

    def clear_media(self, track_id: int, media_key: str, *, cursor: sqlite3.Cursor | None = None) -> None:
        cur = cursor or self.conn.cursor()
        if media_key == "album_art":
            album_id, album_title = self._fetch_album_context(track_id, cursor=cur)
            if self._album_supports_shared_art(album_id, album_title):
                stale_paths = self._collect_album_art_paths_for_album(int(album_id), cursor=cur)
                self._update_album_art_reference(
                    int(album_id),
                    stored_path=None,
                    mime_type=None,
                    size_bytes=0,
                    cursor=cur,
                )
                self._clear_album_track_art_references(int(album_id), cursor=cur)
                self._delete_unreferenced_media_files(stale_paths, cursor=cur)
                return

        stale_meta = self._get_track_row_media_meta(track_id, media_key, cursor=cur)
        self._update_track_media_reference(
            track_id,
            media_key,
            stored_path=None,
            mime_type=None,
            size_bytes=0,
            cursor=cur,
        )
        self._delete_unreferenced_media_files([str(stale_meta.get("path") or "")], cursor=cur)

    def fetch_track_title(self, track_id: int, *, cursor: sqlite3.Cursor | None = None) -> str:
        cur = cursor or self.conn.cursor()
        row = cur.execute("SELECT track_title FROM Tracks WHERE id=?", (track_id,)).fetchone()
        if row and row[0]:
            return str(row[0])
        return f"track_{track_id}"

    def list_album_group_track_ids(self, track_id: int, *, cursor: sqlite3.Cursor | None = None) -> list[int]:
        cur = cursor or self.conn.cursor()
        row = cur.execute(
            """
            SELECT t.album_id, COALESCE(al.title, '')
            FROM Tracks t
            LEFT JOIN Albums al ON al.id = t.album_id
            WHERE t.id=?
            """,
            (int(track_id),),
        ).fetchone()
        if not row:
            return []

        album_id = row[0]
        album_title = (row[1] or "").strip()
        if album_id is None or is_blank(album_title) or album_title.casefold() == "single":
            return []

        rows = cur.execute(
            "SELECT id FROM Tracks WHERE album_id=? ORDER BY id",
            (int(album_id),),
        ).fetchall()
        return [int(group_track_id) for (group_track_id,) in rows]

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
                t.genre,
                t.composer,
                t.publisher,
                t.comments,
                t.lyrics
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
        album_art_meta = self.get_media_meta(track_id, "album_art", cursor=cur)

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
            composer=row[19],
            publisher=row[20],
            comments=row[21],
            lyrics=row[22],
            catalog_number=row[7],
            buma_work_number=row[12],
            audio_file_path=row[3],
            audio_file_mime_type=row[4],
            audio_file_size_bytes=int(row[5] or 0),
            album_art_path=str(album_art_meta.get("path") or "") or None,
            album_art_mime_type=str(album_art_meta.get("mime_type") or "") or None,
            album_art_size_bytes=int(album_art_meta.get("size_bytes") or 0),
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
                    genre=?,
                    composer=?,
                    publisher=?,
                    comments=?,
                    lyrics=?
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
                    snapshot.composer,
                    snapshot.publisher,
                    snapshot.comments,
                    snapshot.lyrics,
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
                    release_date, track_length_sec, iswc, upc, genre,
                    composer, publisher, comments, lyrics
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    snapshot.composer,
                    snapshot.publisher,
                    snapshot.comments,
                    snapshot.lyrics,
                ),
            )
        if self._album_supports_shared_art(album_id, snapshot.album_title):
            self._update_album_art_reference(
                int(album_id),
                stored_path=snapshot.album_art_path,
                mime_type=snapshot.album_art_mime_type,
                size_bytes=int(snapshot.album_art_size_bytes or 0),
                cursor=cur,
            )
            self._update_track_media_reference(
                snapshot.track_id,
                "album_art",
                stored_path=None,
                mime_type=None,
                size_bytes=0,
                cursor=cur,
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
            stale_paths = [
                path
                for (path,) in cur.execute(
                    """
                    SELECT album_art_path
                    FROM Albums
                    WHERE title=?
                      AND id NOT IN (SELECT album_id FROM Tracks WHERE album_id IS NOT NULL)
                      AND album_art_path IS NOT NULL
                      AND album_art_path != ''
                    """,
                    (title,),
                ).fetchall()
                if path
            ]
            cur.execute(
                """
                DELETE FROM Albums
                WHERE title=?
                  AND id NOT IN (SELECT album_id FROM Tracks WHERE album_id IS NOT NULL)
                """,
                (title,),
            )
            self._delete_unreferenced_media_files(stale_paths, cursor=cur)

    def create_track(self, payload: TrackCreatePayload) -> int:
        with self.conn:
            cur = self.conn.cursor()
            main_artist_id = self.get_or_create_artist(payload.artist_name, cursor=cur)
            album_id = self.get_or_create_album(payload.album_title, cursor=cur)
            clean_isrc = str(payload.isrc or "").strip()
            compact_isrc = to_compact_isrc(clean_isrc)
            cur.execute(
                """
                INSERT INTO Tracks (
                    isrc, isrc_compact,
                    audio_file_path, audio_file_mime_type, audio_file_size_bytes,
                    track_title, catalog_number,
                    album_art_path, album_art_mime_type, album_art_size_bytes,
                    main_artist_id, buma_work_number, album_id,
                    release_date, track_length_sec, iswc, upc, genre,
                    composer, publisher, comments, lyrics
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    clean_isrc,
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
                    payload.composer,
                    payload.publisher,
                    payload.comments,
                    payload.lyrics,
                ),
            )
            track_id = int(cur.lastrowid)
            if payload.audio_file_source_path:
                self.set_media_path(track_id, "audio_file", payload.audio_file_source_path, cursor=cur)
            if payload.album_art_source_path:
                self.set_media_path(track_id, "album_art", payload.album_art_source_path, cursor=cur)
            self.replace_additional_artists(track_id, payload.additional_artists, cursor=cur)
            return track_id

    def _update_track_row(self, payload: TrackUpdatePayload, *, cursor: sqlite3.Cursor) -> None:
        main_artist_id = self.get_or_create_artist(payload.artist_name, cursor=cursor)
        album_id = self.get_or_create_album(payload.album_title, cursor=cursor)
        clean_isrc = str(payload.isrc or "").strip()
        compact_isrc = to_compact_isrc(clean_isrc)
        current_audio = self._get_track_row_media_meta(payload.track_id, "audio_file", cursor=cursor)
        current_track_art = self._get_track_row_media_meta(payload.track_id, "album_art", cursor=cursor)
        current_effective_art = self.get_media_meta(payload.track_id, "album_art", cursor=cursor)
        shared_album_art = self._album_supports_shared_art(album_id, payload.album_title)

        cursor.execute(
            """
            UPDATE Tracks SET
                isrc=?, isrc_compact=?,
                audio_file_path=?, audio_file_mime_type=?, audio_file_size_bytes=?,
                track_title=?, catalog_number=?,
                album_art_path=?, album_art_mime_type=?, album_art_size_bytes=?,
                main_artist_id=?, buma_work_number=?, album_id=?, release_date=?,
                track_length_sec=?, iswc=?, upc=?, genre=?, composer=?, publisher=?, comments=?, lyrics=?
            WHERE id=?
            """,
            (
                clean_isrc,
                compact_isrc,
                str(current_audio.get("path") or "") or None,
                str(current_audio.get("mime_type") or "") or None,
                int(current_audio.get("size_bytes") or 0),
                payload.track_title.strip(),
                payload.catalog_number,
                (
                    None
                    if shared_album_art
                    else (str(current_track_art.get("path") or "") or None)
                ),
                (
                    None
                    if shared_album_art
                    else (str(current_track_art.get("mime_type") or "") or None)
                ),
                0 if shared_album_art else int(current_track_art.get("size_bytes") or 0),
                main_artist_id,
                payload.buma_work_number,
                album_id,
                payload.release_date,
                int(payload.track_length_sec or 0),
                payload.iswc,
                payload.upc,
                payload.genre,
                payload.composer,
                payload.publisher,
                payload.comments,
                payload.lyrics,
                payload.track_id,
            ),
        )

        if payload.clear_audio_file:
            self.clear_media(payload.track_id, "audio_file", cursor=cursor)
        elif payload.audio_file_source_path:
            self.set_media_path(payload.track_id, "audio_file", payload.audio_file_source_path, cursor=cursor)

        if payload.clear_album_art:
            self.clear_media(payload.track_id, "album_art", cursor=cursor)
        elif payload.album_art_source_path:
            self.set_media_path(payload.track_id, "album_art", payload.album_art_source_path, cursor=cursor)
        elif shared_album_art:
            stale_track_art_path = str(current_track_art.get("path") or "")
            if stale_track_art_path:
                self._update_track_media_reference(
                    payload.track_id,
                    "album_art",
                    stored_path=None,
                    mime_type=None,
                    size_bytes=0,
                    cursor=cursor,
                )
                self._delete_unreferenced_media_files([stale_track_art_path], cursor=cursor)
        else:
            effective_art_path = str(current_effective_art.get("path") or "")
            if effective_art_path and effective_art_path != str(current_track_art.get("path") or ""):
                self._update_track_media_reference(
                    payload.track_id,
                    "album_art",
                    stored_path=effective_art_path,
                    mime_type=str(current_effective_art.get("mime_type") or "") or None,
                    size_bytes=int(current_effective_art.get("size_bytes") or 0),
                    cursor=cursor,
                )

        self.replace_additional_artists(payload.track_id, payload.additional_artists, cursor=cursor)

    def update_track(self, payload: TrackUpdatePayload, *, cursor: sqlite3.Cursor | None = None) -> None:
        if cursor is not None:
            self._update_track_row(payload, cursor=cursor)
            return

        with self.conn:
            cur = self.conn.cursor()
            self._update_track_row(payload, cursor=cur)

    def apply_album_metadata_to_tracks(
        self,
        track_ids: Iterable[int],
        *,
        field_updates: dict[str, object],
        album_art_source_path: str | None = None,
        clear_album_art: bool = False,
        cursor: sqlite3.Cursor | None = None,
    ) -> list[int]:
        normalized_track_ids: list[int] = []
        seen: set[int] = set()
        for track_id in track_ids:
            value = int(track_id)
            if value <= 0 or value in seen:
                continue
            seen.add(value)
            normalized_track_ids.append(value)

        if not normalized_track_ids:
            return []

        invalid_fields = sorted(set(field_updates) - set(self.ALBUM_SHARED_FIELD_NAMES))
        if invalid_fields:
            raise ValueError(f"Unsupported album metadata field(s): {', '.join(invalid_fields)}")

        apply_album_art = bool(album_art_source_path or clear_album_art)

        def _apply(cur: sqlite3.Cursor) -> list[int]:
            updated_track_ids: list[int] = []
            for track_id in normalized_track_ids:
                snapshot = self.fetch_track_snapshot(track_id, cursor=cur)
                if snapshot is None:
                    raise ValueError(f"Track {track_id} not found")
                self._update_track_row(
                    TrackUpdatePayload(
                        track_id=snapshot.track_id,
                        isrc=snapshot.isrc,
                        track_title=snapshot.track_title,
                        artist_name=(
                            str(field_updates["artist_name"]).strip()
                            if "artist_name" in field_updates
                            else snapshot.artist_name
                        ),
                        additional_artists=list(snapshot.additional_artists),
                        album_title=(
                            field_updates["album_title"]
                            if "album_title" in field_updates
                            else snapshot.album_title
                        ),
                        release_date=(
                            field_updates["release_date"]
                            if "release_date" in field_updates
                            else snapshot.release_date
                        ),
                        track_length_sec=int(snapshot.track_length_sec or 0),
                        iswc=snapshot.iswc,
                        upc=field_updates["upc"] if "upc" in field_updates else snapshot.upc,
                        genre=field_updates["genre"] if "genre" in field_updates else snapshot.genre,
                        catalog_number=(
                            field_updates["catalog_number"]
                            if "catalog_number" in field_updates
                            else snapshot.catalog_number
                        ),
                        buma_work_number=snapshot.buma_work_number,
                        composer=snapshot.composer,
                        publisher=snapshot.publisher,
                        comments=snapshot.comments,
                        lyrics=snapshot.lyrics,
                        album_art_source_path=album_art_source_path if apply_album_art and not clear_album_art else None,
                        clear_album_art=bool(apply_album_art and clear_album_art and not album_art_source_path),
                    ),
                    cursor=cur,
                )
                updated_track_ids.append(track_id)
            return updated_track_ids

        if cursor is not None:
            return _apply(cursor)

        with self.conn:
            cur = self.conn.cursor()
            return _apply(cur)

    def delete_track(self, track_id: int) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM Tracks WHERE id=?", (track_id,))

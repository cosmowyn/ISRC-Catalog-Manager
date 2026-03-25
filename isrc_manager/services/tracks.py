"""Track mutation services used by the UI layer."""

from __future__ import annotations

import base64
import hashlib
import mimetypes
import sqlite3
import tempfile
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from isrc_manager.domain.codes import is_blank, to_compact_isrc
from isrc_manager.domain.standard_fields import standard_media_specs_by_key
from isrc_manager.file_storage import (
    STORAGE_MODE_DATABASE,
    STORAGE_MODE_MANAGED_FILE,
    ManagedFileStorage,
    bytes_from_blob,
    coalesce_filename,
    infer_storage_mode,
    normalize_storage_mode,
)
from isrc_manager.media.audio_formats import classify_audio_format
from isrc_manager.media.blob_files import (
    _is_valid_audio_path,
    _is_valid_image_path,
    _read_blob_from_path,
)

TRACK_RELATIONSHIP_TYPES = frozenset(
    {
        "original",
        "version",
        "remix",
        "edit",
        "live",
        "instrumental",
        "alternate_master",
        "derivative",
        "other",
    }
)


def _build_media_fields() -> dict[str, dict[str, object]]:
    validators = {
        "blob_audio": _is_valid_audio_path,
        "blob_image": _is_valid_image_path,
    }
    return {
        media_key: {
            "path_column": spec.path_column,
            "storage_mode_column": spec.path_column.replace("_path", "_storage_mode"),
            "blob_column": spec.path_column.replace("_path", "_blob"),
            "filename_column": spec.path_column.replace("_path", "_filename"),
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
    work_id: int | None = None
    parent_track_id: int | None = None
    relationship_type: str | None = None
    audio_file_source_path: str | None = None
    audio_file_storage_mode: str | None = None
    album_art_source_path: str | None = None
    album_art_storage_mode: str | None = None


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
    work_id: int | None = None
    parent_track_id: int | None = None
    relationship_type: str | None = None
    audio_file_source_path: str | None = None
    audio_file_storage_mode: str | None = None
    album_art_source_path: str | None = None
    album_art_storage_mode: str | None = None
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
    work_id: int | None = None
    parent_track_id: int | None = None
    relationship_type: str | None = "original"
    audio_file_path: str | None = None
    audio_file_storage_mode: str | None = None
    audio_file_filename: str | None = None
    audio_file_blob_b64: str | None = None
    audio_file_mime_type: str | None = None
    audio_file_size_bytes: int = 0
    album_art_path: str | None = None
    album_art_storage_mode: str | None = None
    album_art_filename: str | None = None
    album_art_blob_b64: str | None = None
    album_art_mime_type: str | None = None
    album_art_size_bytes: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class AlbumArtEditState:
    track_id: int
    album_id: int | None
    album_title: str | None
    has_effective_art: bool
    owner_scope: str | None
    owner_track_id: int | None
    owner_track_title: str | None
    is_shared_reference: bool
    can_replace_directly: bool


@dataclass(slots=True)
class TrackMediaSourceHandle:
    track_id: int
    media_key: str
    filename: str
    suffix: str
    mime_type: str | None
    size_bytes: int
    storage_mode: str | None
    source_path: Path | None
    source_bytes: bytes | None
    owner_scope: str | None
    owner_id: int | None

    def sha256_hex(self) -> str:
        if self.source_bytes is not None:
            return hashlib.sha256(self.source_bytes).hexdigest()
        if self.source_path is None or not self.source_path.exists():
            raise FileNotFoundError(self.filename or self.media_key)
        digest = hashlib.sha256()
        with self.source_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @contextmanager
    def materialize_path(self):
        if self.source_path is not None and self.source_path.exists():
            yield self.source_path
            return
        suffix = self.suffix or Path(self.filename or "").suffix or ""
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
                handle.write(bytes(self.source_bytes or b""))
                temp_path = Path(handle.name)
            yield temp_path
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except Exception:
                    pass


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
        self.media_store = ManagedFileStorage(data_root=data_root, relative_root="track_media")
        self._ensure_storage_columns()

    def _ensure_storage_columns(self) -> None:
        table_names = {
            str(row[0])
            for row in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            if row and row[0]
        }
        track_columns = (
            {
                str(row[1])
                for row in self.conn.execute("PRAGMA table_info(Tracks)").fetchall()
                if row and row[1]
            }
            if "Tracks" in table_names
            else set()
        )
        album_columns = (
            {
                str(row[1])
                for row in self.conn.execute("PRAGMA table_info(Albums)").fetchall()
                if row and row[1]
            }
            if "Albums" in table_names
            else set()
        )
        track_additions = (
            ("audio_file_storage_mode", "TEXT"),
            ("audio_file_blob", "BLOB"),
            ("audio_file_filename", "TEXT"),
            ("album_art_storage_mode", "TEXT"),
            ("album_art_blob", "BLOB"),
            ("album_art_filename", "TEXT"),
        )
        album_additions = (
            ("album_art_storage_mode", "TEXT"),
            ("album_art_blob", "BLOB"),
            ("album_art_filename", "TEXT"),
        )
        with self.conn:
            if "Tracks" in table_names:
                for column_name, column_sql in track_additions:
                    if column_name not in track_columns:
                        self.conn.execute(
                            f"ALTER TABLE Tracks ADD COLUMN {column_name} {column_sql}"
                        )
            if "Albums" in table_names:
                for column_name, column_sql in album_additions:
                    if column_name not in album_columns:
                        self.conn.execute(
                            f"ALTER TABLE Albums ADD COLUMN {column_name} {column_sql}"
                        )

    def _table_names(self) -> set[str]:
        return {
            str(row[0])
            for row in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            if row and row[0]
        }

    def _track_columns(self) -> set[str]:
        if "Tracks" not in self._table_names():
            return set()
        return {
            str(row[1])
            for row in self.conn.execute("PRAGMA table_info(Tracks)").fetchall()
            if row and row[1]
        }

    @staticmethod
    def _normalize_relationship_type(value: str | None) -> str:
        clean = str(value or "").strip().lower().replace(" ", "_")
        if clean in TRACK_RELATIONSHIP_TYPES:
            return clean
        return "original"

    def _current_track_governance(
        self, track_id: int, *, cursor: sqlite3.Cursor
    ) -> tuple[int | None, int | None, str]:
        track_columns = self._track_columns()
        if not track_columns:
            return None, None, "original"
        work_expr = "work_id" if "work_id" in track_columns else "NULL"
        parent_expr = "parent_track_id" if "parent_track_id" in track_columns else "NULL"
        relationship_expr = (
            "relationship_type" if "relationship_type" in track_columns else "'original'"
        )
        row = cursor.execute(
            f"""
            SELECT {work_expr}, {parent_expr}, {relationship_expr}
            FROM Tracks
            WHERE id=?
            """,
            (int(track_id),),
        ).fetchone()
        if row is None:
            return None, None, "original"
        return (
            int(row[0]) if row[0] is not None else None,
            int(row[1]) if row[1] is not None else None,
            self._normalize_relationship_type(row[2]),
        )

    def _rebalance_work_track_primary(self, work_id: int, *, cursor: sqlite3.Cursor) -> None:
        primary_row = cursor.execute(
            """
            SELECT track_id
            FROM WorkTrackLinks
            WHERE work_id=?
            ORDER BY is_primary DESC, track_id
            LIMIT 1
            """,
            (int(work_id),),
        ).fetchone()
        cursor.execute("UPDATE WorkTrackLinks SET is_primary=0 WHERE work_id=?", (int(work_id),))
        if primary_row is not None:
            cursor.execute(
                """
                UPDATE WorkTrackLinks
                SET is_primary=1
                WHERE work_id=? AND track_id=?
                """,
                (int(work_id), int(primary_row[0])),
            )

    def _sync_shadow_work_link(
        self,
        track_id: int,
        work_id: int | None,
        *,
        cursor: sqlite3.Cursor,
    ) -> None:
        table_names = self._table_names()
        if "WorkTrackLinks" not in table_names:
            return
        existing_work_rows = cursor.execute(
            "SELECT work_id FROM WorkTrackLinks WHERE track_id=?",
            (int(track_id),),
        ).fetchall()
        affected_work_ids = {
            int(row[0]) for row in existing_work_rows if row and row[0] is not None
        }
        if work_id is not None:
            affected_work_ids.add(int(work_id))
        cursor.execute("DELETE FROM WorkTrackLinks WHERE track_id=?", (int(track_id),))
        if work_id is not None:
            cursor.execute(
                """
                INSERT INTO WorkTrackLinks(work_id, track_id, is_primary)
                VALUES (?, ?, 0)
                """,
                (int(work_id), int(track_id)),
            )
        for affected_work_id in sorted(affected_work_ids):
            self._rebalance_work_track_primary(affected_work_id, cursor=cursor)

    @staticmethod
    def parse_additional_artists(text: str) -> list[str]:
        parts = [part.strip() for part in (text or "").split(",")]
        return [part for part in parts if part]

    def get_or_create_artist(self, name: str, *, cursor: sqlite3.Cursor | None = None) -> int:
        name = (name or "").strip()
        if is_blank(name):
            raise ValueError("Artist name is required")
        cur = cursor or self.conn.cursor()
        row = cur.execute(
            "SELECT id FROM Artists WHERE name=? ORDER BY id LIMIT 1", (name,)
        ).fetchone()
        if row:
            return int(row[0])
        cur.execute("INSERT INTO Artists (name) VALUES (?)", (name,))
        return int(cur.lastrowid)

    def get_or_create_album(
        self, title: str | None, *, cursor: sqlite3.Cursor | None = None
    ) -> int | None:
        title = (title or "").strip()
        if is_blank(title):
            return None
        cur = cursor or self.conn.cursor()
        row = cur.execute(
            "SELECT id FROM Albums WHERE title=? ORDER BY id LIMIT 1", (title,)
        ).fetchone()
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
            row = cur.execute(
                "SELECT 1 FROM Tracks WHERE isrc_compact = ? LIMIT 1", (norm,)
            ).fetchone()
        else:
            row = cur.execute(
                "SELECT 1 FROM Tracks WHERE isrc_compact = ? AND id != ? LIMIT 1",
                (norm, exclude_track_id),
            ).fetchone()
        return bool(row)

    def resolve_media_path(self, stored_path: str | None) -> Path | None:
        return self.media_store.resolve(stored_path)

    @staticmethod
    def _encode_blob_b64(blob_value: bytes | None) -> str | None:
        if not blob_value:
            return None
        return base64.b64encode(blob_value).decode("ascii")

    @staticmethod
    def _decode_blob_b64(encoded_value: str | None) -> bytes | None:
        clean = str(encoded_value or "").strip()
        if not clean:
            return None
        return base64.b64decode(clean.encode("ascii"))

    @staticmethod
    def _normalize_media_meta(
        path_value: str | None,
        storage_mode: str | None,
        filename: str | None,
        mime_type: str | None,
        size_bytes: int | None,
        *,
        blob_present: bool = False,
        **extra: object,
    ) -> dict[str, str | int | bool | object]:
        clean_path = str(path_value or "").strip()
        clean_filename = str(filename or "").strip() or None
        clean_mime = str(mime_type or "").strip()
        clean_mode = infer_storage_mode(
            explicit_mode=storage_mode,
            stored_path=clean_path,
            blob_value=b"\x00" if blob_present else None,
        )
        audio_profile = classify_audio_format(
            clean_filename or clean_path or None,
            mime_type=clean_mime or None,
        )
        payload: dict[str, str | int | bool | object] = {
            "has_media": bool(clean_path or blob_present),
            "path": clean_path,
            "storage_mode": clean_mode,
            "filename": clean_filename,
            "mime_type": clean_mime,
            "size_bytes": int(size_bytes or 0),
            "blob_present": bool(blob_present),
            "format_id": audio_profile.id if audio_profile is not None else None,
            "format_label": audio_profile.label if audio_profile is not None else None,
            "is_lossy": bool(audio_profile.lossy) if audio_profile is not None else False,
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
        return (
            album_id is not None
            and not is_blank(clean_title)
            and clean_title.casefold() != "single"
        )

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
            SELECT
                {config['path_column']},
                {config['storage_mode_column']},
                {config['filename_column']},
                {config['mime_column']},
                {config['size_column']},
                CASE WHEN {config['blob_column']} IS NOT NULL THEN 1 ELSE 0 END
            FROM Tracks
            WHERE id=?
            """,
            (int(track_id),),
        ).fetchone()
        if not row:
            return self._normalize_media_meta(
                "",
                None,
                None,
                "",
                0,
                owner_scope="track",
                owner_id=int(track_id),
            )
        return self._normalize_media_meta(
            row[0],
            row[1],
            row[2],
            row[3],
            row[4],
            blob_present=bool(row[5]),
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
            SELECT
                album_art_path,
                album_art_storage_mode,
                album_art_filename,
                album_art_mime_type,
                album_art_size_bytes,
                CASE WHEN album_art_blob IS NOT NULL THEN 1 ELSE 0 END
            FROM Albums
            WHERE id=?
            """,
            (int(album_id),),
        ).fetchone()
        if not row:
            return self._normalize_media_meta(
                "",
                None,
                None,
                "",
                0,
                owner_scope="album",
                owner_id=int(album_id),
            )
        return self._normalize_media_meta(
            row[0],
            row[1],
            row[2],
            row[3],
            row[4],
            blob_present=bool(row[5]),
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
            SELECT
                id,
                album_art_path,
                album_art_storage_mode,
                album_art_filename,
                album_art_mime_type,
                album_art_size_bytes,
                CASE WHEN album_art_blob IS NOT NULL THEN 1 ELSE 0 END
            FROM Tracks
            WHERE album_id=?
              AND (
                  (album_art_path IS NOT NULL AND album_art_path != '')
                  OR album_art_blob IS NOT NULL
              )
            ORDER BY id
            LIMIT 1
            """,
            (int(album_id),),
        ).fetchone()
        if not row:
            return self._normalize_media_meta(
                "",
                None,
                None,
                "",
                0,
                owner_scope="album_track",
                owner_id=None,
                album_id=int(album_id),
            )
        return self._normalize_media_meta(
            row[1],
            row[2],
            row[3],
            row[4],
            row[5],
            blob_present=bool(row[6]),
            owner_scope="album_track",
            owner_id=int(row[0]),
            album_id=int(album_id),
        )

    def _fetch_track_row_media_blob(
        self,
        track_id: int,
        media_key: str,
        *,
        cursor: sqlite3.Cursor | None = None,
    ) -> bytes | None:
        config = self.MEDIA_FIELDS[media_key]
        cur = cursor or self.conn.cursor()
        row = cur.execute(
            f"SELECT {config['blob_column']} FROM Tracks WHERE id=?",
            (int(track_id),),
        ).fetchone()
        if not row or row[0] is None:
            return None
        return bytes_from_blob(row[0])

    def _fetch_album_art_blob(
        self,
        album_id: int,
        *,
        cursor: sqlite3.Cursor | None = None,
    ) -> bytes | None:
        cur = cursor or self.conn.cursor()
        row = cur.execute(
            "SELECT album_art_blob FROM Albums WHERE id=?",
            (int(album_id),),
        ).fetchone()
        if not row or row[0] is None:
            return None
        return bytes_from_blob(row[0])

    def _fetch_media_blob_for_meta(
        self,
        media_key: str,
        meta: dict[str, str | int | bool | object],
        *,
        cursor: sqlite3.Cursor | None = None,
    ) -> bytes | None:
        owner_scope = str(meta.get("owner_scope") or "")
        owner_id = meta.get("owner_id")
        if owner_id is None:
            return None
        if owner_scope == "album":
            return self._fetch_album_art_blob(int(owner_id), cursor=cursor)
        return self._fetch_track_row_media_blob(int(owner_id), media_key, cursor=cursor)

    def _read_media_bytes_for_meta(
        self,
        media_key: str,
        meta: dict[str, str | int | bool | object],
        *,
        cursor: sqlite3.Cursor | None = None,
    ) -> bytes | None:
        storage_mode = str(meta.get("storage_mode") or "")
        if storage_mode == STORAGE_MODE_DATABASE:
            return self._fetch_media_blob_for_meta(media_key, meta, cursor=cursor)
        resolved = self.resolve_media_path(str(meta.get("path") or ""))
        if resolved is None or not resolved.exists():
            return None
        return resolved.read_bytes()

    def _source_matches_media_meta(
        self,
        media_key: str,
        source_path: str | Path,
        meta: dict[str, str | int | bool | object],
        *,
        cursor: sqlite3.Cursor | None = None,
    ) -> bool:
        if not bool(meta.get("has_media")):
            return False
        source = Path(source_path)
        if not source.exists():
            return False
        current_bytes = self._read_media_bytes_for_meta(media_key, meta, cursor=cursor)
        if current_bytes is None:
            return False
        return current_bytes == source.read_bytes()

    def _build_media_storage_payload_from_source(
        self,
        media_key: str,
        source_path: str | Path,
        *,
        storage_mode: str | None = None,
    ) -> tuple[str | None, str, bytes | None, str, int]:
        config = self.MEDIA_FIELDS[media_key]
        source = Path(source_path)
        if not source.exists():
            raise FileNotFoundError(source)
        if not config["validator"](str(source)):
            raise ValueError(f"Selected file is not a valid {media_key.replace('_', ' ')}")
        clean_mode = normalize_storage_mode(storage_mode, default=STORAGE_MODE_MANAGED_FILE)
        filename = coalesce_filename(source.name, default_stem=media_key.replace("_", "-"))
        mime_type = mimetypes.guess_type(source.name)[0] or ""
        if clean_mode == STORAGE_MODE_DATABASE:
            blob_data = _read_blob_from_path(str(source))
            return None, filename, blob_data, mime_type, len(blob_data)
        if self.media_root is None or self.data_root is None:
            raise ValueError("Track media root is not configured")
        data = source.read_bytes()
        rel_path = self.media_store.write_bytes(
            data,
            filename=filename,
            subdir=config["subdir"],
        )
        return rel_path, filename, None, mime_type, len(data)

    def _build_media_storage_payload_from_bytes(
        self,
        media_key: str,
        data: bytes,
        *,
        filename: str | None,
        storage_mode: str,
        mime_type: str | None = None,
    ) -> tuple[str | None, str, bytes | None, str, int]:
        config = self.MEDIA_FIELDS[media_key]
        clean_mode = normalize_storage_mode(storage_mode)
        clean_filename = coalesce_filename(filename, default_stem=media_key.replace("_", "-"))
        resolved_mime = str(mime_type or mimetypes.guess_type(clean_filename)[0] or "").strip()
        if clean_mode == STORAGE_MODE_DATABASE:
            return None, clean_filename, data, resolved_mime, len(data)
        if self.media_root is None or self.data_root is None:
            raise ValueError("Track media root is not configured")
        rel_path = self.media_store.write_bytes(
            data,
            filename=clean_filename,
            subdir=config["subdir"],
        )
        return rel_path, clean_filename, None, resolved_mime, len(data)

    def _update_track_media_reference(
        self,
        track_id: int,
        media_key: str,
        *,
        stored_path: str | None,
        storage_mode: str | None,
        blob_data: bytes | None,
        filename: str | None,
        mime_type: str | None,
        size_bytes: int,
        cursor: sqlite3.Cursor,
    ) -> None:
        config = self.MEDIA_FIELDS[media_key]
        cursor.execute(
            f"""
            UPDATE Tracks
            SET {config['path_column']}=?,
                {config['storage_mode_column']}=?,
                {config['blob_column']}=?,
                {config['filename_column']}=?,
                {config['mime_column']}=?,
                {config['size_column']}=?
            WHERE id=?
            """,
            (
                str(stored_path or "").strip() or None,
                normalize_storage_mode(storage_mode, default=None),
                sqlite3.Binary(blob_data) if blob_data is not None else None,
                str(filename or "").strip() or None,
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
        storage_mode: str | None,
        blob_data: bytes | None,
        filename: str | None,
        mime_type: str | None,
        size_bytes: int,
        cursor: sqlite3.Cursor,
    ) -> None:
        cursor.execute(
            """
            UPDATE Albums
            SET album_art_path=?,
                album_art_storage_mode=?,
                album_art_blob=?,
                album_art_filename=?,
                album_art_mime_type=?,
                album_art_size_bytes=?
            WHERE id=?
            """,
            (
                str(stored_path or "").strip() or None,
                normalize_storage_mode(storage_mode, default=None),
                sqlite3.Binary(blob_data) if blob_data is not None else None,
                str(filename or "").strip() or None,
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
            SET album_art_path=NULL,
                album_art_storage_mode=NULL,
                album_art_blob=NULL,
                album_art_filename=NULL,
                album_art_mime_type=NULL,
                album_art_size_bytes=0
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

    def _is_managed_media_path(self, stored_path: str) -> bool:
        return self.media_store.is_managed(stored_path)

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

    @staticmethod
    def _format_album_art_owner_label(track_id: int | None, track_title: str | None) -> str:
        if track_id is None:
            return "another track"
        clean_title = str(track_title or "").strip()
        if clean_title:
            return f'Track #{int(track_id)} "{clean_title}"'
        return f"Track #{int(track_id)}"

    def _format_album_art_replacement_message(self, state: AlbumArtEditState) -> str:
        owner_label = self._format_album_art_owner_label(
            state.owner_track_id,
            state.owner_track_title,
        )
        return (
            f"Album art for this track is managed by {owner_label}. "
            "Edit that record to replace the shared image."
        )

    def _require_direct_album_art_edit(
        self,
        track_id: int,
        *,
        cursor: sqlite3.Cursor | None = None,
    ) -> AlbumArtEditState:
        state = self.describe_album_art_edit_state(track_id, cursor=cursor)
        if state.has_effective_art and not state.can_replace_directly:
            raise ValueError(self._format_album_art_replacement_message(state))
        return state

    def album_art_replacement_message(
        self,
        track_id: int,
        *,
        cursor: sqlite3.Cursor | None = None,
    ) -> str | None:
        state = self.describe_album_art_edit_state(track_id, cursor=cursor)
        if not state.has_effective_art or state.can_replace_directly:
            return None
        return self._format_album_art_replacement_message(state)

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

    def has_media(
        self, track_id: int, media_key: str, *, cursor: sqlite3.Cursor | None = None
    ) -> bool:
        return bool(self.get_media_meta(track_id, media_key, cursor=cursor).get("has_media"))

    def fetch_media_bytes(
        self,
        track_id: int,
        media_key: str,
        *,
        cursor: sqlite3.Cursor | None = None,
    ) -> tuple[bytes, str]:
        meta = self.get_media_meta(track_id, media_key, cursor=cursor)
        storage_mode = str(meta.get("storage_mode") or "")
        if storage_mode == STORAGE_MODE_DATABASE:
            blob_data = self._fetch_media_blob_for_meta(media_key, meta, cursor=cursor)
            if blob_data is None:
                raise FileNotFoundError(f"{media_key} for track {track_id}")
            return blob_data, str(meta.get("mime_type") or "")
        stored_path = str(meta.get("path") or "")
        resolved = self.resolve_media_path(stored_path)
        if not resolved or not resolved.exists():
            raise FileNotFoundError(stored_path or f"{media_key} for track {track_id}")
        return resolved.read_bytes(), str(meta.get("mime_type") or "")

    def resolve_media_source(
        self,
        track_id: int,
        media_key: str,
        *,
        cursor: sqlite3.Cursor | None = None,
    ) -> TrackMediaSourceHandle:
        meta = self.get_media_meta(track_id, media_key, cursor=cursor)
        if not bool(meta.get("has_media")):
            raise FileNotFoundError(f"{media_key} for track {track_id}")
        resolved_path = self.resolve_media_path(str(meta.get("path") or ""))
        source_path = (
            resolved_path if resolved_path is not None and resolved_path.exists() else None
        )
        source_bytes = None
        if source_path is None:
            source_bytes, _mime_type = self.fetch_media_bytes(track_id, media_key, cursor=cursor)
        filename = str(meta.get("filename") or "").strip()
        suffix = Path(filename or str(meta.get("path") or "")).suffix.lower()
        return TrackMediaSourceHandle(
            track_id=int(track_id),
            media_key=str(media_key or ""),
            filename=filename or f"track-{track_id}{suffix}",
            suffix=suffix,
            mime_type=str(meta.get("mime_type") or "").strip() or None,
            size_bytes=int(meta.get("size_bytes") or 0),
            storage_mode=str(meta.get("storage_mode") or "").strip() or None,
            source_path=source_path,
            source_bytes=source_bytes,
            owner_scope=str(meta.get("owner_scope") or "").strip() or None,
            owner_id=int(meta["owner_id"]) if meta.get("owner_id") is not None else None,
        )

    def set_media_path(
        self,
        track_id: int,
        media_key: str,
        source_path: str | Path,
        *,
        storage_mode: str | None = None,
        cursor: sqlite3.Cursor | None = None,
    ) -> dict[str, str | int | bool]:
        cur = cursor or self.conn.cursor()

        if media_key == "album_art":
            album_id, album_title = self._fetch_album_context(track_id, cursor=cur)
            if self._album_supports_shared_art(album_id, album_title):
                effective_meta = self.get_media_meta(track_id, media_key, cursor=cur)
                if self._source_matches_media_meta(
                    media_key,
                    source_path,
                    effective_meta,
                    cursor=cur,
                ):
                    if str(effective_meta.get("owner_scope") or "") == "album":
                        self._clear_album_track_art_references(int(album_id), cursor=cur)
                    return effective_meta
                self._require_direct_album_art_edit(track_id, cursor=cur)
                current_shared_meta = self._get_album_art_meta(int(album_id), cursor=cur)
                rel_path, filename, blob_data, mime_type, size_bytes = (
                    self._build_media_storage_payload_from_source(
                        media_key,
                        source_path,
                        storage_mode=storage_mode,
                    )
                )
                stale_paths = self._collect_album_art_paths_for_album(int(album_id), cursor=cur)
                self._update_album_art_reference(
                    int(album_id),
                    stored_path=rel_path,
                    storage_mode=storage_mode,
                    blob_data=blob_data,
                    filename=filename,
                    mime_type=mime_type,
                    size_bytes=size_bytes,
                    cursor=cur,
                )
                self._clear_album_track_art_references(int(album_id), cursor=cur)
                self._delete_unreferenced_media_files(stale_paths, cursor=cur)
                return self._normalize_media_meta(
                    rel_path,
                    storage_mode,
                    filename,
                    mime_type,
                    size_bytes,
                    blob_present=blob_data is not None,
                    owner_scope="album",
                    owner_id=int(album_id),
                )

        rel_path, filename, blob_data, mime_type, size_bytes = (
            self._build_media_storage_payload_from_source(
                media_key,
                source_path,
                storage_mode=storage_mode,
            )
        )
        stale_meta = self._get_track_row_media_meta(track_id, media_key, cursor=cur)
        self._update_track_media_reference(
            track_id,
            media_key,
            stored_path=rel_path,
            storage_mode=storage_mode,
            blob_data=blob_data,
            filename=filename,
            mime_type=mime_type,
            size_bytes=size_bytes,
            cursor=cur,
        )
        self._delete_unreferenced_media_files([str(stale_meta.get("path") or "")], cursor=cur)
        return self._normalize_media_meta(
            rel_path,
            storage_mode,
            filename,
            mime_type,
            size_bytes,
            blob_present=blob_data is not None,
            owner_scope="track",
            owner_id=int(track_id),
        )

    def clear_media(
        self, track_id: int, media_key: str, *, cursor: sqlite3.Cursor | None = None
    ) -> None:
        cur = cursor or self.conn.cursor()
        if media_key == "album_art":
            album_id, album_title = self._fetch_album_context(track_id, cursor=cur)
            if self._album_supports_shared_art(album_id, album_title):
                stale_paths = self._collect_album_art_paths_for_album(int(album_id), cursor=cur)
                self._update_album_art_reference(
                    int(album_id),
                    stored_path=None,
                    storage_mode=None,
                    blob_data=None,
                    filename=None,
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
            storage_mode=None,
            blob_data=None,
            filename=None,
            mime_type=None,
            size_bytes=0,
            cursor=cur,
        )
        self._delete_unreferenced_media_files([str(stale_meta.get("path") or "")], cursor=cur)

    def convert_media_storage_mode(
        self,
        track_id: int,
        media_key: str,
        target_mode: str,
        *,
        cursor: sqlite3.Cursor | None = None,
    ) -> dict[str, str | int | bool]:
        cur = cursor or self.conn.cursor()
        if media_key == "album_art":
            self._require_direct_album_art_edit(track_id, cursor=cur)
        meta = self.get_media_meta(track_id, media_key, cursor=cur)
        if not bool(meta.get("has_media")):
            raise FileNotFoundError(f"{media_key} for track {track_id}")
        clean_mode = normalize_storage_mode(target_mode)
        current_mode = normalize_storage_mode(str(meta.get("storage_mode") or ""), default=None)
        if current_mode == clean_mode:
            return meta

        data, mime_type = self.fetch_media_bytes(track_id, media_key, cursor=cur)
        rel_path, filename, blob_data, resolved_mime, size_bytes = (
            self._build_media_storage_payload_from_bytes(
                media_key,
                data,
                filename=str(meta.get("filename") or "") or None,
                storage_mode=clean_mode,
                mime_type=mime_type,
            )
        )
        stale_path = str(meta.get("path") or "")
        owner_scope = str(meta.get("owner_scope") or "")
        owner_id = meta.get("owner_id")
        if owner_scope == "album" and owner_id is not None:
            self._update_album_art_reference(
                int(owner_id),
                stored_path=rel_path,
                storage_mode=clean_mode,
                blob_data=blob_data,
                filename=filename,
                mime_type=resolved_mime,
                size_bytes=size_bytes,
                cursor=cur,
            )
        elif owner_id is not None:
            self._update_track_media_reference(
                int(owner_id),
                media_key,
                stored_path=rel_path,
                storage_mode=clean_mode,
                blob_data=blob_data,
                filename=filename,
                mime_type=resolved_mime,
                size_bytes=size_bytes,
                cursor=cur,
            )
        else:
            raise FileNotFoundError(f"{media_key} for track {track_id}")
        if stale_path and stale_path != str(rel_path or ""):
            self._delete_unreferenced_media_files([stale_path], cursor=cur)
        return self.get_media_meta(track_id, media_key, cursor=cur)

    def fetch_track_title(self, track_id: int, *, cursor: sqlite3.Cursor | None = None) -> str:
        cur = cursor or self.conn.cursor()
        row = cur.execute("SELECT track_title FROM Tracks WHERE id=?", (track_id,)).fetchone()
        if row and row[0]:
            return str(row[0])
        return f"track_{track_id}"

    def list_album_group_track_ids(
        self, track_id: int, *, cursor: sqlite3.Cursor | None = None
    ) -> list[int]:
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

    def describe_album_art_edit_state(
        self,
        track_id: int,
        *,
        cursor: sqlite3.Cursor | None = None,
    ) -> AlbumArtEditState:
        cur = cursor or self.conn.cursor()
        album_id, album_title_raw = self._fetch_album_context(track_id, cursor=cur)
        album_title = str(album_title_raw or "").strip() or None
        meta = self.get_media_meta(track_id, "album_art", cursor=cur)
        has_effective_art = bool(meta.get("has_media"))
        owner_scope = str(meta.get("owner_scope") or "").strip() or None
        owner_track_id: int | None = None
        is_shared_reference = False
        can_replace_directly = True

        if has_effective_art:
            if owner_scope == "track":
                owner_track_id = int(meta.get("owner_id") or track_id)
            elif owner_scope == "album_track":
                raw_owner_id = meta.get("owner_id")
                owner_track_id = int(raw_owner_id) if raw_owner_id is not None else None
            elif owner_scope == "album":
                album_group_track_ids = self.list_album_group_track_ids(track_id, cursor=cur)
                if len(album_group_track_ids) <= 1:
                    owner_track_id = (
                        int(album_group_track_ids[0]) if album_group_track_ids else int(track_id)
                    )
                else:
                    owner_track_id = min(album_group_track_ids)
            else:
                raw_owner_id = meta.get("owner_id")
                owner_track_id = int(raw_owner_id) if raw_owner_id is not None else int(track_id)

            can_replace_directly = owner_track_id in (None, int(track_id))
            is_shared_reference = bool(
                owner_scope in {"album", "album_track"}
                and owner_track_id not in (None, int(track_id))
            )

        owner_track_title: str | None = None
        if owner_track_id is not None:
            owner_row = cur.execute(
                "SELECT track_title FROM Tracks WHERE id=?",
                (int(owner_track_id),),
            ).fetchone()
            owner_track_title = str(owner_row[0] or "").strip() or None if owner_row else None

        return AlbumArtEditState(
            track_id=int(track_id),
            album_id=album_id,
            album_title=album_title,
            has_effective_art=has_effective_art,
            owner_scope=owner_scope,
            owner_track_id=owner_track_id,
            owner_track_title=owner_track_title,
            is_shared_reference=is_shared_reference,
            can_replace_directly=can_replace_directly,
        )

    def fetch_track_snapshot(
        self,
        track_id: int,
        *,
        cursor: sqlite3.Cursor | None = None,
        include_media_blobs: bool = True,
    ) -> TrackSnapshot | None:
        cur = cursor or self.conn.cursor()
        track_columns = self._track_columns()
        work_expr = "t.work_id" if "work_id" in track_columns else "NULL"
        parent_expr = "t.parent_track_id" if "parent_track_id" in track_columns else "NULL"
        relationship_expr = (
            "t.relationship_type" if "relationship_type" in track_columns else "'original'"
        )
        row = cur.execute(
            f"""
            SELECT
                t.id,
                t.db_entry_date,
                t.isrc,
                t.track_title,
                t.catalog_number,
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
                t.lyrics,
                t.audio_file_path,
                t.audio_file_storage_mode,
                t.audio_file_filename,
                t.audio_file_mime_type,
                t.audio_file_size_bytes,
                {work_expr},
                {parent_expr},
                {relationship_expr}
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
        audio_meta = self._get_track_row_media_meta(track_id, "audio_file", cursor=cur)
        album_art_meta = self.get_media_meta(track_id, "album_art", cursor=cur)
        audio_blob_b64 = None
        if include_media_blobs and bool(audio_meta.get("blob_present")):
            audio_blob_b64 = self._encode_blob_b64(
                self._fetch_track_row_media_blob(track_id, "audio_file", cursor=cur)
            )
        album_art_blob_b64 = None
        if include_media_blobs and bool(album_art_meta.get("blob_present")):
            album_art_blob_b64 = self._encode_blob_b64(
                self._fetch_media_blob_for_meta("album_art", album_art_meta, cursor=cur)
            )

        return TrackSnapshot(
            track_id=int(row[0]),
            db_entry_date=row[1],
            isrc=row[2] or "",
            track_title=row[3] or "",
            artist_name=row[5] or "",
            additional_artists=[name for (name,) in additional_rows if name],
            album_title=row[7],
            release_date=row[8],
            track_length_sec=int(row[9] or 0),
            iswc=row[10],
            upc=row[11],
            genre=row[12],
            composer=row[13],
            publisher=row[14],
            comments=row[15],
            lyrics=row[16],
            work_id=int(row[22]) if row[22] is not None else None,
            parent_track_id=int(row[23]) if row[23] is not None else None,
            relationship_type=self._normalize_relationship_type(row[24]),
            catalog_number=row[4],
            buma_work_number=row[6],
            audio_file_path=str(audio_meta.get("path") or "") or None,
            audio_file_storage_mode=str(audio_meta.get("storage_mode") or "") or None,
            audio_file_filename=str(audio_meta.get("filename") or "") or None,
            audio_file_blob_b64=audio_blob_b64,
            audio_file_mime_type=str(audio_meta.get("mime_type") or "") or None,
            audio_file_size_bytes=int(audio_meta.get("size_bytes") or 0),
            album_art_path=str(album_art_meta.get("path") or "") or None,
            album_art_storage_mode=str(album_art_meta.get("storage_mode") or "") or None,
            album_art_filename=str(album_art_meta.get("filename") or "") or None,
            album_art_blob_b64=album_art_blob_b64,
            album_art_mime_type=str(album_art_meta.get("mime_type") or "") or None,
            album_art_size_bytes=int(album_art_meta.get("size_bytes") or 0),
        )

    def restore_track_snapshot(
        self, snapshot: TrackSnapshot, *, cursor: sqlite3.Cursor | None = None
    ) -> None:
        cur = cursor or self.conn.cursor()
        track_columns = self._track_columns()
        main_artist_id = self.get_or_create_artist(snapshot.artist_name, cursor=cur)
        album_id = self.get_or_create_album(snapshot.album_title, cursor=cur)
        compact_isrc = to_compact_isrc(snapshot.isrc)
        audio_blob = self._decode_blob_b64(snapshot.audio_file_blob_b64)
        album_art_blob = self._decode_blob_b64(snapshot.album_art_blob_b64)
        existing = cur.execute(
            "SELECT 1 FROM Tracks WHERE id=?", (int(snapshot.track_id),)
        ).fetchone()
        update_assignments = [
            "db_entry_date=?",
            "isrc=?",
            "isrc_compact=?",
            "audio_file_path=?",
            "audio_file_storage_mode=?",
            "audio_file_blob=?",
            "audio_file_filename=?",
            "audio_file_mime_type=?",
            "audio_file_size_bytes=?",
            "track_title=?",
            "catalog_number=?",
            "album_art_path=?",
            "album_art_storage_mode=?",
            "album_art_blob=?",
            "album_art_filename=?",
            "album_art_mime_type=?",
            "album_art_size_bytes=?",
            "main_artist_id=?",
            "buma_work_number=?",
            "album_id=?",
            "release_date=?",
            "track_length_sec=?",
            "iswc=?",
            "upc=?",
            "genre=?",
            "composer=?",
            "publisher=?",
            "comments=?",
            "lyrics=?",
        ]
        update_values: list[object] = [
            snapshot.db_entry_date,
            snapshot.isrc,
            compact_isrc,
            snapshot.audio_file_path,
            snapshot.audio_file_storage_mode,
            sqlite3.Binary(audio_blob) if audio_blob is not None else None,
            snapshot.audio_file_filename,
            snapshot.audio_file_mime_type,
            int(snapshot.audio_file_size_bytes or 0),
            snapshot.track_title,
            snapshot.catalog_number,
            snapshot.album_art_path,
            snapshot.album_art_storage_mode,
            sqlite3.Binary(album_art_blob) if album_art_blob is not None else None,
            snapshot.album_art_filename,
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
        ]
        if "work_id" in track_columns:
            update_assignments.append("work_id=?")
            update_values.append(int(snapshot.work_id) if snapshot.work_id is not None else None)
        if "parent_track_id" in track_columns:
            update_assignments.append("parent_track_id=?")
            update_values.append(
                int(snapshot.parent_track_id) if snapshot.parent_track_id is not None else None
            )
        if "relationship_type" in track_columns:
            update_assignments.append("relationship_type=?")
            update_values.append(self._normalize_relationship_type(snapshot.relationship_type))
        if existing:
            cur.execute(
                f"""
                UPDATE Tracks SET
                    {", ".join(update_assignments)}
                WHERE id=?
                """,
                (*update_values, int(snapshot.track_id)),
            )
        else:
            insert_columns = [
                "id",
                "db_entry_date",
                "isrc",
                "isrc_compact",
                "audio_file_path",
                "audio_file_storage_mode",
                "audio_file_blob",
                "audio_file_filename",
                "audio_file_mime_type",
                "audio_file_size_bytes",
                "track_title",
                "catalog_number",
                "album_art_path",
                "album_art_storage_mode",
                "album_art_blob",
                "album_art_filename",
                "album_art_mime_type",
                "album_art_size_bytes",
                "main_artist_id",
                "buma_work_number",
                "album_id",
                "release_date",
                "track_length_sec",
                "iswc",
                "upc",
                "genre",
                "composer",
                "publisher",
                "comments",
                "lyrics",
            ]
            insert_values: list[object] = [
                int(snapshot.track_id),
                snapshot.db_entry_date,
                snapshot.isrc,
                compact_isrc,
                snapshot.audio_file_path,
                snapshot.audio_file_storage_mode,
                sqlite3.Binary(audio_blob) if audio_blob is not None else None,
                snapshot.audio_file_filename,
                snapshot.audio_file_mime_type,
                int(snapshot.audio_file_size_bytes or 0),
                snapshot.track_title,
                snapshot.catalog_number,
                snapshot.album_art_path,
                snapshot.album_art_storage_mode,
                sqlite3.Binary(album_art_blob) if album_art_blob is not None else None,
                snapshot.album_art_filename,
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
            ]
            if "work_id" in track_columns:
                insert_columns.append("work_id")
                insert_values.append(
                    int(snapshot.work_id) if snapshot.work_id is not None else None
                )
            if "parent_track_id" in track_columns:
                insert_columns.append("parent_track_id")
                insert_values.append(
                    int(snapshot.parent_track_id) if snapshot.parent_track_id is not None else None
                )
            if "relationship_type" in track_columns:
                insert_columns.append("relationship_type")
                insert_values.append(self._normalize_relationship_type(snapshot.relationship_type))
            cur.execute(
                f"""
                INSERT INTO Tracks ({", ".join(insert_columns)})
                VALUES ({", ".join("?" for _ in insert_columns)})
                """,
                insert_values,
            )
        self._sync_shadow_work_link(snapshot.track_id, snapshot.work_id, cursor=cur)
        if self._album_supports_shared_art(album_id, snapshot.album_title):
            self._update_album_art_reference(
                int(album_id),
                stored_path=snapshot.album_art_path,
                storage_mode=snapshot.album_art_storage_mode,
                blob_data=album_art_blob,
                filename=snapshot.album_art_filename,
                mime_type=snapshot.album_art_mime_type,
                size_bytes=int(snapshot.album_art_size_bytes or 0),
                cursor=cur,
            )
            self._update_track_media_reference(
                snapshot.track_id,
                "album_art",
                stored_path=None,
                storage_mode=None,
                blob_data=None,
                filename=None,
                mime_type=None,
                size_bytes=0,
                cursor=cur,
            )
        self.replace_additional_artists(snapshot.track_id, snapshot.additional_artists, cursor=cur)

    def delete_unused_artists_by_names(
        self, names: Iterable[str], *, cursor: sqlite3.Cursor | None = None
    ) -> None:
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

    def delete_unused_albums_by_titles(
        self, titles: Iterable[str], *, cursor: sqlite3.Cursor | None = None
    ) -> None:
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

    def _create_track_row(self, payload: TrackCreatePayload, *, cursor: sqlite3.Cursor) -> int:
        cur = cursor
        track_columns = self._track_columns()
        main_artist_id = self.get_or_create_artist(payload.artist_name, cursor=cur)
        album_id = self.get_or_create_album(payload.album_title, cursor=cur)
        clean_isrc = str(payload.isrc or "").strip()
        compact_isrc = to_compact_isrc(clean_isrc)
        insert_columns = [
            "isrc",
            "isrc_compact",
            "audio_file_path",
            "audio_file_storage_mode",
            "audio_file_blob",
            "audio_file_filename",
            "audio_file_mime_type",
            "audio_file_size_bytes",
            "track_title",
            "catalog_number",
            "album_art_path",
            "album_art_storage_mode",
            "album_art_blob",
            "album_art_filename",
            "album_art_mime_type",
            "album_art_size_bytes",
            "main_artist_id",
            "buma_work_number",
            "album_id",
            "release_date",
            "track_length_sec",
            "iswc",
            "upc",
            "genre",
            "composer",
            "publisher",
            "comments",
            "lyrics",
        ]
        insert_values: list[object] = [
            clean_isrc,
            compact_isrc,
            None,
            None,
            None,
            None,
            None,
            0,
            payload.track_title.strip(),
            payload.catalog_number,
            None,
            None,
            None,
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
        ]
        if "work_id" in track_columns:
            insert_columns.append("work_id")
            insert_values.append(int(payload.work_id) if payload.work_id is not None else None)
        if "parent_track_id" in track_columns:
            insert_columns.append("parent_track_id")
            insert_values.append(
                int(payload.parent_track_id) if payload.parent_track_id is not None else None
            )
        if "relationship_type" in track_columns:
            insert_columns.append("relationship_type")
            insert_values.append(self._normalize_relationship_type(payload.relationship_type))
        cur.execute(
            f"""
            INSERT INTO Tracks ({", ".join(insert_columns)})
            VALUES ({", ".join("?" for _ in insert_columns)})
            """,
            insert_values,
        )
        track_id = int(cur.lastrowid)
        self._sync_shadow_work_link(track_id, payload.work_id, cursor=cur)
        if payload.audio_file_source_path:
            self.set_media_path(
                track_id,
                "audio_file",
                payload.audio_file_source_path,
                storage_mode=payload.audio_file_storage_mode,
                cursor=cur,
            )
        if payload.album_art_source_path:
            self.set_media_path(
                track_id,
                "album_art",
                payload.album_art_source_path,
                storage_mode=payload.album_art_storage_mode,
                cursor=cur,
            )
        self.replace_additional_artists(track_id, payload.additional_artists, cursor=cur)
        return track_id

    def create_track(
        self,
        payload: TrackCreatePayload,
        *,
        cursor: sqlite3.Cursor | None = None,
    ) -> int:
        if cursor is not None:
            return self._create_track_row(payload, cursor=cursor)

        with self.conn:
            cur = self.conn.cursor()
            return self._create_track_row(payload, cursor=cur)

    def _update_track_row(self, payload: TrackUpdatePayload, *, cursor: sqlite3.Cursor) -> None:
        track_columns = self._track_columns()
        main_artist_id = self.get_or_create_artist(payload.artist_name, cursor=cursor)
        album_id = self.get_or_create_album(payload.album_title, cursor=cursor)
        clean_isrc = str(payload.isrc or "").strip()
        compact_isrc = to_compact_isrc(clean_isrc)
        current_work_id, current_parent_track_id, current_relationship_type = (
            self._current_track_governance(payload.track_id, cursor=cursor)
        )
        next_work_id = current_work_id if payload.work_id is None else int(payload.work_id)
        next_parent_track_id = (
            current_parent_track_id
            if payload.parent_track_id is None
            else int(payload.parent_track_id)
        )
        next_relationship_type = (
            current_relationship_type
            if payload.relationship_type is None
            else self._normalize_relationship_type(payload.relationship_type)
        )
        current_audio = self._get_track_row_media_meta(
            payload.track_id, "audio_file", cursor=cursor
        )
        current_audio_blob = self._fetch_track_row_media_blob(
            payload.track_id, "audio_file", cursor=cursor
        )
        current_track_art = self._get_track_row_media_meta(
            payload.track_id, "album_art", cursor=cursor
        )
        current_track_art_blob = self._fetch_track_row_media_blob(
            payload.track_id, "album_art", cursor=cursor
        )
        current_effective_art = self.get_media_meta(payload.track_id, "album_art", cursor=cursor)
        current_effective_art_blob = self._fetch_media_blob_for_meta(
            "album_art", current_effective_art, cursor=cursor
        )
        shared_album_art = self._album_supports_shared_art(album_id, payload.album_title)

        update_assignments = [
            "isrc=?",
            "isrc_compact=?",
            "audio_file_path=?",
            "audio_file_storage_mode=?",
            "audio_file_blob=?",
            "audio_file_filename=?",
            "audio_file_mime_type=?",
            "audio_file_size_bytes=?",
            "track_title=?",
            "catalog_number=?",
            "album_art_path=?",
            "album_art_storage_mode=?",
            "album_art_blob=?",
            "album_art_filename=?",
            "album_art_mime_type=?",
            "album_art_size_bytes=?",
            "main_artist_id=?",
            "buma_work_number=?",
            "album_id=?",
            "release_date=?",
            "track_length_sec=?",
            "iswc=?",
            "upc=?",
            "genre=?",
            "composer=?",
            "publisher=?",
            "comments=?",
            "lyrics=?",
        ]
        update_values: list[object] = [
            clean_isrc,
            compact_isrc,
            str(current_audio.get("path") or "") or None,
            str(current_audio.get("storage_mode") or "") or None,
            sqlite3.Binary(current_audio_blob) if current_audio_blob is not None else None,
            str(current_audio.get("filename") or "") or None,
            str(current_audio.get("mime_type") or "") or None,
            int(current_audio.get("size_bytes") or 0),
            payload.track_title.strip(),
            payload.catalog_number,
            None if shared_album_art else (str(current_track_art.get("path") or "") or None),
            None if shared_album_art else (str(current_track_art.get("storage_mode") or "") or None),
            None
            if shared_album_art or current_track_art_blob is None
            else sqlite3.Binary(current_track_art_blob),
            None if shared_album_art else (str(current_track_art.get("filename") or "") or None),
            None if shared_album_art else (str(current_track_art.get("mime_type") or "") or None),
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
        ]
        if "work_id" in track_columns:
            update_assignments.append("work_id=?")
            update_values.append(next_work_id)
        if "parent_track_id" in track_columns:
            update_assignments.append("parent_track_id=?")
            update_values.append(next_parent_track_id)
        if "relationship_type" in track_columns:
            update_assignments.append("relationship_type=?")
            update_values.append(next_relationship_type)
        cursor.execute(
            f"""
            UPDATE Tracks SET
                {", ".join(update_assignments)}
            WHERE id=?
            """,
            (*update_values, payload.track_id),
        )
        self._sync_shadow_work_link(payload.track_id, next_work_id, cursor=cursor)

        if payload.clear_audio_file:
            self.clear_media(payload.track_id, "audio_file", cursor=cursor)
        elif payload.audio_file_source_path:
            self.set_media_path(
                payload.track_id,
                "audio_file",
                payload.audio_file_source_path,
                storage_mode=payload.audio_file_storage_mode,
                cursor=cursor,
            )

        if payload.clear_album_art:
            self.clear_media(payload.track_id, "album_art", cursor=cursor)
        elif payload.album_art_source_path:
            self.set_media_path(
                payload.track_id,
                "album_art",
                payload.album_art_source_path,
                storage_mode=payload.album_art_storage_mode,
                cursor=cursor,
            )
        elif shared_album_art:
            stale_track_art_path = str(current_track_art.get("path") or "")
            if stale_track_art_path:
                self._update_track_media_reference(
                    payload.track_id,
                    "album_art",
                    stored_path=None,
                    storage_mode=None,
                    blob_data=None,
                    filename=None,
                    mime_type=None,
                    size_bytes=0,
                    cursor=cursor,
                )
                self._delete_unreferenced_media_files([stale_track_art_path], cursor=cursor)
        else:
            if bool(current_effective_art.get("has_media")) and (
                str(current_effective_art.get("path") or "")
                != str(current_track_art.get("path") or "")
                or str(current_effective_art.get("storage_mode") or "")
                != str(current_track_art.get("storage_mode") or "")
            ):
                self._update_track_media_reference(
                    payload.track_id,
                    "album_art",
                    stored_path=str(current_effective_art.get("path") or "") or None,
                    storage_mode=str(current_effective_art.get("storage_mode") or "") or None,
                    blob_data=current_effective_art_blob,
                    filename=str(current_effective_art.get("filename") or "") or None,
                    mime_type=str(current_effective_art.get("mime_type") or "") or None,
                    size_bytes=int(current_effective_art.get("size_bytes") or 0),
                    cursor=cursor,
                )

        self.replace_additional_artists(payload.track_id, payload.additional_artists, cursor=cursor)

    def update_track(
        self, payload: TrackUpdatePayload, *, cursor: sqlite3.Cursor | None = None
    ) -> None:
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
                        genre=(
                            field_updates["genre"] if "genre" in field_updates else snapshot.genre
                        ),
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
                        work_id=snapshot.work_id,
                        parent_track_id=snapshot.parent_track_id,
                        relationship_type=snapshot.relationship_type,
                        album_art_source_path=(
                            album_art_source_path
                            if apply_album_art and not clear_album_art
                            else None
                        ),
                        clear_album_art=bool(
                            apply_album_art and clear_album_art and not album_art_source_path
                        ),
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

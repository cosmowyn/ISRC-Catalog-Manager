"""Release-level catalog mutations and queries."""

from __future__ import annotations

import mimetypes
import re
import sqlite3
from pathlib import Path
from typing import Iterable

from isrc_manager.domain.codes import barcode_validation_status
from isrc_manager.file_storage import (
    STORAGE_MODE_DATABASE,
    STORAGE_MODE_MANAGED_FILE,
    ManagedFileStorage,
    bytes_from_blob,
    coalesce_filename,
    infer_storage_mode,
    normalize_storage_mode,
)
from isrc_manager.media.blob_files import _is_valid_image_path, _read_blob_from_path

from .models import (
    ReleasePayload,
    ReleaseRecord,
    ReleaseSummary,
    ReleaseTrackPlacement,
    ReleaseValidationIssue,
)

RELEASE_TYPE_CHOICES = ("single", "ep", "album", "compilation", "remix_package", "other")


class ReleaseService:
    """Owns first-class release CRUD, media handling, and track placement queries."""

    _REMIX_MARKER_RE = re.compile(r"\b(remix(?:es|ed)?|rmx)\b", re.IGNORECASE)
    _REMIX_BRACKETED_SEGMENT_RE = re.compile(
        r"\s*[\(\[\{][^)\]}]*\b(?:remix(?:es|ed)?|rmx)\b[^)\]}]*[\)\]\}]\s*",
        re.IGNORECASE,
    )
    _REMIX_SUFFIX_RE = re.compile(
        r"""
        (?:\s*[-:]\s*|\s+)
        (?:(?:the|official)\s+)*
        (?:remix(?:es|ed)?|rmx)
        (?:\s+(?:package|album|edition|collection|set))?
        \s*$
        """,
        re.IGNORECASE | re.VERBOSE,
    )

    def __init__(self, conn: sqlite3.Connection, data_root: str | Path | None = None):
        self.conn = conn
        self.data_root = Path(data_root) if data_root is not None else None
        self.media_root = self.data_root / "release_media" if self.data_root is not None else None
        self.media_store = ManagedFileStorage(data_root=data_root, relative_root="release_media")
        self._ensure_storage_columns()

    def _ensure_storage_columns(self) -> None:
        table_names = {
            str(row[0])
            for row in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            if row and row[0]
        }
        if "Releases" not in table_names:
            return
        columns = {
            str(row[1])
            for row in self.conn.execute("PRAGMA table_info(Releases)").fetchall()
            if row and row[1]
        }
        additions = (
            ("artwork_storage_mode", "TEXT"),
            ("artwork_blob", "BLOB"),
            ("artwork_filename", "TEXT"),
        )
        with self.conn:
            for column_name, column_sql in additions:
                if column_name not in columns:
                    self.conn.execute(f"ALTER TABLE Releases ADD COLUMN {column_name} {column_sql}")

    @staticmethod
    def _clean_text(value: str | None) -> str | None:
        text = str(value or "").strip()
        return text or None

    @staticmethod
    def _clean_release_type(value: str | None) -> str:
        clean = str(value or "album").strip().lower().replace(" ", "_")
        if clean not in RELEASE_TYPE_CHOICES:
            return "other"
        return clean

    @staticmethod
    def _normalize_release_identity_text(value: str | None) -> str:
        return " ".join(str(value or "").split()).casefold()

    @classmethod
    def _normalize_release_upc_family_title(cls, value: str | None) -> str:
        normalized = cls._normalize_release_identity_text(value)
        if not normalized:
            return ""

        family_title = cls._REMIX_BRACKETED_SEGMENT_RE.sub(" ", normalized)
        while True:
            updated = cls._REMIX_SUFFIX_RE.sub("", family_title).strip(" -:/")
            updated = " ".join(updated.split())
            if updated == family_title:
                break
            family_title = updated
        return family_title or normalized

    @classmethod
    def releases_share_upc_family(
        cls, releases: Iterable[tuple[str | None, str | None] | str | None]
    ) -> bool:
        normalized_titles: list[str] = []
        family_titles: list[str] = []
        variant_hint = False

        for release in releases:
            if isinstance(release, tuple):
                title, release_type = release
            else:
                title, release_type = release, None
            normalized_title = cls._normalize_release_identity_text(title)
            if not normalized_title:
                continue
            normalized_titles.append(normalized_title)
            family_title = cls._normalize_release_upc_family_title(title)
            family_titles.append(family_title)
            variant_hint = variant_hint or family_title != normalized_title
            variant_hint = variant_hint or bool(cls._REMIX_MARKER_RE.search(str(title or "")))
            variant_hint = variant_hint or cls._clean_release_type(release_type) == "remix_package"

        if not normalized_titles:
            return False
        if len(set(normalized_titles)) == 1:
            return True
        return bool(family_titles) and len(set(family_titles)) == 1 and variant_hint

    @staticmethod
    def _normalize_track_placements(
        placements: Iterable[ReleaseTrackPlacement],
    ) -> list[ReleaseTrackPlacement]:
        clean_placements: list[ReleaseTrackPlacement] = []
        seen_track_ids: set[int] = set()
        used_disc_track_slots: set[tuple[int, int]] = set()
        max_track_number_by_disc: dict[int, int] = {}

        for sequence_number, placement in enumerate(placements, start=1):
            track_id = int(placement.track_id)
            if track_id <= 0 or track_id in seen_track_ids:
                continue
            seen_track_ids.add(track_id)

            disc_number = max(1, int(placement.disc_number or 1))
            track_number = max(1, int(placement.track_number or sequence_number))
            slot = (disc_number, track_number)
            if slot in used_disc_track_slots:
                track_number = max(track_number, max_track_number_by_disc.get(disc_number, 0) + 1)
                while (disc_number, track_number) in used_disc_track_slots:
                    track_number += 1

            used_disc_track_slots.add((disc_number, track_number))
            max_track_number_by_disc[disc_number] = max(
                max_track_number_by_disc.get(disc_number, 0),
                track_number,
            )
            clean_placements.append(
                ReleaseTrackPlacement(
                    track_id=track_id,
                    disc_number=disc_number,
                    track_number=track_number,
                    sequence_number=sequence_number,
                )
            )
        return clean_placements

    def _store_artwork_source(
        self,
        source_path: str | Path,
        *,
        storage_mode: str | None = None,
    ) -> tuple[str | None, str, bytes | None, str, int]:
        source = Path(source_path)
        if not source.exists():
            raise FileNotFoundError(source)
        if not _is_valid_image_path(str(source)):
            raise ValueError("Selected release artwork is not a valid image")
        clean_mode = normalize_storage_mode(storage_mode, default=STORAGE_MODE_MANAGED_FILE)
        filename = coalesce_filename(source.name, default_stem="release-artwork")
        mime_type = mimetypes.guess_type(source.name)[0] or ""
        if clean_mode == STORAGE_MODE_DATABASE:
            data = _read_blob_from_path(str(source))
            return None, filename, data, mime_type, len(data)
        if self.media_root is None or self.data_root is None:
            raise ValueError("Release media root is not configured")
        data = source.read_bytes()
        rel_path = self.media_store.write_bytes(data, filename=filename, subdir="images")
        return rel_path, filename, None, mime_type, len(data)

    def resolve_artwork_path(self, stored_path: str | None) -> Path | None:
        return self.media_store.resolve(stored_path)

    def _is_managed_release_media_path(self, stored_path: str | None) -> bool:
        return self.media_store.is_managed(stored_path)

    def _fetch_artwork_blob(self, release_id: int) -> bytes | None:
        row = self.conn.execute(
            "SELECT artwork_blob FROM Releases WHERE id=?",
            (int(release_id),),
        ).fetchone()
        if not row or row[0] is None:
            return None
        return bytes_from_blob(row[0])

    def fetch_artwork_bytes(self, release_id: int) -> tuple[bytes, str]:
        release = self.fetch_release(release_id)
        if release is None:
            raise FileNotFoundError(release_id)
        if release.artwork_storage_mode == STORAGE_MODE_DATABASE:
            blob_data = self._fetch_artwork_blob(release_id)
            if blob_data is None:
                raise FileNotFoundError(release.artwork_filename or release_id)
            return blob_data, str(release.artwork_mime_type or "").strip()
        resolved = self.resolve_artwork_path(release.artwork_path)
        if resolved is None or not resolved.exists():
            raise FileNotFoundError(release.artwork_path or release_id)
        return resolved.read_bytes(), str(release.artwork_mime_type or "").strip()

    def _delete_unreferenced_artwork(
        self, stored_path: str | None, *, cursor: sqlite3.Cursor
    ) -> None:
        clean_path = str(stored_path or "").strip()
        if not clean_path or not self._is_managed_release_media_path(clean_path):
            return
        row = cursor.execute(
            "SELECT 1 FROM Releases WHERE artwork_path=? LIMIT 1",
            (clean_path,),
        ).fetchone()
        if row:
            return
        album_ref = cursor.execute(
            "SELECT 1 FROM Albums WHERE album_art_path=? LIMIT 1",
            (clean_path,),
        ).fetchone()
        if album_ref:
            return
        track_ref = cursor.execute(
            "SELECT 1 FROM Tracks WHERE album_art_path=? LIMIT 1",
            (clean_path,),
        ).fetchone()
        if track_ref:
            return
        resolved = self.resolve_artwork_path(clean_path)
        if resolved is None:
            return
        try:
            resolved.unlink(missing_ok=True)
        except Exception:
            pass

    def validate_release(
        self,
        payload: ReleasePayload,
        *,
        release_id: int | None = None,
        cursor: sqlite3.Cursor | None = None,
    ) -> list[ReleaseValidationIssue]:
        cur = cursor or self.conn.cursor()
        issues: list[ReleaseValidationIssue] = []
        title = self._clean_text(payload.title)
        if not title:
            issues.append(ReleaseValidationIssue("error", "title", "Release Title is required."))

        clean_release_type = self._clean_release_type(payload.release_type)
        if clean_release_type != str(payload.release_type or "").strip().lower().replace(" ", "_"):
            issues.append(
                ReleaseValidationIssue(
                    "warning", "release_type", "Release Type was normalized to a supported value."
                )
            )

        upc = self._clean_text(payload.upc)
        status = barcode_validation_status(upc)
        if status == "invalid_format":
            issues.append(
                ReleaseValidationIssue("error", "upc", "UPC/EAN must be 12 or 13 digits.")
            )
        elif status == "invalid_checksum":
            issues.append(ReleaseValidationIssue("error", "upc", "UPC/EAN checksum is invalid."))
        elif status == "missing":
            issues.append(ReleaseValidationIssue("warning", "upc", "Release has no UPC/EAN yet."))
        if upc:
            params: list[object] = [upc]
            sql = "SELECT id, title, release_type FROM Releases WHERE upc=?"
            if release_id is not None:
                sql += " AND id != ?"
                params.append(int(release_id))
            sql += " ORDER BY id"
            duplicates = cur.execute(sql, params).fetchall()
            duplicate = duplicates[0] if duplicates else None
            shared_upc_family = self.releases_share_upc_family(
                [(payload.title, payload.release_type), *[(row[1], row[2]) for row in duplicates]]
            )
            if duplicate and not shared_upc_family:
                issues.append(
                    ReleaseValidationIssue(
                        "warning",
                        "upc",
                        f"UPC/EAN is already used by release '{duplicate[1]}'.",
                    )
                )
        catalog_number = self._clean_text(payload.catalog_number)
        if catalog_number:
            params = [catalog_number]
            sql = "SELECT id, title FROM Releases WHERE catalog_number=?"
            if release_id is not None:
                sql += " AND id != ?"
                params.append(int(release_id))
            sql += " ORDER BY id LIMIT 1"
            duplicate = cur.execute(sql, params).fetchone()
            if duplicate:
                issues.append(
                    ReleaseValidationIssue(
                        "warning",
                        "catalog_number",
                        f"Catalog# is already used by release '{duplicate[1]}'.",
                    )
                )
        if payload.release_date and len(str(payload.release_date)) != 10:
            issues.append(
                ReleaseValidationIssue("error", "release_date", "Release Date must be YYYY-MM-DD.")
            )
        if payload.original_release_date and len(str(payload.original_release_date)) != 10:
            issues.append(
                ReleaseValidationIssue(
                    "error", "original_release_date", "Original Release Date must be YYYY-MM-DD."
                )
            )
        return issues

    def find_matching_release_id(
        self,
        *,
        title: str | None,
        primary_artist: str | None = None,
        upc: str | None = None,
        catalog_number: str | None = None,
        cursor: sqlite3.Cursor | None = None,
    ) -> int | None:
        cur = cursor or self.conn.cursor()
        clean_title = self._clean_text(title)
        clean_artist = self._clean_text(primary_artist)
        clean_catalog = self._clean_text(catalog_number)
        if clean_title:
            clauses = ["title=?"]
            params: list[object] = [clean_title]
            if clean_artist:
                clauses.append("COALESCE(primary_artist, '')=?")
                params.append(clean_artist)
            if clean_catalog:
                clauses.append("COALESCE(catalog_number, '')=?")
                params.append(clean_catalog)

            rows = cur.execute(
                f"""
                SELECT id
                FROM Releases
                WHERE {' AND '.join(clauses)}
                ORDER BY id
                """,
                params,
            ).fetchall()
            if rows:
                return int(rows[0][0])

        clean_upc = self._clean_text(upc)
        if clean_upc:
            rows = cur.execute(
                "SELECT id FROM Releases WHERE upc=? ORDER BY id",
                (clean_upc,),
            ).fetchall()
            if len(rows) == 1:
                return int(rows[0][0])
        return None

    def ensure_release(
        self,
        payload: ReleasePayload,
        *,
        cursor: sqlite3.Cursor | None = None,
    ) -> int:
        cur = cursor or self.conn.cursor()
        release_id = self.find_matching_release_id(
            title=payload.title,
            primary_artist=payload.primary_artist,
            upc=payload.upc,
            catalog_number=payload.catalog_number,
            cursor=cur,
        )
        if release_id is None:
            return self._persist_release(payload, cursor=cur)
        return self._persist_release(payload, release_id=release_id, cursor=cur)

    def _persist_release(
        self,
        payload: ReleasePayload,
        *,
        release_id: int | None = None,
        cursor: sqlite3.Cursor,
    ) -> int:
        issues = self.validate_release(payload, release_id=release_id, cursor=cursor)
        errors = [issue.message for issue in issues if issue.severity == "error"]
        if errors:
            raise ValueError("\n".join(errors))

        clean_title = str(self._clean_text(payload.title) or "")
        clean_type = self._clean_release_type(payload.release_type)
        upc = self._clean_text(payload.upc)
        barcode_status = barcode_validation_status(upc)
        stale_artwork_path = None
        current_artwork_path = None
        current_artwork_mode = None
        current_artwork_filename = None
        current_artwork_mime = None
        current_artwork_size = 0
        current_artwork_blob = None

        if release_id is not None:
            current = cursor.execute(
                """
                SELECT
                    artwork_path,
                    artwork_storage_mode,
                    artwork_filename,
                    artwork_mime_type,
                    artwork_size_bytes
                FROM Releases
                WHERE id=?
                """,
                (int(release_id),),
            ).fetchone()
            if not current:
                raise ValueError(f"Release {release_id} not found")
            current_artwork_path = str(current[0] or "") or None
            current_artwork_mode = infer_storage_mode(
                explicit_mode=current[1], stored_path=current[0]
            )
            current_artwork_filename = str(current[2] or "") or None
            current_artwork_mime = str(current[3] or "") or None
            current_artwork_size = int(current[4] or 0)
            if current_artwork_mode == STORAGE_MODE_DATABASE:
                current_artwork_blob = self._fetch_artwork_blob(int(release_id))

        artwork_path = current_artwork_path
        artwork_mode = current_artwork_mode
        artwork_filename = current_artwork_filename
        artwork_mime = current_artwork_mime
        artwork_size = current_artwork_size
        artwork_blob = current_artwork_blob
        if payload.clear_artwork:
            stale_artwork_path = artwork_path
            artwork_path = None
            artwork_mode = None
            artwork_filename = None
            artwork_mime = None
            artwork_size = 0
            artwork_blob = None
        elif payload.artwork_source_path:
            artwork_path, artwork_filename, artwork_blob, artwork_mime, artwork_size = (
                self._store_artwork_source(
                    payload.artwork_source_path,
                    storage_mode=payload.artwork_storage_mode,
                )
            )
            artwork_mode = normalize_storage_mode(
                payload.artwork_storage_mode,
                default=STORAGE_MODE_MANAGED_FILE,
            )
            stale_artwork_path = current_artwork_path

        values = (
            clean_title,
            self._clean_text(payload.version_subtitle),
            self._clean_text(payload.primary_artist),
            self._clean_text(payload.album_artist),
            clean_type,
            self._clean_text(payload.release_date),
            self._clean_text(payload.original_release_date),
            self._clean_text(payload.label),
            self._clean_text(payload.sublabel),
            self._clean_text(payload.catalog_number),
            upc,
            barcode_status,
            self._clean_text(payload.territory),
            1 if payload.explicit_flag else 0,
            self._clean_text(payload.repertoire_status),
            1 if payload.metadata_complete else 0,
            1 if payload.contract_signed else 0,
            1 if payload.rights_verified else 0,
            self._clean_text(payload.notes),
            artwork_path,
            artwork_mode,
            sqlite3.Binary(artwork_blob) if artwork_blob is not None else None,
            artwork_filename,
            artwork_mime,
            artwork_size,
            self._clean_text(payload.profile_name),
        )

        if release_id is None:
            cursor.execute(
                """
                INSERT INTO Releases (
                    title,
                    version_subtitle,
                    primary_artist,
                    album_artist,
                    release_type,
                    release_date,
                    original_release_date,
                    label,
                    sublabel,
                    catalog_number,
                    upc,
                    barcode_validation_status,
                    territory,
                    explicit_flag,
                    repertoire_status,
                    metadata_complete,
                    contract_signed,
                    rights_verified,
                    release_notes,
                    artwork_path,
                    artwork_storage_mode,
                    artwork_blob,
                    artwork_filename,
                    artwork_mime_type,
                    artwork_size_bytes,
                    profile_name
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
            release_id = int(cursor.lastrowid)
        else:
            cursor.execute(
                """
                UPDATE Releases
                SET title=?,
                    version_subtitle=?,
                    primary_artist=?,
                    album_artist=?,
                    release_type=?,
                    release_date=?,
                    original_release_date=?,
                    label=?,
                    sublabel=?,
                    catalog_number=?,
                    upc=?,
                    barcode_validation_status=?,
                    territory=?,
                    explicit_flag=?,
                    repertoire_status=?,
                    metadata_complete=?,
                    contract_signed=?,
                    rights_verified=?,
                    release_notes=?,
                    artwork_path=?,
                    artwork_storage_mode=?,
                    artwork_blob=?,
                    artwork_filename=?,
                    artwork_mime_type=?,
                    artwork_size_bytes=?,
                    profile_name=?
                WHERE id=?
                """,
                values + (int(release_id),),
            )

        if stale_artwork_path and stale_artwork_path != artwork_path:
            self._delete_unreferenced_artwork(stale_artwork_path, cursor=cursor)

        if payload.placements:
            self.replace_release_tracks(release_id, payload.placements, cursor=cursor)
        return int(release_id)

    def create_release(
        self, payload: ReleasePayload, *, cursor: sqlite3.Cursor | None = None
    ) -> int:
        if cursor is not None:
            return self._persist_release(payload, cursor=cursor)
        with self.conn:
            cur = self.conn.cursor()
            return self._persist_release(payload, cursor=cur)

    def update_release(
        self, release_id: int, payload: ReleasePayload, *, cursor: sqlite3.Cursor | None = None
    ) -> int:
        if cursor is not None:
            return self._persist_release(payload, release_id=int(release_id), cursor=cursor)
        with self.conn:
            cur = self.conn.cursor()
            return self._persist_release(payload, release_id=int(release_id), cursor=cur)

    def convert_artwork_storage_mode(self, release_id: int, target_mode: str) -> ReleaseRecord:
        release = self.fetch_release(release_id)
        if release is None:
            raise ValueError(f"Release {release_id} not found")
        clean_mode = normalize_storage_mode(target_mode)
        if release.artwork_storage_mode == clean_mode:
            return release
        data, mime_type = self.fetch_artwork_bytes(release_id)
        if clean_mode == STORAGE_MODE_DATABASE:
            artwork_path = None
            artwork_blob = data
        else:
            artwork_path = self.media_store.write_bytes(
                data,
                filename=coalesce_filename(
                    release.artwork_filename, default_stem="release-artwork"
                ),
                subdir="images",
            )
            artwork_blob = None
        with self.conn:
            self.conn.execute(
                """
                UPDATE Releases
                SET artwork_path=?,
                    artwork_storage_mode=?,
                    artwork_blob=?,
                    artwork_filename=?,
                    artwork_mime_type=?,
                    artwork_size_bytes=?
                WHERE id=?
                """,
                (
                    artwork_path,
                    clean_mode,
                    sqlite3.Binary(artwork_blob) if artwork_blob is not None else None,
                    coalesce_filename(release.artwork_filename, default_stem="release-artwork"),
                    mime_type,
                    len(data),
                    int(release_id),
                ),
            )
        updated = self.fetch_release(release_id)
        if updated is None:
            raise RuntimeError(f"Release {release_id} disappeared after conversion")
        return updated

    def duplicate_release(self, release_id: int) -> int:
        summary = self.fetch_release_summary(release_id)
        if summary is None:
            raise ValueError(f"Release {release_id} not found")
        payload = ReleasePayload(
            title=f"{summary.release.title} Copy",
            version_subtitle=summary.release.version_subtitle,
            primary_artist=summary.release.primary_artist,
            album_artist=summary.release.album_artist,
            release_type=summary.release.release_type,
            release_date=summary.release.release_date,
            original_release_date=summary.release.original_release_date,
            label=summary.release.label,
            sublabel=summary.release.sublabel,
            catalog_number=summary.release.catalog_number,
            upc=None,
            territory=summary.release.territory,
            explicit_flag=summary.release.explicit_flag,
            repertoire_status=summary.release.repertoire_status,
            metadata_complete=summary.release.metadata_complete,
            contract_signed=summary.release.contract_signed,
            rights_verified=summary.release.rights_verified,
            notes=summary.release.notes,
            profile_name=summary.release.profile_name,
            placements=list(summary.tracks),
        )
        return self.create_release(payload)

    def replace_release_tracks(
        self,
        release_id: int,
        placements: Iterable[ReleaseTrackPlacement],
        *,
        cursor: sqlite3.Cursor | None = None,
    ) -> None:
        cur = cursor or self.conn.cursor()
        clean_placements = self._normalize_track_placements(placements)

        cur.execute("DELETE FROM ReleaseTracks WHERE release_id=?", (int(release_id),))
        for placement in clean_placements:
            cur.execute(
                """
                INSERT INTO ReleaseTracks (
                    release_id,
                    track_id,
                    disc_number,
                    track_number,
                    sequence_number
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    int(release_id),
                    placement.track_id,
                    placement.disc_number,
                    placement.track_number,
                    placement.sequence_number,
                ),
            )

    def add_tracks_to_release(
        self,
        release_id: int,
        track_ids: Iterable[int],
        *,
        cursor: sqlite3.Cursor | None = None,
    ) -> list[int]:
        cur = cursor or self.conn.cursor()
        current_rows = cur.execute(
            """
            SELECT track_id, disc_number, track_number, sequence_number
            FROM ReleaseTracks
            WHERE release_id=?
            ORDER BY sequence_number, disc_number, track_number, track_id
            """,
            (int(release_id),),
        ).fetchall()
        placements = [
            ReleaseTrackPlacement(
                track_id=int(track_id),
                disc_number=int(disc_number or 1),
                track_number=int(track_number or 1),
                sequence_number=int(sequence_number or index + 1),
            )
            for index, (track_id, disc_number, track_number, sequence_number) in enumerate(
                current_rows
            )
        ]
        seen = {placement.track_id for placement in placements}
        next_track_number = max([placement.track_number for placement in placements], default=0) + 1
        next_sequence = max([placement.sequence_number for placement in placements], default=0) + 1
        added: list[int] = []
        for track_id in track_ids:
            clean_track_id = int(track_id)
            if clean_track_id <= 0 or clean_track_id in seen:
                continue
            placements.append(
                ReleaseTrackPlacement(
                    track_id=clean_track_id,
                    disc_number=1,
                    track_number=next_track_number,
                    sequence_number=next_sequence,
                )
            )
            seen.add(clean_track_id)
            added.append(clean_track_id)
            next_track_number += 1
            next_sequence += 1
        self.replace_release_tracks(release_id, placements, cursor=cur)
        return added

    def remove_track_from_release(self, release_id: int, track_id: int) -> None:
        with self.conn:
            cur = self.conn.cursor()
            cur.execute(
                "DELETE FROM ReleaseTracks WHERE release_id=? AND track_id=?",
                (int(release_id), int(track_id)),
            )

    def fetch_release(
        self, release_id: int, *, cursor: sqlite3.Cursor | None = None
    ) -> ReleaseRecord | None:
        cur = cursor or self.conn.cursor()
        row = cur.execute(
            """
            SELECT
                r.id,
                r.title,
                r.version_subtitle,
                r.primary_artist,
                r.album_artist,
                r.release_type,
                r.release_date,
                r.original_release_date,
                r.label,
                r.sublabel,
                r.catalog_number,
                r.upc,
                r.barcode_validation_status,
                r.territory,
                r.explicit_flag,
                r.repertoire_status,
                r.metadata_complete,
                r.contract_signed,
                r.rights_verified,
                r.release_notes,
                r.artwork_path,
                r.artwork_storage_mode,
                r.artwork_filename,
                r.artwork_mime_type,
                r.artwork_size_bytes,
                r.profile_name,
                CASE WHEN r.artwork_blob IS NOT NULL THEN 1 ELSE 0 END,
                COUNT(rt.track_id) AS track_count
            FROM Releases r
            LEFT JOIN ReleaseTracks rt ON rt.release_id = r.id
            WHERE r.id=?
            GROUP BY
                r.id, r.title, r.version_subtitle, r.primary_artist, r.album_artist,
                r.release_type, r.release_date, r.original_release_date, r.label,
                r.sublabel, r.catalog_number, r.upc, r.barcode_validation_status,
                r.territory, r.explicit_flag, r.repertoire_status, r.metadata_complete,
                r.contract_signed, r.rights_verified, r.release_notes, r.artwork_path,
                r.artwork_storage_mode, r.artwork_filename, r.artwork_mime_type,
                r.artwork_size_bytes, r.profile_name, r.artwork_blob
            """,
            (int(release_id),),
        ).fetchone()
        if not row:
            return None
        return ReleaseRecord(
            id=int(row[0]),
            title=str(row[1] or ""),
            version_subtitle=self._clean_text(row[2]),
            primary_artist=self._clean_text(row[3]),
            album_artist=self._clean_text(row[4]),
            release_type=str(row[5] or "album"),
            release_date=self._clean_text(row[6]),
            original_release_date=self._clean_text(row[7]),
            label=self._clean_text(row[8]),
            sublabel=self._clean_text(row[9]),
            catalog_number=self._clean_text(row[10]),
            upc=self._clean_text(row[11]),
            barcode_validation_status=str(row[12] or "missing"),
            territory=self._clean_text(row[13]),
            explicit_flag=bool(int(row[14] or 0)),
            repertoire_status=self._clean_text(row[15]),
            metadata_complete=bool(int(row[16] or 0)),
            contract_signed=bool(int(row[17] or 0)),
            rights_verified=bool(int(row[18] or 0)),
            notes=self._clean_text(row[19]),
            artwork_path=self._clean_text(row[20]),
            artwork_storage_mode=infer_storage_mode(
                explicit_mode=row[21],
                stored_path=row[20],
                blob_value=b"\x00" if int(row[26] or 0) else None,
            ),
            artwork_filename=self._clean_text(row[22]),
            artwork_mime_type=self._clean_text(row[23]),
            artwork_size_bytes=int(row[24] or 0),
            profile_name=self._clean_text(row[25]),
            track_count=int(row[27] or 0),
        )

    def list_release_tracks(
        self,
        release_id: int,
        *,
        cursor: sqlite3.Cursor | None = None,
    ) -> list[ReleaseTrackPlacement]:
        cur = cursor or self.conn.cursor()
        rows = cur.execute(
            """
            SELECT track_id, disc_number, track_number, sequence_number
            FROM ReleaseTracks
            WHERE release_id=?
            ORDER BY sequence_number, disc_number, track_number, track_id
            """,
            (int(release_id),),
        ).fetchall()
        return [
            ReleaseTrackPlacement(
                track_id=int(track_id),
                disc_number=int(disc_number or 1),
                track_number=int(track_number or 1),
                sequence_number=int(sequence_number or index + 1),
            )
            for index, (track_id, disc_number, track_number, sequence_number) in enumerate(rows)
        ]

    def fetch_release_summary(self, release_id: int) -> ReleaseSummary | None:
        record = self.fetch_release(release_id)
        if record is None:
            return None
        return ReleaseSummary(release=record, tracks=self.list_release_tracks(release_id))

    def list_releases(self, *, search_text: str = "") -> list[ReleaseRecord]:
        params: list[object] = []
        where_clause = ""
        if search_text.strip():
            needle = f"%{search_text.strip()}%"
            where_clause = """
            WHERE r.title LIKE ?
               OR COALESCE(r.primary_artist, '') LIKE ?
               OR COALESCE(r.album_artist, '') LIKE ?
               OR COALESCE(r.catalog_number, '') LIKE ?
               OR COALESCE(r.upc, '') LIKE ?
            """
            params.extend([needle, needle, needle, needle, needle])

        rows = self.conn.execute(
            f"""
            SELECT
                r.id,
                r.title,
                r.version_subtitle,
                r.primary_artist,
                r.album_artist,
                r.release_type,
                r.release_date,
                r.original_release_date,
                r.label,
                r.sublabel,
                r.catalog_number,
                r.upc,
                r.barcode_validation_status,
                r.territory,
                r.explicit_flag,
                r.repertoire_status,
                r.metadata_complete,
                r.contract_signed,
                r.rights_verified,
                r.release_notes,
                r.artwork_path,
                r.artwork_storage_mode,
                r.artwork_filename,
                r.artwork_mime_type,
                r.artwork_size_bytes,
                r.profile_name,
                CASE WHEN r.artwork_blob IS NOT NULL THEN 1 ELSE 0 END,
                COUNT(rt.track_id) AS track_count
            FROM Releases r
            LEFT JOIN ReleaseTracks rt ON rt.release_id = r.id
            {where_clause}
            GROUP BY
                r.id, r.title, r.version_subtitle, r.primary_artist, r.album_artist,
                r.release_type, r.release_date, r.original_release_date, r.label,
                r.sublabel, r.catalog_number, r.upc, r.barcode_validation_status,
                r.territory, r.explicit_flag, r.repertoire_status, r.metadata_complete,
                r.contract_signed, r.rights_verified, r.release_notes, r.artwork_path,
                r.artwork_storage_mode, r.artwork_filename, r.artwork_mime_type,
                r.artwork_size_bytes, r.profile_name, r.artwork_blob
            ORDER BY COALESCE(r.release_date, ''), r.title COLLATE NOCASE, r.id
            """,
            params,
        ).fetchall()
        return [
            ReleaseRecord(
                id=int(row[0]),
                title=str(row[1] or ""),
                version_subtitle=self._clean_text(row[2]),
                primary_artist=self._clean_text(row[3]),
                album_artist=self._clean_text(row[4]),
                release_type=str(row[5] or "album"),
                release_date=self._clean_text(row[6]),
                original_release_date=self._clean_text(row[7]),
                label=self._clean_text(row[8]),
                sublabel=self._clean_text(row[9]),
                catalog_number=self._clean_text(row[10]),
                upc=self._clean_text(row[11]),
                barcode_validation_status=str(row[12] or "missing"),
                territory=self._clean_text(row[13]),
                explicit_flag=bool(int(row[14] or 0)),
                repertoire_status=self._clean_text(row[15]),
                metadata_complete=bool(int(row[16] or 0)),
                contract_signed=bool(int(row[17] or 0)),
                rights_verified=bool(int(row[18] or 0)),
                notes=self._clean_text(row[19]),
                artwork_path=self._clean_text(row[20]),
                artwork_storage_mode=infer_storage_mode(
                    explicit_mode=row[21],
                    stored_path=row[20],
                    blob_value=b"\x00" if int(row[26] or 0) else None,
                ),
                artwork_filename=self._clean_text(row[22]),
                artwork_mime_type=self._clean_text(row[23]),
                artwork_size_bytes=int(row[24] or 0),
                profile_name=self._clean_text(row[25]),
                track_count=int(row[27] or 0),
            )
            for row in rows
        ]

    def find_release_ids_for_track(self, track_id: int) -> list[int]:
        rows = self.conn.execute(
            """
            SELECT release_id
            FROM ReleaseTracks
            WHERE track_id=?
            ORDER BY sequence_number, release_id
            """,
            (int(track_id),),
        ).fetchall()
        return [int(release_id) for (release_id,) in rows]

    def find_primary_release_for_track(self, track_id: int) -> ReleaseRecord | None:
        release_ids = self.find_release_ids_for_track(track_id)
        if not release_ids:
            return None
        return self.fetch_release(release_ids[0])

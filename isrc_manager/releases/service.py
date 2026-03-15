"""Release-level catalog mutations and queries."""

from __future__ import annotations

import mimetypes
import sqlite3
import time
from pathlib import Path
from typing import Iterable

from isrc_manager.domain.codes import barcode_validation_status, is_blank
from isrc_manager.media.blob_files import _is_valid_image_path

from .models import ReleasePayload, ReleaseRecord, ReleaseSummary, ReleaseTrackPlacement, ReleaseValidationIssue

RELEASE_TYPE_CHOICES = ("single", "ep", "album", "compilation", "remix_package", "other")


class ReleaseService:
    """Owns first-class release CRUD, media handling, and track placement queries."""

    def __init__(self, conn: sqlite3.Connection, data_root: str | Path | None = None):
        self.conn = conn
        self.data_root = Path(data_root) if data_root is not None else None
        self.media_root = self.data_root / "release_media" if self.data_root is not None else None

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

    def _write_artwork_file(self, source_path: str | Path) -> tuple[str, str, int]:
        source = Path(source_path)
        if not source.exists():
            raise FileNotFoundError(source)
        if not _is_valid_image_path(str(source)):
            raise ValueError("Selected release artwork is not a valid image")
        if self.media_root is None or self.data_root is None:
            raise ValueError("Release media root is not configured")

        destination_dir = self.media_root / "images"
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / f"{int(time.time_ns())}_{source.name}"
        destination.write_bytes(source.read_bytes())

        mime_type = mimetypes.guess_type(source.name)[0] or ""
        size_bytes = destination.stat().st_size
        rel_path = str(destination.relative_to(self.data_root))
        return rel_path, mime_type, int(size_bytes)

    def resolve_artwork_path(self, stored_path: str | None) -> Path | None:
        clean_path = str(stored_path or "").strip()
        if not clean_path:
            return None
        path = Path(clean_path)
        if path.is_absolute():
            return path
        if self.data_root is None:
            raise ValueError("Release media root is not configured")
        return self.data_root / path

    def _is_managed_release_media_path(self, stored_path: str | None) -> bool:
        clean_path = str(stored_path or "").strip()
        if not clean_path or self.data_root is None or self.media_root is None:
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

    def _delete_unreferenced_artwork(self, stored_path: str | None, *, cursor: sqlite3.Cursor) -> None:
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
            issues.append(ReleaseValidationIssue("warning", "release_type", "Release Type was normalized to a supported value."))

        upc = self._clean_text(payload.upc)
        status = barcode_validation_status(upc)
        if status == "invalid_format":
            issues.append(ReleaseValidationIssue("error", "upc", "UPC/EAN must be 12 or 13 digits."))
        elif status == "invalid_checksum":
            issues.append(ReleaseValidationIssue("error", "upc", "UPC/EAN checksum is invalid."))
        elif status == "missing":
            issues.append(ReleaseValidationIssue("warning", "upc", "Release has no UPC/EAN yet."))
        if upc:
            params: list[object] = [upc]
            sql = "SELECT id, title FROM Releases WHERE upc=?"
            if release_id is not None:
                sql += " AND id != ?"
                params.append(int(release_id))
            sql += " ORDER BY id LIMIT 1"
            duplicate = cur.execute(sql, params).fetchone()
            if duplicate:
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
            issues.append(ReleaseValidationIssue("error", "release_date", "Release Date must be YYYY-MM-DD."))
        if payload.original_release_date and len(str(payload.original_release_date)) != 10:
            issues.append(
                ReleaseValidationIssue("error", "original_release_date", "Original Release Date must be YYYY-MM-DD.")
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
        current_artwork_mime = None
        current_artwork_size = 0

        if release_id is not None:
            current = cursor.execute(
                "SELECT artwork_path, artwork_mime_type, artwork_size_bytes FROM Releases WHERE id=?",
                (int(release_id),),
            ).fetchone()
            if not current:
                raise ValueError(f"Release {release_id} not found")
            current_artwork_path = str(current[0] or "") or None
            current_artwork_mime = str(current[1] or "") or None
            current_artwork_size = int(current[2] or 0)

        artwork_path = current_artwork_path
        artwork_mime = current_artwork_mime
        artwork_size = current_artwork_size
        if payload.clear_artwork:
            stale_artwork_path = artwork_path
            artwork_path = None
            artwork_mime = None
            artwork_size = 0
        elif payload.artwork_source_path:
            artwork_path, artwork_mime, artwork_size = self._write_artwork_file(payload.artwork_source_path)
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
            self._clean_text(payload.notes),
            artwork_path,
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
                    release_notes,
                    artwork_path,
                    artwork_mime_type,
                    artwork_size_bytes,
                    profile_name
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    release_notes=?,
                    artwork_path=?,
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

    def create_release(self, payload: ReleasePayload, *, cursor: sqlite3.Cursor | None = None) -> int:
        if cursor is not None:
            return self._persist_release(payload, cursor=cursor)
        with self.conn:
            cur = self.conn.cursor()
            return self._persist_release(payload, cursor=cur)

    def update_release(self, release_id: int, payload: ReleasePayload, *, cursor: sqlite3.Cursor | None = None) -> int:
        if cursor is not None:
            return self._persist_release(payload, release_id=int(release_id), cursor=cursor)
        with self.conn:
            cur = self.conn.cursor()
            return self._persist_release(payload, release_id=int(release_id), cursor=cur)

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
        clean_placements: list[ReleaseTrackPlacement] = []
        seen_track_ids: set[int] = set()
        for sequence_number, placement in enumerate(placements, start=1):
            track_id = int(placement.track_id)
            if track_id <= 0 or track_id in seen_track_ids:
                continue
            seen_track_ids.add(track_id)
            clean_placements.append(
                ReleaseTrackPlacement(
                    track_id=track_id,
                    disc_number=max(1, int(placement.disc_number or 1)),
                    track_number=max(1, int(placement.track_number or sequence_number)),
                    sequence_number=max(1, int(placement.sequence_number or sequence_number)),
                )
            )

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
            for index, (track_id, disc_number, track_number, sequence_number) in enumerate(current_rows)
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

    def fetch_release(self, release_id: int, *, cursor: sqlite3.Cursor | None = None) -> ReleaseRecord | None:
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
                r.release_notes,
                r.artwork_path,
                r.artwork_mime_type,
                r.artwork_size_bytes,
                r.profile_name,
                COUNT(rt.track_id) AS track_count
            FROM Releases r
            LEFT JOIN ReleaseTracks rt ON rt.release_id = r.id
            WHERE r.id=?
            GROUP BY
                r.id, r.title, r.version_subtitle, r.primary_artist, r.album_artist,
                r.release_type, r.release_date, r.original_release_date, r.label,
                r.sublabel, r.catalog_number, r.upc, r.barcode_validation_status,
                r.territory, r.explicit_flag, r.release_notes, r.artwork_path,
                r.artwork_mime_type, r.artwork_size_bytes, r.profile_name
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
            notes=self._clean_text(row[15]),
            artwork_path=self._clean_text(row[16]),
            artwork_mime_type=self._clean_text(row[17]),
            artwork_size_bytes=int(row[18] or 0),
            profile_name=self._clean_text(row[19]),
            track_count=int(row[20] or 0),
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
                r.release_notes,
                r.artwork_path,
                r.artwork_mime_type,
                r.artwork_size_bytes,
                r.profile_name,
                COUNT(rt.track_id) AS track_count
            FROM Releases r
            LEFT JOIN ReleaseTracks rt ON rt.release_id = r.id
            {where_clause}
            GROUP BY
                r.id, r.title, r.version_subtitle, r.primary_artist, r.album_artist,
                r.release_type, r.release_date, r.original_release_date, r.label,
                r.sublabel, r.catalog_number, r.upc, r.barcode_validation_status,
                r.territory, r.explicit_flag, r.release_notes, r.artwork_path,
                r.artwork_mime_type, r.artwork_size_bytes, r.profile_name
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
                notes=self._clean_text(row[15]),
                artwork_path=self._clean_text(row[16]),
                artwork_mime_type=self._clean_text(row[17]),
                artwork_size_bytes=int(row[18] or 0),
                profile_name=self._clean_text(row[19]),
                track_count=int(row[20] or 0),
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

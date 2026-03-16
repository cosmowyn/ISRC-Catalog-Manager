"""Actionable catalog health checks and safe bulk fixes."""

from __future__ import annotations

import csv
import json
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path

from isrc_manager.domain.codes import barcode_validation_status, to_compact_isrc
from isrc_manager.releases import ReleaseService
from isrc_manager.services.tracks import TrackService

from .models import QualityIssue, QualityScanResult


class QualityDashboardService:
    """Runs deterministic quality checks and exposes safe repair operations."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        track_service: TrackService,
        release_service: ReleaseService,
        data_root: str | Path | None = None,
    ):
        self.conn = conn
        self.track_service = track_service
        self.release_service = release_service
        self.data_root = Path(data_root) if data_root is not None else None

    def scan(self) -> QualityScanResult:
        issues: list[QualityIssue] = []
        issues.extend(self._track_metadata_issues())
        issues.extend(self._release_issues())
        issues.extend(self._media_issues())
        issues.extend(self._ordering_issues())
        issues.extend(self._license_issues())
        issues.extend(self._custom_field_issues())
        counts_by_severity = Counter(issue.severity for issue in issues)
        counts_by_type = Counter(issue.issue_type for issue in issues)
        return QualityScanResult(
            issues=issues,
            counts_by_severity=dict(counts_by_severity),
            counts_by_type=dict(counts_by_type),
        )

    @staticmethod
    def _normalize_release_identity_text(value: str | None) -> str:
        return " ".join(str(value or "").split()).casefold()

    def _track_metadata_issues(self) -> list[QualityIssue]:
        issues: list[QualityIssue] = []
        rows = self.conn.execute(
            """
            SELECT
                t.id,
                COALESCE(t.track_title, ''),
                COALESCE(a.name, ''),
                COALESCE(t.isrc, ''),
                COALESCE(t.release_date, ''),
                COALESCE(t.audio_file_path, ''),
                COALESCE(t.upc, ''),
                COALESCE(t.catalog_number, ''),
                COALESCE(t.isrc_compact, '')
            FROM Tracks t
            LEFT JOIN Artists a ON a.id = t.main_artist_id
            ORDER BY t.id
            """
        ).fetchall()
        for (
            track_id,
            title,
            artist,
            isrc,
            release_date,
            audio_file_path,
            upc,
            catalog_number,
            compact_isrc,
        ) in rows:
            if not str(title or "").strip():
                issues.append(
                    QualityIssue(
                        "missing_track_title",
                        "error",
                        "Missing Track Title",
                        "Track title is required for exports and browsing.",
                        "track",
                        int(track_id),
                        track_id=int(track_id),
                    )
                )
            if not str(artist or "").strip():
                issues.append(
                    QualityIssue(
                        "missing_primary_artist",
                        "error",
                        "Missing Primary Artist",
                        "Primary artist is required for track metadata and exchange exports.",
                        "track",
                        int(track_id),
                        track_id=int(track_id),
                    )
                )
            if not str(isrc or "").strip():
                issues.append(
                    QualityIssue(
                        "missing_isrc",
                        "warning",
                        "Missing ISRC",
                        "This track does not currently have an ISRC assigned.",
                        "track",
                        int(track_id),
                        track_id=int(track_id),
                    )
                )
            if str(release_date or "").strip():
                try:
                    datetime.strptime(str(release_date), "%Y-%m-%d")
                except Exception:
                    issues.append(
                        QualityIssue(
                            "invalid_track_release_date",
                            "warning",
                            "Invalid Track Release Date",
                            f"Track release date '{release_date}' is not a valid YYYY-MM-DD value.",
                            "track",
                            int(track_id),
                            track_id=int(track_id),
                            fix_key="normalize_dates",
                        )
                    )
            if str(isrc or "").strip() and to_compact_isrc(isrc) != str(compact_isrc or ""):
                issues.append(
                    QualityIssue(
                        "derived_isrc_compact_out_of_sync",
                        "warning",
                        "ISRC Compact Value Out Of Sync",
                        "The derived compact ISRC value can be regenerated safely.",
                        "track",
                        int(track_id),
                        track_id=int(track_id),
                        fix_key="regenerate_derived",
                    )
                )
            if not str(audio_file_path or "").strip():
                issues.append(
                    QualityIssue(
                        "missing_audio_attachment",
                        "warning",
                        "Missing Audio Attachment",
                        "No managed audio file is attached to this track.",
                        "track",
                        int(track_id),
                        track_id=int(track_id),
                    )
                )

        duplicate_rows = self.conn.execute(
            """
            SELECT isrc, GROUP_CONCAT(id, ',')
            FROM Tracks
            WHERE isrc IS NOT NULL AND trim(isrc) != ''
            GROUP BY isrc
            HAVING COUNT(*) > 1
            """
        ).fetchall()
        for isrc, ids in duplicate_rows:
            for track_id in [int(value) for value in str(ids or "").split(",") if value]:
                issues.append(
                    QualityIssue(
                        "duplicate_isrc",
                        "error",
                        "Duplicate ISRC",
                        f"ISRC {isrc} is used by multiple tracks.",
                        "track",
                        track_id,
                        track_id=track_id,
                    )
                )
        return issues

    def _release_issues(self) -> list[QualityIssue]:
        issues: list[QualityIssue] = []
        rows = self.conn.execute(
            """
            SELECT
                id,
                COALESCE(title, ''),
                COALESCE(primary_artist, ''),
                COALESCE(release_date, ''),
                COALESCE(upc, ''),
                COALESCE(catalog_number, ''),
                COALESCE(artwork_path, ''),
                COALESCE(barcode_validation_status, '')
            FROM Releases
            ORDER BY id
            """
        ).fetchall()
        for (
            release_id,
            title,
            primary_artist,
            release_date,
            upc,
            catalog_number,
            artwork_path,
            stored_barcode_status,
        ) in rows:
            if not str(title or "").strip():
                issues.append(
                    QualityIssue(
                        "missing_release_title",
                        "error",
                        "Missing Release Title",
                        "Release title is required for product-level metadata.",
                        "release",
                        int(release_id),
                        release_id=int(release_id),
                    )
                )
            if not str(primary_artist or "").strip():
                issues.append(
                    QualityIssue(
                        "missing_release_primary_artist",
                        "warning",
                        "Missing Release Primary Artist",
                        "Release primary artist should be filled for downstream exchange formats.",
                        "release",
                        int(release_id),
                        release_id=int(release_id),
                    )
                )
            if not str(release_date or "").strip():
                issues.append(
                    QualityIssue(
                        "missing_release_date",
                        "warning",
                        "Missing Release Date",
                        "Release date is empty.",
                        "release",
                        int(release_id),
                        release_id=int(release_id),
                    )
                )
            else:
                try:
                    datetime.strptime(str(release_date), "%Y-%m-%d")
                except Exception:
                    issues.append(
                        QualityIssue(
                            "invalid_release_date",
                            "warning",
                            "Invalid Release Date",
                            f"Release date '{release_date}' is not a valid YYYY-MM-DD value.",
                            "release",
                            int(release_id),
                            release_id=int(release_id),
                            fix_key="normalize_dates",
                        )
                    )
            if not str(upc or "").strip():
                issues.append(
                    QualityIssue(
                        "missing_release_upc",
                        "warning",
                        "Missing UPC/EAN",
                        "Release has no UPC/EAN yet.",
                        "release",
                        int(release_id),
                        release_id=int(release_id),
                    )
                )
            actual_status = barcode_validation_status(upc)
            if actual_status == "invalid_format":
                issues.append(
                    QualityIssue(
                        "invalid_release_upc_format",
                        "error",
                        "Invalid UPC/EAN Format",
                        "Release UPC/EAN must be 12 or 13 digits.",
                        "release",
                        int(release_id),
                        release_id=int(release_id),
                    )
                )
            elif actual_status == "invalid_checksum":
                issues.append(
                    QualityIssue(
                        "invalid_release_upc_checksum",
                        "error",
                        "Invalid UPC/EAN Checksum",
                        "Release UPC/EAN checksum is invalid.",
                        "release",
                        int(release_id),
                        release_id=int(release_id),
                    )
                )
            if actual_status != str(stored_barcode_status or "missing"):
                issues.append(
                    QualityIssue(
                        "release_barcode_status_out_of_sync",
                        "warning",
                        "Barcode Validation Status Out Of Sync",
                        "Stored barcode validation status can be regenerated safely.",
                        "release",
                        int(release_id),
                        release_id=int(release_id),
                        fix_key="regenerate_derived",
                    )
                )
            if not str(artwork_path or "").strip():
                issues.append(
                    QualityIssue(
                        "missing_release_artwork",
                        "warning",
                        "Missing Release Artwork",
                        "Release has no artwork reference.",
                        "release",
                        int(release_id),
                        release_id=int(release_id),
                    )
                )
            if catalog_number:
                duplicate = self.conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM Releases
                    WHERE catalog_number=?
                    """,
                    (catalog_number,),
                ).fetchone()
                if duplicate and int(duplicate[0] or 0) > 1:
                    issues.append(
                        QualityIssue(
                            "duplicate_release_catalog_number",
                            "warning",
                            "Duplicate Release Catalog Number",
                            f"Catalog# {catalog_number} is used by multiple releases.",
                            "release",
                            int(release_id),
                            release_id=int(release_id),
                        )
                    )

        duplicate_upc_rows = self.conn.execute(
            """
            SELECT
                upc,
                GROUP_CONCAT(id, ','),
                GROUP_CONCAT(COALESCE(title, ''), char(31))
            FROM Releases
            WHERE upc IS NOT NULL AND trim(upc) != ''
            GROUP BY upc
            HAVING COUNT(*) > 1
            """
        ).fetchall()
        for upc, ids, titles in duplicate_upc_rows:
            release_ids = [int(value) for value in str(ids or "").split(",") if value]
            release_titles = str(titles or "").split(chr(31))
            normalized_titles = {
                self._normalize_release_identity_text(title)
                for title in release_titles
                if self._normalize_release_identity_text(title)
            }
            shared_release_family = len(normalized_titles) == 1 and bool(normalized_titles)
            issue_type = "shared_release_upc" if shared_release_family else "duplicate_release_upc"
            severity = "info" if shared_release_family else "error"
            issue_title = (
                "Shared Release UPC/EAN" if shared_release_family else "Duplicate Release UPC/EAN"
            )
            details = (
                f"UPC/EAN {upc} is shared across multiple release rows for the same titled release. "
                "This is often intentional for remix packages, compilations, or other multi-artist editions."
                if shared_release_family
                else f"UPC/EAN {upc} is used by multiple releases."
            )
            for release_id in release_ids:
                issues.append(
                    QualityIssue(
                        issue_type,
                        severity,
                        issue_title,
                        details,
                        "release",
                        release_id,
                        release_id=release_id,
                    )
                )
        return issues

    def _media_issues(self) -> list[QualityIssue]:
        issues: list[QualityIssue] = []
        track_rows = self.conn.execute(
            """
            SELECT id, COALESCE(audio_file_path, ''), COALESCE(album_art_path, '')
            FROM Tracks
            ORDER BY id
            """
        ).fetchall()
        for track_id, audio_path, album_art_path in track_rows:
            for media_key, stored_path in (("audio", audio_path), ("album_art", album_art_path)):
                clean_path = str(stored_path or "").strip()
                if not clean_path or self.data_root is None:
                    continue
                path = Path(clean_path)
                if not path.is_absolute():
                    path = self.data_root / path
                if not path.exists():
                    issues.append(
                        QualityIssue(
                            "broken_media_reference",
                            "error",
                            f"Broken {media_key.replace('_', ' ').title()} Reference",
                            f"Managed {media_key.replace('_', ' ')} file is missing: {stored_path}",
                            "track",
                            int(track_id),
                            track_id=int(track_id),
                            fix_key="relink_media",
                        )
                    )

        release_rows = self.conn.execute(
            """
            SELECT id, COALESCE(artwork_path, '')
            FROM Releases
            ORDER BY id
            """
        ).fetchall()
        for release_id, artwork_path in release_rows:
            clean_path = str(artwork_path or "").strip()
            if not clean_path or self.data_root is None:
                continue
            path = Path(clean_path)
            if not path.is_absolute():
                path = self.data_root / path
            if not path.exists():
                issues.append(
                    QualityIssue(
                        "broken_release_artwork_reference",
                        "error",
                        "Broken Release Artwork Reference",
                        f"Release artwork file is missing: {artwork_path}",
                        "release",
                        int(release_id),
                        release_id=int(release_id),
                        fix_key="relink_media",
                    )
                )
        return issues

    def _ordering_issues(self) -> list[QualityIssue]:
        issues: list[QualityIssue] = []
        duplicate_order_rows = self.conn.execute(
            """
            SELECT release_id, disc_number, track_number, GROUP_CONCAT(track_id, ',')
            FROM ReleaseTracks
            GROUP BY release_id, disc_number, track_number
            HAVING COUNT(*) > 1
            """
        ).fetchall()
        for release_id, disc_number, track_number, track_ids in duplicate_order_rows:
            for track_id in [int(value) for value in str(track_ids or "").split(",") if value]:
                issues.append(
                    QualityIssue(
                        "disc_track_conflict",
                        "error",
                        "Disc/Track Number Conflict",
                        f"Release uses disc {disc_number}, track {track_number} more than once.",
                        "track",
                        track_id,
                        release_id=int(release_id),
                        track_id=track_id,
                    )
                )

        missing_placement_rows = self.conn.execute(
            """
            SELECT t.id
            FROM Tracks t
            LEFT JOIN ReleaseTracks rt ON rt.track_id = t.id
            WHERE t.album_id IS NOT NULL
              AND rt.track_id IS NULL
            """
        ).fetchall()
        for (track_id,) in missing_placement_rows:
            issues.append(
                QualityIssue(
                    "track_missing_release_order",
                    "warning",
                    "Track Missing Release Placement",
                    "Track appears album-associated but is not attached to any first-class release order.",
                    "track",
                    int(track_id),
                    track_id=int(track_id),
                )
            )
        return issues

    def _license_issues(self) -> list[QualityIssue]:
        rows = self.conn.execute(
            """
            SELECT l.id
            FROM Licenses l
            LEFT JOIN Tracks t ON t.id = l.track_id
            WHERE t.id IS NULL
            """
        ).fetchall()
        return [
            QualityIssue(
                "orphaned_license",
                "warning",
                "Orphaned License",
                "License record points to a missing track.",
                "license",
                int(license_id),
            )
            for (license_id,) in rows
        ]

    def _custom_field_issues(self) -> list[QualityIssue]:
        issues: list[QualityIssue] = []
        rows = self.conn.execute(
            """
            SELECT id, name, field_type, options
            FROM CustomFieldDefs
            WHERE active=1
            ORDER BY COALESCE(sort_order, 999999), id
            """
        ).fetchall()
        for field_id, name, field_type, options in rows:
            try:
                parsed_options = json.loads(str(options)) if options not in (None, "") else None
            except Exception:
                parsed_options = None
            required = False
            if isinstance(parsed_options, dict):
                required = bool(parsed_options.get("required"))
            if not required:
                continue
            if str(field_type or "text") in {"blob_image", "blob_audio"}:
                value_rows = self.conn.execute(
                    """
                    SELECT t.id
                    FROM Tracks t
                    LEFT JOIN CustomFieldValues cfv
                      ON cfv.track_id = t.id AND cfv.field_def_id = ?
                    WHERE cfv.size_bytes IS NULL OR cfv.size_bytes <= 0
                    ORDER BY t.id
                    """,
                    (int(field_id),),
                ).fetchall()
            else:
                value_rows = self.conn.execute(
                    """
                    SELECT t.id
                    FROM Tracks t
                    LEFT JOIN CustomFieldValues cfv
                      ON cfv.track_id = t.id AND cfv.field_def_id = ?
                    WHERE cfv.value IS NULL OR trim(cfv.value) = ''
                    ORDER BY t.id
                    """,
                    (int(field_id),),
                ).fetchall()
            for (track_id,) in value_rows:
                issues.append(
                    QualityIssue(
                        "missing_required_custom_field",
                        "warning",
                        "Missing Required Custom Field",
                        f"Track is missing required custom field '{name}'.",
                        "track",
                        int(track_id),
                        track_id=int(track_id),
                    )
                )
        return issues

    def export_csv(self, result: QualityScanResult, path: str | Path) -> None:
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "issue_type",
                    "severity",
                    "title",
                    "details",
                    "entity_type",
                    "entity_id",
                    "release_id",
                    "track_id",
                    "fix_key",
                ],
            )
            writer.writeheader()
            for issue in result.issues:
                writer.writerow(issue.__dict__)

    def export_json(self, result: QualityScanResult, path: str | Path) -> None:
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "generated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "counts_by_severity": result.counts_by_severity,
            "counts_by_type": result.counts_by_type,
            "issues": [issue.__dict__ for issue in result.issues],
        }
        output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def apply_fix(self, fix_key: str) -> str:
        if fix_key == "regenerate_derived":
            updated_tracks = 0
            updated_releases = 0
            with self.conn:
                rows = self.conn.execute("SELECT id, isrc FROM Tracks").fetchall()
                for track_id, isrc in rows:
                    compact = to_compact_isrc(str(isrc or ""))
                    self.conn.execute(
                        "UPDATE Tracks SET isrc_compact=? WHERE id=?",
                        (compact, int(track_id)),
                    )
                    updated_tracks += 1
                release_rows = self.conn.execute("SELECT id, upc FROM Releases").fetchall()
                for release_id, upc in release_rows:
                    self.conn.execute(
                        "UPDATE Releases SET barcode_validation_status=? WHERE id=?",
                        (barcode_validation_status(upc), int(release_id)),
                    )
                    updated_releases += 1
            return f"Regenerated derived values for {updated_tracks} track(s) and {updated_releases} release(s)."

        if fix_key == "normalize_dates":
            updated = 0
            with self.conn:
                for table_name in ("Tracks", "Releases"):
                    rows = self.conn.execute(
                        f"SELECT id, release_date FROM {table_name} WHERE release_date IS NOT NULL AND trim(release_date) != ''"
                    ).fetchall()
                    for row_id, raw_value in rows:
                        normalized = self._normalize_date(raw_value)
                        if normalized and normalized != raw_value:
                            self.conn.execute(
                                f"UPDATE {table_name} SET release_date=? WHERE id=?",
                                (normalized, int(row_id)),
                            )
                            updated += 1
            return f"Normalized {updated} date value(s)."

        if fix_key == "relink_media":
            relinked = 0
            if self.data_root is None:
                return "No data root is configured, so media relinking is unavailable."
            with self.conn:
                for table_name, column_name in (
                    ("Tracks", "audio_file_path"),
                    ("Tracks", "album_art_path"),
                    ("Releases", "artwork_path"),
                ):
                    rows = self.conn.execute(
                        f"SELECT id, {column_name} FROM {table_name} WHERE {column_name} IS NOT NULL AND trim({column_name}) != ''"
                    ).fetchall()
                    for row_id, stored_path in rows:
                        clean = str(stored_path or "").strip()
                        if not clean:
                            continue
                        path = Path(clean)
                        if not path.is_absolute():
                            path = self.data_root / path
                        if path.exists():
                            continue
                        match = self._find_media_by_name(Path(clean).name)
                        if match is None:
                            continue
                        new_path = str(match.relative_to(self.data_root))
                        self.conn.execute(
                            f"UPDATE {table_name} SET {column_name}=? WHERE id=?",
                            (new_path, int(row_id)),
                        )
                        relinked += 1
            return f"Relinked {relinked} media reference(s)."

        if fix_key == "fill_from_release":
            updated = 0
            with self.conn:
                rows = self.conn.execute(
                    """
                    SELECT
                        t.id,
                        COALESCE(t.release_date, ''),
                        COALESCE(t.upc, ''),
                        COALESCE(t.catalog_number, ''),
                        COALESCE(al.title, ''),
                        r.release_date,
                        r.upc,
                        r.catalog_number,
                        r.title
                    FROM Tracks t
                    LEFT JOIN Albums al ON al.id = t.album_id
                    LEFT JOIN ReleaseTracks rt ON rt.track_id = t.id
                    LEFT JOIN Releases r ON r.id = rt.release_id
                    ORDER BY t.id, rt.sequence_number
                    """
                ).fetchall()
                seen: set[int] = set()
                for row in rows:
                    track_id = int(row[0])
                    if track_id in seen:
                        continue
                    seen.add(track_id)
                    updates = {}
                    if not str(row[1] or "").strip() and str(row[5] or "").strip():
                        updates["release_date"] = row[5]
                    if not str(row[2] or "").strip() and str(row[6] or "").strip():
                        updates["upc"] = row[6]
                    if not str(row[3] or "").strip() and str(row[7] or "").strip():
                        updates["catalog_number"] = row[7]
                    if not str(row[4] or "").strip() and str(row[8] or "").strip():
                        album_id = self.track_service.get_or_create_album(
                            str(row[8]), cursor=self.conn.cursor()
                        )
                        updates["album_id"] = album_id
                    if updates:
                        assignments = ", ".join(f"{column}=?" for column in updates)
                        self.conn.execute(
                            f"UPDATE Tracks SET {assignments} WHERE id=?",
                            tuple(updates.values()) + (track_id,),
                        )
                        updated += 1
            return f"Filled blank track values from release metadata for {updated} track(s)."

        raise ValueError(f"Unknown quality fix: {fix_key}")

    @staticmethod
    def _normalize_date(value) -> str | None:
        text = str(value or "").strip()
        if not text:
            return None
        for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
            try:
                return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
            except Exception:
                continue
        return None

    def _find_media_by_name(self, basename: str) -> Path | None:
        if self.data_root is None:
            return None
        matches = sorted(path for path in self.data_root.rglob(basename) if path.is_file())
        return matches[0] if matches else None

"""Actionable catalog health checks and safe bulk fixes."""

from __future__ import annotations

import csv
import json
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path

from isrc_manager.assets import AssetService
from isrc_manager.contracts import (
    ContractDocumentPayload,
    ContractObligationPayload,
    ContractPartyPayload,
    ContractPayload,
    ContractService,
)
from isrc_manager.domain.codes import barcode_validation_status, to_compact_isrc
from isrc_manager.file_storage import STORAGE_MODE_MANAGED_FILE, infer_storage_mode
from isrc_manager.parties import PartyService
from isrc_manager.releases import ReleaseService
from isrc_manager.rights import RightsService
from isrc_manager.services.repertoire_status import RepertoireWorkflowService
from isrc_manager.services.tracks import TrackService
from isrc_manager.works import WorkContributorPayload, WorkPayload, WorkService

from .models import QualityIssue, QualityScanResult
from ..services.track_artist_sql import track_main_artist_join_sql


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
        self.party_service = PartyService(conn)
        self.work_service = WorkService(conn, party_service=self.party_service)
        self.contract_service = ContractService(
            conn, self.data_root, party_service=self.party_service
        )
        self.rights_service = RightsService(conn)
        self.asset_service = AssetService(conn, self.data_root)
        self.workflow_service = RepertoireWorkflowService(conn)

    def scan(self) -> QualityScanResult:
        issues: list[QualityIssue] = []
        issues.extend(self._track_metadata_issues())
        issues.extend(self._release_issues())
        issues.extend(self._media_issues())
        issues.extend(self._ordering_issues())
        issues.extend(self._release_backfill_issues())
        issues.extend(self._custom_field_issues())
        issues.extend(self._work_issues())
        issues.extend(self._contract_issues())
        issues.extend(self._rights_issues())
        issues.extend(self._party_issues())
        issues.extend(self._asset_registry_issues())
        issues.extend(self._repertoire_status_issues())
        counts_by_severity = Counter(issue.severity for issue in issues)
        counts_by_type = Counter(issue.issue_type for issue in issues)
        return QualityScanResult(
            issues=issues,
            counts_by_severity=dict(counts_by_severity),
            counts_by_type=dict(counts_by_type),
        )

    @staticmethod
    def _issue_track_id(issue: QualityIssue | None) -> int | None:
        if issue is None:
            return None
        if issue.track_id is not None:
            return int(issue.track_id)
        if issue.entity_type == "track" and issue.entity_id is not None:
            return int(issue.entity_id)
        return None

    @staticmethod
    def _issue_release_id(issue: QualityIssue | None) -> int | None:
        if issue is None:
            return None
        if issue.release_id is not None:
            return int(issue.release_id)
        if issue.entity_type == "release" and issue.entity_id is not None:
            return int(issue.entity_id)
        return None

    def _track_release_backfill_candidates(
        self, *, track_ids: set[int] | None = None
    ) -> list[dict[str, object]]:
        params: list[object] = []
        where_sql = ""
        if track_ids:
            placeholders = ", ".join("?" for _ in track_ids)
            where_sql = f"WHERE t.id IN ({placeholders})"
            params.extend(sorted(int(track_id) for track_id in track_ids))
        rows = self.conn.execute(
            f"""
            SELECT
                t.id,
                COALESCE(t.track_title, ''),
                COALESCE(t.release_date, ''),
                COALESCE(t.upc, ''),
                COALESCE(t.catalog_number, ''),
                COALESCE(al.title, ''),
                r.id,
                COALESCE(r.release_date, ''),
                COALESCE(r.upc, ''),
                COALESCE(r.catalog_number, ''),
                COALESCE(r.title, '')
            FROM Tracks t
            LEFT JOIN Albums al ON al.id = t.album_id
            JOIN ReleaseTracks rt ON rt.track_id = t.id
            JOIN Releases r ON r.id = rt.release_id
            {where_sql}
            ORDER BY t.id, COALESCE(rt.sequence_number, 999999), r.id
            """,
            tuple(params),
        ).fetchall()
        seen: set[int] = set()
        candidates: list[dict[str, object]] = []
        for row in rows:
            track_id = int(row[0])
            if track_id in seen:
                continue
            seen.add(track_id)
            fill_values: dict[str, str] = {}
            if not str(row[2] or "").strip() and str(row[7] or "").strip():
                fill_values["release_date"] = str(row[7])
            if not str(row[3] or "").strip() and str(row[8] or "").strip():
                fill_values["upc"] = str(row[8])
            if not str(row[4] or "").strip() and str(row[9] or "").strip():
                fill_values["catalog_number"] = str(row[9])
            if not str(row[5] or "").strip() and str(row[10] or "").strip():
                fill_values["album_title"] = str(row[10])
            if not fill_values:
                continue
            candidates.append(
                {
                    "track_id": track_id,
                    "track_title": str(row[1] or ""),
                    "release_id": int(row[6]),
                    "release_title": str(row[10] or ""),
                    "fill_values": fill_values,
                }
            )
        return candidates

    def _track_metadata_issues(self) -> list[QualityIssue]:
        issues: list[QualityIssue] = []
        main_artist_join_sql, main_artist_name_expr = track_main_artist_join_sql(
            self.conn,
            track_alias="t",
            artist_alias="main_artist",
        )
        rows = self.conn.execute(
            f"""
            SELECT
                t.id,
                COALESCE(t.track_title, ''),
                COALESCE({main_artist_name_expr}, ''),
                COALESCE(t.isrc, ''),
                COALESCE(t.release_date, ''),
                COALESCE(t.audio_file_path, ''),
                COALESCE(t.audio_file_storage_mode, ''),
                CASE WHEN t.audio_file_blob IS NOT NULL THEN 1 ELSE 0 END,
                COALESCE(t.upc, ''),
                COALESCE(t.catalog_number, ''),
                COALESCE(t.isrc_compact, '')
            FROM Tracks t
            {main_artist_join_sql}
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
            audio_file_storage_mode,
            audio_blob_present,
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
            has_audio = bool(str(audio_file_path or "").strip()) or bool(
                int(audio_blob_present or 0)
            )
            if not has_audio:
                issues.append(
                    QualityIssue(
                        "missing_audio_attachment",
                        "warning",
                        "Missing Audio Attachment",
                        "No audio file is attached to this track.",
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
                GROUP_CONCAT(COALESCE(title, ''), char(31)),
                GROUP_CONCAT(COALESCE(release_type, ''), char(31))
            FROM Releases
            WHERE upc IS NOT NULL AND trim(upc) != ''
            GROUP BY upc
            HAVING COUNT(*) > 1
            """
        ).fetchall()
        for upc, ids, titles, release_types in duplicate_upc_rows:
            release_ids = [int(value) for value in str(ids or "").split(",") if value]
            release_titles = str(titles or "").split(chr(31))
            parsed_release_types = str(release_types or "").split(chr(31))
            shared_release_family = self.release_service.releases_share_upc_family(
                list(zip(release_titles, parsed_release_types, strict=False))
            )
            issue_type = "shared_release_upc" if shared_release_family else "duplicate_release_upc"
            severity = "info" if shared_release_family else "error"
            issue_title = (
                "Shared Release UPC/EAN" if shared_release_family else "Duplicate Release UPC/EAN"
            )
            details = (
                f"UPC/EAN {upc} is shared across multiple release rows for the same release family. "
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
            SELECT
                id,
                COALESCE(audio_file_path, ''),
                COALESCE(audio_file_storage_mode, ''),
                CASE WHEN audio_file_blob IS NOT NULL THEN 1 ELSE 0 END,
                COALESCE(album_art_path, ''),
                COALESCE(album_art_storage_mode, ''),
                CASE WHEN album_art_blob IS NOT NULL THEN 1 ELSE 0 END
            FROM Tracks
            ORDER BY id
            """
        ).fetchall()
        for (
            track_id,
            audio_path,
            audio_mode,
            audio_blob_present,
            album_art_path,
            album_art_mode,
            album_art_blob_present,
        ) in track_rows:
            for media_key, stored_path, storage_mode, blob_present in (
                ("audio", audio_path, audio_mode, audio_blob_present),
                ("album_art", album_art_path, album_art_mode, album_art_blob_present),
            ):
                clean_path = str(stored_path or "").strip()
                if not clean_path or self.data_root is None:
                    continue
                inferred_mode = infer_storage_mode(
                    explicit_mode=storage_mode,
                    stored_path=clean_path,
                    blob_value=b"\x00" if int(blob_present or 0) else None,
                )
                if inferred_mode != STORAGE_MODE_MANAGED_FILE:
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
            SELECT
                id,
                COALESCE(artwork_path, ''),
                COALESCE(artwork_storage_mode, ''),
                CASE WHEN artwork_blob IS NOT NULL THEN 1 ELSE 0 END
            FROM Releases
            ORDER BY id
            """
        ).fetchall()
        for release_id, artwork_path, storage_mode, blob_present in release_rows:
            clean_path = str(artwork_path or "").strip()
            if not clean_path or self.data_root is None:
                continue
            inferred_mode = infer_storage_mode(
                explicit_mode=storage_mode,
                stored_path=clean_path,
                blob_value=b"\x00" if int(blob_present or 0) else None,
            )
            if inferred_mode != STORAGE_MODE_MANAGED_FILE:
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

    def _release_backfill_issues(self) -> list[QualityIssue]:
        issues: list[QualityIssue] = []
        for candidate in self._track_release_backfill_candidates():
            field_labels = [
                {
                    "release_date": "release date",
                    "upc": "UPC/EAN",
                    "catalog_number": "catalog number",
                    "album_title": "album title",
                }[field_name]
                for field_name in candidate["fill_values"].keys()
            ]
            release_title = str(candidate["release_title"] or "").strip() or "linked release"
            issues.append(
                QualityIssue(
                    "track_can_fill_from_release",
                    "info",
                    "Track Can Inherit Release Metadata",
                    (
                        f"Track '{candidate['track_title']}' can fill blank "
                        f"{', '.join(field_labels)} from release '{release_title}'."
                    ),
                    "track",
                    int(candidate["track_id"]),
                    release_id=int(candidate["release_id"]),
                    track_id=int(candidate["track_id"]),
                    fix_key="fill_from_release",
                )
            )
        return issues

    def _work_payload_from_detail(self, detail) -> WorkPayload:
        return WorkPayload(
            title=detail.work.title,
            alternate_titles=list(detail.work.alternate_titles),
            version_subtitle=detail.work.version_subtitle,
            language=detail.work.language,
            lyrics_flag=detail.work.lyrics_flag,
            instrumental_flag=detail.work.instrumental_flag,
            genre_notes=detail.work.genre_notes,
            iswc=detail.work.iswc,
            registration_number=detail.work.registration_number,
            work_status=detail.work.work_status,
            metadata_complete=detail.work.metadata_complete,
            contract_signed=detail.work.contract_signed,
            rights_verified=detail.work.rights_verified,
            notes=detail.work.notes,
            profile_name=detail.work.profile_name,
            contributors=[
                WorkContributorPayload(
                    role=item.role,
                    name=str(item.display_name or ""),
                    share_percent=item.share_percent,
                    role_share_percent=item.role_share_percent,
                    party_id=item.party_id,
                    notes=item.notes,
                )
                for item in detail.contributors
            ],
            track_ids=list(detail.track_ids),
        )

    def _work_issues(self) -> list[QualityIssue]:
        issues: list[QualityIssue] = []
        for work in self.work_service.list_works():
            detail = self.work_service.fetch_work_detail(work.id)
            if detail is None:
                continue
            validation_issues = self.work_service.validate_work(
                self._work_payload_from_detail(detail),
                work_id=work.id,
            )
            for issue in validation_issues:
                issue_type = {
                    "contributors": "work_missing_creators",
                    "share_percent": "invalid_work_split_total",
                    "role_share_percent": "invalid_work_role_split_total",
                    "iswc": "duplicate_work_iswc",
                }.get(issue.field_name, "work_validation_issue")
                issues.append(
                    QualityIssue(
                        issue_type,
                        issue.severity,
                        issue.message,
                        issue.message,
                        "work",
                        work.id,
                    )
                )
            linked_track_count = int(
                self.conn.execute(
                    "SELECT COUNT(*) FROM Tracks WHERE work_id=?",
                    (int(work.id),),
                ).fetchone()[0]
                or 0
            )
            if linked_track_count == 0:
                issues.append(
                    QualityIssue(
                        "orphaned_work_recording_link",
                        "warning",
                        "Work Has No Linked Recording",
                        "This work is not currently linked to any track/recording.",
                        "work",
                        work.id,
                    )
                )

        duplicate_rows = self.conn.execute(
            """
            SELECT iswc, GROUP_CONCAT(id, ',')
            FROM Works
            WHERE iswc IS NOT NULL AND trim(iswc) != ''
            GROUP BY iswc
            HAVING COUNT(*) > 1
            """
        ).fetchall()
        for iswc, ids in duplicate_rows:
            for work_id in [int(value) for value in str(ids or "").split(",") if value]:
                issues.append(
                    QualityIssue(
                        "duplicate_work_iswc",
                        "warning",
                        "Duplicate Work ISWC",
                        f"ISWC {iswc} appears on more than one work.",
                        "work",
                        work_id,
                    )
                )
        track_rows = self.conn.execute(
            """
            SELECT id, track_title
            FROM Tracks
            WHERE (
                COALESCE(iswc, '') != ''
                OR COALESCE(composer, '') != ''
                OR COALESCE(publisher, '') != ''
                OR COALESCE(buma_work_number, '') != ''
            )
              AND NOT EXISTS (
                  SELECT 1 FROM Works w WHERE w.id = Tracks.work_id
              )
            ORDER BY id
            """
        ).fetchall()
        for track_id, title in track_rows:
            issues.append(
                QualityIssue(
                    "track_missing_linked_work",
                    "warning",
                    "Track Missing Linked Work",
                    f"Track '{title}' contains composition metadata but is not linked to any first-class work record.",
                    "track",
                    int(track_id),
                    track_id=int(track_id),
                )
            )
        return issues

    def _contract_issues(self) -> list[QualityIssue]:
        issues: list[QualityIssue] = []
        for contract in self.contract_service.list_contracts():
            detail = self.contract_service.fetch_contract_detail(contract.id)
            if detail is None:
                continue
            validation_issues = self.contract_service.validate_contract(
                ContractPayload(
                    title=contract.title,
                    contract_type=contract.contract_type,
                    draft_date=contract.draft_date,
                    signature_date=contract.signature_date,
                    effective_date=contract.effective_date,
                    start_date=contract.start_date,
                    end_date=contract.end_date,
                    renewal_date=contract.renewal_date,
                    notice_deadline=contract.notice_deadline,
                    option_periods=contract.option_periods,
                    reversion_date=contract.reversion_date,
                    termination_date=contract.termination_date,
                    status=contract.status,
                    supersedes_contract_id=contract.supersedes_contract_id,
                    superseded_by_contract_id=contract.superseded_by_contract_id,
                    summary=contract.summary,
                    notes=contract.notes,
                    profile_name=contract.profile_name,
                    parties=[
                        ContractPartyPayload(
                            party_id=item.party_id,
                            name=item.party_name,
                            role_label=item.role_label,
                            is_primary=item.is_primary,
                            notes=item.notes,
                        )
                        for item in detail.parties
                    ],
                    obligations=[
                        ContractObligationPayload(
                            obligation_id=item.id,
                            obligation_type=item.obligation_type,
                            title=item.title,
                            due_date=item.due_date,
                            follow_up_date=item.follow_up_date,
                            reminder_date=item.reminder_date,
                            completed=item.completed,
                            completed_at=item.completed_at,
                            notes=item.notes,
                        )
                        for item in detail.obligations
                    ],
                    documents=[
                        ContractDocumentPayload(
                            document_id=item.id,
                            title=item.title,
                            document_type=item.document_type,
                            version_label=item.version_label,
                            created_date=item.created_date,
                            received_date=item.received_date,
                            signed_status=item.signed_status,
                            signed_by_all_parties=item.signed_by_all_parties,
                            active_flag=item.active_flag,
                            supersedes_document_id=item.supersedes_document_id,
                            superseded_by_document_id=item.superseded_by_document_id,
                            stored_path=item.file_path,
                            filename=item.filename,
                            checksum_sha256=item.checksum_sha256,
                            notes=item.notes,
                        )
                        for item in detail.documents
                    ],
                    work_ids=list(detail.work_ids),
                    track_ids=list(detail.track_ids),
                    release_ids=list(detail.release_ids),
                )
            )
            for issue in validation_issues:
                issue_type = {
                    "signature_date": "contract_missing_signature",
                    "parties": "contract_missing_parties",
                    "documents": "contract_document_chain_issue",
                }.get(issue.field_name, "contract_validation_issue")
                issues.append(
                    QualityIssue(
                        issue_type,
                        issue.severity,
                        issue.message,
                        issue.message,
                        "contract",
                        contract.id,
                    )
                )
            if not detail.parties:
                issues.append(
                    QualityIssue(
                        "contract_missing_parties",
                        "warning",
                        "Contract Missing Parties",
                        "Contract is not linked to any party records.",
                        "contract",
                        contract.id,
                    )
                )
            if contract.status == "active" and not (
                detail.work_ids or detail.track_ids or detail.release_ids
            ):
                issues.append(
                    QualityIssue(
                        "active_contract_missing_assets",
                        "warning",
                        "Active Contract Missing Linked Assets",
                        "Active contract does not link to any works, tracks, or releases.",
                        "contract",
                        contract.id,
                    )
                )
            if contract.status == "active" and not any(
                doc.document_type == "signed_agreement"
                and doc.active_flag
                and doc.signed_by_all_parties
                for doc in detail.documents
            ):
                issues.append(
                    QualityIssue(
                        "contract_missing_signed_final_document",
                        "warning",
                        "Contract Missing Signed Final Document",
                        "Active contract does not have an active signed-agreement document marked as signed by all parties.",
                        "contract",
                        contract.id,
                    )
                )
        for deadline in self.contract_service.upcoming_deadlines(within_days=45):
            issues.append(
                QualityIssue(
                    "contract_upcoming_deadline",
                    "warning",
                    "Upcoming Contract Deadline",
                    f"{deadline.date_field.replace('_', ' ').title()} is due on {deadline.due_date}.",
                    "contract",
                    deadline.contract_id,
                )
            )
        expired_rows = self.conn.execute(
            """
            SELECT id, title, end_date
            FROM Contracts
            WHERE status='active'
              AND end_date IS NOT NULL
              AND trim(end_date) != ''
              AND end_date < date('now')
            ORDER BY end_date
            """
        ).fetchall()
        for contract_id, title, end_date in expired_rows:
            issues.append(
                QualityIssue(
                    "contract_expired",
                    "warning",
                    "Contract End Date Has Passed",
                    f"Contract '{title}' ended on {end_date} but still has active status.",
                    "contract",
                    int(contract_id),
                )
            )
        return issues

    def _rights_issues(self) -> list[QualityIssue]:
        issues: list[QualityIssue] = []
        for right in self.rights_service.rights_missing_source_contract():
            issues.append(
                QualityIssue(
                    "rights_missing_source_contract",
                    "warning",
                    "Rights Grant Missing Source Contract",
                    "Active or exclusive rights grant is missing a source contract reference.",
                    "right",
                    right.id,
                )
            )
        for conflict in self.rights_service.detect_conflicts():
            issues.append(
                QualityIssue(
                    "overlapping_exclusive_rights",
                    "error",
                    "Overlapping Exclusive Rights",
                    conflict.message,
                    "right",
                    conflict.left_right_id,
                )
            )
        return issues

    def _party_issues(self) -> list[QualityIssue]:
        issues: list[QualityIssue] = []
        for duplicate in self.party_service.detect_duplicates():
            issues.append(
                QualityIssue(
                    "duplicate_party",
                    "warning",
                    "Duplicate or Ambiguous Party",
                    duplicate.detail,
                    "party",
                    duplicate.left_party_id,
                )
            )
        return issues

    def _asset_registry_issues(self) -> list[QualityIssue]:
        issues: list[QualityIssue] = []
        for issue in self.asset_service.validate_assets():
            issues.append(
                QualityIssue(
                    issue.issue_type,
                    issue.severity,
                    issue.message,
                    issue.message,
                    "asset",
                    issue.asset_id,
                )
            )
        return issues

    def _repertoire_status_issues(self) -> list[QualityIssue]:
        issues: list[QualityIssue] = []
        for table_name, entity_type, title_column, status_column in (
            ("Works", "work", "title", "work_status"),
            ("Tracks", "track", "track_title", "repertoire_status"),
            ("Releases", "release", "title", "repertoire_status"),
        ):
            rows = self.conn.execute(
                f"""
                SELECT id, COALESCE({title_column}, ''), COALESCE({status_column}, ''), metadata_complete
                FROM {table_name}
                WHERE COALESCE({status_column}, '') IN ('blocked', 'metadata_incomplete')
                   OR metadata_complete = 0
                ORDER BY id
                """
            ).fetchall()
            for entity_id, title, status, metadata_complete in rows:
                issues.append(
                    QualityIssue(
                        "repertoire_blocked_or_incomplete",
                        "info" if str(status or "") == "blocked" else "warning",
                        "Blocked or Incomplete Repertoire Item",
                        (
                            f"{entity_type.title()} '{title}' is marked as blocked."
                            if str(status or "") == "blocked"
                            else f"{entity_type.title()} '{title}' is still incomplete."
                        ),
                        entity_type,
                        int(entity_id),
                        release_id=int(entity_id) if entity_type == "release" else None,
                        track_id=int(entity_id) if entity_type == "track" else None,
                    )
                )
                if not metadata_complete:
                    readiness = self.workflow_service.readiness_snapshot(
                        entity_type, int(entity_id)
                    )
                    missing_checks = [
                        key.replace("_", " ") for key, value in readiness.items() if value is False
                    ]
                    if missing_checks:
                        issues.append(
                            QualityIssue(
                                "repertoire_readiness_gap",
                                "warning",
                                "Repertoire Readiness Gap",
                                f"{entity_type.title()} '{title}' is missing: {', '.join(missing_checks)}.",
                                entity_type,
                                int(entity_id),
                                release_id=int(entity_id) if entity_type == "release" else None,
                                track_id=int(entity_id) if entity_type == "track" else None,
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

    def apply_fix(self, fix_key: str, *, issue: QualityIssue | None = None) -> str:
        if fix_key == "regenerate_derived":
            updated_tracks = 0
            updated_releases = 0
            with self.conn:
                track_id = self._issue_track_id(issue)
                if track_id is None:
                    rows = self.conn.execute("SELECT id, isrc FROM Tracks").fetchall()
                else:
                    rows = self.conn.execute(
                        "SELECT id, isrc FROM Tracks WHERE id=?",
                        (int(track_id),),
                    ).fetchall()
                for track_id, isrc in rows:
                    compact = to_compact_isrc(str(isrc or ""))
                    self.conn.execute(
                        "UPDATE Tracks SET isrc_compact=? WHERE id=?",
                        (compact, int(track_id)),
                    )
                    updated_tracks += 1
                release_id = self._issue_release_id(issue)
                if release_id is None:
                    release_rows = self.conn.execute("SELECT id, upc FROM Releases").fetchall()
                else:
                    release_rows = self.conn.execute(
                        "SELECT id, upc FROM Releases WHERE id=?",
                        (int(release_id),),
                    ).fetchall()
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
                scopes = [
                    ("Tracks", self._issue_track_id(issue)),
                    ("Releases", self._issue_release_id(issue)),
                ]
                if issue is None:
                    scopes = [("Tracks", None), ("Releases", None)]
                for table_name, row_id in scopes:
                    if row_id is None:
                        rows = self.conn.execute(
                            f"SELECT id, release_date FROM {table_name} WHERE release_date IS NOT NULL AND trim(release_date) != ''"
                        ).fetchall()
                    else:
                        rows = self.conn.execute(
                            f"SELECT id, release_date FROM {table_name} WHERE id=? AND release_date IS NOT NULL AND trim(release_date) != ''",
                            (int(row_id),),
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
            track_id = self._issue_track_id(issue)
            release_id = self._issue_release_id(issue)
            with self.conn:
                media_targets: list[tuple[str, str, int | None]] = []
                if issue is None:
                    media_targets = [
                        ("Tracks", "audio_file_path", None),
                        ("Tracks", "album_art_path", None),
                        ("Releases", "artwork_path", None),
                    ]
                elif track_id is not None:
                    issue_title = str(issue.title or "").casefold()
                    if "audio" in issue_title:
                        media_targets = [("Tracks", "audio_file_path", int(track_id))]
                    elif "album art" in issue_title:
                        media_targets = [("Tracks", "album_art_path", int(track_id))]
                    else:
                        media_targets = [
                            ("Tracks", "audio_file_path", int(track_id)),
                            ("Tracks", "album_art_path", int(track_id)),
                        ]
                elif release_id is not None:
                    media_targets = [("Releases", "artwork_path", int(release_id))]

                for table_name, column_name, row_id in media_targets:
                    if row_id is None:
                        rows = self.conn.execute(
                            f"SELECT id, {column_name} FROM {table_name} WHERE {column_name} IS NOT NULL AND trim({column_name}) != ''"
                        ).fetchall()
                    else:
                        rows = self.conn.execute(
                            f"SELECT id, {column_name} FROM {table_name} WHERE id=? AND {column_name} IS NOT NULL AND trim({column_name}) != ''",
                            (int(row_id),),
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
                track_scope = self._issue_track_id(issue)
                candidates = self._track_release_backfill_candidates(
                    track_ids={int(track_scope)} if track_scope is not None else None
                )
                for candidate in candidates:
                    track_id = int(candidate["track_id"])
                    fill_values = dict(candidate["fill_values"])
                    updates = {}
                    if fill_values.get("release_date"):
                        updates["release_date"] = fill_values["release_date"]
                    if fill_values.get("upc"):
                        updates["upc"] = fill_values["upc"]
                    if fill_values.get("catalog_number"):
                        updates["catalog_number"] = fill_values["catalog_number"]
                    if fill_values.get("album_title"):
                        album_id = self.track_service.get_or_create_album(
                            str(fill_values["album_title"]),
                            cursor=self.conn.cursor(),
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

"""Managed asset version registry for tracks and releases."""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
import time
from dataclasses import asdict
from pathlib import Path

try:
    from mutagen import File as MutagenFile
except Exception:  # pragma: no cover - optional at runtime in constrained environments
    MutagenFile = None

from isrc_manager.domain.repertoire import clean_text

from .models import (
    ASSET_TYPE_CHOICES,
    AssetValidationIssue,
    AssetVersionPayload,
    AssetVersionRecord,
)


class AssetService:
    """Owns deliverable/asset registry rows and managed files."""

    def __init__(self, conn: sqlite3.Connection, data_root: str | Path | None = None):
        self.conn = conn
        self.data_root = Path(data_root) if data_root is not None else None
        self.asset_root = self.data_root / "asset_registry" if self.data_root is not None else None

    @staticmethod
    def _clean_type(value: str | None) -> str:
        clean = str(value or "other").strip().lower().replace(" ", "_")
        if clean not in ASSET_TYPE_CHOICES:
            return "other"
        return clean

    @staticmethod
    def _row_to_record(row) -> AssetVersionRecord:
        return AssetVersionRecord(
            id=int(row[0]),
            asset_type=str(row[1] or "other"),
            filename=str(row[2] or ""),
            stored_path=clean_text(row[3]),
            checksum_sha256=clean_text(row[4]),
            duration_sec=int(row[5]) if row[5] is not None else None,
            sample_rate=int(row[6]) if row[6] is not None else None,
            bit_depth=int(row[7]) if row[7] is not None else None,
            format=clean_text(row[8]),
            derived_from_asset_id=int(row[9]) if row[9] is not None else None,
            approved_for_use=bool(row[10]),
            primary_flag=bool(row[11]),
            version_status=clean_text(row[12]),
            notes=clean_text(row[13]),
            track_id=int(row[14]) if row[14] is not None else None,
            release_id=int(row[15]) if row[15] is not None else None,
            created_at=clean_text(row[16]),
            updated_at=clean_text(row[17]),
        )

    def resolve_asset_path(self, stored_path: str | None) -> Path | None:
        clean_path = clean_text(stored_path)
        if not clean_path:
            return None
        path = Path(clean_path)
        if path.is_absolute():
            return path
        if self.data_root is None:
            return None
        return self.data_root / path

    def _hash_file(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _extract_media_metadata(self, path: Path) -> dict[str, int | None]:
        duration_sec = None
        sample_rate = None
        bit_depth = None
        if MutagenFile is None:
            return {
                "duration_sec": duration_sec,
                "sample_rate": sample_rate,
                "bit_depth": bit_depth,
            }
        try:
            media = MutagenFile(str(path))
            info = getattr(media, "info", None)
            if info is not None:
                length = getattr(info, "length", None)
                if length is not None:
                    duration_sec = int(round(float(length)))
                sample_rate_value = getattr(info, "sample_rate", None)
                if sample_rate_value is not None:
                    sample_rate = int(sample_rate_value)
                bit_depth_value = getattr(info, "bits_per_sample", None)
                if bit_depth_value is not None:
                    bit_depth = int(bit_depth_value)
        except Exception:
            pass
        return {
            "duration_sec": duration_sec,
            "sample_rate": sample_rate,
            "bit_depth": bit_depth,
        }

    def _write_asset_file(
        self, source_path: str | Path
    ) -> tuple[str, str, str, dict[str, int | None]]:
        source = Path(source_path)
        if not source.exists():
            raise FileNotFoundError(source)
        if self.asset_root is None or self.data_root is None:
            raise ValueError("Asset storage is not configured.")
        suffix = source.suffix.lower()
        subdir = (
            "audio" if suffix in {".wav", ".mp3", ".flac", ".aif", ".aiff", ".m4a"} else "files"
        )
        if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
            subdir = "images"
        destination_dir = self.asset_root / subdir
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / f"{int(time.time_ns())}_{source.name}"
        shutil.copy2(source, destination)
        return (
            str(destination.relative_to(self.data_root)),
            source.name,
            self._hash_file(destination),
            self._extract_media_metadata(destination),
        )

    def validate_asset_payload(self, payload: AssetVersionPayload) -> list[str]:
        errors: list[str] = []
        if not any((payload.track_id, payload.release_id)):
            errors.append("Assets must link to either a track or a release.")
        if not clean_text(payload.filename) and not clean_text(payload.source_path):
            errors.append("Assets require a filename or a source file.")
        return errors

    def create_asset(self, payload: AssetVersionPayload) -> int:
        errors = self.validate_asset_payload(payload)
        if errors:
            raise ValueError("\n".join(errors))
        stored_path = clean_text(payload.stored_path)
        filename = clean_text(payload.filename)
        checksum = clean_text(payload.checksum_sha256)
        duration_sec = payload.duration_sec
        sample_rate = payload.sample_rate
        bit_depth = payload.bit_depth
        if clean_text(payload.source_path):
            stored_path, filename, checksum, meta = self._write_asset_file(str(payload.source_path))
            duration_sec = duration_sec if duration_sec is not None else meta["duration_sec"]
            sample_rate = sample_rate if sample_rate is not None else meta["sample_rate"]
            bit_depth = bit_depth if bit_depth is not None else meta["bit_depth"]
        with self.conn:
            cursor = self.conn.execute(
                """
                INSERT INTO AssetVersions (
                    track_id,
                    release_id,
                    asset_type,
                    filename,
                    stored_path,
                    checksum_sha256,
                    duration_sec,
                    sample_rate,
                    bit_depth,
                    format,
                    derived_from_asset_id,
                    approved_for_use,
                    primary_flag,
                    version_status,
                    notes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.track_id,
                    payload.release_id,
                    self._clean_type(payload.asset_type),
                    str(filename or ""),
                    stored_path,
                    checksum,
                    duration_sec,
                    sample_rate,
                    bit_depth,
                    clean_text(payload.format) or (Path(filename or "").suffix.lstrip(".") or None),
                    payload.derived_from_asset_id,
                    1 if payload.approved_for_use else 0,
                    1 if payload.primary_flag else 0,
                    clean_text(payload.version_status),
                    clean_text(payload.notes),
                ),
            )
            asset_id = int(cursor.lastrowid)
            if payload.primary_flag:
                self.mark_primary(asset_id)
            return asset_id

    def update_asset(self, asset_id: int, payload: AssetVersionPayload) -> None:
        errors = self.validate_asset_payload(payload)
        if errors:
            raise ValueError("\n".join(errors))
        existing = self.fetch_asset(int(asset_id))
        if existing is None:
            raise ValueError("Asset not found.")
        stored_path = clean_text(payload.stored_path) or existing.stored_path
        filename = clean_text(payload.filename) or existing.filename
        checksum = clean_text(payload.checksum_sha256) or existing.checksum_sha256
        duration_sec = (
            payload.duration_sec if payload.duration_sec is not None else existing.duration_sec
        )
        sample_rate = (
            payload.sample_rate if payload.sample_rate is not None else existing.sample_rate
        )
        bit_depth = payload.bit_depth if payload.bit_depth is not None else existing.bit_depth
        if clean_text(payload.source_path):
            stored_path, filename, checksum, meta = self._write_asset_file(str(payload.source_path))
            duration_sec = (
                payload.duration_sec if payload.duration_sec is not None else meta["duration_sec"]
            )
            sample_rate = (
                payload.sample_rate if payload.sample_rate is not None else meta["sample_rate"]
            )
            bit_depth = payload.bit_depth if payload.bit_depth is not None else meta["bit_depth"]
        with self.conn:
            self.conn.execute(
                """
                UPDATE AssetVersions
                SET track_id=?,
                    release_id=?,
                    asset_type=?,
                    filename=?,
                    stored_path=?,
                    checksum_sha256=?,
                    duration_sec=?,
                    sample_rate=?,
                    bit_depth=?,
                    format=?,
                    derived_from_asset_id=?,
                    approved_for_use=?,
                    primary_flag=?,
                    version_status=?,
                    notes=?,
                    updated_at=datetime('now')
                WHERE id=?
                """,
                (
                    payload.track_id,
                    payload.release_id,
                    self._clean_type(payload.asset_type),
                    str(filename or ""),
                    stored_path,
                    checksum,
                    duration_sec,
                    sample_rate,
                    bit_depth,
                    clean_text(payload.format) or existing.format,
                    payload.derived_from_asset_id,
                    1 if payload.approved_for_use else 0,
                    1 if payload.primary_flag else 0,
                    clean_text(payload.version_status),
                    clean_text(payload.notes),
                    int(asset_id),
                ),
            )
            if payload.primary_flag:
                self.mark_primary(int(asset_id))

    def mark_primary(self, asset_id: int) -> None:
        asset = self.fetch_asset(int(asset_id))
        if asset is None:
            raise ValueError("Asset not found.")
        with self.conn:
            if asset.track_id is not None:
                self.conn.execute(
                    "UPDATE AssetVersions SET primary_flag=0 WHERE track_id=?",
                    (int(asset.track_id),),
                )
            if asset.release_id is not None:
                self.conn.execute(
                    "UPDATE AssetVersions SET primary_flag=0 WHERE release_id=?",
                    (int(asset.release_id),),
                )
            self.conn.execute(
                "UPDATE AssetVersions SET primary_flag=1 WHERE id=?",
                (int(asset_id),),
            )

    def fetch_asset(self, asset_id: int) -> AssetVersionRecord | None:
        row = self.conn.execute(
            """
            SELECT
                id,
                asset_type,
                filename,
                stored_path,
                checksum_sha256,
                duration_sec,
                sample_rate,
                bit_depth,
                format,
                derived_from_asset_id,
                approved_for_use,
                primary_flag,
                version_status,
                notes,
                track_id,
                release_id,
                created_at,
                updated_at
            FROM AssetVersions
            WHERE id=?
            """,
            (int(asset_id),),
        ).fetchone()
        return self._row_to_record(row) if row else None

    def list_assets(
        self,
        *,
        track_id: int | None = None,
        release_id: int | None = None,
        search_text: str | None = None,
    ) -> list[AssetVersionRecord]:
        clauses: list[str] = []
        params: list[object] = []
        if track_id is not None:
            clauses.append("track_id=?")
            params.append(int(track_id))
        if release_id is not None:
            clauses.append("release_id=?")
            params.append(int(release_id))
        clean_search = clean_text(search_text)
        if clean_search:
            like = f"%{clean_search}%"
            clauses.append(
                "(filename LIKE ? OR COALESCE(asset_type, '') LIKE ? OR COALESCE(version_status, '') LIKE ?)"
            )
            params.extend([like, like, like])
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.conn.execute(
            f"""
            SELECT
                id,
                asset_type,
                filename,
                stored_path,
                checksum_sha256,
                duration_sec,
                sample_rate,
                bit_depth,
                format,
                derived_from_asset_id,
                approved_for_use,
                primary_flag,
                version_status,
                notes,
                track_id,
                release_id,
                created_at,
                updated_at
            FROM AssetVersions
            {where}
            ORDER BY COALESCE(track_id, release_id), primary_flag DESC, asset_type, id
            """,
            params,
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def delete_asset(self, asset_id: int) -> None:
        asset = self.fetch_asset(int(asset_id))
        with self.conn:
            self.conn.execute("DELETE FROM AssetVersions WHERE id=?", (int(asset_id),))
        if asset is not None:
            path = self.resolve_asset_path(asset.stored_path)
            if path is not None:
                try:
                    path.unlink(missing_ok=True)
                except Exception:
                    pass

    def validate_assets(self) -> list[AssetValidationIssue]:
        issues: list[AssetValidationIssue] = []
        assets = self.list_assets()
        by_track: dict[int, list[AssetVersionRecord]] = {}
        by_release: dict[int, list[AssetVersionRecord]] = {}
        for asset in assets:
            path = self.resolve_asset_path(asset.stored_path)
            if asset.stored_path and (path is None or not path.exists()):
                issues.append(
                    AssetValidationIssue(
                        severity="error",
                        issue_type="broken_asset_reference",
                        asset_id=asset.id,
                        message=f"Asset file is missing: {asset.stored_path}",
                    )
                )
            if asset.track_id is not None:
                by_track.setdefault(asset.track_id, []).append(asset)
            if asset.release_id is not None:
                by_release.setdefault(asset.release_id, []).append(asset)
        for group in list(by_track.values()) + list(by_release.values()):
            primary_assets = [asset for asset in group if asset.primary_flag]
            if len(primary_assets) > 1:
                for asset in primary_assets:
                    issues.append(
                        AssetValidationIssue(
                            severity="error",
                            issue_type="duplicate_primary_asset",
                            asset_id=asset.id,
                            message="Multiple assets are marked as primary for the same item.",
                        )
                    )
            master_assets = [
                asset
                for asset in group
                if asset.asset_type in {"main_master", "hi_res_master", "alt_master"}
            ]
            if master_assets and not any(
                asset.approved_for_use and asset.asset_type in {"main_master", "hi_res_master"}
                for asset in master_assets
            ):
                issues.append(
                    AssetValidationIssue(
                        severity="warning",
                        issue_type="missing_approved_master",
                        asset_id=master_assets[0].id,
                        message="No approved main or hi-res master is registered for this item.",
                    )
                )
        return issues

    def export_rows(self) -> list[dict[str, object]]:
        return [asdict(item) for item in self.list_assets()]

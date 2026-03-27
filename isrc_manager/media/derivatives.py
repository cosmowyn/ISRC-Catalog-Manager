"""Managed derivative export and external conversion coordinators."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from isrc_manager.file_storage import sanitize_export_basename
from isrc_manager.media.audio_formats import audio_format_profile
from isrc_manager.tags import AudioTagService, write_catalog_export_tags

from .conversion import AudioConversionService

if TYPE_CHECKING:
    from isrc_manager.authenticity import AudioAuthenticityService
    from isrc_manager.releases import ReleaseService
    from isrc_manager.services.tracks import TrackService

MANAGED_DERIVATIVE_WORKFLOW_KIND = "managed_audio_derivative"
MANAGED_DERIVATIVE_KIND_WATERMARK_AUTHENTIC = "watermark_authentic"
MANAGED_DERIVATIVE_KIND_LOSSY = "lossy_derivative"
AUTHENTICITY_BASIS_DIRECT_WATERMARK = "direct_watermark"
AUTHENTICITY_BASIS_CATALOG_LINEAGE_ONLY = "catalog_lineage_only"


@dataclass(frozen=True, slots=True)
class ManagedDerivativeWorkflow:
    derivative_kind: str
    authenticity_basis: str
    capability_group: str
    apply_watermark: bool
    status_label: str


_MANAGED_WORKFLOWS: dict[str, ManagedDerivativeWorkflow] = {
    MANAGED_DERIVATIVE_KIND_WATERMARK_AUTHENTIC: ManagedDerivativeWorkflow(
        derivative_kind=MANAGED_DERIVATIVE_KIND_WATERMARK_AUTHENTIC,
        authenticity_basis=AUTHENTICITY_BASIS_DIRECT_WATERMARK,
        capability_group="managed_authenticity",
        apply_watermark=True,
        status_label="watermarked managed derivative",
    ),
    MANAGED_DERIVATIVE_KIND_LOSSY: ManagedDerivativeWorkflow(
        derivative_kind=MANAGED_DERIVATIVE_KIND_LOSSY,
        authenticity_basis=AUTHENTICITY_BASIS_CATALOG_LINEAGE_ONLY,
        capability_group="managed_lossy",
        apply_watermark=False,
        status_label="lossy managed derivative",
    ),
}


def managed_derivative_workflow(derivative_kind: str) -> ManagedDerivativeWorkflow:
    clean_kind = str(derivative_kind or "").strip().lower()
    workflow = _MANAGED_WORKFLOWS.get(clean_kind)
    if workflow is None:
        raise ValueError(f"Unsupported managed derivative kind: {derivative_kind}")
    return workflow


@dataclass(slots=True)
class ManagedDerivativeExportRequest:
    track_ids: list[int]
    output_dir: str | Path
    output_format: str
    derivative_kind: str | None = None
    profile_name: str | None = None
    key_id: str | None = None


@dataclass(slots=True)
class ManagedDerivativeExportResult:
    requested: int
    exported: int
    skipped: int
    warnings: list[str]
    written_paths: list[str]
    derivative_ids: list[str]
    batch_public_id: str
    derivative_kind: str
    authenticity_basis: str
    watermark_applied: bool
    zip_path: str | None = None


@dataclass(frozen=True, slots=True)
class DerivativeBatchRecord:
    batch_id: str
    created_at: str
    completed_at: str | None
    workflow_kind: str
    derivative_kind: str
    authenticity_basis: str
    output_format: str
    requested_count: int
    exported_count: int
    skipped_count: int
    status: str
    package_mode: str
    zip_filename: str | None
    profile_name: str | None


@dataclass(frozen=True, slots=True)
class DerivativeLedgerRecord:
    export_id: str
    batch_id: str
    track_id: int | None
    track_title: str
    output_filename: str
    output_format: str
    derivative_kind: str
    authenticity_basis: str
    watermark_applied: bool
    metadata_embedded: bool
    output_size_bytes: int
    output_sha256: str
    status: str
    source_storage_mode: str | None
    source_lineage_ref: str
    derivative_manifest_id: str | None
    batch_created_at: str
    batch_completed_at: str | None
    package_mode: str
    zip_filename: str | None
    managed_file_path: str | None
    sidecar_path: str | None
    package_member_path: str | None


@dataclass(slots=True)
class ExternalAudioConversionRequest:
    input_paths: list[str]
    output_dir: str | Path
    output_format: str


@dataclass(slots=True)
class ExternalAudioConversionResult:
    requested: int
    exported: int
    skipped: int
    warnings: list[str]
    written_paths: list[str]
    batch_public_id: str
    zip_path: str | None = None


@dataclass(slots=True)
class _ManagedItemState:
    track_id: int
    track_title: str
    temp_final_path: Path
    final_name: str
    derivative_id: str


def _batch_public_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"AEX-{timestamp}-{uuid.uuid4().hex[:8]}"


def _sha256_for_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _filename_with_hash_suffix(filename: str, sha256_hex: str) -> str:
    source = Path(filename)
    return f"{source.stem}--{sha256_hex[:12]}{source.suffix}"


def _zip_filename(batch_public_id: str) -> str:
    return f"audio-export-{batch_public_id}.zip"


def _report_progress(
    progress_callback,
    *,
    completed_steps: int,
    total_steps: int,
    message: str,
) -> None:
    if progress_callback is None:
        return
    progress_callback(
        max(0, int(completed_steps)),
        max(1, int(total_steps)),
        str(message or ""),
    )


class DerivativeLedgerService:
    """Persists derivative batch and item references without storing file blobs."""

    def __init__(self, conn):
        self.conn = conn

    def create_batch(
        self,
        *,
        batch_public_id: str,
        track_count: int,
        output_format: str,
        workflow_kind: str,
        derivative_kind: str,
        authenticity_basis: str,
        profile_name: str | None = None,
    ) -> str:
        recipe_payload = {
            "workflow_kind": str(workflow_kind or MANAGED_DERIVATIVE_WORKFLOW_KIND),
            "derivative_kind": str(derivative_kind or "").strip().lower(),
            "authenticity_basis": str(authenticity_basis or "").strip().lower(),
            "output_format": str(output_format or "").strip().lower(),
            "requested_count": int(track_count),
        }
        recipe_canonical = json.dumps(recipe_payload, sort_keys=True, separators=(",", ":"))
        self.conn.execute(
            """
            INSERT INTO DerivativeExportBatches(
                batch_id,
                schema_version,
                workflow_kind,
                derivative_kind,
                authenticity_basis,
                package_mode,
                output_format,
                zip_filename,
                profile_name,
                app_version,
                recipe_canonical,
                recipe_sha256,
                requested_count,
                exported_count,
                skipped_count,
                created_at,
                completed_at,
                status
            )
            VALUES (?, 1, ?, ?, ?, 'directory', ?, NULL, ?, NULL, ?, ?, ?, 0, 0, datetime('now'), NULL, 'pending')
            """,
            (
                str(batch_public_id),
                str(workflow_kind or MANAGED_DERIVATIVE_WORKFLOW_KIND),
                str(derivative_kind or "").strip().lower(),
                str(authenticity_basis or "").strip().lower(),
                str(output_format or "").strip().lower(),
                str(profile_name or "").strip() or None,
                recipe_canonical,
                hashlib.sha256(recipe_canonical.encode("utf-8")).hexdigest(),
                int(track_count),
            ),
        )
        return str(batch_public_id)

    def update_batch_completion(
        self,
        batch_id: str,
        *,
        exported_count: int,
        skipped_count: int,
        package_mode: str,
        status: str,
        zip_filename: str | None = None,
    ) -> None:
        self.conn.execute(
            """
            UPDATE DerivativeExportBatches
            SET exported_count=?,
                skipped_count=?,
                package_mode=?,
                zip_filename=?,
                completed_at=datetime('now'),
                status=?
            WHERE batch_id=?
            """,
            (
                int(exported_count),
                int(skipped_count),
                str(package_mode or "").strip() or "directory",
                str(zip_filename or "").strip() or None,
                str(status or "completed"),
                str(batch_id),
            ),
        )

    def delete_batch(self, batch_id: str) -> None:
        self.conn.execute("DELETE FROM TrackAudioDerivatives WHERE batch_id=?", (str(batch_id),))
        self.conn.execute("DELETE FROM DerivativeExportBatches WHERE batch_id=?", (str(batch_id),))

    def delete_derivative(self, export_id: str) -> None:
        self.conn.execute("DELETE FROM TrackAudioDerivatives WHERE export_id=?", (str(export_id),))

    def list_batches(
        self,
        *,
        search_text: str = "",
        output_format: str | None = None,
        derivative_kind: str | None = None,
        status: str | None = None,
        limit: int = 250,
    ) -> list[DerivativeBatchRecord]:
        params: list[object] = []
        where_parts: list[str] = []
        search = str(search_text or "").strip().lower()
        if search:
            like_value = f"%{search}%"
            where_parts.append(
                """
                (
                    lower(b.batch_id) LIKE ?
                    OR lower(coalesce(b.output_format, '')) LIKE ?
                    OR lower(coalesce(b.derivative_kind, '')) LIKE ?
                    OR lower(coalesce(b.authenticity_basis, '')) LIKE ?
                    OR lower(coalesce(b.profile_name, '')) LIKE ?
                    OR EXISTS (
                        SELECT 1
                        FROM TrackAudioDerivatives d
                        LEFT JOIN Tracks t ON t.id = d.track_id
                        WHERE d.batch_id = b.batch_id
                          AND (
                              lower(coalesce(d.output_filename, '')) LIKE ?
                              OR lower(coalesce(d.output_sha256, '')) LIKE ?
                              OR lower(coalesce(t.track_title, '')) LIKE ?
                          )
                    )
                )
                """
            )
            params.extend([like_value] * 8)
        clean_output_format = str(output_format or "").strip().lower()
        if clean_output_format:
            where_parts.append("lower(coalesce(b.output_format, '')) = ?")
            params.append(clean_output_format)
        clean_derivative_kind = str(derivative_kind or "").strip().lower()
        if clean_derivative_kind:
            where_parts.append("lower(coalesce(b.derivative_kind, '')) = ?")
            params.append(clean_derivative_kind)
        clean_status = str(status or "").strip().lower()
        if clean_status:
            where_parts.append("lower(coalesce(b.status, '')) = ?")
            params.append(clean_status)
        where_clause = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
        params.append(max(1, int(limit or 250)))
        rows = self.conn.execute(
            f"""
            SELECT
                b.batch_id,
                b.created_at,
                b.completed_at,
                b.workflow_kind,
                b.derivative_kind,
                b.authenticity_basis,
                b.output_format,
                b.requested_count,
                b.exported_count,
                b.skipped_count,
                b.status,
                b.package_mode,
                b.zip_filename,
                b.profile_name
            FROM DerivativeExportBatches b
            {where_clause}
            ORDER BY datetime(b.created_at) DESC, b.batch_id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        return [
            DerivativeBatchRecord(
                batch_id=str(row[0] or ""),
                created_at=str(row[1] or ""),
                completed_at=str(row[2] or "").strip() or None,
                workflow_kind=str(row[3] or ""),
                derivative_kind=str(row[4] or ""),
                authenticity_basis=str(row[5] or ""),
                output_format=str(row[6] or ""),
                requested_count=int(row[7] or 0),
                exported_count=int(row[8] or 0),
                skipped_count=int(row[9] or 0),
                status=str(row[10] or ""),
                package_mode=str(row[11] or ""),
                zip_filename=str(row[12] or "").strip() or None,
                profile_name=str(row[13] or "").strip() or None,
            )
            for row in rows
        ]

    def list_derivatives(
        self,
        *,
        batch_id: str | None = None,
        search_text: str = "",
        output_format: str | None = None,
        derivative_kind: str | None = None,
        status: str | None = None,
        limit: int = 1000,
    ) -> list[DerivativeLedgerRecord]:
        params: list[object] = []
        where_parts: list[str] = []
        clean_batch_id = str(batch_id or "").strip()
        if clean_batch_id:
            where_parts.append("d.batch_id = ?")
            params.append(clean_batch_id)
        search = str(search_text or "").strip().lower()
        if search:
            like_value = f"%{search}%"
            where_parts.append(
                """
                (
                    lower(coalesce(t.track_title, '')) LIKE ?
                    OR lower(coalesce(d.output_filename, '')) LIKE ?
                    OR lower(coalesce(d.output_format, '')) LIKE ?
                    OR lower(coalesce(d.derivative_kind, '')) LIKE ?
                    OR lower(coalesce(d.authenticity_basis, '')) LIKE ?
                    OR lower(coalesce(d.output_sha256, '')) LIKE ?
                    OR lower(coalesce(d.export_id, '')) LIKE ?
                )
                """
            )
            params.extend([like_value] * 7)
        clean_output_format = str(output_format or "").strip().lower()
        if clean_output_format:
            where_parts.append("lower(coalesce(d.output_format, '')) = ?")
            params.append(clean_output_format)
        clean_derivative_kind = str(derivative_kind or "").strip().lower()
        if clean_derivative_kind:
            where_parts.append("lower(coalesce(d.derivative_kind, '')) = ?")
            params.append(clean_derivative_kind)
        clean_status = str(status or "").strip().lower()
        if clean_status:
            where_parts.append("lower(coalesce(d.status, '')) = ?")
            params.append(clean_status)
        where_clause = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
        params.append(max(1, int(limit or 1000)))
        rows = self.conn.execute(
            f"""
            SELECT
                d.export_id,
                d.batch_id,
                d.track_id,
                coalesce(t.track_title, ''),
                d.output_filename,
                d.output_format,
                d.derivative_kind,
                d.authenticity_basis,
                d.watermark_applied,
                d.metadata_embedded,
                d.output_size_bytes,
                d.output_sha256,
                d.status,
                d.source_storage_mode,
                d.source_lineage_ref,
                d.derivative_manifest_id,
                b.created_at,
                b.completed_at,
                b.package_mode,
                b.zip_filename,
                d.managed_file_path,
                d.sidecar_path,
                d.package_member_path
            FROM TrackAudioDerivatives d
            LEFT JOIN Tracks t ON t.id = d.track_id
            LEFT JOIN DerivativeExportBatches b ON b.batch_id = d.batch_id
            {where_clause}
            ORDER BY datetime(b.created_at) DESC, d.output_filename COLLATE NOCASE ASC
            LIMIT ?
            """,
            params,
        ).fetchall()
        return [
            DerivativeLedgerRecord(
                export_id=str(row[0] or ""),
                batch_id=str(row[1] or ""),
                track_id=int(row[2]) if row[2] is not None else None,
                track_title=str(row[3] or ""),
                output_filename=str(row[4] or ""),
                output_format=str(row[5] or ""),
                derivative_kind=str(row[6] or ""),
                authenticity_basis=str(row[7] or ""),
                watermark_applied=bool(row[8]),
                metadata_embedded=bool(row[9]),
                output_size_bytes=int(row[10] or 0),
                output_sha256=str(row[11] or ""),
                status=str(row[12] or ""),
                source_storage_mode=str(row[13] or "").strip() or None,
                source_lineage_ref=str(row[14] or ""),
                derivative_manifest_id=str(row[15] or "").strip() or None,
                batch_created_at=str(row[16] or ""),
                batch_completed_at=str(row[17] or "").strip() or None,
                package_mode=str(row[18] or ""),
                zip_filename=str(row[19] or "").strip() or None,
                managed_file_path=str(row[20] or "").strip() or None,
                sidecar_path=str(row[21] or "").strip() or None,
                package_member_path=str(row[22] or "").strip() or None,
            )
            for row in rows
        ]

    def create_derivative(
        self,
        *,
        source_track_id: int,
        export_batch_id: str,
        workflow_kind: str,
        derivative_kind: str,
        authenticity_basis: str,
        output_format: str,
        watermark_applied: bool,
        metadata_embedded: bool,
        final_sha256: str,
        output_filename: str,
        source_lineage_ref: str,
        source_sha256: str,
        source_storage_mode: str | None,
        authenticity_manifest_id: str | None,
        output_size_bytes: int,
        filename_hash_suffix: str,
        output_mime_type: str | None = None,
        managed_file_path: str | None = None,
        sidecar_path: str | None = None,
        package_member_path: str | None = None,
    ) -> str:
        derivative_id = uuid.uuid4().hex
        self.conn.execute(
            """
            INSERT INTO TrackAudioDerivatives(
                export_id,
                batch_id,
                track_id,
                target_key,
                workflow_kind,
                derivative_kind,
                authenticity_basis,
                source_kind,
                source_lineage_ref,
                source_audio_sha256,
                source_storage_mode,
                derivative_manifest_id,
                output_format,
                output_suffix,
                output_mime_type,
                output_filename,
                filename_hash_suffix,
                watermark_applied,
                metadata_embedded,
                output_sha256,
                output_size_bytes,
                managed_file_path,
                sidecar_path,
                package_member_path,
                status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                derivative_id,
                str(export_batch_id),
                int(source_track_id),
                str(output_format or "").strip().lower(),
                str(workflow_kind or MANAGED_DERIVATIVE_WORKFLOW_KIND),
                str(derivative_kind or "").strip().lower(),
                str(authenticity_basis or "").strip().lower(),
                "track_audio",
                str(source_lineage_ref or ""),
                str(source_sha256 or ""),
                str(source_storage_mode or "").strip() or None,
                str(authenticity_manifest_id or "").strip() or None,
                str(output_format or "").strip().lower(),
                str(Path(output_filename).suffix.lower()),
                str(output_mime_type or "").strip() or None,
                str(output_filename or ""),
                str(filename_hash_suffix or ""),
                1 if watermark_applied else 0,
                1 if metadata_embedded else 0,
                str(final_sha256 or ""),
                int(output_size_bytes or 0),
                str(managed_file_path or "").strip() or None,
                str(sidecar_path or "").strip() or None,
                str(package_member_path or "").strip() or None,
                "completed",
            ),
        )
        return derivative_id

    def update_derivative_artifacts(
        self,
        export_id: str,
        *,
        managed_file_path: str | None = None,
        sidecar_path: str | None = None,
        package_member_path: str | None = None,
    ) -> None:
        self.conn.execute(
            """
            UPDATE TrackAudioDerivatives
            SET managed_file_path=?,
                sidecar_path=?,
                package_member_path=?,
                updated_at=datetime('now')
            WHERE export_id=?
            """,
            (
                str(managed_file_path or "").strip() or None,
                str(sidecar_path or "").strip() or None,
                str(package_member_path or "").strip() or None,
                str(export_id or ""),
            ),
        )


class ManagedDerivativeExportCoordinator:
    """Runs the catalog-owned derivative export workflow."""

    def __init__(
        self,
        *,
        conn,
        track_service: TrackService,
        release_service: ReleaseService | None,
        tag_service: AudioTagService,
        authenticity_service: AudioAuthenticityService | None,
        conversion_service: AudioConversionService | None = None,
    ):
        self.conn = conn
        self.track_service = track_service
        self.release_service = release_service
        self.tag_service = tag_service
        self.authenticity_service = authenticity_service
        self.conversion_service = conversion_service or AudioConversionService()
        self.ledger = DerivativeLedgerService(conn)

    def export(
        self,
        request: ManagedDerivativeExportRequest,
        *,
        progress_callback=None,
        is_cancelled=None,
    ) -> ManagedDerivativeExportResult:
        output_format = str(request.output_format or "").strip().lower()
        output_profile = audio_format_profile(output_format)
        if output_profile is None:
            raise ValueError(f"Unsupported output format: {output_format}")
        derivative_kind = str(request.derivative_kind or "").strip().lower()
        if not derivative_kind:
            derivative_kind = (
                MANAGED_DERIVATIVE_KIND_LOSSY
                if output_profile.lossy
                else MANAGED_DERIVATIVE_KIND_WATERMARK_AUTHENTIC
            )
        workflow = managed_derivative_workflow(derivative_kind)
        if not self.conversion_service.is_supported_target(
            output_format,
            capability_group=workflow.capability_group,
        ):
            raise ValueError(f"Unsupported {workflow.status_label} target: {request.output_format}")
        if workflow.apply_watermark and self.authenticity_service is None:
            raise RuntimeError(
                "Managed watermarked derivative export requires audio authenticity support."
            )
        destination_root = Path(request.output_dir)
        destination_root.mkdir(parents=True, exist_ok=True)
        track_ids = [int(track_id) for track_id in request.track_ids]
        batch_public_id = _batch_public_id()
        warnings: list[str] = []
        written_paths: list[str] = []
        derivative_ids: list[str] = []
        exported_states: list[_ManagedItemState] = []
        exported = 0
        batch_id: str | None = None
        zip_path: Path | None = None
        planned_items: list[tuple[int, object]] = []

        for track_id in track_ids:
            if is_cancelled is not None and is_cancelled():
                raise InterruptedError("Managed derivative export cancelled.")
            snapshot = self.track_service.fetch_track_snapshot(track_id)
            if snapshot is None or not self.track_service.has_media(track_id, "audio_file"):
                warnings.append(f"Track {track_id} has no attached audio.")
                continue
            planned_items.append((track_id, snapshot))

        item_stage_count = 7 if workflow.apply_watermark else 6
        total_steps = 1 + (len(planned_items) * item_stage_count) + 1
        completed_steps = 1

        try:
            with self.conn:
                batch_id = self.ledger.create_batch(
                    batch_public_id=batch_public_id,
                    track_count=len(track_ids),
                    output_format=output_format,
                    workflow_kind=MANAGED_DERIVATIVE_WORKFLOW_KIND,
                    derivative_kind=workflow.derivative_kind,
                    authenticity_basis=workflow.authenticity_basis,
                    profile_name=request.profile_name,
                )
                with tempfile.TemporaryDirectory(
                    prefix=f"managed-derivative-{batch_public_id}-"
                ) as temp_dir_text:
                    temp_dir = Path(temp_dir_text)
                    temp_final_dir = temp_dir / "finalized"
                    temp_final_dir.mkdir(parents=True, exist_ok=True)
                    planned_total = len(planned_items)
                    for item_index, (track_id, snapshot) in enumerate(planned_items, start=1):
                        if is_cancelled is not None and is_cancelled():
                            raise InterruptedError("Managed derivative export cancelled.")
                        source_handle = self.track_service.resolve_media_source(
                            track_id, "audio_file"
                        )
                        source_sha256 = source_handle.sha256_hex()
                        source_lineage_ref = f"track-audio/{track_id}/{source_sha256}"
                        base_name = sanitize_export_basename(
                            snapshot.track_title or f"track-{track_id}"
                        )
                        source_ext = output_profile.suffixes[0]
                        converted_path = temp_dir / f"{base_name}{source_ext}"
                        watermarked_path = temp_dir / f"{base_name}.watermarked{source_ext}"
                        _report_progress(
                            progress_callback,
                            completed_steps=completed_steps,
                            total_steps=total_steps,
                            message=(
                                f"Resolving source audio {item_index} of {planned_total}: "
                                f"{snapshot.track_title}"
                            ),
                        )
                        with source_handle.materialize_path() as materialized_source:
                            if is_cancelled is not None and is_cancelled():
                                raise InterruptedError("Managed derivative export cancelled.")
                            completed_steps += 1
                            _report_progress(
                                progress_callback,
                                completed_steps=completed_steps,
                                total_steps=total_steps,
                                message=(
                                    f"Converting derivative {item_index} of {planned_total}: "
                                    f"{snapshot.track_title}"
                                ),
                            )
                            self.conversion_service.transcode(
                                source_path=materialized_source,
                                destination_path=converted_path,
                                target_id=output_format,
                            )
                        metadata_embedded = False
                        manifest_record = None
                        finalized_output_path = converted_path
                        if workflow.apply_watermark:
                            completed_steps += 1
                            _report_progress(
                                progress_callback,
                                completed_steps=completed_steps,
                                total_steps=total_steps,
                                message=(
                                    f"Applying direct watermark {item_index} of {planned_total}: "
                                    f"{snapshot.track_title}"
                                ),
                            )
                            manifest_record = (
                                self.authenticity_service.watermark_catalog_derivative(
                                    track_id=track_id,
                                    source_path=converted_path,
                                    destination_path=watermarked_path,
                                    key_id=request.key_id,
                                    profile_name=request.profile_name,
                                )
                            )
                            finalized_output_path = watermarked_path
                            completed_steps += 1
                            _report_progress(
                                progress_callback,
                                completed_steps=completed_steps,
                                total_steps=total_steps,
                                message=(
                                    f"Writing catalog metadata {item_index} of {planned_total}: "
                                    f"{snapshot.track_title}"
                                ),
                            )
                        else:
                            completed_steps += 1
                            _report_progress(
                                progress_callback,
                                completed_steps=completed_steps,
                                total_steps=total_steps,
                                message=(
                                    f"Writing catalog metadata {item_index} of {planned_total}: "
                                    f"{snapshot.track_title}"
                                ),
                            )
                            metadata_embedded, metadata_warning = write_catalog_export_tags(
                                converted_path,
                                track_id=track_id,
                                track_service=self.track_service,
                                release_service=self.release_service,
                                tag_service=self.tag_service,
                                include_artwork_bytes=True,
                            )
                            if metadata_warning:
                                warnings.append(
                                    f"{snapshot.track_title}: metadata embedding skipped; {metadata_warning}."
                                )
                        if workflow.apply_watermark:
                            metadata_embedded, metadata_warning = write_catalog_export_tags(
                                finalized_output_path,
                                track_id=track_id,
                                track_service=self.track_service,
                                release_service=self.release_service,
                                tag_service=self.tag_service,
                                include_artwork_bytes=True,
                            )
                            if metadata_warning:
                                warnings.append(
                                    f"{snapshot.track_title}: metadata embedding skipped; {metadata_warning}."
                                )
                        completed_steps += 1
                        _report_progress(
                            progress_callback,
                            completed_steps=completed_steps,
                            total_steps=total_steps,
                            message=(
                                f"Hashing finalized derivative {item_index} of {planned_total}: "
                                f"{snapshot.track_title}"
                            ),
                        )
                        final_sha256 = _sha256_for_file(finalized_output_path)
                        final_name = _filename_with_hash_suffix(
                            f"{base_name}{source_ext}", final_sha256
                        )
                        completed_steps += 1
                        _report_progress(
                            progress_callback,
                            completed_steps=completed_steps,
                            total_steps=total_steps,
                            message=(
                                f"Registering derivative {item_index} of {planned_total}: "
                                f"{snapshot.track_title}"
                            ),
                        )
                        derivative_id = self.ledger.create_derivative(
                            source_track_id=track_id,
                            export_batch_id=batch_id,
                            workflow_kind=MANAGED_DERIVATIVE_WORKFLOW_KIND,
                            derivative_kind=workflow.derivative_kind,
                            authenticity_basis=workflow.authenticity_basis,
                            output_format=output_format,
                            watermark_applied=workflow.apply_watermark,
                            metadata_embedded=metadata_embedded,
                            final_sha256=final_sha256,
                            output_filename=final_name,
                            source_lineage_ref=source_lineage_ref,
                            source_sha256=source_sha256,
                            source_storage_mode=source_handle.storage_mode,
                            authenticity_manifest_id=(
                                manifest_record.manifest_id if manifest_record is not None else None
                            ),
                            output_size_bytes=int(finalized_output_path.stat().st_size),
                            filename_hash_suffix=final_sha256[:12],
                            output_mime_type=(
                                output_profile.mime_types[0] if output_profile.mime_types else None
                            ),
                        )
                        final_temp_path = temp_final_dir / final_name
                        completed_steps += 1
                        _report_progress(
                            progress_callback,
                            completed_steps=completed_steps,
                            total_steps=total_steps,
                            message=(
                                f"Staging finalized derivative {item_index} of {planned_total}: "
                                f"{snapshot.track_title}"
                            ),
                        )
                        shutil.move(str(finalized_output_path), str(final_temp_path))
                        exported_states.append(
                            _ManagedItemState(
                                track_id=track_id,
                                track_title=str(snapshot.track_title or ""),
                                temp_final_path=final_temp_path,
                                final_name=final_name,
                                derivative_id=derivative_id,
                            )
                        )
                        derivative_ids.append(derivative_id)
                        exported += 1
                        completed_steps += 1

                    if exported == 0:
                        _report_progress(
                            progress_callback,
                            completed_steps=completed_steps,
                            total_steps=total_steps,
                            message="No exportable derivatives were produced; cleaning up the batch...",
                        )
                        self.ledger.delete_batch(batch_id)
                    elif exported > 1:
                        _report_progress(
                            progress_callback,
                            completed_steps=completed_steps,
                            total_steps=total_steps,
                            message="Packaging ZIP archive…",
                        )
                        zip_path = destination_root / _zip_filename(batch_public_id)
                        with zipfile.ZipFile(
                            zip_path, "w", compression=zipfile.ZIP_DEFLATED
                        ) as archive:
                            for exported_state in exported_states:
                                archive.write(
                                    exported_state.temp_final_path,
                                    arcname=exported_state.final_name,
                                )
                                self.ledger.update_derivative_artifacts(
                                    exported_state.derivative_id,
                                    managed_file_path=None,
                                    sidecar_path=None,
                                    package_member_path=exported_state.final_name,
                                )
                        self.ledger.update_batch_completion(
                            batch_id,
                            exported_count=exported,
                            skipped_count=max(0, len(track_ids) - exported),
                            package_mode="zip",
                            status="completed",
                            zip_filename=zip_path.name,
                        )
                    elif exported_states:
                        _report_progress(
                            progress_callback,
                            completed_steps=completed_steps,
                            total_steps=total_steps,
                            message="Finalizing managed derivative delivery…",
                        )
                        final_destination = destination_root / exported_states[0].final_name
                        shutil.move(str(exported_states[0].temp_final_path), str(final_destination))
                        written_paths.append(str(final_destination))
                        self.ledger.update_derivative_artifacts(
                            exported_states[0].derivative_id,
                            managed_file_path=str(final_destination),
                            sidecar_path=None,
                            package_member_path=None,
                        )
                        self.ledger.update_batch_completion(
                            batch_id,
                            exported_count=exported,
                            skipped_count=max(0, len(track_ids) - exported),
                            package_mode="directory",
                            status="completed",
                            zip_filename=None,
                        )
                    completed_steps += 1
                if zip_path is not None:
                    written_paths.append(str(zip_path))
        except Exception:
            for path_text in written_paths:
                try:
                    Path(path_text).unlink(missing_ok=True)
                except Exception:
                    pass
            raise

        skipped = max(0, len(track_ids) - exported)
        return ManagedDerivativeExportResult(
            requested=len(track_ids),
            exported=exported,
            skipped=skipped,
            warnings=warnings,
            written_paths=written_paths,
            derivative_ids=derivative_ids,
            batch_public_id=batch_public_id,
            derivative_kind=workflow.derivative_kind,
            authenticity_basis=workflow.authenticity_basis,
            watermark_applied=workflow.apply_watermark,
            zip_path=str(zip_path) if zip_path is not None else None,
        )


class ExternalAudioConversionCoordinator:
    """Runs the file-picker conversion workflow without DB metadata or watermarking."""

    def __init__(self, *, conversion_service: AudioConversionService | None = None):
        self.conversion_service = conversion_service or AudioConversionService()

    def export(
        self,
        request: ExternalAudioConversionRequest,
        *,
        progress_callback=None,
        is_cancelled=None,
    ) -> ExternalAudioConversionResult:
        output_format = str(request.output_format or "").strip().lower()
        if not self.conversion_service.is_supported_target(output_format, managed_only=False):
            raise ValueError(f"Unsupported external conversion target: {request.output_format}")
        destination_root = Path(request.output_dir)
        destination_root.mkdir(parents=True, exist_ok=True)
        file_paths = [Path(path) for path in request.input_paths if str(path).strip()]
        batch_public_id = _batch_public_id()
        warnings: list[str] = []
        written_paths: list[str] = []
        exported = 0
        zip_path: Path | None = None
        output_profile = audio_format_profile(output_format)
        if output_profile is None:
            raise ValueError(f"Unsupported output format: {output_format}")
        valid_paths: list[Path] = []
        for input_path in file_paths:
            if is_cancelled is not None and is_cancelled():
                raise InterruptedError("External audio conversion cancelled.")
            if not input_path.exists():
                warnings.append(f"Missing source audio: {input_path}")
                continue
            valid_paths.append(input_path)

        total_steps = 1 + len(valid_paths) + 1
        completed_steps = 1

        try:
            with tempfile.TemporaryDirectory(
                prefix=f"external-convert-{batch_public_id}-"
            ) as temp_dir_text:
                temp_dir = Path(temp_dir_text)
                temp_final_dir = temp_dir / "finalized"
                temp_final_dir.mkdir(parents=True, exist_ok=True)
                finalized_paths: list[Path] = []
                valid_total = len(valid_paths)
                for item_index, input_path in enumerate(valid_paths, start=1):
                    if is_cancelled is not None and is_cancelled():
                        raise InterruptedError("External audio conversion cancelled.")
                    _report_progress(
                        progress_callback,
                        completed_steps=completed_steps,
                        total_steps=total_steps,
                        message=f"Converting external audio {item_index} of {valid_total}: {input_path.name}",
                    )
                    base_name = sanitize_export_basename(input_path.stem or input_path.name)
                    temp_destination = temp_final_dir / f"{base_name}{output_profile.suffixes[0]}"
                    self.conversion_service.transcode(
                        source_path=input_path,
                        destination_path=temp_destination,
                        target_id=output_format,
                        metadata_behavior="strip",
                    )
                    finalized_paths.append(temp_destination)
                    exported += 1
                    completed_steps += 1
                if exported > 1:
                    _report_progress(
                        progress_callback,
                        completed_steps=completed_steps,
                        total_steps=total_steps,
                        message="Packaging ZIP archive…",
                    )
                    zip_path = destination_root / _zip_filename(batch_public_id)
                    with zipfile.ZipFile(
                        zip_path, "w", compression=zipfile.ZIP_DEFLATED
                    ) as archive:
                        for finalized_path in finalized_paths:
                            archive.write(finalized_path, arcname=finalized_path.name)
                    written_paths.append(str(zip_path))
                elif finalized_paths:
                    _report_progress(
                        progress_callback,
                        completed_steps=completed_steps,
                        total_steps=total_steps,
                        message="Finalizing converted output…",
                    )
                    final_destination = destination_root / finalized_paths[0].name
                    shutil.move(str(finalized_paths[0]), str(final_destination))
                    written_paths.append(str(final_destination))
                else:
                    _report_progress(
                        progress_callback,
                        completed_steps=completed_steps,
                        total_steps=total_steps,
                        message="No external audio files were converted.",
                    )
                completed_steps += 1
        except Exception:
            for path_text in written_paths:
                try:
                    Path(path_text).unlink(missing_ok=True)
                except Exception:
                    pass
            raise

        return ExternalAudioConversionResult(
            requested=len(file_paths),
            exported=exported,
            skipped=max(0, len(file_paths) - exported),
            warnings=warnings,
            written_paths=written_paths,
            batch_public_id=batch_public_id,
            zip_path=str(zip_path) if zip_path is not None else None,
        )

"""Forensic watermark export and inspection services."""

from __future__ import annotations

import hashlib
import secrets
import shutil
import tempfile
import uuid
import zipfile
import zlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from isrc_manager.authenticity.crypto import derive_forensic_watermark_key
from isrc_manager.file_storage import sanitize_export_basename
from isrc_manager.media.audio_formats import audio_format_profile
from isrc_manager.media.conversion import AudioConversionService
from isrc_manager.media.derivatives import DerivativeLedgerService
from isrc_manager.tags import AudioTagService, build_catalog_tag_data

from .models import (
    AUTHENTICITY_BASIS_FORENSIC_TRACE,
    DERIVATIVE_KIND_FORENSIC_WATERMARKED_COPY,
    FORENSIC_STATUS_MATCH_FOUND,
    FORENSIC_STATUS_MATCH_LOW_CONFIDENCE,
    FORENSIC_STATUS_NOT_DETECTED,
    FORENSIC_STATUS_TOKEN_UNRESOLVED,
    FORENSIC_STATUS_UNSUPPORTED_OR_INSUFFICIENT,
    FORENSIC_TOKEN_VERSION,
    FORENSIC_WATERMARK_VERSION,
    WORKFLOW_KIND_FORENSIC_EXPORT,
    ForensicExportRecord,
    ForensicExportRequest,
    ForensicExportResult,
    ForensicInspectionReport,
    ForensicWatermarkToken,
)
from .watermark import (
    ForensicWatermarkCore,
    forensic_watermark_settings_payload,
    supported_forensic_audio_path,
)

if TYPE_CHECKING:
    from isrc_manager.authenticity import AuthenticityKeyService
    from isrc_manager.releases import ReleaseService
    from isrc_manager.services.tracks import TrackService

_FORENSIC_STAGE_COUNT = 9
_FORENSIC_INSPECTION_STAGE_COUNT = 4
_LOSSY_FORENSIC_OUTPUT_IDS = frozenset({"mp3"})


@dataclass(slots=True)
class _ForensicExportState:
    track_id: int
    track_title: str
    temp_final_path: Path
    final_name: str
    derivative_id: str
    forensic_export_id: str


@dataclass(slots=True)
class _ResolutionCandidate:
    record: ForensicExportRecord
    source_audio_sha256: str
    source_lineage_ref: str | None


def _clean_text(value: object | None) -> str | None:
    text = str(value or "").strip()
    return text or None


def _batch_public_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"FEX-{timestamp}-{uuid.uuid4().hex[:8]}"


def _forensic_export_public_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"FWX-{timestamp}-{uuid.uuid4().hex[:10]}"


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
    return f"forensic-export-{batch_public_id}.zip"


def _binding_crc32(
    *,
    batch_id: str,
    track_id: int,
    output_format: str,
    recipient_label: str | None,
    share_label: str | None,
) -> int:
    payload = "\x1f".join(
        (
            str(batch_id),
            str(track_id),
            str(output_format or "").strip().lower(),
            str(recipient_label or "").strip(),
            str(share_label or "").strip(),
        )
    ).encode("utf-8")
    return zlib.crc32(payload) & 0xFFFFFFFF


def _report_stage(
    progress_callback,
    *,
    item_index: int,
    item_total: int,
    stage_index: int,
    stage_count: int,
    message: str,
) -> None:
    if progress_callback is None:
        return
    value = ((item_index - 1) * stage_count) + stage_index
    maximum = max(1, item_total * stage_count)
    progress_callback(value, maximum, message)


class ForensicWatermarkService:
    """Application-facing wrapper around the forensic watermark core."""

    def __init__(self):
        self.core = ForensicWatermarkCore()

    def settings_payload(self) -> dict[str, object]:
        return forensic_watermark_settings_payload()

    def embed_to_path(
        self,
        *,
        source_path: str | Path | None = None,
        source_bytes: bytes | None = None,
        destination_path: str | Path,
        watermark_key: bytes,
        token: ForensicWatermarkToken,
    ) -> dict[str, float | int]:
        return self.core.embed_to_path(
            source_path=source_path,
            source_bytes=source_bytes,
            destination_path=destination_path,
            watermark_key=watermark_key,
            token=token,
        )

    def embed_export_path(
        self,
        *,
        source_path: str | Path,
        destination_path: str | Path,
        output_format: str,
        conversion_service: AudioConversionService,
        watermark_key: bytes,
        token: ForensicWatermarkToken,
    ) -> dict[str, float | int]:
        destination = Path(destination_path)
        output_id = str(output_format or "").strip().lower()
        if supported_forensic_audio_path(destination):
            return self.embed_to_path(
                source_path=source_path,
                destination_path=destination,
                watermark_key=watermark_key,
                token=token,
            )
        if output_id not in _LOSSY_FORENSIC_OUTPUT_IDS:
            raise ValueError(f"Unsupported forensic delivery output format: {output_format}")
        with tempfile.TemporaryDirectory(prefix=f"forensic-{output_id}-embed-") as temp_dir_text:
            temp_dir = Path(temp_dir_text)
            decoded_source = temp_dir / "decoded-source.wav"
            watermarked_pcm = temp_dir / "watermarked.wav"
            conversion_service.transcode(
                source_path=source_path,
                destination_path=decoded_source,
                target_id="wav",
            )
            metrics = self.embed_to_path(
                source_path=decoded_source,
                destination_path=watermarked_pcm,
                watermark_key=watermark_key,
                token=token,
            )
            conversion_service.transcode(
                source_path=watermarked_pcm,
                destination_path=destination,
                target_id=output_id,
            )
            return metrics

    def extract_from_path(self, path: str | Path, *, watermark_keys: list[tuple[str, bytes]]):
        return self.core.extract_from_path(path, watermark_keys=watermark_keys)

    def verify_expected_token_against_reference(
        self,
        candidate_path: str | Path,
        *,
        reference_path: str | Path | None = None,
        reference_bytes: bytes | None = None,
        watermark_keys: list[tuple[str, bytes]],
        token: ForensicWatermarkToken,
    ):
        return self.core.verify_expected_token_against_reference(
            candidate_path,
            reference_path=reference_path,
            reference_bytes=reference_bytes,
            watermark_keys=watermark_keys,
            token=token,
        )


class ForensicLedgerService:
    """Stores recipient-specific forensic export mappings without storing audio blobs."""

    def __init__(self, conn):
        self.conn = conn

    def create_export(
        self,
        *,
        batch_id: str,
        derivative_export_id: str | None,
        track_id: int,
        key_id: str,
        token: ForensicWatermarkToken,
        recipient_label: str | None,
        share_label: str | None,
        output_format: str,
        output_filename: str,
        output_sha256: str,
        output_size_bytes: int,
        source_lineage_ref: str,
    ) -> str:
        forensic_export_id = _forensic_export_public_id()
        self.conn.execute(
            """
            INSERT INTO ForensicWatermarkExports(
                forensic_export_id,
                batch_id,
                derivative_export_id,
                track_id,
                key_id,
                token_version,
                forensic_watermark_version,
                token_id,
                binding_crc32,
                recipient_label,
                share_label,
                output_format,
                output_filename,
                output_sha256,
                output_size_bytes,
                source_lineage_ref,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (
                forensic_export_id,
                str(batch_id),
                _clean_text(derivative_export_id),
                int(track_id),
                str(key_id),
                int(token.version),
                FORENSIC_WATERMARK_VERSION,
                int(token.token_id),
                int(token.binding_crc32),
                _clean_text(recipient_label),
                _clean_text(share_label),
                str(output_format or "").strip().lower(),
                str(output_filename or ""),
                str(output_sha256 or ""),
                int(output_size_bytes or 0),
                str(source_lineage_ref or ""),
            ),
        )
        return forensic_export_id

    def _row_to_record(self, row) -> ForensicExportRecord | None:
        if row is None:
            return None
        return ForensicExportRecord(
            forensic_export_id=str(row[0] or ""),
            batch_id=str(row[1] or ""),
            derivative_export_id=_clean_text(row[2]),
            track_id=int(row[3] or 0),
            key_id=str(row[4] or ""),
            token_version=int(row[5] or FORENSIC_TOKEN_VERSION),
            forensic_watermark_version=int(row[6] or FORENSIC_WATERMARK_VERSION),
            token_id=int(row[7] or 0),
            binding_crc32=int(row[8] or 0),
            recipient_label=_clean_text(row[9]),
            share_label=_clean_text(row[10]),
            output_format=_clean_text(row[11]),
            output_filename=_clean_text(row[12]),
            output_sha256=_clean_text(row[13]),
            output_size_bytes=int(row[14] or 0),
            source_lineage_ref=_clean_text(row[15]),
            created_at=_clean_text(row[16]),
            last_verified_at=_clean_text(row[17]),
            last_verification_status=_clean_text(row[18]),
            last_verification_confidence=(float(row[19]) if row[19] is not None else None),
        )

    def fetch_by_token(self, token_id: int, binding_crc32: int) -> ForensicExportRecord | None:
        row = self.conn.execute(
            """
            SELECT
                forensic_export_id,
                batch_id,
                derivative_export_id,
                track_id,
                key_id,
                token_version,
                forensic_watermark_version,
                token_id,
                binding_crc32,
                recipient_label,
                share_label,
                output_format,
                output_filename,
                output_sha256,
                output_size_bytes,
                source_lineage_ref,
                created_at,
                last_verified_at,
                last_verification_status,
                last_verification_confidence
            FROM ForensicWatermarkExports
            WHERE token_id=? AND binding_crc32=?
            """,
            (int(token_id), int(binding_crc32)),
        ).fetchone()
        return self._row_to_record(row)

    def fetch_by_output_sha256(self, output_sha256: str) -> ForensicExportRecord | None:
        row = self.conn.execute(
            """
            SELECT
                forensic_export_id,
                batch_id,
                derivative_export_id,
                track_id,
                key_id,
                token_version,
                forensic_watermark_version,
                token_id,
                binding_crc32,
                recipient_label,
                share_label,
                output_format,
                output_filename,
                output_sha256,
                output_size_bytes,
                source_lineage_ref,
                created_at,
                last_verified_at,
                last_verification_status,
                last_verification_confidence
            FROM ForensicWatermarkExports
            WHERE output_sha256=?
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (str(output_sha256 or ""),),
        ).fetchone()
        return self._row_to_record(row)

    def iter_resolution_candidates(self) -> list[_ResolutionCandidate]:
        rows = self.conn.execute(
            """
            SELECT
                f.forensic_export_id,
                f.batch_id,
                f.derivative_export_id,
                f.track_id,
                f.key_id,
                f.token_version,
                f.forensic_watermark_version,
                f.token_id,
                f.binding_crc32,
                f.recipient_label,
                f.share_label,
                f.output_format,
                f.output_filename,
                f.output_sha256,
                f.output_size_bytes,
                f.source_lineage_ref,
                f.created_at,
                f.last_verified_at,
                f.last_verification_status,
                f.last_verification_confidence,
                COALESCE(d.source_audio_sha256, ''),
                d.source_lineage_ref
            FROM ForensicWatermarkExports f
            LEFT JOIN TrackAudioDerivatives d ON d.export_id = f.derivative_export_id
            ORDER BY f.created_at DESC, f.id DESC
            """
        ).fetchall()
        candidates: list[_ResolutionCandidate] = []
        for row in rows:
            record = self._row_to_record(row[:20])
            if record is None:
                continue
            candidates.append(
                _ResolutionCandidate(
                    record=record,
                    source_audio_sha256=str(row[20] or ""),
                    source_lineage_ref=_clean_text(row[21]),
                )
            )
        return candidates

    def record_verification(
        self, forensic_export_id: str, *, status: str, confidence: float | None
    ) -> None:
        self.conn.execute(
            """
            UPDATE ForensicWatermarkExports
            SET last_verified_at=datetime('now'),
                last_verification_status=?,
                last_verification_confidence=?
            WHERE forensic_export_id=?
            """,
            (
                str(status or ""),
                float(confidence) if confidence is not None else None,
                str(forensic_export_id),
            ),
        )


class ForensicExportCoordinator:
    """Runs recipient-specific forensic watermark exports and inspections."""

    def __init__(
        self,
        *,
        conn,
        track_service: TrackService,
        release_service: ReleaseService | None,
        tag_service: AudioTagService,
        key_service: AuthenticityKeyService,
        conversion_service: AudioConversionService | None = None,
        watermark_service: ForensicWatermarkService | None = None,
    ):
        self.conn = conn
        self.track_service = track_service
        self.release_service = release_service
        self.tag_service = tag_service
        self.key_service = key_service
        self.conversion_service = conversion_service or AudioConversionService()
        self.watermark_service = watermark_service or ForensicWatermarkService()
        self.derivative_ledger = DerivativeLedgerService(conn)
        self.forensic_ledger = ForensicLedgerService(conn)

    def _forensic_key_material(self, key_id: str | None = None) -> tuple[str, bytes]:
        key_record, private_key, _authenticity_watermark_key = self.key_service.signing_material(
            key_id
        )
        return key_record.key_id, derive_forensic_watermark_key(private_key)

    def _forensic_extraction_keys(self) -> list[tuple[str, bytes]]:
        ordered = self.key_service.list_keys()
        default_key_id = self.key_service.default_key_id()
        if default_key_id:
            ordered.sort(key=lambda item: (0 if item.key_id == default_key_id else 1, item.key_id))
        result: list[tuple[str, bytes]] = []
        for record in ordered:
            try:
                private_key = self.key_service.load_private_key(record.key_id)
            except Exception:
                continue
            result.append((record.key_id, derive_forensic_watermark_key(private_key)))
        return result

    def _prepare_analysis_audio(self, source_path: Path, temp_dir: Path) -> Path:
        if supported_forensic_audio_path(source_path):
            return source_path
        if not self.conversion_service.is_supported_target("wav"):
            raise ValueError(
                "The selected file format cannot be decoded for forensic inspection on this system."
            )
        analysis_path = (
            temp_dir / f"{sanitize_export_basename(source_path.stem or source_path.name)}.wav"
        )
        self.conversion_service.transcode(
            source_path=source_path,
            destination_path=analysis_path,
            target_id="wav",
        )
        return analysis_path

    def _rebuild_reference_audio(
        self,
        *,
        candidate: _ResolutionCandidate,
        temp_dir: Path,
    ) -> Path | None:
        if not candidate.source_audio_sha256:
            return None
        if not self.track_service.has_media(candidate.record.track_id, "audio_file"):
            return None
        source_handle = self.track_service.resolve_media_source(
            candidate.record.track_id, "audio_file"
        )
        if source_handle.sha256_hex() != candidate.source_audio_sha256:
            return None
        output_format = str(candidate.record.output_format or "").strip().lower()
        output_profile = audio_format_profile(output_format)
        if output_profile is None:
            return None
        reference_path = (
            temp_dir
            / f"reference-{candidate.record.forensic_export_id}{output_profile.suffixes[0]}"
        )
        with source_handle.materialize_path() as materialized_source:
            self.conversion_service.transcode(
                source_path=materialized_source,
                destination_path=reference_path,
                target_id=output_format,
            )
        if supported_forensic_audio_path(reference_path):
            return reference_path
        analysis_reference_path = temp_dir / f"reference-{candidate.record.forensic_export_id}.wav"
        self.conversion_service.transcode(
            source_path=reference_path,
            destination_path=analysis_reference_path,
            target_id="wav",
        )
        return analysis_reference_path

    def _match_report(
        self,
        *,
        status: str,
        message: str,
        inspected_path: str | Path,
        record: ForensicExportRecord,
        confidence: float | None,
        resolution_basis: str,
        exact_hash_match: bool | None = None,
        extra_details: list[str] | None = None,
    ) -> ForensicInspectionReport:
        details = [
            f"Forensic Export ID: {record.forensic_export_id}",
            f"Batch ID: {record.batch_id}",
            f"Track ID: {record.track_id}",
        ]
        if record.derivative_export_id:
            details.append(f"Derivative Export ID: {record.derivative_export_id}")
        if record.recipient_label:
            details.append(f"Recipient: {record.recipient_label}")
        if record.share_label:
            details.append(f"Share Label: {record.share_label}")
        if record.output_format:
            details.append(f"Output Format: {record.output_format}")
        if record.output_filename:
            details.append(f"Output Filename: {record.output_filename}")
        if record.output_sha256:
            details.append(f"Final SHA-256: {record.output_sha256}")
        if extra_details:
            details.extend(extra_details)
        return ForensicInspectionReport(
            status=status,
            message=message,
            inspected_path=str(inspected_path),
            forensic_export_id=record.forensic_export_id,
            batch_id=record.batch_id,
            derivative_export_id=record.derivative_export_id,
            track_id=record.track_id,
            recipient_label=record.recipient_label,
            share_label=record.share_label,
            output_format=record.output_format,
            token_id=record.token_id,
            exact_hash_match=exact_hash_match,
            confidence_score=confidence,
            resolution_basis=resolution_basis,
            details=details,
        )

    def export(
        self,
        request: ForensicExportRequest,
        *,
        progress_callback=None,
        is_cancelled=None,
    ) -> ForensicExportResult:
        output_format = str(request.output_format or "").strip().lower()
        output_profile = audio_format_profile(output_format)
        if output_profile is None:
            raise ValueError(f"Unsupported forensic output format: {request.output_format}")
        if not self.conversion_service.is_supported_target(
            output_format,
            capability_group="managed_forensic",
        ):
            raise ValueError(f"Unsupported forensic watermark target: {request.output_format}")
        destination_root = Path(request.output_dir)
        destination_root.mkdir(parents=True, exist_ok=True)
        track_ids = [int(track_id) for track_id in request.track_ids]
        batch_public_id = _batch_public_id()
        warnings: list[str] = []
        written_paths: list[str] = []
        derivative_ids: list[str] = []
        forensic_export_ids: list[str] = []
        exported_states: list[_ForensicExportState] = []
        exported = 0
        batch_id: str | None = None
        zip_path: Path | None = None
        key_id, forensic_watermark_key = self._forensic_key_material(request.key_id)

        try:
            with self.conn:
                batch_id = self.derivative_ledger.create_batch(
                    batch_public_id=batch_public_id,
                    track_count=len(track_ids),
                    output_format=output_format,
                    workflow_kind=WORKFLOW_KIND_FORENSIC_EXPORT,
                    derivative_kind=DERIVATIVE_KIND_FORENSIC_WATERMARKED_COPY,
                    authenticity_basis=AUTHENTICITY_BASIS_FORENSIC_TRACE,
                    profile_name=request.profile_name,
                )
                with tempfile.TemporaryDirectory(
                    prefix=f"forensic-export-{batch_public_id}-"
                ) as temp_dir_text:
                    temp_dir = Path(temp_dir_text)
                    temp_final_dir = temp_dir / "finalized"
                    temp_final_dir.mkdir(parents=True, exist_ok=True)
                    for item_index, track_id in enumerate(track_ids, start=1):
                        if is_cancelled is not None and is_cancelled():
                            raise InterruptedError("Forensic watermark export cancelled.")
                        snapshot = self.track_service.fetch_track_snapshot(track_id)
                        if snapshot is None or not self.track_service.has_media(
                            track_id, "audio_file"
                        ):
                            warnings.append(f"Track {track_id} has no attached audio.")
                            continue
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
                        watermarked_path = temp_dir / f"{base_name}.forensic{source_ext}"
                        _report_stage(
                            progress_callback,
                            item_index=item_index,
                            item_total=len(track_ids),
                            stage_index=0,
                            stage_count=_FORENSIC_STAGE_COUNT,
                            message=f"Resolving source {item_index} of {len(track_ids)}: {snapshot.track_title}",
                        )
                        with source_handle.materialize_path() as materialized_source:
                            if is_cancelled is not None and is_cancelled():
                                raise InterruptedError("Forensic watermark export cancelled.")
                            _report_stage(
                                progress_callback,
                                item_index=item_index,
                                item_total=len(track_ids),
                                stage_index=1,
                                stage_count=_FORENSIC_STAGE_COUNT,
                                message=f"Converting {item_index} of {len(track_ids)}: {snapshot.track_title}",
                            )
                            self.conversion_service.transcode(
                                source_path=materialized_source,
                                destination_path=converted_path,
                                target_id=output_format,
                            )
                        tag_data = build_catalog_tag_data(
                            track_id,
                            track_service=self.track_service,
                            release_service=self.release_service,
                            release_policy="unambiguous",
                            include_artwork_bytes=True,
                        )
                        _report_stage(
                            progress_callback,
                            item_index=item_index,
                            item_total=len(track_ids),
                            stage_index=2,
                            stage_count=_FORENSIC_STAGE_COUNT,
                            message=f"Writing metadata {item_index} of {len(track_ids)}: {snapshot.track_title}",
                        )
                        self.tag_service.write_tags(converted_path, tag_data)
                        token = ForensicWatermarkToken(
                            version=FORENSIC_TOKEN_VERSION,
                            token_id=max(1, int(secrets.randbits(48))),
                            binding_crc32=_binding_crc32(
                                batch_id=batch_public_id,
                                track_id=track_id,
                                output_format=output_format,
                                recipient_label=request.recipient_label,
                                share_label=request.share_label,
                            ),
                        )
                        _report_stage(
                            progress_callback,
                            item_index=item_index,
                            item_total=len(track_ids),
                            stage_index=3,
                            stage_count=_FORENSIC_STAGE_COUNT,
                            message=f"Applying forensic watermark {item_index} of {len(track_ids)}: {snapshot.track_title}",
                        )
                        self.watermark_service.embed_export_path(
                            source_path=converted_path,
                            destination_path=watermarked_path,
                            output_format=output_format,
                            conversion_service=self.conversion_service,
                            watermark_key=forensic_watermark_key,
                            token=token,
                        )
                        # Keep DB metadata on the final delivery file after watermark finalization.
                        self.tag_service.write_tags(watermarked_path, tag_data)
                        _report_stage(
                            progress_callback,
                            item_index=item_index,
                            item_total=len(track_ids),
                            stage_index=4,
                            stage_count=_FORENSIC_STAGE_COUNT,
                            message=f"Hashing final output {item_index} of {len(track_ids)}: {snapshot.track_title}",
                        )
                        final_sha256 = _sha256_for_file(watermarked_path)
                        final_name = _filename_with_hash_suffix(
                            f"{base_name}{source_ext}", final_sha256
                        )
                        _report_stage(
                            progress_callback,
                            item_index=item_index,
                            item_total=len(track_ids),
                            stage_index=5,
                            stage_count=_FORENSIC_STAGE_COUNT,
                            message=f"Registering derivative {item_index} of {len(track_ids)}: {snapshot.track_title}",
                        )
                        derivative_id = self.derivative_ledger.create_derivative(
                            source_track_id=track_id,
                            export_batch_id=batch_id,
                            workflow_kind=WORKFLOW_KIND_FORENSIC_EXPORT,
                            derivative_kind=DERIVATIVE_KIND_FORENSIC_WATERMARKED_COPY,
                            authenticity_basis=AUTHENTICITY_BASIS_FORENSIC_TRACE,
                            output_format=output_format,
                            watermark_applied=True,
                            metadata_embedded=True,
                            final_sha256=final_sha256,
                            output_filename=final_name,
                            source_lineage_ref=source_lineage_ref,
                            source_sha256=source_sha256,
                            source_storage_mode=source_handle.storage_mode,
                            authenticity_manifest_id=None,
                            output_size_bytes=int(watermarked_path.stat().st_size),
                            filename_hash_suffix=final_sha256[:12],
                            output_mime_type=(
                                output_profile.mime_types[0] if output_profile.mime_types else None
                            ),
                        )
                        derivative_ids.append(derivative_id)
                        _report_stage(
                            progress_callback,
                            item_index=item_index,
                            item_total=len(track_ids),
                            stage_index=6,
                            stage_count=_FORENSIC_STAGE_COUNT,
                            message=f"Registering forensic export {item_index} of {len(track_ids)}: {snapshot.track_title}",
                        )
                        forensic_export_id = self.forensic_ledger.create_export(
                            batch_id=batch_id,
                            derivative_export_id=derivative_id,
                            track_id=track_id,
                            key_id=key_id,
                            token=token,
                            recipient_label=request.recipient_label,
                            share_label=request.share_label,
                            output_format=output_format,
                            output_filename=final_name,
                            output_sha256=final_sha256,
                            output_size_bytes=int(watermarked_path.stat().st_size),
                            source_lineage_ref=source_lineage_ref,
                        )
                        forensic_export_ids.append(forensic_export_id)
                        final_temp_path = temp_final_dir / final_name
                        _report_stage(
                            progress_callback,
                            item_index=item_index,
                            item_total=len(track_ids),
                            stage_index=7,
                            stage_count=_FORENSIC_STAGE_COUNT,
                            message=f"Finalizing filename {item_index} of {len(track_ids)}: {snapshot.track_title}",
                        )
                        shutil.move(str(watermarked_path), str(final_temp_path))
                        exported_states.append(
                            _ForensicExportState(
                                track_id=track_id,
                                track_title=str(snapshot.track_title or ""),
                                temp_final_path=final_temp_path,
                                final_name=final_name,
                                derivative_id=derivative_id,
                                forensic_export_id=forensic_export_id,
                            )
                        )
                        exported += 1
                    if exported == 0:
                        self.derivative_ledger.delete_batch(batch_id)
                    elif exported > 1:
                        _report_stage(
                            progress_callback,
                            item_index=len(track_ids),
                            item_total=len(track_ids),
                            stage_index=8,
                            stage_count=_FORENSIC_STAGE_COUNT,
                            message="Packaging forensic ZIP archive…",
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
                        self.derivative_ledger.update_batch_completion(
                            batch_id,
                            exported_count=exported,
                            skipped_count=max(0, len(track_ids) - exported),
                            package_mode="zip",
                            status="completed",
                            zip_filename=zip_path.name,
                        )
                    elif exported_states:
                        final_destination = destination_root / exported_states[0].final_name
                        shutil.move(str(exported_states[0].temp_final_path), str(final_destination))
                        written_paths.append(str(final_destination))
                        self.derivative_ledger.update_batch_completion(
                            batch_id,
                            exported_count=exported,
                            skipped_count=max(0, len(track_ids) - exported),
                            package_mode="directory",
                            status="completed",
                            zip_filename=None,
                        )
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
        if progress_callback is not None:
            progress_callback(
                max(1, len(track_ids) * _FORENSIC_STAGE_COUNT),
                max(1, len(track_ids) * _FORENSIC_STAGE_COUNT),
                "Forensic watermark export finished.",
            )
        return ForensicExportResult(
            requested=len(track_ids),
            exported=exported,
            skipped=skipped,
            warnings=warnings,
            written_paths=written_paths,
            derivative_ids=derivative_ids,
            forensic_export_ids=forensic_export_ids,
            batch_public_id=batch_public_id,
            zip_path=str(zip_path) if zip_path is not None else None,
            recipient_label=request.recipient_label,
            share_label=request.share_label,
        )

    def inspect_file(
        self,
        path: str | Path,
        *,
        progress_callback=None,
        is_cancelled=None,
    ) -> ForensicInspectionReport:
        inspected_path = Path(path)
        if not inspected_path.exists():
            raise FileNotFoundError(inspected_path)
        extraction_keys = self._forensic_extraction_keys()
        original_sha256 = _sha256_for_file(inspected_path)

        with tempfile.TemporaryDirectory(prefix="forensic-inspection-") as temp_dir_text:
            temp_dir = Path(temp_dir_text)
            try:
                _report_stage(
                    progress_callback,
                    item_index=1,
                    item_total=1,
                    stage_index=0,
                    stage_count=_FORENSIC_INSPECTION_STAGE_COUNT,
                    message="Preparing inspection source…",
                )
                analysis_path = self._prepare_analysis_audio(inspected_path, temp_dir)
            except Exception:
                return ForensicInspectionReport(
                    status=FORENSIC_STATUS_UNSUPPORTED_OR_INSUFFICIENT,
                    message=(
                        "The selected file could not be decoded into a forensic inspection source "
                        "with the current runtime."
                    ),
                    inspected_path=str(inspected_path),
                    resolution_basis="decode_failure",
                    details=[],
                )

            _report_stage(
                progress_callback,
                item_index=1,
                item_total=1,
                stage_index=1,
                stage_count=_FORENSIC_INSPECTION_STAGE_COUNT,
                message="Attempting forensic token extraction…",
            )
            extraction = self.watermark_service.extract_from_path(
                analysis_path, watermark_keys=extraction_keys
            )
            if extraction.token is not None:
                matched_record = self.forensic_ledger.fetch_by_token(
                    extraction.token.token_id,
                    extraction.token.binding_crc32,
                )
                if matched_record is not None:
                    confidence = float(extraction.mean_confidence or 0.0)
                    status = (
                        FORENSIC_STATUS_MATCH_FOUND
                        if extraction.status == "detected"
                        else FORENSIC_STATUS_MATCH_LOW_CONFIDENCE
                    )
                    exact_hash_match = (
                        bool(matched_record.output_sha256)
                        and matched_record.output_sha256 == original_sha256
                    )
                    self.forensic_ledger.record_verification(
                        matched_record.forensic_export_id,
                        status=status,
                        confidence=confidence,
                    )
                    return self._match_report(
                        status=status,
                        message=(
                            "A forensic watermark token was extracted and resolved to a managed "
                            "forensic export record."
                            if status == FORENSIC_STATUS_MATCH_FOUND
                            else "A forensic watermark token candidate was found and resolved, but the confidence stayed below the strong-match threshold."
                        ),
                        inspected_path=inspected_path,
                        record=matched_record,
                        confidence=confidence,
                        resolution_basis="blind_forensic_token",
                        exact_hash_match=exact_hash_match,
                    )
                return ForensicInspectionReport(
                    status=FORENSIC_STATUS_TOKEN_UNRESOLVED,
                    message=(
                        "A forensic watermark token was extracted, but it could not be resolved "
                        "to a forensic export record in the open profile."
                    ),
                    inspected_path=str(inspected_path),
                    token_id=extraction.token.token_id,
                    confidence_score=float(extraction.mean_confidence or 0.0),
                    resolution_basis="blind_forensic_token",
                    details=[
                        f"Token ID: {extraction.token.token_id}",
                        f"Binding CRC32: {extraction.token.binding_crc32}",
                    ],
                )

            exact_hash_record = self.forensic_ledger.fetch_by_output_sha256(original_sha256)
            if exact_hash_record is not None:
                self.forensic_ledger.record_verification(
                    exact_hash_record.forensic_export_id,
                    status=FORENSIC_STATUS_MATCH_FOUND,
                    confidence=1.0,
                )
                return self._match_report(
                    status=FORENSIC_STATUS_MATCH_FOUND,
                    message=(
                        "The inspected file exactly matches a previously exported forensic copy "
                        "from the derivative ledger."
                    ),
                    inspected_path=inspected_path,
                    record=exact_hash_record,
                    confidence=1.0,
                    resolution_basis="exact_output_hash",
                    exact_hash_match=True,
                )

            _report_stage(
                progress_callback,
                item_index=1,
                item_total=1,
                stage_index=2,
                stage_count=_FORENSIC_INSPECTION_STAGE_COUNT,
                message="Comparing against known forensic exports…",
            )
            best_candidate: _ResolutionCandidate | None = None
            best_result = None
            for candidate in self.forensic_ledger.iter_resolution_candidates():
                if is_cancelled is not None and is_cancelled():
                    raise InterruptedError("Forensic inspection cancelled.")
                try:
                    reference_path = self._rebuild_reference_audio(
                        candidate=candidate, temp_dir=temp_dir
                    )
                except Exception:
                    reference_path = None
                if reference_path is None:
                    continue
                try:
                    _key_id, forensic_key = self._forensic_key_material(candidate.record.key_id)
                    result = self.watermark_service.verify_expected_token_against_reference(
                        analysis_path,
                        reference_path=reference_path,
                        watermark_keys=[(candidate.record.key_id, forensic_key)],
                        token=ForensicWatermarkToken(
                            version=int(candidate.record.token_version),
                            token_id=int(candidate.record.token_id),
                            binding_crc32=int(candidate.record.binding_crc32),
                        ),
                    )
                except Exception:
                    continue
                if result.status == "detected":
                    confidence = float(result.mean_confidence or 0.0)
                    self.forensic_ledger.record_verification(
                        candidate.record.forensic_export_id,
                        status=FORENSIC_STATUS_MATCH_FOUND,
                        confidence=confidence,
                    )
                    return self._match_report(
                        status=FORENSIC_STATUS_MATCH_FOUND,
                        message=(
                            "The inspected file matched a known forensic export after "
                            "reference-guided watermark comparison."
                        ),
                        inspected_path=inspected_path,
                        record=candidate.record,
                        confidence=confidence,
                        resolution_basis="reference_guided_forensic",
                        exact_hash_match=False,
                    )
                if best_result is None or (
                    result.mean_confidence,
                    result.group_agreement,
                    result.sync_score,
                ) > (
                    best_result.mean_confidence,
                    best_result.group_agreement,
                    best_result.sync_score,
                ):
                    best_candidate = candidate
                    best_result = result

            _report_stage(
                progress_callback,
                item_index=1,
                item_total=1,
                stage_index=3,
                stage_count=_FORENSIC_INSPECTION_STAGE_COUNT,
                message="Forensic inspection finished.",
            )
            if (
                best_candidate is not None
                and best_result is not None
                and best_result.status == "insufficient"
            ):
                confidence = float(best_result.mean_confidence or 0.0)
                self.forensic_ledger.record_verification(
                    best_candidate.record.forensic_export_id,
                    status=FORENSIC_STATUS_MATCH_LOW_CONFIDENCE,
                    confidence=confidence,
                )
                return self._match_report(
                    status=FORENSIC_STATUS_MATCH_LOW_CONFIDENCE,
                    message=(
                        "A likely forensic export match was found, but the watermark evidence "
                        "did not meet the strong-match threshold."
                    ),
                    inspected_path=inspected_path,
                    record=best_candidate.record,
                    confidence=confidence,
                    resolution_basis="reference_guided_forensic",
                    exact_hash_match=False,
                    extra_details=[
                        f"Sync Score: {best_result.sync_score:.3f}",
                        f"Group Agreement: {best_result.group_agreement:.3f}",
                    ],
                )
            return ForensicInspectionReport(
                status=FORENSIC_STATUS_NOT_DETECTED,
                message=(
                    "No resolvable forensic watermark was detected in the inspected audio with "
                    "the current profile keys and export ledger."
                ),
                inspected_path=str(inspected_path),
                resolution_basis="no_match",
                details=[],
            )

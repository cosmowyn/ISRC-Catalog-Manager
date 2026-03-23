"""Dataclasses and constants for forensic watermark export workflows."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

FORENSIC_WATERMARK_VERSION = 1
FORENSIC_TOKEN_VERSION = 1

WORKFLOW_KIND_FORENSIC_EXPORT = "forensic_watermark_export"
DERIVATIVE_KIND_FORENSIC_WATERMARKED_COPY = "forensic_watermarked_copy"
AUTHENTICITY_BASIS_FORENSIC_TRACE = "forensic_trace"

FORENSIC_STATUS_MATCH_FOUND = "forensic_match_found"
FORENSIC_STATUS_MATCH_LOW_CONFIDENCE = "forensic_match_low_confidence"
FORENSIC_STATUS_NOT_DETECTED = "forensic_watermark_not_detected"
FORENSIC_STATUS_UNSUPPORTED_OR_INSUFFICIENT = "unsupported_format_or_insufficient_confidence"
FORENSIC_STATUS_TOKEN_UNRESOLVED = "token_found_but_unresolved"


@dataclass(slots=True)
class ForensicWatermarkToken:
    version: int
    token_id: int
    binding_crc32: int
    crc32: int | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class ForensicWatermarkExtractionResult:
    status: str
    key_id: str | None
    token: ForensicWatermarkToken | None
    mean_confidence: float
    sync_score: float
    group_agreement: float
    repeat_groups: int
    crc_ok: bool

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["token"] = self.token.to_dict() if self.token is not None else None
        return data


@dataclass(slots=True)
class ForensicExportRequest:
    track_ids: list[int]
    output_dir: str
    output_format: str
    recipient_label: str | None = None
    share_label: str | None = None
    profile_name: str | None = None
    key_id: str | None = None


@dataclass(slots=True)
class ForensicExportResult:
    requested: int
    exported: int
    skipped: int
    warnings: list[str]
    written_paths: list[str]
    derivative_ids: list[str]
    forensic_export_ids: list[str]
    batch_public_id: str
    zip_path: str | None = None
    recipient_label: str | None = None
    share_label: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class ForensicExportRecord:
    forensic_export_id: str
    batch_id: str
    derivative_export_id: str | None
    track_id: int
    key_id: str
    token_version: int
    forensic_watermark_version: int
    token_id: int
    binding_crc32: int
    recipient_label: str | None
    share_label: str | None
    output_format: str | None
    output_filename: str | None
    output_sha256: str | None
    output_size_bytes: int
    source_lineage_ref: str | None
    created_at: str | None
    last_verified_at: str | None = None
    last_verification_status: str | None = None
    last_verification_confidence: float | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class ForensicInspectionReport:
    status: str
    message: str
    inspected_path: str
    forensic_export_id: str | None = None
    batch_id: str | None = None
    derivative_export_id: str | None = None
    track_id: int | None = None
    recipient_label: str | None = None
    share_label: str | None = None
    output_format: str | None = None
    token_id: int | None = None
    exact_hash_match: bool | None = None
    confidence_score: float | None = None
    resolution_basis: str | None = None
    details: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

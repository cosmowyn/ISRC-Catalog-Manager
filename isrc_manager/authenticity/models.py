"""Shared dataclasses for audio authenticity workflows."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

AUTHENTICITY_SCHEMA_VERSION = 1
WATERMARK_VERSION = 1
DOCUMENT_TYPE_DIRECT_WATERMARK = "direct_watermark"
DOCUMENT_TYPE_PROVENANCE_LINEAGE = "provenance_lineage"
WORKFLOW_KIND_AUTHENTICITY_MASTER = "authenticity_master"
WORKFLOW_KIND_AUTHENTICITY_LINEAGE = "authenticity_lineage"

DIRECT_WATERMARK_SUFFIXES = frozenset({".wav", ".flac", ".aif", ".aiff"})
PROVENANCE_ONLY_SUFFIXES = frozenset({".mp3", ".ogg", ".oga", ".opus", ".m4a", ".mp4", ".aac"})
VERIFICATION_INPUT_SUFFIXES = frozenset(DIRECT_WATERMARK_SUFFIXES | PROVENANCE_ONLY_SUFFIXES)
SUPPORTED_AUTHENTICITY_SUFFIXES = DIRECT_WATERMARK_SUFFIXES

VERIFICATION_STATUS_VERIFIED = "verified_authentic"
VERIFICATION_STATUS_VERIFIED_BY_LINEAGE = "verified_by_lineage"
VERIFICATION_STATUS_SIGNATURE_INVALID = "signature_invalid"
VERIFICATION_STATUS_MANIFEST_REFERENCE_MISMATCH = "manifest_found_reference_mismatch"
VERIFICATION_STATUS_NO_WATERMARK = "no_watermark_detected"
VERIFICATION_STATUS_UNSUPPORTED_OR_INSUFFICIENT = "unsupported_format_or_insufficient_confidence"


@dataclass(slots=True)
class AuthenticityKeyRecord:
    key_id: str
    algorithm: str
    signer_label: str | None
    public_key_b64: str
    created_at: str | None
    retired_at: str | None
    notes: str | None
    has_private_key: bool = False
    is_default: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class AuthenticityManifestRecord:
    id: int
    track_id: int
    reference_asset_id: int | None
    key_id: str
    manifest_schema_version: int
    watermark_version: int
    manifest_id: str
    watermark_id: int
    watermark_nonce: int
    manifest_digest_prefix: str
    payload_canonical: str
    payload_sha256: str
    signature_b64: str
    reference_audio_sha256: str
    reference_fingerprint_b64: str
    reference_source_kind: str
    embed_settings_json: str | None
    created_at: str | None
    revoked_at: str | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class WatermarkToken:
    version: int
    watermark_id: int
    manifest_digest_prefix: str
    nonce: int
    crc32: int | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class ReferenceAudioSelection:
    track_id: int
    source_kind: str
    source_label: str
    reference_asset_id: int | None
    filename: str
    mime_type: str | None
    size_bytes: int
    suffix: str
    source_path: Path | None = None
    source_bytes: bytes | None = None
    sample_rate: int | None = None
    bit_depth: int | None = None
    format_name: str | None = None
    sha256_hex: str | None = None
    fingerprint_b64: str | None = None

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["source_path"] = str(self.source_path) if self.source_path is not None else None
        if self.source_bytes is not None:
            data["source_bytes"] = f"<{len(self.source_bytes)} bytes>"
        return data


@dataclass(slots=True)
class PreparedAuthenticityManifest:
    track_id: int
    track_title: str
    suggested_name: str
    key_id: str
    signer_label: str | None
    public_key_b64: str
    payload: dict[str, object]
    payload_canonical: str
    payload_sha256: str
    signature_b64: str
    watermark_token: WatermarkToken
    reference: ReferenceAudioSelection
    embed_settings: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["reference"] = self.reference.to_dict()
        data["watermark_token"] = self.watermark_token.to_dict()
        return data


@dataclass(slots=True)
class AuthenticityExportPlanItem:
    track_id: int
    track_title: str
    source_label: str
    source_suffix: str
    suggested_name: str
    key_id: str
    document_type: str = DOCUMENT_TYPE_DIRECT_WATERMARK
    workflow_kind: str = WORKFLOW_KIND_AUTHENTICITY_MASTER
    status: str = "ready"
    warning: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class AuthenticityExportPlan:
    key_id: str
    signer_label: str | None
    document_type: str = DOCUMENT_TYPE_DIRECT_WATERMARK
    workflow_kind: str = WORKFLOW_KIND_AUTHENTICITY_MASTER
    items: list[AuthenticityExportPlanItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def ready_items(self) -> list[AuthenticityExportPlanItem]:
        return [item for item in self.items if item.status == "ready"]

    def to_dict(self) -> dict[str, object]:
        return {
            "key_id": self.key_id,
            "signer_label": self.signer_label,
            "document_type": self.document_type,
            "workflow_kind": self.workflow_kind,
            "items": [item.to_dict() for item in self.items],
            "warnings": list(self.warnings),
        }


@dataclass(slots=True)
class AuthenticityExportResult:
    requested: int
    exported: int
    skipped: int
    warnings: list[str]
    written_audio_paths: list[str]
    written_sidecar_paths: list[str]
    manifest_ids: list[str]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class WatermarkExtractionResult:
    status: str
    key_id: str | None
    token: WatermarkToken | None
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
class AuthenticityVerificationReport:
    status: str
    message: str
    inspected_path: str
    key_id: str | None = None
    manifest_id: str | None = None
    watermark_id: int | None = None
    resolution_source: str | None = None
    verification_basis: str | None = None
    document_type: str | None = None
    workflow_kind: str | None = None
    parent_manifest_id: str | None = None
    signature_valid: bool | None = None
    exact_hash_match: bool | None = None
    fingerprint_similarity: float | None = None
    extraction_confidence: float | None = None
    sidecar_path: str | None = None
    details: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

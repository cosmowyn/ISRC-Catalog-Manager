"""Dataclasses for deliverables and asset version tracking."""

from __future__ import annotations

from dataclasses import asdict, dataclass


ASSET_TYPE_CHOICES = (
    "main_master",
    "instrumental",
    "radio_edit",
    "extended_mix",
    "clean_version",
    "explicit_version",
    "alt_master",
    "hi_res_master",
    "mp3_derivative",
    "artwork_front",
    "artwork_alternate",
    "promotional_asset",
    "other",
)


@dataclass(slots=True)
class AssetVersionPayload:
    asset_type: str
    filename: str | None = None
    source_path: str | None = None
    stored_path: str | None = None
    checksum_sha256: str | None = None
    duration_sec: int | None = None
    sample_rate: int | None = None
    bit_depth: int | None = None
    format: str | None = None
    derived_from_asset_id: int | None = None
    approved_for_use: bool = False
    primary_flag: bool = False
    version_status: str | None = None
    notes: str | None = None
    track_id: int | None = None
    release_id: int | None = None


@dataclass(slots=True)
class AssetVersionRecord:
    id: int
    asset_type: str
    filename: str
    stored_path: str | None
    checksum_sha256: str | None
    duration_sec: int | None
    sample_rate: int | None
    bit_depth: int | None
    format: str | None
    derived_from_asset_id: int | None
    approved_for_use: bool
    primary_flag: bool
    version_status: str | None
    notes: str | None
    track_id: int | None
    release_id: int | None
    created_at: str | None
    updated_at: str | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class AssetValidationIssue:
    severity: str
    issue_type: str
    asset_id: int | None
    message: str

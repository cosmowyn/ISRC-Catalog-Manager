"""Dataclasses for release-level catalog management."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(slots=True)
class ReleaseTrackPlacement:
    track_id: int
    disc_number: int = 1
    track_number: int = 1
    sequence_number: int = 1


@dataclass(slots=True)
class ReleasePayload:
    title: str
    version_subtitle: str | None = None
    primary_artist: str | None = None
    album_artist: str | None = None
    release_type: str = "album"
    release_date: str | None = None
    original_release_date: str | None = None
    label: str | None = None
    sublabel: str | None = None
    catalog_number: str | None = None
    upc: str | None = None
    territory: str | None = None
    explicit_flag: bool = False
    notes: str | None = None
    artwork_source_path: str | None = None
    clear_artwork: bool = False
    profile_name: str | None = None
    placements: list[ReleaseTrackPlacement] = field(default_factory=list)


@dataclass(slots=True)
class ReleaseRecord:
    id: int
    title: str
    version_subtitle: str | None
    primary_artist: str | None
    album_artist: str | None
    release_type: str
    release_date: str | None
    original_release_date: str | None
    label: str | None
    sublabel: str | None
    catalog_number: str | None
    upc: str | None
    barcode_validation_status: str
    territory: str | None
    explicit_flag: bool
    notes: str | None
    artwork_path: str | None
    artwork_mime_type: str | None
    artwork_size_bytes: int
    profile_name: str | None
    track_count: int = 0

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class ReleaseSummary:
    release: ReleaseRecord
    tracks: list[ReleaseTrackPlacement]


@dataclass(slots=True)
class ReleaseValidationIssue:
    severity: str
    field_name: str
    message: str

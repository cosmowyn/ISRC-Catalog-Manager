"""Canonical audio tag models used across format adapters."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(slots=True)
class ArtworkPayload:
    data: bytes
    mime_type: str
    description: str = ""


@dataclass(slots=True)
class AudioTagData:
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    album_artist: str | None = None
    track_number: int | None = None
    disc_number: int | None = None
    genre: str | None = None
    composer: str | None = None
    publisher: str | None = None
    release_date: str | None = None
    isrc: str | None = None
    upc: str | None = None
    comments: str | None = None
    lyrics: str | None = None
    artwork: ArtworkPayload | None = None
    raw_fields: dict[str, object] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class TagFieldConflict:
    field_name: str
    database_value: object
    file_value: object
    chosen_value: object


@dataclass(slots=True)
class TaggedAudioExportResult:
    requested: int
    exported: int
    skipped: int
    warnings: list[str]
    written_paths: list[str]


@dataclass(slots=True)
class TaggedAudioExportItem:
    suggested_name: str
    tag_data: AudioTagData
    source_suffix: str
    source_path: str | Path | None = None
    source_bytes: bytes | bytearray | memoryview | None = None
    album_title: str | None = None

    def __post_init__(self) -> None:
        if (self.source_path is None) == (self.source_bytes is None):
            raise ValueError("TaggedAudioExportItem requires exactly one source input.")


@dataclass(slots=True)
class TaggedAudioExportPlanItem:
    track_id: int
    track_title: str
    suggested_name: str
    source_suffix: str
    source_label: str
    album_title: str | None = None


@dataclass(slots=True)
class BulkAudioAttachTrackCandidate:
    track_id: int
    title: str
    artist: str | None = None
    album: str | None = None
    isrc: str | None = None


@dataclass(slots=True)
class BulkAudioAttachPlanItem:
    source_path: str
    source_name: str
    detected_title: str | None = None
    detected_artist: str | None = None
    matched_track_id: int | None = None
    matched_track_title: str | None = None
    matched_track_artist: str | None = None
    candidate_track_ids: list[int] = field(default_factory=list)
    match_basis: str | None = None
    status: str = "unmatched"
    warning: str | None = None


@dataclass(slots=True)
class BulkAudioAttachPlan:
    items: list[BulkAudioAttachPlanItem]
    warnings: list[str] = field(default_factory=list)
    suggested_artist: str | None = None


@dataclass(slots=True)
class DroppedAudioImportItem:
    source_path: str
    source_name: str
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    album_artist: str | None = None
    track_number: int | None = None
    release_date: str | None = None
    duration_seconds: int | None = None
    isrc: str | None = None
    upc: str | None = None
    genre: str | None = None
    composer: str | None = None
    publisher: str | None = None
    comments: str | None = None
    lyrics: str | None = None
    artwork: ArtworkPayload | None = None
    warning: str | None = None


@dataclass(slots=True)
class DroppedAudioImportPlan:
    items: list[DroppedAudioImportItem]
    warnings: list[str] = field(default_factory=list)
    suggested_artist: str | None = None


@dataclass(slots=True)
class BulkAudioAttachResult:
    attached_count: int
    artist_updated_count: int
    skipped_count: int
    warnings: list[str] = field(default_factory=list)
    track_ids: list[int] = field(default_factory=list)

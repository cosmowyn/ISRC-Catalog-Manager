"""Canonical audio tag models used across format adapters."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


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

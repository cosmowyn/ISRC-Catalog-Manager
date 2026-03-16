"""Dataclasses for first-class musical works and their creators."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


WORK_CREATOR_ROLE_CHOICES = (
    "songwriter",
    "composer",
    "lyricist",
    "arranger",
    "adaptor",
    "publisher",
    "subpublisher",
)

WORK_STATUS_CHOICES = (
    "idea",
    "demo",
    "in_production",
    "metadata_incomplete",
    "contract_pending",
    "contract_signed",
    "rights_verified",
    "cleared",
    "blocked",
    "archived",
)


@dataclass(slots=True)
class WorkContributorPayload:
    role: str
    name: str
    share_percent: float | None = None
    role_share_percent: float | None = None
    party_id: int | None = None
    notes: str | None = None


@dataclass(slots=True)
class WorkPayload:
    title: str
    alternate_titles: list[str] = field(default_factory=list)
    version_subtitle: str | None = None
    language: str | None = None
    lyrics_flag: bool = False
    instrumental_flag: bool = False
    genre_notes: str | None = None
    iswc: str | None = None
    registration_number: str | None = None
    work_status: str | None = None
    metadata_complete: bool = False
    contract_signed: bool = False
    rights_verified: bool = False
    notes: str | None = None
    profile_name: str | None = None
    contributors: list[WorkContributorPayload] = field(default_factory=list)
    track_ids: list[int] = field(default_factory=list)


@dataclass(slots=True)
class WorkContributorRecord:
    id: int
    work_id: int
    party_id: int | None
    display_name: str | None
    role: str
    share_percent: float | None
    role_share_percent: float | None
    notes: str | None


@dataclass(slots=True)
class WorkRecord:
    id: int
    title: str
    alternate_titles: list[str]
    version_subtitle: str | None
    language: str | None
    lyrics_flag: bool
    instrumental_flag: bool
    genre_notes: str | None
    iswc: str | None
    registration_number: str | None
    work_status: str | None
    metadata_complete: bool
    contract_signed: bool
    rights_verified: bool
    notes: str | None
    profile_name: str | None
    created_at: str | None
    updated_at: str | None
    track_count: int = 0
    contributor_count: int = 0

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class WorkDetail:
    work: WorkRecord
    contributors: list[WorkContributorRecord]
    track_ids: list[int]


@dataclass(slots=True)
class WorkValidationIssue:
    severity: str
    field_name: str
    message: str

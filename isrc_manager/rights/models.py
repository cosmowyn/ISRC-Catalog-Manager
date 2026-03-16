"""Dataclasses for rights grants and ownership summaries."""

from __future__ import annotations

from dataclasses import asdict, dataclass

RIGHT_TYPE_CHOICES = (
    "master",
    "composition_publishing",
    "neighboring",
    "sync",
    "mechanical",
    "performance",
    "reproduction",
    "digital",
    "promotional",
    "other",
)


@dataclass(slots=True)
class RightPayload:
    title: str | None = None
    right_type: str = "other"
    exclusive_flag: bool = False
    territory: str | None = None
    media_use_type: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    perpetual_flag: bool = False
    granted_by_party_id: int | None = None
    granted_to_party_id: int | None = None
    retained_by_party_id: int | None = None
    source_contract_id: int | None = None
    work_id: int | None = None
    track_id: int | None = None
    release_id: int | None = None
    notes: str | None = None
    profile_name: str | None = None


@dataclass(slots=True)
class RightRecord:
    id: int
    title: str | None
    right_type: str
    exclusive_flag: bool
    territory: str | None
    media_use_type: str | None
    start_date: str | None
    end_date: str | None
    perpetual_flag: bool
    granted_by_party_id: int | None
    granted_by_name: str | None
    granted_to_party_id: int | None
    granted_to_name: str | None
    retained_by_party_id: int | None
    retained_by_name: str | None
    source_contract_id: int | None
    source_contract_title: str | None
    work_id: int | None
    track_id: int | None
    release_id: int | None
    notes: str | None
    profile_name: str | None
    created_at: str | None
    updated_at: str | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class RightsConflict:
    left_right_id: int
    right_right_id: int
    right_type: str
    territory: str
    message: str


@dataclass(slots=True)
class OwnershipSummary:
    entity_type: str
    entity_id: int
    master_control: list[str]
    publishing_control: list[str]
    exclusive_territories: list[str]

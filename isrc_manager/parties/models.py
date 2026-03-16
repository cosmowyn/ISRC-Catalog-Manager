"""Dataclasses for the party and contact registry."""

from __future__ import annotations

from dataclasses import asdict, dataclass


PARTY_TYPE_CHOICES = (
    "artist",
    "label",
    "publisher",
    "subpublisher",
    "producer",
    "remixer",
    "licensee",
    "lawyer",
    "manager",
    "distributor",
    "organization",
    "person",
    "other",
)


@dataclass(slots=True)
class PartyPayload:
    legal_name: str
    display_name: str | None = None
    party_type: str = "organization"
    contact_person: str | None = None
    email: str | None = None
    phone: str | None = None
    website: str | None = None
    address_line1: str | None = None
    address_line2: str | None = None
    city: str | None = None
    region: str | None = None
    postal_code: str | None = None
    country: str | None = None
    tax_id: str | None = None
    vat_number: str | None = None
    pro_affiliation: str | None = None
    ipi_cae: str | None = None
    notes: str | None = None
    profile_name: str | None = None


@dataclass(slots=True)
class PartyRecord:
    id: int
    legal_name: str
    display_name: str | None
    party_type: str
    contact_person: str | None
    email: str | None
    phone: str | None
    website: str | None
    address_line1: str | None
    address_line2: str | None
    city: str | None
    region: str | None
    postal_code: str | None
    country: str | None
    tax_id: str | None
    vat_number: str | None
    pro_affiliation: str | None
    ipi_cae: str | None
    notes: str | None
    profile_name: str | None
    created_at: str | None
    updated_at: str | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class PartyDuplicate:
    match_type: str
    left_party_id: int
    right_party_id: int
    detail: str


@dataclass(slots=True)
class PartyUsageSummary:
    work_count: int = 0
    contract_count: int = 0
    rights_count: int = 0

"""Dataclasses for the party and contact registry."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

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
    artist_name: str | None = None
    company_name: str | None = None
    first_name: str | None = None
    middle_name: str | None = None
    last_name: str | None = None
    party_type: str = "organization"
    contact_person: str | None = None
    email: str | None = None
    alternative_email: str | None = None
    phone: str | None = None
    website: str | None = None
    street_name: str | None = None
    street_number: str | None = None
    address_line1: str | None = None
    address_line2: str | None = None
    city: str | None = None
    region: str | None = None
    postal_code: str | None = None
    country: str | None = None
    bank_account_number: str | None = None
    chamber_of_commerce_number: str | None = None
    tax_id: str | None = None
    vat_number: str | None = None
    pro_affiliation: str | None = None
    pro_number: str | None = None
    ipi_cae: str | None = None
    notes: str | None = None
    profile_name: str | None = None
    artist_aliases: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PartyArtistAliasRecord:
    id: int
    party_id: int
    alias_name: str
    normalized_alias: str
    sort_order: int
    created_at: str | None
    updated_at: str | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class PartyRecord:
    id: int
    legal_name: str
    display_name: str | None
    artist_name: str | None
    company_name: str | None
    first_name: str | None
    middle_name: str | None
    last_name: str | None
    party_type: str
    contact_person: str | None
    email: str | None
    alternative_email: str | None
    phone: str | None
    website: str | None
    street_name: str | None
    street_number: str | None
    address_line1: str | None
    address_line2: str | None
    city: str | None
    region: str | None
    postal_code: str | None
    country: str | None
    bank_account_number: str | None
    chamber_of_commerce_number: str | None
    tax_id: str | None
    vat_number: str | None
    pro_affiliation: str | None
    pro_number: str | None
    ipi_cae: str | None
    notes: str | None
    profile_name: str | None
    created_at: str | None
    updated_at: str | None
    artist_aliases: tuple[str, ...] = ()

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

"""Dataclasses for contract lifecycle management and linked documents."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

CONTRACT_STATUS_CHOICES = (
    "draft",
    "pending_signature",
    "active",
    "expired",
    "terminated",
    "superseded",
)

DOCUMENT_TYPE_CHOICES = (
    "draft",
    "signed_agreement",
    "amendment",
    "appendix",
    "exhibit",
    "correspondence",
    "scan",
    "other",
)

OBLIGATION_TYPE_CHOICES = (
    "delivery",
    "approval",
    "exclusivity",
    "notice",
    "follow_up",
    "reminder",
    "other",
)


@dataclass(slots=True)
class ContractPartyPayload:
    party_id: int | None = None
    name: str | None = None
    role_label: str = "counterparty"
    is_primary: bool = False
    notes: str | None = None


@dataclass(slots=True)
class ContractObligationPayload:
    obligation_id: int | None = None
    obligation_type: str = "other"
    title: str = ""
    due_date: str | None = None
    follow_up_date: str | None = None
    reminder_date: str | None = None
    completed: bool = False
    completed_at: str | None = None
    notes: str | None = None


@dataclass(slots=True)
class ContractDocumentPayload:
    document_id: int | None = None
    title: str = ""
    document_type: str = "other"
    version_label: str | None = None
    created_date: str | None = None
    received_date: str | None = None
    signed_status: str | None = None
    signed_by_all_parties: bool = False
    active_flag: bool = False
    supersedes_document_id: int | None = None
    superseded_by_document_id: int | None = None
    source_path: str | None = None
    stored_path: str | None = None
    filename: str | None = None
    checksum_sha256: str | None = None
    notes: str | None = None


@dataclass(slots=True)
class ContractPayload:
    title: str
    contract_type: str | None = None
    draft_date: str | None = None
    signature_date: str | None = None
    effective_date: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    renewal_date: str | None = None
    notice_deadline: str | None = None
    option_periods: str | None = None
    reversion_date: str | None = None
    termination_date: str | None = None
    status: str = "draft"
    supersedes_contract_id: int | None = None
    superseded_by_contract_id: int | None = None
    summary: str | None = None
    notes: str | None = None
    profile_name: str | None = None
    parties: list[ContractPartyPayload] = field(default_factory=list)
    obligations: list[ContractObligationPayload] = field(default_factory=list)
    documents: list[ContractDocumentPayload] = field(default_factory=list)
    work_ids: list[int] = field(default_factory=list)
    track_ids: list[int] = field(default_factory=list)
    release_ids: list[int] = field(default_factory=list)


@dataclass(slots=True)
class ContractRecord:
    id: int
    title: str
    contract_type: str | None
    draft_date: str | None
    signature_date: str | None
    effective_date: str | None
    start_date: str | None
    end_date: str | None
    renewal_date: str | None
    notice_deadline: str | None
    option_periods: str | None
    reversion_date: str | None
    termination_date: str | None
    status: str
    supersedes_contract_id: int | None
    superseded_by_contract_id: int | None
    summary: str | None
    notes: str | None
    profile_name: str | None
    created_at: str | None
    updated_at: str | None
    obligation_count: int = 0
    document_count: int = 0

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class ContractPartyRecord:
    party_id: int
    party_name: str
    role_label: str
    is_primary: bool
    notes: str | None


@dataclass(slots=True)
class ContractObligationRecord:
    id: int
    contract_id: int
    obligation_type: str
    title: str
    due_date: str | None
    follow_up_date: str | None
    reminder_date: str | None
    completed: bool
    completed_at: str | None
    notes: str | None


@dataclass(slots=True)
class ContractDocumentRecord:
    id: int
    contract_id: int
    title: str
    document_type: str
    version_label: str | None
    created_date: str | None
    received_date: str | None
    signed_status: str | None
    signed_by_all_parties: bool
    active_flag: bool
    supersedes_document_id: int | None
    superseded_by_document_id: int | None
    file_path: str | None
    filename: str | None
    checksum_sha256: str | None
    notes: str | None
    uploaded_at: str | None


@dataclass(slots=True)
class ContractDetail:
    contract: ContractRecord
    parties: list[ContractPartyRecord]
    obligations: list[ContractObligationRecord]
    documents: list[ContractDocumentRecord]
    work_ids: list[int]
    track_ids: list[int]
    release_ids: list[int]


@dataclass(slots=True)
class ContractValidationIssue:
    severity: str
    field_name: str
    message: str


@dataclass(slots=True)
class ContractDeadline:
    contract_id: int
    title: str
    date_field: str
    due_date: str

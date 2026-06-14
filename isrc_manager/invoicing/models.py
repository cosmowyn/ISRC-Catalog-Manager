"""Domain models for invoice and accounting foundations."""

from __future__ import annotations

from dataclasses import asdict, dataclass

DEFAULT_CURRENCY = "EUR"

VAT_TREATMENT_STANDARD = "standard"
VAT_TREATMENT_REDUCED = "reduced"
VAT_TREATMENT_ZERO_RATED = "zero_rated"
VAT_TREATMENT_EXEMPT = "exempt"
VAT_TREATMENT_REVERSE_CHARGE = "reverse_charge"
VAT_TREATMENT_OUT_OF_SCOPE = "out_of_scope"

VAT_TREATMENTS = frozenset(
    {
        VAT_TREATMENT_STANDARD,
        VAT_TREATMENT_REDUCED,
        VAT_TREATMENT_ZERO_RATED,
        VAT_TREATMENT_EXEMPT,
        VAT_TREATMENT_REVERSE_CHARGE,
        VAT_TREATMENT_OUT_OF_SCOPE,
    }
)

ZERO_VAT_TREATMENTS = frozenset(
    {
        VAT_TREATMENT_ZERO_RATED,
        VAT_TREATMENT_EXEMPT,
        VAT_TREATMENT_REVERSE_CHARGE,
        VAT_TREATMENT_OUT_OF_SCOPE,
    }
)

NORMAL_BALANCE_DEBIT = "debit"
NORMAL_BALANCE_CREDIT = "credit"


@dataclass(frozen=True, slots=True)
class Money:
    minor_units: int
    currency: str = DEFAULT_CURRENCY

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class Quantity:
    value: int
    scale: int = 0

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AccountingAccountSeed:
    code: str
    name: str
    account_type: str
    normal_balance: str


@dataclass(frozen=True, slots=True)
class AccountingAccountPayload:
    code: str
    name: str
    account_type: str
    normal_balance: str
    active: bool = True


@dataclass(slots=True)
class AccountingAccountRecord:
    id: int
    code: str
    name: str
    account_type: str
    normal_balance: str
    system_flag: bool
    active: bool
    created_at: str | None
    updated_at: str | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class LedgerEntryDraft:
    account_code: str
    currency: str
    debit_minor: int | None = None
    credit_minor: int | None = None
    party_id: int | None = None
    vat_treatment: str | None = None
    vat_rate_basis_points: int | None = None
    source_type: str | None = None
    source_id: str | int | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class LedgerTransactionRecord:
    id: int
    registry_entry_id: int | None
    transaction_number: str | None
    transaction_type: str
    posted_at: str
    reversal_of_transaction_id: int | None
    command_key: str | None
    idempotency_key: str | None
    created_by: str | None
    memo: str | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AccountingTransactionLinkDraft:
    source_type: str
    source_id: str | int
    relation_type: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class FinancialCommandLogRecord:
    command_key: str
    command_type: str
    source_type: str | None
    source_id: str | None
    result_type: str | None
    result_id: str | None
    ledger_transaction_id: int | None
    status: str
    created_at: str | None
    completed_at: str | None
    error_message: str | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class InvoiceCatalogCategoryPayload:
    name: str
    active: bool = True


@dataclass(slots=True)
class InvoiceCatalogCategoryRecord:
    id: int
    name: str
    active: bool
    created_at: str | None
    updated_at: str | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class InvoiceCatalogItemPayload:
    name: str
    description: str | None = None
    default_quantity: str | Quantity = "1"
    default_unit_price_minor: int = 0
    default_vat_treatment: str = VAT_TREATMENT_STANDARD
    default_vat_rate_basis_points: int = 0
    vat_country_code: str | None = None
    currency: str | None = None
    category: str | None = None
    default_account_code: str | None = None
    active: bool = True


@dataclass(slots=True)
class InvoiceCatalogItemRecord:
    id: int
    name: str
    description: str | None
    default_quantity_value: int
    default_quantity_scale: int
    default_unit_price_minor: int
    default_vat_treatment: str
    default_vat_rate_basis_points: int
    vat_country_code: str | None
    currency: str
    category: str | None
    default_account_code: str | None
    active: bool
    created_at: str | None
    updated_at: str | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class InvoiceLinePayload:
    description: str
    quantity: str | Quantity = "1"
    unit_price_minor: int = 0
    vat_treatment: str = VAT_TREATMENT_STANDARD
    vat_rate_basis_points: int = 0
    vat_country_code: str | None = None
    ledger_account_code: str | None = None
    catalog_item_id: int | None = None
    source_type: str | None = None
    source_id: str | int | None = None


@dataclass(frozen=True, slots=True)
class InvoiceDraftPayload:
    party_id: int
    invoice_type: str = "venue_invoice"
    issue_date: str | None = None
    due_date: str | None = None
    currency: str = DEFAULT_CURRENCY
    seller_vat_id_snapshot: str | None = None
    buyer_vat_id_snapshot: str | None = None
    vat_treatment_summary: str | None = None
    created_by: str | None = None
    lines: tuple[InvoiceLinePayload, ...] = ()


@dataclass(slots=True)
class InvoiceRecord:
    id: int
    draft_display_id: str | None
    invoice_registry_entry_id: int | None
    invoice_number: str | None
    party_id: int
    invoice_type: str
    document_status: str
    issue_date: str | None
    due_date: str | None
    currency: str
    subtotal_minor: int
    vat_total_minor: int
    total_minor: int
    issued_ledger_transaction_id: int | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class InvoiceTemplateRevisionRecord:
    id: int
    template_id: int
    template_name: str
    revision_label: str | None
    source_filename: str
    html_content: str
    source_checksum_sha256: str | None
    symbol_inventory_json: str | None
    validation_status: str
    validation_error: str | None
    created_at: str | None
    updated_at: str | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class InvoiceTemplateRenderResult:
    template_revision_id: int | None
    rendered_html: str
    resolved_values: dict[str, object]
    warnings: tuple[str, ...]
    snapshot_id: int | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class InvoiceOutputArtifactRecord:
    id: int
    snapshot_id: int
    invoice_id: int | None
    ledger_transaction_id: int | None
    contract_template_draft_id: int | None
    contract_template_snapshot_id: int | None
    contract_template_artifact_id: int | None
    artifact_type: str
    status: str
    output_path: str
    output_filename: str
    mime_type: str | None
    storage_mode: str | None
    managed_file_path: str | None
    content_blob: bytes | None
    size_bytes: int
    checksum_sha256: str | None
    created_at: str | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class InvoicePaymentPayload:
    invoice_id: int
    party_id: int
    amount_minor: int
    paid_at: str
    currency: str = DEFAULT_CURRENCY
    payment_method: str | None = None
    payment_reference: str | None = None
    memo: str | None = None
    idempotency_key: str = ""
    created_by: str | None = None
    allow_overpayment: bool = False


@dataclass(slots=True)
class InvoicePaymentRecord:
    id: int
    invoice_id: int
    party_id: int
    amount_minor: int
    currency: str
    paid_at: str
    payment_method: str | None
    payment_reference: str | None
    ledger_transaction_id: int
    memo: str | None
    idempotency_key: str
    created_by: str | None
    created_at: str | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CreditNoteLineAllocationPayload:
    invoice_line_item_id: int
    subtotal_minor: int
    vat_minor: int = 0


@dataclass(slots=True)
class CreditNoteLineAllocationRecord:
    id: int
    credit_note_id: int
    invoice_line_item_id: int
    subtotal_minor: int
    vat_minor: int
    total_minor: int
    currency: str
    created_at: str | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class CreditableInvoiceLineRecord:
    id: int
    description: str
    net_amount_minor: int
    vat_amount_minor: int
    gross_amount_minor: int
    credited_subtotal_minor: int
    credited_vat_minor: int
    remaining_subtotal_minor: int
    remaining_vat_minor: int
    currency: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CreditNotePayload:
    invoice_id: int
    party_id: int
    reason: str
    issue_date: str
    subtotal_minor: int
    vat_total_minor: int = 0
    line_allocations: tuple[CreditNoteLineAllocationPayload, ...] = ()
    currency: str = DEFAULT_CURRENCY
    revenue_account_code: str = "4100"
    idempotency_key: str = ""
    created_by: str | None = None


@dataclass(slots=True)
class CreditNoteRecord:
    id: int
    credit_note_registry_entry_id: int
    credit_note_number: str
    invoice_id: int
    party_id: int
    reason: str
    status: str
    issue_date: str
    currency: str
    subtotal_minor: int
    vat_total_minor: int
    total_minor: int
    ledger_transaction_id: int
    idempotency_key: str
    created_by: str | None
    created_at: str | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class InvoiceSettlementSummary:
    invoice_id: int
    currency: str
    invoice_total_minor: int
    paid_minor: int
    credited_minor: int
    receivable_balance_minor: int
    payment_status: str
    due_status: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class OutstandingInvoiceReportRow:
    invoice_id: int
    invoice_number: str | None
    party_id: int
    currency: str
    total_minor: int
    outstanding_minor: int
    due_date: str | None
    payment_status: str
    due_status: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class PartyBalanceReportRow:
    party_id: int | None
    currency: str
    balance_minor: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class VatSummaryReportRow:
    vat_treatment: str | None
    vat_rate_basis_points: int | None
    currency: str
    vat_output_minor: int
    vat_input_minor: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class RevenueByCatalogServiceRow:
    catalog_item_id: int | None
    catalog_item_name: str | None
    currency: str
    net_amount_minor: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class ArtistPayoutReportRow:
    party_id: int
    currency: str
    payable_posted_minor: int
    payout_paid_minor: int
    payable_balance_minor: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class LedgerAuditReportRow:
    transaction_id: int
    transaction_type: str
    posted_at: str
    transaction_number: str | None
    command_key: str | None
    created_by: str | None
    account_code: str
    party_id: int | None
    debit_minor: int | None
    credit_minor: int | None
    currency: str
    source_type: str | None
    source_id: str | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RoyaltyCalculationLinePayload:
    description: str
    net_payable_minor: int
    source_type: str | None = None
    source_id: str | int | None = None


@dataclass(frozen=True, slots=True)
class RoyaltyCalculationPayload:
    party_id: int
    currency: str = DEFAULT_CURRENCY
    period_start: str | None = None
    period_end: str | None = None
    lines: tuple[RoyaltyCalculationLinePayload, ...] = ()
    created_by: str | None = None


@dataclass(slots=True)
class RoyaltyCalculationRecord:
    id: int
    party_id: int
    status: str
    currency: str
    net_payable_minor: int
    ledger_transaction_id: int | None
    created_at: str | None
    updated_at: str | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class RoyaltyStatementRecord:
    id: int
    statement_registry_entry_id: int
    statement_number: str
    calculation_id: int
    party_id: int
    status: str
    issue_date: str
    currency: str
    total_minor: int
    idempotency_key: str
    created_at: str | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ArtistPayoutPayload:
    party_id: int
    amount_minor: int
    paid_at: str
    currency: str = DEFAULT_CURRENCY
    royalty_calculation_id: int | None = None
    payment_method: str | None = None
    payment_reference: str | None = None
    memo: str | None = None
    idempotency_key: str = ""
    created_by: str | None = None
    allow_overpayment: bool = False


@dataclass(slots=True)
class ArtistPayoutRecord:
    id: int
    party_id: int
    royalty_calculation_id: int | None
    amount_minor: int
    currency: str
    paid_at: str
    payment_method: str | None
    payment_reference: str | None
    ledger_transaction_id: int
    idempotency_key: str
    memo: str | None
    created_by: str | None
    created_at: str | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

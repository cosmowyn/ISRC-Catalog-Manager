import sqlite3

import pytest

from isrc_manager.code_registry import (
    BUILTIN_CATEGORY_CREDIT_NOTE_NUMBER,
    BUILTIN_CATEGORY_INVOICE_NUMBER,
    BUILTIN_CATEGORY_ROYALTY_STATEMENT_NUMBER,
    CodeRegistryService,
)
from isrc_manager.invoicing import (
    ArtistPayoutPayload,
    CreditNoteLineAllocationPayload,
    CreditNotePayload,
    CreditNoteService,
    InvoiceCatalogItemPayload,
    InvoiceDraftPayload,
    InvoiceLinePayload,
    InvoicePaymentPayload,
    InvoicePaymentService,
    InvoiceService,
    LedgerEntryDraft,
    LedgerPostingService,
    Quantity,
    RoyaltyAccountingService,
    RoyaltyCalculationLinePayload,
    RoyaltyCalculationPayload,
    calculate_vat_minor,
    line_net_amount_minor,
    parse_money_minor,
    parse_quantity,
)
from isrc_manager.invoicing.models import (
    AccountingAccountRecord,
    AccountingTransactionLinkDraft,
    ArtistPayoutRecord,
    ArtistPayoutReportRow,
    CreditNoteRecord,
    FinancialCommandLogRecord,
    InvoiceCatalogItemRecord,
    InvoicePaymentRecord,
    InvoiceRecord,
    InvoiceSettlementSummary,
    LedgerAuditReportRow,
    LedgerTransactionRecord,
    Money,
    OutstandingInvoiceReportRow,
    PartyBalanceReportRow,
    RevenueByCatalogServiceRow,
    RoyaltyCalculationRecord,
    RoyaltyStatementRecord,
    VatSummaryReportRow,
)
from isrc_manager.invoicing.money import divide_minor_half_up, normalize_currency
from isrc_manager.parties import PartyPayload, PartyService
from isrc_manager.services import DatabaseSchemaService


def _connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    schema = DatabaseSchemaService(conn)
    schema.init_db()
    schema.migrate_schema()
    CodeRegistryService(conn)
    for system_key, prefix in (
        (BUILTIN_CATEGORY_INVOICE_NUMBER, "INV"),
        (BUILTIN_CATEGORY_CREDIT_NOTE_NUMBER, "CN"),
        (BUILTIN_CATEGORY_ROYALTY_STATEMENT_NUMBER, "ROY"),
    ):
        conn.execute(
            """
            UPDATE CodeRegistryCategories
            SET prefix=?, normalized_prefix=?
            WHERE system_key=?
            """,
            (prefix, prefix, system_key),
        )
    conn.commit()
    return conn


def _party_id(
    conn: sqlite3.Connection, *, party_type: str = "organization", suffix: str = ""
) -> int:
    label = f"{party_type.title()} Party{suffix}"
    return PartyService(conn).create_party(
        PartyPayload(
            legal_name=label,
            display_name=label,
            artist_name=label if party_type == "artist" else None,
            party_type=party_type,
            vat_number=f"VAT-{party_type}{suffix}",
        )
    )


def _issued_invoice(conn: sqlite3.Connection, *, party_id: int):
    service = InvoiceService(conn)
    draft = service.create_draft_invoice(
        InvoiceDraftPayload(
            party_id=party_id,
            lines=(
                InvoiceLinePayload(
                    description="Service",
                    quantity="1",
                    unit_price_minor=10_000,
                    vat_rate_basis_points=2100,
                ),
            ),
        )
    )
    return service.issue_invoice(draft.id, command_key=f"issue-{draft.id}")


def test_model_to_dict_helpers_cover_accounting_records():
    objects = [
        Money(1),
        Quantity(1),
        AccountingAccountRecord(1, "1000", "Cash", "asset", "debit", True, True, None, None),
        LedgerEntryDraft("1000", "EUR", debit_minor=1),
        LedgerTransactionRecord(1, None, None, "adjustment", "now", None, None, None, None, None),
        AccountingTransactionLinkDraft("invoice", 1, "invoice_issue"),
        FinancialCommandLogRecord(
            "k", "type", None, None, None, None, None, "started", None, None, None
        ),
        InvoiceCatalogItemRecord(
            1, "Item", None, 1, 0, 1, "standard", 0, None, "EUR", None, None, True, None, None
        ),
        InvoiceRecord(
            1, "DRAFT-1", None, None, 1, "venue_invoice", "draft", None, None, "EUR", 0, 0, 0, None
        ),
        InvoicePaymentRecord(1, 1, 1, 1, "EUR", "2026-01-01", None, None, 1, None, "k", None, None),
        CreditNoteRecord(
            1, 1, "CN1", 1, 1, "Reason", "issued", "2026-01-01", "EUR", 1, 0, 1, 1, "k", None, None
        ),
        InvoiceSettlementSummary(1, "EUR", 1, 0, 0, 1, "unpaid", "not_due"),
        OutstandingInvoiceReportRow(1, "INV1", 1, "EUR", 1, 1, None, "unpaid", "not_due"),
        PartyBalanceReportRow(1, "EUR", 1),
        VatSummaryReportRow("standard", 2100, "EUR", 1, 0),
        RevenueByCatalogServiceRow(1, "Item", "EUR", 1),
        ArtistPayoutReportRow(1, "EUR", 1, 0, 1),
        LedgerAuditReportRow(
            1, "type", "now", None, None, None, "1000", None, 1, None, "EUR", None, None
        ),
        RoyaltyCalculationRecord(1, 1, "calculated", "EUR", 1, None, None, None),
        RoyaltyStatementRecord(1, 1, "ROY1", 1, 1, "generated", "2026-01-01", "EUR", 1, "k", None),
        ArtistPayoutRecord(1, 1, 1, 1, "EUR", "2026-01-01", None, None, 1, "k", None, None, None),
    ]

    assert all(obj.to_dict() for obj in objects)


def test_money_and_catalog_validation_paths():
    conn = _connection()
    catalog = InvoiceService(conn).catalog_service

    with pytest.raises(ValueError, match="ISO"):
        normalize_currency("EU")
    with pytest.raises(ValueError, match="Money amount"):
        parse_money_minor("abc")
    with pytest.raises(ValueError, match="Quantity"):
        parse_quantity("0")
    with pytest.raises(ValueError, match="Denominator"):
        divide_minor_half_up(1, 0)
    with pytest.raises(ValueError, match="Unit price"):
        line_net_amount_minor(-1, Quantity(1))
    with pytest.raises(ValueError, match="VAT rate"):
        calculate_vat_minor(1, -1)
    with pytest.raises(ValueError, match="Catalog item name"):
        catalog.create_item(InvoiceCatalogItemPayload(name=""))
    with pytest.raises(ValueError, match="unit price"):
        catalog.create_item(InvoiceCatalogItemPayload(name="Bad", default_unit_price_minor=-1))
    with pytest.raises(ValueError, match="VAT rate"):
        catalog.create_item(
            InvoiceCatalogItemPayload(name="Bad VAT", default_vat_rate_basis_points=-1)
        )
    assert catalog.fetch_item(999) is None

    conn.close()


def test_invoice_validation_and_void_rejections():
    conn = _connection()
    party_id = _party_id(conn)
    service = InvoiceService(conn)

    with pytest.raises(ValueError, match="description"):
        service.create_draft_invoice(
            InvoiceDraftPayload(
                party_id=party_id,
                lines=(InvoiceLinePayload(description="", unit_price_minor=1),),
            )
        )
    with pytest.raises(ValueError, match="not found"):
        service.create_draft_invoice(
            InvoiceDraftPayload(
                party_id=party_id,
                lines=(InvoiceLinePayload(description="x", catalog_item_id=999),),
            )
        )
    inactive_item = service.catalog_service.create_item(
        InvoiceCatalogItemPayload(name="Inactive", default_unit_price_minor=1, active=False)
    )
    with pytest.raises(ValueError, match="inactive"):
        service.create_draft_invoice(
            InvoiceDraftPayload(
                party_id=party_id,
                lines=(InvoiceLinePayload(description="x", catalog_item_id=inactive_item),),
            )
        )
    usd_item = service.catalog_service.create_item(
        InvoiceCatalogItemPayload(name="USD", default_unit_price_minor=1, currency="USD")
    )
    with pytest.raises(ValueError, match="currency"):
        service.create_draft_invoice(
            InvoiceDraftPayload(
                party_id=party_id,
                lines=(InvoiceLinePayload(description="x", catalog_item_id=usd_item),),
            )
        )
    zero = service.create_draft_invoice(InvoiceDraftPayload(party_id=party_id))
    with pytest.raises(ValueError, match="command key"):
        service.issue_invoice(zero.id, command_key="")
    with pytest.raises(ValueError, match="greater than zero"):
        service.issue_invoice(zero.id, command_key="issue-zero")
    with pytest.raises(ValueError, match="not found"):
        service.issue_invoice(999, command_key="issue-missing")
    with pytest.raises(ValueError, match="Only issued"):
        service.void_issued_invoice(zero.id, command_key="void-draft")

    issued = _issued_invoice(conn, party_id=party_id)
    InvoicePaymentService(conn).record_invoice_payment(
        InvoicePaymentPayload(
            invoice_id=issued.id,
            party_id=party_id,
            amount_minor=1,
            paid_at="2026-01-01",
            idempotency_key="partial-before-void",
        )
    )
    with pytest.raises(ValueError, match="Only unsettled"):
        service.void_issued_invoice(issued.id, command_key="void-settled")

    conn.close()


def test_payment_and_credit_note_validation_paths():
    conn = _connection()
    party_id = _party_id(conn)
    other_party_id = _party_id(conn)
    invoice = _issued_invoice(conn, party_id=party_id)
    payment_service = InvoicePaymentService(conn)
    credit_service = CreditNoteService(conn)

    payment_cases = [
        (
            InvoicePaymentPayload(invoice.id, party_id, 1, "2026-01-01", idempotency_key=""),
            "idempotency",
        ),
        (
            InvoicePaymentPayload(invoice.id, party_id, 0, "2026-01-01", idempotency_key="p0"),
            "greater than zero",
        ),
        (
            InvoicePaymentPayload(invoice.id, party_id, 1, "", idempotency_key="pdate"),
            "date",
        ),
        (
            InvoicePaymentPayload(
                invoice.id, other_party_id, 1, "2026-01-01", idempotency_key="pparty"
            ),
            "party",
        ),
        (
            InvoicePaymentPayload(
                invoice.id, party_id, 1, "2026-01-01", currency="USD", idempotency_key="pcurrency"
            ),
            "currency",
        ),
        (
            InvoicePaymentPayload(
                invoice.id, party_id, 99_999, "2026-01-01", idempotency_key="pover"
            ),
            "overpay",
        ),
    ]
    for payload, message in payment_cases:
        with pytest.raises(ValueError, match=message):
            payment_service.record_invoice_payment(payload)
    assert payment_service.fetch_payment(999) is None

    draft = InvoiceService(conn).create_draft_invoice(
        InvoiceDraftPayload(
            party_id=party_id,
            lines=(InvoiceLinePayload(description="Draft", unit_price_minor=1),),
        )
    )
    with pytest.raises(ValueError, match="cannot accept payments"):
        payment_service.record_invoice_payment(
            InvoicePaymentPayload(
                draft.id,
                party_id,
                1,
                "2026-01-01",
                idempotency_key="pdraft",
            )
        )

    credit_cases = [
        (
            CreditNotePayload(invoice.id, party_id, "Reason", "2026-01-01", 1, idempotency_key=""),
            "idempotency",
        ),
        (
            CreditNotePayload(invoice.id, party_id, "", "2026-01-01", 1, idempotency_key="creason"),
            "reason",
        ),
        (
            CreditNotePayload(invoice.id, party_id, "Reason", "", 1, idempotency_key="cdate"),
            "date",
        ),
        (
            CreditNotePayload(
                invoice.id, party_id, "Reason", "2026-01-01", -1, idempotency_key="cneg"
            ),
            "non-negative",
        ),
        (
            CreditNotePayload(
                invoice.id, party_id, "Reason", "2026-01-01", 0, idempotency_key="czero"
            ),
            "greater than zero",
        ),
        (
            CreditNotePayload(999, party_id, "Reason", "2026-01-01", 1, idempotency_key="cmissing"),
            "not found",
        ),
        (
            CreditNotePayload(
                invoice.id, other_party_id, "Reason", "2026-01-01", 1, idempotency_key="cparty"
            ),
            "party",
        ),
        (
            CreditNotePayload(
                invoice.id,
                party_id,
                "Reason",
                "2026-01-01",
                1,
                currency="USD",
                idempotency_key="ccurrency",
            ),
            "currency",
        ),
        (
            CreditNotePayload(
                invoice.id, party_id, "Reason", "2026-01-01", 99_999, idempotency_key="cover"
            ),
            "exceed",
        ),
    ]
    for payload, message in credit_cases:
        with pytest.raises(ValueError, match=message):
            credit_service.create_credit_note(payload)
    with pytest.raises(ValueError, match="cannot be credited"):
        credit_service.create_credit_note(
            CreditNotePayload(
                draft.id, party_id, "Reason", "2026-01-01", 1, idempotency_key="cdraft"
            )
        )
    assert credit_service.fetch_credit_note(999) is None

    conn.close()


def test_invoice_command_retries_and_credit_allocation_edge_paths():
    conn = _connection()
    party_id = _party_id(conn)
    service = InvoiceService(conn)
    credit_service = CreditNoteService(conn)

    first_invoice = _issued_invoice(conn, party_id=party_id)
    second_invoice = _issued_invoice(conn, party_id=party_id)
    with pytest.raises(ValueError, match="belongs to another source"):
        service.issue_invoice(second_invoice.id, command_key=f"issue-{first_invoice.id}")

    service.command_log.start(
        command_key="ghost-issue",
        command_type="issue_invoice",
        source_type="invoice",
        source_id=999,
    )
    service.command_log.complete(
        command_key="ghost-issue",
        result_type="invoice",
        result_id=999,
    )
    conn.commit()
    with pytest.raises(RuntimeError, match="missing invoice"):
        service.issue_invoice(999, command_key="ghost-issue")

    service.void_issued_invoice(first_invoice.id, command_key="void-first")
    with pytest.raises(ValueError, match="belongs to another source"):
        service.void_issued_invoice(second_invoice.id, command_key="void-first")

    service.command_log.start(
        command_key="ghost-void",
        command_type="void_invoice",
        source_type="invoice",
        source_id=999,
    )
    service.command_log.complete(
        command_key="ghost-void",
        result_type="invoice",
        result_id=999,
    )
    conn.commit()
    with pytest.raises(RuntimeError, match="missing invoice"):
        service.void_issued_invoice(999, command_key="ghost-void")

    allocation_draft = service.create_draft_invoice(
        InvoiceDraftPayload(
            party_id=party_id,
            lines=(
                InvoiceLinePayload(
                    description="Standard VAT",
                    unit_price_minor=1_000,
                    vat_rate_basis_points=2100,
                ),
                InvoiceLinePayload(
                    description="Reduced VAT",
                    unit_price_minor=1_000,
                    vat_treatment="reduced",
                    vat_rate_basis_points=900,
                ),
            ),
        )
    )
    allocation_invoice = service.issue_invoice(
        allocation_draft.id,
        command_key="issue-allocation-edge-invoice",
    )
    first_line, _second_line = credit_service.creditable_invoice_lines(allocation_invoice.id)

    credit_cases = [
        (
            CreditNotePayload(
                allocation_invoice.id,
                party_id,
                "Subtotal over-credit",
                "2026-01-01",
                allocation_invoice.subtotal_minor + 1,
                0,
                idempotency_key="credit-subtotal-over",
            ),
            "subtotal exceeds",
        ),
        (
            CreditNotePayload(
                allocation_invoice.id,
                party_id,
                "VAT over-credit",
                "2026-01-01",
                0,
                allocation_invoice.vat_total_minor + 1,
                idempotency_key="credit-vat-over",
            ),
            "VAT exceeds",
        ),
        (
            CreditNotePayload(
                allocation_invoice.id,
                party_id,
                "Negative allocation",
                "2026-01-01",
                1,
                0,
                line_allocations=(CreditNoteLineAllocationPayload(first_line.id, -1, 0),),
                idempotency_key="credit-negative-allocation",
            ),
            "non-negative",
        ),
        (
            CreditNotePayload(
                allocation_invoice.id,
                party_id,
                "Zero allocation",
                "2026-01-01",
                1,
                0,
                line_allocations=(CreditNoteLineAllocationPayload(first_line.id, 0, 0),),
                idempotency_key="credit-zero-allocation",
            ),
            "greater than zero",
        ),
        (
            CreditNotePayload(
                allocation_invoice.id,
                party_id,
                "Subtotal mismatch",
                "2026-01-01",
                2,
                0,
                line_allocations=(CreditNoteLineAllocationPayload(first_line.id, 1, 0),),
                idempotency_key="credit-subtotal-mismatch",
            ),
            "subtotal allocation",
        ),
        (
            CreditNotePayload(
                allocation_invoice.id,
                party_id,
                "VAT mismatch",
                "2026-01-01",
                1,
                2,
                line_allocations=(CreditNoteLineAllocationPayload(first_line.id, 1, 1),),
                idempotency_key="credit-vat-mismatch",
            ),
            "VAT allocation",
        ),
        (
            CreditNotePayload(
                allocation_invoice.id,
                party_id,
                "Line subtotal over-credit",
                "2026-01-01",
                first_line.net_amount_minor + 1,
                0,
                line_allocations=(
                    CreditNoteLineAllocationPayload(
                        first_line.id,
                        first_line.net_amount_minor + 1,
                        0,
                    ),
                ),
                idempotency_key="credit-line-subtotal-over",
            ),
            "line subtotal",
        ),
        (
            CreditNotePayload(
                allocation_invoice.id,
                party_id,
                "Line VAT over-credit",
                "2026-01-01",
                0,
                first_line.vat_amount_minor + 1,
                line_allocations=(
                    CreditNoteLineAllocationPayload(
                        first_line.id,
                        0,
                        first_line.vat_amount_minor + 1,
                    ),
                ),
                idempotency_key="credit-line-vat-over",
            ),
            "line VAT",
        ),
    ]
    for payload, message in credit_cases:
        with pytest.raises(ValueError, match=message):
            credit_service.create_credit_note(payload)

    other_invoice = _issued_invoice(conn, party_id=party_id)
    other_line = credit_service.creditable_invoice_lines(other_invoice.id)[0]
    with pytest.raises(ValueError, match="non-invoice line"):
        credit_service.create_credit_note(
            CreditNotePayload(
                allocation_invoice.id,
                party_id,
                "Wrong invoice line",
                "2026-01-01",
                1,
                0,
                line_allocations=(CreditNoteLineAllocationPayload(other_line.id, 1, 0),),
                idempotency_key="credit-wrong-line",
            )
        )

    no_vat_draft = service.create_draft_invoice(
        InvoiceDraftPayload(
            party_id=party_id,
            lines=(InvoiceLinePayload(description="No VAT", unit_price_minor=1_000),),
        )
    )
    no_vat_invoice = service.issue_invoice(no_vat_draft.id, command_key="issue-no-vat-credit")
    no_vat_credit = credit_service.create_credit_note(
        CreditNotePayload(
            no_vat_invoice.id,
            party_id,
            "No VAT credit",
            "2026-01-01",
            1,
            0,
            idempotency_key="credit-no-vat",
        )
    )
    assert no_vat_credit.vat_total_minor == 0

    conn.close()


def test_ledger_validation_paths():
    conn = _connection()
    service = LedgerPostingService(conn)

    with pytest.raises(ValueError, match="command key"):
        service.post_adjustment(command_key="", entries=())
    with pytest.raises(ValueError, match="transaction type"):
        service.post_transaction(command_key="missing-type", transaction_type="", entries=())
    with pytest.raises(ValueError, match="at least one"):
        service.post_adjustment(command_key="empty-adjustment", entries=())
    with pytest.raises(ValueError, match="Unknown accounting account"):
        service.post_adjustment(
            command_key="unknown-account",
            entries=(
                LedgerEntryDraft("9999", "EUR", debit_minor=1),
                LedgerEntryDraft("9000", "EUR", credit_minor=1),
            ),
        )
    with pytest.raises(ValueError, match="exactly one"):
        service.post_adjustment(
            command_key="bad-entry",
            entries=(LedgerEntryDraft("1000", "EUR", debit_minor=1, credit_minor=1),),
        )
    with pytest.raises(ValueError, match="non-negative"):
        service.post_adjustment(
            command_key="negative-debit",
            entries=(LedgerEntryDraft("1000", "EUR", debit_minor=-1),),
        )
    with pytest.raises(ValueError, match="no entries"):
        service.reverse_transaction(999, command_key="reverse-missing")

    conn.close()


def test_financial_edge_guards_cover_overpayment_and_missing_post_links():
    conn = _connection()
    party_id = _party_id(conn)
    invoice = _issued_invoice(conn, party_id=party_id)
    ledger = LedgerPostingService(conn)
    payment_service = InvoicePaymentService(conn)
    credit_service = CreditNoteService(conn)

    assert ledger.fetch_account_by_code("9999") is None
    assert ledger.fetch_transaction(999) is None

    conn.execute("UPDATE AccountingAccounts SET active=0 WHERE code='1000'")
    conn.commit()
    with pytest.raises(ValueError, match="inactive"):
        ledger.post_adjustment(
            command_key="inactive-cash",
            entries=(
                LedgerEntryDraft("1000", "EUR", debit_minor=1),
                LedgerEntryDraft("9000", "EUR", credit_minor=1),
            ),
        )
    conn.execute("UPDATE AccountingAccounts SET active=1 WHERE code='1000'")
    conn.commit()

    with pytest.raises(ValueError, match="Credit amounts"):
        ledger.post_adjustment(
            command_key="negative-credit",
            entries=(LedgerEntryDraft("1000", "EUR", credit_minor=-1),),
        )
    with pytest.raises(ValueError, match="Unsupported VAT treatment"):
        ledger.post_adjustment(
            command_key="bad-vat-treatment",
            entries=(
                LedgerEntryDraft(
                    "2100",
                    "EUR",
                    credit_minor=1,
                    vat_treatment="not-a-treatment",
                ),
                LedgerEntryDraft("1000", "EUR", debit_minor=1),
            ),
        )
    ledger.command_log.start(command_key="started-only", command_type="adjustment")
    conn.commit()
    with pytest.raises(ValueError, match="already started"):
        ledger.post_adjustment(
            command_key="started-only",
            entries=(
                LedgerEntryDraft("1000", "EUR", debit_minor=1),
                LedgerEntryDraft("9000", "EUR", credit_minor=1),
            ),
        )

    overpayment = payment_service.record_invoice_payment(
        InvoicePaymentPayload(
            invoice.id,
            party_id,
            invoice.total_minor + 1,
            "2026-01-01",
            idempotency_key="controlled-overpayment",
            allow_overpayment=True,
        )
    )
    assert overpayment.amount_minor == invoice.total_minor + 1
    assert payment_service.invoice_receivable_balance_minor(invoice.id) == -1

    payment_id = conn.execute(
        """
        INSERT INTO InvoicePayments(
            invoice_id,
            party_id,
            amount_minor,
            currency,
            paid_at,
            idempotency_key
        )
        VALUES (?, ?, 1, 'EUR', '2026-01-02', 'missing-ledger-payment')
        """,
        (invoice.id, party_id),
    ).lastrowid
    with pytest.raises(RuntimeError, match="ledger transaction link"):
        payment_service.fetch_payment(payment_id)

    credit_note_id = conn.execute(
        """
        INSERT INTO CreditNotes(
            invoice_id,
            party_id,
            reason,
            status,
            issue_date,
            currency,
            subtotal_minor,
            vat_total_minor,
            total_minor,
            idempotency_key
        )
        VALUES (?, ?, 'Missing ledger', 'issued', '2026-01-03', 'EUR', 1, 0, 1, 'missing-ledger-credit')
        """,
        (invoice.id, party_id),
    ).lastrowid
    with pytest.raises(RuntimeError, match="ledger transaction link"):
        credit_service.fetch_credit_note(credit_note_id)

    conn.close()


def test_royalty_validation_paths():
    conn = _connection()
    artist_id = _party_id(conn, party_type="artist")
    other_artist_id = _party_id(conn, party_type="artist", suffix=" 2")
    service = RoyaltyAccountingService(conn)

    with pytest.raises(ValueError, match="at least one"):
        service.create_calculation(RoyaltyCalculationPayload(party_id=artist_id))
    with pytest.raises(ValueError, match="description"):
        service.create_calculation(
            RoyaltyCalculationPayload(
                party_id=artist_id,
                lines=(RoyaltyCalculationLinePayload("", 1),),
            )
        )
    with pytest.raises(ValueError, match="non-negative"):
        service.create_calculation(
            RoyaltyCalculationPayload(
                party_id=artist_id,
                lines=(RoyaltyCalculationLinePayload("Bad", -1),),
            )
        )
    with pytest.raises(ValueError, match="greater than zero"):
        service.create_calculation(
            RoyaltyCalculationPayload(
                party_id=artist_id,
                lines=(RoyaltyCalculationLinePayload("Zero", 0),),
            )
        )
    calculation = service.create_calculation(
        RoyaltyCalculationPayload(
            party_id=artist_id,
            lines=(RoyaltyCalculationLinePayload("Royalty", 1_000),),
        )
    )
    with pytest.raises(ValueError, match="idempotency"):
        service.approve_and_post_calculation(calculation.id, command_key="")
    with pytest.raises(ValueError, match="not found"):
        service.approve_and_post_calculation(999, command_key="approve-missing")
    with pytest.raises(ValueError, match="idempotency"):
        service.generate_statement(calculation.id, command_key="", issue_date="2026-01-01")
    with pytest.raises(ValueError, match="issue date"):
        service.generate_statement(calculation.id, command_key="statement-no-date", issue_date="")
    with pytest.raises(ValueError, match="after posting"):
        service.generate_statement(
            calculation.id, command_key="statement-before-post", issue_date="2026-01-01"
        )

    posted = service.approve_and_post_calculation(calculation.id, command_key="approve")
    with pytest.raises(ValueError, match="cannot be posted"):
        service.approve_and_post_calculation(posted.id, command_key="approve-again")
    second_calculation = service.create_calculation(
        RoyaltyCalculationPayload(
            party_id=artist_id,
            lines=(RoyaltyCalculationLinePayload("Other royalty", 500),),
        )
    )
    with pytest.raises(ValueError, match="belongs to another source"):
        service.approve_and_post_calculation(second_calculation.id, command_key="approve")
    service.command_log.start(
        command_key="statement-started",
        command_type="royalty_statement",
        source_type="royalty_calculation",
        source_id=posted.id,
    )
    conn.commit()
    with pytest.raises(ValueError, match="already started"):
        service.generate_statement(
            posted.id,
            command_key="statement-started",
            issue_date="2026-01-01",
        )
    with pytest.raises(ValueError, match="not found"):
        service.generate_statement(999, command_key="statement-missing", issue_date="2026-01-01")
    service.generate_statement(posted.id, command_key="statement", issue_date="2026-01-01")
    with pytest.raises(ValueError, match="already has"):
        service.generate_statement(posted.id, command_key="statement-2", issue_date="2026-01-02")

    unposted_calculation = service.create_calculation(
        RoyaltyCalculationPayload(
            party_id=artist_id,
            lines=(RoyaltyCalculationLinePayload("Draft payout", 100),),
        )
    )
    with pytest.raises(ValueError, match="after royalty posting"):
        service.record_artist_payout(
            ArtistPayoutPayload(
                artist_id,
                1,
                "2026-01-01",
                royalty_calculation_id=unposted_calculation.id,
                idempotency_key="pay-unposted",
            )
        )

    payout_cases = [
        (
            ArtistPayoutPayload(
                artist_id, 1, "2026-01-01", royalty_calculation_id=posted.id, idempotency_key=""
            ),
            "idempotency",
        ),
        (
            ArtistPayoutPayload(
                artist_id,
                0,
                "2026-01-01",
                royalty_calculation_id=posted.id,
                idempotency_key="pay-zero",
            ),
            "greater than zero",
        ),
        (
            ArtistPayoutPayload(
                artist_id, 1, "", royalty_calculation_id=posted.id, idempotency_key="pay-date"
            ),
            "date",
        ),
        (
            ArtistPayoutPayload(artist_id, 1, "2026-01-01", idempotency_key="pay-no-calc"),
            "link",
        ),
        (
            ArtistPayoutPayload(
                artist_id,
                1,
                "2026-01-01",
                royalty_calculation_id=999,
                idempotency_key="pay-missing-calculation",
            ),
            "not found",
        ),
        (
            ArtistPayoutPayload(
                other_artist_id,
                1,
                "2026-01-01",
                royalty_calculation_id=posted.id,
                idempotency_key="pay-party",
            ),
            "party",
        ),
        (
            ArtistPayoutPayload(
                artist_id,
                1,
                "2026-01-01",
                currency="USD",
                royalty_calculation_id=posted.id,
                idempotency_key="pay-currency",
            ),
            "currency",
        ),
        (
            ArtistPayoutPayload(
                artist_id,
                9_999,
                "2026-01-01",
                royalty_calculation_id=posted.id,
                idempotency_key="pay-over",
            ),
            "overpay",
        ),
    ]
    for payload, message in payout_cases:
        with pytest.raises(ValueError, match=message):
            service.record_artist_payout(payload)
    assert service.fetch_statement(999) is None
    assert service.fetch_statement_for_calculation(999) is None
    assert service.fetch_artist_payout_by_idempotency_key("missing") is None

    conn.execute(
        """
        INSERT INTO ArtistPayouts(
            party_id,
            royalty_calculation_id,
            amount_minor,
            currency,
            paid_at,
            idempotency_key
        )
        VALUES (?, ?, 1, 'EUR', '2026-01-01', 'missing-ledger-payout')
        """,
        (artist_id, posted.id),
    )
    with pytest.raises(RuntimeError, match="ledger transaction link"):
        service.fetch_artist_payout_by_idempotency_key("missing-ledger-payout")

    conn.close()

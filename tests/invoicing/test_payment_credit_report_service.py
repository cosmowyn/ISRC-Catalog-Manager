import sqlite3

import pytest

from isrc_manager.code_registry import (
    BUILTIN_CATEGORY_CREDIT_NOTE_NUMBER,
    BUILTIN_CATEGORY_INVOICE_NUMBER,
    CodeRegistryService,
)
from isrc_manager.invoicing import (
    CreditNoteLineAllocationPayload,
    CreditNotePayload,
    CreditNoteService,
    InvoiceAccountingReportService,
    InvoiceCatalogItemPayload,
    InvoiceDraftPayload,
    InvoiceLinePayload,
    InvoicePaymentPayload,
    InvoicePaymentService,
    InvoiceService,
)
from isrc_manager.parties import PartyPayload, PartyService
from isrc_manager.services import DatabaseSchemaService


def _connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    schema = DatabaseSchemaService(conn)
    schema.init_db()
    schema.migrate_schema()
    CodeRegistryService(conn)
    conn.execute(
        """
        UPDATE CodeRegistryCategories
        SET prefix='INV', normalized_prefix='INV'
        WHERE system_key=?
        """,
        (BUILTIN_CATEGORY_INVOICE_NUMBER,),
    )
    conn.execute(
        """
        UPDATE CodeRegistryCategories
        SET prefix='CN', normalized_prefix='CN'
        WHERE system_key=?
        """,
        (BUILTIN_CATEGORY_CREDIT_NOTE_NUMBER,),
    )
    conn.commit()
    return conn


def _party_id(conn: sqlite3.Connection) -> int:
    return PartyService(conn).create_party(
        PartyPayload(
            legal_name="Venue BV",
            display_name="Venue",
            party_type="organization",
            vat_number="NL123",
        )
    )


def _issued_invoice(conn: sqlite3.Connection, *, party_id: int):
    invoice_service = InvoiceService(conn)
    item_id = invoice_service.catalog_service.create_item(
        InvoiceCatalogItemPayload(
            name="Venue service",
            default_unit_price_minor=10_000,
            default_vat_rate_basis_points=2100,
            default_account_code="4100",
        )
    )
    draft = invoice_service.create_draft_invoice(
        InvoiceDraftPayload(
            party_id=party_id,
            due_date="2026-01-31",
            lines=(
                InvoiceLinePayload(
                    catalog_item_id=item_id,
                    description="",
                    quantity="1",
                ),
            ),
        )
    )
    return invoice_service.issue_invoice(draft.id, command_key=f"issue-{draft.id}")


def test_invoice_payments_are_idempotent_partial_and_ledger_backed():
    conn = _connection()
    party_id = _party_id(conn)
    invoice = _issued_invoice(conn, party_id=party_id)
    payment_service = InvoicePaymentService(conn)
    reports = InvoiceAccountingReportService(conn)

    first_payment = payment_service.record_invoice_payment(
        InvoicePaymentPayload(
            invoice_id=invoice.id,
            party_id=party_id,
            amount_minor=5_000,
            paid_at="2026-01-15",
            payment_method="bank",
            payment_reference="BANK-1",
            idempotency_key="payment-1",
        )
    )
    replayed = payment_service.record_invoice_payment(
        InvoicePaymentPayload(
            invoice_id=invoice.id,
            party_id=party_id,
            amount_minor=5_000,
            paid_at="2026-01-15",
            idempotency_key="payment-1",
        )
    )
    settlement = reports.invoice_settlement(invoice.id, as_of_date="2026-02-01")

    assert replayed.id == first_payment.id
    assert settlement.invoice_total_minor == 12_100
    assert settlement.paid_minor == 5_000
    assert settlement.receivable_balance_minor == 7_100
    assert settlement.payment_status == "partially_paid"
    assert settlement.due_status == "overdue"
    assert len(reports.outstanding_invoices(as_of_date="2026-02-01")) == 1

    payment_service.record_invoice_payment(
        InvoicePaymentPayload(
            invoice_id=invoice.id,
            party_id=party_id,
            amount_minor=7_100,
            paid_at="2026-01-20",
            idempotency_key="payment-2",
        )
    )
    paid_settlement = reports.invoice_settlement(invoice.id, as_of_date="2026-02-01")

    assert paid_settlement.receivable_balance_minor == 0
    assert paid_settlement.payment_status == "paid"
    assert paid_settlement.due_status == "not_due"
    assert reports.outstanding_invoices(as_of_date="2026-02-01") == []
    assert conn.execute("SELECT COUNT(*) FROM InvoicePayments").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM AccountingTransactions").fetchone()[0] == 3

    with pytest.raises(ValueError, match="no outstanding receivable"):
        payment_service.record_invoice_payment(
            InvoicePaymentPayload(
                invoice_id=invoice.id,
                party_id=party_id,
                amount_minor=1,
                paid_at="2026-01-21",
                idempotency_key="payment-overpay",
            )
        )

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "UPDATE InvoicePayments SET amount_minor=1 WHERE id=?",
            (first_payment.id,),
        )

    conn.close()


def test_credit_notes_reverse_receivable_revenue_and_vat_without_mutating_invoice():
    conn = _connection()
    party_id = _party_id(conn)
    invoice = _issued_invoice(conn, party_id=party_id)
    credit_service = CreditNoteService(conn)
    reports = InvoiceAccountingReportService(conn)

    credit_note = credit_service.create_credit_note(
        CreditNotePayload(
            invoice_id=invoice.id,
            party_id=party_id,
            reason="Cancelled booking",
            issue_date="2026-01-16",
            subtotal_minor=10_000,
            vat_total_minor=2_100,
            idempotency_key="credit-full",
        )
    )
    replayed = credit_service.create_credit_note(
        CreditNotePayload(
            invoice_id=invoice.id,
            party_id=party_id,
            reason="Cancelled booking",
            issue_date="2026-01-16",
            subtotal_minor=10_000,
            vat_total_minor=2_100,
            idempotency_key="credit-full",
        )
    )
    settlement = reports.invoice_settlement(invoice.id)
    vat_rows = reports.vat_summary_report()
    credit_entries = conn.execute(
        """
        SELECT a.code, e.debit_minor, e.credit_minor, e.party_id
        FROM AccountingEntries e
        INNER JOIN AccountingAccounts a ON a.id=e.account_id
        WHERE e.transaction_id=?
        ORDER BY e.id
        """,
        (credit_note.ledger_transaction_id,),
    ).fetchall()
    reloaded_invoice = InvoiceService(conn).fetch_invoice(invoice.id)

    assert credit_note.credit_note_number.startswith("CN")
    assert replayed.id == credit_note.id
    assert settlement.credited_minor == 12_100
    assert settlement.receivable_balance_minor == 0
    assert settlement.payment_status == "credited"
    assert reloaded_invoice is not None
    assert reloaded_invoice.document_status == "credited"
    assert credit_entries == [
        ("4100", 10_000, None, None),
        ("2100", 2_100, None, None),
        ("1100", None, 12_100, party_id),
    ]
    assert [(row.vat_output_minor, row.vat_input_minor) for row in vat_rows] == [(0, 0)]

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "UPDATE CreditNotes SET total_minor=1 WHERE id=?",
            (credit_note.id,),
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "UPDATE InvoiceLineItems SET net_amount_minor=1 WHERE invoice_id=?",
            (invoice.id,),
        )

    conn.close()


def test_credit_note_line_allocations_are_persisted_and_cannot_exceed_line_remaining():
    conn = _connection()
    party_id = _party_id(conn)
    invoice = _issued_invoice(conn, party_id=party_id)
    line_id = conn.execute(
        "SELECT id FROM InvoiceLineItems WHERE invoice_id=?",
        (invoice.id,),
    ).fetchone()[0]
    credit_service = CreditNoteService(conn)

    credit_note = credit_service.create_credit_note(
        CreditNotePayload(
            invoice_id=invoice.id,
            party_id=party_id,
            reason="Partial line credit",
            issue_date="2026-01-16",
            subtotal_minor=5_000,
            vat_total_minor=1_050,
            line_allocations=(
                CreditNoteLineAllocationPayload(
                    invoice_line_item_id=line_id,
                    subtotal_minor=5_000,
                    vat_minor=1_050,
                ),
            ),
            idempotency_key="credit-line-partial",
        )
    )
    lines = credit_service.creditable_invoice_lines(invoice.id)
    allocation = conn.execute("""
        SELECT credit_note_id, invoice_line_item_id, subtotal_minor, vat_minor, total_minor
        FROM CreditNoteLineAllocations
        """).fetchone()

    assert allocation == (credit_note.id, line_id, 5_000, 1_050, 6_050)
    assert [(line.remaining_subtotal_minor, line.remaining_vat_minor) for line in lines] == [
        (5_000, 1_050)
    ]

    with pytest.raises(ValueError, match="remaining invoice subtotal"):
        credit_service.create_credit_note(
            CreditNotePayload(
                invoice_id=invoice.id,
                party_id=party_id,
                reason="Too much line credit",
                issue_date="2026-01-17",
                subtotal_minor=6_000,
                vat_total_minor=0,
                line_allocations=(
                    CreditNoteLineAllocationPayload(
                        invoice_line_item_id=line_id,
                        subtotal_minor=6_000,
                    ),
                ),
                idempotency_key="credit-line-too-much",
            )
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "UPDATE CreditNoteLineAllocations SET subtotal_minor=1 WHERE credit_note_id=?",
            (credit_note.id,),
        )
    manual_note_id = conn.execute(
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
        VALUES (?, ?, 'Manual bypass attempt', 'issued', '2026-01-18', 'EUR', 6000, 0, 6000, 'manual-overcredit')
        """,
        (invoice.id, party_id),
    ).lastrowid
    with pytest.raises(sqlite3.IntegrityError, match="exceeds remaining line subtotal"):
        conn.execute(
            """
            INSERT INTO CreditNoteLineAllocations(
                credit_note_id,
                invoice_line_item_id,
                subtotal_minor,
                vat_minor,
                total_minor,
                currency
            )
            VALUES (?, ?, 6000, 0, 6000, 'EUR')
            """,
            (manual_note_id, line_id),
        )

    other_invoice = _issued_invoice(conn, party_id=party_id)
    other_line_id = conn.execute(
        "SELECT id FROM InvoiceLineItems WHERE invoice_id=?",
        (other_invoice.id,),
    ).fetchone()[0]
    wrong_line_note_id = conn.execute(
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
        VALUES (?, ?, 'Wrong line bypass attempt', 'issued', '2026-01-19', 'EUR', 100, 0, 100, 'manual-wrong-line')
        """,
        (invoice.id, party_id),
    ).lastrowid
    with pytest.raises(sqlite3.IntegrityError, match="must match invoice and currency"):
        conn.execute(
            """
            INSERT INTO CreditNoteLineAllocations(
                credit_note_id,
                invoice_line_item_id,
                subtotal_minor,
                vat_minor,
                total_minor,
                currency
            )
            VALUES (?, ?, 100, 0, 100, 'EUR')
            """,
            (wrong_line_note_id, other_line_id),
        )

    conn.close()


def test_reports_reconcile_catalog_revenue_party_balances_vat_and_audit_rows():
    conn = _connection()
    party_id = _party_id(conn)
    invoice = _issued_invoice(conn, party_id=party_id)
    reports = InvoiceAccountingReportService(conn)

    party_rows = reports.party_balance_report()
    vat_rows = reports.vat_summary_report()
    revenue_rows = reports.revenue_by_catalog_service()
    audit_rows = reports.ledger_audit_report()

    assert [(row.party_id, row.balance_minor) for row in party_rows] == [(party_id, 12_100)]
    assert [
        (row.vat_treatment, row.vat_rate_basis_points, row.vat_output_minor) for row in vat_rows
    ] == [("standard", 2100, 2_100)]
    assert [(row.catalog_item_name, row.net_amount_minor) for row in revenue_rows] == [
        ("Venue service", 10_000)
    ]
    assert {row.transaction_type for row in audit_rows} == {"invoice_issue"}
    assert sum(row.debit_minor or 0 for row in audit_rows) == invoice.total_minor
    assert sum(row.credit_minor or 0 for row in audit_rows) == invoice.total_minor

    conn.close()

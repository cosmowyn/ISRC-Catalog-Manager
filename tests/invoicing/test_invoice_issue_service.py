import sqlite3

import pytest

from isrc_manager.code_registry import BUILTIN_CATEGORY_INVOICE_NUMBER, CodeRegistryService
from isrc_manager.invoicing import (
    InvoiceCatalogItemPayload,
    InvoiceDraftPayload,
    InvoiceLinePayload,
    InvoiceService,
    LedgerPostingService,
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


def test_create_draft_invoice_snapshots_catalog_line_and_vat_breakdown():
    conn = _connection()
    party_id = _party_id(conn)
    service = InvoiceService(conn)
    item_id = service.catalog_service.create_item(
        InvoiceCatalogItemPayload(
            name="Venue licensing package",
            description="Venue service",
            default_unit_price_minor=10_000,
            default_vat_treatment="standard",
            default_vat_rate_basis_points=2100,
            default_account_code="4100",
        )
    )

    invoice = service.create_draft_invoice(
        InvoiceDraftPayload(
            party_id=party_id,
            lines=(
                InvoiceLinePayload(
                    catalog_item_id=item_id,
                    description="",
                    quantity="1.5",
                ),
            ),
        )
    )
    conn.execute(
        """
        UPDATE InvoiceCatalogItems
        SET default_unit_price_minor=999999,
            default_vat_rate_basis_points=0,
            default_account_code='4000'
        WHERE id=?
        """,
        (item_id,),
    )
    conn.commit()
    line = conn.execute(
        """
        SELECT
            catalog_item_name_snapshot,
            quantity_value,
            quantity_scale,
            net_amount_minor,
            vat_amount_minor,
            gross_amount_minor,
            ledger_account_code
        FROM InvoiceLineItems
        WHERE invoice_id=?
        """,
        (invoice.id,),
    ).fetchone()
    vat = conn.execute(
        """
        SELECT taxable_amount_minor, vat_amount_minor, gross_amount_minor
        FROM InvoiceVatBreakdown
        WHERE invoice_id=?
        """,
        (invoice.id,),
    ).fetchone()

    assert invoice.document_status == "draft"
    assert invoice.invoice_number is None
    assert invoice.subtotal_minor == 15_000
    assert invoice.vat_total_minor == 3_150
    assert invoice.total_minor == 18_150
    assert line == ("Venue licensing package", 15, 1, 15_000, 3_150, 18_150, "4100")
    assert vat == (15_000, 3_150, 18_150)

    conn.close()


def test_issue_invoice_generates_number_posts_ledger_and_is_idempotent():
    conn = _connection()
    party_id = _party_id(conn)
    service = InvoiceService(conn)
    invoice = service.create_draft_invoice(
        InvoiceDraftPayload(
            party_id=party_id,
            lines=(
                InvoiceLinePayload(
                    description="Venue service",
                    quantity="1",
                    unit_price_minor=10_000,
                    vat_rate_basis_points=2100,
                    ledger_account_code="4100",
                ),
            ),
        )
    )

    issued = service.issue_invoice(invoice.id, command_key="issue-venue-invoice")
    replayed = service.issue_invoice(invoice.id, command_key="issue-venue-invoice")

    transaction_count = conn.execute("SELECT COUNT(*) FROM AccountingTransactions").fetchone()[0]
    entry_rows = conn.execute("""
        SELECT a.code, e.debit_minor, e.credit_minor, e.party_id
        FROM AccountingEntries e
        INNER JOIN AccountingAccounts a ON a.id=e.account_id
        ORDER BY e.id
        """).fetchall()

    assert issued.invoice_number is not None
    assert issued.invoice_number.startswith("INV")
    assert issued.document_status == "issued"
    assert issued.issued_ledger_transaction_id is not None
    assert replayed.invoice_number == issued.invoice_number
    assert replayed.issued_ledger_transaction_id == issued.issued_ledger_transaction_id
    assert transaction_count == 1
    assert entry_rows == [
        ("1100", 12_100, None, party_id),
        ("4100", None, 10_000, None),
        ("2100", None, 2_100, None),
    ]
    assert LedgerPostingService(conn).party_balance_minor(party_id) == 12_100

    conn.close()


def test_issuing_already_issued_invoice_with_new_command_is_rejected():
    conn = _connection()
    party_id = _party_id(conn)
    service = InvoiceService(conn)
    invoice = service.create_draft_invoice(
        InvoiceDraftPayload(
            party_id=party_id,
            lines=(
                InvoiceLinePayload(
                    description="Venue service",
                    quantity="1",
                    unit_price_minor=10_000,
                ),
            ),
        )
    )
    service.issue_invoice(invoice.id, command_key="issue-once")

    with pytest.raises(ValueError, match="Only draft invoices can be issued"):
        service.issue_invoice(invoice.id, command_key="issue-twice")

    assert conn.execute("SELECT COUNT(*) FROM CodeRegistryEntries").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM AccountingTransactions").fetchone()[0] == 1

    conn.close()


def test_void_issued_invoice_posts_reversal_and_is_idempotent():
    conn = _connection()
    party_id = _party_id(conn)
    service = InvoiceService(conn)
    invoice = service.create_draft_invoice(
        InvoiceDraftPayload(
            party_id=party_id,
            lines=(
                InvoiceLinePayload(
                    description="Venue service",
                    quantity="1",
                    unit_price_minor=10_000,
                    vat_rate_basis_points=2100,
                ),
            ),
        )
    )
    issued = service.issue_invoice(invoice.id, command_key="issue-before-void")

    voided = service.void_issued_invoice(issued.id, command_key="void-invoice")
    replayed = service.void_issued_invoice(issued.id, command_key="void-invoice")
    rows = conn.execute(
        """
        SELECT a.code, e.debit_minor, e.credit_minor, e.party_id
        FROM AccountingEntries e
        INNER JOIN AccountingAccounts a ON a.id=e.account_id
        WHERE e.transaction_id != ?
        ORDER BY e.id
        """,
        (issued.issued_ledger_transaction_id,),
    ).fetchall()

    assert voided.document_status == "voided"
    assert replayed.document_status == "voided"
    assert conn.execute("SELECT COUNT(*) FROM AccountingTransactions").fetchone()[0] == 2
    assert rows == [
        ("1100", None, 12_100, party_id),
        ("4100", 10_000, None, None),
        ("2100", 2_100, None, None),
    ]
    assert LedgerPostingService(conn).party_balance_minor(party_id) == 0

    conn.close()

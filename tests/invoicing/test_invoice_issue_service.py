import sqlite3
from pathlib import Path

import pytest

from isrc_manager.code_registry import (
    BUILTIN_CATEGORY_CREDIT_NOTE_NUMBER,
    BUILTIN_CATEGORY_INVOICE_NUMBER,
    CodeRegistryService,
)
from isrc_manager.file_storage import STORAGE_MODE_DATABASE, STORAGE_MODE_MANAGED_FILE
from isrc_manager.invoicing import (
    CreditNotePayload,
    CreditNoteService,
    InvoiceCatalogItemPayload,
    InvoiceDraftPayload,
    InvoiceLinePayload,
    InvoicePaymentPayload,
    InvoicePaymentService,
    InvoiceService,
    LedgerPostingService,
)
from isrc_manager.invoicing.template_service import InvoiceTemplateService
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


def test_catalog_items_update_filter_and_validation_edges(monkeypatch):
    conn = _connection()
    service = InvoiceService(conn)
    catalog = service.catalog_service
    active_id = catalog.create_item(
        InvoiceCatalogItemPayload(
            name="Mixing",
            default_unit_price_minor=5_000,
            default_vat_rate_basis_points=2100,
            category="Studio",
            default_account_code="4200",
        )
    )
    catalog.create_item(
        InvoiceCatalogItemPayload(
            name="Inactive",
            default_unit_price_minor=1_000,
            active=False,
        )
    )
    inferred_id = catalog.create_item(
        InvoiceCatalogItemPayload(
            name="US travel",
            default_unit_price_minor=2_000,
            vat_country_code="US",
            active=False,
        )
    )

    updated = catalog.update_item(
        active_id,
        InvoiceCatalogItemPayload(
            name=" Mastering ",
            description="Final master",
            default_quantity="2.5",
            default_unit_price_minor=7_500,
            default_vat_rate_basis_points=900,
            vat_country_code="NL",
            currency="USD",
            category="Delivery",
            default_account_code="4300",
            active=True,
        ),
    )
    active_items = catalog.list_items(active_only=True)

    assert updated.name == "Mastering"
    assert updated.description == "Final master"
    assert updated.default_quantity_value == 25
    assert updated.default_quantity_scale == 1
    assert updated.default_unit_price_minor == 7_500
    assert updated.default_vat_rate_basis_points == 900
    assert updated.vat_country_code == "NL"
    assert updated.currency == "USD"
    assert catalog.fetch_item(inferred_id).currency == "USD"
    assert updated.category == "Delivery"
    assert updated.default_account_code == "4300"
    assert [item.id for item in active_items] == [active_id]
    assert catalog.fetch_item(9999) is None

    with pytest.raises(ValueError, match="name is required"):
        catalog.update_item(active_id, InvoiceCatalogItemPayload(name=" "))
    with pytest.raises(ValueError, match="unit price"):
        catalog.update_item(
            active_id,
            InvoiceCatalogItemPayload(name="Bad price", default_unit_price_minor=-1),
        )
    with pytest.raises(ValueError, match="VAT rate"):
        catalog.update_item(
            active_id,
            InvoiceCatalogItemPayload(name="Bad VAT", default_vat_rate_basis_points=-1),
        )
    with pytest.raises(ValueError, match="was not found"):
        catalog.update_item(9999, InvoiceCatalogItemPayload(name="Missing"))

    monkeypatch.setattr(catalog, "fetch_item", lambda _item_id: None)
    with pytest.raises(RuntimeError, match="could not be reloaded"):
        catalog.update_item(active_id, InvoiceCatalogItemPayload(name="Reload failure"))

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


def test_finalize_invoice_stores_database_and_managed_artifacts(tmp_path: Path):
    conn = _connection()
    party_id = _party_id(conn)
    invoice_service = InvoiceService(conn, data_root=tmp_path)
    template_service = InvoiceTemplateService(conn, data_root=tmp_path)
    first = invoice_service.create_draft_invoice(
        InvoiceDraftPayload(
            party_id=party_id,
            lines=(
                InvoiceLinePayload(
                    description="Database final invoice",
                    quantity="1",
                    unit_price_minor=10_000,
                    vat_rate_basis_points=2100,
                    ledger_account_code="4100",
                ),
            ),
        )
    )
    second = invoice_service.create_draft_invoice(
        InvoiceDraftPayload(
            party_id=party_id,
            lines=(
                InvoiceLinePayload(
                    description="Managed final invoice",
                    quantity="1",
                    unit_price_minor=5_000,
                    vat_rate_basis_points=0,
                    ledger_account_code="4100",
                ),
            ),
        )
    )

    database_artifact = template_service.finalize_invoice(
        first.id,
        command_key="finalize-database",
        storage_mode=STORAGE_MODE_DATABASE,
    )
    managed_artifact = template_service.finalize_invoice(
        second.id,
        command_key="finalize-managed",
        storage_mode=STORAGE_MODE_MANAGED_FILE,
    )

    db_path = template_service.materialize_output_artifact(database_artifact.id)
    managed_path = template_service.materialize_output_artifact(managed_artifact.id)
    artifact_rows = conn.execute("""
        SELECT artifact_type, status, storage_mode, managed_file_path, content_blob IS NOT NULL
        FROM InvoiceOutputArtifacts
        ORDER BY id
        """).fetchall()

    assert database_artifact.ledger_transaction_id is not None
    assert database_artifact.storage_mode == STORAGE_MODE_DATABASE
    assert database_artifact.content_blob is not None
    assert managed_artifact.ledger_transaction_id is not None
    assert managed_artifact.storage_mode == STORAGE_MODE_MANAGED_FILE
    assert managed_artifact.content_blob is None
    assert managed_artifact.managed_file_path
    assert managed_path.exists()
    assert managed_path == tmp_path / managed_artifact.managed_file_path
    assert db_path.exists()
    assert "Database final invoice" in db_path.read_text(encoding="utf-8")
    assert "Managed final invoice" in managed_path.read_text(encoding="utf-8")
    assert artifact_rows == [
        ("final_html", "final", STORAGE_MODE_DATABASE, None, 1),
        ("final_html", "final", STORAGE_MODE_MANAGED_FILE, managed_artifact.managed_file_path, 0),
    ]

    conn.close()


def test_purge_invoice_for_cleanup_removes_linked_accounting_cluster(tmp_path: Path):
    conn = _connection()
    party_id = _party_id(conn)
    invoice_service = InvoiceService(conn, data_root=tmp_path)
    template_service = InvoiceTemplateService(conn, data_root=tmp_path)
    invoice = invoice_service.create_draft_invoice(
        InvoiceDraftPayload(
            party_id=party_id,
            lines=(
                InvoiceLinePayload(
                    description="Cleanup invoice",
                    quantity="1",
                    unit_price_minor=10_000,
                    vat_rate_basis_points=0,
                    ledger_account_code="4100",
                ),
            ),
        )
    )
    artifact = template_service.finalize_invoice(
        invoice.id,
        command_key="cleanup-issue",
        storage_mode=STORAGE_MODE_MANAGED_FILE,
    )
    managed_path = template_service.materialize_output_artifact(artifact.id)
    InvoicePaymentService(conn).record_invoice_payment(
        InvoicePaymentPayload(
            invoice_id=invoice.id,
            party_id=party_id,
            amount_minor=2_500,
            paid_at="2026-02-01",
            idempotency_key="cleanup-payment",
        )
    )
    CreditNoteService(conn).create_credit_note(
        CreditNotePayload(
            invoice_id=invoice.id,
            party_id=party_id,
            reason="Cleanup credit",
            issue_date="2026-02-02",
            subtotal_minor=7_500,
            vat_total_minor=0,
            idempotency_key="cleanup-credit",
        )
    )

    summary = invoice_service.purge_invoice_for_cleanup(invoice.id)

    assert summary == {
        "invoices": 1,
        "payments": 1,
        "credit_notes": 1,
        "artifacts": 1,
        "ledger_transactions": 3,
        "command_log_entries": 3,
        "managed_files": 1,
    }
    assert not managed_path.exists()
    for table in (
        "Invoices",
        "InvoiceLineItems",
        "InvoiceVatBreakdown",
        "InvoicePayments",
        "CreditNotes",
        "CreditNoteLineAllocations",
        "InvoiceTemplateResolvedSnapshots",
        "InvoiceOutputArtifacts",
        "AccountingTransactions",
        "AccountingEntries",
        "AccountingTransactionLinks",
        "FinancialCommandLog",
    ):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    assert LedgerPostingService(conn).party_balance_minor(party_id) == 0

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


def test_invoice_issue_and_void_validation_edges():
    conn = _connection()
    party_id = _party_id(conn)
    service = InvoiceService(conn)

    with pytest.raises(ValueError, match="command key"):
        service.issue_invoice(1, command_key=" ")
    with pytest.raises(ValueError, match="was not found"):
        service.issue_invoice(999, command_key="issue-missing")
    with pytest.raises(ValueError, match="Void invoice command key"):
        service.void_issued_invoice(1, command_key="")
    with pytest.raises(ValueError, match="was not found"):
        service.void_issued_invoice(999, command_key="void-missing")
    with pytest.raises(ValueError, match="has no entries"):
        service._reversal_entries_for_transaction(999)

    draft = service.create_draft_invoice(
        InvoiceDraftPayload(
            party_id=party_id,
            lines=(
                InvoiceLinePayload(
                    description="Zero total",
                    quantity="1",
                    unit_price_minor=0,
                ),
            ),
        )
    )
    with pytest.raises(ValueError, match="greater than zero"):
        service.issue_invoice(draft.id, command_key="issue-zero-total")
    with pytest.raises(ValueError, match="Only issued or sent invoices"):
        service.void_issued_invoice(draft.id, command_key="void-draft")

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

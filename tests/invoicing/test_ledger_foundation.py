import sqlite3

import pytest

from isrc_manager.code_registry import (
    BUILTIN_CATEGORY_CREDIT_NOTE_NUMBER,
    BUILTIN_CATEGORY_INVOICE_NUMBER,
    BUILTIN_CATEGORY_LEDGER_TRANSACTION_NUMBER,
    BUILTIN_CATEGORY_ROYALTY_STATEMENT_NUMBER,
    CodeRegistryService,
)
from isrc_manager.constants import SCHEMA_TARGET
from isrc_manager.invoicing import LedgerEntryDraft, LedgerPostingService
from isrc_manager.parties import PartyPayload, PartyService
from isrc_manager.services import DatabaseSchemaService


def _foundation_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    schema = DatabaseSchemaService(conn)
    schema.init_db()
    schema.migrate_schema()
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


def test_schema_adds_accounting_tables_accounts_and_registry_categories():
    conn = _foundation_connection()

    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    accounts = {
        row[0]: row[1]
        for row in conn.execute("SELECT code, name FROM AccountingAccounts").fetchall()
    }
    triggers = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'").fetchall()
    }
    registry = CodeRegistryService(conn)

    assert DatabaseSchemaService(conn).get_db_version() == SCHEMA_TARGET
    assert "AccountingTransactions" in tables
    assert "AccountingEntries" in tables
    assert "FinancialCommandLog" in tables
    assert "InvoicePayments" in tables
    assert "CreditNotes" in tables
    assert "RoyaltyCalculations" in tables
    assert "RoyaltyStatements" in tables
    assert "ArtistPayouts" in tables
    assert accounts["1000"] == "Cash Clearing"
    assert accounts["1100"] == "Accounts Receivable"
    assert accounts["2100"] == "VAT Output / VAT Payable"
    assert "trg_accounting_transactions_no_update" in triggers
    assert "trg_accounting_entries_no_delete" in triggers
    assert "trg_invoices_issued_number_no_update" in triggers
    assert "trg_credit_notes_no_delete" in triggers
    assert "trg_invoice_payments_no_update_after_post" in triggers
    assert "trg_artist_payouts_no_delete" in triggers
    assert "trg_royalty_statements_no_update" in triggers
    assert registry.fetch_category_by_system_key(BUILTIN_CATEGORY_INVOICE_NUMBER) is not None
    assert registry.fetch_category_by_system_key(BUILTIN_CATEGORY_CREDIT_NOTE_NUMBER) is not None
    assert (
        registry.fetch_category_by_system_key(BUILTIN_CATEGORY_LEDGER_TRANSACTION_NUMBER)
        is not None
    )
    assert (
        registry.fetch_category_by_system_key(BUILTIN_CATEGORY_ROYALTY_STATEMENT_NUMBER) is not None
    )

    conn.close()


def test_post_transaction_balances_entries_and_is_idempotent():
    conn = _foundation_connection()
    party_id = _party_id(conn)
    service = LedgerPostingService(conn)

    transaction = service.post_transaction(
        command_key="issue-invoice-1",
        transaction_type="invoice_issue",
        source_type="invoice",
        source_id=1,
        entries=(
            LedgerEntryDraft("1100", "EUR", debit_minor=12_100, party_id=party_id),
            LedgerEntryDraft("4100", "EUR", credit_minor=10_000),
            LedgerEntryDraft(
                "2100",
                "EUR",
                credit_minor=2_100,
                vat_treatment="standard",
                vat_rate_basis_points=2100,
            ),
        ),
    )
    replayed = service.post_transaction(
        command_key="issue-invoice-1",
        transaction_type="invoice_issue",
        source_type="invoice",
        source_id=1,
        entries=(
            LedgerEntryDraft("1100", "EUR", debit_minor=12_100, party_id=party_id),
            LedgerEntryDraft("4100", "EUR", credit_minor=10_000),
            LedgerEntryDraft("2100", "EUR", credit_minor=2_100),
        ),
    )
    replayed_without_revalidating_payload = service.post_transaction(
        command_key="issue-invoice-1",
        transaction_type="invoice_issue",
        source_type="invoice",
        source_id=1,
        entries=(LedgerEntryDraft("1100", "EUR", debit_minor=1),),
    )

    entry_count = conn.execute("SELECT COUNT(*) FROM AccountingEntries").fetchone()[0]
    assert replayed.id == transaction.id
    assert replayed_without_revalidating_payload.id == transaction.id
    assert entry_count == 3
    assert service.party_balance_minor(party_id) == 12_100

    conn.close()


def test_unbalanced_transactions_and_posted_mutations_are_rejected():
    conn = _foundation_connection()
    service = LedgerPostingService(conn)

    with pytest.raises(ValueError):
        service.post_transaction(
            command_key="unbalanced",
            transaction_type="invoice_issue",
            entries=(
                LedgerEntryDraft("1100", "EUR", debit_minor=100),
                LedgerEntryDraft("4100", "EUR", credit_minor=99),
            ),
        )

    transaction = service.post_transaction(
        command_key="balanced",
        transaction_type="adjustment",
        entries=(
            LedgerEntryDraft("1000", "EUR", debit_minor=100),
            LedgerEntryDraft("9000", "EUR", credit_minor=100),
        ),
    )

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "UPDATE AccountingTransactions SET memo='changed' WHERE id=?",
            (transaction.id,),
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "DELETE FROM AccountingEntries WHERE transaction_id=?",
            (transaction.id,),
        )

    conn.close()


def test_reversal_offsets_party_balance_without_mutating_original():
    conn = _foundation_connection()
    party_id = _party_id(conn)
    service = LedgerPostingService(conn)
    original = service.post_transaction(
        command_key="invoice-to-reverse",
        transaction_type="invoice_issue",
        entries=(
            LedgerEntryDraft("1100", "EUR", debit_minor=121, party_id=party_id),
            LedgerEntryDraft("4100", "EUR", credit_minor=100),
            LedgerEntryDraft("2100", "EUR", credit_minor=21),
        ),
    )

    reversal = service.reverse_transaction(
        original.id,
        command_key="reverse-invoice",
    )

    assert reversal.reversal_of_transaction_id == original.id
    assert service.party_balance_minor(party_id) == 0

    conn.close()


def test_financial_command_keys_cannot_be_reused_for_different_sources():
    conn = _foundation_connection()
    service = LedgerPostingService(conn)
    service.post_adjustment(
        command_key="shared-command",
        entries=(
            LedgerEntryDraft("1000", "EUR", debit_minor=100),
            LedgerEntryDraft("9000", "EUR", credit_minor=100),
        ),
    )

    with pytest.raises(ValueError, match="belongs to another ledger command"):
        service.post_transaction(
            command_key="shared-command",
            transaction_type="invoice_issue",
            source_type="invoice",
            source_id=1,
            entries=(
                LedgerEntryDraft("1100", "EUR", debit_minor=100),
                LedgerEntryDraft("4100", "EUR", credit_minor=100),
            ),
        )

    conn.close()

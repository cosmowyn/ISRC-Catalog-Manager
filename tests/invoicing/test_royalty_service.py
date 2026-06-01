import sqlite3

import pytest

from isrc_manager.code_registry import (
    BUILTIN_CATEGORY_ROYALTY_STATEMENT_NUMBER,
    CodeRegistryService,
)
from isrc_manager.invoicing import (
    ArtistPayoutPayload,
    InvoiceAccountingReportService,
    RoyaltyAccountingService,
    RoyaltyCalculationLinePayload,
    RoyaltyCalculationPayload,
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
        SET prefix='ROY', normalized_prefix='ROY'
        WHERE system_key=?
        """,
        (BUILTIN_CATEGORY_ROYALTY_STATEMENT_NUMBER,),
    )
    conn.commit()
    return conn


def _artist_id(conn: sqlite3.Connection) -> int:
    return PartyService(conn).create_party(
        PartyPayload(
            legal_name="Artist Person",
            display_name="Artist",
            artist_name="Artist",
            party_type="artist",
            vat_number="NLARTIST",
        )
    )


def test_royalty_calculation_posts_only_after_approval_and_is_idempotent():
    conn = _connection()
    artist_id = _artist_id(conn)
    service = RoyaltyAccountingService(conn)
    reports = InvoiceAccountingReportService(conn)

    calculation = service.create_calculation(
        RoyaltyCalculationPayload(
            party_id=artist_id,
            lines=(
                RoyaltyCalculationLinePayload(
                    description="Streaming royalty",
                    net_payable_minor=12_000,
                    source_type="track",
                    source_id=1,
                ),
                RoyaltyCalculationLinePayload(
                    description="Download royalty",
                    net_payable_minor=3_000,
                    source_type="track",
                    source_id=2,
                ),
            ),
        )
    )

    assert calculation.status == "calculated"
    assert calculation.net_payable_minor == 15_000
    assert conn.execute("SELECT COUNT(*) FROM AccountingTransactions").fetchone()[0] == 0

    posted = service.approve_and_post_calculation(
        calculation.id,
        command_key="approve-royalty",
    )
    replayed = service.approve_and_post_calculation(
        calculation.id,
        command_key="approve-royalty",
    )
    entries = conn.execute("""
        SELECT a.code, e.debit_minor, e.credit_minor, e.party_id
        FROM AccountingEntries e
        INNER JOIN AccountingAccounts a ON a.id=e.account_id
        ORDER BY e.id
        """).fetchall()
    payout_report = reports.artist_payout_report()

    assert posted.status == "posted"
    assert replayed.ledger_transaction_id == posted.ledger_transaction_id
    assert entries == [
        ("5000", 15_000, None, None),
        ("2000", None, 15_000, artist_id),
    ]
    assert [
        (row.party_id, row.payable_posted_minor, row.payout_paid_minor, row.payable_balance_minor)
        for row in payout_report
    ] == [(artist_id, 15_000, 0, 15_000)]

    conn.close()


def test_royalty_statement_is_canonical_non_posting_and_artist_payout_settles_payable():
    conn = _connection()
    artist_id = _artist_id(conn)
    service = RoyaltyAccountingService(conn)
    reports = InvoiceAccountingReportService(conn)
    calculation = service.create_calculation(
        RoyaltyCalculationPayload(
            party_id=artist_id,
            lines=(
                RoyaltyCalculationLinePayload(
                    description="Royalty",
                    net_payable_minor=15_000,
                ),
            ),
        )
    )
    posted = service.approve_and_post_calculation(
        calculation.id,
        command_key="approve-royalty",
    )

    statement = service.generate_statement(
        posted.id,
        command_key="statement-royalty",
        issue_date="2026-02-01",
    )
    replayed_statement = service.generate_statement(
        posted.id,
        command_key="statement-royalty",
        issue_date="2026-02-01",
    )

    assert statement.statement_number.startswith("ROY")
    assert replayed_statement.id == statement.id
    assert conn.execute("SELECT COUNT(*) FROM AccountingTransactions").fetchone()[0] == 1

    first_payout = service.record_artist_payout(
        ArtistPayoutPayload(
            party_id=artist_id,
            royalty_calculation_id=posted.id,
            amount_minor=5_000,
            paid_at="2026-02-10",
            payment_method="bank",
            payment_reference="PAY-1",
            idempotency_key="artist-payout-1",
        )
    )
    replayed_payout = service.record_artist_payout(
        ArtistPayoutPayload(
            party_id=artist_id,
            royalty_calculation_id=posted.id,
            amount_minor=5_000,
            paid_at="2026-02-10",
            idempotency_key="artist-payout-1",
        )
    )
    service.record_artist_payout(
        ArtistPayoutPayload(
            party_id=artist_id,
            royalty_calculation_id=posted.id,
            amount_minor=10_000,
            paid_at="2026-02-11",
            idempotency_key="artist-payout-2",
        )
    )
    paid_calculation = service.fetch_calculation(posted.id)
    payout_report = reports.artist_payout_report()

    assert replayed_payout.id == first_payout.id
    assert (
        service.royalty_payable_balance_minor(
            calculation_id=posted.id,
            party_id=artist_id,
        )
        == 0
    )
    assert paid_calculation is not None
    assert paid_calculation.status == "paid"
    assert [
        (row.party_id, row.payable_posted_minor, row.payout_paid_minor, row.payable_balance_minor)
        for row in payout_report
    ] == [(artist_id, 15_000, 15_000, 0)]

    with pytest.raises(ValueError, match="no outstanding payable"):
        service.record_artist_payout(
            ArtistPayoutPayload(
                party_id=artist_id,
                royalty_calculation_id=posted.id,
                amount_minor=1,
                paid_at="2026-02-12",
                idempotency_key="artist-payout-overpay",
            )
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "UPDATE ArtistPayouts SET amount_minor=1 WHERE id=?",
            (first_payout.id,),
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "UPDATE RoyaltyStatements SET total_minor=1 WHERE id=?",
            (statement.id,),
        )

    conn.close()

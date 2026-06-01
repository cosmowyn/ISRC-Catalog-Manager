"""Royalty calculation, statement, payable, and artist payout services."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager

from isrc_manager.code_registry import (
    BUILTIN_CATEGORY_ROYALTY_STATEMENT_NUMBER,
    CodeRegistryService,
)

from .command_log import FinancialCommandLogService
from .ledger_service import LedgerPostingService
from .models import (
    DEFAULT_CURRENCY,
    AccountingTransactionLinkDraft,
    ArtistPayoutPayload,
    ArtistPayoutRecord,
    LedgerEntryDraft,
    RoyaltyCalculationPayload,
    RoyaltyCalculationRecord,
    RoyaltyStatementRecord,
)
from .money import normalize_currency


def _clean_text(value: object | None) -> str | None:
    text = str(value or "").strip()
    return text or None


class RoyaltyAccountingService:
    """Keeps draft royalty calculations non-posting until approved and posted."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.ledger = LedgerPostingService(conn)
        self.code_registry = CodeRegistryService(conn)
        self.command_log = FinancialCommandLogService(conn)

    @contextmanager
    def _immediate_transaction(self):
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield self.conn.cursor()
        except Exception:
            self.conn.rollback()
            raise
        else:
            self.conn.commit()

    def create_calculation(self, payload: RoyaltyCalculationPayload) -> RoyaltyCalculationRecord:
        currency = normalize_currency(payload.currency)
        if not payload.lines:
            raise ValueError("Royalty calculation requires at least one line.")
        line_rows: list[tuple[str, int, str | None, str | None]] = []
        for line in payload.lines:
            description = _clean_text(line.description)
            if description is None:
                raise ValueError("Royalty calculation line description is required.")
            amount = int(line.net_payable_minor)
            if amount < 0:
                raise ValueError("Royalty calculation line amount must be non-negative.")
            line_rows.append(
                (
                    description,
                    amount,
                    _clean_text(line.source_type),
                    _clean_text(line.source_id),
                )
            )
        total = sum(row[1] for row in line_rows)
        if total <= 0:
            raise ValueError("Royalty calculation payable amount must be greater than zero.")
        with self.conn:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                INSERT INTO RoyaltyCalculations(
                    party_id,
                    status,
                    period_start,
                    period_end,
                    currency,
                    net_payable_minor,
                    created_by
                )
                VALUES (?, 'calculated', ?, ?, ?, ?, ?)
                """,
                (
                    int(payload.party_id),
                    _clean_text(payload.period_start),
                    _clean_text(payload.period_end),
                    currency,
                    total,
                    _clean_text(payload.created_by),
                ),
            )
            calculation_id = int(cursor.lastrowid)
            for sort_order, row in enumerate(line_rows, start=1):
                cursor.execute(
                    """
                    INSERT INTO RoyaltyCalculationLines(
                        calculation_id,
                        description,
                        net_payable_minor,
                        source_type,
                        source_id,
                        sort_order
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        calculation_id,
                        row[0],
                        row[1],
                        row[2],
                        row[3],
                        sort_order,
                    ),
                )
        record = self.fetch_calculation(calculation_id)
        if record is None:
            raise RuntimeError("Royalty calculation could not be reloaded.")
        return record

    def approve_and_post_calculation(
        self,
        calculation_id: int,
        *,
        command_key: str,
        created_by: str | None = None,
    ) -> RoyaltyCalculationRecord:
        clean_command_key = str(command_key or "").strip()
        if not clean_command_key:
            raise ValueError("Royalty approval idempotency key is required.")
        with self._immediate_transaction() as cursor:
            existing = self.command_log.fetch(clean_command_key)
            if existing is not None and existing.status == "completed":
                if existing.source_type != "royalty_calculation" or existing.source_id != str(
                    int(calculation_id)
                ):
                    raise ValueError(
                        f"Financial command {clean_command_key!r} belongs to another source."
                    )
                record = self.fetch_calculation(int(calculation_id))
                if record is None:
                    raise RuntimeError("Completed royalty command points to a missing calculation.")
                return record
            calculation = self.fetch_calculation(int(calculation_id))
            if calculation is None:
                raise ValueError(f"Royalty calculation {int(calculation_id)} was not found.")
            if calculation.status not in {"calculated", "reviewed", "approved"}:
                raise ValueError(
                    f"Royalty calculation status {calculation.status!r} cannot be posted."
                )
            transaction = self.ledger.post_transaction(
                command_key=clean_command_key,
                transaction_type="royalty_payable",
                source_type="royalty_calculation",
                source_id=int(calculation.id),
                created_by=created_by,
                memo=f"Approve royalty payable {calculation.id}",
                cursor=cursor,
                links=(
                    AccountingTransactionLinkDraft(
                        source_type="royalty_calculation",
                        source_id=int(calculation.id),
                        relation_type="royalty_payable",
                    ),
                ),
                entries=(
                    LedgerEntryDraft(
                        "5000",
                        calculation.currency,
                        debit_minor=calculation.net_payable_minor,
                        source_type="royalty_calculation",
                        source_id=int(calculation.id),
                    ),
                    LedgerEntryDraft(
                        "2000",
                        calculation.currency,
                        credit_minor=calculation.net_payable_minor,
                        party_id=int(calculation.party_id),
                        source_type="royalty_calculation",
                        source_id=int(calculation.id),
                    ),
                ),
            )
            cursor.execute(
                """
                UPDATE RoyaltyCalculations
                SET status='posted',
                    ledger_transaction_id=?,
                    idempotency_key=?,
                    updated_at=datetime('now')
                WHERE id=? AND status IN ('calculated', 'reviewed', 'approved')
                """,
                (int(transaction.id), clean_command_key, int(calculation.id)),
            )
            if cursor.rowcount != 1:
                raise ValueError("Royalty calculation could not be posted because it changed.")
        record = self.fetch_calculation(int(calculation_id))
        if record is None:
            raise RuntimeError("Posted royalty calculation could not be reloaded.")
        return record

    def generate_statement(
        self,
        calculation_id: int,
        *,
        command_key: str,
        issue_date: str,
    ) -> RoyaltyStatementRecord:
        clean_command_key = str(command_key or "").strip()
        if not clean_command_key:
            raise ValueError("Royalty statement idempotency key is required.")
        clean_issue_date = _clean_text(issue_date)
        if clean_issue_date is None:
            raise ValueError("Royalty statement issue date is required.")
        with self._immediate_transaction() as cursor:
            existing = self.command_log.fetch(clean_command_key)
            if existing is not None:
                if existing.status == "completed":
                    record = self.fetch_statement_by_idempotency_key(clean_command_key)
                    if record is None:
                        raise RuntimeError("Completed statement command is missing its statement.")
                    return record
                raise ValueError(
                    f"Financial command {clean_command_key!r} is already {existing.status}."
                )
            existing_statement = self.fetch_statement_for_calculation(int(calculation_id))
            if existing_statement is not None:
                raise ValueError("Royalty calculation already has a generated statement.")
            calculation = self.fetch_calculation(int(calculation_id))
            if calculation is None:
                raise ValueError(f"Royalty calculation {int(calculation_id)} was not found.")
            if calculation.status not in {"posted", "statement_generated", "paid"}:
                raise ValueError("Royalty statement can only be generated after posting.")
            self.command_log.start(
                command_key=clean_command_key,
                command_type="royalty_statement",
                source_type="royalty_calculation",
                source_id=int(calculation.id),
            )
            result = self.code_registry.generate_next_code(
                system_key=BUILTIN_CATEGORY_ROYALTY_STATEMENT_NUMBER,
                created_via="royalty.statement",
                cursor=cursor,
            )
            cursor.execute(
                """
                INSERT INTO RoyaltyStatements(
                    statement_registry_entry_id,
                    statement_number,
                    calculation_id,
                    party_id,
                    status,
                    issue_date,
                    currency,
                    total_minor,
                    idempotency_key
                )
                VALUES (?, ?, ?, ?, 'generated', ?, ?, ?, ?)
                """,
                (
                    int(result.entry.id),
                    result.entry.value,
                    int(calculation.id),
                    int(calculation.party_id),
                    clean_issue_date,
                    calculation.currency,
                    int(calculation.net_payable_minor),
                    clean_command_key,
                ),
            )
            statement_id = int(cursor.lastrowid)
            if calculation.status == "posted":
                cursor.execute(
                    """
                    UPDATE RoyaltyCalculations
                    SET status='statement_generated',
                        updated_at=datetime('now')
                    WHERE id=?
                    """,
                    (int(calculation.id),),
                )
            self.command_log.complete(
                command_key=clean_command_key,
                result_type="royalty_statement",
                result_id=statement_id,
                ledger_transaction_id=None,
            )
        record = self.fetch_statement_by_idempotency_key(clean_command_key)
        if record is None:
            raise RuntimeError("Royalty statement could not be reloaded.")
        return record

    def record_artist_payout(self, payload: ArtistPayoutPayload) -> ArtistPayoutRecord:
        command_key = str(payload.idempotency_key or "").strip()
        if not command_key:
            raise ValueError("Artist payout idempotency key is required.")
        currency = normalize_currency(payload.currency)
        if int(payload.amount_minor) <= 0:
            raise ValueError("Artist payout amount must be greater than zero.")
        if not _clean_text(payload.paid_at):
            raise ValueError("Artist payout date is required.")
        if payload.royalty_calculation_id is None:
            raise ValueError("Artist payout must link to a royalty calculation.")
        with self._immediate_transaction() as cursor:
            existing = self.fetch_artist_payout_by_idempotency_key(command_key)
            if existing is not None:
                return existing
            calculation = self.fetch_calculation(int(payload.royalty_calculation_id))
            if calculation is None:
                raise ValueError(
                    f"Royalty calculation {int(payload.royalty_calculation_id)} was not found."
                )
            if calculation.party_id != int(payload.party_id):
                raise ValueError(
                    "Artist payout party does not match the royalty calculation party."
                )
            if calculation.currency != currency:
                raise ValueError(
                    "Artist payout currency must match the royalty calculation currency."
                )
            if calculation.status not in {"posted", "statement_generated", "paid"}:
                raise ValueError("Artist payout can only be recorded after royalty posting.")
            payable_balance = self.royalty_payable_balance_minor(
                calculation_id=int(calculation.id),
                party_id=int(payload.party_id),
                currency=currency,
                cursor=cursor,
            )
            if payable_balance <= 0:
                raise ValueError("Royalty calculation has no outstanding payable balance.")
            if int(payload.amount_minor) > payable_balance and not payload.allow_overpayment:
                raise ValueError("Artist payout would overpay the royalty payable.")
            cursor.execute(
                """
                INSERT INTO ArtistPayouts(
                    party_id,
                    royalty_calculation_id,
                    amount_minor,
                    currency,
                    paid_at,
                    payment_method,
                    payment_reference,
                    memo,
                    idempotency_key,
                    created_by
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(payload.party_id),
                    int(calculation.id),
                    int(payload.amount_minor),
                    currency,
                    str(payload.paid_at).strip(),
                    _clean_text(payload.payment_method),
                    _clean_text(payload.payment_reference),
                    _clean_text(payload.memo),
                    command_key,
                    _clean_text(payload.created_by),
                ),
            )
            payout_id = int(cursor.lastrowid)
            transaction = self.ledger.post_transaction(
                command_key=command_key,
                transaction_type="artist_payout",
                source_type="artist_payout",
                source_id=payout_id,
                created_by=payload.created_by,
                memo=f"Artist payout for royalty calculation {calculation.id}",
                cursor=cursor,
                links=(
                    AccountingTransactionLinkDraft(
                        source_type="royalty_calculation",
                        source_id=int(calculation.id),
                        relation_type="artist_payout",
                    ),
                    AccountingTransactionLinkDraft(
                        source_type="artist_payout",
                        source_id=payout_id,
                        relation_type="artist_payout",
                    ),
                ),
                entries=(
                    LedgerEntryDraft(
                        "2000",
                        currency,
                        debit_minor=int(payload.amount_minor),
                        party_id=int(payload.party_id),
                        source_type="royalty_calculation",
                        source_id=int(calculation.id),
                    ),
                    LedgerEntryDraft(
                        "1000",
                        currency,
                        credit_minor=int(payload.amount_minor),
                        source_type="artist_payout",
                        source_id=payout_id,
                    ),
                ),
            )
            cursor.execute(
                "UPDATE ArtistPayouts SET ledger_transaction_id=? WHERE id=?",
                (int(transaction.id), payout_id),
            )
            remaining = self.royalty_payable_balance_minor(
                calculation_id=int(calculation.id),
                party_id=int(payload.party_id),
                currency=currency,
                cursor=cursor,
            )
            if remaining <= 0:
                cursor.execute(
                    """
                    UPDATE RoyaltyCalculations
                    SET status='paid',
                        updated_at=datetime('now')
                    WHERE id=?
                    """,
                    (int(calculation.id),),
                )
        record = self.fetch_artist_payout_by_idempotency_key(command_key)
        if record is None:
            raise RuntimeError("Artist payout could not be reloaded.")
        return record

    def royalty_payable_balance_minor(
        self,
        *,
        calculation_id: int,
        party_id: int,
        currency: str = DEFAULT_CURRENCY,
        cursor: sqlite3.Cursor | None = None,
    ) -> int:
        cur = cursor or self.conn.cursor()
        row = cur.execute(
            """
            SELECT COALESCE(SUM(COALESCE(e.credit_minor, 0) - COALESCE(e.debit_minor, 0)), 0)
            FROM AccountingEntries e
            INNER JOIN AccountingAccounts a ON a.id=e.account_id
            WHERE a.code='2000'
              AND e.party_id=?
              AND e.currency=?
              AND e.source_type='royalty_calculation'
              AND e.source_id=?
            """,
            (int(party_id), normalize_currency(currency), str(int(calculation_id))),
        ).fetchone()
        return int(row[0] or 0)

    def fetch_calculation(self, calculation_id: int) -> RoyaltyCalculationRecord | None:
        row = self.conn.execute(
            """
            SELECT id, party_id, status, currency, net_payable_minor, ledger_transaction_id, created_at, updated_at
            FROM RoyaltyCalculations
            WHERE id=?
            """,
            (int(calculation_id),),
        ).fetchone()
        if not row:
            return None
        return RoyaltyCalculationRecord(
            id=int(row[0]),
            party_id=int(row[1]),
            status=str(row[2] or ""),
            currency=str(row[3] or DEFAULT_CURRENCY),
            net_payable_minor=int(row[4] or 0),
            ledger_transaction_id=int(row[5]) if row[5] is not None else None,
            created_at=_clean_text(row[6]),
            updated_at=_clean_text(row[7]),
        )

    def fetch_statement(self, statement_id: int) -> RoyaltyStatementRecord | None:
        row = self.conn.execute(
            """
            SELECT
                id,
                statement_registry_entry_id,
                statement_number,
                calculation_id,
                party_id,
                status,
                issue_date,
                currency,
                total_minor,
                idempotency_key,
                created_at
            FROM RoyaltyStatements
            WHERE id=?
            """,
            (int(statement_id),),
        ).fetchone()
        return self._row_to_statement(row) if row else None

    def fetch_statement_by_idempotency_key(
        self, idempotency_key: str
    ) -> RoyaltyStatementRecord | None:
        row = self.conn.execute(
            """
            SELECT
                id,
                statement_registry_entry_id,
                statement_number,
                calculation_id,
                party_id,
                status,
                issue_date,
                currency,
                total_minor,
                idempotency_key,
                created_at
            FROM RoyaltyStatements
            WHERE idempotency_key=?
            """,
            (str(idempotency_key or "").strip(),),
        ).fetchone()
        return self._row_to_statement(row) if row else None

    def fetch_statement_for_calculation(self, calculation_id: int) -> RoyaltyStatementRecord | None:
        row = self.conn.execute(
            """
            SELECT
                id,
                statement_registry_entry_id,
                statement_number,
                calculation_id,
                party_id,
                status,
                issue_date,
                currency,
                total_minor,
                idempotency_key,
                created_at
            FROM RoyaltyStatements
            WHERE calculation_id=?
            """,
            (int(calculation_id),),
        ).fetchone()
        return self._row_to_statement(row) if row else None

    def fetch_artist_payout_by_idempotency_key(
        self, idempotency_key: str
    ) -> ArtistPayoutRecord | None:
        row = self.conn.execute(
            """
            SELECT
                id,
                party_id,
                royalty_calculation_id,
                amount_minor,
                currency,
                paid_at,
                payment_method,
                payment_reference,
                ledger_transaction_id,
                idempotency_key,
                memo,
                created_by,
                created_at
            FROM ArtistPayouts
            WHERE idempotency_key=?
            """,
            (str(idempotency_key or "").strip(),),
        ).fetchone()
        if not row:
            return None
        if row[8] is None:
            raise RuntimeError("Artist payout is missing its ledger transaction link.")
        return ArtistPayoutRecord(
            id=int(row[0]),
            party_id=int(row[1]),
            royalty_calculation_id=int(row[2]) if row[2] is not None else None,
            amount_minor=int(row[3]),
            currency=str(row[4] or DEFAULT_CURRENCY),
            paid_at=str(row[5] or ""),
            payment_method=_clean_text(row[6]),
            payment_reference=_clean_text(row[7]),
            ledger_transaction_id=int(row[8]),
            idempotency_key=str(row[9] or ""),
            memo=_clean_text(row[10]),
            created_by=_clean_text(row[11]),
            created_at=_clean_text(row[12]),
        )

    @staticmethod
    def _row_to_statement(row) -> RoyaltyStatementRecord:
        return RoyaltyStatementRecord(
            id=int(row[0]),
            statement_registry_entry_id=int(row[1]),
            statement_number=str(row[2] or ""),
            calculation_id=int(row[3]),
            party_id=int(row[4]),
            status=str(row[5] or ""),
            issue_date=str(row[6] or ""),
            currency=str(row[7] or DEFAULT_CURRENCY),
            total_minor=int(row[8] or 0),
            idempotency_key=str(row[9] or ""),
            created_at=_clean_text(row[10]),
        )

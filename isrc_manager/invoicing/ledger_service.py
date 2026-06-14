"""Ledger posting primitives for ledger-backed billing."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from contextlib import contextmanager

from .command_log import FinancialCommandLogService
from .models import (
    DEFAULT_CURRENCY,
    NORMAL_BALANCE_CREDIT,
    NORMAL_BALANCE_DEBIT,
    AccountingAccountPayload,
    AccountingAccountRecord,
    AccountingAccountSeed,
    AccountingTransactionLinkDraft,
    LedgerEntryDraft,
    LedgerTransactionRecord,
)
from .money import normalize_currency, normalize_vat_treatment

DEFAULT_ACCOUNT_SEEDS: tuple[AccountingAccountSeed, ...] = (
    AccountingAccountSeed("1000", "Cash Clearing", "asset", NORMAL_BALANCE_DEBIT),
    AccountingAccountSeed("1100", "Accounts Receivable", "asset", NORMAL_BALANCE_DEBIT),
    AccountingAccountSeed("1200", "VAT Input / VAT Receivable", "asset", NORMAL_BALANCE_DEBIT),
    AccountingAccountSeed("2000", "Accounts Payable", "liability", NORMAL_BALANCE_CREDIT),
    AccountingAccountSeed("2100", "VAT Output / VAT Payable", "liability", NORMAL_BALANCE_CREDIT),
    AccountingAccountSeed("4000", "Revenue", "income", NORMAL_BALANCE_CREDIT),
    AccountingAccountSeed("4100", "Venue Revenue", "income", NORMAL_BALANCE_CREDIT),
    AccountingAccountSeed("5000", "Artist/Royalty Expense", "expense", NORMAL_BALANCE_DEBIT),
    AccountingAccountSeed("5100", "Catalog/Service Expense", "expense", NORMAL_BALANCE_DEBIT),
    AccountingAccountSeed("8000", "Rounding Difference", "expense", NORMAL_BALANCE_DEBIT),
    AccountingAccountSeed(
        "9000",
        "Suspense / Migration Opening Balance",
        "equity",
        NORMAL_BALANCE_CREDIT,
    ),
)

ACCOUNT_TYPES = frozenset({"asset", "liability", "equity", "income", "expense"})
NORMAL_BALANCES = frozenset({NORMAL_BALANCE_DEBIT, NORMAL_BALANCE_CREDIT})


def _clean_text(value: object | None) -> str | None:
    text = str(value or "").strip()
    return text or None


def ensure_default_accounts(conn: sqlite3.Connection) -> None:
    for seed in DEFAULT_ACCOUNT_SEEDS:
        conn.execute(
            """
            INSERT INTO AccountingAccounts(
                code,
                name,
                account_type,
                normal_balance,
                system_flag,
                active
            )
            VALUES (?, ?, ?, ?, 1, 1)
            ON CONFLICT(code) DO UPDATE SET
                name=excluded.name,
                account_type=excluded.account_type,
                normal_balance=excluded.normal_balance,
                system_flag=1,
                updated_at=datetime('now')
            """,
            (seed.code, seed.name, seed.account_type, seed.normal_balance),
        )


class AccountingAccountService:
    """Maintains the editable chart-of-accounts records used by ledger postings."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def list_accounts(self, *, active_only: bool = False) -> list[AccountingAccountRecord]:
        where_sql = "WHERE active=1" if active_only else ""
        rows = self.conn.execute(f"""
            SELECT id, code, name, account_type, normal_balance, system_flag, active, created_at, updated_at
            FROM AccountingAccounts
            {where_sql}
            ORDER BY active DESC, code
            """).fetchall()
        return [self._row_to_record(row) for row in rows]

    def fetch_account(self, account_id: int) -> AccountingAccountRecord | None:
        row = self.conn.execute(
            """
            SELECT id, code, name, account_type, normal_balance, system_flag, active, created_at, updated_at
            FROM AccountingAccounts
            WHERE id=?
            """,
            (int(account_id),),
        ).fetchone()
        return self._row_to_record(row) if row else None

    def fetch_account_by_code(self, account_code: str) -> AccountingAccountRecord | None:
        row = self.conn.execute(
            """
            SELECT id, code, name, account_type, normal_balance, system_flag, active, created_at, updated_at
            FROM AccountingAccounts
            WHERE code=?
            """,
            (str(account_code or "").strip(),),
        ).fetchone()
        return self._row_to_record(row) if row else None

    def create_account(self, payload: AccountingAccountPayload) -> int:
        clean_code, clean_name, account_type, normal_balance = self._validated_payload(payload)
        with self.conn:
            cur = self.conn.execute(
                """
                INSERT INTO AccountingAccounts(
                    code, name, account_type, normal_balance, system_flag, active
                )
                VALUES (?, ?, ?, ?, 0, ?)
                """,
                (clean_code, clean_name, account_type, normal_balance, 1 if payload.active else 0),
            )
            return int(cur.lastrowid)

    def update_account(
        self, account_id: int, payload: AccountingAccountPayload
    ) -> AccountingAccountRecord:
        clean_code, clean_name, account_type, normal_balance = self._validated_payload(payload)
        with self.conn:
            cur = self.conn.execute(
                """
                UPDATE AccountingAccounts
                SET code=?,
                    name=?,
                    account_type=?,
                    normal_balance=?,
                    active=?,
                    updated_at=datetime('now')
                WHERE id=?
                """,
                (
                    clean_code,
                    clean_name,
                    account_type,
                    normal_balance,
                    1 if payload.active else 0,
                    int(account_id),
                ),
            )
            if cur.rowcount != 1:
                raise ValueError(f"Accounting account {int(account_id)} was not found.")
        record = self.fetch_account(account_id)
        if record is None:
            raise RuntimeError("Accounting account could not be reloaded.")
        return record

    @staticmethod
    def _validated_payload(payload: AccountingAccountPayload) -> tuple[str, str, str, str]:
        clean_code = _clean_text(payload.code)
        clean_name = _clean_text(payload.name)
        account_type = str(payload.account_type or "").strip().lower()
        normal_balance = str(payload.normal_balance or "").strip().lower()
        if clean_code is None:
            raise ValueError("Accounting account code is required.")
        if clean_name is None:
            raise ValueError("Accounting account name is required.")
        if account_type not in ACCOUNT_TYPES:
            raise ValueError("Accounting account type is invalid.")
        if normal_balance not in NORMAL_BALANCES:
            raise ValueError("Accounting normal balance is invalid.")
        return clean_code, clean_name, account_type, normal_balance

    @staticmethod
    def _row_to_record(row) -> AccountingAccountRecord:
        return AccountingAccountRecord(
            id=int(row[0]),
            code=str(row[1] or ""),
            name=str(row[2] or ""),
            account_type=str(row[3] or ""),
            normal_balance=str(row[4] or ""),
            system_flag=bool(row[5]),
            active=bool(row[6]),
            created_at=_clean_text(row[7]),
            updated_at=_clean_text(row[8]),
        )


class LedgerPostingService:
    """Posts balanced immutable accounting transactions."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
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

    def fetch_account_by_code(self, account_code: str) -> AccountingAccountRecord | None:
        row = self.conn.execute(
            """
            SELECT id, code, name, account_type, normal_balance, system_flag, active, created_at, updated_at
            FROM AccountingAccounts
            WHERE code=?
            """,
            (str(account_code or "").strip(),),
        ).fetchone()
        if not row:
            return None
        return AccountingAccountRecord(
            id=int(row[0]),
            code=str(row[1] or ""),
            name=str(row[2] or ""),
            account_type=str(row[3] or ""),
            normal_balance=str(row[4] or ""),
            system_flag=bool(row[5]),
            active=bool(row[6]),
            created_at=_clean_text(row[7]),
            updated_at=_clean_text(row[8]),
        )

    def fetch_transaction(self, transaction_id: int) -> LedgerTransactionRecord | None:
        row = self.conn.execute(
            """
            SELECT
                id,
                registry_entry_id,
                transaction_number,
                transaction_type,
                posted_at,
                reversal_of_transaction_id,
                command_key,
                idempotency_key,
                created_by,
                memo
            FROM AccountingTransactions
            WHERE id=?
            """,
            (int(transaction_id),),
        ).fetchone()
        if not row:
            return None
        return LedgerTransactionRecord(
            id=int(row[0]),
            registry_entry_id=int(row[1]) if row[1] is not None else None,
            transaction_number=_clean_text(row[2]),
            transaction_type=str(row[3] or ""),
            posted_at=str(row[4] or ""),
            reversal_of_transaction_id=int(row[5]) if row[5] is not None else None,
            command_key=_clean_text(row[6]),
            idempotency_key=_clean_text(row[7]),
            created_by=_clean_text(row[8]),
            memo=_clean_text(row[9]),
        )

    def post_transaction(
        self,
        *,
        command_key: str,
        transaction_type: str,
        entries: Iterable[LedgerEntryDraft],
        links: Iterable[AccountingTransactionLinkDraft] = (),
        cursor: sqlite3.Cursor | None = None,
        source_type: str | None = None,
        source_id: str | int | None = None,
        registry_entry_id: int | None = None,
        transaction_number: str | None = None,
        reversal_of_transaction_id: int | None = None,
        created_by: str | None = None,
        memo: str | None = None,
    ) -> LedgerTransactionRecord:
        clean_command_key = str(command_key or "").strip()
        if not clean_command_key:
            raise ValueError("Financial command key is required.")
        clean_transaction_type = str(transaction_type or "").strip()
        if not clean_transaction_type:
            raise ValueError("Ledger transaction type is required.")
        entry_list = tuple(entries)
        link_list = tuple(links)
        if cursor is not None:
            transaction_id = self._post_transaction_with_cursor(
                cursor,
                command_key=clean_command_key,
                transaction_type=clean_transaction_type,
                entries=entry_list,
                links=link_list,
                source_type=source_type,
                source_id=source_id,
                registry_entry_id=registry_entry_id,
                transaction_number=transaction_number,
                reversal_of_transaction_id=reversal_of_transaction_id,
                created_by=created_by,
                memo=memo,
            )
            record = self.fetch_transaction(transaction_id)
            if record is None:
                raise RuntimeError("Posted ledger transaction could not be reloaded.")
            return record
        with self._immediate_transaction() as cursor:
            transaction_id = self._post_transaction_with_cursor(
                cursor,
                command_key=clean_command_key,
                transaction_type=clean_transaction_type,
                entries=entry_list,
                links=link_list,
                source_type=source_type,
                source_id=source_id,
                registry_entry_id=registry_entry_id,
                transaction_number=transaction_number,
                reversal_of_transaction_id=reversal_of_transaction_id,
                created_by=created_by,
                memo=memo,
            )
        record = self.fetch_transaction(transaction_id)
        if record is None:
            raise RuntimeError("Posted ledger transaction could not be reloaded.")
        return record

    def _post_transaction_with_cursor(
        self,
        cursor: sqlite3.Cursor,
        *,
        command_key: str,
        transaction_type: str,
        entries: tuple[LedgerEntryDraft, ...],
        links: tuple[AccountingTransactionLinkDraft, ...],
        source_type: str | None,
        source_id: str | int | None,
        registry_entry_id: int | None,
        transaction_number: str | None,
        reversal_of_transaction_id: int | None,
        created_by: str | None,
        memo: str | None,
    ) -> int:
        existing = self.command_log.start(
            command_key=command_key,
            command_type=transaction_type,
            source_type=source_type,
            source_id=source_id,
        )
        if existing is not None:
            if existing.status == "completed" and existing.ledger_transaction_id is not None:
                if (
                    existing.command_type != transaction_type
                    or existing.source_type != _clean_text(source_type)
                    or existing.source_id != _clean_text(source_id)
                ):
                    raise ValueError(
                        f"Financial command {command_key!r} belongs to another ledger command."
                    )
                return int(existing.ledger_transaction_id)
            raise ValueError(f"Financial command {command_key!r} is already {existing.status}.")
        self._validate_entries(entries)
        cursor.execute(
            """
            INSERT INTO AccountingTransactions(
                registry_entry_id,
                transaction_number,
                transaction_type,
                reversal_of_transaction_id,
                command_key,
                idempotency_key,
                created_by,
                memo
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(registry_entry_id) if registry_entry_id is not None else None,
                _clean_text(transaction_number),
                transaction_type,
                int(reversal_of_transaction_id) if reversal_of_transaction_id is not None else None,
                command_key,
                command_key,
                _clean_text(created_by),
                _clean_text(memo),
            ),
        )
        transaction_id = int(cursor.lastrowid)
        self._insert_entries(cursor, transaction_id=transaction_id, entries=entries)
        self._insert_links(cursor, transaction_id=transaction_id, links=links)
        if source_type and source_id is not None:
            self._insert_links(
                cursor,
                transaction_id=transaction_id,
                links=(
                    AccountingTransactionLinkDraft(
                        source_type=str(source_type),
                        source_id=source_id,
                        relation_type=transaction_type,
                    ),
                ),
            )
        self.command_log.complete(
            command_key=command_key,
            result_type="accounting_transaction",
            result_id=transaction_id,
            ledger_transaction_id=transaction_id,
        )
        return transaction_id

    def reverse_transaction(
        self,
        original_transaction_id: int,
        *,
        command_key: str,
        created_by: str | None = None,
        memo: str | None = None,
    ) -> LedgerTransactionRecord:
        rows = self.conn.execute(
            """
            SELECT
                a.code,
                e.currency,
                e.debit_minor,
                e.credit_minor,
                e.party_id,
                e.vat_treatment,
                e.vat_rate_basis_points,
                e.source_type,
                e.source_id
            FROM AccountingEntries e
            INNER JOIN AccountingAccounts a ON a.id=e.account_id
            WHERE e.transaction_id=?
            ORDER BY e.id
            """,
            (int(original_transaction_id),),
        ).fetchall()
        if not rows:
            raise ValueError(f"Ledger transaction {int(original_transaction_id)} has no entries.")
        reversal_entries = [
            LedgerEntryDraft(
                account_code=str(row[0] or ""),
                currency=str(row[1] or DEFAULT_CURRENCY),
                debit_minor=int(row[3]) if row[3] is not None else None,
                credit_minor=int(row[2]) if row[2] is not None else None,
                party_id=int(row[4]) if row[4] is not None else None,
                vat_treatment=_clean_text(row[5]),
                vat_rate_basis_points=int(row[6]) if row[6] is not None else None,
                source_type=_clean_text(row[7]),
                source_id=_clean_text(row[8]),
            )
            for row in rows
        ]
        return self.post_transaction(
            command_key=command_key,
            transaction_type="reversal",
            entries=reversal_entries,
            links=(
                AccountingTransactionLinkDraft(
                    source_type="accounting_transaction",
                    source_id=int(original_transaction_id),
                    relation_type="reversal",
                ),
            ),
            reversal_of_transaction_id=int(original_transaction_id),
            created_by=created_by,
            memo=memo,
        )

    def post_adjustment(
        self,
        *,
        command_key: str,
        entries: Iterable[LedgerEntryDraft],
        links: Iterable[AccountingTransactionLinkDraft] = (),
        created_by: str | None = None,
        memo: str | None = None,
    ) -> LedgerTransactionRecord:
        """Post an explicit balanced adjustment instead of mutating history."""

        return self.post_transaction(
            command_key=command_key,
            transaction_type="adjustment",
            entries=entries,
            links=links,
            created_by=created_by,
            memo=memo,
        )

    def party_balance_minor(self, party_id: int, *, currency: str = DEFAULT_CURRENCY) -> int:
        row = self.conn.execute(
            """
            SELECT COALESCE(SUM(COALESCE(debit_minor, 0) - COALESCE(credit_minor, 0)), 0)
            FROM AccountingEntries
            WHERE party_id=? AND currency=?
            """,
            (int(party_id), normalize_currency(currency)),
        ).fetchone()
        return int(row[0] or 0)

    def _validate_entries(self, entries: tuple[LedgerEntryDraft, ...]) -> None:
        if not entries:
            raise ValueError("A ledger transaction requires at least one entry.")
        totals: dict[str, dict[str, int]] = {}
        for entry in entries:
            currency = normalize_currency(entry.currency)
            account = self.fetch_account_by_code(entry.account_code)
            if account is None:
                raise ValueError(f"Unknown accounting account: {entry.account_code}")
            if not account.active:
                raise ValueError(f"Accounting account is inactive: {entry.account_code}")
            debit = entry.debit_minor
            credit = entry.credit_minor
            if (debit is None and credit is None) or (debit is not None and credit is not None):
                raise ValueError("Each ledger entry must contain exactly one debit or credit.")
            if debit is not None and int(debit) < 0:
                raise ValueError("Debit amounts must be non-negative.")
            if credit is not None and int(credit) < 0:
                raise ValueError("Credit amounts must be non-negative.")
            if entry.vat_treatment is not None:
                normalize_vat_treatment(entry.vat_treatment)
            bucket = totals.setdefault(currency, {"debit": 0, "credit": 0})
            bucket["debit"] += int(debit or 0)
            bucket["credit"] += int(credit or 0)
        for currency, values in totals.items():
            if values["debit"] != values["credit"]:
                raise ValueError(
                    f"Ledger transaction is not balanced for {currency}: "
                    f"debits={values['debit']} credits={values['credit']}"
                )

    def _insert_entries(
        self,
        cursor: sqlite3.Cursor,
        *,
        transaction_id: int,
        entries: tuple[LedgerEntryDraft, ...],
    ) -> None:
        for entry in entries:
            account = self.fetch_account_by_code(entry.account_code)
            if account is None:
                raise ValueError(f"Unknown accounting account: {entry.account_code}")
            cursor.execute(
                """
                INSERT INTO AccountingEntries(
                    transaction_id,
                    account_id,
                    party_id,
                    debit_minor,
                    credit_minor,
                    currency,
                    vat_treatment,
                    vat_rate_basis_points,
                    source_type,
                    source_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(transaction_id),
                    int(account.id),
                    int(entry.party_id) if entry.party_id is not None else None,
                    int(entry.debit_minor) if entry.debit_minor is not None else None,
                    int(entry.credit_minor) if entry.credit_minor is not None else None,
                    normalize_currency(entry.currency),
                    (
                        normalize_vat_treatment(entry.vat_treatment)
                        if entry.vat_treatment is not None
                        else None
                    ),
                    (
                        int(entry.vat_rate_basis_points)
                        if entry.vat_rate_basis_points is not None
                        else None
                    ),
                    _clean_text(entry.source_type),
                    _clean_text(entry.source_id),
                ),
            )

    @staticmethod
    def _insert_links(
        cursor: sqlite3.Cursor,
        *,
        transaction_id: int,
        links: tuple[AccountingTransactionLinkDraft, ...],
    ) -> None:
        for link in links:
            cursor.execute(
                """
                INSERT OR IGNORE INTO AccountingTransactionLinks(
                    transaction_id,
                    source_type,
                    source_id,
                    relation_type
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    int(transaction_id),
                    str(link.source_type or "").strip(),
                    str(link.source_id),
                    str(link.relation_type or "").strip(),
                ),
            )

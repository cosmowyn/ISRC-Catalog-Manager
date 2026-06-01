"""Invoice payment commands backed by immutable ledger postings."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager

from .invoice_service import InvoiceService
from .ledger_service import LedgerPostingService
from .models import (
    DEFAULT_CURRENCY,
    AccountingTransactionLinkDraft,
    InvoicePaymentPayload,
    InvoicePaymentRecord,
    LedgerEntryDraft,
)
from .money import normalize_currency


def _clean_text(value: object | None) -> str | None:
    text = str(value or "").strip()
    return text or None


class InvoicePaymentService:
    """Records business-facing invoice payments and posts settlement ledger entries."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.invoice_service = InvoiceService(conn)
        self.ledger = LedgerPostingService(conn)

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

    def record_invoice_payment(self, payload: InvoicePaymentPayload) -> InvoicePaymentRecord:
        command_key = str(payload.idempotency_key or "").strip()
        if not command_key:
            raise ValueError("Payment idempotency key is required.")
        currency = normalize_currency(payload.currency)
        if int(payload.amount_minor) <= 0:
            raise ValueError("Payment amount must be greater than zero.")
        if not _clean_text(payload.paid_at):
            raise ValueError("Payment date is required.")
        with self._immediate_transaction() as cursor:
            existing = self.fetch_payment_by_idempotency_key(command_key)
            if existing is not None:
                return existing
            invoice = self.invoice_service.fetch_invoice(int(payload.invoice_id))
            if invoice is None:
                raise ValueError(f"Invoice {int(payload.invoice_id)} was not found.")
            if invoice.party_id != int(payload.party_id):
                raise ValueError("Payment party does not match the invoice party.")
            if invoice.currency != currency:
                raise ValueError("Payment currency must match the invoice currency.")
            if invoice.document_status in {"draft", "cancelled", "voided", "credited"}:
                raise ValueError(
                    f"Invoice status {invoice.document_status!r} cannot accept payments."
                )
            outstanding = self.invoice_receivable_balance_minor(
                int(invoice.id),
                currency=currency,
                cursor=cursor,
            )
            if outstanding <= 0:
                raise ValueError("Invoice has no outstanding receivable balance.")
            if int(payload.amount_minor) > outstanding and not payload.allow_overpayment:
                raise ValueError("Payment would overpay the invoice.")
            cursor.execute(
                """
                INSERT INTO InvoicePayments(
                    invoice_id,
                    party_id,
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
                    int(invoice.id),
                    int(payload.party_id),
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
            payment_id = int(cursor.lastrowid)
            transaction = self.ledger.post_transaction(
                command_key=command_key,
                transaction_type="invoice_payment",
                source_type="invoice_payment",
                source_id=payment_id,
                created_by=payload.created_by,
                memo=f"Payment for invoice {invoice.invoice_number or invoice.draft_display_id}",
                cursor=cursor,
                links=(
                    AccountingTransactionLinkDraft(
                        source_type="invoice",
                        source_id=int(invoice.id),
                        relation_type="invoice_payment",
                    ),
                    AccountingTransactionLinkDraft(
                        source_type="invoice_payment",
                        source_id=payment_id,
                        relation_type="invoice_payment",
                    ),
                ),
                entries=(
                    LedgerEntryDraft(
                        "1000",
                        currency,
                        debit_minor=int(payload.amount_minor),
                        source_type="invoice_payment",
                        source_id=payment_id,
                    ),
                    LedgerEntryDraft(
                        "1100",
                        currency,
                        credit_minor=int(payload.amount_minor),
                        party_id=int(payload.party_id),
                        source_type="invoice",
                        source_id=int(invoice.id),
                    ),
                ),
            )
            cursor.execute(
                "UPDATE InvoicePayments SET ledger_transaction_id=? WHERE id=?",
                (int(transaction.id), payment_id),
            )
        record = self.fetch_payment_by_idempotency_key(command_key)
        if record is None:
            raise RuntimeError("Invoice payment could not be reloaded.")
        return record

    def invoice_receivable_balance_minor(
        self,
        invoice_id: int,
        *,
        currency: str = DEFAULT_CURRENCY,
        cursor: sqlite3.Cursor | None = None,
    ) -> int:
        cur = cursor or self.conn.cursor()
        row = cur.execute(
            """
            SELECT COALESCE(SUM(COALESCE(e.debit_minor, 0) - COALESCE(e.credit_minor, 0)), 0)
            FROM AccountingEntries e
            INNER JOIN AccountingAccounts a ON a.id=e.account_id
            WHERE a.code='1100'
              AND e.currency=?
              AND e.source_type='invoice'
              AND e.source_id=?
            """,
            (normalize_currency(currency), str(int(invoice_id))),
        ).fetchone()
        return int(row[0] or 0)

    def fetch_payment(self, payment_id: int) -> InvoicePaymentRecord | None:
        row = self.conn.execute(
            """
            SELECT
                id,
                invoice_id,
                party_id,
                amount_minor,
                currency,
                paid_at,
                payment_method,
                payment_reference,
                ledger_transaction_id,
                memo,
                idempotency_key,
                created_by,
                created_at
            FROM InvoicePayments
            WHERE id=?
            """,
            (int(payment_id),),
        ).fetchone()
        return self._row_to_payment(row) if row else None

    def fetch_payment_by_idempotency_key(self, idempotency_key: str) -> InvoicePaymentRecord | None:
        row = self.conn.execute(
            """
            SELECT
                id,
                invoice_id,
                party_id,
                amount_minor,
                currency,
                paid_at,
                payment_method,
                payment_reference,
                ledger_transaction_id,
                memo,
                idempotency_key,
                created_by,
                created_at
            FROM InvoicePayments
            WHERE idempotency_key=?
            """,
            (str(idempotency_key or "").strip(),),
        ).fetchone()
        return self._row_to_payment(row) if row else None

    @staticmethod
    def _row_to_payment(row) -> InvoicePaymentRecord:
        if row[8] is None:
            raise RuntimeError("Invoice payment is missing its ledger transaction link.")
        return InvoicePaymentRecord(
            id=int(row[0]),
            invoice_id=int(row[1]),
            party_id=int(row[2]),
            amount_minor=int(row[3]),
            currency=str(row[4] or DEFAULT_CURRENCY),
            paid_at=str(row[5] or ""),
            payment_method=_clean_text(row[6]),
            payment_reference=_clean_text(row[7]),
            ledger_transaction_id=int(row[8]),
            memo=_clean_text(row[9]),
            idempotency_key=str(row[10] or ""),
            created_by=_clean_text(row[11]),
            created_at=_clean_text(row[12]),
        )

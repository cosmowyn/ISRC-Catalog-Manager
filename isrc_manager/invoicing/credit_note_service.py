"""Credit-note commands for correcting issued invoices without mutation."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager

from isrc_manager.code_registry import BUILTIN_CATEGORY_CREDIT_NOTE_NUMBER, CodeRegistryService

from .invoice_service import InvoiceService
from .ledger_service import LedgerPostingService
from .models import (
    AccountingTransactionLinkDraft,
    CreditableInvoiceLineRecord,
    CreditNotePayload,
    CreditNoteRecord,
    LedgerEntryDraft,
)
from .money import normalize_currency
from .payment_service import InvoicePaymentService


def _clean_text(value: object | None) -> str | None:
    text = str(value or "").strip()
    return text or None


class CreditNoteService:
    """Issues canonical credit notes and posts reversing receivable ledger entries."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.invoice_service = InvoiceService(conn)
        self.payment_service = InvoicePaymentService(conn)
        self.ledger = LedgerPostingService(conn)
        self.code_registry = CodeRegistryService(conn)

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

    def create_credit_note(self, payload: CreditNotePayload) -> CreditNoteRecord:
        command_key = str(payload.idempotency_key or "").strip()
        if not command_key:
            raise ValueError("Credit note idempotency key is required.")
        reason = _clean_text(payload.reason)
        if reason is None:
            raise ValueError("Credit note reason is required.")
        issue_date = _clean_text(payload.issue_date)
        if issue_date is None:
            raise ValueError("Credit note issue date is required.")
        subtotal = int(payload.subtotal_minor)
        vat_total = int(payload.vat_total_minor)
        if subtotal < 0 or vat_total < 0:
            raise ValueError("Credit note amounts must be non-negative.")
        total = subtotal + vat_total
        if total <= 0:
            raise ValueError("Credit note total must be greater than zero.")
        currency = normalize_currency(payload.currency)
        with self._immediate_transaction() as cursor:
            existing = self.fetch_credit_note_by_idempotency_key(command_key)
            if existing is not None:
                return existing
            invoice = self.invoice_service.fetch_invoice(int(payload.invoice_id))
            if invoice is None:
                raise ValueError(f"Invoice {int(payload.invoice_id)} was not found.")
            if invoice.party_id != int(payload.party_id):
                raise ValueError("Credit note party does not match the invoice party.")
            if invoice.currency != currency:
                raise ValueError("Credit note currency must match the invoice currency.")
            if invoice.document_status in {"draft", "cancelled", "voided", "credited"}:
                raise ValueError(f"Invoice status {invoice.document_status!r} cannot be credited.")
            outstanding = self.payment_service.invoice_receivable_balance_minor(
                int(invoice.id),
                currency=currency,
                cursor=cursor,
            )
            if total > outstanding:
                raise ValueError("Credit note would exceed the invoice outstanding balance.")
            (
                remaining_subtotal,
                remaining_vat,
            ) = self._remaining_invoice_creditable_amounts(int(invoice.id), cursor=cursor)
            if subtotal > remaining_subtotal:
                raise ValueError("Credit note subtotal exceeds the remaining invoice subtotal.")
            if vat_total > remaining_vat:
                raise ValueError("Credit note VAT exceeds the remaining invoice VAT.")
            line_allocations = self._validated_line_allocations(
                invoice_id=int(invoice.id),
                allocations=payload.line_allocations,
                subtotal_minor=subtotal,
                vat_total_minor=vat_total,
                currency=currency,
                cursor=cursor,
            )
            result = self.code_registry.generate_next_code(
                system_key=BUILTIN_CATEGORY_CREDIT_NOTE_NUMBER,
                created_via="credit_note.issue",
                cursor=cursor,
            )
            cursor.execute(
                """
                INSERT INTO CreditNotes(
                    credit_note_registry_entry_id,
                    credit_note_number,
                    invoice_id,
                    party_id,
                    reason,
                    status,
                    issue_date,
                    currency,
                    subtotal_minor,
                    vat_total_minor,
                    total_minor,
                    idempotency_key,
                    created_by
                )
                VALUES (?, ?, ?, ?, ?, 'issued', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(result.entry.id),
                    result.entry.value,
                    int(invoice.id),
                    int(payload.party_id),
                    reason,
                    issue_date,
                    currency,
                    subtotal,
                    vat_total,
                    total,
                    command_key,
                    _clean_text(payload.created_by),
                ),
            )
            credit_note_id = int(cursor.lastrowid)
            self._insert_line_allocations(
                cursor,
                credit_note_id=credit_note_id,
                line_allocations=line_allocations,
                currency=currency,
            )
            transaction = self.ledger.post_transaction(
                command_key=command_key,
                transaction_type="credit_note",
                source_type="credit_note",
                source_id=credit_note_id,
                created_by=payload.created_by,
                memo=f"Credit note {result.entry.value} for invoice {invoice.invoice_number}",
                cursor=cursor,
                links=(
                    AccountingTransactionLinkDraft(
                        source_type="invoice",
                        source_id=int(invoice.id),
                        relation_type="credit_note",
                    ),
                    AccountingTransactionLinkDraft(
                        source_type="credit_note",
                        source_id=credit_note_id,
                        relation_type="credit_note",
                    ),
                ),
                entries=tuple(
                    [
                        *self._revenue_reversal_entries(
                            credit_note_id=credit_note_id,
                            subtotal_minor=subtotal,
                            currency=currency,
                            fallback_account_code=payload.revenue_account_code,
                            line_allocations=line_allocations,
                        ),
                        *self._vat_reversal_entries(
                            invoice_id=int(invoice.id),
                            credit_note_id=credit_note_id,
                            vat_total_minor=vat_total,
                            currency=currency,
                            line_allocations=line_allocations,
                            cursor=cursor,
                        ),
                        LedgerEntryDraft(
                            "1100",
                            currency,
                            credit_minor=total,
                            party_id=int(payload.party_id),
                            source_type="invoice",
                            source_id=int(invoice.id),
                        ),
                    ]
                ),
            )
            cursor.execute(
                "UPDATE CreditNotes SET ledger_transaction_id=? WHERE id=?",
                (int(transaction.id), credit_note_id),
            )
            total_credited = self._credited_total_minor(int(invoice.id), cursor=cursor)
            if total_credited >= invoice.total_minor:
                cursor.execute(
                    """
                    UPDATE Invoices
                    SET document_status='credited',
                        updated_at=datetime('now')
                    WHERE id=? AND document_status IN ('issued', 'sent')
                    """,
                    (int(invoice.id),),
                )
        record = self.fetch_credit_note_by_idempotency_key(command_key)
        if record is None:
            raise RuntimeError("Credit note could not be reloaded.")
        return record

    def creditable_invoice_lines(self, invoice_id: int) -> list[CreditableInvoiceLineRecord]:
        rows = self.conn.execute(
            """
            SELECT
                l.id,
                l.description,
                l.net_amount_minor,
                l.vat_amount_minor,
                l.gross_amount_minor,
                COALESCE(SUM(CASE WHEN cn.status='issued' THEN cla.subtotal_minor ELSE 0 END), 0),
                COALESCE(SUM(CASE WHEN cn.status='issued' THEN cla.vat_minor ELSE 0 END), 0),
                l.currency
            FROM InvoiceLineItems l
            LEFT JOIN CreditNoteLineAllocations cla ON cla.invoice_line_item_id=l.id
            LEFT JOIN CreditNotes cn ON cn.id=cla.credit_note_id
            WHERE l.invoice_id=?
            GROUP BY l.id
            ORDER BY l.sort_order, l.id
            """,
            (int(invoice_id),),
        ).fetchall()
        return [
            CreditableInvoiceLineRecord(
                id=int(row[0]),
                description=str(row[1] or ""),
                net_amount_minor=int(row[2] or 0),
                vat_amount_minor=int(row[3] or 0),
                gross_amount_minor=int(row[4] or 0),
                credited_subtotal_minor=int(row[5] or 0),
                credited_vat_minor=int(row[6] or 0),
                remaining_subtotal_minor=max(0, int(row[2] or 0) - int(row[5] or 0)),
                remaining_vat_minor=max(0, int(row[3] or 0) - int(row[6] or 0)),
                currency=str(row[7] or ""),
            )
            for row in rows
        ]

    def fetch_credit_note(self, credit_note_id: int) -> CreditNoteRecord | None:
        row = self.conn.execute(
            """
            SELECT
                id,
                credit_note_registry_entry_id,
                credit_note_number,
                invoice_id,
                party_id,
                reason,
                status,
                issue_date,
                currency,
                subtotal_minor,
                vat_total_minor,
                total_minor,
                ledger_transaction_id,
                idempotency_key,
                created_by,
                created_at
            FROM CreditNotes
            WHERE id=?
            """,
            (int(credit_note_id),),
        ).fetchone()
        return self._row_to_credit_note(row) if row else None

    def fetch_credit_note_by_idempotency_key(self, idempotency_key: str) -> CreditNoteRecord | None:
        row = self.conn.execute(
            """
            SELECT
                id,
                credit_note_registry_entry_id,
                credit_note_number,
                invoice_id,
                party_id,
                reason,
                status,
                issue_date,
                currency,
                subtotal_minor,
                vat_total_minor,
                total_minor,
                ledger_transaction_id,
                idempotency_key,
                created_by,
                created_at
            FROM CreditNotes
            WHERE idempotency_key=?
            """,
            (str(idempotency_key or "").strip(),),
        ).fetchone()
        return self._row_to_credit_note(row) if row else None

    def _credited_total_minor(
        self,
        invoice_id: int,
        *,
        cursor: sqlite3.Cursor | None = None,
    ) -> int:
        cur = cursor or self.conn.cursor()
        row = cur.execute(
            """
            SELECT COALESCE(SUM(total_minor), 0)
            FROM CreditNotes
            WHERE invoice_id=? AND status='issued'
            """,
            (int(invoice_id),),
        ).fetchone()
        return int(row[0] or 0)

    def _remaining_invoice_creditable_amounts(
        self,
        invoice_id: int,
        *,
        cursor: sqlite3.Cursor,
    ) -> tuple[int, int]:
        row = cursor.execute(
            """
            SELECT
                i.subtotal_minor - COALESCE(SUM(cn.subtotal_minor), 0),
                i.vat_total_minor - COALESCE(SUM(cn.vat_total_minor), 0)
            FROM Invoices i
            LEFT JOIN CreditNotes cn
              ON cn.invoice_id=i.id
             AND cn.status='issued'
            WHERE i.id=?
            GROUP BY i.id
            """,
            (int(invoice_id),),
        ).fetchone()
        if row is None:
            return (0, 0)
        return (max(0, int(row[0] or 0)), max(0, int(row[1] or 0)))

    def _validated_line_allocations(
        self,
        *,
        invoice_id: int,
        allocations: tuple[object, ...],
        subtotal_minor: int,
        vat_total_minor: int,
        currency: str,
        cursor: sqlite3.Cursor,
    ) -> tuple[dict[str, object], ...]:
        if not allocations:
            return ()
        grouped: dict[int, dict[str, int]] = {}
        for allocation in allocations:
            line_id = int(getattr(allocation, "invoice_line_item_id"))
            subtotal = int(getattr(allocation, "subtotal_minor"))
            vat = int(getattr(allocation, "vat_minor"))
            if subtotal < 0 or vat < 0:
                raise ValueError("Credit note line allocation amounts must be non-negative.")
            if subtotal + vat <= 0:
                raise ValueError("Credit note line allocation total must be greater than zero.")
            bucket = grouped.setdefault(line_id, {"subtotal_minor": 0, "vat_minor": 0})
            bucket["subtotal_minor"] += subtotal
            bucket["vat_minor"] += vat
        if sum(row["subtotal_minor"] for row in grouped.values()) != int(subtotal_minor):
            raise ValueError(
                "Credit note line subtotal allocation must match credit note subtotal."
            )
        if sum(row["vat_minor"] for row in grouped.values()) != int(vat_total_minor):
            raise ValueError("Credit note line VAT allocation must match credit note VAT total.")

        rows = cursor.execute(
            f"""
            SELECT
                id,
                net_amount_minor,
                vat_amount_minor,
                currency,
                COALESCE(ledger_account_code, '4100'),
                vat_treatment,
                vat_rate_basis_points
            FROM InvoiceLineItems
            WHERE invoice_id=?
              AND id IN ({", ".join("?" for _ in grouped)})
            """,
            (int(invoice_id), *grouped.keys()),
        ).fetchall()
        line_rows = {int(row[0]): row for row in rows}
        if set(line_rows) != set(grouped):
            raise ValueError("Credit note line allocation references a non-invoice line.")
        validated: list[dict[str, object]] = []
        for line_id, amounts in grouped.items():
            line = line_rows[line_id]
            credited = cursor.execute(
                """
                SELECT
                    COALESCE(SUM(cla.subtotal_minor), 0),
                    COALESCE(SUM(cla.vat_minor), 0)
                FROM CreditNoteLineAllocations cla
                INNER JOIN CreditNotes cn ON cn.id=cla.credit_note_id
                WHERE cla.invoice_line_item_id=?
                  AND cn.status='issued'
                """,
                (line_id,),
            ).fetchone()
            remaining_subtotal = int(line[1] or 0) - int(credited[0] or 0)
            remaining_vat = int(line[2] or 0) - int(credited[1] or 0)
            if str(line[3] or "").upper() != currency:
                raise ValueError("Credit note line allocation currency does not match invoice.")
            if amounts["subtotal_minor"] > remaining_subtotal:
                raise ValueError("Credit note line allocation exceeds remaining line subtotal.")
            if amounts["vat_minor"] > remaining_vat:
                raise ValueError("Credit note line allocation exceeds remaining line VAT.")
            validated.append(
                {
                    "invoice_line_item_id": line_id,
                    "subtotal_minor": int(amounts["subtotal_minor"]),
                    "vat_minor": int(amounts["vat_minor"]),
                    "ledger_account_code": str(line[4] or "4100"),
                    "vat_treatment": str(line[5] or "standard"),
                    "vat_rate_basis_points": int(line[6] or 0),
                }
            )
        return tuple(validated)

    @staticmethod
    def _insert_line_allocations(
        cursor: sqlite3.Cursor,
        *,
        credit_note_id: int,
        line_allocations: tuple[dict[str, object], ...],
        currency: str,
    ) -> None:
        for allocation in line_allocations:
            subtotal = int(allocation["subtotal_minor"])
            vat = int(allocation["vat_minor"])
            cursor.execute(
                """
                INSERT INTO CreditNoteLineAllocations(
                    credit_note_id,
                    invoice_line_item_id,
                    subtotal_minor,
                    vat_minor,
                    total_minor,
                    currency
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    int(credit_note_id),
                    int(allocation["invoice_line_item_id"]),
                    subtotal,
                    vat,
                    subtotal + vat,
                    currency,
                ),
            )

    @staticmethod
    def _revenue_reversal_entries(
        *,
        credit_note_id: int,
        subtotal_minor: int,
        currency: str,
        fallback_account_code: str,
        line_allocations: tuple[dict[str, object], ...],
    ) -> list[LedgerEntryDraft]:
        if int(subtotal_minor) <= 0:
            return []
        by_account: dict[str, int] = {}
        if line_allocations:
            for allocation in line_allocations:
                account_code = str(allocation["ledger_account_code"] or "4100").strip() or "4100"
                by_account[account_code] = by_account.get(account_code, 0) + int(
                    allocation["subtotal_minor"]
                )
        else:
            account_code = str(fallback_account_code or "4100").strip() or "4100"
            by_account[account_code] = int(subtotal_minor)
        return [
            LedgerEntryDraft(
                account_code,
                currency,
                debit_minor=amount,
                source_type="credit_note",
                source_id=credit_note_id,
            )
            for account_code, amount in sorted(by_account.items())
            if amount > 0
        ]

    @staticmethod
    def _vat_reversal_entries(
        *,
        invoice_id: int,
        credit_note_id: int,
        vat_total_minor: int,
        currency: str,
        line_allocations: tuple[dict[str, object], ...],
        cursor: sqlite3.Cursor,
    ) -> list[LedgerEntryDraft]:
        if int(vat_total_minor) <= 0:
            return []
        if line_allocations:
            by_vat: dict[tuple[str, int], int] = {}
            for allocation in line_allocations:
                amount = int(allocation["vat_minor"])
                if amount <= 0:
                    continue
                key = (
                    str(allocation["vat_treatment"] or "standard"),
                    int(allocation["vat_rate_basis_points"] or 0),
                )
                by_vat[key] = by_vat.get(key, 0) + amount
            return [
                LedgerEntryDraft(
                    "2100",
                    currency,
                    debit_minor=amount,
                    vat_treatment=vat_treatment,
                    vat_rate_basis_points=vat_rate,
                    source_type="credit_note",
                    source_id=int(credit_note_id),
                )
                for (vat_treatment, vat_rate), amount in sorted(by_vat.items())
                if amount > 0
            ]
        rows = cursor.execute(
            """
            SELECT vat_treatment, vat_rate_basis_points, vat_amount_minor
            FROM InvoiceVatBreakdown
            WHERE invoice_id=? AND vat_amount_minor > 0
            ORDER BY vat_treatment, vat_rate_basis_points
            """,
            (int(invoice_id),),
        ).fetchall()
        if not rows:
            return [
                LedgerEntryDraft(
                    "2100",
                    currency,
                    debit_minor=int(vat_total_minor),
                    vat_treatment="standard",
                    source_type="credit_note",
                    source_id=int(credit_note_id),
                )
            ]
        source_total = sum(int(row[2] or 0) for row in rows)
        if source_total <= 0:
            return []
        allocated: list[LedgerEntryDraft] = []
        remaining = int(vat_total_minor)
        for index, row in enumerate(rows):
            if index == len(rows) - 1:
                amount = remaining
            else:
                amount = int(vat_total_minor) * int(row[2] or 0) // source_total
                remaining -= amount
            if amount <= 0:
                continue
            allocated.append(
                LedgerEntryDraft(
                    "2100",
                    currency,
                    debit_minor=amount,
                    vat_treatment=str(row[0] or "standard"),
                    vat_rate_basis_points=int(row[1] or 0),
                    source_type="credit_note",
                    source_id=int(credit_note_id),
                )
            )
        return allocated

    @staticmethod
    def _row_to_credit_note(row) -> CreditNoteRecord:
        if row[12] is None:
            raise RuntimeError("Credit note is missing its ledger transaction link.")
        return CreditNoteRecord(
            id=int(row[0]),
            credit_note_registry_entry_id=int(row[1]),
            credit_note_number=str(row[2] or ""),
            invoice_id=int(row[3]),
            party_id=int(row[4]),
            reason=str(row[5] or ""),
            status=str(row[6] or ""),
            issue_date=str(row[7] or ""),
            currency=str(row[8] or ""),
            subtotal_minor=int(row[9] or 0),
            vat_total_minor=int(row[10] or 0),
            total_minor=int(row[11] or 0),
            ledger_transaction_id=int(row[12]),
            idempotency_key=str(row[13] or ""),
            created_by=_clean_text(row[14]),
            created_at=_clean_text(row[15]),
        )

"""Ledger-backed reports for invoice and royalty accounting."""

from __future__ import annotations

import sqlite3
from datetime import date

from .invoice_service import InvoiceService
from .models import (
    DEFAULT_CURRENCY,
    ArtistPayoutReportRow,
    InvoiceSettlementSummary,
    LedgerAuditReportRow,
    OutstandingInvoiceReportRow,
    PartyBalanceReportRow,
    RevenueByCatalogServiceRow,
    VatSummaryReportRow,
)
from .money import normalize_currency
from .payment_service import InvoicePaymentService


def _clean_text(value: object | None) -> str | None:
    text = str(value or "").strip()
    return text or None


def _parse_date(value: str | None) -> date | None:
    clean = _clean_text(value)
    if clean is None:
        return None
    return date.fromisoformat(clean)


class InvoiceAccountingReportService:
    """Builds reports from ledger entries and immutable invoice snapshots."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.invoice_service = InvoiceService(conn)
        self.payment_service = InvoicePaymentService(conn)

    def invoice_settlement(
        self,
        invoice_id: int,
        *,
        as_of_date: str | None = None,
    ) -> InvoiceSettlementSummary:
        invoice = self.invoice_service.fetch_invoice(int(invoice_id))
        if invoice is None:
            raise ValueError(f"Invoice {int(invoice_id)} was not found.")
        paid = self._paid_total_minor(int(invoice.id))
        credited = self._credited_total_minor(int(invoice.id))
        balance = self.payment_service.invoice_receivable_balance_minor(
            int(invoice.id),
            currency=invoice.currency,
        )
        return InvoiceSettlementSummary(
            invoice_id=int(invoice.id),
            currency=invoice.currency,
            invoice_total_minor=invoice.total_minor,
            paid_minor=paid,
            credited_minor=credited,
            receivable_balance_minor=balance,
            payment_status=self._payment_status(
                invoice_total_minor=invoice.total_minor,
                paid_minor=paid,
                credited_minor=credited,
                receivable_balance_minor=balance,
            ),
            due_status=self._due_status(
                document_status=invoice.document_status,
                due_date=invoice.due_date,
                outstanding_minor=balance,
                as_of_date=as_of_date,
            ),
        )

    def outstanding_invoices(
        self,
        *,
        currency: str = DEFAULT_CURRENCY,
        as_of_date: str | None = None,
    ) -> list[OutstandingInvoiceReportRow]:
        clean_currency = normalize_currency(currency)
        rows = self.conn.execute(
            """
            SELECT id, invoice_number, party_id, total_minor, due_date
            FROM Invoices
            WHERE currency=?
              AND document_status IN ('issued', 'sent')
            ORDER BY due_date IS NULL, due_date, id
            """,
            (clean_currency,),
        ).fetchall()
        report_rows: list[OutstandingInvoiceReportRow] = []
        for row in rows:
            settlement = self.invoice_settlement(int(row[0]), as_of_date=as_of_date)
            if settlement.receivable_balance_minor <= 0:
                continue
            report_rows.append(
                OutstandingInvoiceReportRow(
                    invoice_id=int(row[0]),
                    invoice_number=_clean_text(row[1]),
                    party_id=int(row[2]),
                    currency=clean_currency,
                    total_minor=int(row[3] or 0),
                    outstanding_minor=settlement.receivable_balance_minor,
                    due_date=_clean_text(row[4]),
                    payment_status=settlement.payment_status,
                    due_status=settlement.due_status,
                )
            )
        return report_rows

    def party_balance_report(
        self,
        *,
        currency: str = DEFAULT_CURRENCY,
    ) -> list[PartyBalanceReportRow]:
        clean_currency = normalize_currency(currency)
        rows = self.conn.execute(
            """
            SELECT
                party_id,
                currency,
                COALESCE(SUM(COALESCE(debit_minor, 0) - COALESCE(credit_minor, 0)), 0)
            FROM AccountingEntries
            WHERE party_id IS NOT NULL AND currency=?
            GROUP BY party_id, currency
            ORDER BY party_id
            """,
            (clean_currency,),
        ).fetchall()
        return [
            PartyBalanceReportRow(
                party_id=int(row[0]) if row[0] is not None else None,
                currency=str(row[1] or clean_currency),
                balance_minor=int(row[2] or 0),
            )
            for row in rows
        ]

    def vat_summary_report(
        self,
        *,
        currency: str = DEFAULT_CURRENCY,
    ) -> list[VatSummaryReportRow]:
        clean_currency = normalize_currency(currency)
        rows = self.conn.execute(
            """
            SELECT
                e.vat_treatment,
                e.vat_rate_basis_points,
                e.currency,
                COALESCE(SUM(
                    CASE
                        WHEN a.code='2100'
                        THEN COALESCE(e.credit_minor, 0) - COALESCE(e.debit_minor, 0)
                        ELSE 0
                    END
                ), 0) AS vat_output_minor,
                COALESCE(SUM(
                    CASE
                        WHEN a.code='1200'
                        THEN COALESCE(e.debit_minor, 0) - COALESCE(e.credit_minor, 0)
                        ELSE 0
                    END
                ), 0) AS vat_input_minor
            FROM AccountingEntries e
            INNER JOIN AccountingAccounts a ON a.id=e.account_id
            WHERE a.code IN ('1200', '2100') AND e.currency=?
            GROUP BY e.vat_treatment, e.vat_rate_basis_points, e.currency
            ORDER BY e.vat_treatment, e.vat_rate_basis_points
            """,
            (clean_currency,),
        ).fetchall()
        return [
            VatSummaryReportRow(
                vat_treatment=_clean_text(row[0]),
                vat_rate_basis_points=int(row[1]) if row[1] is not None else None,
                currency=str(row[2] or clean_currency),
                vat_output_minor=int(row[3] or 0),
                vat_input_minor=int(row[4] or 0),
            )
            for row in rows
        ]

    def revenue_by_catalog_service(
        self,
        *,
        currency: str = DEFAULT_CURRENCY,
    ) -> list[RevenueByCatalogServiceRow]:
        clean_currency = normalize_currency(currency)
        rows = self.conn.execute(
            """
            SELECT
                li.catalog_item_id,
                li.catalog_item_name_snapshot,
                li.currency,
                COALESCE(SUM(li.net_amount_minor), 0)
            FROM InvoiceLineItems li
            INNER JOIN Invoices i ON i.id=li.invoice_id
            WHERE li.currency=?
              AND i.document_status IN ('issued', 'sent')
            GROUP BY li.catalog_item_id, li.catalog_item_name_snapshot, li.currency
            ORDER BY li.catalog_item_name_snapshot, li.catalog_item_id
            """,
            (clean_currency,),
        ).fetchall()
        return [
            RevenueByCatalogServiceRow(
                catalog_item_id=int(row[0]) if row[0] is not None else None,
                catalog_item_name=_clean_text(row[1]),
                currency=str(row[2] or clean_currency),
                net_amount_minor=int(row[3] or 0),
            )
            for row in rows
        ]

    def artist_payout_report(
        self,
        *,
        currency: str = DEFAULT_CURRENCY,
    ) -> list[ArtistPayoutReportRow]:
        clean_currency = normalize_currency(currency)
        rows = self.conn.execute(
            """
            SELECT
                e.party_id,
                e.currency,
                COALESCE(SUM(COALESCE(e.credit_minor, 0)), 0) AS posted,
                COALESCE(SUM(COALESCE(e.debit_minor, 0)), 0) AS paid_or_reversed
            FROM AccountingEntries e
            INNER JOIN AccountingAccounts a ON a.id=e.account_id
            WHERE a.code='2000'
              AND e.party_id IS NOT NULL
              AND e.currency=?
            GROUP BY e.party_id, e.currency
            ORDER BY e.party_id
            """,
            (clean_currency,),
        ).fetchall()
        return [
            ArtistPayoutReportRow(
                party_id=int(row[0]),
                currency=str(row[1] or clean_currency),
                payable_posted_minor=int(row[2] or 0),
                payout_paid_minor=int(row[3] or 0),
                payable_balance_minor=int(row[2] or 0) - int(row[3] or 0),
            )
            for row in rows
        ]

    def ledger_audit_report(self) -> list[LedgerAuditReportRow]:
        rows = self.conn.execute("""
            SELECT
                t.id,
                t.transaction_type,
                t.posted_at,
                t.transaction_number,
                t.command_key,
                t.created_by,
                a.code,
                e.party_id,
                e.debit_minor,
                e.credit_minor,
                e.currency,
                e.source_type,
                e.source_id
            FROM AccountingEntries e
            INNER JOIN AccountingTransactions t ON t.id=e.transaction_id
            INNER JOIN AccountingAccounts a ON a.id=e.account_id
            ORDER BY t.posted_at, t.id, e.id
            """).fetchall()
        return [
            LedgerAuditReportRow(
                transaction_id=int(row[0]),
                transaction_type=str(row[1] or ""),
                posted_at=str(row[2] or ""),
                transaction_number=_clean_text(row[3]),
                command_key=_clean_text(row[4]),
                created_by=_clean_text(row[5]),
                account_code=str(row[6] or ""),
                party_id=int(row[7]) if row[7] is not None else None,
                debit_minor=int(row[8]) if row[8] is not None else None,
                credit_minor=int(row[9]) if row[9] is not None else None,
                currency=str(row[10] or ""),
                source_type=_clean_text(row[11]),
                source_id=_clean_text(row[12]),
            )
            for row in rows
        ]

    def _paid_total_minor(self, invoice_id: int) -> int:
        row = self.conn.execute(
            """
            SELECT COALESCE(SUM(amount_minor), 0)
            FROM InvoicePayments
            WHERE invoice_id=?
            """,
            (int(invoice_id),),
        ).fetchone()
        return int(row[0] or 0)

    def _credited_total_minor(self, invoice_id: int) -> int:
        row = self.conn.execute(
            """
            SELECT COALESCE(SUM(total_minor), 0)
            FROM CreditNotes
            WHERE invoice_id=? AND status='issued'
            """,
            (int(invoice_id),),
        ).fetchone()
        return int(row[0] or 0)

    @staticmethod
    def _payment_status(
        *,
        invoice_total_minor: int,
        paid_minor: int,
        credited_minor: int,
        receivable_balance_minor: int,
    ) -> str:
        if int(receivable_balance_minor) < 0:
            return "overpaid"
        if int(receivable_balance_minor) == 0 and int(credited_minor) >= int(invoice_total_minor):
            return "credited"
        if int(receivable_balance_minor) == 0:
            return "paid"
        if (
            int(receivable_balance_minor) >= int(invoice_total_minor)
            and not paid_minor
            and not credited_minor
        ):
            return "unpaid"
        return "partially_paid"

    @staticmethod
    def _due_status(
        *,
        document_status: str,
        due_date: str | None,
        outstanding_minor: int,
        as_of_date: str | None,
    ) -> str:
        if document_status in {"voided", "credited", "cancelled"} or int(outstanding_minor) <= 0:
            return "not_due"
        due = _parse_date(due_date)
        if due is None:
            return "not_due"
        as_of = _parse_date(as_of_date) or date.today()
        if due < as_of:
            return "overdue"
        if due == as_of:
            return "due_today"
        return "not_due"

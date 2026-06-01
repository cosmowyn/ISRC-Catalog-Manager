"""Invoice draft and issue orchestration backed by the accounting ledger."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager

from isrc_manager.code_registry import BUILTIN_CATEGORY_INVOICE_NUMBER, CodeRegistryService

from .catalog_service import InvoiceCatalogService
from .command_log import FinancialCommandLogService
from .ledger_service import LedgerPostingService
from .models import (
    DEFAULT_CURRENCY,
    VAT_TREATMENT_STANDARD,
    AccountingTransactionLinkDraft,
    InvoiceDraftPayload,
    InvoiceLinePayload,
    InvoiceRecord,
    LedgerEntryDraft,
    Quantity,
)
from .money import (
    calculate_vat_minor,
    line_net_amount_minor,
    normalize_currency,
    normalize_vat_treatment,
    parse_quantity,
)


def _clean_text(value: object | None) -> str | None:
    text = str(value or "").strip()
    return text or None


class InvoiceService:
    """Owns invoice drafts and issue-time ledger posting."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.catalog_service = InvoiceCatalogService(conn)
        self.code_registry = CodeRegistryService(conn)
        self.command_log = FinancialCommandLogService(conn)
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

    def create_draft_invoice(self, payload: InvoiceDraftPayload) -> InvoiceRecord:
        currency = normalize_currency(payload.currency)
        line_rows = [self._line_row(line, currency=currency) for line in payload.lines]
        subtotal = sum(int(row["net_amount_minor"]) for row in line_rows)
        vat_total = sum(int(row["vat_amount_minor"]) for row in line_rows)
        total = sum(int(row["gross_amount_minor"]) for row in line_rows)
        with self.conn:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                INSERT INTO Invoices(
                    party_id,
                    invoice_type,
                    document_status,
                    issue_date,
                    due_date,
                    currency,
                    seller_vat_id_snapshot,
                    buyer_vat_id_snapshot,
                    vat_treatment_summary,
                    subtotal_minor,
                    vat_total_minor,
                    total_minor,
                    created_by
                )
                VALUES (?, ?, 'draft', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(payload.party_id),
                    str(payload.invoice_type or "venue_invoice").strip() or "venue_invoice",
                    _clean_text(payload.issue_date),
                    _clean_text(payload.due_date),
                    currency,
                    _clean_text(payload.seller_vat_id_snapshot),
                    _clean_text(payload.buyer_vat_id_snapshot),
                    _clean_text(payload.vat_treatment_summary),
                    int(subtotal),
                    int(vat_total),
                    int(total),
                    _clean_text(payload.created_by),
                ),
            )
            invoice_id = int(cursor.lastrowid)
            cursor.execute(
                "UPDATE Invoices SET draft_display_id=? WHERE id=?",
                (f"DRAFT-{invoice_id:06d}", invoice_id),
            )
            self._insert_line_rows(cursor, invoice_id=invoice_id, rows=line_rows)
            self._replace_vat_breakdown(cursor, invoice_id=invoice_id)
        record = self.fetch_invoice(invoice_id)
        if record is None:
            raise RuntimeError("Invoice draft could not be reloaded.")
        return record

    def issue_invoice(
        self,
        invoice_id: int,
        *,
        command_key: str,
        created_by: str | None = None,
    ) -> InvoiceRecord:
        clean_command_key = str(command_key or "").strip()
        if not clean_command_key:
            raise ValueError("Issue invoice command key is required.")
        with self._immediate_transaction() as cursor:
            existing = self.command_log.fetch(clean_command_key)
            if existing is not None and existing.status == "completed":
                if existing.source_type != "invoice" or existing.source_id != str(int(invoice_id)):
                    raise ValueError(
                        f"Financial command {clean_command_key!r} belongs to another source."
                    )
                record = self.fetch_invoice(invoice_id)
                if record is None:
                    raise RuntimeError("Completed issue command points to a missing invoice.")
                return record
            invoice = self.fetch_invoice(invoice_id)
            if invoice is None:
                raise ValueError(f"Invoice {int(invoice_id)} was not found.")
            if invoice.document_status != "draft":
                raise ValueError("Only draft invoices can be issued.")
            if invoice.total_minor <= 0:
                raise ValueError("Invoice total must be greater than zero before issue.")
            result = self.code_registry.generate_next_code(
                system_key=BUILTIN_CATEGORY_INVOICE_NUMBER,
                created_via="invoice.issue",
                cursor=cursor,
            )
            cursor.execute(
                """
                UPDATE Invoices
                SET invoice_registry_entry_id=?,
                    invoice_number=?,
                    document_status='issued',
                    issue_date=COALESCE(issue_date, date('now')),
                    updated_at=datetime('now')
                WHERE id=? AND document_status='draft' AND invoice_number IS NULL
                """,
                (int(result.entry.id), result.entry.value, int(invoice_id)),
            )
            if cursor.rowcount != 1:
                raise ValueError("Invoice could not be issued because it changed concurrently.")
            issued = self.fetch_invoice(invoice_id)
            if issued is None:
                raise RuntimeError("Issued invoice could not be reloaded.")
            transaction = self.ledger.post_transaction(
                command_key=clean_command_key,
                transaction_type="invoice_issue",
                source_type="invoice",
                source_id=int(invoice_id),
                created_by=created_by,
                memo=f"Issue invoice {issued.invoice_number}",
                cursor=cursor,
                links=(
                    AccountingTransactionLinkDraft(
                        source_type="invoice",
                        source_id=int(invoice_id),
                        relation_type="invoice_issue",
                    ),
                ),
                entries=tuple(self._issue_entries(issued)),
            )
            cursor.execute(
                """
                UPDATE Invoices
                SET issued_ledger_transaction_id=?,
                    updated_at=datetime('now')
                WHERE id=?
                """,
                (int(transaction.id), int(invoice_id)),
            )
        record = self.fetch_invoice(invoice_id)
        if record is None:
            raise RuntimeError("Issued invoice could not be reloaded.")
        return record

    def void_issued_invoice(
        self,
        invoice_id: int,
        *,
        command_key: str,
        created_by: str | None = None,
        memo: str | None = None,
    ) -> InvoiceRecord:
        clean_command_key = str(command_key or "").strip()
        if not clean_command_key:
            raise ValueError("Void invoice command key is required.")
        with self._immediate_transaction() as cursor:
            existing = self.command_log.fetch(clean_command_key)
            if existing is not None and existing.status == "completed":
                if existing.source_type != "invoice" or existing.source_id != str(int(invoice_id)):
                    raise ValueError(
                        f"Financial command {clean_command_key!r} belongs to another source."
                    )
                record = self.fetch_invoice(invoice_id)
                if record is None:
                    raise RuntimeError("Completed void command points to a missing invoice.")
                return record
            invoice = self.fetch_invoice(invoice_id)
            if invoice is None:
                raise ValueError(f"Invoice {int(invoice_id)} was not found.")
            if invoice.document_status not in {"issued", "sent"}:
                raise ValueError("Only issued or sent invoices can be voided.")
            if invoice.issued_ledger_transaction_id is None:
                raise ValueError("Invoice has no issue ledger transaction to reverse.")
            receivable_balance = self._invoice_receivable_balance_minor(
                invoice.id,
                currency=invoice.currency,
                cursor=cursor,
            )
            if receivable_balance != invoice.total_minor:
                raise ValueError(
                    "Only unsettled invoices can be voided; use credit or correction flows instead."
                )
            transaction = self.ledger.post_transaction(
                command_key=clean_command_key,
                transaction_type="invoice_void",
                source_type="invoice",
                source_id=int(invoice.id),
                created_by=created_by,
                memo=_clean_text(memo) or f"Void invoice {invoice.invoice_number}",
                cursor=cursor,
                reversal_of_transaction_id=int(invoice.issued_ledger_transaction_id),
                links=(
                    AccountingTransactionLinkDraft(
                        source_type="invoice",
                        source_id=int(invoice.id),
                        relation_type="invoice_void",
                    ),
                    AccountingTransactionLinkDraft(
                        source_type="accounting_transaction",
                        source_id=int(invoice.issued_ledger_transaction_id),
                        relation_type="reversal",
                    ),
                ),
                entries=tuple(
                    self._reversal_entries_for_transaction(
                        int(invoice.issued_ledger_transaction_id)
                    )
                ),
            )
            if transaction.reversal_of_transaction_id != invoice.issued_ledger_transaction_id:
                raise RuntimeError("Invoice void reversal did not link to the issue transaction.")
            cursor.execute(
                """
                UPDATE Invoices
                SET document_status='voided',
                    updated_at=datetime('now')
                WHERE id=? AND document_status IN ('issued', 'sent')
                """,
                (int(invoice.id),),
            )
            if cursor.rowcount != 1:
                raise ValueError("Invoice could not be voided because it changed concurrently.")
        record = self.fetch_invoice(invoice_id)
        if record is None:
            raise RuntimeError("Voided invoice could not be reloaded.")
        return record

    def fetch_invoice(self, invoice_id: int) -> InvoiceRecord | None:
        row = self.conn.execute(
            """
            SELECT
                id,
                draft_display_id,
                invoice_registry_entry_id,
                invoice_number,
                party_id,
                invoice_type,
                document_status,
                issue_date,
                due_date,
                currency,
                subtotal_minor,
                vat_total_minor,
                total_minor,
                issued_ledger_transaction_id
            FROM Invoices
            WHERE id=?
            """,
            (int(invoice_id),),
        ).fetchone()
        if not row:
            return None
        return InvoiceRecord(
            id=int(row[0]),
            draft_display_id=_clean_text(row[1]),
            invoice_registry_entry_id=int(row[2]) if row[2] is not None else None,
            invoice_number=_clean_text(row[3]),
            party_id=int(row[4]),
            invoice_type=str(row[5] or ""),
            document_status=str(row[6] or ""),
            issue_date=_clean_text(row[7]),
            due_date=_clean_text(row[8]),
            currency=str(row[9] or DEFAULT_CURRENCY),
            subtotal_minor=int(row[10] or 0),
            vat_total_minor=int(row[11] or 0),
            total_minor=int(row[12] or 0),
            issued_ledger_transaction_id=int(row[13]) if row[13] is not None else None,
        )

    def preview_invoice_line(
        self,
        payload: InvoiceLinePayload,
        *,
        currency: str = DEFAULT_CURRENCY,
    ) -> dict[str, object]:
        """Return the same deterministic line calculation used when saving drafts."""

        return self._line_row(payload, currency=normalize_currency(currency))

    def _line_row(self, payload: InvoiceLinePayload, *, currency: str) -> dict[str, object]:
        catalog_item = (
            self.catalog_service.fetch_item(int(payload.catalog_item_id))
            if payload.catalog_item_id is not None
            else None
        )
        if payload.catalog_item_id is not None and catalog_item is None:
            raise ValueError(f"Invoice catalog item {int(payload.catalog_item_id)} was not found.")
        if catalog_item is not None and not catalog_item.active:
            raise ValueError(f"Invoice catalog item {int(catalog_item.id)} is inactive.")
        description = _clean_text(payload.description)
        if description is None and catalog_item is not None:
            description = catalog_item.description or catalog_item.name
        if description is None:
            raise ValueError("Invoice line description is required.")
        quantity = (
            payload.quantity
            if isinstance(payload.quantity, Quantity)
            else parse_quantity(payload.quantity)
        )
        unit_price = int(
            catalog_item.default_unit_price_minor
            if catalog_item is not None and int(payload.unit_price_minor) == 0
            else payload.unit_price_minor
        )
        vat_treatment = normalize_vat_treatment(
            catalog_item.default_vat_treatment
            if catalog_item is not None and payload.vat_treatment == VAT_TREATMENT_STANDARD
            else payload.vat_treatment
        )
        vat_rate = int(
            catalog_item.default_vat_rate_basis_points
            if catalog_item is not None and int(payload.vat_rate_basis_points) == 0
            else payload.vat_rate_basis_points
        )
        line_currency = normalize_currency(
            catalog_item.currency if catalog_item is not None else currency
        )
        if line_currency != currency:
            raise ValueError("All invoice lines must use the invoice currency.")
        net = line_net_amount_minor(unit_price, quantity)
        vat = calculate_vat_minor(net, vat_rate, vat_treatment=vat_treatment)
        return {
            "catalog_item_id": catalog_item.id if catalog_item is not None else None,
            "catalog_item_name_snapshot": catalog_item.name if catalog_item is not None else None,
            "description": description,
            "quantity_value": quantity.value,
            "quantity_scale": quantity.scale,
            "unit_price_minor": unit_price,
            "vat_treatment": vat_treatment,
            "vat_rate_basis_points": vat_rate,
            "vat_country_code": _clean_text(payload.vat_country_code)
            or (catalog_item.vat_country_code if catalog_item is not None else None),
            "net_amount_minor": net,
            "vat_amount_minor": vat,
            "gross_amount_minor": net + vat,
            "currency": currency,
            "ledger_account_code": _clean_text(payload.ledger_account_code)
            or (catalog_item.default_account_code if catalog_item is not None else None)
            or "4100",
            "source_type": _clean_text(payload.source_type),
            "source_id": _clean_text(payload.source_id),
        }

    @staticmethod
    def _insert_line_rows(
        cursor: sqlite3.Cursor,
        *,
        invoice_id: int,
        rows: list[dict[str, object]],
    ) -> None:
        for sort_order, row in enumerate(rows, start=1):
            cursor.execute(
                """
                INSERT INTO InvoiceLineItems(
                    invoice_id,
                    catalog_item_id,
                    catalog_item_name_snapshot,
                    description,
                    quantity_value,
                    quantity_scale,
                    unit_price_minor,
                    vat_treatment,
                    vat_rate_basis_points,
                    vat_country_code,
                    net_amount_minor,
                    vat_amount_minor,
                    gross_amount_minor,
                    currency,
                    ledger_account_code,
                    source_type,
                    source_id,
                    sort_order
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(invoice_id),
                    row["catalog_item_id"],
                    row["catalog_item_name_snapshot"],
                    row["description"],
                    row["quantity_value"],
                    row["quantity_scale"],
                    row["unit_price_minor"],
                    row["vat_treatment"],
                    row["vat_rate_basis_points"],
                    row["vat_country_code"],
                    row["net_amount_minor"],
                    row["vat_amount_minor"],
                    row["gross_amount_minor"],
                    row["currency"],
                    row["ledger_account_code"],
                    row["source_type"],
                    row["source_id"],
                    sort_order,
                ),
            )

    @staticmethod
    def _replace_vat_breakdown(cursor: sqlite3.Cursor, *, invoice_id: int) -> None:
        cursor.execute("DELETE FROM InvoiceVatBreakdown WHERE invoice_id=?", (int(invoice_id),))
        cursor.execute(
            """
            INSERT INTO InvoiceVatBreakdown(
                invoice_id,
                vat_treatment,
                vat_rate_basis_points,
                taxable_amount_minor,
                vat_amount_minor,
                gross_amount_minor,
                currency
            )
            SELECT
                invoice_id,
                vat_treatment,
                vat_rate_basis_points,
                SUM(net_amount_minor),
                SUM(vat_amount_minor),
                SUM(gross_amount_minor),
                currency
            FROM InvoiceLineItems
            WHERE invoice_id=?
            GROUP BY invoice_id, vat_treatment, vat_rate_basis_points, currency
            """,
            (int(invoice_id),),
        )

    def _issue_entries(self, invoice: InvoiceRecord) -> list[LedgerEntryDraft]:
        revenue_rows = self.conn.execute(
            """
            SELECT ledger_account_code, SUM(net_amount_minor)
            FROM InvoiceLineItems
            WHERE invoice_id=?
            GROUP BY ledger_account_code
            """,
            (int(invoice.id),),
        ).fetchall()
        vat_rows = self.conn.execute(
            """
            SELECT vat_treatment, vat_rate_basis_points, vat_amount_minor
            FROM InvoiceVatBreakdown
            WHERE invoice_id=? AND vat_amount_minor > 0
            ORDER BY vat_treatment, vat_rate_basis_points
            """,
            (int(invoice.id),),
        ).fetchall()
        entries = [
            LedgerEntryDraft(
                "1100",
                invoice.currency,
                debit_minor=invoice.total_minor,
                party_id=invoice.party_id,
                source_type="invoice",
                source_id=invoice.id,
            )
        ]
        for row in revenue_rows:
            entries.append(
                LedgerEntryDraft(
                    str(row[0] or "4000"),
                    invoice.currency,
                    credit_minor=int(row[1] or 0),
                    source_type="invoice",
                    source_id=invoice.id,
                )
            )
        for row in vat_rows:
            entries.append(
                LedgerEntryDraft(
                    "2100",
                    invoice.currency,
                    credit_minor=int(row[2] or 0),
                    vat_treatment=str(row[0] or VAT_TREATMENT_STANDARD),
                    vat_rate_basis_points=int(row[1] or 0),
                    source_type="invoice",
                    source_id=invoice.id,
                )
            )
        return entries

    def _reversal_entries_for_transaction(self, transaction_id: int) -> list[LedgerEntryDraft]:
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
            (int(transaction_id),),
        ).fetchall()
        if not rows:
            raise ValueError(f"Ledger transaction {int(transaction_id)} has no entries.")
        return [
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

    def _invoice_receivable_balance_minor(
        self,
        invoice_id: int,
        *,
        currency: str,
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
            (currency, str(int(invoice_id))),
        ).fetchone()
        return int(row[0] or 0)

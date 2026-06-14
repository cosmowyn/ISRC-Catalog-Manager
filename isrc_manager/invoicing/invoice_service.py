"""Invoice draft and issue orchestration backed by the accounting ledger."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from isrc_manager.code_registry import BUILTIN_CATEGORY_INVOICE_NUMBER, CodeRegistryService

from .command_log import FinancialCommandLogService
from .currencies import currency_for_country
from .ledger_service import LedgerPostingService
from .models import (
    DEFAULT_CURRENCY,
    VAT_TREATMENT_STANDARD,
    AccountingTransactionLinkDraft,
    InvoiceCatalogCategoryPayload,
    InvoiceCatalogCategoryRecord,
    InvoiceCatalogItemPayload,
    InvoiceCatalogItemRecord,
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


DEFAULT_INVOICE_CATALOG_CATEGORIES = (
    "Services",
    "Goods",
    "Travel",
    "Licensing",
    "Royalties",
)


def ensure_default_invoice_catalog_categories(conn: sqlite3.Connection) -> None:
    for name in DEFAULT_INVOICE_CATALOG_CATEGORIES:
        conn.execute(
            """
            INSERT INTO InvoiceCatalogCategories(name, active)
            VALUES (?, 1)
            ON CONFLICT(name) DO NOTHING
            """,
            (name,),
        )


class InvoiceCatalogCategoryService:
    """Maintains reusable invoice catalog category values."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def list_categories(self, *, active_only: bool = False) -> list[InvoiceCatalogCategoryRecord]:
        where_sql = "WHERE active=1" if active_only else ""
        rows = self.conn.execute(f"""
            SELECT id, name, active, created_at, updated_at
            FROM InvoiceCatalogCategories
            {where_sql}
            ORDER BY active DESC, name COLLATE NOCASE, id
            """).fetchall()
        return [self._row_to_record(row) for row in rows]

    def fetch_category(self, category_id: int) -> InvoiceCatalogCategoryRecord | None:
        row = self.conn.execute(
            """
            SELECT id, name, active, created_at, updated_at
            FROM InvoiceCatalogCategories
            WHERE id=?
            """,
            (int(category_id),),
        ).fetchone()
        return self._row_to_record(row) if row else None

    def ensure_category(self, name: str | None) -> InvoiceCatalogCategoryRecord | None:
        clean_name = _clean_text(name)
        if clean_name is None:
            return None
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO InvoiceCatalogCategories(name, active)
                VALUES (?, 1)
                ON CONFLICT(name) DO UPDATE SET active=1, updated_at=datetime('now')
                """,
                (clean_name,),
            )
        row = self.conn.execute(
            """
            SELECT id, name, active, created_at, updated_at
            FROM InvoiceCatalogCategories
            WHERE name=?
            """,
            (clean_name,),
        ).fetchone()
        return self._row_to_record(row) if row else None

    def create_category(self, payload: InvoiceCatalogCategoryPayload) -> int:
        clean_name = _clean_text(payload.name)
        if clean_name is None:
            raise ValueError("Catalog category name is required.")
        with self.conn:
            cur = self.conn.execute(
                """
                INSERT INTO InvoiceCatalogCategories(name, active)
                VALUES (?, ?)
                """,
                (clean_name, 1 if payload.active else 0),
            )
            return int(cur.lastrowid)

    def update_category(
        self, category_id: int, payload: InvoiceCatalogCategoryPayload
    ) -> InvoiceCatalogCategoryRecord:
        clean_name = _clean_text(payload.name)
        if clean_name is None:
            raise ValueError("Catalog category name is required.")
        with self.conn:
            cur = self.conn.execute(
                """
                UPDATE InvoiceCatalogCategories
                SET name=?, active=?, updated_at=datetime('now')
                WHERE id=?
                """,
                (clean_name, 1 if payload.active else 0, int(category_id)),
            )
            if cur.rowcount != 1:
                raise ValueError(f"Catalog category {int(category_id)} was not found.")
        record = self.fetch_category(category_id)
        if record is None:
            raise RuntimeError("Catalog category could not be reloaded.")
        return record

    @staticmethod
    def _row_to_record(row) -> InvoiceCatalogCategoryRecord:
        return InvoiceCatalogCategoryRecord(
            id=int(row[0]),
            name=str(row[1] or ""),
            active=bool(row[2]),
            created_at=_clean_text(row[3]),
            updated_at=_clean_text(row[4]),
        )


class InvoiceCatalogService:
    """Maintains billable catalog services and default costs."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    @staticmethod
    def _payload_quantity(payload: InvoiceCatalogItemPayload) -> Quantity:
        quantity = payload.default_quantity
        return quantity if isinstance(quantity, Quantity) else parse_quantity(quantity)

    @staticmethod
    def _payload_currency(payload: InvoiceCatalogItemPayload) -> str:
        inferred = currency_for_country(payload.vat_country_code)
        return normalize_currency(payload.currency or inferred or DEFAULT_CURRENCY)

    def create_item(self, payload: InvoiceCatalogItemPayload) -> int:
        clean_name = _clean_text(payload.name)
        if clean_name is None:
            raise ValueError("Catalog item name is required.")
        quantity = self._payload_quantity(payload)
        if int(payload.default_unit_price_minor) < 0:
            raise ValueError("Default unit price must be non-negative.")
        if int(payload.default_vat_rate_basis_points) < 0:
            raise ValueError("Default VAT rate must be non-negative.")
        InvoiceCatalogCategoryService(self.conn).ensure_category(payload.category)
        with self.conn:
            cur = self.conn.execute(
                """
                INSERT INTO InvoiceCatalogItems(
                    name,
                    description,
                    default_quantity_value,
                    default_quantity_scale,
                    default_unit_price_minor,
                    default_vat_treatment,
                    default_vat_rate_basis_points,
                    vat_country_code,
                    currency,
                    category,
                    default_account_code,
                    active
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    clean_name,
                    _clean_text(payload.description),
                    int(quantity.value),
                    int(quantity.scale),
                    int(payload.default_unit_price_minor),
                    normalize_vat_treatment(payload.default_vat_treatment),
                    int(payload.default_vat_rate_basis_points),
                    _clean_text(payload.vat_country_code),
                    self._payload_currency(payload),
                    _clean_text(payload.category),
                    _clean_text(payload.default_account_code),
                    1 if payload.active else 0,
                ),
            )
            return int(cur.lastrowid)

    def update_item(
        self, item_id: int, payload: InvoiceCatalogItemPayload
    ) -> InvoiceCatalogItemRecord:
        clean_name = _clean_text(payload.name)
        if clean_name is None:
            raise ValueError("Catalog item name is required.")
        quantity = self._payload_quantity(payload)
        if int(payload.default_unit_price_minor) < 0:
            raise ValueError("Default unit price must be non-negative.")
        if int(payload.default_vat_rate_basis_points) < 0:
            raise ValueError("Default VAT rate must be non-negative.")
        InvoiceCatalogCategoryService(self.conn).ensure_category(payload.category)
        with self.conn:
            cur = self.conn.execute(
                """
                UPDATE InvoiceCatalogItems
                SET name=?,
                    description=?,
                    default_quantity_value=?,
                    default_quantity_scale=?,
                    default_unit_price_minor=?,
                    default_vat_treatment=?,
                    default_vat_rate_basis_points=?,
                    vat_country_code=?,
                    currency=?,
                    category=?,
                    default_account_code=?,
                    active=?,
                    updated_at=datetime('now')
                WHERE id=?
                """,
                (
                    clean_name,
                    _clean_text(payload.description),
                    int(quantity.value),
                    int(quantity.scale),
                    int(payload.default_unit_price_minor),
                    normalize_vat_treatment(payload.default_vat_treatment),
                    int(payload.default_vat_rate_basis_points),
                    _clean_text(payload.vat_country_code),
                    self._payload_currency(payload),
                    _clean_text(payload.category),
                    _clean_text(payload.default_account_code),
                    1 if payload.active else 0,
                    int(item_id),
                ),
            )
            if cur.rowcount != 1:
                raise ValueError(f"Invoice catalog item {int(item_id)} was not found.")
        record = self.fetch_item(item_id)
        if record is None:
            raise RuntimeError("Invoice catalog item could not be reloaded.")
        return record

    def list_items(self, *, active_only: bool = False) -> list[InvoiceCatalogItemRecord]:
        where_sql = "WHERE active=1" if active_only else ""
        rows = self.conn.execute(f"""
            SELECT
                id,
                name,
                description,
                default_quantity_value,
                default_quantity_scale,
                default_unit_price_minor,
                default_vat_treatment,
                default_vat_rate_basis_points,
                vat_country_code,
                currency,
                category,
                default_account_code,
                active,
                created_at,
                updated_at
            FROM InvoiceCatalogItems
            {where_sql}
            ORDER BY active DESC, COALESCE(category, ''), name, id
            """).fetchall()
        return [self._row_to_record(row) for row in rows]

    def fetch_item(self, item_id: int) -> InvoiceCatalogItemRecord | None:
        row = self.conn.execute(
            """
            SELECT
                id,
                name,
                description,
                default_quantity_value,
                default_quantity_scale,
                default_unit_price_minor,
                default_vat_treatment,
                default_vat_rate_basis_points,
                vat_country_code,
                currency,
                category,
                default_account_code,
                active,
                created_at,
                updated_at
            FROM InvoiceCatalogItems
            WHERE id=?
            """,
            (int(item_id),),
        ).fetchone()
        if not row:
            return None
        return self._row_to_record(row)

    @staticmethod
    def _row_to_record(row) -> InvoiceCatalogItemRecord:
        return InvoiceCatalogItemRecord(
            id=int(row[0]),
            name=str(row[1] or ""),
            description=_clean_text(row[2]),
            default_quantity_value=int(row[3] or 1),
            default_quantity_scale=int(row[4] or 0),
            default_unit_price_minor=int(row[5] or 0),
            default_vat_treatment=str(row[6] or ""),
            default_vat_rate_basis_points=int(row[7] or 0),
            vat_country_code=_clean_text(row[8]),
            currency=str(row[9] or ""),
            category=_clean_text(row[10]),
            default_account_code=_clean_text(row[11]),
            active=bool(row[12]),
            created_at=_clean_text(row[13]),
            updated_at=_clean_text(row[14]),
        )


class InvoiceService:
    """Owns invoice drafts and issue-time ledger posting."""

    def __init__(self, conn: sqlite3.Connection, *, data_root: str | Path | None = None):
        self.conn = conn
        self.data_root = Path(data_root).resolve() if data_root is not None else None
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
        registry_entry_id: int | None = None,
        invoice_number: str | None = None,
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
            if registry_entry_id is None:
                result = self.code_registry.generate_next_code(
                    system_key=BUILTIN_CATEGORY_INVOICE_NUMBER,
                    created_via="invoice.issue",
                    cursor=cursor,
                )
                clean_registry_entry_id = int(result.entry.id)
                clean_invoice_number = result.entry.value
            else:
                entry = self.code_registry.fetch_entry(int(registry_entry_id))
                if entry is None:
                    raise ValueError(
                        f"Invoice registry entry {int(registry_entry_id)} was not found."
                    )
                if entry.category_system_key != BUILTIN_CATEGORY_INVOICE_NUMBER:
                    raise ValueError("Selected registry entry is not an invoice number.")
                clean_registry_entry_id = int(entry.id)
                clean_invoice_number = _clean_text(invoice_number) or entry.value
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
                (clean_registry_entry_id, clean_invoice_number, int(invoice_id)),
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

    def purge_invoice_for_cleanup(self, invoice_id: int) -> dict[str, int]:
        """Hard-delete an invoice and dependent accounting rows for local cleanup.

        This is intentionally separate from business correction workflows such as voids,
        credit notes, and payments. It exists for removing test or accidental records
        from a local profile when the ledger would otherwise be polluted.
        """

        invoice = self.fetch_invoice(int(invoice_id))
        if invoice is None:
            raise ValueError(f"Invoice {int(invoice_id)} was not found.")
        with self._immediate_transaction() as cursor:
            cursor.execute(
                """
                INSERT OR REPLACE INTO AccountingMaintenanceBypass(scope, reason, created_at)
                VALUES ('invoice_cleanup', ?, datetime('now'))
                """,
                (f"purge invoice {int(invoice_id)}",),
            )
            payment_ids = self._ids_for_query(
                cursor,
                "SELECT id FROM InvoicePayments WHERE invoice_id=?",
                (int(invoice_id),),
            )
            credit_note_ids = self._ids_for_query(
                cursor,
                "SELECT id FROM CreditNotes WHERE invoice_id=?",
                (int(invoice_id),),
            )
            snapshot_ids = self._ids_for_query(
                cursor,
                "SELECT id FROM InvoiceTemplateResolvedSnapshots WHERE invoice_id=?",
                (int(invoice_id),),
            )
            artifact_ids = self._invoice_cleanup_artifact_ids(
                cursor,
                invoice_id=int(invoice_id),
                snapshot_ids=snapshot_ids,
            )
            transaction_ids = self._invoice_cleanup_transaction_ids(
                cursor,
                invoice_id=int(invoice_id),
                payment_ids=payment_ids,
                credit_note_ids=credit_note_ids,
                artifact_ids=artifact_ids,
            )
            command_keys = self._invoice_cleanup_command_keys(
                cursor,
                invoice_id=int(invoice_id),
                payment_ids=payment_ids,
                credit_note_ids=credit_note_ids,
                transaction_ids=transaction_ids,
            )
            managed_paths = self._invoice_cleanup_managed_paths(cursor, artifact_ids)

            self._delete_ids(cursor, "InvoiceOutputArtifacts", artifact_ids)
            self._delete_ids(cursor, "InvoiceTemplateResolvedSnapshots", snapshot_ids)
            cursor.execute(
                "DELETE FROM InvoiceManualSymbols WHERE invoice_id=?", (int(invoice_id),)
            )
            self._delete_children_for_ids(
                cursor,
                "CreditNoteLineAllocations",
                "credit_note_id",
                credit_note_ids,
            )
            self._delete_ids(cursor, "CreditNotes", credit_note_ids)
            self._delete_ids(cursor, "InvoicePayments", payment_ids)
            cursor.execute("DELETE FROM InvoiceVatBreakdown WHERE invoice_id=?", (int(invoice_id),))
            cursor.execute("DELETE FROM InvoiceLineItems WHERE invoice_id=?", (int(invoice_id),))
            cursor.execute("DELETE FROM Invoices WHERE id=?", (int(invoice_id),))
            if cursor.rowcount != 1:
                raise RuntimeError("Invoice cleanup did not remove the selected invoice.")

            if transaction_ids:
                placeholders = ",".join("?" for _ in transaction_ids)
                cursor.execute(
                    f"""
                    UPDATE AccountingTransactions
                    SET reversal_of_transaction_id=NULL
                    WHERE id IN ({placeholders})
                    """,
                    tuple(transaction_ids),
                )
                cursor.execute(
                    f"DELETE FROM AccountingEntries WHERE transaction_id IN ({placeholders})",
                    tuple(transaction_ids),
                )
                cursor.execute(
                    f"DELETE FROM AccountingTransactionLinks WHERE transaction_id IN ({placeholders})",
                    tuple(transaction_ids),
                )
                cursor.execute(
                    f"DELETE FROM AccountingTransactions WHERE id IN ({placeholders})",
                    tuple(transaction_ids),
                )
            if command_keys:
                placeholders = ",".join("?" for _ in command_keys)
                cursor.execute(
                    f"DELETE FROM FinancialCommandLog WHERE command_key IN ({placeholders})",
                    tuple(command_keys),
                )
            cursor.execute("DELETE FROM AccountingMaintenanceBypass WHERE scope='invoice_cleanup'")

        for managed_path in managed_paths:
            try:
                managed_path.unlink(missing_ok=True)
            except OSError:
                pass
        return {
            "invoices": 1,
            "payments": len(payment_ids),
            "credit_notes": len(credit_note_ids),
            "artifacts": len(artifact_ids),
            "ledger_transactions": len(transaction_ids),
            "command_log_entries": len(command_keys),
            "managed_files": len(managed_paths),
        }

    @staticmethod
    def _ids_for_query(
        cursor: sqlite3.Cursor,
        sql: str,
        params: tuple[object, ...],
    ) -> list[int]:
        return [int(row[0]) for row in cursor.execute(sql, params).fetchall()]

    @staticmethod
    def _delete_ids(cursor: sqlite3.Cursor, table: str, ids: list[int]) -> None:
        if not ids:
            return
        placeholders = ",".join("?" for _ in ids)
        cursor.execute(f"DELETE FROM {table} WHERE id IN ({placeholders})", tuple(ids))

    @staticmethod
    def _delete_children_for_ids(
        cursor: sqlite3.Cursor,
        table: str,
        column: str,
        ids: list[int],
    ) -> None:
        if not ids:
            return
        placeholders = ",".join("?" for _ in ids)
        cursor.execute(f"DELETE FROM {table} WHERE {column} IN ({placeholders})", tuple(ids))

    def _invoice_cleanup_artifact_ids(
        self,
        cursor: sqlite3.Cursor,
        *,
        invoice_id: int,
        snapshot_ids: list[int],
    ) -> list[int]:
        artifact_ids = set(
            self._ids_for_query(
                cursor,
                "SELECT id FROM InvoiceOutputArtifacts WHERE invoice_id=?",
                (int(invoice_id),),
            )
        )
        if snapshot_ids:
            placeholders = ",".join("?" for _ in snapshot_ids)
            artifact_ids.update(
                self._ids_for_query(
                    cursor,
                    f"SELECT id FROM InvoiceOutputArtifacts WHERE snapshot_id IN ({placeholders})",
                    tuple(snapshot_ids),
                )
            )
        return sorted(artifact_ids)

    def _invoice_cleanup_transaction_ids(
        self,
        cursor: sqlite3.Cursor,
        *,
        invoice_id: int,
        payment_ids: list[int],
        credit_note_ids: list[int],
        artifact_ids: list[int],
    ) -> list[int]:
        transaction_ids = set(
            self._ids_for_query(
                cursor,
                """
                SELECT issued_ledger_transaction_id
                FROM Invoices
                WHERE id=? AND issued_ledger_transaction_id IS NOT NULL
                """,
                (int(invoice_id),),
            )
        )
        for table, column, ids in (
            ("InvoicePayments", "id", payment_ids),
            ("CreditNotes", "id", credit_note_ids),
            ("InvoiceOutputArtifacts", "id", artifact_ids),
        ):
            if not ids:
                continue
            placeholders = ",".join("?" for _ in ids)
            transaction_ids.update(
                self._ids_for_query(
                    cursor,
                    f"""
                    SELECT ledger_transaction_id
                    FROM {table}
                    WHERE {column} IN ({placeholders})
                      AND ledger_transaction_id IS NOT NULL
                    """,
                    tuple(ids),
                )
            )
        source_pairs: list[tuple[str, int]] = [("invoice", int(invoice_id))]
        source_pairs.extend(("invoice_payment", payment_id) for payment_id in payment_ids)
        source_pairs.extend(("credit_note", credit_note_id) for credit_note_id in credit_note_ids)
        for source_type, source_id in source_pairs:
            transaction_ids.update(
                self._ids_for_query(
                    cursor,
                    """
                    SELECT transaction_id
                    FROM AccountingTransactionLinks
                    WHERE source_type=? AND source_id=?
                    """,
                    (source_type, str(source_id)),
                )
            )
        return sorted(transaction_ids)

    def _invoice_cleanup_command_keys(
        self,
        cursor: sqlite3.Cursor,
        *,
        invoice_id: int,
        payment_ids: list[int],
        credit_note_ids: list[int],
        transaction_ids: list[int],
    ) -> list[str]:
        command_keys: set[str] = set()
        if transaction_ids:
            placeholders = ",".join("?" for _ in transaction_ids)
            rows = cursor.execute(
                f"""
                SELECT command_key
                FROM AccountingTransactions
                WHERE id IN ({placeholders}) AND command_key IS NOT NULL
                """,
                tuple(transaction_ids),
            ).fetchall()
            command_keys.update(str(row[0]) for row in rows if row[0])
        source_pairs: list[tuple[str, int]] = [("invoice", int(invoice_id))]
        source_pairs.extend(("invoice_payment", payment_id) for payment_id in payment_ids)
        source_pairs.extend(("credit_note", credit_note_id) for credit_note_id in credit_note_ids)
        for source_type, source_id in source_pairs:
            rows = cursor.execute(
                """
                SELECT command_key
                FROM FinancialCommandLog
                WHERE (source_type=? AND source_id=?)
                   OR (result_type=? AND result_id=?)
                """,
                (source_type, str(source_id), source_type, str(source_id)),
            ).fetchall()
            command_keys.update(str(row[0]) for row in rows if row[0])
        return sorted(command_keys)

    def _invoice_cleanup_managed_paths(
        self,
        cursor: sqlite3.Cursor,
        artifact_ids: list[int],
    ) -> list[Path]:
        if not artifact_ids:
            return []
        placeholders = ",".join("?" for _ in artifact_ids)
        rows = cursor.execute(
            f"""
            SELECT managed_file_path, output_path, storage_mode
            FROM InvoiceOutputArtifacts
            WHERE id IN ({placeholders})
              AND (
                    managed_file_path IS NOT NULL
                    OR storage_mode='managed_file'
                  )
            """,
            tuple(artifact_ids),
        ).fetchall()
        paths: list[Path] = []
        seen: set[Path] = set()
        for row in rows:
            stored_path = _clean_text(row[0]) or _clean_text(row[1])
            if stored_path is None:
                continue
            path = Path(stored_path).expanduser()
            if not path.is_absolute():
                if self.data_root is None:
                    continue
                path = self.data_root / path
            resolved = path.resolve(strict=False)
            if resolved in seen:
                continue
            seen.add(resolved)
            paths.append(resolved)
        return paths

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

    def fetch_invoice_by_registry_entry_id(
        self,
        registry_entry_id: int,
    ) -> InvoiceRecord | None:
        row = self.conn.execute(
            "SELECT id FROM Invoices WHERE invoice_registry_entry_id=?",
            (int(registry_entry_id),),
        ).fetchone()
        if not row:
            return None
        return self.fetch_invoice(int(row[0]))

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

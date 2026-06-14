"""Accounting value adapters for the central template workspace."""

from __future__ import annotations

import html
import sqlite3
from typing import Any

from isrc_manager.invoicing.invoice_service import InvoiceService
from isrc_manager.invoicing.models import DEFAULT_CURRENCY, InvoiceLinePayload, Quantity
from isrc_manager.invoicing.money import format_money, format_quantity
from isrc_manager.invoicing.report_service import InvoiceAccountingReportService
from isrc_manager.invoicing.royalty_service import RoyaltyAccountingService

from .models import ContractTemplateFormChoice


def _clean_text(value: object | None) -> str | None:
    text = str(value or "").strip()
    return text or None


def _escape(value: object | None) -> str:
    return html.escape(str(value or ""), quote=True)


def _join_address(parts: tuple[object | None, ...]) -> str:
    return "\n".join(str(part).strip() for part in parts if str(part or "").strip())


def _format_vat_rate(rate_basis_points: object | None) -> str:
    rate = int(rate_basis_points or 0)
    whole, fraction = divmod(rate, 100)
    if fraction:
        return f"{whole}.{fraction:02d}%"
    return f"{whole}%"


class AccountingTemplateResolver:
    """Read-only accounting adapter used by template form and export services."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        invoice_service: InvoiceService | None = None,
        report_service: InvoiceAccountingReportService | None = None,
        royalty_service: RoyaltyAccountingService | None = None,
        settings_reads: object | None = None,
    ):
        self.conn = conn
        self.invoice_service = invoice_service or InvoiceService(conn)
        self.report_service = report_service or InvoiceAccountingReportService(conn)
        self.royalty_service = royalty_service or RoyaltyAccountingService(conn)
        self.settings_reads = settings_reads

    def choices_for_entity_type(self, entity_type: str) -> tuple[ContractTemplateFormChoice, ...]:
        clean_type = str(entity_type or "").strip().lower()
        if clean_type == "invoice":
            return self.invoice_choices()
        if clean_type == "invoice_catalog_item":
            return self.invoice_catalog_item_choices()
        if clean_type == "invoice_line_item":
            return self.invoice_line_choices()
        if clean_type == "royalty_statement":
            return self.royalty_statement_choices()
        if clean_type == "royalty_line_item":
            return self.royalty_line_choices()
        return ()

    def invoice_choices(self) -> tuple[ContractTemplateFormChoice, ...]:
        rows = self.conn.execute("""
            SELECT
                i.id,
                i.invoice_number,
                i.draft_display_id,
                i.document_status,
                i.total_minor,
                i.currency,
                COALESCE(NULLIF(p.display_name, ''), NULLIF(p.company_name, ''), p.legal_name)
            FROM Invoices i
            INNER JOIN Parties p ON p.id=i.party_id
            ORDER BY i.updated_at DESC, i.id DESC
            """).fetchall()
        return tuple(
            ContractTemplateFormChoice(
                value=str(int(row[0])),
                label=(
                    f"{_clean_text(row[1]) or _clean_text(row[2]) or f'Invoice #{int(row[0])}'}"
                    f" - {_clean_text(row[6]) or 'Unknown party'}"
                    f" - {format_money(int(row[4] or 0), currency=str(row[5] or DEFAULT_CURRENCY))}"
                ),
                description=f"Document status: {str(row[3] or 'draft')}",
            )
            for row in rows
        )

    def invoice_line_choices(self) -> tuple[ContractTemplateFormChoice, ...]:
        rows = self.conn.execute("""
            SELECT
                li.id,
                li.invoice_id,
                COALESCE(i.invoice_number, i.draft_display_id),
                li.description,
                li.net_amount_minor,
                li.currency
            FROM InvoiceLineItems li
            INNER JOIN Invoices i ON i.id=li.invoice_id
            ORDER BY i.updated_at DESC, i.id DESC, li.sort_order, li.id
            """).fetchall()
        return tuple(
            ContractTemplateFormChoice(
                value=str(int(row[0])),
                label=(
                    f"{_clean_text(row[2]) or f'Invoice #{int(row[1])}'} - "
                    f"{_clean_text(row[3]) or f'Line #{int(row[0])}'}"
                ),
                description=format_money(
                    int(row[4] or 0), currency=str(row[5] or DEFAULT_CURRENCY)
                ),
            )
            for row in rows
        )

    def invoice_catalog_item_choices(self) -> tuple[ContractTemplateFormChoice, ...]:
        items = self.invoice_service.catalog_service.list_items(active_only=True)
        choices: list[ContractTemplateFormChoice] = []
        for item in items:
            quantity = format_quantity(
                Quantity(item.default_quantity_value, item.default_quantity_scale)
            )
            choices.append(
                ContractTemplateFormChoice(
                    value=str(int(item.id)),
                    label=(
                        f"{item.name} - {quantity} x "
                        f"{format_money(item.default_unit_price_minor, currency=item.currency)}"
                    ),
                    description=(
                        f"{item.description or item.category or 'Invoice catalog item'}; "
                        f"VAT {_format_vat_rate(item.default_vat_rate_basis_points)} "
                        f"{item.default_vat_treatment}"
                    ),
                )
            )
        return tuple(choices)

    def royalty_statement_choices(self) -> tuple[ContractTemplateFormChoice, ...]:
        rows = self.conn.execute("""
            SELECT
                s.id,
                s.statement_number,
                s.status,
                s.total_minor,
                s.currency,
                COALESCE(NULLIF(p.display_name, ''), NULLIF(p.company_name, ''), p.legal_name)
            FROM RoyaltyStatements s
            INNER JOIN Parties p ON p.id=s.party_id
            ORDER BY s.created_at DESC, s.id DESC
            """).fetchall()
        return tuple(
            ContractTemplateFormChoice(
                value=str(int(row[0])),
                label=(
                    f"{_clean_text(row[1]) or f'Royalty Statement #{int(row[0])}'}"
                    f" - {_clean_text(row[5]) or 'Unknown payee'}"
                    f" - {format_money(int(row[3] or 0), currency=str(row[4] or DEFAULT_CURRENCY))}"
                ),
                description=f"Statement status: {str(row[2] or 'generated')}",
            )
            for row in rows
        )

    def royalty_line_choices(self) -> tuple[ContractTemplateFormChoice, ...]:
        rows = self.conn.execute("""
            SELECT
                l.id,
                l.calculation_id,
                COALESCE(s.statement_number, 'Calculation #' || l.calculation_id),
                l.description,
                l.net_payable_minor,
                c.currency
            FROM RoyaltyCalculationLines l
            INNER JOIN RoyaltyCalculations c ON c.id=l.calculation_id
            LEFT JOIN RoyaltyStatements s ON s.calculation_id=l.calculation_id
            ORDER BY c.updated_at DESC, c.id DESC, l.sort_order, l.id
            """).fetchall()
        return tuple(
            ContractTemplateFormChoice(
                value=str(int(row[0])),
                label=(
                    f"{_clean_text(row[2]) or f'Calculation #{int(row[1])}'} - "
                    f"{_clean_text(row[3]) or f'Line #{int(row[0])}'}"
                ),
                description=format_money(
                    int(row[4] or 0), currency=str(row[5] or DEFAULT_CURRENCY)
                ),
            )
            for row in rows
        )

    def resolve_invoice_value(self, key: str, invoice_id: int, *, strict: bool) -> Any:
        invoice = self.invoice_service.fetch_invoice(int(invoice_id))
        if invoice is None:
            raise ValueError(f"Invoice {int(invoice_id)} was not found.")
        clean_key = str(key or "").strip().lower()
        settlement = None
        if clean_key in {"payment_status", "due_status", "outstanding_balance"}:
            settlement = self.report_service.invoice_settlement(int(invoice.id))
        if clean_key == "number":
            if invoice.invoice_number:
                return invoice.invoice_number
            if strict:
                raise ValueError("Invoice number is only available after the invoice is issued.")
            return invoice.draft_display_id or f"DRAFT-{int(invoice.id):06d}"
        if clean_key == "draft_display_id":
            return invoice.draft_display_id
        if clean_key == "id":
            return invoice.id
        if clean_key == "type":
            return invoice.invoice_type
        if clean_key == "document_status":
            return invoice.document_status
        if clean_key == "issue_date":
            return invoice.issue_date
        if clean_key == "due_date":
            return invoice.due_date
        if clean_key == "currency":
            return invoice.currency
        if clean_key == "subtotal":
            return format_money(invoice.subtotal_minor, currency=invoice.currency)
        if clean_key == "vat_total":
            return format_money(invoice.vat_total_minor, currency=invoice.currency)
        if clean_key == "total":
            return format_money(invoice.total_minor, currency=invoice.currency)
        if clean_key == "payment_status":
            return settlement.payment_status if settlement is not None else ""
        if clean_key == "due_status":
            return settlement.due_status if settlement is not None else ""
        if clean_key == "outstanding_balance":
            amount = settlement.receivable_balance_minor if settlement is not None else 0
            return format_money(amount, currency=invoice.currency)
        if clean_key == "lines":
            return self.render_invoice_lines_table(int(invoice.id))
        if clean_key == "vat_breakdown":
            return self.render_invoice_vat_table(int(invoice.id))
        if clean_key.startswith("party_"):
            return self._resolve_party_key(invoice.party_id, clean_key.removeprefix("party_"))
        if clean_key.startswith("buyer_"):
            return self._resolve_party_key(invoice.party_id, clean_key.removeprefix("buyer_"))
        if clean_key.startswith("seller_"):
            return self._resolve_owner_key(clean_key.removeprefix("seller_"))
        raise ValueError(f"Unsupported invoice template value: {key}")

    def resolve_invoice_line_value(self, key: str, line_id: int) -> Any:
        row = self.conn.execute(
            """
            SELECT
                description,
                quantity_value,
                quantity_scale,
                unit_price_minor,
                net_amount_minor,
                vat_amount_minor,
                gross_amount_minor,
                vat_treatment,
                vat_rate_basis_points,
                catalog_item_name_snapshot,
                ledger_account_code,
                currency
            FROM InvoiceLineItems
            WHERE id=?
            """,
            (int(line_id),),
        ).fetchone()
        if row is None:
            raise ValueError(f"Invoice line item {int(line_id)} was not found.")
        currency = str(row[11] or DEFAULT_CURRENCY)
        clean_key = str(key or "").strip().lower()
        values = {
            "description": row[0],
            "quantity": format_quantity(Quantity(value=int(row[1]), scale=int(row[2]))),
            "unit_price": format_money(int(row[3] or 0), currency=currency),
            "net_amount": format_money(int(row[4] or 0), currency=currency),
            "vat_amount": format_money(int(row[5] or 0), currency=currency),
            "gross_amount": format_money(int(row[6] or 0), currency=currency),
            "vat_treatment": row[7],
            "vat_rate": _format_vat_rate(row[8]),
            "catalog_item_name": row[9],
            "ledger_account_code": row[10],
            "currency": currency,
        }
        if clean_key not in values:
            raise ValueError(f"Unsupported invoice line template value: {key}")
        return values[clean_key]

    def preview_invoice_catalog_line(
        self,
        catalog_item_id: int,
        *,
        quantity: object | None = None,
    ) -> dict[str, object]:
        item = self.invoice_service.catalog_service.fetch_item(int(catalog_item_id))
        if item is None:
            raise ValueError(f"Invoice catalog item {int(catalog_item_id)} was not found.")
        quantity_text = _clean_text(quantity) or format_quantity(
            Quantity(item.default_quantity_value, item.default_quantity_scale)
        )
        return self.invoice_service.preview_invoice_line(
            InvoiceLinePayload(
                description=item.description or item.name,
                quantity=str(quantity_text),
                unit_price_minor=0,
                vat_treatment=item.default_vat_treatment,
                vat_rate_basis_points=0,
                vat_country_code=item.vat_country_code,
                ledger_account_code=item.default_account_code,
                catalog_item_id=item.id,
            ),
            currency=item.currency,
        )

    def resolve_invoice_catalog_line_value(
        self,
        key: str,
        catalog_item_id: int,
        *,
        quantity: object | None = None,
    ) -> Any:
        row = self.preview_invoice_catalog_line(catalog_item_id, quantity=quantity)
        currency = str(row["currency"] or DEFAULT_CURRENCY)
        clean_key = str(key or "").strip().lower()
        values = {
            "description": row["description"],
            "quantity": format_quantity(
                Quantity(
                    value=int(row["quantity_value"]),
                    scale=int(row["quantity_scale"]),
                )
            ),
            "unit_price": format_money(int(row["unit_price_minor"] or 0), currency=currency),
            "net_amount": format_money(int(row["net_amount_minor"] or 0), currency=currency),
            "vat_amount": format_money(int(row["vat_amount_minor"] or 0), currency=currency),
            "gross_amount": format_money(int(row["gross_amount_minor"] or 0), currency=currency),
            "vat_treatment": row["vat_treatment"],
            "vat_rate": _format_vat_rate(row["vat_rate_basis_points"]),
            "catalog_item_name": row["catalog_item_name_snapshot"],
            "ledger_account_code": row["ledger_account_code"],
            "currency": currency,
        }
        if clean_key not in values:
            raise ValueError(f"Unsupported invoice catalog line template value: {key}")
        return values[clean_key]

    def render_calculated_invoice_lines_table(self, rows: tuple[dict[str, object], ...]) -> str:
        if not rows:
            return ""
        body = []
        for row in rows:
            currency = str(row["currency"] or DEFAULT_CURRENCY)
            body.append(
                "<tr>"
                f"<td>{_escape(row.get('description'))}</td>"
                f"<td>{_escape(format_quantity(Quantity(value=int(row['quantity_value']), scale=int(row['quantity_scale']))))}</td>"
                f"<td>{_escape(format_money(int(row['unit_price_minor'] or 0), currency=currency))}</td>"
                f"<td>{_escape(format_money(int(row['net_amount_minor'] or 0), currency=currency))}</td>"
                f"<td>{_escape(_format_vat_rate(row['vat_rate_basis_points']))}</td>"
                f"<td>{_escape(format_money(int(row['vat_amount_minor'] or 0), currency=currency))}</td>"
                f"<td>{_escape(format_money(int(row['gross_amount_minor'] or 0), currency=currency))}</td>"
                "</tr>"
            )
        return (
            '<table class="invoice-lines">'
            "<thead><tr><th>Description</th><th>Qty</th><th>Unit</th>"
            "<th>Net</th><th>VAT Rate</th><th>VAT</th><th>Gross</th></tr></thead>"
            f"<tbody>{''.join(body)}</tbody></table>"
        )

    def render_calculated_invoice_vat_table(self, rows: tuple[dict[str, object], ...]) -> str:
        grouped: dict[tuple[str, int, str], dict[str, int]] = {}
        for row in rows:
            key = (
                str(row["vat_treatment"] or ""),
                int(row["vat_rate_basis_points"] or 0),
                str(row["currency"] or DEFAULT_CURRENCY),
            )
            bucket = grouped.setdefault(key, {"net": 0, "vat": 0, "gross": 0})
            bucket["net"] += int(row["net_amount_minor"] or 0)
            bucket["vat"] += int(row["vat_amount_minor"] or 0)
            bucket["gross"] += int(row["gross_amount_minor"] or 0)
        if not grouped:
            return ""
        body = []
        for (vat_treatment, vat_rate, currency), totals in sorted(grouped.items()):
            body.append(
                "<tr>"
                f"<td>{_escape(vat_treatment)}</td>"
                f"<td>{_escape(_format_vat_rate(vat_rate))}</td>"
                f"<td>{_escape(format_money(totals['net'], currency=currency))}</td>"
                f"<td>{_escape(format_money(totals['vat'], currency=currency))}</td>"
                f"<td>{_escape(format_money(totals['gross'], currency=currency))}</td>"
                "</tr>"
            )
        return (
            '<table class="invoice-vat-breakdown">'
            "<thead><tr><th>Treatment</th><th>Rate</th><th>Taxable</th>"
            "<th>VAT</th><th>Gross</th></tr></thead>"
            f"<tbody>{''.join(body)}</tbody></table>"
        )

    def resolve_royalty_value(self, key: str, statement_id: int, *, strict: bool) -> Any:
        statement = self.royalty_service.fetch_statement(int(statement_id))
        if statement is None:
            raise ValueError(f"Royalty statement {int(statement_id)} was not found.")
        calculation = self.royalty_service.fetch_calculation(int(statement.calculation_id))
        if calculation is None:
            raise ValueError(f"Royalty calculation {int(statement.calculation_id)} was not found.")
        clean_key = str(key or "").strip().lower()
        period = self._royalty_period(int(calculation.id))
        if clean_key == "statement_number":
            if statement.statement_number:
                return statement.statement_number
            if strict:
                raise ValueError("Royalty statement number is only available after generation.")
            return f"Royalty Statement #{int(statement.id)}"
        if clean_key == "statement_id":
            return statement.id
        if clean_key == "calculation_id":
            return statement.calculation_id
        if clean_key == "status":
            return statement.status
        if clean_key == "issue_date":
            return statement.issue_date
        if clean_key == "currency":
            return statement.currency
        if clean_key == "period_start":
            return period.get("period_start")
        if clean_key == "period_end":
            return period.get("period_end")
        if clean_key == "payee_name":
            return self._resolve_party_key(statement.party_id, "name")
        if clean_key == "contract_title":
            return period.get("contract_title")
        if clean_key in {"gross_royalty", "net_payable"}:
            return format_money(statement.total_minor, currency=statement.currency)
        if clean_key in {"deductions", "advance_recouped"}:
            return format_money(0, currency=statement.currency)
        if clean_key == "payment_status":
            return calculation.status
        if clean_key == "payable_balance":
            balance = self.royalty_service.royalty_payable_balance_minor(
                calculation_id=int(calculation.id),
                party_id=int(statement.party_id),
                currency=statement.currency,
            )
            return format_money(balance, currency=statement.currency)
        if clean_key == "lines":
            return self.render_royalty_lines_table(int(calculation.id))
        raise ValueError(f"Unsupported royalty template value: {key}")

    def resolve_royalty_line_value(self, key: str, line_id: int) -> Any:
        row = self.conn.execute(
            """
            SELECT l.description, l.net_payable_minor, l.source_type, l.source_id, c.currency
            FROM RoyaltyCalculationLines l
            INNER JOIN RoyaltyCalculations c ON c.id=l.calculation_id
            WHERE l.id=?
            """,
            (int(line_id),),
        ).fetchone()
        if row is None:
            raise ValueError(f"Royalty line item {int(line_id)} was not found.")
        currency = str(row[4] or DEFAULT_CURRENCY)
        clean_key = str(key or "").strip().lower()
        values = {
            "description": row[0],
            "net_payable": format_money(int(row[1] or 0), currency=currency),
            "source_type": row[2],
            "source_id": row[3],
            "currency": currency,
        }
        if clean_key not in values:
            raise ValueError(f"Unsupported royalty line template value: {key}")
        return values[clean_key]

    def render_invoice_lines_table(self, invoice_id: int) -> str:
        rows = self.conn.execute(
            """
            SELECT
                description,
                quantity_value,
                quantity_scale,
                unit_price_minor,
                net_amount_minor,
                vat_amount_minor,
                gross_amount_minor,
                currency
            FROM InvoiceLineItems
            WHERE invoice_id=?
            ORDER BY sort_order, id
            """,
            (int(invoice_id),),
        ).fetchall()
        if not rows:
            return ""
        body = []
        for row in rows:
            currency = str(row[7] or DEFAULT_CURRENCY)
            body.append(
                "<tr>"
                f"<td>{_escape(row[0])}</td>"
                f"<td>{_escape(format_quantity(Quantity(value=int(row[1]), scale=int(row[2]))))}</td>"
                f"<td>{_escape(format_money(int(row[3] or 0), currency=currency))}</td>"
                f"<td>{_escape(format_money(int(row[4] or 0), currency=currency))}</td>"
                f"<td>{_escape(format_money(int(row[5] or 0), currency=currency))}</td>"
                f"<td>{_escape(format_money(int(row[6] or 0), currency=currency))}</td>"
                "</tr>"
            )
        return (
            '<table class="invoice-lines">'
            "<thead><tr><th>Description</th><th>Qty</th><th>Unit</th>"
            "<th>Net</th><th>VAT</th><th>Gross</th></tr></thead>"
            f"<tbody>{''.join(body)}</tbody></table>"
        )

    def render_invoice_vat_table(self, invoice_id: int) -> str:
        rows = self.conn.execute(
            """
            SELECT vat_treatment, vat_rate_basis_points, taxable_amount_minor,
                   vat_amount_minor, gross_amount_minor, currency
            FROM InvoiceVatBreakdown
            WHERE invoice_id=?
            ORDER BY vat_treatment, vat_rate_basis_points
            """,
            (int(invoice_id),),
        ).fetchall()
        if not rows:
            return ""
        body = []
        for row in rows:
            currency = str(row[5] or DEFAULT_CURRENCY)
            body.append(
                "<tr>"
                f"<td>{_escape(row[0])}</td>"
                f"<td>{_escape(_format_vat_rate(row[1]))}</td>"
                f"<td>{_escape(format_money(int(row[2] or 0), currency=currency))}</td>"
                f"<td>{_escape(format_money(int(row[3] or 0), currency=currency))}</td>"
                f"<td>{_escape(format_money(int(row[4] or 0), currency=currency))}</td>"
                "</tr>"
            )
        return (
            '<table class="invoice-vat-breakdown">'
            "<thead><tr><th>Treatment</th><th>Rate</th><th>Taxable</th>"
            "<th>VAT</th><th>Gross</th></tr></thead>"
            f"<tbody>{''.join(body)}</tbody></table>"
        )

    def render_royalty_lines_table(self, calculation_id: int) -> str:
        rows = self.conn.execute(
            """
            SELECT description, net_payable_minor, source_type, source_id, sort_order
            FROM RoyaltyCalculationLines
            WHERE calculation_id=?
            ORDER BY sort_order, id
            """,
            (int(calculation_id),),
        ).fetchall()
        calculation = self.royalty_service.fetch_calculation(int(calculation_id))
        currency = calculation.currency if calculation is not None else DEFAULT_CURRENCY
        if not rows:
            return ""
        body = []
        for row in rows:
            body.append(
                "<tr>"
                f"<td>{_escape(row[0])}</td>"
                f"<td>{_escape(format_money(int(row[1] or 0), currency=currency))}</td>"
                f"<td>{_escape(row[2])}</td>"
                f"<td>{_escape(row[3])}</td>"
                "</tr>"
            )
        return (
            '<table class="royalty-lines">'
            "<thead><tr><th>Description</th><th>Net Payable</th><th>Source</th>"
            "<th>Source ID</th></tr></thead>"
            f"<tbody>{''.join(body)}</tbody></table>"
        )

    def _resolve_party_key(self, party_id: int, key: str) -> str | None:
        party = self._party_row(int(party_id))
        if party is None:
            return None
        clean_key = str(key or "").strip().lower()
        if clean_key in {"name", "display_name"}:
            return (
                _clean_text(party["display_name"])
                or _clean_text(party["company_name"])
                or _clean_text(party["legal_name"])
            )
        if clean_key == "address":
            return _join_address(
                (
                    party["address_line1"],
                    party["address_line2"],
                    " ".join(
                        part
                        for part in (
                            str(party["street_name"] or "").strip(),
                            str(party["street_number"] or "").strip(),
                        )
                        if part
                    ),
                    " ".join(
                        part
                        for part in (
                            str(party["postal_code"] or "").strip(),
                            str(party["city"] or "").strip(),
                        )
                        if part
                    ),
                    party["region"],
                    party["country"],
                )
            )
        mapping = {
            "legal_name": "legal_name",
            "company_name": "company_name",
            "email": "email",
            "phone": "phone",
            "address_line1": "address_line1",
            "address_line2": "address_line2",
            "street_name": "street_name",
            "street_number": "street_number",
            "postal_code": "postal_code",
            "city": "city",
            "region": "region",
            "country": "country",
            "vat_number": "vat_number",
            "tax_id": "tax_id",
            "bank_account_number": "bank_account_number",
            "chamber_of_commerce_number": "chamber_of_commerce_number",
        }
        column = mapping.get(clean_key)
        return _clean_text(party[column]) if column else None

    def _resolve_owner_key(self, key: str) -> str | None:
        if self.settings_reads is None:
            return None
        owner = self.settings_reads.load_owner_party_settings()
        clean_key = str(key or "").strip().lower()
        if clean_key == "name":
            return (
                _clean_text(getattr(owner, "display_name", None))
                or _clean_text(getattr(owner, "company_name", None))
                or _clean_text(getattr(owner, "legal_name", None))
            )
        if clean_key == "address":
            return _join_address(
                (
                    getattr(owner, "address_line1", None),
                    getattr(owner, "address_line2", None),
                    " ".join(
                        part
                        for part in (
                            str(getattr(owner, "street_name", "") or "").strip(),
                            str(getattr(owner, "street_number", "") or "").strip(),
                        )
                        if part
                    ),
                    " ".join(
                        part
                        for part in (
                            str(getattr(owner, "postal_code", "") or "").strip(),
                            str(getattr(owner, "city", "") or "").strip(),
                        )
                        if part
                    ),
                    getattr(owner, "region", None),
                    getattr(owner, "country", None),
                )
            )
        return _clean_text(getattr(owner, clean_key, None))

    def _party_row(self, party_id: int) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT
                legal_name,
                display_name,
                company_name,
                email,
                phone,
                address_line1,
                address_line2,
                street_name,
                street_number,
                postal_code,
                city,
                region,
                country,
                vat_number,
                tax_id,
                bank_account_number,
                chamber_of_commerce_number
            FROM Parties
            WHERE id=?
            """,
            (int(party_id),),
        ).fetchone()
        if row is None:
            return None
        keys = (
            "legal_name",
            "display_name",
            "company_name",
            "email",
            "phone",
            "address_line1",
            "address_line2",
            "street_name",
            "street_number",
            "postal_code",
            "city",
            "region",
            "country",
            "vat_number",
            "tax_id",
            "bank_account_number",
            "chamber_of_commerce_number",
        )
        return dict(zip(keys, row, strict=False))

    def _royalty_period(self, calculation_id: int) -> dict[str, str | None]:
        row = self.conn.execute(
            """
            SELECT rc.period_start, rc.period_end, c.title
            FROM RoyaltyCalculations rc
            LEFT JOIN Contracts c ON c.id=rc.contract_id
            WHERE rc.id=?
            """,
            (int(calculation_id),),
        ).fetchone()
        if row is None:
            return {}
        return {
            "period_start": _clean_text(row[0]),
            "period_end": _clean_text(row[1]),
            "contract_title": _clean_text(row[2]),
        }

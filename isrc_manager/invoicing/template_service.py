"""Secure HTML invoice template storage, symbol validation, and rendering."""

from __future__ import annotations

import hashlib
import html
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from isrc_manager.contract_templates.html_support import HTMLTemplateScanner, decode_html_bytes
from isrc_manager.contract_templates.models import build_contract_template_indexed_selection_key
from isrc_manager.contract_templates.parser import (
    InvalidPlaceholderError,
    base_symbol_for_indexed_placeholder,
    parse_placeholder,
)
from isrc_manager.services.settings_reads import SettingsReadService

from .invoice_service import InvoiceService
from .models import (
    InvoiceOutputArtifactRecord,
    InvoiceTemplateRenderResult,
    InvoiceTemplateRevisionRecord,
    Quantity,
)
from .money import format_money, format_quantity
from .report_service import InvoiceAccountingReportService

_SYMBOL_RE = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
_DUPLICATE_START_SYMBOL = "{{duplicate.start}}"
_DUPLICATE_END_SYMBOL = "{{duplicate.end}}"
_DUPLICATE_NUMBER_SYMBOL = "{{duplicate.number}}"
_DB_INDEX_SYMBOL = "{{db.index}}"
_DUPLICATE_BLOCK_RE = re.compile(
    r"\{\{\s*duplicate\.start\s*\}\}(.*?)\{\{\s*duplicate\.end\s*\}\}",
    re.IGNORECASE | re.DOTALL,
)
_MAX_DUPLICATE_COPIES = 200
_PATH_TRAVERSAL_ASSET_RE = re.compile(
    r"\s(?:src|href)\s*=\s*['\"][^'\"]*\.\./",
    re.IGNORECASE,
)
_SYMBOL_ALIASES: dict[str, str] = {
    "contract.license_number": "invoice.number",
    "contract.number": "invoice.number",
    "contract.reference": "invoice.number",
    "party.company_name": "invoice.party.company_name",
    "party.display_name": "invoice.party.display_name",
    "party.name": "invoice.party.name",
    "party.legal_name": "invoice.party.legal_name",
    "party.address": "invoice.party.address",
    "party.address_line1": "invoice.party.address_line1",
    "party.address_line2": "invoice.party.address_line2",
    "party.street_name": "invoice.party.street_name",
    "party.street_number": "invoice.party.street_number",
    "party.postal_code": "invoice.party.postal_code",
    "party.city": "invoice.party.city",
    "party.region": "invoice.party.region",
    "party.country": "invoice.party.country",
    "party.vat_number": "invoice.party.vat_number",
    "party.tax_id": "invoice.party.tax_id",
    "party.email": "invoice.party.email",
    "party.phone": "invoice.party.phone",
    "party.bank_account_number": "invoice.party.bank_account_number",
    "party.chamber_of_commerce_number": "invoice.party.chamber_of_commerce_number",
    "invoice.party_name": "invoice.party.name",
    "invoice.party_company_name": "invoice.party.company_name",
    "invoice.party_display_name": "invoice.party.display_name",
    "invoice.party_legal_name": "invoice.party.legal_name",
    "invoice.party_address": "invoice.party.address",
    "invoice.party_address_line1": "invoice.party.address_line1",
    "invoice.party_address_line2": "invoice.party.address_line2",
    "invoice.party_street_name": "invoice.party.street_name",
    "invoice.party_street_number": "invoice.party.street_number",
    "invoice.party_postal_code": "invoice.party.postal_code",
    "invoice.party_city": "invoice.party.city",
    "invoice.party_region": "invoice.party.region",
    "invoice.party_country": "invoice.party.country",
    "invoice.party_vat_number": "invoice.party.vat_number",
    "invoice.party_tax_id": "invoice.party.tax_id",
    "invoice.party_email": "invoice.party.email",
    "invoice.party_phone": "invoice.party.phone",
    "invoice.party_bank_account_number": "invoice.party.bank_account_number",
    "invoice.party_chamber_of_commerce_number": "invoice.party.chamber_of_commerce_number",
    "owner.company_name": "company.company_name",
    "owner.display_name": "company.display_name",
    "owner.legal_name": "company.legal_name",
    "owner.name": "company.name",
    "owner.address": "company.address",
    "owner.address_line1": "company.address_line1",
    "owner.address_line2": "company.address_line2",
    "owner.street_name": "company.street_name",
    "owner.street_number": "company.street_number",
    "owner.postal_code": "company.postal_code",
    "owner.city": "company.city",
    "owner.region": "company.region",
    "owner.country": "company.country",
    "owner.vat_number": "company.vat_number",
    "owner.email": "company.email",
    "owner.phone": "company.phone",
    "owner.bank_account_number": "company.payment_details",
    "owner.chamber_of_commerce_number": "company.chamber_of_commerce_number",
}


@dataclass(frozen=True, slots=True)
class _SymbolDefinition:
    key: str
    render_mode: str
    required: bool = False


_CANONICAL_SYMBOLS: dict[str, _SymbolDefinition] = {
    "invoice.number": _SymbolDefinition("invoice.number", "text"),
    "invoice.issue_date": _SymbolDefinition("invoice.issue_date", "date"),
    "invoice.due_date": _SymbolDefinition("invoice.due_date", "date"),
    "invoice.document_status": _SymbolDefinition("invoice.document_status", "text"),
    "invoice.payment_status": _SymbolDefinition("invoice.payment_status", "text"),
    "invoice.due_status": _SymbolDefinition("invoice.due_status", "text"),
    "invoice.currency": _SymbolDefinition("invoice.currency", "text"),
    "invoice.subtotal": _SymbolDefinition("invoice.subtotal", "money"),
    "invoice.vat_total": _SymbolDefinition("invoice.vat_total", "money"),
    "invoice.total": _SymbolDefinition("invoice.total", "money"),
    "invoice.outstanding_balance": _SymbolDefinition("invoice.outstanding_balance", "money"),
    "invoice.lines": _SymbolDefinition("invoice.lines", "table"),
    "invoice.vat_breakdown": _SymbolDefinition("invoice.vat_breakdown", "table"),
    "invoice.party.name": _SymbolDefinition("invoice.party.name", "text"),
    "invoice.party.company_name": _SymbolDefinition("invoice.party.company_name", "text"),
    "invoice.party.display_name": _SymbolDefinition("invoice.party.display_name", "text"),
    "invoice.party.legal_name": _SymbolDefinition("invoice.party.legal_name", "text"),
    "invoice.party.address": _SymbolDefinition("invoice.party.address", "text"),
    "invoice.party.address_line1": _SymbolDefinition("invoice.party.address_line1", "text"),
    "invoice.party.address_line2": _SymbolDefinition("invoice.party.address_line2", "text"),
    "invoice.party.street_name": _SymbolDefinition("invoice.party.street_name", "text"),
    "invoice.party.street_number": _SymbolDefinition("invoice.party.street_number", "text"),
    "invoice.party.postal_code": _SymbolDefinition("invoice.party.postal_code", "text"),
    "invoice.party.city": _SymbolDefinition("invoice.party.city", "text"),
    "invoice.party.region": _SymbolDefinition("invoice.party.region", "text"),
    "invoice.party.country": _SymbolDefinition("invoice.party.country", "text"),
    "invoice.party.vat_number": _SymbolDefinition("invoice.party.vat_number", "text"),
    "invoice.party.tax_id": _SymbolDefinition("invoice.party.tax_id", "text"),
    "invoice.party.email": _SymbolDefinition("invoice.party.email", "text"),
    "invoice.party.phone": _SymbolDefinition("invoice.party.phone", "text"),
    "invoice.party.bank_account_number": _SymbolDefinition(
        "invoice.party.bank_account_number", "text"
    ),
    "invoice.party.chamber_of_commerce_number": _SymbolDefinition(
        "invoice.party.chamber_of_commerce_number", "text"
    ),
    "company.name": _SymbolDefinition("company.name", "text"),
    "company.company_name": _SymbolDefinition("company.company_name", "text"),
    "company.display_name": _SymbolDefinition("company.display_name", "text"),
    "company.legal_name": _SymbolDefinition("company.legal_name", "text"),
    "company.address": _SymbolDefinition("company.address", "text"),
    "company.address_line1": _SymbolDefinition("company.address_line1", "text"),
    "company.address_line2": _SymbolDefinition("company.address_line2", "text"),
    "company.street_name": _SymbolDefinition("company.street_name", "text"),
    "company.street_number": _SymbolDefinition("company.street_number", "text"),
    "company.postal_code": _SymbolDefinition("company.postal_code", "text"),
    "company.city": _SymbolDefinition("company.city", "text"),
    "company.region": _SymbolDefinition("company.region", "text"),
    "company.country": _SymbolDefinition("company.country", "text"),
    "company.vat_number": _SymbolDefinition("company.vat_number", "text"),
    "company.email": _SymbolDefinition("company.email", "text"),
    "company.phone": _SymbolDefinition("company.phone", "text"),
    "company.payment_details": _SymbolDefinition("company.payment_details", "text"),
    "company.chamber_of_commerce_number": _SymbolDefinition(
        "company.chamber_of_commerce_number", "text"
    ),
    "credit_note.number": _SymbolDefinition("credit_note.number", "text"),
    "credit_note.reason": _SymbolDefinition("credit_note.reason", "text"),
    "credit_note.original_invoice_number": _SymbolDefinition(
        "credit_note.original_invoice_number", "text"
    ),
    "royalty.statement_number": _SymbolDefinition("royalty.statement_number", "text"),
    "royalty.payee_name": _SymbolDefinition("royalty.payee_name", "text"),
    "royalty.contract_title": _SymbolDefinition("royalty.contract_title", "text"),
    "royalty.period_start": _SymbolDefinition("royalty.period_start", "date"),
    "royalty.period_end": _SymbolDefinition("royalty.period_end", "date"),
    "royalty.gross_royalty": _SymbolDefinition("royalty.gross_royalty", "money"),
    "royalty.deductions": _SymbolDefinition("royalty.deductions", "money"),
    "royalty.advance_recouped": _SymbolDefinition("royalty.advance_recouped", "money"),
    "royalty.net_payable": _SymbolDefinition("royalty.net_payable", "money"),
    "royalty.payment_status": _SymbolDefinition("royalty.payment_status", "text"),
    "royalty.calculation_id": _SymbolDefinition("royalty.calculation_id", "text"),
    "royalty.statement_id": _SymbolDefinition("royalty.statement_id", "text"),
}


def _clean_text(value: object | None) -> str | None:
    text = str(value or "").strip()
    return text or None


def _symbol_key(value: str) -> str:
    return str(value or "").strip().lower().replace("-", "_")


def _invoice_symbol_key(value: str) -> str:
    symbol = _symbol_key(value)
    if symbol.startswith("{{") and symbol.endswith("}}"):
        symbol = _symbol_key(symbol[2:-2])
    if symbol.startswith("db."):
        symbol = symbol[3:]
    if symbol.startswith("manual."):
        symbol = f"custom.{symbol[7:]}"
    return _SYMBOL_ALIASES.get(symbol, symbol)


def _contract_placeholder_token(value: object | None):
    inner = str(value or "").strip()
    if inner.startswith("{{") and inner.endswith("}}"):
        inner = inner[2:-2].strip()
    if not inner:
        return None
    try:
        return parse_placeholder(f"{{{{{inner}}}}}")
    except InvalidPlaceholderError:
        return None


def _manual_symbol_key(value: object | None) -> str:
    text = str(value or "").strip()
    if text.startswith("{{") and text.endswith("}}"):
        token = _contract_placeholder_token(text[2:-2])
    else:
        token = _contract_placeholder_token(text)
    if token is not None and token.binding_kind == "manual":
        return token.canonical_symbol
    symbol = _symbol_key(text)
    if symbol.startswith("manual."):
        token = _contract_placeholder_token(symbol)
        if token is not None and token.binding_kind == "manual":
            return token.canonical_symbol
    return _invoice_symbol_key(text)


def _manual_lookup(values: dict[str, str], canonical_symbol: str) -> str | None:
    token = _contract_placeholder_token(canonical_symbol[2:-2])
    keys = [canonical_symbol]
    if token is not None and token.binding_kind == "manual":
        keys.extend(
            [
                f"manual.{token.key}",
                f"custom.{token.key}",
                _symbol_key(canonical_symbol),
            ]
        )
    for key in keys:
        if key in values:
            return values[key]
    return None


def _escape_text(value: object | None) -> str:
    return html.escape(str(value or ""), quote=True)


class InvoiceTemplateService:
    """Renders invoice HTML through one strict path for preview and export."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.invoice_service = InvoiceService(conn)
        self.reports = InvoiceAccountingReportService(conn)

    def upload_html_template(
        self,
        *,
        name: str,
        html_content: str,
        source_filename: str = "invoice.html",
        revision_label: str | None = None,
        template_id: int | None = None,
        activate: bool = True,
    ) -> InvoiceTemplateRevisionRecord:
        clean_name = _clean_text(name)
        if clean_name is None:
            raise ValueError("Invoice template name is required.")
        clean_filename = _clean_text(source_filename) or "invoice.html"
        content = str(html_content or "")
        symbols = self.validate_html_template(content)
        checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()
        symbol_inventory_json = json.dumps(sorted(symbols), sort_keys=True)
        with self.conn:
            cursor = self.conn.cursor()
            if template_id is None:
                cursor.execute(
                    """
                    INSERT INTO InvoiceTemplates(name, active_revision_id)
                    VALUES (?, NULL)
                    """,
                    (clean_name,),
                )
                clean_template_id = int(cursor.lastrowid)
            else:
                clean_template_id = int(template_id)
                cursor.execute(
                    """
                    UPDATE InvoiceTemplates
                    SET name=?,
                        updated_at=datetime('now')
                    WHERE id=?
                    """,
                    (clean_name, clean_template_id),
                )
                if cursor.rowcount != 1:
                    raise ValueError(f"Invoice template {clean_template_id} was not found.")
            cursor.execute(
                """
                INSERT INTO InvoiceTemplateRevisions(
                    template_id,
                    revision_label,
                    source_filename,
                    html_content,
                    source_checksum_sha256,
                    symbol_inventory_json,
                    validation_status
                )
                VALUES (?, ?, ?, ?, ?, ?, 'valid')
                """,
                (
                    clean_template_id,
                    _clean_text(revision_label),
                    clean_filename,
                    content,
                    checksum,
                    symbol_inventory_json,
                ),
            )
            revision_id = int(cursor.lastrowid)
            if activate:
                cursor.execute(
                    """
                    UPDATE InvoiceTemplates
                    SET active_revision_id=?,
                        updated_at=datetime('now')
                    WHERE id=?
                    """,
                    (revision_id, clean_template_id),
                )
        record = self.fetch_revision(revision_id)
        if record is None:
            raise RuntimeError("Invoice template revision could not be reloaded.")
        return record

    def upload_html_template_from_path(
        self,
        source_path: str | Path,
        *,
        name: str,
        revision_label: str | None = None,
        template_id: int | None = None,
        activate: bool = True,
    ) -> InvoiceTemplateRevisionRecord:
        path = Path(source_path).expanduser()
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(str(path))
        if path.suffix.lower() not in {".html", ".htm"}:
            raise ValueError("Invoice templates must be uploaded from an HTML file.")
        return self.upload_html_template(
            name=name,
            html_content=decode_html_bytes(path.read_bytes()),
            source_filename=path.name,
            revision_label=revision_label,
            template_id=template_id,
            activate=activate,
        )

    def validate_html_template(self, html_content: str) -> tuple[str, ...]:
        content = str(html_content or "")
        if not content.strip():
            raise ValueError("Invoice HTML template content is required.")
        if _PATH_TRAVERSAL_ASSET_RE.search(content):
            raise ValueError("Invoice HTML template assets cannot escape the bundle root.")
        scanner = HTMLTemplateScanner()
        scanner.scan_bytes(content.encode("utf-8"), source_filename="invoice-template.html")
        symbols: list[str] = []
        for match in _SYMBOL_RE.finditer(content):
            inner = str(match.group(1) or "").strip()
            token = _contract_placeholder_token(inner)
            if token is not None:
                if token.binding_kind in {"db_index", "duplicate"}:
                    symbols.append(token.canonical_symbol)
                elif token.binding_kind == "manual":
                    symbols.append(token.canonical_symbol)
                elif token.binding_kind == "db":
                    if token.indexed:
                        symbols.append(token.canonical_symbol)
                    else:
                        symbols.append(_invoice_symbol_key(f"db.{token.namespace}.{token.key}"))
                else:
                    symbols.append(token.canonical_symbol)
            else:
                symbols.append(_invoice_symbol_key(inner))
        symbols = list(dict.fromkeys(symbols))
        return symbols

    def set_manual_symbols(
        self,
        *,
        invoice_id: int,
        template_revision_id: int | None,
        values: dict[str, object],
    ) -> None:
        with self.conn:
            for raw_key, raw_value in values.items():
                key = _manual_symbol_key(raw_key)
                if not (key.startswith("custom.") or key.startswith("{{manual.")):
                    key = f"custom.{key}"
                self.conn.execute(
                    """
                    INSERT INTO InvoiceManualSymbols(
                        invoice_id,
                        template_revision_id,
                        symbol_key,
                        value_text
                    )
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(invoice_id, symbol_key) DO UPDATE SET
                        template_revision_id=excluded.template_revision_id,
                        value_text=excluded.value_text,
                        updated_at=datetime('now')
                    """,
                    (
                        int(invoice_id),
                        int(template_revision_id) if template_revision_id is not None else None,
                        key,
                        str(raw_value or ""),
                    ),
                )

    def preview_invoice(
        self,
        invoice_id: int,
        *,
        template_revision_id: int | None = None,
        manual_symbols: dict[str, object] | None = None,
        canonical_overrides: dict[str, object] | None = None,
    ) -> InvoiceTemplateRenderResult:
        return self.render_invoice(
            invoice_id,
            template_revision_id=template_revision_id,
            manual_symbols=manual_symbols,
            canonical_overrides=canonical_overrides,
            strict=False,
            create_snapshot=False,
        )

    def export_invoice_html(
        self,
        invoice_id: int,
        *,
        template_revision_id: int | None = None,
        manual_symbols: dict[str, object] | None = None,
        canonical_overrides: dict[str, object] | None = None,
    ) -> InvoiceTemplateRenderResult:
        return self.render_invoice(
            invoice_id,
            template_revision_id=template_revision_id,
            manual_symbols=manual_symbols,
            canonical_overrides=canonical_overrides,
            strict=True,
            create_snapshot=True,
        )

    def create_html_output_artifact(
        self,
        *,
        snapshot_id: int,
        output_path: str | None = None,
        output_filename: str | None = None,
    ) -> InvoiceOutputArtifactRecord:
        row = self.conn.execute(
            """
            SELECT invoice_id, rendered_html_content, rendered_checksum_sha256
            FROM InvoiceTemplateResolvedSnapshots
            WHERE id=?
            """,
            (int(snapshot_id),),
        ).fetchone()
        if not row:
            raise ValueError(f"Invoice resolved snapshot {int(snapshot_id)} was not found.")
        rendered_html = str(row[1] or "")
        if not rendered_html:
            raise ValueError("Invoice resolved snapshot has no rendered HTML content.")
        filename = (
            _clean_text(output_filename)
            or f"invoice-{int(row[0])}-snapshot-{int(snapshot_id)}.html"
        )
        path = _clean_text(output_path) or f"invoice-artifacts/{filename}"
        checksum = str(row[2] or "") or hashlib.sha256(rendered_html.encode("utf-8")).hexdigest()
        with self.conn:
            cursor = self.conn.execute(
                """
                INSERT INTO InvoiceOutputArtifacts(
                    snapshot_id,
                    artifact_type,
                    output_path,
                    output_filename,
                    mime_type,
                    size_bytes,
                    checksum_sha256
                )
                VALUES (?, 'html', ?, ?, 'text/html; charset=utf-8', ?, ?)
                """,
                (
                    int(snapshot_id),
                    path,
                    filename,
                    len(rendered_html.encode("utf-8")),
                    checksum,
                ),
            )
            artifact_id = int(cursor.lastrowid)
        artifact = self.fetch_output_artifact(artifact_id)
        if artifact is None:
            raise RuntimeError("Invoice output artifact could not be reloaded.")
        return artifact

    def fetch_output_artifact(self, artifact_id: int) -> InvoiceOutputArtifactRecord | None:
        row = self.conn.execute(
            """
            SELECT
                id,
                snapshot_id,
                artifact_type,
                output_path,
                output_filename,
                mime_type,
                size_bytes,
                checksum_sha256,
                created_at
            FROM InvoiceOutputArtifacts
            WHERE id=?
            """,
            (int(artifact_id),),
        ).fetchone()
        if not row:
            return None
        return InvoiceOutputArtifactRecord(
            id=int(row[0]),
            snapshot_id=int(row[1]),
            artifact_type=str(row[2] or ""),
            output_path=str(row[3] or ""),
            output_filename=str(row[4] or ""),
            mime_type=_clean_text(row[5]),
            size_bytes=int(row[6] or 0),
            checksum_sha256=_clean_text(row[7]),
            created_at=_clean_text(row[8]),
        )

    def render_invoice(
        self,
        invoice_id: int,
        *,
        template_revision_id: int | None = None,
        manual_symbols: dict[str, object] | None = None,
        canonical_overrides: dict[str, object] | None = None,
        strict: bool = True,
        create_snapshot: bool = False,
    ) -> InvoiceTemplateRenderResult:
        invoice = self.invoice_service.fetch_invoice(int(invoice_id))
        if invoice is None:
            raise ValueError(f"Invoice {int(invoice_id)} was not found.")
        revision = (
            self.fetch_revision(int(template_revision_id))
            if template_revision_id is not None
            else self.fetch_active_revision()
        )
        if revision is None:
            raise ValueError("No invoice template revision is available.")
        self.validate_html_template(revision.html_content)
        stored_manual = self._manual_symbols(int(invoice.id))
        for key, value in (manual_symbols or {}).items():
            raw_key = str(key or "").strip()
            if "#index:" in raw_key:
                stored_manual[raw_key] = str(value or "")
                continue
            token = _contract_placeholder_token(raw_key)
            if token is not None and token.binding_kind == "duplicate":
                stored_manual[token.canonical_symbol] = str(value or "")
                continue
            clean_key = _manual_symbol_key(key)
            if not (clean_key.startswith("custom.") or clean_key.startswith("{{manual.")):
                clean_key = f"custom.{clean_key}"
            stored_manual[clean_key] = str(value or "")
        canonical_values = self._canonical_values(int(invoice.id))
        override_values: dict[str, object] = {}
        for key, value in (canonical_overrides or {}).items():
            raw_key = str(key or "").strip()
            if "#index:" in raw_key:
                override_values[raw_key] = value
                continue
            clean_key = _invoice_symbol_key(raw_key)
            if clean_key in canonical_values:
                canonical_values[clean_key] = value
            else:
                override_values[clean_key] = value
        warnings: list[str] = []
        source_html, duplicate_warnings = self._apply_duplicate_controls(
            revision.html_content,
            manual_values=stored_manual,
            canonical_values=canonical_values,
            canonical_overrides=override_values,
            strict=strict,
        )
        warnings.extend(duplicate_warnings)
        replacements: dict[str, str] = {}
        resolved_values: dict[str, object] = {}
        for match in _SYMBOL_RE.finditer(source_html):
            raw_token = match.group(0)
            inner = str(match.group(1) or "").strip()
            contract_token = _contract_placeholder_token(inner)
            if contract_token is not None and contract_token.binding_kind in {
                "db_index",
                "duplicate",
            }:
                replacements[raw_token] = ""
                continue
            if contract_token is not None and contract_token.binding_kind == "manual":
                symbol = contract_token.canonical_symbol
                manual_value = _manual_lookup(stored_manual, symbol)
                if manual_value is None:
                    message = f"Missing manual symbol: {symbol}"
                    if strict:
                        raise ValueError(message)
                    warnings.append(message)
                    value = ""
                else:
                    value = _escape_text(manual_value)
                replacements[raw_token] = value
                resolved_values[symbol] = value
                continue
            if contract_token is not None and contract_token.binding_kind == "db":
                symbol = _invoice_symbol_key(f"db.{contract_token.namespace}.{contract_token.key}")
            elif contract_token is not None and contract_token.binding_kind == "current":
                symbol = contract_token.canonical_symbol
                value = str(date.today().year) if contract_token.key == "year" else ""
                replacements[raw_token] = _escape_text(value)
                resolved_values[symbol] = value
                continue
            else:
                symbol = _invoice_symbol_key(inner)
            if symbol.startswith("custom."):
                if symbol not in stored_manual:
                    message = f"Missing manual symbol: {symbol}"
                    if strict:
                        raise ValueError(message)
                    warnings.append(message)
                    value = ""
                else:
                    value = _escape_text(stored_manual[symbol])
                replacements[raw_token] = value
                resolved_values[symbol] = value
                continue
            if symbol not in canonical_values:
                message = f"Unsupported invoice template symbol: {symbol}"
                if strict:
                    raise ValueError(message)
                warnings.append(message)
                replacements[raw_token] = ""
                continue
            definition = _CANONICAL_SYMBOLS[symbol]
            value = canonical_values[symbol]
            rendered = (
                str(value)
                if definition.render_mode in {"table", "html_fragment"}
                else _escape_text(value)
            )
            replacements[raw_token] = rendered
            resolved_values[symbol] = rendered
        rendered_html = self._replace_tokens(source_html, replacements)
        snapshot_id = None
        if create_snapshot:
            snapshot_id = self._create_snapshot(
                invoice_id=int(invoice.id),
                template_revision_id=int(revision.id),
                rendered_html=rendered_html,
                resolved_values=resolved_values,
                warnings=tuple(warnings),
            )
        return InvoiceTemplateRenderResult(
            template_revision_id=int(revision.id),
            rendered_html=rendered_html,
            resolved_values=resolved_values,
            warnings=tuple(warnings),
            snapshot_id=snapshot_id,
        )

    def fetch_active_revision(self) -> InvoiceTemplateRevisionRecord | None:
        row = self.conn.execute("""
            SELECT active_revision_id
            FROM InvoiceTemplates
            WHERE archived=0 AND active_revision_id IS NOT NULL
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """).fetchone()
        if not row:
            return None
        return self.fetch_revision(int(row[0]))

    def fetch_revision(self, revision_id: int) -> InvoiceTemplateRevisionRecord | None:
        row = self.conn.execute(
            """
            SELECT
                r.id,
                r.template_id,
                t.name,
                r.revision_label,
                r.source_filename,
                r.html_content,
                r.source_checksum_sha256,
                r.symbol_inventory_json,
                r.validation_status,
                r.validation_error,
                r.created_at,
                r.updated_at
            FROM InvoiceTemplateRevisions r
            INNER JOIN InvoiceTemplates t ON t.id=r.template_id
            WHERE r.id=?
            """,
            (int(revision_id),),
        ).fetchone()
        if not row:
            return None
        return InvoiceTemplateRevisionRecord(
            id=int(row[0]),
            template_id=int(row[1]),
            template_name=str(row[2] or ""),
            revision_label=_clean_text(row[3]),
            source_filename=str(row[4] or ""),
            html_content=str(row[5] or ""),
            source_checksum_sha256=_clean_text(row[6]),
            symbol_inventory_json=_clean_text(row[7]),
            validation_status=str(row[8] or ""),
            validation_error=_clean_text(row[9]),
            created_at=_clean_text(row[10]),
            updated_at=_clean_text(row[11]),
        )

    @staticmethod
    def _is_supported_symbol(symbol: str) -> bool:
        return symbol in _CANONICAL_SYMBOLS or symbol.startswith("custom.")

    @staticmethod
    def _replace_tokens(content: str, replacements: dict[str, str]) -> str:
        rendered = str(content or "")
        for token in sorted(replacements, key=len, reverse=True):
            rendered = rendered.replace(token, replacements[token])
        return rendered

    @staticmethod
    def _duplicate_copy_count(value: object | None, *, strict: bool) -> int | None:
        text = str(value if value is not None else "").strip()
        if not text:
            if strict:
                raise ValueError(
                    "Duplicate Number is required when duplicate block cymbols are present."
                )
            return None
        try:
            number = float(text)
        except ValueError as exc:
            raise ValueError("Duplicate Number must be a whole number.") from exc
        if not number.is_integer():
            raise ValueError("Duplicate Number must be a whole number.")
        count = int(number)
        if count < 0:
            raise ValueError("Duplicate Number cannot be negative.")
        if count > _MAX_DUPLICATE_COPIES:
            raise ValueError(f"Duplicate Number cannot be greater than {_MAX_DUPLICATE_COPIES}.")
        return count

    @staticmethod
    def _indexed_symbols_for_text(text: str, *, binding_kind: str) -> tuple[str, ...]:
        symbols: list[str] = []
        for match in _SYMBOL_RE.finditer(str(text or "")):
            token = _contract_placeholder_token(match.group(1))
            if token is None or token.binding_kind != binding_kind or not token.indexed:
                continue
            symbols.append(token.canonical_symbol)
        return tuple(dict.fromkeys(symbols))

    @staticmethod
    def _render_symbol_value(
        symbol: str,
        value: object,
        *,
        canonical_values: dict[str, object],
    ) -> str:
        definition = _CANONICAL_SYMBOLS.get(symbol)
        if definition is not None and definition.render_mode in {"table", "html_fragment"}:
            return str(value or "")
        if symbol in canonical_values or definition is not None:
            return _escape_text(value)
        return _escape_text(value)

    def _indexed_manual_replacements(
        self,
        *,
        symbols: tuple[str, ...],
        index: int,
        manual_values: dict[str, str],
        strict: bool,
        warnings: list[str],
    ) -> dict[str, str]:
        replacements: dict[str, str] = {}
        for symbol in symbols:
            selection_key = build_contract_template_indexed_selection_key(symbol, index)
            value = manual_values.get(selection_key)
            if value is None:
                message = (
                    f"Indexed manual placeholder {symbol} at Duplicate Index {index} does not "
                    "have a saved value."
                )
                if strict:
                    raise ValueError(message)
                warnings.append(message)
                value = ""
            replacements[symbol] = _escape_text(value)
        return replacements

    def _indexed_db_replacements(
        self,
        *,
        symbols: tuple[str, ...],
        index: int,
        canonical_values: dict[str, object],
        canonical_overrides: dict[str, object],
        strict: bool,
        warnings: list[str],
    ) -> dict[str, str]:
        replacements: dict[str, str] = {}
        for symbol in symbols:
            selection_key = build_contract_template_indexed_selection_key(symbol, index)
            value = canonical_overrides.get(selection_key)
            base_symbol = base_symbol_for_indexed_placeholder(symbol) or symbol
            matched_key = _invoice_symbol_key(base_symbol)
            if value is None and matched_key in canonical_overrides:
                value = canonical_overrides[matched_key]
            if value is None and matched_key in canonical_values:
                value = canonical_values[matched_key]
            if value is None:
                message = (
                    f"Indexed placeholder {symbol} at DB Index {index} does not have "
                    "a selected record."
                )
                if strict:
                    raise ValueError(message)
                warnings.append(message)
                value = ""
            replacements[symbol] = self._render_symbol_value(
                matched_key,
                value,
                canonical_values=canonical_values,
            )
        return replacements

    def _apply_duplicate_controls(
        self,
        html_content: str,
        *,
        manual_values: dict[str, str],
        canonical_values: dict[str, object],
        canonical_overrides: dict[str, object],
        strict: bool,
    ) -> tuple[str, tuple[str, ...]]:
        rendered = str(html_content or "")
        has_start = bool(re.search(r"\{\{\s*duplicate\.start\s*\}\}", rendered, re.IGNORECASE))
        has_end = bool(re.search(r"\{\{\s*duplicate\.end\s*\}\}", rendered, re.IGNORECASE))
        has_number = bool(re.search(r"\{\{\s*duplicate\.number\s*\}\}", rendered, re.IGNORECASE))
        has_db_index = bool(re.search(r"\{\{\s*db\.index\s*\}\}", rendered, re.IGNORECASE))
        if not (has_start or has_end or has_number or has_db_index):
            return rendered, ()
        count = self._duplicate_copy_count(
            manual_values.get(_DUPLICATE_NUMBER_SYMBOL),
            strict=strict,
        )
        warnings: list[str] = []
        matched = False
        missing_count_warning_added = False

        def _replace_block(match: re.Match[str]) -> str:
            nonlocal matched, missing_count_warning_added
            matched = True
            block = str(match.group(1) or "")
            indexed_db_symbols = self._indexed_symbols_for_text(block, binding_kind="db")
            indexed_manual_symbols = self._indexed_symbols_for_text(block, binding_kind="manual")
            if count is None:
                copy_count = 1
                if not missing_count_warning_added:
                    warnings.append(
                        "Duplicate block preview uses one copy until Duplicate Number is set."
                    )
                    missing_count_warning_added = True
            else:
                copy_count = int(count)
            rendered_blocks: list[str] = []
            for index in range(1, copy_count + 1):
                replacements = {
                    _DB_INDEX_SYMBOL: str(index),
                    "{{ db.index }}": str(index),
                }
                replacements.update(
                    self._indexed_db_replacements(
                        symbols=indexed_db_symbols,
                        index=index,
                        canonical_values=canonical_values,
                        canonical_overrides=canonical_overrides,
                        strict=strict,
                        warnings=warnings,
                    )
                )
                replacements.update(
                    self._indexed_manual_replacements(
                        symbols=indexed_manual_symbols,
                        index=index,
                        manual_values=manual_values,
                        strict=strict,
                        warnings=warnings,
                    )
                )
                for token_match in _SYMBOL_RE.finditer(block):
                    token = _contract_placeholder_token(token_match.group(1))
                    if token is None:
                        continue
                    if token.binding_kind == "db_index":
                        replacements[token_match.group(0)] = str(index)
                    elif token.indexed and token.canonical_symbol in replacements:
                        replacements[token_match.group(0)] = replacements[token.canonical_symbol]
                rendered_blocks.append(self._replace_tokens(block, replacements))
            return "".join(rendered_blocks)

        rendered = _DUPLICATE_BLOCK_RE.sub(_replace_block, rendered)
        if (has_start or has_end) and not matched:
            message = "Duplicate cymbols must use {{duplicate.start}} before {{duplicate.end}}."
            if strict:
                raise ValueError(message)
            warnings.append(message)
        rendered = re.sub(r"\{\{\s*duplicate\.start\s*\}\}", "", rendered, flags=re.IGNORECASE)
        rendered = re.sub(r"\{\{\s*duplicate\.end\s*\}\}", "", rendered, flags=re.IGNORECASE)
        rendered = re.sub(r"\{\{\s*duplicate\.number\s*\}\}", "", rendered, flags=re.IGNORECASE)
        rendered = re.sub(r"\{\{\s*db\.index\s*\}\}", "", rendered, flags=re.IGNORECASE)
        return rendered, tuple(dict.fromkeys(warnings))

    def _canonical_values(self, invoice_id: int) -> dict[str, object]:
        invoice = self.invoice_service.fetch_invoice(int(invoice_id))
        if invoice is None:
            raise ValueError(f"Invoice {int(invoice_id)} was not found.")
        settlement = self.reports.invoice_settlement(int(invoice.id))
        party = self._party_values(int(invoice.party_id))
        company = self._company_values()
        return {
            "invoice.number": invoice.invoice_number or invoice.draft_display_id or "",
            "invoice.issue_date": invoice.issue_date or "",
            "invoice.due_date": invoice.due_date or "",
            "invoice.document_status": invoice.document_status,
            "invoice.payment_status": settlement.payment_status,
            "invoice.due_status": settlement.due_status,
            "invoice.currency": invoice.currency,
            "invoice.subtotal": format_money(invoice.subtotal_minor, currency=invoice.currency),
            "invoice.vat_total": format_money(invoice.vat_total_minor, currency=invoice.currency),
            "invoice.total": format_money(invoice.total_minor, currency=invoice.currency),
            "invoice.outstanding_balance": format_money(
                settlement.receivable_balance_minor, currency=invoice.currency
            ),
            "invoice.lines": self._render_lines_table(int(invoice.id), invoice.currency),
            "invoice.vat_breakdown": self._render_vat_breakdown_table(
                int(invoice.id), invoice.currency
            ),
            **party,
            **company,
            "credit_note.number": "",
            "credit_note.reason": "",
            "credit_note.original_invoice_number": invoice.invoice_number or "",
            "royalty.statement_number": "",
            "royalty.payee_name": "",
            "royalty.contract_title": "",
            "royalty.period_start": "",
            "royalty.period_end": "",
            "royalty.gross_royalty": "",
            "royalty.deductions": "",
            "royalty.advance_recouped": "",
            "royalty.net_payable": "",
            "royalty.payment_status": "",
            "royalty.calculation_id": "",
            "royalty.statement_id": "",
        }

    def _party_values(self, party_id: int) -> dict[str, object]:
        row = self.conn.execute(
            """
            SELECT
                legal_name,
                display_name,
                company_name,
                address_line1,
                address_line2,
                street_name,
                street_number,
                city,
                region,
                postal_code,
                country,
                vat_number,
                tax_id,
                email,
                phone,
                bank_account_number,
                chamber_of_commerce_number
            FROM Parties
            WHERE id=?
            """,
            (int(party_id),),
        ).fetchone()
        if not row:
            return {
                "invoice.party.name": "",
                "invoice.party.company_name": "",
                "invoice.party.display_name": "",
                "invoice.party.legal_name": "",
                "invoice.party.address": "",
                "invoice.party.address_line1": "",
                "invoice.party.address_line2": "",
                "invoice.party.street_name": "",
                "invoice.party.street_number": "",
                "invoice.party.postal_code": "",
                "invoice.party.city": "",
                "invoice.party.region": "",
                "invoice.party.country": "",
                "invoice.party.vat_number": "",
                "invoice.party.tax_id": "",
                "invoice.party.email": "",
                "invoice.party.phone": "",
                "invoice.party.bank_account_number": "",
                "invoice.party.chamber_of_commerce_number": "",
            }
        legal_name = str(row[0] or "")
        display_name = str(row[1] or "")
        company_name = str(row[2] or "")
        resolved_name = display_name or company_name or legal_name
        address_line1 = str(row[3] or "")
        address_line2 = str(row[4] or "")
        street_name = str(row[5] or "")
        street_number = str(row[6] or "")
        city = str(row[7] or "")
        region = str(row[8] or "")
        postal_code = str(row[9] or "")
        country = str(row[10] or "")
        street_line = " ".join(
            part for part in (street_name, street_number) if str(part).strip()
        ).strip()
        city_line = " ".join(part for part in (postal_code, city) if str(part).strip()).strip()
        address = "\n".join(
            str(part or "").strip()
            for part in (
                address_line1,
                address_line2,
                street_line,
                city_line,
                region,
                country,
            )
            if str(part or "").strip()
        )
        return {
            "invoice.party.name": resolved_name,
            "invoice.party.company_name": company_name,
            "invoice.party.display_name": display_name,
            "invoice.party.legal_name": legal_name,
            "invoice.party.address": address,
            "invoice.party.address_line1": address_line1,
            "invoice.party.address_line2": address_line2,
            "invoice.party.street_name": street_name,
            "invoice.party.street_number": street_number,
            "invoice.party.postal_code": postal_code,
            "invoice.party.city": city,
            "invoice.party.region": region,
            "invoice.party.country": country,
            "invoice.party.vat_number": str(row[11] or ""),
            "invoice.party.tax_id": str(row[12] or ""),
            "invoice.party.email": str(row[13] or ""),
            "invoice.party.phone": str(row[14] or ""),
            "invoice.party.bank_account_number": str(row[15] or ""),
            "invoice.party.chamber_of_commerce_number": str(row[16] or ""),
        }

    def _company_values(self) -> dict[str, object]:
        try:
            owner = SettingsReadService(self.conn).load_owner_party_settings()
        except Exception:
            owner = None
        if owner is not None and owner.party_id is not None:
            owner_name = (
                owner.company_name or owner.display_name or owner.legal_name or owner.artist_name
            )
            street_line = " ".join(
                part for part in (owner.street_name, owner.street_number) if str(part).strip()
            ).strip()
            address = "\n".join(
                str(part).strip()
                for part in (
                    owner.address_line1,
                    owner.address_line2,
                    street_line,
                    " ".join(
                        part for part in (owner.postal_code, owner.city) if str(part).strip()
                    ).strip(),
                    owner.region,
                    owner.country,
                )
                if str(part).strip()
            )
            return {
                "company.name": owner_name,
                "company.company_name": owner.company_name,
                "company.display_name": owner.display_name,
                "company.legal_name": owner.legal_name,
                "company.address": address,
                "company.address_line1": owner.address_line1,
                "company.address_line2": owner.address_line2,
                "company.street_name": owner.street_name,
                "company.street_number": owner.street_number,
                "company.postal_code": owner.postal_code,
                "company.city": owner.city,
                "company.region": owner.region,
                "company.country": owner.country,
                "company.vat_number": owner.vat_number,
                "company.email": owner.email,
                "company.phone": owner.phone,
                "company.payment_details": owner.bank_account_number,
                "company.chamber_of_commerce_number": owner.chamber_of_commerce_number,
            }
        vat_row = self.conn.execute("SELECT nr FROM BTW ORDER BY id LIMIT 1").fetchone()
        return {
            "company.name": "",
            "company.company_name": "",
            "company.display_name": "",
            "company.legal_name": "",
            "company.address": "",
            "company.address_line1": "",
            "company.address_line2": "",
            "company.street_name": "",
            "company.street_number": "",
            "company.postal_code": "",
            "company.city": "",
            "company.region": "",
            "company.country": "",
            "company.vat_number": str(vat_row[0] or "") if vat_row else "",
            "company.email": "",
            "company.phone": "",
            "company.payment_details": "",
            "company.chamber_of_commerce_number": "",
        }

    def _manual_symbols(self, invoice_id: int) -> dict[str, str]:
        rows = self.conn.execute(
            """
            SELECT symbol_key, value_text
            FROM InvoiceManualSymbols
            WHERE invoice_id=?
            """,
            (int(invoice_id),),
        ).fetchall()
        return {_symbol_key(str(row[0] or "")): str(row[1] or "") for row in rows}

    def _render_lines_table(self, invoice_id: int, currency: str) -> str:
        rows = self.conn.execute(
            """
            SELECT description, quantity_value, quantity_scale, unit_price_minor, vat_amount_minor, gross_amount_minor
            FROM InvoiceLineItems
            WHERE invoice_id=?
            ORDER BY sort_order, id
            """,
            (int(invoice_id),),
        ).fetchall()
        body = "".join(
            "<tr>"
            f"<td>{_escape_text(row[0])}</td>"
            f"<td>{_escape_text(format_quantity(Quantity(int(row[1] or 0), int(row[2] or 0))))}</td>"
            f"<td>{_escape_text(format_money(int(row[3] or 0), currency=currency))}</td>"
            f"<td>{_escape_text(format_money(int(row[4] or 0), currency=currency))}</td>"
            f"<td>{_escape_text(format_money(int(row[5] or 0), currency=currency))}</td>"
            "</tr>"
            for row in rows
        )
        return (
            '<table class="invoice-lines"><thead><tr>'
            "<th>Description</th><th>Quantity</th><th>Unit price</th><th>VAT</th><th>Total</th>"
            f"</tr></thead><tbody>{body}</tbody></table>"
        )

    def _render_vat_breakdown_table(self, invoice_id: int, currency: str) -> str:
        rows = self.conn.execute(
            """
            SELECT vat_treatment, vat_rate_basis_points, taxable_amount_minor, vat_amount_minor, gross_amount_minor
            FROM InvoiceVatBreakdown
            WHERE invoice_id=?
            ORDER BY vat_treatment, vat_rate_basis_points
            """,
            (int(invoice_id),),
        ).fetchall()
        body = "".join(
            "<tr>"
            f"<td>{_escape_text(row[0])}</td>"
            f"<td>{int(row[1] or 0) / 100:.2f}%</td>"
            f"<td>{_escape_text(format_money(int(row[2] or 0), currency=currency))}</td>"
            f"<td>{_escape_text(format_money(int(row[3] or 0), currency=currency))}</td>"
            f"<td>{_escape_text(format_money(int(row[4] or 0), currency=currency))}</td>"
            "</tr>"
            for row in rows
        )
        return (
            '<table class="invoice-vat-breakdown"><thead><tr>'
            "<th>Treatment</th><th>Rate</th><th>Taxable</th><th>VAT</th><th>Gross</th>"
            f"</tr></thead><tbody>{body}</tbody></table>"
        )

    def _create_snapshot(
        self,
        *,
        invoice_id: int,
        template_revision_id: int,
        rendered_html: str,
        resolved_values: dict[str, object],
        warnings: tuple[str, ...],
    ) -> int:
        checksum = hashlib.sha256(rendered_html.encode("utf-8")).hexdigest()
        with self.conn:
            cursor = self.conn.execute(
                """
                INSERT INTO InvoiceTemplateResolvedSnapshots(
                    invoice_id,
                    template_revision_id,
                    resolved_values_json,
                    resolution_warnings_json,
                    rendered_html_content,
                    rendered_checksum_sha256
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    int(invoice_id),
                    int(template_revision_id),
                    json.dumps(resolved_values, sort_keys=True),
                    json.dumps(list(warnings), sort_keys=True),
                    rendered_html,
                    checksum,
                ),
            )
            return int(cursor.lastrowid)

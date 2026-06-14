"""Finalize Template Workspace invoice drafts into ledger-backed invoices."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from isrc_manager.contract_templates.models import (
    ContractTemplateOutputArtifactRecord,
    build_contract_template_selector_scope_key,
)
from isrc_manager.contract_templates.parser import parse_placeholder
from isrc_manager.contract_templates.service import ContractTemplateService
from isrc_manager.file_storage import STORAGE_MODE_DATABASE, normalize_storage_mode

from .invoice_service import InvoiceService
from .models import (
    DEFAULT_CURRENCY,
    InvoiceDraftPayload,
    InvoiceLinePayload,
    InvoiceOutputArtifactRecord,
    InvoiceRecord,
    Quantity,
)
from .money import format_quantity
from .template_service import InvoiceTemplateService

_INVOICE_NUMBER_SYMBOL = "{{db.invoice.number}}"


def _clean_text(value: object | None) -> str | None:
    text = str(value or "").strip()
    return text or None


def _coerce_int(value: object | None) -> int | None:
    try:
        return int(str(value or "").strip())
    except TypeError, ValueError:
        return None


def _selection_key_index(key: object | None) -> int | None:
    text = str(key or "").strip()
    marker = "#index:"
    if marker not in text:
        return None
    _prefix, raw_index = text.rsplit(marker, 1)
    return _coerce_int(raw_index)


def _line_input_quantity(line_input: object | None) -> object | None:
    if isinstance(line_input, dict):
        return line_input.get("quantity")
    return line_input


@dataclass(slots=True)
class FinalizedTemplateInvoiceResult:
    invoice: InvoiceRecord
    final_artifact: InvoiceOutputArtifactRecord
    reused: bool = False


class TemplateWorkspaceInvoiceFinalizationService:
    """Creates immutable accounting records from Template Workspace invoice drafts."""

    def __init__(self, conn: sqlite3.Connection, *, data_root: str | Path | None = None):
        self.conn = conn
        self.data_root = Path(data_root).resolve() if data_root is not None else None
        self.template_service = ContractTemplateService(conn, data_root=self.data_root)
        self.invoice_service = InvoiceService(conn)
        self.invoice_artifacts = InvoiceTemplateService(conn, data_root=self.data_root)

    def finalize_from_pdf_artifact(
        self,
        *,
        draft_id: int,
        pdf_artifact: ContractTemplateOutputArtifactRecord,
        resolved_html_artifact: ContractTemplateOutputArtifactRecord | None = None,
        storage_mode: str = STORAGE_MODE_DATABASE,
        created_by: str | None = None,
    ) -> FinalizedTemplateInvoiceResult:
        clean_storage_mode = normalize_storage_mode(storage_mode, default=STORAGE_MODE_DATABASE)
        if clean_storage_mode is None:
            clean_storage_mode = STORAGE_MODE_DATABASE
        existing = self.invoice_artifacts.fetch_latest_template_invoice_output_artifact(
            contract_template_draft_id=int(draft_id),
            artifact_type="final_pdf",
        )
        linked_invoice: InvoiceRecord | None = None
        if existing is not None and existing.invoice_id is not None:
            invoice = self.invoice_service.fetch_invoice(int(existing.invoice_id))
            if invoice is not None:
                linked_invoice = invoice
                if normalize_storage_mode(existing.storage_mode, default=STORAGE_MODE_DATABASE) == (
                    clean_storage_mode
                ):
                    return FinalizedTemplateInvoiceResult(
                        invoice=invoice,
                        final_artifact=existing,
                        reused=True,
                    )

        draft = self.template_service.fetch_draft(int(draft_id))
        if draft is None:
            raise ValueError(f"Template draft {int(draft_id)} was not found.")
        payload = self.template_service.fetch_draft_payload(int(draft_id))
        if not isinstance(payload, dict):
            raise ValueError("Template draft payload is empty or invalid.")
        invoice_payload = self._invoice_payload_from_template_payload(
            draft_id=int(draft_id),
            payload=payload,
            scope_entity_type=draft.scope_entity_type,
            scope_entity_id=draft.scope_entity_id,
        )
        registry_entry_id: int | None = None
        invoice_number: str | None = None
        assignment = self.template_service.fetch_draft_registry_assignment(
            int(draft_id),
            _INVOICE_NUMBER_SYMBOL,
        )
        if assignment is not None:
            registry_entry_id = int(assignment.registry_entry_id)
            invoice_number = assignment.registry_value
            existing_invoice = self.invoice_service.fetch_invoice_by_registry_entry_id(
                registry_entry_id
            )
            if existing_invoice is not None:
                invoice = existing_invoice
            elif linked_invoice is not None:
                invoice = linked_invoice
            else:
                invoice = self.invoice_service.create_draft_invoice(invoice_payload)
        else:
            invoice = linked_invoice or self.invoice_service.create_draft_invoice(invoice_payload)
        if invoice.document_status == "draft":
            invoice = self.invoice_service.issue_invoice(
                int(invoice.id),
                command_key=f"template-workspace-invoice-final-{int(draft_id)}",
                registry_entry_id=registry_entry_id,
                invoice_number=invoice_number,
                created_by=created_by,
            )
        if invoice.document_status != "issued":
            raise ValueError("Only issued template invoices can be stored as final.")

        rendered_html = self._read_artifact_text(resolved_html_artifact)
        snapshot_values, snapshot_warnings, snapshot_checksum = self._contract_snapshot_payload(
            int(pdf_artifact.snapshot_id)
        )
        invoice_snapshot_id = self.invoice_artifacts.create_external_snapshot(
            invoice_id=int(invoice.id),
            resolved_values=snapshot_values,
            resolution_warnings=snapshot_warnings,
            rendered_html_content=rendered_html,
            rendered_checksum_sha256=snapshot_checksum,
        )
        pdf_bytes = self._read_artifact_bytes(pdf_artifact)
        filename = f"{invoice.invoice_number or f'invoice-{invoice.id}'}.pdf"
        final_artifact = self.invoice_artifacts.create_output_artifact_from_bytes(
            snapshot_id=invoice_snapshot_id,
            artifact_bytes=pdf_bytes,
            output_filename=filename,
            mime_type=pdf_artifact.mime_type or "application/pdf",
            artifact_type="final_pdf",
            status="final",
            storage_mode=clean_storage_mode,
            contract_template_draft_id=int(draft_id),
            contract_template_snapshot_id=int(pdf_artifact.snapshot_id),
            contract_template_artifact_id=int(pdf_artifact.artifact_id),
        )
        self._mark_draft_final(int(draft_id))
        return FinalizedTemplateInvoiceResult(invoice=invoice, final_artifact=final_artifact)

    def _invoice_payload_from_template_payload(
        self,
        *,
        draft_id: int,
        payload: dict[str, object],
        scope_entity_type: str | None,
        scope_entity_id: str | None,
    ) -> InvoiceDraftPayload:
        db_selections = dict(payload.get("db_selections") or {})
        invoice_line_inputs = dict(payload.get("invoice_line_inputs") or {})
        party_id = self._party_id_from_payload(
            db_selections=db_selections,
            scope_entity_type=scope_entity_type,
            scope_entity_id=scope_entity_id,
        )
        if party_id is None:
            raise ValueError(
                "Select a buyer/customer party in the Template Workspace before marking "
                "the invoice final. Use party cymbols such as {{db.party.display_name}} "
                "for the buyer."
            )
        lines = self._invoice_lines_from_payload(
            draft_id=draft_id,
            db_selections=db_selections,
            invoice_line_inputs=invoice_line_inputs,
        )
        if not lines:
            raise ValueError(
                "No invoice catalog item rows were found in the template draft. "
                "Use indexed invoice-line catalog cymbols and select at least one item."
            )
        currency = self._invoice_currency_for_lines(lines)
        return InvoiceDraftPayload(
            party_id=party_id,
            issue_date=self._manual_date_value(payload, ("issue_date", "invoice_date", "date")),
            due_date=self._manual_date_value(payload, ("due_date", "payment_due")),
            currency=currency,
            created_by="template_workspace",
            lines=tuple(lines),
        )

    def _party_id_from_payload(
        self,
        *,
        db_selections: dict[str, object],
        scope_entity_type: str | None,
        scope_entity_id: str | None,
    ) -> int | None:
        if str(scope_entity_type or "").strip().lower() == "party":
            scoped_party_id = _coerce_int(scope_entity_id)
            if self._party_exists(scoped_party_id):
                return scoped_party_id
        party_scope_prefix = build_contract_template_selector_scope_key(
            "party",
            "party_selection_required",
        )
        for key, value in db_selections.items():
            clean_key = str(key or "").strip()
            if clean_key.startswith("db_scope.party.") or clean_key == party_scope_prefix:
                party_id = _coerce_int(value)
                if self._party_exists(party_id):
                    return party_id
        for key, value in db_selections.items():
            base_key = str(key or "").strip().rsplit("#index:", 1)[0]
            try:
                token = parse_placeholder(base_key)
            except ValueError:
                continue
            if token.binding_kind == "db" and token.namespace == "party":
                party_id = _coerce_int(value)
                if self._party_exists(party_id):
                    return party_id
        return None

    def _party_exists(self, party_id: int | None) -> bool:
        if party_id is None:
            return False
        row = self.conn.execute("SELECT 1 FROM Parties WHERE id=?", (int(party_id),)).fetchone()
        return row is not None

    def _invoice_lines_from_payload(
        self,
        *,
        draft_id: int,
        db_selections: dict[str, object],
        invoice_line_inputs: dict[str, object],
    ) -> list[InvoiceLinePayload]:
        grouped: dict[str, tuple[int, int, object | None]] = {}
        for selection_key, selection_value in db_selections.items():
            clean_key = str(selection_key or "").strip()
            base_key = clean_key.rsplit("#index:", 1)[0]
            try:
                token = parse_placeholder(base_key)
            except ValueError:
                continue
            if token.binding_kind != "db" or token.namespace != "invoice_line":
                continue
            record_id = _coerce_int(selection_value)
            if record_id is None:
                continue
            index = _selection_key_index(clean_key)
            group_key = f"index:{index}" if index is not None else "single"
            if group_key in grouped:
                continue
            grouped[group_key] = (
                index or 0,
                record_id,
                self._invoice_line_input_for_selection_key(clean_key, invoice_line_inputs),
            )

        lines: list[InvoiceLinePayload] = []
        for _index, catalog_item_id, line_input in sorted(
            grouped.values(), key=lambda item: item[0]
        ):
            item = self.invoice_service.catalog_service.fetch_item(int(catalog_item_id))
            if item is None:
                raise ValueError(f"Invoice catalog item {int(catalog_item_id)} was not found.")
            quantity = _line_input_quantity(line_input) or format_quantity(
                Quantity(item.default_quantity_value, item.default_quantity_scale)
            )
            lines.append(
                InvoiceLinePayload(
                    description=item.description or item.name,
                    quantity=str(quantity),
                    unit_price_minor=0,
                    vat_treatment=item.default_vat_treatment,
                    vat_rate_basis_points=0,
                    vat_country_code=item.vat_country_code,
                    ledger_account_code=item.default_account_code,
                    catalog_item_id=item.id,
                    source_type="template_workspace_invoice",
                    source_id=draft_id,
                )
            )
        return lines

    def _invoice_line_input_for_selection_key(
        self,
        selection_key: object,
        invoice_line_inputs: dict[str, object],
    ) -> object | None:
        clean_key = str(selection_key or "").strip()
        if clean_key in invoice_line_inputs:
            return invoice_line_inputs[clean_key]
        index = _selection_key_index(clean_key)
        if index is None:
            return None
        for candidate_key, candidate_value in invoice_line_inputs.items():
            if _selection_key_index(candidate_key) == index:
                return candidate_value
        return None

    def _invoice_currency_for_lines(self, lines: list[InvoiceLinePayload]) -> str:
        currencies: list[str] = []
        for line in lines:
            if line.catalog_item_id is None:
                continue
            item = self.invoice_service.catalog_service.fetch_item(int(line.catalog_item_id))
            if item is not None and item.currency:
                currencies.append(item.currency)
        unique = tuple(dict.fromkeys(currencies))
        if len(unique) > 1:
            raise ValueError("All invoice catalog rows must use one currency before finalization.")
        return unique[0] if unique else DEFAULT_CURRENCY

    def _manual_date_value(
        self,
        payload: dict[str, object],
        hints: tuple[str, ...],
    ) -> str | None:
        manual_values = dict(payload.get("manual_values") or {})
        for key, value in manual_values.items():
            clean_key = str(key or "").strip().lower()
            if all("due" not in hint for hint in hints) and "due" in clean_key:
                continue
            if any(hint in clean_key for hint in hints):
                return _clean_text(value)
        return None

    def _contract_snapshot_payload(
        self,
        snapshot_id: int,
    ) -> tuple[object, object | None, str | None]:
        row = self.conn.execute(
            """
            SELECT resolved_values_json, resolution_warnings_json, resolved_checksum_sha256
            FROM ContractTemplateResolvedSnapshots
            WHERE id=?
            """,
            (int(snapshot_id),),
        ).fetchone()
        if not row:
            return {}, None, None
        return (
            self._json_payload(row[0], default={}),
            self._json_payload(row[1], default=None),
            _clean_text(row[2]),
        )

    @staticmethod
    def _json_payload(value: object | None, *, default: object) -> object:
        text = _clean_text(value)
        if text is None:
            return default
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return default

    @staticmethod
    def _read_artifact_bytes(artifact: ContractTemplateOutputArtifactRecord) -> bytes:
        path = Path(artifact.output_path)
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(str(path))
        return path.read_bytes()

    @staticmethod
    def _read_artifact_text(
        artifact: ContractTemplateOutputArtifactRecord | None,
    ) -> str | None:
        if artifact is None:
            return None
        path = Path(artifact.output_path)
        if not path.exists() or not path.is_file():
            return None
        return path.read_text(encoding="utf-8")

    def _mark_draft_final(self, draft_id: int) -> None:
        with self.conn:
            self.conn.execute(
                """
                UPDATE ContractTemplateDrafts
                SET status='final',
                    updated_at=datetime('now')
                WHERE id=?
                """,
                (int(draft_id),),
            )

import sqlite3
from pathlib import Path

import pytest

from isrc_manager.code_registry import (
    BUILTIN_CATEGORY_INVOICE_NUMBER,
    BUILTIN_CATEGORY_ROYALTY_STATEMENT_NUMBER,
    CodeRegistryService,
)
from isrc_manager.contract_templates.accounting_resolver import AccountingTemplateResolver
from isrc_manager.contract_templates.catalog import ContractTemplateCatalogService
from isrc_manager.contract_templates.export_service import (
    ContractTemplateExportError,
    ContractTemplateExportService,
)
from isrc_manager.contract_templates.form_service import ContractTemplateFormService
from isrc_manager.contract_templates.models import (
    ContractTemplateDraftPayload,
    ContractTemplatePayload,
    ContractTemplateRevisionPayload,
    build_contract_template_indexed_selection_key,
)
from isrc_manager.contract_templates.service import ContractTemplateService
from isrc_manager.invoicing import (
    InvoiceCatalogItemPayload,
    InvoiceDraftPayload,
    InvoiceLinePayload,
    InvoiceService,
    RoyaltyAccountingService,
    RoyaltyCalculationLinePayload,
    RoyaltyCalculationPayload,
)
from isrc_manager.invoicing.ledger_service import ensure_default_accounts
from isrc_manager.invoicing.template_workspace_finalization import (
    TemplateWorkspaceInvoiceFinalizationService,
)
from isrc_manager.parties import PartyPayload, PartyService
from isrc_manager.services import DatabaseSchemaService


class _FakeHtmlPdfAdapter:
    adapter_name = "fake_html_pdf"

    def render_file_to_pdf(self, source: Path, target: Path) -> None:
        target.write_bytes(b"%PDF-1.4\n%fake\n")


def _connection(tmp_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    schema = DatabaseSchemaService(conn, data_root=tmp_path)
    schema.init_db()
    schema.migrate_schema()
    ensure_default_accounts(conn)
    CodeRegistryService(conn)
    conn.execute(
        "UPDATE CodeRegistryCategories SET prefix='INV', normalized_prefix='INV' WHERE system_key=?",
        (BUILTIN_CATEGORY_INVOICE_NUMBER,),
    )
    conn.execute(
        "UPDATE CodeRegistryCategories SET prefix='ROY', normalized_prefix='ROY' WHERE system_key=?",
        (BUILTIN_CATEGORY_ROYALTY_STATEMENT_NUMBER,),
    )
    conn.commit()
    return conn


def _template_stack(conn: sqlite3.Connection, tmp_path: Path):
    catalog = ContractTemplateCatalogService(conn)
    template_service = ContractTemplateService(conn, data_root=tmp_path)
    resolver = AccountingTemplateResolver(conn)
    party_service = PartyService(conn)
    form_service = ContractTemplateFormService(
        template_service=template_service,
        catalog_service=catalog,
        accounting_resolver=resolver,
        party_service=party_service,
    )
    export_service = ContractTemplateExportService(
        template_service=template_service,
        catalog_service=catalog,
        accounting_resolver=resolver,
        party_service=party_service,
        html_pdf_adapter=_FakeHtmlPdfAdapter(),
    )
    return catalog, template_service, form_service, export_service


def _import_html_template(
    template_service: ContractTemplateService,
    tmp_path: Path,
    *,
    family: str,
    name: str,
    html: str,
):
    template = template_service.create_template(
        ContractTemplatePayload(name=name, template_family=family, source_format="html")
    )
    source_path = tmp_path / f"{name.lower().replace(' ', '-')}.html"
    source_path.write_text(html, encoding="utf-8")
    return template_service.import_revision_from_path(
        template.template_id,
        source_path,
        payload=ContractTemplateRevisionPayload(
            source_filename=source_path.name,
            source_format="html",
        ),
    ).revision


def _invoice(conn: sqlite3.Connection):
    party_id = PartyService(conn).create_party(
        PartyPayload(
            legal_name="Venue Legal BV",
            display_name="Venue",
            company_name="Venue Company BV",
            party_type="organization",
            email="venue@example.test",
            address_line1="Street 1",
            city="Amsterdam",
            country="NL",
            vat_number="NL-VENUE",
        )
    )
    return InvoiceService(conn).create_draft_invoice(
        InvoiceDraftPayload(
            party_id=party_id,
            due_date="2026-02-01",
            lines=(
                InvoiceLinePayload(
                    description="Venue <service>",
                    quantity="1",
                    unit_price_minor=10_000,
                    vat_rate_basis_points=2100,
                ),
            ),
        )
    )


def test_invoice_template_context_resolves_drafts_without_issuing_numbers(tmp_path: Path):
    conn = _connection(tmp_path)
    _, template_service, form_service, export_service = _template_stack(conn, tmp_path)
    invoice = _invoice(conn)
    revision = _import_html_template(
        template_service,
        tmp_path,
        family="invoice",
        name="Invoice Template",
        html=(
            "<html><body>{{db.invoice.number}} {{db.invoice.party_name}} "
            "{{db.invoice.total}} {{db.invoice.lines}}</body></html>"
        ),
    )

    definition = form_service.build_form_definition(revision.revision_id)
    assert definition.selector_fields[0].scope_entity_type == "invoice"
    assert definition.selector_fields[0].choices[0].value == str(invoice.id)

    payload = {
        "revision_id": revision.revision_id,
        "db_selections": {
            "{{db.invoice.number}}": str(invoice.id),
            "{{db.invoice.party_name}}": str(invoice.id),
            "{{db.invoice.total}}": str(invoice.id),
            "{{db.invoice.lines}}": str(invoice.id),
        },
        "manual_values": {},
        "type_overrides": {},
    }
    values, warnings = export_service._resolve_payload_values(
        revision.revision_id,
        payload,
        strict=False,
    )

    assert values["{{db.invoice.number}}"] == invoice.draft_display_id
    assert "Venue" in values["{{db.invoice.party_name}}"]
    assert "EUR 121.00" == values["{{db.invoice.total}}"]
    assert "invoice-lines" in values["{{db.invoice.lines}}"]
    assert "Venue &lt;service&gt;" in values["{{db.invoice.lines}}"]
    assert warnings == (
        "Invoice number is showing the draft display ID; issue the invoice before strict export.",
    )
    assert InvoiceService(conn).fetch_invoice(invoice.id).invoice_number is None

    with pytest.raises(
        ContractTemplateExportError, match="only available after the invoice is issued"
    ):
        export_service._resolve_payload_values(revision.revision_id, payload, strict=True)

    issued = InvoiceService(conn).issue_invoice(invoice.id, command_key="issue-template-test")
    strict_values, strict_warnings = export_service._resolve_payload_values(
        revision.revision_id,
        payload,
        strict=True,
    )
    assert strict_values["{{db.invoice.number}}"] == issued.invoice_number
    assert strict_warnings == ()
    conn.close()


def test_indexed_invoice_line_template_uses_catalog_items_and_calculated_totals(tmp_path: Path):
    conn = _connection(tmp_path)
    _catalog, template_service, form_service, export_service = _template_stack(conn, tmp_path)
    invoice_service = InvoiceService(conn)
    mastering_id = invoice_service.catalog_service.create_item(
        InvoiceCatalogItemPayload(
            name="Mastering",
            description="Mastering <service>",
            default_unit_price_minor=10_000,
            default_vat_rate_basis_points=2100,
            default_account_code="4100",
            currency="USD",
        )
    )
    artwork_id = invoice_service.catalog_service.create_item(
        InvoiceCatalogItemPayload(
            name="Artwork",
            description="Cover artwork",
            default_unit_price_minor=5_000,
            default_vat_rate_basis_points=900,
            default_account_code="4200",
            currency="USD",
        )
    )
    revision = _import_html_template(
        template_service,
        tmp_path,
        family="invoice",
        name="Dynamic Invoice Lines",
        html=(
            "<html><body><table><tbody>{{duplicate.start}}"
            "<tr><td>{{db.index}}</td>"
            "<td>{{db.invoice_line.description.indexed}}</td>"
            "<td>{{db.invoice_line.quantity.indexed}}</td>"
            "<td>{{db.invoice_line.unit_price.indexed}}</td>"
            "<td>{{db.invoice_line.net_amount.indexed}}</td>"
            "<td>{{db.invoice_line.vat_rate.indexed}}</td>"
            "<td>{{db.invoice_line.vat_amount.indexed}}</td>"
            "<td>{{db.invoice_line.gross_amount.indexed}}</td></tr>"
            "{{duplicate.end}}</tbody></table>"
            "<p>Subtotal {{db.invoice.subtotal}}</p>"
            "<p>VAT {{db.invoice.vat_total}}</p>"
            "<p>Total {{db.invoice.total}}</p>"
            "{{db.invoice.vat_breakdown}}{{duplicate.number}}</body></html>"
        ),
    )
    definition = form_service.build_form_definition(revision.revision_id)

    assert definition.indexed_selector_fields[0].scope_entity_type == "invoice_catalog_item"
    assert {choice.value for choice in definition.indexed_selector_fields[0].choices} == {
        str(mastering_id),
        str(artwork_id),
    }
    assert {field.canonical_symbol: field.source_label for field in definition.auto_fields}[
        "{{db.invoice.total}}"
    ] == "Calculated Invoice Lines"

    line_symbols = (
        "{{db.invoice_line.description.indexed}}",
        "{{db.invoice_line.quantity.indexed}}",
        "{{db.invoice_line.unit_price.indexed}}",
        "{{db.invoice_line.net_amount.indexed}}",
        "{{db.invoice_line.vat_rate.indexed}}",
        "{{db.invoice_line.vat_amount.indexed}}",
        "{{db.invoice_line.gross_amount.indexed}}",
    )
    db_selections = {}
    for symbol in line_symbols:
        db_selections[build_contract_template_indexed_selection_key(symbol, 1)] = str(mastering_id)
        db_selections[build_contract_template_indexed_selection_key(symbol, 2)] = str(artwork_id)
    draft = template_service.create_draft(
        ContractTemplateDraftPayload(
            revision_id=revision.revision_id,
            name="Dynamic Invoice Draft",
            editable_payload={
                "revision_id": revision.revision_id,
                "db_selections": db_selections,
                "invoice_line_inputs": {
                    build_contract_template_indexed_selection_key(
                        "{{db.invoice_line.description.indexed}}", 1
                    ): {"quantity": "2"},
                    build_contract_template_indexed_selection_key(
                        "{{db.invoice_line.description.indexed}}", 2
                    ): {"quantity": "3"},
                },
                "manual_values": {"{{duplicate.number}}": 2},
                "type_overrides": {},
            },
            storage_mode="database",
        )
    )

    result = export_service.export_draft_to_pdf(draft.draft_id)
    rendered_html = Path(result.resolved_html_artifact.output_path).read_text(encoding="utf-8")

    assert "Mastering &lt;service&gt;" in rendered_html
    assert "Cover artwork" in rendered_html
    assert "<td>2</td>" in rendered_html
    assert "<td>3</td>" in rendered_html
    assert "21%" in rendered_html
    assert "9%" in rendered_html
    assert "USD 200.00" in rendered_html
    assert "USD 42.00" in rendered_html
    assert "USD 150.00" in rendered_html
    assert "USD 13.50" in rendered_html
    assert "Subtotal USD 350.00" in rendered_html
    assert "VAT USD 55.50" in rendered_html
    assert "Total USD 405.50" in rendered_html
    assert '<table class="invoice-vat-breakdown">' in rendered_html
    assert "&lt;table class=&quot;invoice-vat-breakdown&quot;" not in rendered_html
    assert "{{db.invoice_line.description.indexed}}" not in rendered_html
    conn.close()


def test_template_workspace_invoice_finalization_posts_ledger_and_stores_artifact(
    tmp_path: Path,
):
    conn = _connection(tmp_path)
    _catalog, template_service, _form_service, export_service = _template_stack(conn, tmp_path)
    party_id = PartyService(conn).create_party(
        PartyPayload(
            legal_name="Buyer Legal BV",
            display_name="Buyer",
            party_type="organization",
        )
    )
    catalog_item_id = InvoiceService(conn).catalog_service.create_item(
        InvoiceCatalogItemPayload(
            name="DJ performance",
            description="DJ set hourly rate",
            default_unit_price_minor=15_000,
            default_vat_rate_basis_points=900,
            default_account_code="4100",
            currency="EUR",
        )
    )
    revision = _import_html_template(
        template_service,
        tmp_path,
        family="invoice",
        name="Final Template Invoice",
        html=(
            "<html><body>"
            "<p>{{db.invoice.number}}</p>"
            "<p>{{db.party.display_name}}</p>"
            "<p>{{db.invoice.currency}}</p>"
            "<p>{{db.invoice.total}}</p>"
            "{{duplicate.start}}"
            "<p>{{db.invoice_line.description.indexed}} "
            "{{db.invoice_line.quantity.indexed}} "
            "{{db.invoice_line.gross_amount.indexed}}</p>"
            "{{duplicate.end}}{{duplicate.number}}"
            "</body></html>"
        ),
    )
    line_key = build_contract_template_indexed_selection_key(
        "{{db.invoice_line.description.indexed}}",
        1,
    )
    draft = template_service.create_draft(
        ContractTemplateDraftPayload(
            revision_id=revision.revision_id,
            name="Final Invoice Draft",
            editable_payload={
                "revision_id": revision.revision_id,
                "db_selections": {
                    "db_scope.party.party_selection_required": str(party_id),
                    line_key: str(catalog_item_id),
                },
                "invoice_line_inputs": {line_key: {"quantity": "2"}},
                "manual_values": {"{{duplicate.number}}": 1},
                "type_overrides": {},
            },
            storage_mode="database",
        )
    )

    export_result = export_service.export_draft_to_pdf(draft.draft_id)
    finalizer = TemplateWorkspaceInvoiceFinalizationService(conn, data_root=tmp_path)
    managed = finalizer.finalize_from_pdf_artifact(
        draft_id=draft.draft_id,
        pdf_artifact=export_result.pdf_artifact,
        resolved_html_artifact=export_result.resolved_html_artifact,
        storage_mode="managed_file",
    )

    invoice = managed.invoice
    assignment = template_service.fetch_draft_registry_assignment(
        draft.draft_id,
        "{{db.invoice.number}}",
    )
    assert assignment is not None
    assert invoice.document_status == "issued"
    assert invoice.invoice_number == assignment.registry_value
    assert invoice.issued_ledger_transaction_id is not None
    assert invoice.total_minor == 32_700
    assert managed.final_artifact.artifact_type == "final_pdf"
    assert managed.final_artifact.status == "final"
    assert managed.final_artifact.storage_mode == "managed_file"
    assert managed.final_artifact.contract_template_draft_id == draft.draft_id
    assert (
        managed.final_artifact.contract_template_artifact_id
        == export_result.pdf_artifact.artifact_id
    )
    managed_path = finalizer.invoice_artifacts.materialize_output_artifact(
        managed.final_artifact.id
    )
    assert managed_path.exists()

    reused = finalizer.finalize_from_pdf_artifact(
        draft_id=draft.draft_id,
        pdf_artifact=export_result.pdf_artifact,
        resolved_html_artifact=export_result.resolved_html_artifact,
        storage_mode="managed_file",
    )
    assert reused.reused is True
    assert reused.invoice.id == invoice.id

    embedded = finalizer.finalize_from_pdf_artifact(
        draft_id=draft.draft_id,
        pdf_artifact=export_result.pdf_artifact,
        resolved_html_artifact=export_result.resolved_html_artifact,
        storage_mode="database",
    )
    assert embedded.invoice.id == invoice.id
    assert embedded.final_artifact.storage_mode == "database"
    assert embedded.final_artifact.content_blob
    assert conn.execute("SELECT COUNT(*) FROM Invoices").fetchone()[0] == 1
    conn.close()


def test_invoice_template_export_persists_invoice_scope_on_snapshot(tmp_path: Path):
    conn = _connection(tmp_path)
    _, template_service, _form_service, export_service = _template_stack(conn, tmp_path)
    issued = InvoiceService(conn).issue_invoice(_invoice(conn).id, command_key="issue-export-test")
    revision = _import_html_template(
        template_service,
        tmp_path,
        family="invoice",
        name="Invoice Export",
        html="<html><body>{{db.invoice.number}} {{db.invoice.vat_breakdown}}</body></html>",
    )
    draft = template_service.create_draft(
        ContractTemplateDraftPayload(
            revision_id=revision.revision_id,
            name="Invoice Draft",
            editable_payload={
                "revision_id": revision.revision_id,
                "db_selections": {
                    "{{db.invoice.number}}": str(issued.id),
                    "{{db.invoice.vat_breakdown}}": str(issued.id),
                },
                "manual_values": {},
                "type_overrides": {},
            },
            scope_entity_type="invoice",
            scope_entity_id=str(issued.id),
            storage_mode="database",
        )
    )

    result = export_service.export_draft_to_pdf(draft.draft_id)

    assert result.snapshot.scope_entity_type == "invoice"
    assert result.snapshot.scope_entity_id == str(issued.id)
    assert result.resolved_html_artifact is not None
    resolved_html = Path(result.resolved_html_artifact.output_path).read_text(encoding="utf-8")
    assignments = template_service.list_draft_registry_assignments(draft.draft_id)
    assignment_values = {
        assignment.canonical_symbol: assignment.registry_value for assignment in assignments
    }
    generated_invoice_number = assignment_values["{{db.invoice.number}}"]
    assert generated_invoice_number.startswith("INV")
    assert generated_invoice_number in resolved_html
    assert issued.invoice_number not in resolved_html
    assert '<table class="invoice-vat-breakdown">' in resolved_html
    assert "&lt;table class=&quot;invoice-vat-breakdown&quot;" not in resolved_html
    conn.close()


def test_royalty_statement_template_resolves_statement_values_and_lines(tmp_path: Path):
    conn = _connection(tmp_path)
    catalog, template_service, form_service, export_service = _template_stack(conn, tmp_path)
    party_id = PartyService(conn).create_party(
        PartyPayload(
            legal_name="Writer Legal",
            display_name="Writer",
            party_type="artist",
        )
    )
    royalty_service = RoyaltyAccountingService(conn)
    calculation = royalty_service.create_calculation(
        RoyaltyCalculationPayload(
            party_id=party_id,
            period_start="2026-01-01",
            period_end="2026-03-31",
            lines=(
                RoyaltyCalculationLinePayload(
                    description="Streaming <income>",
                    net_payable_minor=12_345,
                    source_type="streaming",
                    source_id="DSP-1",
                ),
            ),
        )
    )
    royalty_service.approve_and_post_calculation(calculation.id, command_key="post-royalty")
    statement = royalty_service.generate_statement(
        calculation.id,
        command_key="statement-royalty",
        issue_date="2026-04-15",
    )
    revision = _import_html_template(
        template_service,
        tmp_path,
        family="royalty_statement",
        name="Royalty Statement",
        html=(
            "<html><body>{{db.royalty.statement_number}} {{db.royalty.payee_name}} "
            "{{db.royalty.net_payable}} {{db.royalty.lines}}</body></html>"
        ),
    )

    assert "{{db.royalty.lines}}" in {
        entry.canonical_symbol for entry in catalog.list_known_symbols()
    }
    definition = form_service.build_form_definition(revision.revision_id)
    assert definition.selector_fields[0].scope_entity_type == "royalty_statement"
    assert definition.selector_fields[0].choices[0].value == str(statement.id)

    payload = {
        "revision_id": revision.revision_id,
        "db_selections": {
            "{{db.royalty.statement_number}}": str(statement.id),
            "{{db.royalty.payee_name}}": str(statement.id),
            "{{db.royalty.net_payable}}": str(statement.id),
            "{{db.royalty.lines}}": str(statement.id),
        },
        "manual_values": {},
        "type_overrides": {},
    }
    values, warnings = export_service._resolve_payload_values(
        revision.revision_id,
        payload,
        strict=True,
    )

    assert values["{{db.royalty.statement_number}}"] == statement.statement_number
    assert values["{{db.royalty.payee_name}}"] == "Writer"
    assert values["{{db.royalty.net_payable}}"] == "EUR 123.45"
    assert "royalty-lines" in values["{{db.royalty.lines}}"]
    assert "Streaming &lt;income&gt;" in values["{{db.royalty.lines}}"]
    assert warnings == ()
    conn.close()

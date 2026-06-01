import sqlite3

import pytest

from isrc_manager.code_registry import BUILTIN_CATEGORY_INVOICE_NUMBER, CodeRegistryService
from isrc_manager.contract_templates.models import build_contract_template_indexed_selection_key
from isrc_manager.invoicing import (
    InvoiceDraftPayload,
    InvoiceLinePayload,
    InvoiceService,
    InvoiceTemplateService,
)
from isrc_manager.invoicing.template_service import (
    _DB_INDEX_SYMBOL,
    _DUPLICATE_NUMBER_SYMBOL,
    _contract_placeholder_token,
    _invoice_symbol_key,
    _manual_lookup,
    _manual_symbol_key,
)
from isrc_manager.parties import PartyPayload, PartyService
from isrc_manager.services import DatabaseSchemaService


def _connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    schema = DatabaseSchemaService(conn)
    schema.init_db()
    schema.migrate_schema()
    CodeRegistryService(conn)
    conn.execute(
        """
        UPDATE CodeRegistryCategories
        SET prefix='INV', normalized_prefix='INV'
        WHERE system_key=?
        """,
        (BUILTIN_CATEGORY_INVOICE_NUMBER,),
    )
    conn.execute("INSERT INTO BTW(id, nr) VALUES (1, 'NL-COMPANY')")
    conn.commit()
    return conn


def _invoice_id(conn: sqlite3.Connection) -> int:
    party_id = PartyService(conn).create_party(
        PartyPayload(
            legal_name="Venue Legal BV",
            display_name="Venue",
            company_name="Venue Company BV",
            party_type="organization",
            email="venue@example.test",
            address_line1="Street 1",
            street_name="Damrak",
            street_number="12",
            postal_code="1012 LG",
            city="Amsterdam",
            country="NL",
            vat_number="NL-VENUE",
        )
    )
    invoice_service = InvoiceService(conn)
    draft = invoice_service.create_draft_invoice(
        InvoiceDraftPayload(
            party_id=party_id,
            due_date="2026-02-01",
            lines=(
                InvoiceLinePayload(
                    description="Venue service",
                    quantity="1",
                    unit_price_minor=10_000,
                    vat_rate_basis_points=2100,
                ),
            ),
        )
    )
    return invoice_service.issue_invoice(draft.id, command_key="issue-template-invoice").id


def test_template_preview_and_export_share_render_path_and_escape_manual_symbols():
    conn = _connection()
    invoice_id = _invoice_id(conn)
    service = InvoiceTemplateService(conn)
    revision = service.upload_html_template(
        name="Standard invoice",
        html_content="""
        <html><body>
            <h1>{{ invoice.number }}</h1>
            <p>{{ invoice.party.name }} {{ invoice.party.vat_number }}</p>
            <p>{{ company.vat_number }}</p>
            <p>{{ invoice.total }} / {{ invoice.outstanding_balance }}</p>
            {{ invoice.lines }}
            {{ invoice.vat_breakdown }}
            <footer>{{ custom.footer_note }}</footer>
        </body></html>
        """,
    )
    service.set_manual_symbols(
        invoice_id=invoice_id,
        template_revision_id=revision.id,
        values={"custom.footer_note": "<strong>Pay within 14 days</strong>"},
    )

    preview = service.preview_invoice(invoice_id)
    exported = service.export_invoice_html(invoice_id)
    artifact = service.create_html_output_artifact(snapshot_id=exported.snapshot_id or 0)
    snapshot = conn.execute(
        """
        SELECT rendered_html_content, resolved_values_json
        FROM InvoiceTemplateResolvedSnapshots
        WHERE id=?
        """,
        (exported.snapshot_id,),
    ).fetchone()

    assert preview.warnings == ()
    assert exported.warnings == ()
    assert preview.rendered_html == exported.rendered_html
    assert exported.snapshot_id is not None
    assert artifact.snapshot_id == exported.snapshot_id
    assert artifact.artifact_type == "html"
    assert artifact.mime_type == "text/html; charset=utf-8"
    assert artifact.size_bytes == len(exported.rendered_html.encode("utf-8"))
    assert snapshot[0] == exported.rendered_html
    assert "EUR 121.00 / EUR 121.00" in exported.rendered_html
    assert "Venue service" in exported.rendered_html
    assert "invoice-lines" in exported.rendered_html
    assert "invoice-vat-breakdown" in exported.rendered_html
    assert "NL-COMPANY" in exported.rendered_html
    assert "&lt;strong&gt;Pay within 14 days&lt;/strong&gt;" in exported.rendered_html
    assert "<strong>Pay within 14 days</strong>" not in exported.rendered_html

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "UPDATE InvoiceTemplateResolvedSnapshots SET rendered_html_content='changed' WHERE id=?",
            (exported.snapshot_id,),
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "UPDATE InvoiceOutputArtifacts SET output_filename='changed.html' WHERE id=?",
            (artifact.id,),
        )

    conn.close()


def test_template_upload_uses_contract_html_source_rules_and_render_time_symbol_validation():
    conn = _connection()
    invoice_id = _invoice_id(conn)
    service = InvoiceTemplateService(conn)
    revision = service.upload_html_template(
        name="Contract-style invoice",
        html_content=(
            "<html><body><script>window.templateLoaded = true;</script>"
            "<h1>{{ db.invoice.number }}</h1><p>{{ db.invoice.party_name }}</p>"
            "<p>{{ db.party.street_name }} {{ db.party.street_number }}</p>"
            "<p>{{ db.party.postal_code }} {{ db.party.city }}</p>"
            "<p>{{ db.royalty.net_payable }}</p><footer>{{ manual.footer_note }}</footer>"
            "</body></html>"
        ),
    )
    service.set_manual_symbols(
        invoice_id=invoice_id,
        template_revision_id=revision.id,
        values={"footer_note": "<b>Escaped</b>"},
    )
    rendered = service.preview_invoice(invoice_id)

    assert rendered.warnings == ()
    assert "INV" in rendered.rendered_html
    assert "Venue" in rendered.rendered_html
    assert "Damrak 12" in rendered.rendered_html
    assert "1012 LG Amsterdam" in rendered.rendered_html
    assert rendered.rendered_html.count("Damrak") == 1
    assert "&lt;b&gt;Escaped&lt;/b&gt;" in rendered.rendered_html
    assert "<script>window.templateLoaded = true;</script>" in rendered.rendered_html
    assert "{{ db.royalty.net_payable }}" not in rendered.rendered_html

    with pytest.raises(ValueError, match="escape"):
        service.upload_html_template(name="Unsafe path", html_content="<img src='../secret.png'>")

    unknown = service.upload_html_template(
        name="Unknown at render time",
        html_content="<p>{{ invoice.unknown }}</p>",
    )
    preview = service.preview_invoice(invoice_id, template_revision_id=unknown.id)
    assert preview.warnings == ("Unsupported invoice template symbol: invoice.unknown",)
    with pytest.raises(ValueError, match="Unsupported invoice template symbol"):
        service.export_invoice_html(invoice_id, template_revision_id=unknown.id)

    conn.close()


def test_invoice_template_duplicate_block_renders_indexed_symbols_like_contract_templates():
    conn = _connection()
    invoice_id = _invoice_id(conn)
    service = InvoiceTemplateService(conn)
    revision = service.upload_html_template(
        name="Indexed invoice",
        html_content=(
            "<section>{{duplicate.start}}"
            "<p>{{db.index}} {{db.track.track_title.indexed}} "
            "{{manual.explicit$bool[Yes;No].indexed}}</p>"
            "{{duplicate.end}}</section>"
        ),
    )
    track_symbol = "{{db.track.track_title.indexed}}"
    explicit_symbol = "{{manual.explicit$bool[Yes;No].indexed}}"
    preview = service.preview_invoice(
        invoice_id,
        template_revision_id=revision.id,
        manual_symbols={
            "{{duplicate.number}}": 2,
            build_contract_template_indexed_selection_key(explicit_symbol, 1): "Yes",
            build_contract_template_indexed_selection_key(explicit_symbol, 2): "No",
        },
        canonical_overrides={
            build_contract_template_indexed_selection_key(track_symbol, 1): "First Track",
            build_contract_template_indexed_selection_key(track_symbol, 2): "Second Track",
        },
    )

    assert preview.warnings == ()
    assert "1 First Track Yes" in preview.rendered_html
    assert "2 Second Track No" in preview.rendered_html
    assert "{{duplicate.start}}" not in preview.rendered_html
    assert "{{duplicate.end}}" not in preview.rendered_html
    assert "{{db.track.track_title.indexed}}" not in preview.rendered_html

    with pytest.raises(ValueError, match="Duplicate Number"):
        service.export_invoice_html(
            invoice_id,
            template_revision_id=revision.id,
            manual_symbols={
                build_contract_template_indexed_selection_key(explicit_symbol, 1): "Yes",
            },
            canonical_overrides={
                build_contract_template_indexed_selection_key(track_symbol, 1): "First Track",
            },
        )

    conn.close()


def test_template_revision_update_and_missing_render_edges(tmp_path):
    conn = _connection()
    invoice_id = _invoice_id(conn)
    service = InvoiceTemplateService(conn)

    assert service.fetch_active_revision() is None
    assert service.fetch_revision(999) is None
    assert service.fetch_output_artifact(999) is None
    with pytest.raises(ValueError, match="name"):
        service.upload_html_template(
            name="",
            html_content="<p>{{ invoice.number }}</p>",
        )
    with pytest.raises(ValueError, match="content is required"):
        service.validate_html_template("  ")
    with pytest.raises(ValueError, match="No invoice template revision"):
        service.preview_invoice(invoice_id)

    revision = service.upload_html_template(
        name="Inactive template",
        html_content="<p>{{ invoice.number }}</p>",
        activate=False,
    )
    assert service.fetch_active_revision() is None

    rendered = service.render_invoice(invoice_id, template_revision_id=revision.id)
    assert rendered.snapshot_id is None
    assert "INV" in rendered.rendered_html

    manual_revision = service.upload_html_template(
        name="Manual normalization",
        html_content="<footer>{{ custom.footer_note }}</footer>",
        activate=False,
    )
    service.set_manual_symbols(
        invoice_id=invoice_id,
        template_revision_id=manual_revision.id,
        values={"footer_note": "<b>Stored safely</b>"},
    )
    stored_manual = service.render_invoice(
        invoice_id,
        template_revision_id=manual_revision.id,
    )
    inline_manual = service.render_invoice(
        invoice_id,
        template_revision_id=manual_revision.id,
        manual_symbols={"footer_note": "<i>Inline safely</i>"},
    )
    assert "&lt;b&gt;Stored safely&lt;/b&gt;" in stored_manual.rendered_html
    assert "&lt;i&gt;Inline safely&lt;/i&gt;" in inline_manual.rendered_html
    assert "<i>Inline safely</i>" not in inline_manual.rendered_html

    updated = service.upload_html_template(
        name="Updated template",
        html_content="<p>{{ invoice.total }}</p>",
        template_id=revision.template_id,
        activate=False,
    )
    assert updated.template_id == revision.template_id
    assert updated.id != revision.id
    with pytest.raises(ValueError, match="was not found"):
        service.upload_html_template(
            name="Missing template",
            html_content="<p>{{ invoice.number }}</p>",
            template_id=999,
        )
    uploaded_path = tmp_path / "uploaded-invoice.html"
    uploaded_path.write_text("<p>{{invoice.number}}</p><p>{{invoice.total}}</p>", encoding="utf-8")
    uploaded = service.upload_html_template_from_path(
        uploaded_path,
        name="Uploaded HTML invoice",
    )
    uploaded_preview = service.preview_invoice(invoice_id, template_revision_id=uploaded.id)
    assert uploaded.source_filename == "uploaded-invoice.html"
    assert "INV" in uploaded_preview.rendered_html
    assert "EUR 121.00" in uploaded_preview.rendered_html
    bad_path = tmp_path / "invoice.txt"
    bad_path.write_text("<p>{{ invoice.number }}</p>", encoding="utf-8")
    with pytest.raises(ValueError, match="HTML file"):
        service.upload_html_template_from_path(bad_path, name="Bad")
    with pytest.raises(ValueError, match="snapshot 999"):
        service.create_html_output_artifact(snapshot_id=999)
    blank_snapshot_id = conn.execute(
        """
        INSERT INTO InvoiceTemplateResolvedSnapshots(
            invoice_id,
            template_revision_id,
            resolved_values_json,
            resolution_warnings_json,
            rendered_html_content,
            rendered_checksum_sha256
        )
        VALUES (?, ?, '{}', '[]', '', 'empty')
        """,
        (invoice_id, revision.id),
    ).lastrowid
    with pytest.raises(ValueError, match="no rendered HTML"):
        service.create_html_output_artifact(snapshot_id=blank_snapshot_id)

    conn.close()


def test_preview_warns_for_missing_manual_symbol_but_export_is_strict():
    conn = _connection()
    invoice_id = _invoice_id(conn)
    service = InvoiceTemplateService(conn)
    service.upload_html_template(
        name="Manual",
        html_content="<p>{{ invoice.number }}</p><p>{{ custom.payment_instruction }}</p>",
    )

    preview = service.preview_invoice(invoice_id)

    assert preview.warnings == ("Missing manual symbol: custom.payment_instruction",)
    assert "custom.payment_instruction" not in preview.rendered_html
    with pytest.raises(ValueError, match="Missing manual symbol"):
        service.export_invoice_html(invoice_id)

    conn.close()


def test_invoice_template_service_duplicate_and_symbol_edge_helpers(monkeypatch, tmp_path):
    conn = _connection()
    invoice_id = _invoice_id(conn)
    service = InvoiceTemplateService(conn)

    assert _invoice_symbol_key("manual.footer_note") == "custom.footer_note"
    assert _contract_placeholder_token("") is None
    assert _manual_symbol_key("{{manual.footer_note}}") == "{{manual.footer_note}}"
    assert _manual_symbol_key("manual.footer_note") == "{{manual.footer_note}}"
    assert _manual_lookup({"manual.footer_note": "Manual"}, "{{manual.footer_note}}") == "Manual"
    assert _manual_lookup({}, "{{manual.footer_note}}") is None
    assert service._is_supported_symbol("custom.footer_note")
    assert service.validate_html_template("{{ current.year }} {{ db.index }}") == [
        "{{current.year}}",
        "{{db.index}}",
    ]
    with pytest.raises(FileNotFoundError):
        service.upload_html_template_from_path(tmp_path / "missing.html", name="Missing")
    with pytest.raises(ValueError, match="Invoice 999"):
        service.render_invoice(999)

    revision = service.upload_html_template(
        name="Duplicate edges",
        html_content=(
            "{{duplicate.start}}"
            "{{db.index}} {{db.party.display_name.indexed}} "
            "{{manual.note.indexed}} {{ current.year }}"
            "{{duplicate.end}}{{duplicate.number}}"
        ),
    )
    preview = service.preview_invoice(
        invoice_id,
        template_revision_id=revision.id,
        canonical_overrides={"invoice.party.display_name": "Fallback Party"},
        manual_symbols={
            build_contract_template_indexed_selection_key("{{manual.note.indexed}}", 1): "First",
        },
    )

    assert "1 Fallback Party First" in preview.rendered_html
    assert any("Duplicate block preview uses one copy" in warning for warning in preview.warnings)
    assert "{{ current.year }}" not in preview.rendered_html

    manual_revision = service.upload_html_template(
        name="Manual missing",
        html_content="<p>{{manual.approver}}</p><p>{{ invoice.number }}</p>",
        activate=False,
    )
    missing_manual = service.preview_invoice(invoice_id, template_revision_id=manual_revision.id)
    assert "Missing manual symbol: {{manual.approver}}" in missing_manual.warnings
    with pytest.raises(ValueError, match="Missing manual symbol"):
        service.export_invoice_html(invoice_id, template_revision_id=manual_revision.id)

    override_revision = service.upload_html_template(
        name="Override unknown",
        html_content="<p>{{ unknown.override }}</p>",
        activate=False,
    )
    override_preview = service.preview_invoice(
        invoice_id,
        template_revision_id=override_revision.id,
        canonical_overrides={"unknown.override": "Override"},
    )
    assert override_preview.rendered_html == "<p></p>"
    assert override_preview.warnings == ("Unsupported invoice template symbol: unknown.override",)

    service_for_reload_error = InvoiceTemplateService(conn)
    monkeypatch.setattr(service_for_reload_error, "fetch_revision", lambda _revision_id: None)
    with pytest.raises(RuntimeError, match="could not be reloaded"):
        service_for_reload_error.upload_html_template(
            name="Reload", html_content="<p>{{invoice.number}}</p>"
        )

    snapshot_id = service._create_snapshot(
        invoice_id=invoice_id,
        template_revision_id=revision.id,
        rendered_html="<html>snapshot</html>",
        resolved_values={},
        warnings=(),
    )
    monkeypatch.setattr(service, "fetch_output_artifact", lambda _artifact_id: None)
    with pytest.raises(RuntimeError, match="artifact could not be reloaded"):
        service.create_html_output_artifact(snapshot_id=snapshot_id)
    monkeypatch.undo()

    with pytest.raises(ValueError, match="whole number"):
        service._duplicate_copy_count("bad", strict=True)
    with pytest.raises(ValueError, match="whole number"):
        service._duplicate_copy_count("2.5", strict=True)
    with pytest.raises(ValueError, match="cannot be negative"):
        service._duplicate_copy_count("-1", strict=True)
    with pytest.raises(ValueError, match="greater than"):
        service._duplicate_copy_count("201", strict=True)
    assert service._duplicate_copy_count("", strict=False) is None

    warnings: list[str] = []
    replacements = service._indexed_manual_replacements(
        symbols=("{{manual.note.indexed}}",),
        index=2,
        manual_values={},
        strict=False,
        warnings=warnings,
    )
    assert replacements["{{manual.note.indexed}}"] == ""
    assert "Indexed manual placeholder" in warnings[-1]
    with pytest.raises(ValueError, match="Indexed manual placeholder"):
        service._indexed_manual_replacements(
            symbols=("{{manual.note.indexed}}",),
            index=2,
            manual_values={},
            strict=True,
            warnings=[],
        )

    warnings.clear()
    db_replacements = service._indexed_db_replacements(
        symbols=("{{db.party.display_name.indexed}}",),
        index=1,
        canonical_values={},
        canonical_overrides={
            build_contract_template_indexed_selection_key(
                "{{db.party.display_name.indexed}}",
                1,
            ): "Indexed Party",
        },
        strict=True,
        warnings=warnings,
    )
    assert db_replacements["{{db.party.display_name.indexed}}"] == "Indexed Party"
    canonical_fallback = service._indexed_db_replacements(
        symbols=("{{db.party.display_name.indexed}}",),
        index=2,
        canonical_values={},
        canonical_overrides={"invoice.party.display_name": "Canonical Party"},
        strict=True,
        warnings=[],
    )
    assert canonical_fallback["{{db.party.display_name.indexed}}"] == "Canonical Party"
    with pytest.raises(ValueError, match="selected record"):
        service._indexed_db_replacements(
            symbols=("{{db.party.display_name.indexed}}",),
            index=1,
            canonical_values={},
            canonical_overrides={},
            strict=True,
            warnings=[],
        )

    rendered, warnings_tuple = service._apply_duplicate_controls(
        "{{duplicate.start}}missing end",
        manual_values={_DUPLICATE_NUMBER_SYMBOL: "1"},
        canonical_values={},
        canonical_overrides={},
        strict=False,
    )
    assert rendered == "missing end"
    assert "Duplicate cymbols must use" in warnings_tuple[0]
    with pytest.raises(ValueError, match="Duplicate cymbols"):
        service._apply_duplicate_controls(
            "{{duplicate.start}}missing end",
            manual_values={_DUPLICATE_NUMBER_SYMBOL: "1"},
            canonical_values={},
            canonical_overrides={},
            strict=True,
        )
    rendered_unknown, _warnings = service._apply_duplicate_controls(
        "{{duplicate.start}}{{unknown}}{{duplicate.end}}",
        manual_values={_DUPLICATE_NUMBER_SYMBOL: "1"},
        canonical_values={},
        canonical_overrides={},
        strict=False,
    )
    assert "{{unknown}}" in rendered_unknown
    assert service._apply_duplicate_controls(
        "plain",
        manual_values={},
        canonical_values={},
        canonical_overrides={},
        strict=True,
    ) == ("plain", ())

    assert service._replace_tokens("{{aa}} {{a}}", {"{{a}}": "A", "{{aa}}": "AA"}) == "AA A"
    assert (
        service._render_symbol_value(
            "invoice.lines",
            "<table></table>",
            canonical_values={"invoice.lines": "<table></table>"},
        )
        == "<table></table>"
    )
    assert service._party_values(999)["invoice.party.name"] == ""
    assert service._company_values()["company.vat_number"] == "NL-COMPANY"
    owner_id = PartyService(conn).create_party(
        PartyPayload(
            legal_name="Owner Legal",
            display_name="Owner Display",
            company_name="Owner Company",
            party_type="organization",
            street_name="Owner Street",
            street_number="4",
            postal_code="1000 AA",
            city="Amsterdam",
            country="NL",
            vat_number="NL-OWNER",
        )
    )
    conn.execute(
        "INSERT OR REPLACE INTO ApplicationOwnerBinding(id, party_id) VALUES(1, ?)", (owner_id,)
    )
    owner_values = service._company_values()
    assert owner_values["company.name"] == "Owner Company"
    assert owner_values["company.address"] == "Owner Street 4\n1000 AA Amsterdam\nNL"
    assert service._manual_symbols(invoice_id) == {}
    with pytest.raises(ValueError, match="Invoice 999"):
        service._canonical_values(999)
    assert _DB_INDEX_SYMBOL == "{{db.index}}"

    conn.close()

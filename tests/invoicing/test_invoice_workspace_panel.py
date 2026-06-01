import sqlite3
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDoubleSpinBox,
    QGroupBox,
    QLineEdit,
    QScrollArea,
    QSizePolicy,
    QWidget,
)

from isrc_manager.code_registry import (
    BUILTIN_CATEGORY_CREDIT_NOTE_NUMBER,
    BUILTIN_CATEGORY_INVOICE_NUMBER,
    BUILTIN_CATEGORY_ROYALTY_STATEMENT_NUMBER,
    CodeRegistryService,
)
from isrc_manager.contract_templates.models import (
    ContractTemplateFormManualField,
    build_contract_template_indexed_selection_key,
)
from isrc_manager.contracts import ContractPartyPayload, ContractPayload, ContractService
from isrc_manager.invoicing import controller as invoice_controller
from isrc_manager.invoicing import workspace as workspace_module
from isrc_manager.invoicing.invoice_service import InvoiceService
from isrc_manager.invoicing.royalty_import import RoyaltySourceImportService
from isrc_manager.invoicing.template_service import InvoiceTemplateService
from isrc_manager.invoicing.travel_distance import TravelDistanceResult
from isrc_manager.invoicing.workspace import (
    InvoiceWorkspacePanel,
    _contract_placeholder_token,
    _display_date,
    _invoice_template_symbol_key,
    _status_label,
    _template_value_preview,
)
from isrc_manager.parties import PartyPayload, PartyService
from isrc_manager.rights import OwnershipInterestPayload, RightPayload, RightsService
from isrc_manager.services import DatabaseSchemaService
from isrc_manager.works import WorkContributorPayload, WorkPayload, WorkService


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


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
    conn.execute(
        """
        UPDATE CodeRegistryCategories
        SET prefix='CN', normalized_prefix='CN'
        WHERE system_key=?
        """,
        (BUILTIN_CATEGORY_CREDIT_NOTE_NUMBER,),
    )
    conn.execute(
        """
        UPDATE CodeRegistryCategories
        SET prefix='ROY', normalized_prefix='ROY'
        WHERE system_key=?
        """,
        (BUILTIN_CATEGORY_ROYALTY_STATEMENT_NUMBER,),
    )
    conn.commit()
    return conn


def _has_scroll_area_ancestor(widget: QWidget) -> bool:
    ancestor = widget.parentWidget()
    while ancestor is not None:
        if isinstance(ancestor, QScrollArea):
            return True
        ancestor = ancestor.parentWidget()
    return False


def _integrated_royalty_fixture(conn: sqlite3.Connection) -> tuple[int, int, int, int]:
    party_service = PartyService(conn)
    writer_id = party_service.create_party(
        PartyPayload(
            legal_name="Writer Person",
            display_name="Writer",
            party_type="artist",
            artist_name="Writer",
        )
    )
    publisher_id = party_service.create_party(
        PartyPayload(
            legal_name="Publisher BV",
            display_name="Publisher",
            party_type="publisher",
        )
    )
    work_id = WorkService(conn, party_service=party_service).create_work(
        WorkPayload(
            title="Royalty Work",
            metadata_complete=True,
            contract_signed=True,
            rights_verified=True,
            contributors=(
                WorkContributorPayload(
                    role="composer",
                    name="Writer",
                    share_percent=100.0,
                    party_id=writer_id,
                ),
            ),
        )
    )
    contract_id = ContractService(conn, party_service=party_service).create_contract(
        ContractPayload(
            title="Publishing Agreement",
            contract_type="publishing",
            status="active",
            parties=(
                ContractPartyPayload(
                    party_id=writer_id,
                    role_label="writer",
                    is_primary=True,
                ),
            ),
            work_ids=(work_id,),
        )
    )
    right_id = RightsService(conn).create_right(
        RightPayload(
            title="Publishing grant",
            right_type="composition_publishing",
            exclusive_flag=True,
            territory="Worldwide",
            perpetual_flag=True,
            granted_to_party_id=publisher_id,
            source_contract_id=contract_id,
            work_id=work_id,
        )
    )
    RightsService(conn).replace_work_ownership_interests(
        work_id,
        (
            OwnershipInterestPayload(
                role="publisher",
                party_id=publisher_id,
                share_percent=100.0,
                territory="Worldwide",
                source_contract_id=contract_id,
            ),
        ),
    )
    return contract_id, work_id, publisher_id, right_id


def test_invoice_workspace_panel_creates_issues_templates_and_exports_html(tmp_path):
    _app()
    conn = _connection()
    PartyService(conn).create_party(
        PartyPayload(
            legal_name="Venue BV",
            display_name="Venue",
            party_type="organization",
        )
    )
    panel = InvoiceWorkspacePanel(conn_provider=lambda: conn)
    panel.description_field.setText("Venue service")
    panel.unit_price_field.setText("100.00")
    panel.vat_rate_field.setText("2100")
    panel.due_date_field.setText("2026-02-01")

    panel.create_draft_invoice()
    panel.refresh_invoices()
    panel.invoice_table.selectRow(0)
    panel.issue_selected_invoice()
    panel.invoice_table.selectRow(0)
    template_path = tmp_path / "invoice-template.html"
    template_path.write_text(
        "<html><body><h1>{{invoice.number}}</h1>{{ invoice.lines }}"
        "<p>{{ invoice.total }}</p><footer>{{ custom.footer_note }}</footer></body></html>",
        encoding="utf-8",
    )
    panel.template_path_field.setText(str(template_path))
    panel.manual_footer_field.setText("Pay promptly")
    panel.upload_template()
    panel.preview_selected_invoice()
    preview = panel.preview_output.toPlainText()
    preview_url = panel.preview_output.url()
    preview_html = Path(preview_url.toLocalFile()).read_text(encoding="utf-8")
    panel.export_selected_invoice_html()

    assert panel.invoice_table.rowCount() == 1
    assert preview_url.isLocalFile()
    assert "<base href=" in preview_html
    assert "INV" in preview
    assert "Venue service" in preview
    assert "EUR 121.00" in preview
    assert "Pay promptly" in preview
    assert conn.execute("SELECT COUNT(*) FROM InvoiceTemplateResolvedSnapshots").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM InvoiceOutputArtifacts").fetchone()[0] == 1

    panel.deleteLater()
    conn.close()


def test_invoice_workspace_panel_exposes_royalties_accounting_navigation():
    _app()
    conn = _connection()
    panel = InvoiceWorkspacePanel(conn_provider=lambda: conn)

    assert [panel.tabs.tabText(index) for index in range(panel.tabs.count())] == [
        "Royalties",
        "Invoices",
        "Accounting",
        "Payments",
        "Reports",
        "Settings",
    ]
    assert [
        panel.royalty_workflow_tabs.tabText(index)
        for index in range(panel.royalty_workflow_tabs.count())
    ] == [
        "Contracts",
        "Rights / Titles",
        "Sales & Usage Imports",
        "Calculation Runs",
        "Royalty Statements",
        "Disputes",
        "Readiness",
    ]
    assert [
        panel.invoice_workflow_tabs.tabText(index)
        for index in range(panel.invoice_workflow_tabs.count())
    ] == [
        "Sales Invoices",
        "Line Allocation",
        "Create / Edit",
        "Credit Notes",
        "Royalty Payables",
        "E-Invoices",
    ]
    group_titles = {group.title() for group in panel.findChildren(QGroupBox)}
    assert {
        "Term economics",
        "Scope and rights",
        "Validity and notes",
        "Source identity",
        "Linked repertoire",
        "Amounts and reporting period",
    }.issubset(group_titles)

    panel.focus_tab("accounting")
    assert panel.tabs.currentIndex() == 2
    panel.resize(1200, 800)
    panel.show()
    _app().processEvents()
    visible_direct_children = [
        name
        for name, widget in vars(panel).items()
        if isinstance(widget, QWidget)
        and widget is not panel.tabs
        and widget.parentWidget() is panel
        and widget.isVisible()
    ]
    assert visible_direct_children == []
    assert panel.journal_table.horizontalHeaderItem(0).text() == "Journal entry ID"
    assert panel.payables_table.horizontalHeaderItem(0).text() == "Payee"
    assert panel.report_catalog_table.horizontalHeaderItem(0).text() == "Category"
    preview_toolbar = panel.findChild(QWidget, "invoiceTemplatePreviewToolbar")
    assert preview_toolbar is not None
    assert preview_toolbar.maximumHeight() == 56
    assert preview_toolbar.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Fixed

    panel.deleteLater()
    conn.close()


def test_invoice_workspace_panel_company_settings_use_owner_party_ledger():
    _app()
    conn = _connection()
    owner_id = PartyService(conn).create_party(
        PartyPayload(
            legal_name="Cosmowyn Records BV",
            display_name="Cosmowyn Records",
            company_name="Cosmowyn Records BV",
            party_type="organization",
            contact_person="Mervyn van de Kleut",
            email="legal@cosmowyn.com",
            phone="+31 647 821 383",
            street_name="Koelhorst",
            street_number="25",
            city="Ede",
            postal_code="6714 KL",
            country="The Netherlands",
            bank_account_number="NL36 RABO 0367 5499 64",
            chamber_of_commerce_number="91222419",
            tax_id="NL004875947B29",
            vat_number="NL004875947B29",
            pro_affiliation="BUMA/STEMRA",
            pro_number="123456",
            ipi_cae="987654321",
        )
    )
    conn.execute(
        "INSERT INTO ApplicationOwnerBinding(id, party_id) VALUES(1, ?)",
        (owner_id,),
    )
    conn.commit()

    panel = InvoiceWorkspacePanel(conn_provider=lambda: conn)

    text = panel.company_owner_output.toPlainText()
    assert "Source: Party Manager -> Current Owner Party" in text
    assert "Cosmowyn Records BV" in text
    assert "NL004875947B29" in text
    assert "Koelhorst 25" in text
    assert "NL36 RABO 0367 5499 64" in text
    assert "Company settings should extend" not in text

    panel.deleteLater()
    conn.close()


def test_invoice_workspace_panel_users_roles_use_party_manager_records():
    _app()
    conn = _connection()
    party_service = PartyService(conn)
    owner_id = party_service.create_party(
        PartyPayload(
            legal_name="Cosmowyn Records BV",
            display_name="Cosmowyn Records",
            company_name="Cosmowyn Records BV",
            party_type="organization",
            contact_person="Mervyn van de Kleut",
            email="legal@cosmowyn.com",
            street_name="Koelhorst",
            street_number="25",
            city="Ede",
            postal_code="6714 KL",
            country="The Netherlands",
            bank_account_number="NL36 RABO 0367 5499 64",
            vat_number="NL004875947B29",
        )
    )
    artist_id = party_service.create_party(
        PartyPayload(
            legal_name="Aeonium Artist",
            display_name="Aeonium",
            artist_name="Aeonium",
            party_type="artist",
            email="artist@example.test",
            bank_account_number="NL00 ARTIST 0000 0000 00",
            ipi_cae="123456789",
        )
    )
    party_service.create_party(
        PartyPayload(
            legal_name="Forest Venue BV",
            display_name="Forest Venue",
            party_type="licensee",
            email="ap@forest.example.test",
            street_name="Main",
            street_number="1",
            city="Amsterdam",
            postal_code="1000 AA",
            country="The Netherlands",
            vat_number="NL001234567B01",
        )
    )
    conn.execute(
        "INSERT INTO ApplicationOwnerBinding(id, party_id) VALUES(1, ?)",
        (owner_id,),
    )
    conn.commit()

    panel = InvoiceWorkspacePanel(conn_provider=lambda: conn)

    table_text = " ".join(
        panel.users_roles_table.item(row, column).text()
        for row in range(panel.users_roles_table.rowCount())
        for column in range(panel.users_roles_table.columnCount())
        if panel.users_roles_table.item(row, column) is not None
    )
    assert "Current owner / invoice issuer" in table_text
    assert "Royalty payee / artist payout recipient" in table_text
    assert "Customer / invoice recipient" in table_text
    assert (
        "Users & Roles settings should extend" not in panel.users_roles_detail_output.toPlainText()
    )

    for row in range(panel.users_roles_table.rowCount()):
        item = panel.users_roles_table.item(row, 0)
        if item is not None and item.data(Qt.ItemDataRole.UserRole) == artist_id:
            panel.users_roles_table.selectRow(row)
            break
    detail = panel.users_roles_detail_output.toPlainText()
    assert "Source: Party Manager -> Parties" in detail
    assert "Aeonium Artist" in detail
    assert "Royalty calculations, statements, payables, artist payouts" in detail
    assert "Permission model: not duplicated here" in detail
    assert _has_scroll_area_ancestor(panel.users_roles_table)

    panel.deleteLater()
    conn.close()


def test_invoice_workspace_panel_double_clicks_party_role_into_party_manager():
    _app()
    conn = _connection()
    party_id = PartyService(conn).create_party(
        PartyPayload(
            legal_name="Altar Records",
            display_name="Altar Records",
            party_type="licensee",
            email="licensing@altar.example.test",
        )
    )
    opened: list[int | None] = []
    panel = InvoiceWorkspacePanel(
        conn_provider=lambda: conn,
        open_party_manager=lambda selected_id: opened.append(selected_id),
    )

    double_clicked_item = None
    for row in range(panel.users_roles_table.rowCount()):
        item = panel.users_roles_table.item(row, 0)
        if item is not None and item.data(Qt.ItemDataRole.UserRole) == party_id:
            double_clicked_item = item
            break

    assert double_clicked_item is not None
    panel.users_roles_table.itemDoubleClicked.emit(double_clicked_item)

    assert opened == [party_id]

    panel.deleteLater()
    conn.close()


def test_invoice_workspace_panel_vat_tax_settings_use_existing_vat_records():
    _app()
    conn = _connection()
    party_service = PartyService(conn)
    owner_id = party_service.create_party(
        PartyPayload(
            legal_name="Cosmowyn Records BV",
            display_name="Cosmowyn Records",
            company_name="Cosmowyn Records BV",
            party_type="organization",
            email="legal@cosmowyn.com",
            street_name="Koelhorst",
            street_number="25",
            city="Ede",
            postal_code="6714 KL",
            country="The Netherlands",
            bank_account_number="NL36 RABO 0367 5499 64",
            vat_number="NL004875947B29",
        )
    )
    venue_id = party_service.create_party(
        PartyPayload(
            legal_name="Forest Venue BV",
            display_name="Forest Venue",
            party_type="licensee",
            email="ap@forest.example.test",
            street_name="Main",
            street_number="1",
            city="Amsterdam",
            postal_code="1000 AA",
            country="The Netherlands",
            vat_number="NL001234567B01",
        )
    )
    conn.execute(
        "INSERT INTO ApplicationOwnerBinding(id, party_id) VALUES(1, ?)",
        (owner_id,),
    )
    conn.commit()

    panel = InvoiceWorkspacePanel(conn_provider=lambda: conn)
    panel.catalog_name_field.setText("Domestic service")
    panel.catalog_description_field.setText("Standard domestic VAT service")
    panel.catalog_quantity_field.setText("1")
    panel.catalog_unit_price_field.setText("100.00")
    panel.catalog_vat_rate_field.setText("2100")
    panel.catalog_vat_country_field.setText("NL")
    panel.catalog_category_field.setText("Services")
    panel.catalog_account_field.setText("4100")
    panel.save_catalog_preset()
    panel.party_combo.setCurrentIndex(panel.party_combo.findData(venue_id))
    panel.description_field.setText("Venue service")
    panel.unit_price_field.setText("100.00")
    panel.vat_rate_field.setText("2100")
    panel.due_date_field.setText("2026-02-01")
    panel.create_draft_invoice()
    panel.refresh_invoices()
    panel.invoice_table.selectRow(0)
    panel.issue_selected_invoice()
    panel._refresh_vat_tax_settings()

    treatment_text = " ".join(
        panel.vat_treatment_table.item(row, column).text()
        for row in range(panel.vat_treatment_table.rowCount())
        for column in range(panel.vat_treatment_table.columnCount())
        if panel.vat_treatment_table.item(row, column) is not None
    )
    activity_text = " ".join(
        panel.vat_activity_table.item(row, column).text()
        for row in range(panel.vat_activity_table.rowCount())
        for column in range(panel.vat_activity_table.columnCount())
        if panel.vat_activity_table.item(row, column) is not None
    )
    detail = panel.vat_tax_detail_output.toPlainText()

    assert "Standard" in treatment_text
    assert "21.00%" in treatment_text
    assert "NL" in treatment_text
    assert "EUR 21.00" in treatment_text
    assert "VAT Output" in panel.vat_activity_table.horizontalHeaderItem(3).text()
    assert "EUR 21.00" in activity_text
    assert "Seller VAT number: NL004875947B29" in detail
    assert "Invoice VAT snapshots" in detail
    assert "VAT & Tax settings should extend" not in detail
    assert _has_scroll_area_ancestor(panel.vat_treatment_table)

    panel.deleteLater()
    conn.close()


def test_invoice_workspace_panel_invoice_numbering_uses_code_registry_sequences():
    _app()
    conn = _connection()
    venue_id = PartyService(conn).create_party(
        PartyPayload(
            legal_name="Forest Venue BV",
            display_name="Forest Venue",
            party_type="licensee",
        )
    )
    panel = InvoiceWorkspacePanel(conn_provider=lambda: conn)
    panel.party_combo.setCurrentIndex(panel.party_combo.findData(venue_id))
    panel.description_field.setText("Venue service")
    panel.unit_price_field.setText("100.00")
    panel.vat_rate_field.setText("2100")
    panel.due_date_field.setText("2026-02-01")
    panel.create_draft_invoice()
    panel.refresh_invoices()
    panel.invoice_table.selectRow(0)
    panel.issue_selected_invoice()
    panel.description_field.setText("Draft-only service")
    panel.create_draft_invoice()
    panel._refresh_invoice_numbering_settings()

    sequence_text = " ".join(
        panel.numbering_sequence_table.item(row, column).text()
        for row in range(panel.numbering_sequence_table.rowCount())
        for column in range(panel.numbering_sequence_table.columnCount())
        if panel.numbering_sequence_table.item(row, column) is not None
    )
    usage_text = " ".join(
        panel.numbering_usage_table.item(row, column).text()
        for row in range(panel.numbering_usage_table.rowCount())
        for column in range(panel.numbering_usage_table.columnCount())
        if panel.numbering_usage_table.item(row, column) is not None
    )
    detail = panel.invoice_numbering_detail_output.toPlainText()

    assert "Invoice Number" in sequence_text
    assert "Credit Note Number" in sequence_text
    assert "Ledger Transaction Number" in sequence_text
    assert "Royalty Statement Number" in sequence_text
    assert "INV" in sequence_text
    assert "CN" in sequence_text
    assert "ROY" in sequence_text
    assert "Ready" in sequence_text
    assert "Invoices" in usage_text
    assert "Issued invoice numbers are immutable" in usage_text
    assert "Source: Code Registry Workspace" in detail
    assert "Draft invoices do not receive final invoice numbers." in detail
    assert "Next preview values shown here are not reservations" in detail
    assert "Numbered records missing registry links: 0" in detail
    assert "Invoice Numbering settings should extend" not in detail
    assert _has_scroll_area_ancestor(panel.numbering_sequence_table)

    panel.deleteLater()
    conn.close()


def test_invoice_workspace_panel_integrations_preview_real_dsp_statement(tmp_path):
    _app()
    conn = _connection()
    csv_path = tmp_path / "155840_00020 Royalties Statement.csv"
    csv_path.write_text(
        "\n".join(
            (
                "date_id,total_gbp,store_name",
                "2026-03,0.068928,TIDAL",
                '2026-03,0.000047,"YouTube Content ID (Subscription)"',
            )
        ),
        encoding="utf-8",
    )
    panel = InvoiceWorkspacePanel(conn_provider=lambda: conn)
    panel.integration_file_path_field.setText(str(csv_path))

    panel._refresh_integrations_settings()

    profile_text = " ".join(
        panel.integration_profile_table.item(row, column).text()
        for row in range(panel.integration_profile_table.rowCount())
        for column in range(panel.integration_profile_table.columnCount())
        if panel.integration_profile_table.item(row, column) is not None
    )
    mapping_text = " ".join(
        panel.integration_mapping_table.item(row, column).text()
        for row in range(panel.integration_mapping_table.rowCount())
        for column in range(panel.integration_mapping_table.columnCount())
        if panel.integration_mapping_table.item(row, column) is not None
    )
    preview_text = " ".join(
        panel.integration_preview_table.item(row, column).text()
        for row in range(panel.integration_preview_table.rowCount())
        for column in range(panel.integration_preview_table.columnCount())
        if panel.integration_preview_table.item(row, column) is not None
    )
    detail = panel.integrations_detail_output.toPlainText()

    assert "RoyaltySourceImportService" in profile_text
    assert "date_id" in mapping_text
    assert "period_start" in mapping_text
    assert "total_gbp" in mapping_text
    assert "net_amount" in mapping_text
    assert "Currency inferred from amount header: GBP." in mapping_text
    assert "TIDAL" in preview_text
    assert "GBP 0.07" in preview_text
    assert "Skipped" in preview_text
    assert "Error" not in preview_text
    assert "micro amounts below one minor unit" in detail
    assert "date_id,total_gbp,store_name" not in detail
    assert "Settings should extend" not in detail
    assert _has_scroll_area_ancestor(panel.integration_file_path_field)

    panel.deleteLater()
    conn.close()


def test_invoice_workspace_panel_workflows_settings_are_ledger_backed():
    _app()
    conn = _connection()
    PartyService(conn).create_party(
        PartyPayload(
            legal_name="Workflow Venue BV",
            display_name="Workflow Venue",
            party_type="organization",
        )
    )
    panel = InvoiceWorkspacePanel(conn_provider=lambda: conn)
    panel.description_field.setText("Workflow review service")
    panel.unit_price_field.setText("100.00")
    panel.vat_rate_field.setText("2100")
    panel.due_date_field.setText("2026-02-01")
    panel.create_draft_invoice()

    panel._refresh_workflows_settings()

    policy_text = " ".join(
        panel.workflow_policy_table.item(row, column).text()
        for row in range(panel.workflow_policy_table.rowCount())
        for column in range(panel.workflow_policy_table.columnCount())
        if panel.workflow_policy_table.item(row, column) is not None
    )
    queue_text = " ".join(
        panel.workflow_queue_table.item(row, column).text()
        for row in range(panel.workflow_queue_table.rowCount())
        for column in range(panel.workflow_queue_table.columnCount())
        if panel.workflow_queue_table.item(row, column) is not None
    )
    detail = panel.workflow_detail_output.toPlainText()

    assert "Invoice issue" in policy_text
    assert "Royalty calculation" in policy_text
    assert "FinancialCommandLog" in queue_text
    assert "Draft invoices" in queue_text
    assert "1" in queue_text
    assert "Source: existing invoice, royalty, command-log, and ledger services" in detail
    assert "does not create a duplicate permissions or workflow engine" in detail
    assert "Workflows settings should extend" not in detail
    assert _has_scroll_area_ancestor(panel.workflow_policy_table)

    panel.deleteLater()
    conn.close()


def test_royalty_import_service_imports_real_dsp_aggregate_statement(tmp_path):
    conn = _connection()
    csv_path = tmp_path / "155840_00020 Royalties Statement.csv"
    csv_path.write_text(
        "\n".join(("date_id,total_gbp,store_name", "2026-03,0.068928,TIDAL")),
        encoding="utf-8",
    )
    service = RoyaltySourceImportService(conn)
    inspection = service.inspect_file(csv_path)

    report = service.apply_import(csv_path, inspection.suggested_mapping)

    event = conn.execute("""
        SELECT source_type, description, currency, net_amount_minor, period_start, period_end
        FROM RoyaltySourceEvents
        """).fetchone()
    assert inspection.suggested_mapping == {
        "date_id": "period_start",
        "total_gbp": "net_amount",
        "store_name": "source_type",
    }
    assert report.passed == 1
    assert event == (
        "TIDAL",
        "TIDAL royalty revenue 2026-03",
        "GBP",
        7,
        "2026-03-01",
        "2026-03-31",
    )

    conn.close()


def test_invoice_workspace_panel_renders_template_preview_without_invoice():
    _app()
    conn = _connection()
    selected_party_id = PartyService(conn).create_party(
        PartyPayload(
            legal_name="Selected Venue Legal BV",
            display_name="Selected Venue",
            company_name="Selected Venue Company BV",
            party_type="organization",
            email="selected@example.test",
            phone="+31 20 123 4567",
            street_name="Singel",
            street_number="1",
            postal_code="1012 AA",
            city="Amsterdam",
            country="NL",
            bank_account_number="NL00 TEST 0000 0000 02",
            chamber_of_commerce_number="12345678",
        )
    )
    panel = InvoiceWorkspacePanel(conn_provider=lambda: conn)
    panel.template_html_editor.setPlainText(
        "<html><body><h1>{{ invoice.number }}</h1>"
        "<p>{{ invoice.party.name }}</p>{{ invoice.lines }}{{ db.invoice.total }}"
        "{{ db.party.company_name }}"
        "<p>{{ db.party.street_name }} {{ db.party.street_number }}</p>"
        "<p>{{ db.party.postal_code }} {{ db.party.city }}</p>"
        "<p>{{ db.party.country }}</p>"
        "<p>{{ db.party.email }}</p><p>{{ manual.date }}</p>"
        "<footer>{{ custom.footer_note }}</footer></body></html>"
    )
    panel.manual_footer_field.setText("Sample footer")
    party_index = panel.template_party_selector_combo.findData(str(selected_party_id))
    panel.template_party_selector_combo.setCurrentIndex(party_index)
    date_widget = panel.template_manual_widgets["{{manual.date}}"]
    assert isinstance(date_widget, QDateEdit)
    date_widget.setDate(QDate(2026, 5, 30))
    date_widget.setProperty("has_user_value", True)

    panel.preview_selected_invoice()

    preview = panel.preview_output.toPlainText()
    assert "INV-2026-0001" in preview
    assert "Selected Venue" in preview
    assert "Selected Venue Company BV" in preview
    assert "Singel 1" in preview
    assert "1012 AA Amsterdam" in preview
    assert preview.count("Singel") == 1
    assert "selected@example.test" in preview
    assert "Example billable service" in preview
    assert "Sample footer" in preview
    assert "30.May.2026" in preview
    assert "EUR 121.00" in preview
    assert "{{ db.party.company_name }}" not in preview
    assert "Unresolved:" not in preview
    symbol_text = " ".join(
        panel.template_symbol_combo.itemText(index)
        for index in range(panel.template_symbol_combo.count())
    )
    database_text = " ".join(
        panel.template_database_value_combo.itemText(index)
        for index in range(panel.template_database_value_combo.count())
    )
    group_titles = {group.title() for group in panel.findChildren(QGroupBox)}
    assert "Source preview" not in group_titles
    assert "Manual Fields" in group_titles
    assert "Database-Linked Fields" in group_titles
    assert "Resolved Symbols" in group_titles
    assert "db.party.company_name" in symbol_text
    assert "invoice.party.name" in symbol_text
    assert "db.invoice.total" in symbol_text
    assert "{{manual.date}}" in symbol_text
    assert "Resolved" in symbol_text
    assert "db.party.company_name" in database_text
    assert "Party selection" in database_text
    assert "db.invoice.total" in database_text
    assert "Invoice context" in database_text

    panel.deleteLater()
    conn.close()


def test_invoice_workspace_template_fill_form_expands_indexed_duplicate_fields():
    _app()
    conn = _connection()
    party_service = PartyService(conn)
    party_service.create_party(
        PartyPayload(
            legal_name="Venue Legal BV",
            display_name="Venue",
            party_type="organization",
        )
    )
    artist_id = party_service.create_party(
        PartyPayload(
            legal_name="Indexed Artist",
            display_name="Indexed Artist",
            party_type="artist",
        )
    )
    track_id = conn.execute(
        """
        INSERT INTO Tracks(isrc, isrc_compact, track_title, main_artist_party_id, track_length_sec)
        VALUES ('NL-C51-26-00001', 'NLC512600001', 'Indexed Track', ?, 185)
        """,
        (artist_id,),
    ).lastrowid
    panel = InvoiceWorkspacePanel(conn_provider=lambda: conn)
    panel.description_field.setText("Template service")
    panel.unit_price_field.setText("100.00")
    panel.vat_rate_field.setText("2100")
    panel.due_date_field.setText("2026-02-01")
    panel.create_draft_invoice()
    panel.refresh_invoices()
    panel.invoice_table.selectRow(0)
    panel.issue_selected_invoice()
    panel.invoice_table.selectRow(0)

    html = (
        "<html><body>{{duplicate.start}}"
        "<p>{{db.index}} {{db.track.track_title.indexed}} "
        "{{manual.explicit$bool[Yes;No].indexed}}</p>"
        "{{duplicate.end}}</body></html>"
    )
    InvoiceTemplateService(conn).upload_html_template(name="Indexed", html_content=html)
    panel.template_html_editor.setPlainText(html)
    duplicate_widget = panel.template_manual_widgets["{{duplicate.number}}"]
    assert isinstance(duplicate_widget, QDoubleSpinBox)
    duplicate_widget.setValue(2)
    assert panel._template_pending_fill_rebuild is True
    _app().processEvents()
    assert panel._template_pending_fill_rebuild is False

    track_symbol = "{{db.track.track_title.indexed}}"
    explicit_symbol = "{{manual.explicit$bool[Yes;No].indexed}}"
    track_key_1 = build_contract_template_indexed_selection_key(track_symbol, 1)
    track_key_2 = build_contract_template_indexed_selection_key(track_symbol, 2)
    explicit_key_1 = build_contract_template_indexed_selection_key(explicit_symbol, 1)
    explicit_key_2 = build_contract_template_indexed_selection_key(explicit_symbol, 2)
    assert track_key_1 in panel.template_indexed_selector_widgets
    assert track_key_2 in panel.template_indexed_selector_widgets
    assert explicit_key_1 in panel.template_indexed_manual_widgets
    assert explicit_key_2 in panel.template_indexed_manual_widgets

    for key in (track_key_1, track_key_2):
        combo = panel._template_selector_combo(panel.template_indexed_selector_widgets[key])
        assert combo is not None
        combo.setCurrentIndex(combo.findData(str(track_id)))
    for key, value in ((explicit_key_1, "Yes"), (explicit_key_2, "No")):
        combo = panel._template_selector_combo(panel.template_indexed_manual_widgets[key])
        assert combo is not None
        combo.setCurrentIndex(combo.findData(value))

    panel.preview_selected_invoice()

    preview = panel.preview_output.toPlainText()
    assert "1 Indexed Track Yes" in preview
    assert "2 Indexed Track No" in preview
    assert "{{db.track.track_title.indexed}}" not in preview
    assert "{{manual.explicit$bool[Yes;No].indexed}}" not in preview

    panel.deleteLater()
    conn.close()


def test_invoice_workspace_panel_builds_multi_line_invoice_from_catalog_and_travel(monkeypatch):
    _app()
    conn = _connection()
    warnings: list[str] = []
    monkeypatch.setattr(
        "isrc_manager.invoicing.workspace.QMessageBox.warning",
        lambda _parent, _title, message: warnings.append(str(message)),
    )
    PartyService(conn).create_party(
        PartyPayload(
            legal_name="Venue BV",
            display_name="Venue",
            party_type="organization",
        )
    )
    panel = InvoiceWorkspacePanel(conn_provider=lambda: conn)

    panel.catalog_name_field.setText("Session fee")
    panel.catalog_description_field.setText("Studio session")
    panel.catalog_quantity_field.setText("2")
    panel.catalog_unit_price_field.setText("50.00")
    panel.catalog_vat_rate_field.setText("2100")
    panel.catalog_category_field.setText("Services")
    panel.catalog_account_field.setText("4100")
    panel.save_catalog_preset()
    panel.catalog_item_combo.setCurrentIndex(panel.catalog_item_combo.findData(1))
    panel.add_catalog_invoice_line()

    panel.description_field.setText("Manual production")
    panel.quantity_field.setText("1.5")
    panel.unit_price_field.setText("100.00")
    panel.vat_rate_field.setText("2100")
    panel.add_manual_invoice_line()

    monkeypatch.setattr(
        "isrc_manager.invoicing.workspace.TravelDistanceService.estimate_one_way_km",
        lambda *_args, **_kwargs: TravelDistanceResult("A", "B", "10"),
    )
    panel.travel_origin_field.setText("Amsterdam")
    panel.travel_destination_field.setText("Utrecht")
    panel.travel_rate_field.setText("0.35")
    panel.travel_round_trip_check.setChecked(True)
    panel.calculate_travel_km()
    panel.add_travel_invoice_line()
    panel.create_draft_invoice()

    assert warnings == []
    assert panel.draft_line_table.rowCount() == 0
    assert conn.execute("SELECT COUNT(*) FROM InvoiceCatalogItems").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM InvoiceLineItems").fetchone()[0] == 3
    assert conn.execute(
        "SELECT quantity_value, quantity_scale FROM InvoiceLineItems WHERE source_type='travel'"
    ).fetchone() == (20, 0)
    assert conn.execute("SELECT total_minor FROM Invoices").fetchone()[0] > 0

    panel.deleteLater()
    conn.close()


def test_invoice_workspace_panel_records_payment_and_credit_with_patched_prompts(monkeypatch):
    _app()
    conn = _connection()
    PartyService(conn).create_party(
        PartyPayload(
            legal_name="Venue BV",
            display_name="Venue",
            party_type="organization",
        )
    )
    warnings: list[str] = []
    monkeypatch.setattr(
        "isrc_manager.invoicing.workspace.QMessageBox.warning",
        lambda _parent, _title, message: warnings.append(str(message)),
    )
    panel = InvoiceWorkspacePanel(conn_provider=lambda: conn)
    panel.description_field.setText("Venue service")
    panel.unit_price_field.setText("100.00")
    panel.vat_rate_field.setText("2100")
    panel.create_draft_invoice()
    panel.refresh_invoices()
    panel.invoice_table.selectRow(0)
    panel.issue_selected_invoice()
    panel.invoice_table.selectRow(0)

    monkeypatch.setattr(
        "isrc_manager.invoicing.workspace.QInputDialog.getText",
        lambda *_args, **_kwargs: ("10.00", True),
    )
    panel.record_payment_for_selected_invoice()
    panel.invoice_line_table.selectRow(0)
    panel.credit_subtotal_field.setText("4.13")
    panel.credit_vat_field.setText("0.87")
    panel.credit_reason_field.setText("Service correction")
    panel.create_credit_note_for_selected_invoice()
    panel.void_selected_invoice()
    panel.refresh_reports()

    invoice_id = int(panel.invoice_table.item(0, 0).text())
    invoice = InvoiceService(conn).fetch_invoice(invoice_id)
    assert invoice is not None
    assert conn.execute("SELECT COUNT(*) FROM InvoicePayments").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM CreditNotes").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM CreditNoteLineAllocations").fetchone()[0] == 1
    assert any("Only unsettled" in warning for warning in warnings)
    assert "Outstanding invoices" in panel.report_output.toPlainText()

    panel.deleteLater()
    conn.close()


def test_invoice_workspace_panel_handles_royalty_calculation_statement_and_payout():
    _app()
    conn = _connection()
    PartyService(conn).create_party(
        PartyPayload(
            legal_name="Artist Person",
            display_name="Artist",
            artist_name="Artist",
            party_type="artist",
        )
    )
    panel = InvoiceWorkspacePanel(conn_provider=lambda: conn)
    panel.focus_tab("royalties")
    panel.royalty_description_field.setText("Streaming royalty")
    panel.royalty_amount_field.setText("150.00")
    panel.royalty_period_start_field.setText("2026-01-01")
    panel.royalty_period_end_field.setText("2026-01-31")

    panel.create_royalty_calculation()
    panel.royalty_table.selectRow(0)
    panel.approve_selected_royalty_calculation()
    panel.royalty_table.selectRow(0)
    panel.generate_statement_for_selected_royalty()
    panel.royalty_table.selectRow(0)
    panel.royalty_payout_amount_field.setText("150.00")
    panel.royalty_payment_reference_field.setText("BANK-ROY-1")
    panel.record_artist_payout_for_selected_royalty()
    panel.refresh_reports()

    assert panel.tabs.currentIndex() == 0
    assert panel.royalty_table.rowCount() == 1
    assert conn.execute("SELECT status FROM RoyaltyCalculations").fetchone()[0] == "paid"
    assert (
        conn.execute("SELECT statement_number FROM RoyaltyStatements")
        .fetchone()[0]
        .startswith("ROY")
    )
    assert conn.execute("SELECT COUNT(*) FROM ArtistPayouts").fetchone()[0] == 1
    assert "Party balances" in panel.report_output.toPlainText()

    panel.deleteLater()
    conn.close()


def test_invoice_workspace_panel_integrates_contract_royalty_context_terms_and_events():
    _app()
    conn = _connection()
    contract_id, work_id, publisher_id, _right_id = _integrated_royalty_fixture(conn)
    panel = InvoiceWorkspacePanel(conn_provider=lambda: conn)
    panel.focus_tab("royalties")

    panel.royalty_term_party_combo.setCurrentIndex(
        panel.royalty_term_party_combo.findData(publisher_id)
    )
    panel.royalty_term_rate_field.setText("1500")
    panel.royalty_term_right_type_field.setText("composition_publishing")
    panel.royalty_term_scope_type_combo.setCurrentIndex(
        panel.royalty_term_scope_type_combo.findData("work")
    )
    panel.royalty_term_scope_id_combo.setCurrentIndex(
        panel.royalty_term_scope_id_combo.findData(work_id)
    )
    panel.create_contract_royalty_term()
    panel.royalty_source_description_field.setText("DSP January statement")
    panel.royalty_source_type_field.setText("statement")
    panel.royalty_source_id_field.setText("DSP-2026-01")
    panel.royalty_event_work_combo.setCurrentIndex(panel.royalty_event_work_combo.findData(work_id))
    panel.royalty_source_gross_field.setText("120.00")
    panel.royalty_source_net_field.setText("100.00")
    panel.royalty_source_period_start_field.setText("2026-01-01")
    panel.royalty_source_period_end_field.setText("2026-01-31")
    panel.royalty_source_metadata_field.setText("imported from statement")
    panel.record_royalty_source_event()
    panel.royalty_period_start_field.setText("2026-01-01")
    panel.royalty_period_end_field.setText("2026-01-31")
    panel.generate_contract_royalty_calculations()

    assert panel.tabs.currentIndex() == 0
    assert panel.royalty_workflow_tabs.currentIndex() == 3
    assert "Ready for royalty accounting: yes" in panel.royalty_context_output.toPlainText()
    assert panel.royalty_term_table.rowCount() == 1
    assert panel.royalty_source_event_table.rowCount() == 1
    assert panel.royalty_table.rowCount() == 1
    assert conn.execute("SELECT COUNT(*) FROM RoyaltyCalculationSourceLinks").fetchone()[0] == 1
    assert conn.execute("SELECT net_payable_minor FROM RoyaltyCalculations").fetchone()[0] == 1_500
    assert conn.execute("SELECT contract_id FROM RoyaltyCalculations").fetchone()[0] == contract_id

    panel.deleteLater()
    conn.close()


def test_invoice_workspace_panel_opens_related_workspaces_and_restores_layout():
    _app()
    conn = _connection()
    contract_id, work_id, _publisher_id, right_id = _integrated_royalty_fixture(conn)
    opened: list[tuple[str, int | None]] = []
    panel = InvoiceWorkspacePanel(
        conn_provider=lambda: conn,
        open_contract_manager=lambda selected_id: opened.append(("contract", selected_id)),
        open_work_manager=lambda selected_id: opened.append(("work", selected_id)),
        open_rights_matrix=lambda selected_id: opened.append(("right", selected_id)),
    )
    panel.focus_tab("royalties")
    panel.royalty_workflow_tabs.setCurrentIndex(1)

    panel.open_selected_contract_workspace()
    panel.open_selected_work_workspace()
    panel.open_selected_rights_workspace()
    double_clicked_item = None
    for row in range(panel.rights_titles_table.rowCount()):
        item = panel.rights_titles_table.item(row, 0)
        if item is not None and item.data(Qt.ItemDataRole.UserRole) == work_id:
            double_clicked_item = item
            break
    assert double_clicked_item is not None
    assert double_clicked_item.data(Qt.ItemDataRole.UserRole + 1) == right_id
    panel.rights_titles_table.itemDoubleClicked.emit(double_clicked_item)
    state = panel.capture_layout_state()
    restored = InvoiceWorkspacePanel(conn_provider=lambda: conn)
    restored.restore_layout_state(state)

    assert opened == [
        ("contract", contract_id),
        ("work", work_id),
        ("right", right_id),
        ("work", work_id),
    ]
    assert restored.tabs.currentIndex() == 0
    assert restored.royalty_workflow_tabs.currentIndex() == 1
    assert restored.royalty_contract_combo.currentData() == contract_id

    panel.deleteLater()
    restored.deleteLater()
    conn.close()


def test_invoice_workspace_panel_handles_missing_profile_and_empty_selection(monkeypatch):
    _app()
    warnings: list[str] = []
    monkeypatch.setattr(
        "isrc_manager.invoicing.workspace.QMessageBox.warning",
        lambda _parent, _title, message: warnings.append(str(message)),
    )
    panel = InvoiceWorkspacePanel(conn_provider=lambda: None)

    panel.refresh_all()
    panel.create_draft_invoice()
    panel.issue_selected_invoice()
    panel.void_selected_invoice()
    panel.record_payment_for_selected_invoice()
    panel.create_credit_note_for_selected_invoice()
    panel.create_royalty_calculation()
    panel.approve_selected_royalty_calculation()
    panel.generate_statement_for_selected_royalty()
    panel.record_artist_payout_for_selected_royalty()
    panel.preview_selected_invoice()
    panel.create_contract_royalty_term()
    panel.record_royalty_source_event()
    panel.generate_contract_royalty_calculations()

    assert warnings
    assert all(message == "Open a profile first." for message in warnings)

    panel.deleteLater()


def test_invoice_workspace_panel_handles_credit_validation_and_cancelled_payment(monkeypatch):
    _app()
    conn = _connection()
    PartyService(conn).create_party(
        PartyPayload(
            legal_name="Venue BV",
            display_name="Venue",
            party_type="organization",
        )
    )
    warnings: list[str] = []
    monkeypatch.setattr(
        "isrc_manager.invoicing.workspace.QMessageBox.warning",
        lambda _parent, _title, message: warnings.append(str(message)),
    )
    monkeypatch.setattr(
        "isrc_manager.invoicing.workspace.QInputDialog.getText",
        lambda *_args, **_kwargs: ("", False),
    )
    panel = InvoiceWorkspacePanel(conn_provider=lambda: conn)
    panel.description_field.setText("Venue service")
    panel.unit_price_field.setText("100.00")
    panel.vat_rate_field.setText("2100")
    panel.create_draft_invoice()
    panel.refresh_invoices()
    panel.invoice_table.selectRow(0)
    panel.issue_selected_invoice()
    panel.invoice_table.selectRow(0)

    panel.record_payment_for_selected_invoice()
    panel.create_credit_note_for_selected_invoice()
    panel.invoice_line_table.selectRow(0)
    panel.create_credit_note_for_selected_invoice()

    assert conn.execute("SELECT COUNT(*) FROM InvoicePayments").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM CreditNotes").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM CreditNoteLineAllocations").fetchone()[0] == 1
    assert warnings == ["Enter a positive credit subtotal and VAT allocation."]

    panel.deleteLater()
    conn.close()


def test_invoice_workspace_panel_warns_without_party_and_reports_empty(monkeypatch):
    _app()
    conn = _connection()
    warnings: list[str] = []
    monkeypatch.setattr(
        "isrc_manager.invoicing.workspace.QMessageBox.warning",
        lambda _parent, _title, message: warnings.append(str(message)),
    )
    panel = InvoiceWorkspacePanel(conn_provider=lambda: conn)

    panel.create_draft_invoice()
    panel.refresh_reports()

    report = panel.report_output.toPlainText()
    assert warnings == ["Create a party before invoicing."]
    assert "No outstanding invoices." in report
    assert "No party ledger balances." in report
    assert "No VAT ledger entries." in report

    panel.deleteLater()
    conn.close()


def test_invoice_workspace_panel_handles_royalty_validation_paths(monkeypatch):
    _app()
    conn = _connection()
    warnings: list[str] = []
    monkeypatch.setattr(
        "isrc_manager.invoicing.workspace.QMessageBox.warning",
        lambda _parent, _title, message: warnings.append(str(message)),
    )
    panel = InvoiceWorkspacePanel(conn_provider=lambda: conn)

    panel.create_royalty_calculation()
    PartyService(conn).create_party(
        PartyPayload(
            legal_name="Artist Person",
            display_name="Artist",
            artist_name="Artist",
            party_type="artist",
        )
    )
    panel.refresh_all()
    panel.royalty_amount_field.setText("0")
    panel.create_royalty_calculation()

    assert warnings == [
        "Create an artist party before royalties.",
        "Royalty calculation payable amount must be greater than zero.",
    ]

    panel.deleteLater()
    conn.close()


def test_invoice_workspace_helpers_and_layout_restore_edge_paths() -> None:
    _app()
    conn = _connection()
    panel = InvoiceWorkspacePanel(conn_provider=lambda: conn)

    assert _display_date(None) == ""
    assert _display_date("2026-06-01T12:13:14Z") == "01-Jun-2026"
    assert _display_date("not-a-date") == "not-a-date"
    assert _status_label("") == "Unknown"
    assert _invoice_template_symbol_key("{{manual.date}}") == "{{manual.date}}"
    assert _invoice_template_symbol_key("manual.date") == "{{manual.date}}"
    assert _invoice_template_symbol_key("{{db.invoice.number}}") == "invoice.number"
    assert _invoice_template_symbol_key("{{current.year}}") == "{{current.year}}"
    assert _invoice_template_symbol_key("invoice-number") == "invoice_number"
    assert _contract_placeholder_token("") is None
    assert _contract_placeholder_token("{{bad }}") is None
    assert _template_value_preview("<b>A&nbsp; B</b>\n C") == "A B C"

    panel.restore_layout_state(None)
    panel.restore_layout_state({"tab": 2, "tab_schema": "legacy_v0", "invoice_tab": 99})
    assert panel.tabs.currentIndex() == 1
    panel.restore_layout_state({"tab_key": "reports", "invoice_tab": 1, "royalty_tab": 2})
    assert panel.tabs.currentIndex() == 4
    assert panel.invoice_workflow_tabs.currentIndex() == 1
    assert panel.royalty_workflow_tabs.currentIndex() == 2

    panel.deleteLater()
    conn.close()


def test_invoice_workspace_panel_edges_warn_and_keep_ui_stable(monkeypatch) -> None:
    _app()
    conn = _connection()
    warnings: list[str] = []
    monkeypatch.setattr(
        "isrc_manager.invoicing.workspace.QMessageBox.warning",
        lambda _parent, _title, message: warnings.append(str(message)),
    )
    panel = InvoiceWorkspacePanel(conn_provider=lambda: conn)

    panel.refresh_royalty_context()
    panel.refresh_royalty_terms()
    panel.refresh_royalty_source_events()
    panel.add_catalog_invoice_line()
    panel.travel_km_field.setText("bad")
    panel.add_travel_invoice_line()
    monkeypatch.setattr(
        "isrc_manager.invoicing.workspace.TravelDistanceService.estimate_one_way_km",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("distance failed")),
    )
    panel.calculate_travel_km()
    panel.description_field.setText("Removable line")
    panel.unit_price_field.setText("1.00")
    panel.add_manual_invoice_line()
    panel.draft_line_table.selectRow(0)
    panel.remove_selected_draft_line()
    panel.clear_draft_lines()
    panel.catalog_name_field.setText("Broken preset")
    panel.catalog_unit_price_field.setText("not-money")
    panel.save_catalog_preset()
    panel.record_artist_payout_for_selected_royalty()
    panel.open_selected_contract_workspace()
    panel.open_selected_work_workspace()
    panel.open_selected_track_workspace()
    panel.open_selected_rights_workspace()
    panel.open_selected_rights_title_record(None)

    assert "Select an active contract" in panel.royalty_context_output.toPlainText()
    assert panel.royalty_term_table.rowCount() == 0
    assert panel.royalty_source_event_table.rowCount() == 0
    assert panel.draft_line_table.rowCount() == 0
    assert any("distance failed" in warning for warning in warnings)
    assert any(
        "Money amount must be a decimal string or integer." in warning for warning in warnings
    )
    assert "Contract manager is unavailable." in warnings
    assert "Work manager is unavailable." in warnings
    assert "Track editor is unavailable." in warnings
    assert "Rights matrix is unavailable." in warnings
    assert "No linked work or rights record is available." in warnings

    panel.deleteLater()
    conn.close()


def test_invoice_workspace_template_preview_edges(monkeypatch, tmp_path) -> None:
    _app()
    conn = _connection()
    panel = InvoiceWorkspacePanel(conn_provider=lambda: conn)
    source_file = tmp_path / "template.html"
    source_file.write_text(
        "<html><head></head><body>{{ invoice.number }}</body></html>", encoding="utf-8"
    )

    assert panel._inject_invoice_preview_base_href("plain", source_path=None) == "plain"
    assert "<base href=" in panel._inject_invoice_preview_base_href(
        "<html><head><title>x</title></head><body>x</body></html>",
        source_path=source_file,
    )
    assert (
        panel._inject_invoice_preview_base_href(
            '<html><head><base href="x"></head></html>',
            source_path=source_file,
        ).count("<base")
        == 1
    )
    assert panel._inject_invoice_preview_base_href(
        "<!doctype html><html><body>x</body></html>",
        source_path=source_file,
    ).startswith("<!doctype html><head><base")
    assert panel._inject_invoice_preview_base_href("body only", source_path=source_file).startswith(
        "<head><base"
    )

    panel.template_path_field.setText(str(source_file))
    assert panel._active_template_source_path() == source_file
    panel.template_path_field.setText(str(tmp_path / "missing.html"))
    assert panel._active_template_source_path() is None

    monkeypatch.setattr(
        "isrc_manager.invoicing.workspace.QFileDialog.getOpenFileName",
        lambda *_args, **_kwargs: ("", ""),
    )
    panel.browse_template_file()
    panel.template_html_editor.setPlainText("<html><body>{{ invoice.number }}</body></html>")
    panel.template_path_field.setText("")
    panel.template_name_field.setText("Inline Template")
    panel.upload_template()
    assert "Active revision" in panel.template_status_label.text()

    monkeypatch.setattr(
        "isrc_manager.invoicing.workspace.QFileDialog.getOpenFileName",
        lambda *_args, **_kwargs: (str(source_file), "HTML templates"),
    )
    panel.browse_template_file()
    assert panel.template_path_field.text() == str(source_file)

    panel.template_html_editor.clear()
    sample_preview = panel._sample_template_preview_html()
    assert "Sample preview" in sample_preview
    assert "INV-2026-0001" in sample_preview
    panel._refresh_template_symbol_matches(resolved_values={})
    assert not panel.template_symbol_combo.isEnabled()
    assert "Upload an HTML template" in panel.template_symbol_detail_output.toPlainText()
    assert panel._template_duplicate_count({}) == 1
    assert panel._template_duplicate_count({"{{duplicate.number}}": "bad"}) == 1
    assert panel._template_duplicate_count({"{{duplicate.number}}": "2.5"}) == 1
    assert panel._template_duplicate_count({"{{duplicate.number}}": "250"}) == 200

    panel._set_invoice_preview_html("<html><body>Preview</body></html>", source_path=source_file)
    assert panel._invoice_preview_session_dir is not None
    panel._clear_invoice_preview_surface()
    assert panel.invoice_preview_zoom_label.text() == "100%"
    panel._reset_invoice_html_preview_to_fit()
    panel._step_invoice_html_preview_zoom(25)
    assert panel._current_invoice_preview_zoom_percent() >= 100

    panel.deleteLater()
    conn.close()


def test_invoice_workspace_template_form_handles_rich_placeholder_matrix() -> None:
    _app()
    conn = _connection()
    party_id = PartyService(conn).create_party(
        PartyPayload(
            legal_name="Template Party Legal BV",
            display_name="Template Party",
            company_name="Template Party Company",
            party_type="licensee",
            email="template-party@example.test",
            street_name="Damrak",
            street_number="1",
            postal_code="1012 LG",
            city="Amsterdam",
            country="NL",
            vat_number="NL001122334B01",
        )
    )
    owner_id = PartyService(conn).create_party(
        PartyPayload(
            legal_name="Owner Legal BV",
            display_name="Owner Display",
            company_name="Owner Company",
            party_type="organization",
            vat_number="NL009988776B01",
            street_name="Koelhorst",
            street_number="25",
            city="Ede",
            postal_code="6714 KL",
            country="NL",
        )
    )
    conn.execute("INSERT INTO ApplicationOwnerBinding(id, party_id) VALUES(1, ?)", (owner_id,))
    track_id = conn.execute(
        """
        INSERT INTO Tracks(
            isrc, isrc_compact, track_title, main_artist_party_id, composer, track_length_sec
        )
        VALUES ('NL-C51-26-00999', 'NLC512600999', 'Template Track', ?,
                'Template Writer', 241)
        """,
        (party_id,),
    ).lastrowid
    conn.commit()

    panel = InvoiceWorkspacePanel(conn_provider=lambda: conn)
    panel.template_html_editor.setPlainText(
        "\n".join(
            (
                "{{db.party.display_name}}",
                "{{db.party.display_name.indexed}}",
                "{{db.track.track_title.indexed}}",
                "{{db.owner.vat_number}}",
                "{{db.invoice.total}}",
                "{{db.royalty.statement_number}}",
                "{{db.unknown.value}}",
                "{{manual.choice$list[A;B]}}",
                "{{manual.deadline}}",
                "{{manual.amount}}",
                "{{manual.flag$bool[Yes;No]}}",
                "{{manual.enabled$bool}}",
                "{{manual.free_text}}",
                "{{custom.legacy_note}}",
            )
        )
    )
    definition = panel._template_form_definition()
    fields = {field.canonical_symbol: field for field in definition.manual_fields}
    indexed_fields = {field.canonical_symbol: field for field in definition.indexed_manual_fields}

    assert "{{duplicate.number}}" in fields
    assert fields["{{manual.choice$list[A;B]}}"].field_type == "list"
    assert fields["{{manual.deadline}}"].field_type == "date"
    assert fields["{{manual.amount}}"].field_type == "number"
    assert fields["{{manual.flag$bool[Yes;No]}}"].field_type == "boolean"
    assert fields["custom.legacy_note"].widget_kind == "text_input"
    assert "{{manual.free_text}}" in fields
    assert "custom.enabled$bool" in fields
    assert "{{manual.flag$bool[Yes;No]}}" not in indexed_fields
    assert len(definition.selector_fields) == 1
    assert len(definition.indexed_selector_fields) == 2
    assert definition.warnings

    panel._rebuild_template_fill_fields()
    duplicate_widget = panel.template_manual_widgets["{{duplicate.number}}"]
    assert isinstance(duplicate_widget, QDoubleSpinBox)
    duplicate_widget.setValue(2)
    duplicate_widget.setProperty("has_user_value", True)
    panel._run_deferred_template_fill_field_rebuild()

    list_widget = panel.template_manual_widgets["{{manual.choice$list[A;B]}}"]
    date_widget = panel.template_manual_widgets["{{manual.deadline}}"]
    amount_widget = panel.template_manual_widgets["{{manual.amount}}"]
    bool_options_widget = panel.template_manual_widgets["{{manual.flag$bool[Yes;No]}}"]
    text_widget = panel.template_manual_widgets["{{manual.free_text}}"]
    assert isinstance(list_widget, QComboBox)
    assert isinstance(date_widget, QDateEdit)
    assert isinstance(amount_widget, QDoubleSpinBox)
    assert isinstance(bool_options_widget, QComboBox)
    assert isinstance(text_widget, QLineEdit)
    bool_checkbox = panel._build_template_manual_widget(
        ContractTemplateFormManualField(
            canonical_symbol="{{manual.enabled}}",
            display_label="Enabled",
            field_type="boolean",
            widget_kind="checkbox",
            required=True,
            placeholder_count=1,
            description="Boolean checkbox.",
        )
    )
    assert isinstance(bool_checkbox, QCheckBox)
    panel.template_manual_widgets["{{manual.enabled}}"] = bool_checkbox

    list_widget.setCurrentIndex(list_widget.findData("B"))
    panel._write_template_widget_value(date_widget, "2026-06-01", explicit=True)
    panel._write_template_widget_value(amount_widget, 42.5, explicit=True)
    panel._write_template_widget_value(bool_options_widget, "Yes", explicit=True)
    panel._write_template_widget_value(bool_checkbox, True, explicit=True)
    panel._write_template_widget_value(text_widget, "Manual value", explicit=True)

    party_widget = panel.template_selector_widgets["{{db.party.display_name}}"]
    panel._write_template_widget_value(party_widget, str(party_id), explicit=True)
    for key, widget in panel.template_indexed_selector_widgets.items():
        combo = panel._template_selector_combo(widget)
        assert combo is not None
        if "track" in key:
            panel._write_template_widget_value(widget, str(track_id), explicit=True)
        else:
            panel._write_template_widget_value(widget, str(party_id), explicit=True)

    values = panel._template_manual_values()
    overrides = panel._template_canonical_overrides()
    panel._refresh_template_symbol_matches(
        resolved_values={
            **panel._sample_template_replacements(),
            **values,
            **overrides,
        },
        warnings=("{{db.unknown.value}} needs attention",),
    )
    panel._refresh_template_database_values()
    panel._refresh_template_database_detail()

    assert values["{{manual.choice$list[A;B]}}"] == "B"
    assert values["{{manual.amount}}"] == 42.5
    assert values["{{manual.enabled}}"] is True
    assert overrides["invoice.party.display_name"] == "Template Party"
    assert any("Template Track" in str(value) for value in overrides.values())
    attention_index = panel.template_symbol_combo.findData("{{db.unknown.value}}")
    assert attention_index >= 0
    panel.template_symbol_combo.setCurrentIndex(attention_index)
    panel._refresh_template_symbol_detail()
    assert "Needs attention" in panel.template_symbol_detail_output.toPlainText()
    assert "Unsupported database placeholder" in panel.template_database_value_combo.itemText(
        panel.template_database_value_combo.count() - 1
    )

    panel.deleteLater()
    conn.close()


def test_invoice_workspace_royalty_import_and_generation_edges(monkeypatch, tmp_path) -> None:
    _app()
    conn = _connection()
    contract_id, _work_id, _publisher_id, _right_id = _integrated_royalty_fixture(conn)
    infos: list[str] = []
    warnings: list[str] = []
    monkeypatch.setattr(
        "isrc_manager.invoicing.workspace.QMessageBox.information",
        lambda _parent, _title, message: infos.append(str(message)),
    )
    monkeypatch.setattr(
        "isrc_manager.invoicing.workspace.QMessageBox.warning",
        lambda _parent, _title, message: warnings.append(str(message)),
    )
    panel = InvoiceWorkspacePanel(conn_provider=lambda: conn)
    panel.royalty_contract_combo.setCurrentIndex(panel.royalty_contract_combo.findData(contract_id))

    monkeypatch.setattr(
        workspace_module.RoyaltyIntegrationService,
        "create_draft_calculations_from_contract",
        lambda *_args, **_kwargs: [],
    )
    panel.generate_contract_royalty_calculations()
    assert "No royalty calculations were generated." in panel.report_output.toPlainText()

    csv_path = tmp_path / "statement.csv"
    csv_path.write_text("date_id,total_gbp,store_name\n2026-01,1.23,TIDAL\n", encoding="utf-8")
    monkeypatch.setattr(
        "isrc_manager.invoicing.workspace.QFileDialog.getOpenFileName",
        lambda *_args, **_kwargs: ("", ""),
    )
    panel.import_royalty_source_events()

    class _RejectedImportDialog:
        def __init__(self, **_kwargs):
            pass

        def exec(self):
            return workspace_module.QDialog.DialogCode.Rejected

    monkeypatch.setattr(workspace_module, "RoyaltySourceImportDialog", _RejectedImportDialog)
    monkeypatch.setattr(
        "isrc_manager.invoicing.workspace.QFileDialog.getOpenFileName",
        lambda *_args, **_kwargs: (str(csv_path), "CSV Files"),
    )
    panel.import_royalty_source_events()

    class _AcceptedImportDialog:
        def __init__(self, **kwargs):
            self.inspection = kwargs["inspection"]

        def exec(self):
            return workspace_module.QDialog.DialogCode.Accepted

        def mapping(self):
            return self.inspection.suggested_mapping

    monkeypatch.setattr(workspace_module, "RoyaltySourceImportDialog", _AcceptedImportDialog)
    panel.import_royalty_source_events()

    assert any("Rows imported: 1" in message for message in infos)
    assert conn.execute("SELECT COUNT(*) FROM RoyaltySourceEvents").fetchone()[0] == 1
    assert warnings == []

    panel.deleteLater()
    conn.close()


def test_invoice_workspace_controller_routes_panel_opening():
    _app()
    conn = _connection()
    captured: dict[str, object] = {}

    class FakeApp:
        def __init__(self):
            self.conn = conn

        def _ensure_invoice_workspace_dock(self):
            captured["ensured"] = True
            return object()

        def _show_workspace_panel(self, ensure_dock, *, panel_attr, configure):
            ensure_dock()
            panel = InvoiceWorkspacePanel(conn_provider=lambda: conn)
            configure(panel)
            captured["panel_attr"] = panel_attr
            captured["tab_index"] = panel.tabs.currentIndex()
            panel.deleteLater()
            return panel

    panel = invoice_controller.open_invoice_workspace(FakeApp(), initial_tab="reports")

    assert panel is not None
    assert captured == {
        "ensured": True,
        "panel_attr": "invoice_workspace_panel",
        "tab_index": 4,
    }

    conn.close()


def test_invoice_workspace_controller_warns_without_profile_and_creates_panel(monkeypatch):
    _app()
    conn = _connection()
    warnings: list[str] = []
    monkeypatch.setattr(
        invoice_controller,
        "_message_box",
        lambda: SimpleNamespace(
            warning=lambda _parent, _title, message: warnings.append(str(message))
        ),
    )

    class MissingProfileApp:
        conn = None

    assert invoice_controller.open_invoice_workspace(MissingProfileApp()) is None
    assert warnings == ["Open a profile first."]

    party_id = PartyService(conn).create_party(
        PartyPayload(legal_name="Controller Party", display_name="Controller Party")
    )
    opened_parties: list[int | None] = []
    panel = invoice_controller._create_invoice_workspace_panel(
        SimpleNamespace(
            conn=conn,
            open_party_manager=lambda selected_id: opened_parties.append(selected_id),
        ),
        None,
    )
    assert isinstance(panel, InvoiceWorkspacePanel)
    for row in range(panel.users_roles_table.rowCount()):
        item = panel.users_roles_table.item(row, 0)
        if item is not None and item.data(Qt.ItemDataRole.UserRole) == party_id:
            panel.users_roles_table.itemDoubleClicked.emit(item)
            break
    assert opened_parties == [party_id]

    panel.deleteLater()
    conn.close()

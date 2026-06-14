import sqlite3
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QWidget,
)

from isrc_manager.code_registry import (
    BUILTIN_CATEGORY_CREDIT_NOTE_NUMBER,
    BUILTIN_CATEGORY_INVOICE_NUMBER,
    BUILTIN_CATEGORY_ROYALTY_STATEMENT_NUMBER,
    CodeRegistryService,
)
from isrc_manager.contracts import ContractPartyPayload, ContractPayload, ContractService
from isrc_manager.invoicing import controller as invoice_controller
from isrc_manager.invoicing import workspace as workspace_module
from isrc_manager.invoicing.invoice_service import InvoiceService
from isrc_manager.invoicing.royalty_import import RoyaltySourceImportService
from isrc_manager.invoicing.travel_distance import TravelDistanceResult
from isrc_manager.invoicing.workspace import (
    InvoiceWorkspacePanel,
    _add_kpi_card,
    _display_date,
    _scrollable_page,
    _set_table_rows,
    _status_label,
)
from isrc_manager.parties import PartyPayload, PartyRecord, PartyService
from isrc_manager.rights import OwnershipInterestPayload, RightPayload, RightsService
from isrc_manager.services import DatabaseSchemaService
from isrc_manager.services.settings_reads import OwnerPartySettings
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


def test_invoice_workspace_panel_issues_invoice_without_template_handoff_tab(monkeypatch):
    _app()
    conn = _connection()
    opened_paths: list[Path] = []
    monkeypatch.setattr(
        workspace_module,
        "open_external_path",
        lambda path, **_kwargs: opened_paths.append(Path(path)) or True,
    )
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
    panel.view_selected_final_invoice()

    assert panel.invoice_table.rowCount() == 1
    status, ledger_transaction_id = conn.execute("""
        SELECT document_status, issued_ledger_transaction_id
        FROM Invoices
        """).fetchone()
    assert status == "issued"
    assert ledger_transaction_id is not None
    artifact_row = conn.execute("""
        SELECT artifact_type, status, storage_mode, content_blob IS NOT NULL
        FROM InvoiceOutputArtifacts
        """).fetchone()
    assert artifact_row == ("final_html", "final", "database", 1)
    assert opened_paths
    assert opened_paths[0].exists()
    assert "Venue service" in opened_paths[0].read_text(encoding="utf-8")
    assert not hasattr(panel, "template_linked_document_table")
    assert panel.findChild(QTableWidget, "invoiceTemplateLinkedDocumentTable") is None
    button_texts = {
        button.text() for button in panel.invoice_workflow_tabs.findChildren(QPushButton)
    }
    assert {"Open Invoice", "Open File Location", "Purge Selected"}.issubset(button_texts)
    assert button_texts.isdisjoint(
        {"Finalize / Issue", "View Final Invoice", "Template Workspace", "Refresh Docs"}
    )

    panel.deleteLater()
    conn.close()


def test_invoice_workspace_panel_purges_selected_invoice_after_confirmation(monkeypatch):
    _app()
    conn = _connection()
    PartyService(conn).create_party(
        PartyPayload(
            legal_name="Cleanup Venue BV",
            display_name="Cleanup Venue",
            party_type="organization",
        )
    )
    monkeypatch.setattr(
        workspace_module.QMessageBox,
        "question",
        lambda *_args, **_kwargs: workspace_module.QMessageBox.StandardButton.Yes,
    )
    panel = InvoiceWorkspacePanel(conn_provider=lambda: conn)
    panel.description_field.setText("Test invoice to purge")
    panel.unit_price_field.setText("75.00")
    panel.vat_rate_field.setText("0")
    panel.create_draft_invoice()
    panel.refresh_invoices()
    panel.invoice_table.selectRow(0)

    panel.purge_selected_invoice_for_cleanup()

    assert panel.invoice_table.rowCount() == 0
    assert conn.execute("SELECT COUNT(*) FROM Invoices").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM InvoiceLineItems").fetchone()[0] == 0
    assert "Purged invoice cleanup" in panel.invoice_final_status_label.text()

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
    settings_tabs = panel.tabs.widget(5).findChild(QTabWidget)
    assert settings_tabs is not None
    assert "Templates" not in [
        settings_tabs.tabText(index) for index in range(settings_tabs.count())
    ]
    assert panel.findChild(QTableWidget, "invoiceTemplateLinkedDocumentTable") is None

    panel.deleteLater()
    conn.close()


def test_invoice_workspace_billing_preset_dropdowns_link_to_admin_pages():
    _app()
    conn = _connection()
    panel = InvoiceWorkspacePanel(conn_provider=lambda: conn)

    assert isinstance(panel.catalog_category_combo, QComboBox)
    assert isinstance(panel.catalog_account_combo, QComboBox)
    assert panel.catalog_category_combo.findData("Services") >= 0
    assert panel.catalog_account_combo.findData("4100") >= 0

    panel.open_catalog_category_admin()
    settings_tabs = panel.tabs.widget(5).findChild(QTabWidget)
    assert settings_tabs is not None
    assert settings_tabs.tabText(settings_tabs.currentIndex()) == "Preset Categories"
    panel.catalog_category_name_field.setText("Consulting")
    panel.catalog_category_active_check.setChecked(True)
    panel.save_catalog_category()
    assert panel.catalog_category_combo.findData("Consulting") >= 0

    panel.open_ledger_account_admin()
    assert settings_tabs.tabText(settings_tabs.currentIndex()) == "Ledger Accounts"
    panel._clear_ledger_account_form()
    panel.account_code_field.setText("4200")
    panel.account_name_field.setText("Digital Sales")
    panel._select_required_combo_data(panel.account_type_combo, "income")
    panel._select_required_combo_data(panel.account_normal_balance_combo, "credit")
    panel.save_ledger_account()
    assert panel.catalog_account_combo.findData("4200") >= 0

    panel._select_combo_text(panel.catalog_category_combo, "Consulting")
    panel.catalog_account_combo.setCurrentIndex(panel.catalog_account_combo.findData("4200"))
    panel.catalog_name_field.setText("Mix consulting")
    panel.catalog_description_field.setText("Mix advice")
    panel.catalog_quantity_field.setText("1")
    panel.catalog_unit_price_field.setText("75.00")
    panel.catalog_vat_rate_field.setText("0")
    panel.catalog_vat_country_field.setText("NL")
    panel.save_catalog_preset()

    item = InvoiceService(conn).catalog_service.fetch_item(1)
    assert item is not None
    assert item.category == "Consulting"
    assert item.default_account_code == "4200"

    panel.deleteLater()
    conn.close()


def test_invoice_workspace_helpers_and_no_connection_command_paths(monkeypatch):
    _app()
    parent = QWidget()
    grid = QGridLayout(parent)
    kpi = _add_kpi_card(
        grid,
        row=0,
        column=0,
        title="Open",
        value="3",
        detail="Overdue",
        parent=parent,
    )
    scroll, content, layout = _scrollable_page(parent)
    table = QTableWidget(parent)

    _set_table_rows(table, ("Name", "Value"), [], empty_message="Empty")
    assert kpi.text() == "Open\n3\nOverdue"
    assert isinstance(scroll, QScrollArea)
    assert content.property("role") == "workspaceCanvas"
    assert layout.count() == 0
    assert table.rowCount() == 1
    assert table.item(0, 0).text() == "Empty"
    assert not bool(table.item(0, 0).flags() & Qt.ItemFlag.ItemIsSelectable)

    _set_table_rows(table, ("Name", "Value"), [("A",)], empty_message="Empty")
    assert table.item(0, 0).text() == "A"
    assert table.item(0, 1).text() == ""

    warnings: list[tuple[str, str]] = []
    monkeypatch.setattr(
        workspace_module.QMessageBox,
        "warning",
        lambda _parent, title, message: warnings.append((title, message)),
    )
    monkeypatch.setattr(
        workspace_module.QFileDialog,
        "getOpenFileName",
        lambda *_args, **_kwargs: ("", ""),
    )
    panel = InvoiceWorkspacePanel(conn_provider=lambda: None)

    for command in (
        panel.refresh_dashboard,
        panel.refresh_contracts,
        panel.refresh_rights_titles,
        panel.refresh_imports,
        panel.refresh_statements,
        panel.refresh_invoices,
        panel.refresh_invoice_lines,
        panel.refresh_accounting,
        panel.refresh_payments,
        panel.refresh_reports,
        panel.refresh_royalty_context,
        panel.refresh_royalty_terms,
        panel.refresh_royalty_source_events,
        panel.refresh_royalties,
        panel.create_draft_invoice,
        panel.add_manual_invoice_line,
        panel.add_catalog_invoice_line,
        panel.add_travel_invoice_line,
        panel.remove_selected_draft_line,
        panel.clear_draft_lines,
        panel.save_catalog_preset,
        panel.issue_selected_invoice,
        panel.view_selected_final_invoice,
        panel.void_selected_invoice,
        panel.record_payment_for_selected_invoice,
        panel.create_credit_note_for_selected_invoice,
        panel.create_royalty_calculation,
        panel.record_royalty_source_event,
        panel.generate_contract_royalty_calculations,
        panel.approve_selected_royalty_calculation,
        panel.generate_statement_for_selected_royalty,
        panel.record_artist_payout_for_selected_royalty,
    ):
        command()

    panel.description_field.clear()
    panel.quantity_field.setText("2")
    panel.unit_price_field.setText("12.50")
    panel.vat_rate_field.setText("2100")
    panel.add_manual_invoice_line()
    assert panel.draft_line_table.item(0, 1).text() == "Manual item"
    panel.travel_description_field.setText("Mileage")
    panel.travel_origin_field.setText("Amsterdam")
    panel.travel_destination_field.setText("Rotterdam")
    panel.travel_km_field.setText("10")
    panel.travel_rate_field.setText("0.35")
    panel.travel_round_trip_check.setChecked(True)
    panel.add_travel_invoice_line()
    assert "round trip" in panel.draft_line_table.item(1, 1).text()
    panel.draft_line_table.selectRow(0)
    panel.remove_selected_draft_line()
    assert len(panel._draft_invoice_lines) == 1
    panel.clear_draft_lines()
    assert panel.draft_line_table.rowCount() == 0

    class _TravelService:
        def estimate_one_way_km(self, origin: str, destination: str) -> TravelDistanceResult:
            assert origin == "Amsterdam"
            assert destination == "Rotterdam"
            return TravelDistanceResult("Amsterdam", "Rotterdam", "61.4")

    monkeypatch.setattr(workspace_module, "TravelDistanceService", _TravelService)
    panel.travel_description_field.clear()
    panel.calculate_travel_km()
    assert panel.travel_km_field.text() == "61.4"
    assert panel.travel_description_field.text() == "Travel costs"

    for command in (
        panel._refresh_company_settings,
        panel._refresh_users_roles_settings,
        panel._refresh_vat_tax_settings,
        panel._browse_integration_statement_file,
        panel._inspect_integrations_statement,
        panel._open_integrations_import_wizard,
        panel._refresh_integrations_settings,
        panel._refresh_workflows_settings,
        panel._refresh_parties,
        panel._refresh_invoice_catalog,
        panel._refresh_royalty_contracts,
        panel._refresh_royalty_parties,
        panel._refresh_selected_royalty_contract_context,
        lambda: panel._populate_context_entity_choices(None),
        lambda: panel._scalar("SELECT 1"),
        lambda: panel._refresh_dashboard_kpi_labels(),
        lambda: panel._refresh_dashboard_tables(()),
    ):
        command()
    selected_statement = Path("/tmp/dsp-statement.csv")
    monkeypatch.setattr(
        workspace_module.QFileDialog,
        "getOpenFileName",
        lambda *_args, **_kwargs: (str(selected_statement), ""),
    )
    refresh_calls: list[str] = []
    panel._refresh_integrations_settings = lambda: refresh_calls.append("integrations")
    panel._browse_integration_statement_file()
    assert panel.integration_file_path_field.text() == str(selected_statement)
    assert refresh_calls == ["integrations"]
    assert warnings

    panel.deleteLater()
    parent.deleteLater()


def test_invoice_workspace_display_and_selection_helpers():
    _app()
    panel = InvoiceWorkspacePanel(conn_provider=lambda: None)

    assert _display_date(None) == ""
    assert _display_date("2026-02-03") == "03-Feb-2026"
    assert _display_date("2026-02-03T04:05:06") == "03-Feb-2026"
    assert _display_date("not-a-date") == "not-a-date"
    assert _status_label(None) == "Unknown"
    assert _status_label("needs_setup") == "Needs Setup"

    panel.restore_layout_state(None)
    panel.restore_layout_state(
        {
            "tab": 3,
            "tab_schema": "legacy_with_home",
            "invoice_tab": 0,
            "royalty_tab": 0,
            "invoice_id": 99,
            "royalty_calculation_id": 88,
        }
    )
    assert panel.tabs.currentIndex() == 2
    panel.restore_layout_state({"tab_key": "reports"})
    assert panel.tabs.tabText(panel.tabs.currentIndex()) == "Reports"

    panel.invoice_table = SimpleNamespace(selectedItems=lambda: [])
    assert panel._selected_invoice_id() is None
    invoice_item = QTableWidgetItem("12")
    selected_cell = SimpleNamespace(row=lambda: 0)
    panel.invoice_table = SimpleNamespace(
        selectedItems=lambda: [selected_cell],
        item=lambda _row, _column: invoice_item,
    )
    assert panel._selected_invoice_id() == 12
    invoice_item.setData(Qt.ItemDataRole.UserRole, 13)
    assert panel._selected_invoice_id() == 13

    panel.catalog_table = SimpleNamespace(selectedItems=lambda: [])
    assert panel._selected_catalog_item_id() is None
    catalog_item = QTableWidgetItem("21")
    catalog_item.setData(Qt.ItemDataRole.UserRole, "22")
    panel.catalog_table = SimpleNamespace(
        selectedItems=lambda: [selected_cell],
        item=lambda _row, _column: catalog_item,
    )
    assert panel._selected_catalog_item_id() == 22

    rights_item = QTableWidgetItem("right")
    rights_item.setData(Qt.ItemDataRole.UserRole, "31")
    rights_item.setData(Qt.ItemDataRole.UserRole + 1, "32")
    panel.rights_titles_table = SimpleNamespace(selectedItems=lambda: [rights_item])
    assert panel._selected_rights_titles_work_id() == 31
    assert panel._selected_rights_titles_right_id() == 32
    assert panel._rights_titles_item_id(None, Qt.ItemDataRole.UserRole) is None
    invalid_item = QTableWidgetItem("invalid")
    invalid_item.setData(Qt.ItemDataRole.UserRole, "not-int")
    assert panel._rights_titles_item_id(invalid_item, Qt.ItemDataRole.UserRole) is None

    empty_combo = QComboBox()
    assert panel._combo_int_data(empty_combo) is None
    empty_combo.addItem("Nine", "9")
    empty_combo.setCurrentIndex(0)
    assert panel._combo_int_data(empty_combo) == 9
    assert panel._format_named_ids("Tracks", ()) == "none"
    assert panel._optional_id_label("Tracks", 5) == "#5"
    assert panel._party_label(None) == ""
    assert panel._party_label(8) == "Party #8"

    panel.deleteLater()


def test_invoice_workspace_settings_role_formatting_and_error_edges(monkeypatch):
    _app()
    panel = InvoiceWorkspacePanel(conn_provider=lambda: None)

    no_owner_text = panel._format_owner_ledger_settings(OwnerPartySettings())
    assert "No current Owner Party is set" in no_owner_text

    owner_text = panel._format_owner_ledger_settings(
        OwnerPartySettings(
            party_id=44,
            display_name="",
            legal_name="",
            company_name="",
            notes="Owner setup note",
        )
    )
    assert "Party #44" in owner_text
    assert "Owner notes" in owner_text
    assert "company/legal name" in owner_text
    assert "billing address" in owner_text
    assert "VAT number" in owner_text
    assert "bank account" in owner_text

    def party_record(**overrides) -> PartyRecord:
        values = {
            "id": 9,
            "legal_name": "",
            "display_name": None,
            "artist_name": None,
            "company_name": None,
            "first_name": None,
            "middle_name": None,
            "last_name": None,
            "party_type": "artist",
            "contact_person": None,
            "email": None,
            "alternative_email": None,
            "phone": None,
            "website": None,
            "street_name": None,
            "street_number": None,
            "address_line1": None,
            "address_line2": None,
            "city": None,
            "region": None,
            "postal_code": None,
            "country": None,
            "bank_account_number": None,
            "chamber_of_commerce_number": None,
            "tax_id": None,
            "vat_number": None,
            "pro_affiliation": None,
            "pro_number": None,
            "ipi_cae": None,
            "notes": None,
            "profile_name": None,
            "created_at": "2026-01-01",
            "updated_at": "2026-01-02",
            "artist_aliases": (),
        }
        values.update(overrides)
        return PartyRecord(**values)

    artist = party_record(id=10, artist_name="Artist", party_type="artist")
    licensee = party_record(id=11, legal_name="Client BV", party_type="licensee")
    distributor = party_record(id=12, legal_name="DSP", party_type="distributor")
    manager = party_record(id=13, legal_name="Manager", party_type="manager")
    other = party_record(id=14, legal_name="Other", party_type="other", notes="Party note")

    assert panel._party_display_label(artist) == "Artist"
    assert panel._party_contact_summary(artist) == "-"
    assert panel._party_accounting_role(artist, is_owner=True) == "Current owner / invoice issuer"
    assert "Royalty payee" in panel._party_accounting_role(artist, is_owner=False)
    assert "Customer" in panel._party_accounting_role(licensee, is_owner=False)
    assert "General" in panel._party_accounting_role(other, is_owner=False)
    assert "Seller identity" in panel._party_workflow_use(artist, is_owner=True)
    assert "Royalty calculations" in panel._party_workflow_use(artist, is_owner=False)
    assert "Sales invoices" in panel._party_workflow_use(licensee, is_owner=False)
    assert "DSP imports" in panel._party_workflow_use(distributor, is_owner=False)
    assert "Contract review" in panel._party_workflow_use(manager, is_owner=False)
    assert "audit traceability" in panel._party_workflow_use(other, is_owner=False)
    assert panel._party_role_readiness_gaps(artist, is_owner=False) == [
        "contact",
        "payout bank",
        "tax/rights ID",
    ]
    assert panel._party_role_readiness_gaps(licensee, is_owner=False) == [
        "contact",
        "billing address",
        "VAT/tax ID",
    ]
    assert panel._party_role_readiness_gaps(other, is_owner=True) == [
        "contact",
        "billing address",
        "VAT",
        "bank",
    ]
    formatted = panel._format_party_role_settings(other, is_owner=False)
    assert "Party notes" in formatted
    assert "Party note" in formatted

    invalid_item = QTableWidgetItem("bad")
    invalid_item.setData(Qt.ItemDataRole.UserRole, "bad")
    panel.users_roles_table = SimpleNamespace(selectedItems=lambda: [invalid_item])
    assert panel._selected_users_roles_party_id() is None
    assert panel._users_roles_party_id_from_item(None) is None
    assert panel._users_roles_party_id_from_item(invalid_item) is None

    warnings: list[tuple[str, str]] = []
    monkeypatch.setattr(
        workspace_module.QMessageBox,
        "warning",
        lambda _parent, title, message: warnings.append((title, message)),
    )
    opened: list[int | None] = []
    panel._open_party_manager = None
    panel.open_selected_users_roles_party()
    panel._open_party_manager = lambda party_id: opened.append(party_id)
    good_item = QTableWidgetItem("good")
    good_item.setData(Qt.ItemDataRole.UserRole, "55")
    panel.open_selected_users_roles_party(good_item)
    assert warnings[-1][0] == "Party Manager"
    assert opened == [55]

    panel._conn_provider = lambda: None
    panel._refresh_users_roles_detail()
    conn = _connection()
    panel._conn_provider = lambda: conn
    panel.users_roles_table = SimpleNamespace(selectedItems=lambda: [good_item])
    panel._refresh_users_roles_detail()
    assert "no longer exists" in panel.users_roles_detail_output.toPlainText()

    class _BrokenSettingsReadService:
        def __init__(self, _conn) -> None:
            pass

        def load_owner_party_settings(self):
            raise RuntimeError("owner failed")

    monkeypatch.setattr(workspace_module, "SettingsReadService", _BrokenSettingsReadService)
    panel._refresh_company_settings()
    assert "Unable to load" in panel.company_owner_output.toPlainText()
    panel._refresh_vat_tax_settings()
    assert "Unable to load VAT" in panel.vat_tax_detail_output.toPlainText()

    panel.integration_file_path_field.setText(str(Path("/tmp/missing-dsp.csv")))
    panel._open_integrations_import_wizard()
    assert warnings[-1][0] == "DSP Import"

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
    panel._select_combo_text(panel.catalog_category_combo, "Services")
    panel.catalog_account_combo.setCurrentIndex(panel.catalog_account_combo.findData("4100"))
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
    panel.catalog_vat_country_field.setText("US")
    panel._apply_catalog_currency_from_country()
    assert panel.catalog_currency_combo.currentData() == "USD"
    panel._select_combo_text(panel.catalog_category_combo, "Services")
    panel.catalog_account_combo.setCurrentIndex(panel.catalog_account_combo.findData("4100"))
    panel.save_catalog_preset()
    assert InvoiceService(conn).catalog_service.fetch_item(1).currency == "USD"
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
    panel.create_contract_royalty_term()
    panel.record_royalty_source_event()
    panel.generate_contract_royalty_calculations()

    assert warnings
    assert set(warnings) == {"Open a profile first."}

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

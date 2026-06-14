"""Royalties & Accounting UI panel for ledger-backed billing workflows."""

from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Callable, Sequence
from datetime import date, datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpacerItem,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from isrc_manager.code_registry import (
    BUILTIN_CATEGORY_CREDIT_NOTE_NUMBER,
    BUILTIN_CATEGORY_INVOICE_NUMBER,
    BUILTIN_CATEGORY_LEDGER_TRANSACTION_NUMBER,
    BUILTIN_CATEGORY_ROYALTY_STATEMENT_NUMBER,
    CodeRegistryService,
)
from isrc_manager.external_launch import open_external_path
from isrc_manager.file_storage import STORAGE_MODE_DATABASE, STORAGE_MODE_MANAGED_FILE
from isrc_manager.parties import PartyRecord, PartyService
from isrc_manager.services.settings_reads import OwnerPartySettings, SettingsReadService
from isrc_manager.ui_common import _configure_standard_form_layout, _create_standard_section

from .credit_note_service import CreditNoteService
from .currencies import ISO_4217_CURRENCY_CODES, currency_for_country
from .invoice_service import InvoiceCatalogCategoryService, InvoiceCatalogService, InvoiceService
from .ledger_service import ACCOUNT_TYPES, NORMAL_BALANCES, AccountingAccountService
from .models import (
    DEFAULT_CURRENCY,
    VAT_TREATMENTS,
    AccountingAccountPayload,
    ArtistPayoutPayload,
    CreditNoteLineAllocationPayload,
    CreditNotePayload,
    InvoiceCatalogCategoryPayload,
    InvoiceCatalogItemPayload,
    InvoiceDraftPayload,
    InvoiceLinePayload,
    InvoicePaymentPayload,
    Quantity,
    RoyaltyCalculationLinePayload,
    RoyaltyCalculationPayload,
)
from .money import format_money, format_quantity, parse_money_minor, parse_quantity
from .payment_service import InvoicePaymentService
from .report_service import InvoiceAccountingReportService
from .royalty_import import RoyaltySourceImportService
from .royalty_import_dialog import RoyaltySourceImportDialog
from .royalty_integration import (
    ContractRoyaltyTermPayload,
    RoyaltyIntegrationContext,
    RoyaltyIntegrationService,
    RoyaltySourceEventPayload,
    RoyaltyTermScopePayload,
)
from .royalty_service import RoyaltyAccountingService
from .template_service import InvoiceTemplateService
from .travel_distance import TravelDistanceService


def _clean_text(value: object | None) -> str | None:
    text = str(value or "").strip()
    return text or None


def _configure_workspace_table(table: QTableWidget, *, minimum_height: int = 150) -> None:
    table.setAlternatingRowColors(True)
    table.setMinimumHeight(int(minimum_height))
    table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    table.setWordWrap(False)
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    table.setHorizontalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
    table.setVerticalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setStretchLastSection(False)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)


def _configure_detail_view(view: QTextEdit | QTextBrowser) -> None:
    view.setReadOnly(True)
    view.setProperty("role", "workspaceCanvas")
    view.setMinimumWidth(300)


def _display_date(value: object | None) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text[:19], fmt).strftime("%d-%b-%Y")
        except ValueError:
            continue
    return text


def _status_label(value: object | None) -> str:
    return str(value or "").strip().replace("_", " ").title() or "Unknown"


def _set_table_rows(
    table: QTableWidget,
    headers: tuple[str, ...],
    rows: Sequence[Sequence[object]],
    *,
    empty_message: str,
) -> None:
    table.setColumnCount(len(headers))
    table.setHorizontalHeaderLabels(headers)
    display_rows = rows or [(empty_message,) + ("",) * (len(headers) - 1)]
    table.setRowCount(len(display_rows))
    for row_index, row in enumerate(display_rows):
        values = tuple(row) + ("",) * max(0, len(headers) - len(row))
        for col_index, value in enumerate(values[: len(headers)]):
            item = QTableWidgetItem(str(value or ""))
            if not rows:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            table.setItem(row_index, col_index, item)
    table.resizeColumnsToContents()


def _add_kpi_card(
    layout: QGridLayout,
    *,
    row: int,
    column: int,
    title: str,
    value: str,
    detail: str,
    parent: QWidget,
) -> QLabel:
    card = QLabel(f"{title}\n{value}\n{detail}", parent)
    card.setProperty("role", "workspaceCard")
    card.setWordWrap(True)
    card.setMinimumHeight(76)
    card.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    layout.addWidget(card, row, column)
    return card


def _scrollable_page(owner: QWidget) -> tuple[QScrollArea, QWidget, QVBoxLayout]:
    scroll = QScrollArea(owner)
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setProperty("role", "workspaceCanvas")
    content = QWidget(scroll)
    content.setProperty("role", "workspaceCanvas")
    layout = QVBoxLayout(content)
    layout.setContentsMargins(12, 12, 12, 12)
    layout.setSpacing(12)
    scroll.setWidget(content)
    return scroll, content, layout


def _add_action_button(
    parent: QWidget,
    layout: QHBoxLayout,
    label: str,
    slot: Callable[..., object],
) -> QPushButton:
    button = QPushButton(label, parent)
    button.clicked.connect(slot)
    layout.addWidget(button)
    return button


class InvoiceWorkspacePanel(QWidget):
    """Operational panel for invoices, settlement, templates, and reports."""

    def __init__(
        self,
        *,
        conn_provider: Callable[[], sqlite3.Connection | None],
        data_root: str | Path | None = None,
        open_contract_manager: Callable[[int | None], object] | None = None,
        open_work_manager: Callable[[int | None], object] | None = None,
        open_track_editor: Callable[[int | None], object] | None = None,
        open_rights_matrix: Callable[[int | None], object] | None = None,
        open_party_manager: Callable[[int | None], object] | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._conn_provider = conn_provider
        self._data_root = Path(data_root).resolve() if data_root is not None else None
        self._open_contract_manager = open_contract_manager
        self._open_work_manager = open_work_manager
        self._open_track_editor = open_track_editor
        self._open_rights_matrix = open_rights_matrix
        self._open_party_manager = open_party_manager
        self.setObjectName("invoiceWorkspacePanel")
        self.setProperty("role", "workspaceCanvas")
        self.tabs = QTabWidget(self)
        self.invoice_workflow_tabs = QTabWidget(self)
        self.dashboard_work_queue_table = QTableWidget(0, 8, self)
        self.dashboard_calculation_table = QTableWidget(0, 8, self)
        self.dashboard_invoice_status_table = QTableWidget(0, 4, self)
        self.dashboard_accounting_control_table = QTableWidget(0, 4, self)
        self.contracts_table = QTableWidget(0, 11, self)
        self.rights_titles_table = QTableWidget(0, 10, self)
        self.imports_table = QTableWidget(0, 12, self)
        self.statement_table = QTableWidget(0, 12, self)
        self.dispute_table = QTableWidget(0, 8, self)
        self.invoice_table = QTableWidget(0, 8, self)
        self.invoice_final_storage_combo = QComboBox(self)
        self.invoice_final_status_label = QLabel(self)
        self.royalty_payables_table = QTableWidget(0, 9, self)
        self.einvoice_table = QTableWidget(0, 7, self)
        self.invoice_line_table = QTableWidget(0, 7, self)
        self.draft_line_table = QTableWidget(0, 7, self)
        self.catalog_table = QTableWidget(0, 9, self)
        self.catalog_item_combo = QComboBox(self)
        self.royalty_table = QTableWidget(0, 7, self)
        self.journal_table = QTableWidget(0, 10, self)
        self.journal_line_table = QTableWidget(0, 9, self)
        self.ledger_mapping_table = QTableWidget(0, 8, self)
        self.vat_summary_table = QTableWidget(0, 9, self)
        self.period_close_table = QTableWidget(0, 6, self)
        self.accounting_export_table = QTableWidget(0, 7, self)
        self.payables_table = QTableWidget(0, 10, self)
        self.receivables_table = QTableWidget(0, 9, self)
        self.bank_reconciliation_table = QTableWidget(0, 8, self)
        self.sepa_batch_table = QTableWidget(0, 8, self)
        self.report_catalog_table = QTableWidget(0, 5, self)
        self.royalty_workflow_tabs = QTabWidget(self)
        self.royalty_contract_combo = QComboBox(self)
        self.royalty_context_output = QTextEdit(self)
        self.royalty_term_table = QTableWidget(0, 7, self)
        self.royalty_source_event_table = QTableWidget(0, 9, self)
        self.party_combo = QComboBox(self)
        self.royalty_party_combo = QComboBox(self)
        self.royalty_term_party_combo = QComboBox(self)
        self.royalty_term_scope_type_combo = QComboBox(self)
        self.royalty_term_scope_id_combo = QComboBox(self)
        self.royalty_event_work_combo = QComboBox(self)
        self.royalty_event_track_combo = QComboBox(self)
        self.royalty_event_release_combo = QComboBox(self)
        self.description_field = QLineEdit(self)
        self.quantity_field = QLineEdit(self)
        self.unit_price_field = QLineEdit(self)
        self.vat_rate_field = QLineEdit(self)
        self.due_date_field = QLineEdit(self)
        self.draft_totals_label = QLabel(self)
        self.catalog_name_field = QLineEdit(self)
        self.catalog_description_field = QLineEdit(self)
        self.catalog_quantity_field = QLineEdit(self)
        self.catalog_unit_price_field = QLineEdit(self)
        self.catalog_currency_combo = QComboBox(self)
        self.catalog_vat_rate_field = QLineEdit(self)
        self.catalog_vat_country_field = QLineEdit(self)
        self.catalog_category_combo = QComboBox(self)
        self.catalog_account_combo = QComboBox(self)
        self.catalog_active_check = QCheckBox("Active", self)
        self.catalog_category_table = QTableWidget(0, 5, self)
        self.catalog_category_name_field = QLineEdit(self)
        self.catalog_category_active_check = QCheckBox("Active", self)
        self.account_admin_table = QTableWidget(0, 7, self)
        self.account_code_field = QLineEdit(self)
        self.account_name_field = QLineEdit(self)
        self.account_type_combo = QComboBox(self)
        self.account_normal_balance_combo = QComboBox(self)
        self.account_active_check = QCheckBox("Active", self)
        self.travel_origin_field = QLineEdit(self)
        self.travel_destination_field = QLineEdit(self)
        self.travel_km_field = QLineEdit(self)
        self.travel_rate_field = QLineEdit(self)
        self.travel_description_field = QLineEdit(self)
        self.travel_round_trip_check = QCheckBox("Round trip", self)
        self.travel_status_label = QLabel(self)
        self.credit_subtotal_field = QLineEdit(self)
        self.credit_vat_field = QLineEdit(self)
        self.credit_reason_field = QLineEdit(self)
        self.royalty_description_field = QLineEdit(self)
        self.royalty_amount_field = QLineEdit(self)
        self.royalty_term_rate_field = QLineEdit(self)
        self.royalty_term_right_type_field = QLineEdit(self)
        self.royalty_term_territory_field = QLineEdit(self)
        self.royalty_term_effective_start_field = QLineEdit(self)
        self.royalty_term_effective_end_field = QLineEdit(self)
        self.royalty_term_notes_field = QLineEdit(self)
        self.royalty_term_basis_combo = QComboBox(self)
        self.royalty_source_description_field = QLineEdit(self)
        self.royalty_source_type_field = QLineEdit(self)
        self.royalty_source_id_field = QLineEdit(self)
        self.royalty_source_gross_field = QLineEdit(self)
        self.royalty_source_net_field = QLineEdit(self)
        self.royalty_source_event_date_field = QLineEdit(self)
        self.royalty_source_period_start_field = QLineEdit(self)
        self.royalty_source_period_end_field = QLineEdit(self)
        self.royalty_source_metadata_field = QLineEdit(self)
        self.royalty_period_start_field = QLineEdit(self)
        self.royalty_period_end_field = QLineEdit(self)
        self.royalty_payout_amount_field = QLineEdit(self)
        self.royalty_payment_reference_field = QLineEdit(self)
        self.manual_footer_field = QLineEdit(self)
        self.report_output = QTextEdit(self)
        self.dashboard_detail_output = QTextEdit(self)
        self.company_owner_output = QTextEdit(self)
        self.users_roles_table = QTableWidget(self)
        self.users_roles_detail_output = QTextEdit(self)
        self.vat_treatment_table = QTableWidget(self)
        self.vat_activity_table = QTableWidget(self)
        self.vat_tax_detail_output = QTextEdit(self)
        self.numbering_sequence_table = QTableWidget(self)
        self.numbering_usage_table = QTableWidget(self)
        self.invoice_numbering_detail_output = QTextEdit(self)
        self.integration_file_path_field = QLineEdit(self)
        self.integration_profile_table = QTableWidget(self)
        self.integration_mapping_table = QTableWidget(self)
        self.integration_preview_table = QTableWidget(self)
        self.integrations_detail_output = QTextEdit(self)
        self.workflow_policy_table = QTableWidget(self)
        self.workflow_queue_table = QTableWidget(self)
        self.workflow_command_table = QTableWidget(self)
        self.workflow_detail_output = QTextEdit(self)
        self.contract_detail_output = QTextEdit(self)
        self.rights_detail_output = QTextEdit(self)
        self.import_detail_output = QTextEdit(self)
        self.royalty_calculation_detail_output = QTextEdit(self)
        self.statement_detail_output = QTextEdit(self)
        self.invoice_detail_output = QTextEdit(self)
        self.accounting_detail_output = QTextEdit(self)
        self.payment_detail_output = QTextEdit(self)
        self.settings_detail_output = QTextEdit(self)
        self._draft_invoice_lines: list[InvoiceLinePayload] = []
        self._build_ui()
        self.refresh_all()

    def focus_tab(self, tab_key: str = "invoices") -> None:
        mapping = {
            "dashboard": 0,
            "home": 0,
            "royalty": 0,
            "royalties": 0,
            "contracts": 0,
            "imports": 0,
            "statements": 0,
            "invoices": 1,
            "invoice": 1,
            "accounting": 2,
            "ledger": 2,
            "payments": 3,
            "reports": 4,
            "catalog": 5,
            "items": 5,
            "settings": 5,
        }
        self.tabs.setCurrentIndex(mapping.get(str(tab_key or "").strip().lower(), 1))

    def _focus_settings_page(self, tab_title: str) -> None:
        self.focus_tab("settings")
        tabs = getattr(self, "settings_tabs", None)
        if not isinstance(tabs, QTabWidget):
            return
        for index in range(tabs.count()):
            if tabs.tabText(index) == tab_title:
                tabs.setCurrentIndex(index)
                return

    def open_catalog_category_admin(self) -> None:
        self._focus_settings_page("Preset Categories")

    def open_ledger_account_admin(self) -> None:
        self._focus_settings_page("Ledger Accounts")

    def refresh_all(self) -> None:
        if self._conn() is None:
            return
        self._refresh_parties()
        self._refresh_company_settings()
        self._refresh_users_roles_settings()
        self._refresh_vat_tax_settings()
        self._refresh_invoice_numbering_settings()
        self._refresh_integrations_settings()
        self._refresh_workflows_settings()
        self._refresh_invoice_catalog()
        self._refresh_catalog_category_settings()
        self._refresh_account_admin_settings()
        self._refresh_royalty_parties()
        self._refresh_royalty_contracts()
        self.refresh_dashboard()
        self.refresh_contracts()
        self.refresh_rights_titles()
        self.refresh_imports()
        self.refresh_statements()
        self.refresh_invoices()
        self.refresh_invoice_lines()
        self.refresh_accounting()
        self.refresh_payments()
        self.refresh_royalty_context()
        self.refresh_royalty_terms()
        self.refresh_royalty_source_events()
        self.refresh_royalties()
        self.refresh_reports()

    def refresh(self) -> None:
        self.refresh_all()

    def capture_layout_state(self) -> dict[str, object]:
        tab_index = self.tabs.currentIndex()
        return {
            "tab_schema": "royalties_accounting_no_home_v1",
            "tab": tab_index,
            "tab_key": self.tabs.tabText(tab_index).strip().lower(),
            "invoice_tab": self.invoice_workflow_tabs.currentIndex(),
            "royalty_tab": self.royalty_workflow_tabs.currentIndex(),
            "invoice_id": self._selected_invoice_id(),
            "royalty_calculation_id": self._selected_royalty_calculation_id(),
            "royalty_contract_id": self._selected_royalty_contract_id(),
        }

    def restore_layout_state(self, state: dict[str, object] | None) -> None:
        if not isinstance(state, dict):
            return
        tab = state.get("tab")
        tab_key = state.get("tab_key")
        tab_schema = state.get("tab_schema")
        invoice_tab = state.get("invoice_tab")
        royalty_tab = state.get("royalty_tab")
        contract_id = state.get("royalty_contract_id")
        invoice_id = state.get("invoice_id")
        calculation_id = state.get("royalty_calculation_id")
        if isinstance(tab_key, str) and tab_key.strip():
            self.focus_tab(tab_key)
        elif isinstance(tab, int):
            if tab_schema != "royalties_accounting_no_home_v1":
                tab = max(0, tab - 1)
            if 0 <= tab < self.tabs.count():
                self.tabs.setCurrentIndex(tab)
        if isinstance(invoice_tab, int) and 0 <= invoice_tab < self.invoice_workflow_tabs.count():
            self.invoice_workflow_tabs.setCurrentIndex(invoice_tab)
        if isinstance(royalty_tab, int) and 0 <= royalty_tab < self.royalty_workflow_tabs.count():
            self.royalty_workflow_tabs.setCurrentIndex(royalty_tab)
        if contract_id is not None:
            index = self.royalty_contract_combo.findData(int(str(contract_id)))
            if index >= 0:
                self.royalty_contract_combo.setCurrentIndex(index)
        if invoice_id is not None:
            self._select_invoice_id(int(str(invoice_id)))
        if calculation_id is not None:
            self._select_royalty_calculation_id(int(str(calculation_id)))

    def refresh_dashboard(self) -> None:
        conn = self._conn()
        if conn is None:
            return
        reports = InvoiceAccountingReportService(conn)
        outstanding = reports.outstanding_invoices()
        vat = reports.vat_summary_report()
        royalties_due = self._scalar("""
            SELECT COALESCE(SUM(c.net_payable_minor - COALESCE(p.paid_minor, 0)), 0)
            FROM RoyaltyCalculations c
            LEFT JOIN (
                SELECT royalty_calculation_id, SUM(amount_minor) AS paid_minor
                FROM ArtistPayouts
                GROUP BY royalty_calculation_id
            ) p ON p.royalty_calculation_id=c.id
            WHERE c.status IN ('approved', 'posted', 'statement_generated', 'paid')
            """)
        awaiting_statements = self._scalar(
            "SELECT COUNT(*) FROM RoyaltyCalculations WHERE status IN ('approved', 'posted')"
        )
        open_invoices = len(outstanding)
        overdue = sum(1 for row in outstanding if row.due_status == "overdue")
        unmatched_imports = self._scalar("""
            SELECT COUNT(*)
            FROM RoyaltySourceEvents
            WHERE contract_id IS NULL AND work_id IS NULL AND track_id IS NULL AND release_id IS NULL
            """)
        payments_waiting = self._scalar("""
            SELECT COUNT(*)
            FROM RoyaltyCalculations c
            LEFT JOIN (
                SELECT royalty_calculation_id, SUM(amount_minor) AS paid_minor
                FROM ArtistPayouts
                GROUP BY royalty_calculation_id
            ) p ON p.royalty_calculation_id=c.id
            WHERE c.status IN ('posted', 'statement_generated')
              AND (c.net_payable_minor - COALESCE(p.paid_minor, 0)) > 0
            """)
        vat_current = sum(int(row.vat_output_minor) - int(row.vat_input_minor) for row in vat)
        exceptions = int(unmatched_imports) + int(overdue)

        self._dashboard_kpis = {
            "royalties_due": format_money(int(royalties_due)),
            "statements": str(awaiting_statements),
            "open_invoices": str(open_invoices),
            "overdue": str(overdue),
            "imports": str(unmatched_imports),
            "payments": str(payments_waiting),
            "vat": format_money(int(vat_current)),
            "exceptions": str(exceptions),
        }
        self._refresh_dashboard_kpi_labels()
        self._refresh_dashboard_tables(outstanding)

    def refresh_contracts(self) -> None:
        conn = self._conn()
        if conn is None:
            return
        rows = conn.execute("""
            SELECT
                c.id,
                c.title,
                COALESCE(p.display_name, p.legal_name, ''),
                COALESCE(c.contract_type, ''),
                '',
                COALESCE(c.effective_date, c.start_date, ''),
                COALESCE(c.end_date, ''),
                COALESCE(c.status, ''),
                COUNT(DISTINCT t.id),
                COALESCE(MAX(t.updated_at), MAX(c.updated_at), ''),
                COALESCE(SUM(r.net_payable_minor - COALESCE(rp.paid_minor, 0)), 0)
            FROM Contracts c
            LEFT JOIN ContractParties cp ON cp.contract_id=c.id AND cp.is_primary=1
            LEFT JOIN Parties p ON p.id=cp.party_id
            LEFT JOIN ContractRoyaltyTerms t ON t.contract_id=c.id
            LEFT JOIN RoyaltyCalculations r ON r.contract_id=c.id
            LEFT JOIN (
                SELECT royalty_calculation_id, SUM(amount_minor) AS paid_minor
                FROM ArtistPayouts
                GROUP BY royalty_calculation_id
            ) rp ON rp.royalty_calculation_id=r.id
            GROUP BY c.id
            ORDER BY c.updated_at DESC, c.id DESC
            """).fetchall()
        table_rows = [
            (
                row[0],
                row[1],
                row[2],
                row[3],
                row[4],
                _display_date(row[5]),
                _display_date(row[6]),
                _status_label(row[7]),
                "Configured" if int(row[8] or 0) else "Missing",
                format_money(int(row[10] or 0)),
                _display_date(row[9]),
            )
            for row in rows
        ]
        _set_table_rows(
            self.contracts_table,
            (
                "Contract ID",
                "Contract name",
                "Party / Payee",
                "Type",
                "Territory",
                "Start date",
                "End date",
                "Status",
                "Statement cycle",
                "Unrecouped advance",
                "Last updated",
            ),
            table_rows,
            empty_message="No royalty contracts found.",
        )

    def refresh_rights_titles(self) -> None:
        conn = self._conn()
        if conn is None:
            return
        rows = conn.execute("""
            SELECT
                w.id,
                w.title,
                COALESCE(w.iswc, w.registration_number, printf('Work %d', w.id)),
                'Musical work',
                COALESCE(MAX(p.display_name), MAX(p.legal_name), MAX(wc.display_name), ''),
                COALESCE(MAX(c.title), ''),
                COALESCE(MAX(r.territory), ''),
                COALESCE(MAX(r.right_type), ''),
                CASE WHEN w.rights_verified THEN 'Verified' ELSE 'Needs review' END,
                COALESCE(MAX(t.rate_basis_points), 0),
                COALESCE(MAX(se.created_at), MAX(w.updated_at), ''),
                MAX(r.id)
            FROM Works w
            LEFT JOIN WorkContributors wc ON wc.work_id=w.id
            LEFT JOIN Parties p ON p.id=wc.party_id
            LEFT JOIN ContractWorkLinks cwl ON cwl.work_id=w.id
            LEFT JOIN Contracts c ON c.id=cwl.contract_id
            LEFT JOIN RightsRecords r ON r.work_id=w.id
            LEFT JOIN ContractRoyaltyTerms t ON t.contract_id=c.id
            LEFT JOIN RoyaltySourceEvents se ON se.work_id=w.id
            GROUP BY w.id
            ORDER BY w.updated_at DESC, w.id DESC
            """).fetchall()
        table_rows = [
            (
                row[1],
                row[2],
                row[3],
                row[4],
                row[5],
                row[6],
                row[7],
                row[8],
                f"{int(row[9] or 0) / 100:.2f}%" if int(row[9] or 0) else "Missing",
                _display_date(row[10]),
            )
            for row in rows
        ]
        _set_table_rows(
            self.rights_titles_table,
            (
                "Title / Product",
                "Identifier",
                "Type",
                "Owner / Payee",
                "Contract",
                "Territory",
                "Channel",
                "Status",
                "Royalty rule",
                "Last activity",
            ),
            table_rows,
            empty_message="No rights or title records found.",
        )
        for row_index, row in enumerate(rows):
            work_id = int(row[0])
            right_id = int(row[11]) if row[11] is not None else None
            for column in range(self.rights_titles_table.columnCount()):
                item = self.rights_titles_table.item(row_index, column)
                if item is None:
                    continue
                item.setData(Qt.ItemDataRole.UserRole, work_id)
                if right_id is not None:
                    item.setData(Qt.ItemDataRole.UserRole + 1, right_id)

    def refresh_imports(self) -> None:
        conn = self._conn()
        if conn is None:
            return
        rows = conn.execute("""
            SELECT
                COALESCE(source_type, 'manual/import'),
                COALESCE(source_id, printf('source-event-%d', id)),
                COALESCE(period_start, ''),
                COALESCE(period_end, ''),
                COUNT(*),
                SUM(CASE WHEN contract_id IS NOT NULL OR work_id IS NOT NULL OR track_id IS NOT NULL THEN 1 ELSE 0 END),
                SUM(CASE WHEN contract_id IS NULL AND work_id IS NULL AND track_id IS NULL THEN 1 ELSE 0 END),
                COALESCE(SUM(gross_amount_minor), 0),
                COALESCE(SUM(net_amount_minor), 0),
                MIN(created_at),
                MAX(created_at)
            FROM RoyaltySourceEvents
            GROUP BY source_type, source_id, period_start, period_end
            ORDER BY MAX(created_at) DESC, source_type
            LIMIT 200
            """).fetchall()
        table_rows = [
            (
                f"{row[0]}:{row[1]}",
                row[0],
                row[1],
                f"{_display_date(row[2])} - {_display_date(row[3])}".strip(" -"),
                "current user",
                _display_date(row[10]),
                row[4],
                row[5],
                row[6],
                format_money(int(row[7] or 0)),
                "Has exceptions" if int(row[6] or 0) else "Imported",
                "Review / Reverse",
            )
            for row in rows
        ]
        _set_table_rows(
            self.imports_table,
            (
                "Import ID",
                "Source",
                "File name",
                "Period",
                "Imported by",
                "Imported at",
                "Rows",
                "Matched rows",
                "Unmatched rows",
                "Total revenue",
                "Status",
                "Actions",
            ),
            table_rows,
            empty_message="No sales or usage imports found.",
        )

    def refresh_statements(self) -> None:
        conn = self._conn()
        if conn is None:
            return
        rows = conn.execute("""
            SELECT
                s.statement_number,
                COALESCE(p.display_name, p.legal_name, printf('Party %d', c.party_id)),
                COALESCE(ct.title, ''),
                c.period_start,
                c.period_end,
                c.net_payable_minor,
                c.currency,
                s.status,
                s.issue_date,
                COALESCE(paid.paid_minor, 0),
                c.id,
                s.id
            FROM RoyaltyStatements s
            INNER JOIN RoyaltyCalculations c ON c.id=s.calculation_id
            LEFT JOIN Parties p ON p.id=c.party_id
            LEFT JOIN Contracts ct ON ct.id=c.contract_id
            LEFT JOIN (
                SELECT royalty_calculation_id, SUM(amount_minor) AS paid_minor
                FROM ArtistPayouts
                GROUP BY royalty_calculation_id
            ) paid ON paid.royalty_calculation_id=c.id
            ORDER BY s.created_at DESC, s.id DESC
            """).fetchall()
        table_rows = [
            (
                row[0],
                row[1],
                row[2],
                f"{_display_date(row[3])} - {_display_date(row[4])}".strip(" -"),
                format_money(int(row[5] or 0), currency=str(row[6] or "EUR")),
                format_money(0, currency=str(row[6] or "EUR")),
                format_money(0, currency=str(row[6] or "EUR")),
                format_money(int(row[5] or 0), currency=str(row[6] or "EUR")),
                row[6],
                _status_label(row[7]),
                _display_date(row[8]),
                "Paid" if int(row[9] or 0) >= int(row[5] or 0) else "Open",
            )
            for row in rows
        ]
        _set_table_rows(
            self.statement_table,
            (
                "Statement number",
                "Payee",
                "Contract",
                "Period",
                "Gross royalty",
                "Deductions",
                "Advance recouped",
                "Net payable",
                "Currency",
                "Status",
                "Sent at",
                "Payment status",
            ),
            table_rows,
            empty_message="No royalty statements generated yet.",
        )
        for row_index, row in enumerate(rows):
            item = self.statement_table.item(row_index, 0)
            if item is None:
                continue
            item.setData(Qt.ItemDataRole.UserRole, int(row[11]))
            item.setData(Qt.ItemDataRole.UserRole + 1, int(row[10]))
        _set_table_rows(
            self.dispute_table,
            (
                "Dispute ID",
                "Statement",
                "Payee",
                "Reason",
                "Amount",
                "Priority",
                "Status",
                "Action",
            ),
            [],
            empty_message="No statement disputes recorded.",
        )

    def refresh_invoices(self) -> None:
        conn = self._conn()
        if conn is None:
            return
        reports = InvoiceAccountingReportService(conn)
        rows = conn.execute("""
            SELECT
                id,
                COALESCE(invoice_number, draft_display_id, printf('Invoice %d', id)),
                party_id,
                invoice_type,
                document_status,
                issue_date,
                due_date,
                currency,
                total_minor
            FROM Invoices
            ORDER BY created_at DESC, id DESC
            """).fetchall()
        self.invoice_table.setRowCount(len(rows))
        einvoice_rows = []
        for row_index, row in enumerate(rows):
            settlement = reports.invoice_settlement(int(row[0]))
            values = (
                str(row[0]),
                str(row[1] or ""),
                str(row[2] or ""),
                str(row[4] or ""),
                settlement.payment_status,
                settlement.due_status,
                format_money(int(row[8] or 0), currency=str(row[7] or "EUR")),
                format_money(settlement.receivable_balance_minor, currency=str(row[7] or "EUR")),
            )
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col_index == 0:
                    item.setData(Qt.ItemDataRole.UserRole, int(row[0]))
                self.invoice_table.setItem(row_index, col_index, item)
            einvoice_rows.append(
                (
                    str(row[1] or row[0]),
                    _status_label(row[3]),
                    f"Party {row[2]}",
                    "HTML",
                    _status_label(row[4]),
                    "Ready after template validation",
                    "Preview / Export",
                )
            )
        self.invoice_table.resizeColumnsToContents()
        _set_table_rows(
            self.einvoice_table,
            ("Invoice", "Type", "Party", "Format", "Status", "Validation", "Action"),
            einvoice_rows,
            empty_message="No e-invoice artifacts have been generated.",
        )
        if not rows:
            self.invoice_final_status_label.setText(
                "No final invoices yet. Create and mark invoices final in Template Workspace."
            )

    def refresh_invoice_lines(self) -> None:
        conn = self._conn()
        invoice_id = self._selected_invoice_id()
        if conn is None or invoice_id is None:
            self.invoice_line_table.setRowCount(0)
            return
        rows = CreditNoteService(conn).creditable_invoice_lines(invoice_id)
        self.invoice_line_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = (
                str(row.id),
                row.description,
                format_money(row.net_amount_minor, currency=row.currency),
                format_money(row.vat_amount_minor, currency=row.currency),
                format_money(row.gross_amount_minor, currency=row.currency),
                format_money(row.remaining_subtotal_minor, currency=row.currency),
                format_money(row.remaining_vat_minor, currency=row.currency),
            )
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col_index == 0:
                    item.setData(Qt.ItemDataRole.UserRole, int(row.id))
                self.invoice_line_table.setItem(row_index, col_index, item)
        self.invoice_line_table.resizeColumnsToContents()

    def refresh_accounting(self) -> None:
        conn = self._conn()
        if conn is None:
            return
        journal_rows = conn.execute("""
            SELECT
                t.id,
                t.transaction_type,
                COALESCE(t.memo, ''),
                COALESCE(t.posted_at, ''),
                COALESCE(MIN(e.currency), 'EUR'),
                COALESCE(SUM(e.debit_minor), 0),
                COALESCE(SUM(e.credit_minor), 0),
                'posted',
                COUNT(DISTINCT l.source_id),
                t.created_by
            FROM AccountingTransactions t
            LEFT JOIN AccountingEntries e ON e.transaction_id=t.id
            LEFT JOIN AccountingTransactionLinks l ON l.transaction_id=t.id
            GROUP BY t.id
            ORDER BY t.posted_at DESC, t.id DESC
            LIMIT 200
            """).fetchall()
        _set_table_rows(
            self.journal_table,
            (
                "Journal entry ID",
                "Source type",
                "Source reference",
                "Posting date",
                "Accounting period",
                "Description",
                "Debit total",
                "Credit total",
                "Status",
                "Export status",
            ),
            [
                (
                    row[0],
                    _status_label(row[1]),
                    f"{int(row[8] or 0)} linked source(s)",
                    _display_date(row[3]),
                    str(row[3] or "")[:7],
                    row[2],
                    format_money(int(row[5] or 0), currency=str(row[4] or "EUR")),
                    format_money(int(row[6] or 0), currency=str(row[4] or "EUR")),
                    _status_label(row[7]),
                    "Not exported",
                )
                for row in journal_rows
            ],
            empty_message="No ledger-backed journal entries posted yet.",
        )
        account_rows = conn.execute("""
            SELECT code, name, account_type, normal_balance, active, updated_at
            FROM AccountingAccounts
            ORDER BY code
            """).fetchall()
        _set_table_rows(
            self.ledger_mapping_table,
            (
                "Mapping type",
                "Source category",
                "Royalty/invoice type",
                "Existing ledger account",
                "VAT code",
                "Cost centre rule",
                "Active",
                "Last updated",
            ),
            [
                (
                    _status_label(row[2]),
                    "System account",
                    "Invoices / royalties",
                    f"{row[0]} - {row[1]}",
                    "Derived from VAT treatment",
                    "Contract / party",
                    "Active" if row[4] else "Inactive",
                    _display_date(row[5]),
                )
                for row in account_rows
            ],
            empty_message="No accounting accounts are available.",
        )
        vat_rows = InvoiceAccountingReportService(conn).vat_summary_report()
        _set_table_rows(
            self.vat_summary_table,
            (
                "Period",
                "VAT payable",
                "VAT receivable",
                "Reverse charge",
                "Exempt",
                "Intra-EU",
                "Domestic VAT",
                "Unposted items",
                "Exceptions",
            ),
            [
                (
                    "All open periods",
                    format_money(row.vat_output_minor, currency=row.currency),
                    format_money(row.vat_input_minor, currency=row.currency),
                    "Yes" if row.vat_treatment == "reverse_charge" else "",
                    "Yes" if row.vat_treatment == "exempt" else "",
                    "",
                    f"{row.vat_rate_basis_points or 0} bp",
                    "0",
                    "",
                )
                for row in vat_rows
            ],
            empty_message="No VAT ledger entries found.",
        )
        self._refresh_period_close_and_exports()

    def refresh_payments(self) -> None:
        conn = self._conn()
        if conn is None:
            return
        payables = conn.execute("""
            SELECT
                COALESCE(p.display_name, p.legal_name, printf('Party %d', c.party_id)),
                COALESCE(s.statement_number, ''),
                c.id,
                c.period_end,
                c.net_payable_minor - COALESCE(paid.paid_minor, 0),
                c.currency,
                c.status
            FROM RoyaltyCalculations c
            LEFT JOIN Parties p ON p.id=c.party_id
            LEFT JOIN RoyaltyStatements s ON s.calculation_id=c.id
            LEFT JOIN (
                SELECT royalty_calculation_id, SUM(amount_minor) AS paid_minor
                FROM ArtistPayouts
                GROUP BY royalty_calculation_id
            ) paid ON paid.royalty_calculation_id=c.id
            WHERE (c.net_payable_minor - COALESCE(paid.paid_minor, 0)) > 0
            ORDER BY c.period_end DESC, c.id DESC
            """).fetchall()
        payable_rows = [
            (
                row[0],
                row[1],
                f"Royalty calculation {row[2]}",
                _display_date(row[3]),
                format_money(int(row[4] or 0), currency=str(row[5] or "EUR")),
                row[5],
                "Not held",
                _status_label(row[6]),
                "Awaiting release",
                "Approve / Pay / Hold",
            )
            for row in payables
        ]
        _set_table_rows(
            self.payables_table,
            (
                "Payee",
                "Statement",
                "Invoice",
                "Due date",
                "Amount",
                "Currency",
                "Hold status",
                "Approval status",
                "Payment status",
                "Actions",
            ),
            payable_rows,
            empty_message="No royalty payables awaiting payment.",
        )
        _set_table_rows(
            self.royalty_payables_table,
            (
                "Payee",
                "Statement",
                "Invoice",
                "Due date",
                "Amount",
                "Currency",
                "Approval",
                "Payment",
                "Action",
            ),
            [
                (
                    row[0],
                    row[1],
                    row[2],
                    row[3],
                    row[4],
                    row[5],
                    row[7],
                    row[8],
                    row[9],
                )
                for row in payable_rows
            ],
            empty_message="No royalty payable invoices are awaiting creation.",
        )
        receivables = InvoiceAccountingReportService(conn).outstanding_invoices()
        _set_table_rows(
            self.receivables_table,
            (
                "Customer",
                "Invoice",
                "Due date",
                "Amount",
                "Currency",
                "Days overdue",
                "Payment status",
                "Actions",
                "Trace",
            ),
            [
                (
                    f"Party {row.party_id}",
                    row.invoice_number or row.invoice_id,
                    _display_date(row.due_date),
                    format_money(row.outstanding_minor, currency=row.currency),
                    row.currency,
                    "Overdue" if row.due_status == "overdue" else "",
                    _status_label(row.payment_status),
                    "Record / Match payment",
                    f"Invoice {row.invoice_id}",
                )
                for row in receivables
            ],
            empty_message="No receivables are outstanding.",
        )
        _set_table_rows(
            self.bank_reconciliation_table,
            (
                "Bank row",
                "Date",
                "Reference",
                "Amount",
                "Suggested match",
                "Confidence",
                "Status",
                "Action",
            ),
            [],
            empty_message="No bank statement import is loaded.",
        )
        _set_table_rows(
            self.sepa_batch_table,
            (
                "Batch ID",
                "Created date",
                "Created by",
                "Payment date",
                "Payments",
                "Total amount",
                "Status",
                "Approval",
            ),
            [],
            empty_message="No SEPA payment batches created.",
        )

    def refresh_reports(self) -> None:
        conn = self._conn()
        if conn is None:
            return
        reports = InvoiceAccountingReportService(conn)
        outstanding = reports.outstanding_invoices()
        party_balances = reports.party_balance_report()
        vat = reports.vat_summary_report()
        lines = ["Outstanding invoices"]
        if not outstanding:
            lines.append("No outstanding invoices.")
        for row in outstanding:
            lines.append(
                f"{row.invoice_number or row.invoice_id}: "
                f"{format_money(row.outstanding_minor, currency=row.currency)} "
                f"({row.payment_status}, {row.due_status})"
            )
        lines.append("")
        lines.append("Party balances")
        if not party_balances:
            lines.append("No party ledger balances.")
        for row in party_balances:
            lines.append(
                f"Party {row.party_id}: {format_money(row.balance_minor, currency=row.currency)}"
            )
        lines.append("")
        lines.append("VAT summary")
        if not vat:
            lines.append("No VAT ledger entries.")
        for row in vat:
            lines.append(
                f"{row.vat_treatment or 'none'} {row.vat_rate_basis_points or 0}bp: "
                f"output {format_money(row.vat_output_minor, currency=row.currency)}, "
                f"input {format_money(row.vat_input_minor, currency=row.currency)}"
            )
        self.report_output.setPlainText("\n".join(lines))
        self._refresh_report_catalog()

    def refresh_royalty_context(self) -> None:
        conn = self._conn()
        contract_id = self._selected_royalty_contract_id()
        if conn is None or contract_id is None:
            self.royalty_context_output.setPlainText(
                "Select an active contract to inspect royalty readiness."
            )
            self._populate_context_entity_choices(None)
            return
        try:
            context = RoyaltyIntegrationService(conn).build_context(
                contract_id,
                period_start=_clean_text(self.royalty_period_start_field.text()),
                period_end=_clean_text(self.royalty_period_end_field.text()),
            )
        except Exception as exc:
            self.royalty_context_output.setPlainText(str(exc))
            self._populate_context_entity_choices(None)
            return
        lines = [
            f"Contract #{context.contract_id}: {context.contract_title}",
            f"Status: {context.contract_status}",
            f"Ready for royalty accounting: {'yes' if context.is_ready else 'no'}",
            "",
            f"Linked works: {self._format_named_ids('Works', context.work_ids)}",
            "Linked recordings: "
            f"{self._format_named_ids('Tracks', context.track_ids)} "
            "(from linked musical works only)",
            f"Linked releases: {self._format_named_ids('Releases', context.release_ids)}",
            f"Rights records: {self._format_named_ids('RightsRecords', context.right_ids)}",
            f"Ownership interests: {len(context.ownership_interest_ids)}",
            f"Royalty terms: {len(context.terms)}",
            f"Source events in period: {len(context.source_events)}",
        ]
        if context.issues:
            lines.extend(("", "Readiness issues"))
            for issue in context.issues:
                lines.append(f"- {issue.severity.upper()} {issue.code}: {issue.message}")
        else:
            lines.extend(("", "No readiness issues detected."))
        self.royalty_context_output.setPlainText("\n".join(lines))
        self._populate_context_entity_choices(context)

    def refresh_royalty_terms(self) -> None:
        conn = self._conn()
        contract_id = self._selected_royalty_contract_id()
        if conn is None or contract_id is None:
            self.royalty_term_table.setRowCount(0)
            return
        service = RoyaltyIntegrationService(conn)
        rows = service.list_contract_royalty_terms(contract_id, active_only=False)
        self.royalty_term_table.setRowCount(len(rows))
        for row_index, term in enumerate(rows):
            scopes = service.list_term_scopes(term.id)
            scope_text = (
                ", ".join(f"{scope.scope_type}:{scope.scope_id}" for scope in scopes)
                or "whole contract"
            )
            values = (
                str(term.id),
                self._party_label(term.party_id),
                f"{term.rate_basis_points / 100:.2f}%",
                term.royalty_basis,
                scope_text,
                term.right_type or "",
                "active" if term.active else "inactive",
            )
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col_index == 0:
                    item.setData(Qt.ItemDataRole.UserRole, int(term.id))
                self.royalty_term_table.setItem(row_index, col_index, item)
        self.royalty_term_table.resizeColumnsToContents()

    def refresh_royalty_source_events(self) -> None:
        conn = self._conn()
        contract_id = self._selected_royalty_contract_id()
        if conn is None or contract_id is None:
            self.royalty_source_event_table.setRowCount(0)
            return
        service = RoyaltyIntegrationService(conn)
        try:
            context = service.build_context(
                contract_id,
                period_start=_clean_text(self.royalty_period_start_field.text()),
                period_end=_clean_text(self.royalty_period_end_field.text()),
            )
        except Exception:
            self.royalty_source_event_table.setRowCount(0)
            return
        self.royalty_source_event_table.setRowCount(len(context.source_events))
        for row_index, event in enumerate(context.source_events):
            values = (
                str(event.id),
                event.description,
                self._optional_id_label("Contracts", event.contract_id),
                self._optional_id_label("Works", event.work_id),
                self._optional_id_label("Tracks", event.track_id),
                self._optional_id_label("Releases", event.release_id),
                f"{event.period_start or ''} - {event.period_end or ''}".strip(" -"),
                format_money(event.net_amount_minor, currency=event.currency),
                format_money(event.gross_amount_minor, currency=event.currency),
            )
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col_index == 0:
                    item.setData(Qt.ItemDataRole.UserRole, int(event.id))
                self.royalty_source_event_table.setItem(row_index, col_index, item)
        self.royalty_source_event_table.resizeColumnsToContents()

    def refresh_royalties(self) -> None:
        conn = self._conn()
        if conn is None:
            return
        service = RoyaltyAccountingService(conn)
        rows = conn.execute("""
            SELECT
                rc.id,
                rc.party_id,
                rc.status,
                rc.currency,
                rc.net_payable_minor,
                rc.ledger_transaction_id,
                rs.statement_number
            FROM RoyaltyCalculations rc
            LEFT JOIN RoyaltyStatements rs ON rs.calculation_id=rc.id
            ORDER BY rc.created_at DESC, rc.id DESC
            """).fetchall()
        self.royalty_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            balance = service.royalty_payable_balance_minor(
                calculation_id=int(row[0]),
                party_id=int(row[1]),
                currency=str(row[3] or "EUR"),
            )
            values = (
                str(row[0]),
                str(row[1]),
                str(row[2] or ""),
                format_money(int(row[4] or 0), currency=str(row[3] or "EUR")),
                format_money(balance, currency=str(row[3] or "EUR")),
                str(row[6] or ""),
                str(row[5] or ""),
            )
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col_index == 0:
                    item.setData(Qt.ItemDataRole.UserRole, int(row[0]))
                self.royalty_table.setItem(row_index, col_index, item)
        self.royalty_table.resizeColumnsToContents()

    def create_draft_invoice(self) -> None:
        conn = self._conn_or_warn()
        if conn is None:
            return
        party_id = self.party_combo.currentData()
        if party_id is None:
            QMessageBox.warning(self, "Invoice Workspace", "Create a party before invoicing.")
            return
        try:
            lines = tuple(self._draft_invoice_lines)
            if not lines:
                lines = (self._manual_line_payload(default_description="Invoice item"),)
            currency = self._draft_invoice_currency(InvoiceService(conn), lines)
            invoice = InvoiceService(conn).create_draft_invoice(
                InvoiceDraftPayload(
                    party_id=int(party_id),
                    due_date=_clean_text(self.due_date_field.text()),
                    currency=currency,
                    lines=lines,
                )
            )
            self._draft_invoice_lines.clear()
            self._refresh_draft_line_table()
            self._select_invoice_id(invoice.id)
            self.refresh_all()
        except Exception as exc:
            QMessageBox.warning(self, "Invoice Workspace", str(exc))

    def add_manual_invoice_line(self) -> None:
        try:
            self._append_draft_line(self._manual_line_payload(default_description="Manual item"))
        except Exception as exc:
            QMessageBox.warning(self, "Invoice Line", str(exc))

    def add_catalog_invoice_line(self) -> None:
        conn = self._conn_or_warn()
        item_id = self.catalog_item_combo.currentData()
        if conn is None or item_id is None:
            return
        item = InvoiceCatalogService(conn).fetch_item(int(item_id))
        if item is None:
            QMessageBox.warning(self, "Invoice Line", "Selected catalog preset was not found.")
            return
        quantity = format_quantity(
            Quantity(item.default_quantity_value, item.default_quantity_scale)
        )
        try:
            self._append_draft_line(
                InvoiceLinePayload(
                    description=item.description or item.name,
                    quantity=quantity,
                    unit_price_minor=0,
                    vat_treatment=item.default_vat_treatment,
                    vat_rate_basis_points=0,
                    vat_country_code=item.vat_country_code,
                    ledger_account_code=item.default_account_code,
                    catalog_item_id=item.id,
                )
            )
        except Exception as exc:
            QMessageBox.warning(self, "Invoice Line", str(exc))

    def add_travel_invoice_line(self) -> None:
        try:
            quantity = parse_quantity(_clean_text(self.travel_km_field.text()) or "0")
            if self.travel_round_trip_check.isChecked():
                quantity = Quantity(quantity.value * 2, quantity.scale)
            description = _clean_text(self.travel_description_field.text()) or "Travel costs"
            origin = _clean_text(self.travel_origin_field.text())
            destination = _clean_text(self.travel_destination_field.text())
            if origin and destination:
                description = f"{description}: {origin} to {destination}"
                if self.travel_round_trip_check.isChecked():
                    description += " round trip"
            self._append_draft_line(
                InvoiceLinePayload(
                    description=description,
                    quantity=format_quantity(quantity),
                    unit_price_minor=parse_money_minor(
                        _clean_text(self.travel_rate_field.text()) or "0"
                    ),
                    vat_rate_basis_points=int(_clean_text(self.vat_rate_field.text()) or "0"),
                    source_type="travel",
                )
            )
        except Exception as exc:
            QMessageBox.warning(self, "Travel Line", str(exc))

    def calculate_travel_km(self) -> None:
        try:
            result = TravelDistanceService().estimate_one_way_km(
                self.travel_origin_field.text(),
                self.travel_destination_field.text(),
            )
            self.travel_km_field.setText(result.one_way_km)
            if not _clean_text(self.travel_description_field.text()):
                self.travel_description_field.setText("Travel costs")
            self.travel_status_label.setText(f"Travel distance: {result.one_way_km} km one way.")
        except Exception as exc:
            QMessageBox.warning(self, "Travel KM Calculator", str(exc))

    def remove_selected_draft_line(self) -> None:
        row = self.draft_line_table.currentRow()
        if 0 <= row < len(self._draft_invoice_lines):
            del self._draft_invoice_lines[row]
            self._refresh_draft_line_table()

    def clear_draft_lines(self) -> None:
        self._draft_invoice_lines.clear()
        self._refresh_draft_line_table()

    def save_catalog_preset(self) -> None:
        conn = self._conn_or_warn()
        if conn is None:
            return
        try:
            payload = InvoiceCatalogItemPayload(
                name=_clean_text(self.catalog_name_field.text()) or "",
                description=_clean_text(self.catalog_description_field.text()),
                default_quantity=_clean_text(self.catalog_quantity_field.text()) or "1",
                default_unit_price_minor=parse_money_minor(
                    _clean_text(self.catalog_unit_price_field.text()) or "0"
                ),
                default_vat_rate_basis_points=int(
                    _clean_text(self.catalog_vat_rate_field.text()) or "0"
                ),
                vat_country_code=_clean_text(self.catalog_vat_country_field.text()),
                currency=self.catalog_currency_combo.currentData() or DEFAULT_CURRENCY,
                category=self._catalog_category_value(),
                default_account_code=self._catalog_account_code_value(),
                active=self.catalog_active_check.isChecked(),
            )
            service = InvoiceCatalogService(conn)
            item_id = self._selected_catalog_item_id()
            if item_id is None:
                service.create_item(payload)
            else:
                service.update_item(item_id, payload)
            self._refresh_invoice_catalog()
        except Exception as exc:
            QMessageBox.warning(self, "Catalog Preset", str(exc))

    def save_catalog_category(self) -> None:
        conn = self._conn_or_warn()
        if conn is None:
            return
        try:
            payload = InvoiceCatalogCategoryPayload(
                name=_clean_text(self.catalog_category_name_field.text()) or "",
                active=self.catalog_category_active_check.isChecked(),
            )
            service = InvoiceCatalogCategoryService(conn)
            category_id = self._selected_catalog_category_id()
            if category_id is None:
                service.create_category(payload)
            else:
                service.update_category(category_id, payload)
            self._refresh_catalog_category_settings()
            self._refresh_catalog_category_options()
        except Exception as exc:
            QMessageBox.warning(self, "Catalog Category", str(exc))

    def save_ledger_account(self) -> None:
        conn = self._conn_or_warn()
        if conn is None:
            return
        try:
            payload = AccountingAccountPayload(
                code=_clean_text(self.account_code_field.text()) or "",
                name=_clean_text(self.account_name_field.text()) or "",
                account_type=str(self.account_type_combo.currentData() or ""),
                normal_balance=str(self.account_normal_balance_combo.currentData() or ""),
                active=self.account_active_check.isChecked(),
            )
            service = AccountingAccountService(conn)
            account_id = self._selected_ledger_account_id()
            if account_id is None:
                service.create_account(payload)
            else:
                service.update_account(account_id, payload)
            self._refresh_account_admin_settings()
            self._refresh_catalog_account_options()
            self.refresh_accounting()
        except Exception as exc:
            QMessageBox.warning(self, "Ledger Account", str(exc))

    def _manual_line_payload(self, *, default_description: str) -> InvoiceLinePayload:
        return InvoiceLinePayload(
            description=_clean_text(self.description_field.text()) or default_description,
            quantity=_clean_text(self.quantity_field.text()) or "1",
            unit_price_minor=parse_money_minor(_clean_text(self.unit_price_field.text()) or "0"),
            vat_rate_basis_points=int(_clean_text(self.vat_rate_field.text()) or "0"),
        )

    def _append_draft_line(self, payload: InvoiceLinePayload) -> None:
        self._draft_invoice_lines.append(payload)
        try:
            self._refresh_draft_line_table()
        except Exception:
            self._draft_invoice_lines.pop()
            self._refresh_draft_line_table()
            raise

    @staticmethod
    def _draft_invoice_currency(
        invoice_service: InvoiceService,
        lines: tuple[InvoiceLinePayload, ...],
    ) -> str:
        currencies: list[str] = []
        for payload in lines:
            if payload.catalog_item_id is None:
                continue
            item = invoice_service.catalog_service.fetch_item(int(payload.catalog_item_id))
            if item is not None and item.currency:
                currencies.append(item.currency)
        unique = tuple(dict.fromkeys(currencies))
        if len(unique) > 1:
            raise ValueError("All draft invoice preset lines must use one currency.")
        return unique[0] if unique else DEFAULT_CURRENCY

    def _refresh_draft_line_table(self) -> None:
        conn = self._conn()
        self.draft_line_table.setRowCount(len(self._draft_invoice_lines))
        subtotal = 0
        vat_total = 0
        gross_total = 0
        invoice_service = InvoiceService(conn) if conn is not None else None
        currency = DEFAULT_CURRENCY
        if invoice_service is not None:
            currency = self._draft_invoice_currency(
                invoice_service,
                tuple(self._draft_invoice_lines),
            )
        for row_index, payload in enumerate(self._draft_invoice_lines):
            if invoice_service is not None:
                preview = invoice_service.preview_invoice_line(payload, currency=currency)
                quantity = format_quantity(
                    Quantity(
                        int(preview["quantity_value"]),
                        int(preview["quantity_scale"]),
                    )
                )
                line_currency = str(preview["currency"] or currency)
                unit = format_money(int(preview["unit_price_minor"]), currency=line_currency)
                net = int(preview["net_amount_minor"])
                vat = int(preview["vat_amount_minor"])
                gross = int(preview["gross_amount_minor"])
                source = str(
                    preview["catalog_item_name_snapshot"] or payload.source_type or "manual"
                )
            else:
                quantity = str(payload.quantity)
                unit = format_money(int(payload.unit_price_minor))
                net = vat = gross = 0
                source = payload.source_type or "manual"
            subtotal += net
            vat_total += vat
            gross_total += gross
            values = (
                str(row_index + 1),
                str(payload.description),
                quantity,
                unit,
                format_money(net, currency=currency),
                format_money(vat, currency=currency),
                format_money(gross, currency=currency),
            )
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col_index == 0:
                    item.setData(Qt.ItemDataRole.UserRole, source)
                self.draft_line_table.setItem(row_index, col_index, item)
        self.draft_line_table.resizeColumnsToContents()
        self.draft_totals_label.setText(
            "Draft totals: "
            f"net {format_money(subtotal, currency=currency)}, "
            f"VAT {format_money(vat_total, currency=currency)}, "
            f"gross {format_money(gross_total, currency=currency)}"
        )

    def issue_selected_invoice(self) -> None:
        invoice_id = self._selected_invoice_id()
        conn = self._conn_or_warn()
        if conn is None or invoice_id is None:
            return
        try:
            artifact = InvoiceTemplateService(conn, data_root=self._data_root).finalize_invoice(
                invoice_id,
                command_key=f"ui-issue-{invoice_id}-{uuid.uuid4().hex}",
                storage_mode=self._selected_invoice_final_storage_mode(),
            )
            self.refresh_all()
            self._select_invoice_id(invoice_id)
            self.invoice_final_status_label.setText(
                f"Final invoice stored as {self._storage_label(artifact.storage_mode)}."
            )
        except Exception as exc:
            QMessageBox.warning(self, "Finalize Invoice", str(exc))

    def view_selected_final_invoice(self) -> None:
        invoice_id = self._selected_invoice_id()
        conn = self._conn_or_warn()
        if conn is None:
            return
        if invoice_id is None:
            QMessageBox.warning(
                self,
                "Open Invoice",
                "Select a final invoice row first. Final invoices are created from Template Workspace.",
            )
            return
        try:
            template_service = InvoiceTemplateService(conn, data_root=self._data_root)
            artifact = self._latest_final_invoice_artifact(template_service, invoice_id)
            if artifact is None:
                QMessageBox.warning(
                    self,
                    "Open Invoice",
                    "The selected ledger invoice has no retained final invoice artifact.",
                )
                return
            path = template_service.materialize_output_artifact(int(artifact.id))
            opened = open_external_path(
                path,
                source="InvoiceWorkspacePanel.view_selected_final_invoice",
                metadata={
                    "invoice_id": int(invoice_id),
                    "artifact_id": int(artifact.id),
                    "storage_mode": artifact.storage_mode,
                },
            )
            self.invoice_final_status_label.setText(
                f"{'Opened' if opened else 'Could not open'} final invoice: {path}"
            )
            if not opened:
                QMessageBox.warning(self, "Open Invoice", f"Could not open {path}.")
        except Exception as exc:
            QMessageBox.warning(self, "Open Invoice", str(exc))

    def open_selected_final_invoice_location(self) -> None:
        invoice_id = self._selected_invoice_id()
        conn = self._conn_or_warn()
        if conn is None:
            return
        if invoice_id is None:
            QMessageBox.warning(
                self,
                "Open File Location",
                "Select a final invoice row first. Final invoices are created from Template Workspace.",
            )
            return
        try:
            template_service = InvoiceTemplateService(conn, data_root=self._data_root)
            artifact = self._latest_final_invoice_artifact(template_service, invoice_id)
            if artifact is None:
                QMessageBox.warning(
                    self,
                    "Open File Location",
                    "The selected ledger invoice has no retained final invoice artifact.",
                )
                return
            if artifact.storage_mode != STORAGE_MODE_MANAGED_FILE:
                self.invoice_final_status_label.setText(
                    "This final invoice is database embedded and has no managed file location."
                )
                return
            path = template_service.materialize_output_artifact(int(artifact.id))
            opened = open_external_path(
                path.parent,
                source="InvoiceWorkspacePanel.open_selected_final_invoice_location",
                metadata={
                    "invoice_id": int(invoice_id),
                    "artifact_id": int(artifact.id),
                    "storage_mode": artifact.storage_mode,
                },
            )
            self.invoice_final_status_label.setText(
                f"{'Opened' if opened else 'Could not open'} final invoice folder: {path.parent}"
            )
        except Exception as exc:
            QMessageBox.warning(self, "Open File Location", str(exc))

    def void_selected_invoice(self) -> None:
        invoice_id = self._selected_invoice_id()
        conn = self._conn_or_warn()
        if conn is None or invoice_id is None:
            return
        try:
            InvoiceService(conn).void_issued_invoice(
                invoice_id,
                command_key=f"ui-void-{invoice_id}-{uuid.uuid4().hex}",
            )
            self.refresh_all()
        except Exception as exc:
            QMessageBox.warning(self, "Void Invoice", str(exc))

    def purge_selected_invoice_for_cleanup(self) -> None:
        invoice_id = self._selected_invoice_id()
        conn = self._conn_or_warn()
        if conn is None:
            return
        if invoice_id is None:
            QMessageBox.warning(
                self,
                "Purge Invoice",
                "Select an invoice ledger row to purge.",
            )
            return
        invoice = InvoiceService(conn).fetch_invoice(invoice_id)
        if invoice is None:
            QMessageBox.warning(self, "Purge Invoice", "The selected invoice was not found.")
            return
        invoice_label = (
            invoice.invoice_number or invoice.draft_display_id or f"Invoice {invoice.id}"
        )
        accepted = QMessageBox.question(
            self,
            "Purge Invoice",
            (
                f"Permanently purge {invoice_label} and all linked invoice ledger data?\n\n"
                "This removes invoice lines, payments, credit notes, final artifacts, "
                "accounting transactions, and command-log rows for this invoice. "
                "Use this only for cleanup of accidental or test records."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if accepted != QMessageBox.StandardButton.Yes:
            return
        try:
            summary = InvoiceService(conn, data_root=self._data_root).purge_invoice_for_cleanup(
                invoice_id
            )
            self.refresh_all()
            self.invoice_final_status_label.setText(
                "Purged invoice cleanup: "
                f"{summary['payments']} payment(s), "
                f"{summary['credit_notes']} credit note(s), "
                f"{summary['artifacts']} artifact(s), "
                f"{summary['ledger_transactions']} ledger transaction(s)."
            )
        except Exception as exc:
            QMessageBox.warning(self, "Purge Invoice", str(exc))

    def record_payment_for_selected_invoice(self) -> None:
        invoice_id = self._selected_invoice_id()
        conn = self._conn_or_warn()
        if conn is None or invoice_id is None:
            return
        invoice = InvoiceService(conn).fetch_invoice(invoice_id)
        if invoice is None:
            QMessageBox.warning(self, "Record Payment", "Select an invoice first.")
            return
        amount_text, accepted = QInputDialog.getText(
            self,
            "Record Payment",
            "Payment amount:",
        )
        if not accepted:
            return
        try:
            InvoicePaymentService(conn).record_invoice_payment(
                InvoicePaymentPayload(
                    invoice_id=invoice.id,
                    party_id=invoice.party_id,
                    amount_minor=parse_money_minor(amount_text),
                    paid_at=date.today().isoformat(),
                    idempotency_key=f"ui-payment-{invoice.id}-{uuid.uuid4().hex}",
                )
            )
            self.refresh_all()
        except Exception as exc:
            QMessageBox.warning(self, "Record Payment", str(exc))

    def create_credit_note_for_selected_invoice(self) -> None:
        invoice_id = self._selected_invoice_id()
        conn = self._conn_or_warn()
        if conn is None or invoice_id is None:
            return
        invoice = InvoiceService(conn).fetch_invoice(invoice_id)
        if invoice is None:
            QMessageBox.warning(self, "Credit Note", "Select an invoice first.")
            return
        try:
            subtotal = parse_money_minor(_clean_text(self.credit_subtotal_field.text()) or "0")
            vat = parse_money_minor(_clean_text(self.credit_vat_field.text()) or "0")
            line_allocations: tuple[CreditNoteLineAllocationPayload, ...] = ()
            invoice_line_id = self._selected_invoice_line_id()
            if invoice_line_id is not None:
                if subtotal + vat <= 0:
                    line = next(
                        (
                            row
                            for row in CreditNoteService(conn).creditable_invoice_lines(invoice.id)
                            if row.id == invoice_line_id
                        ),
                        None,
                    )
                    if line is None:
                        QMessageBox.warning(
                            self,
                            "Credit Note",
                            "Selected invoice line is no longer available.",
                        )
                        return
                    subtotal = line.remaining_subtotal_minor
                    vat = line.remaining_vat_minor
                line_allocations = (
                    CreditNoteLineAllocationPayload(
                        invoice_line_item_id=invoice_line_id,
                        subtotal_minor=subtotal,
                        vat_minor=vat,
                    ),
                )
            if subtotal + vat <= 0:
                QMessageBox.warning(
                    self,
                    "Credit Note",
                    "Enter a positive credit subtotal and VAT allocation.",
                )
                return
            CreditNoteService(conn).create_credit_note(
                CreditNotePayload(
                    invoice_id=invoice.id,
                    party_id=invoice.party_id,
                    reason=_clean_text(self.credit_reason_field.text()) or "UI credit note",
                    issue_date=date.today().isoformat(),
                    subtotal_minor=subtotal,
                    vat_total_minor=vat,
                    line_allocations=line_allocations,
                    idempotency_key=f"ui-credit-{invoice.id}-{uuid.uuid4().hex}",
                )
            )
            self.refresh_all()
        except Exception as exc:
            QMessageBox.warning(self, "Credit Note", str(exc))

    def create_royalty_calculation(self) -> None:
        conn = self._conn_or_warn()
        if conn is None:
            return
        party_id = self.royalty_party_combo.currentData()
        if party_id is None:
            QMessageBox.warning(self, "Royalties", "Create an artist party before royalties.")
            return
        try:
            calculation = RoyaltyAccountingService(conn).create_calculation(
                RoyaltyCalculationPayload(
                    party_id=int(party_id),
                    period_start=_clean_text(self.royalty_period_start_field.text()),
                    period_end=_clean_text(self.royalty_period_end_field.text()),
                    lines=(
                        RoyaltyCalculationLinePayload(
                            description=_clean_text(self.royalty_description_field.text())
                            or "Royalty",
                            net_payable_minor=parse_money_minor(
                                _clean_text(self.royalty_amount_field.text()) or "0"
                            ),
                        ),
                    ),
                )
            )
            self.refresh_all()
            self._select_royalty_calculation_id(calculation.id)
        except Exception as exc:
            QMessageBox.warning(self, "Royalties", str(exc))

    def create_contract_royalty_term(self) -> None:
        conn = self._conn_or_warn()
        contract_id = self._selected_royalty_contract_id()
        party_id = self.royalty_term_party_combo.currentData()
        if conn is None or contract_id is None:
            return
        if party_id is None:
            QMessageBox.warning(self, "Royalty Terms", "Select a royalty payee party.")
            return
        scope_type = self.royalty_term_scope_type_combo.currentData()
        scope_id = self.royalty_term_scope_id_combo.currentData()
        scopes: tuple[RoyaltyTermScopePayload, ...] = ()
        if scope_type and scope_type != "contract":
            if scope_id is None:
                QMessageBox.warning(self, "Royalty Terms", "Select a scope record.")
                return
            scopes = (RoyaltyTermScopePayload(str(scope_type), int(scope_id)),)
        try:
            RoyaltyIntegrationService(conn).create_contract_royalty_term(
                ContractRoyaltyTermPayload(
                    contract_id=contract_id,
                    party_id=int(party_id),
                    royalty_basis=str(self.royalty_term_basis_combo.currentData() or "net"),
                    rate_basis_points=int(_clean_text(self.royalty_term_rate_field.text()) or "0"),
                    right_type=_clean_text(self.royalty_term_right_type_field.text()),
                    territory=_clean_text(self.royalty_term_territory_field.text()),
                    effective_start=_clean_text(self.royalty_term_effective_start_field.text()),
                    effective_end=_clean_text(self.royalty_term_effective_end_field.text()),
                    notes=_clean_text(self.royalty_term_notes_field.text()),
                ),
                scopes=scopes,
            )
            self.refresh_all()
        except Exception as exc:
            QMessageBox.warning(self, "Royalty Terms", str(exc))

    def record_royalty_source_event(self) -> None:
        conn = self._conn_or_warn()
        contract_id = self._selected_royalty_contract_id()
        if conn is None or contract_id is None:
            return
        metadata_note = _clean_text(self.royalty_source_metadata_field.text())
        try:
            RoyaltyIntegrationService(conn).record_source_event(
                RoyaltySourceEventPayload(
                    contract_id=contract_id,
                    work_id=self._combo_int_data(self.royalty_event_work_combo),
                    track_id=self._combo_int_data(self.royalty_event_track_combo),
                    release_id=self._combo_int_data(self.royalty_event_release_combo),
                    source_type=_clean_text(self.royalty_source_type_field.text()),
                    source_id=_clean_text(self.royalty_source_id_field.text()),
                    description=_clean_text(self.royalty_source_description_field.text())
                    or "Royalty source event",
                    event_date=_clean_text(self.royalty_source_event_date_field.text()),
                    period_start=_clean_text(self.royalty_source_period_start_field.text()),
                    period_end=_clean_text(self.royalty_source_period_end_field.text()),
                    gross_amount_minor=parse_money_minor(
                        _clean_text(self.royalty_source_gross_field.text()) or "0"
                    ),
                    net_amount_minor=parse_money_minor(
                        _clean_text(self.royalty_source_net_field.text()) or "0"
                    ),
                    metadata={"note": metadata_note} if metadata_note else None,
                )
            )
            self.refresh_all()
        except Exception as exc:
            QMessageBox.warning(self, "Royalty Source Event", str(exc))

    def import_royalty_source_events(self) -> None:
        conn = self._conn_or_warn()
        contract_id = self._selected_royalty_contract_id()
        if conn is None or contract_id is None:
            return
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Import Royalty Source Events",
            "",
            "DSP Statement Files (*.csv *.xml *.xlsx);;CSV Files (*.csv);;"
            "XML Files (*.xml);;Excel Files (*.xlsx)",
        )
        if not path:
            return
        try:
            service = RoyaltySourceImportService(conn)
            inspection = service.inspect_file(path)
            dialog = RoyaltySourceImportDialog(
                inspection=inspection,
                preview_callback=lambda mapping: service.preview_import(
                    path,
                    mapping,
                    default_contract_id=contract_id,
                ),
                parent=self,
            )
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            report = service.apply_import(
                path,
                dialog.mapping(),
                default_contract_id=contract_id,
            )
            self.refresh_all()
            QMessageBox.information(
                self,
                "Royalty Import",
                "\n".join(report.summary_lines),
            )
        except Exception as exc:
            QMessageBox.warning(self, "Royalty Import", str(exc))

    def generate_contract_royalty_calculations(self) -> None:
        conn = self._conn_or_warn()
        contract_id = self._selected_royalty_contract_id()
        if conn is None or contract_id is None:
            return
        try:
            calculations = RoyaltyIntegrationService(conn).create_draft_calculations_from_contract(
                contract_id,
                period_start=_clean_text(self.royalty_period_start_field.text()),
                period_end=_clean_text(self.royalty_period_end_field.text()),
                created_by="ui",
            )
            self.refresh_all()
            if calculations:
                self._select_royalty_calculation_id(calculations[0].id)
                self.royalty_workflow_tabs.setCurrentIndex(3)
            else:
                self.report_output.setPlainText(
                    "No royalty calculations were generated. Check term scopes, "
                    "source event amounts, and selected period."
                )
        except Exception as exc:
            QMessageBox.warning(self, "Generate Royalties", str(exc))

    def approve_selected_royalty_calculation(self) -> None:
        calculation_id = self._selected_royalty_calculation_id()
        conn = self._conn_or_warn()
        if conn is None or calculation_id is None:
            return
        try:
            RoyaltyAccountingService(conn).approve_and_post_calculation(
                calculation_id,
                command_key=f"ui-royalty-approve-{calculation_id}-{uuid.uuid4().hex}",
            )
            self.refresh_all()
        except Exception as exc:
            QMessageBox.warning(self, "Royalties", str(exc))

    def open_selected_contract_workspace(self) -> None:
        if self._open_contract_manager is None:
            QMessageBox.warning(self, "Contract Manager", "Contract manager is unavailable.")
            return
        self._open_contract_manager(self._selected_royalty_contract_id())

    def open_selected_work_workspace(self) -> None:
        if self._open_work_manager is None:
            QMessageBox.warning(self, "Work Manager", "Work manager is unavailable.")
            return
        work_id = self._selected_context_work_id()
        self._open_work_manager(work_id)

    def open_selected_track_workspace(self) -> None:
        if self._open_track_editor is None:
            QMessageBox.warning(self, "Track Editor", "Track editor is unavailable.")
            return
        track_id = self._selected_context_track_id()
        self._open_track_editor(track_id)

    def open_selected_rights_workspace(self) -> None:
        if self._open_rights_matrix is None:
            QMessageBox.warning(self, "Rights Matrix", "Rights matrix is unavailable.")
            return
        self._open_rights_matrix(self._selected_context_right_id())

    def open_selected_rights_title_record(self, item: QTableWidgetItem | None = None) -> None:
        work_id = self._rights_titles_item_id(item, Qt.ItemDataRole.UserRole)
        if work_id is None:
            work_id = self._selected_rights_titles_work_id()
        if work_id is not None and self._open_work_manager is not None:
            self._open_work_manager(work_id)
            return

        right_id = self._rights_titles_item_id(item, Qt.ItemDataRole.UserRole + 1)
        if right_id is None:
            right_id = self._selected_rights_titles_right_id()
        if right_id is not None and self._open_rights_matrix is not None:
            self._open_rights_matrix(right_id)
            return

        QMessageBox.warning(
            self, "Rights / Titles", "No linked work or rights record is available."
        )

    def generate_statement_for_selected_royalty(self) -> None:
        calculation_id = self._selected_royalty_calculation_id()
        conn = self._conn_or_warn()
        if conn is None or calculation_id is None:
            return
        try:
            RoyaltyAccountingService(conn).generate_statement(
                calculation_id,
                command_key=f"ui-royalty-statement-{calculation_id}-{uuid.uuid4().hex}",
                issue_date=date.today().isoformat(),
            )
            self.refresh_all()
        except Exception as exc:
            QMessageBox.warning(self, "Royalties", str(exc))

    def record_artist_payout_for_selected_royalty(self) -> None:
        calculation_id = self._selected_royalty_calculation_id()
        conn = self._conn_or_warn()
        if conn is None or calculation_id is None:
            return
        service = RoyaltyAccountingService(conn)
        calculation = service.fetch_calculation(calculation_id)
        if calculation is None:
            QMessageBox.warning(self, "Royalties", "Select a royalty calculation first.")
            return
        try:
            service.record_artist_payout(
                ArtistPayoutPayload(
                    party_id=calculation.party_id,
                    royalty_calculation_id=calculation.id,
                    amount_minor=parse_money_minor(
                        _clean_text(self.royalty_payout_amount_field.text()) or "0"
                    ),
                    paid_at=date.today().isoformat(),
                    payment_reference=_clean_text(self.royalty_payment_reference_field.text()),
                    idempotency_key=f"ui-artist-payout-{calculation.id}-{uuid.uuid4().hex}",
                )
            )
            self.refresh_all()
        except Exception as exc:
            QMessageBox.warning(self, "Royalties", str(exc))

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 2, 0, 0)
        root.setSpacing(0)
        root.addWidget(self.tabs)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.addTab(self._build_royalty_tab(), "Royalties")
        self.tabs.addTab(self._build_invoice_tab(), "Invoices")
        self.tabs.addTab(self._build_accounting_tab(), "Accounting")
        self.tabs.addTab(self._build_payments_tab(), "Payments")
        self.tabs.addTab(self._build_report_tab(), "Reports")
        self.tabs.addTab(self._build_settings_tab(), "Settings")
        self._hide_unmanaged_direct_children()

    def _hide_unmanaged_direct_children(self) -> None:
        """Prevent pre-created, unlaid-out widgets from floating over the workspace tabs."""

        for child in self.children():
            if (
                isinstance(child, QWidget)
                and child is not self.tabs
                and child.parentWidget() is self
            ):
                child.hide()

    def _build_dashboard_tab(self) -> QWidget:
        tab = QWidget(self)
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(8)
        title_box = QVBoxLayout()
        dashboard_title = QLabel("Royalties & Accounting Dashboard", tab)
        dashboard_title.setProperty("role", "heading")
        subtitle = QLabel(
            "Attention queue for royalties, invoice accounting, payments, VAT, and posting controls.",
            tab,
        )
        subtitle.setProperty("role", "secondary")
        subtitle.setWordWrap(True)
        title_box.addWidget(dashboard_title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box, 1)
        for label, slot in (
            ("Import Sales / Usage", self.import_royalty_source_events),
            ("Run Royalty Calculation", self.generate_contract_royalty_calculations),
            ("Create Invoice", lambda: self.tabs.setCurrentIndex(2)),
            ("Review Exceptions", lambda: self.tabs.setCurrentIndex(1)),
            ("Export Accounting", lambda: self.tabs.setCurrentIndex(3)),
        ):
            _add_action_button(tab, header, label, slot)
        layout.addLayout(header)

        kpi_grid = QGridLayout()
        kpi_grid.setHorizontalSpacing(10)
        kpi_grid.setVerticalSpacing(10)
        self._dashboard_kpi_labels = {
            "royalties_due": _add_kpi_card(
                kpi_grid,
                row=0,
                column=0,
                title="Royalties due",
                value="EUR 0.00",
                detail="Ledger-derived payable balance",
                parent=tab,
            ),
            "statements": _add_kpi_card(
                kpi_grid,
                row=0,
                column=1,
                title="Statements awaiting approval",
                value="0",
                detail="Approved or posted calculations without statements",
                parent=tab,
            ),
            "open_invoices": _add_kpi_card(
                kpi_grid,
                row=0,
                column=2,
                title="Open invoices",
                value="0",
                detail="Outstanding receivables",
                parent=tab,
            ),
            "overdue": _add_kpi_card(
                kpi_grid,
                row=0,
                column=3,
                title="Overdue invoices",
                value="0",
                detail="Due status derived at report time",
                parent=tab,
            ),
            "imports": _add_kpi_card(
                kpi_grid,
                row=1,
                column=0,
                title="Unmatched imports",
                value="0",
                detail="DSP/source rows needing metadata links",
                parent=tab,
            ),
            "payments": _add_kpi_card(
                kpi_grid,
                row=1,
                column=1,
                title="Payments awaiting release",
                value="0",
                detail="Royalty payables not fully paid",
                parent=tab,
            ),
            "vat": _add_kpi_card(
                kpi_grid,
                row=1,
                column=2,
                title="VAT amount current period",
                value="EUR 0.00",
                detail="VAT output less input",
                parent=tab,
            ),
            "exceptions": _add_kpi_card(
                kpi_grid,
                row=1,
                column=3,
                title="Exceptions requiring action",
                value="0",
                detail="Imports, overdue balances, and posting blockers",
                parent=tab,
            ),
        }
        layout.addLayout(kpi_grid)

        splitter = QSplitter(Qt.Orientation.Horizontal, tab)
        layout.addWidget(splitter, 1)
        left_panel = QWidget(splitter)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)
        left_sections: tuple[tuple[QTableWidget, str, str, tuple[str, ...]], ...] = (
            (
                self.dashboard_work_queue_table,
                "Work queue",
                "Prioritised exceptions and approvals that need a user decision.",
                (
                    "Type",
                    "Description",
                    "Related party",
                    "Period",
                    "Amount",
                    "Priority",
                    "Status",
                    "Action",
                ),
            ),
            (
                self.dashboard_calculation_table,
                "Royalty calculation status",
                "Recent calculation runs with statement, posting, and payout traceability.",
                (
                    "Period",
                    "Run ID",
                    "Status",
                    "Gross royalties",
                    "Deductions",
                    "Advance",
                    "Net payable",
                    "Exceptions",
                ),
            ),
        )
        for table, section_title, description, headers in left_sections:
            table.setHorizontalHeaderLabels(headers)
            _configure_workspace_table(table, minimum_height=180)
            box, box_layout = _create_standard_section(left_panel, section_title, description)
            box_layout.addWidget(table)
            left_layout.addWidget(box)
        right_panel = QWidget(splitter)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(10)
        right_sections: tuple[tuple[QTableWidget, str, str, tuple[str, ...]], ...] = (
            (
                self.dashboard_invoice_status_table,
                "Invoice status",
                "Document status is shown separately from ledger-derived payment state.",
                ("Status", "Count", "Outstanding", "Action"),
            ),
            (
                self.dashboard_accounting_control_table,
                "Accounting control",
                "Posting, export, and period-close checks before financial handoff.",
                ("Control", "Open items", "Status", "Action"),
            ),
        )
        for table, section_title, description, headers in right_sections:
            table.setHorizontalHeaderLabels(headers)
            _configure_workspace_table(table, minimum_height=180)
            box, box_layout = _create_standard_section(right_panel, section_title, description)
            box_layout.addWidget(table)
            right_layout.addWidget(box)
        _configure_detail_view(self.dashboard_detail_output)
        detail_box, detail_layout = _create_standard_section(
            right_panel,
            "Traceability note",
            "Every KPI should reconcile to invoices, royalty calculations, ledger entries, or source imports.",
        )
        detail_layout.addWidget(self.dashboard_detail_output)
        right_layout.addWidget(detail_box, 1)
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([720, 520])
        return tab

    def _build_invoice_tab(self) -> QWidget:
        tab = QWidget(self)
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        layout.addWidget(self.invoice_workflow_tabs, 1)

        ledger_tab = QWidget(self.invoice_workflow_tabs)
        ledger_layout = QVBoxLayout(ledger_tab)
        ledger_layout.setContentsMargins(8, 8, 8, 8)
        ledger_layout.setSpacing(10)
        ledger_actions = QHBoxLayout()
        ledger_actions.setSpacing(8)
        for label, slot in (
            ("Refresh", self.refresh_all),
            ("Open Invoice", self.view_selected_final_invoice),
            ("Open File Location", self.open_selected_final_invoice_location),
            ("Payment", self.record_payment_for_selected_invoice),
            ("Void", self.void_selected_invoice),
            ("Purge Selected", self.purge_selected_invoice_for_cleanup),
        ):
            _add_action_button(ledger_tab, ledger_actions, label, slot)
        ledger_actions.addStretch(1)
        ledger_layout.addLayout(ledger_actions)

        invoice_box, invoice_layout = _create_standard_section(
            ledger_tab,
            "Invoice ledger",
            "Ledger-derived document state, payment state, due state, totals, and outstanding balance.",
        )
        self.invoice_table.setHorizontalHeaderLabels(
            ("ID", "Number", "Party", "Document", "Payment", "Due", "Total", "Outstanding")
        )
        self.invoice_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.invoice_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.invoice_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.invoice_table.itemSelectionChanged.connect(self.refresh_invoice_lines)
        self.invoice_table.itemSelectionChanged.connect(self._refresh_selected_invoice_final_status)
        _configure_workspace_table(self.invoice_table, minimum_height=260)
        invoice_layout.addWidget(self.invoice_table)
        self.invoice_final_status_label.setProperty("role", "statusText")
        invoice_layout.addWidget(self.invoice_final_status_label)
        ledger_layout.addWidget(invoice_box, 1)
        self.invoice_workflow_tabs.addTab(ledger_tab, "Ledger")

        lines_tab = QWidget(self.invoice_workflow_tabs)
        lines_layout = QVBoxLayout(lines_tab)
        lines_layout.setContentsMargins(8, 8, 8, 8)
        lines_layout.setSpacing(8)
        self.invoice_line_table.setHorizontalHeaderLabels(
            ("Line ID", "Description", "Net", "VAT", "Gross", "Credit net left", "Credit VAT left")
        )
        self.invoice_line_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.invoice_line_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.invoice_line_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        _configure_workspace_table(self.invoice_line_table, minimum_height=150)
        lines_layout.addWidget(self.invoice_line_table)
        self.invoice_workflow_tabs.addTab(lines_tab, "Line Allocation")

        credit_tab = QWidget(self.invoice_workflow_tabs)
        credit_layout = QVBoxLayout(credit_tab)
        credit_layout.setContentsMargins(8, 8, 8, 8)
        credit_layout.setSpacing(10)
        credit_box = QGroupBox("Create credit note for selected invoice", credit_tab)
        credit_form = QFormLayout(credit_box)
        _configure_standard_form_layout(credit_form)
        self.credit_subtotal_field.setPlaceholderText("Credit net amount, e.g. 10.00")
        self.credit_vat_field.setPlaceholderText("Credit VAT amount, e.g. 2.10")
        self.credit_reason_field.setPlaceholderText("Reason shown in audit records")
        credit_form.addRow("Credit subtotal", self.credit_subtotal_field)
        credit_form.addRow("Credit VAT", self.credit_vat_field)
        credit_form.addRow("Reason", self.credit_reason_field)
        credit_layout.addWidget(credit_box)
        credit_actions = QHBoxLayout()
        credit_actions.setSpacing(8)
        _add_action_button(
            credit_tab,
            credit_actions,
            "Create Credit Note",
            self.create_credit_note_for_selected_invoice,
        )
        credit_actions.addStretch(1)
        credit_layout.addLayout(credit_actions)
        credit_layout.addStretch(1)
        self.invoice_workflow_tabs.addTab(credit_tab, "Credit Notes")
        self.invoice_workflow_tabs.setTabText(0, "Sales Invoices")
        self.invoice_workflow_tabs.addTab(
            self._build_table_detail_page(
                title="Royalty Payable Invoices",
                description=(
                    "Royalty payables and self-billing documents linked to statements and ledger postings."
                ),
                table=self.royalty_payables_table,
                detail=self.invoice_detail_output,
                headers=(
                    "Payee",
                    "Statement",
                    "Invoice",
                    "Due date",
                    "Amount",
                    "Currency",
                    "Approval",
                    "Payment",
                    "Action",
                ),
                empty_hint="Royalty payable invoices are created from approved statements.",
            ),
            "Royalty Payables",
        )
        self.invoice_workflow_tabs.addTab(
            self._build_table_detail_page(
                title="E-Invoices",
                description="E-invoice previews and delivery state for supported invoice types.",
                table=self.einvoice_table,
                detail=QTextEdit(self),
                headers=("Invoice", "Type", "Party", "Format", "Status", "Validation", "Action"),
                empty_hint="No e-invoice artifacts have been generated.",
            ),
            "E-Invoices",
        )
        return tab

    def _build_catalog_tab(self) -> QWidget:
        tab = QWidget(self)
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        splitter = QSplitter(Qt.Orientation.Horizontal, tab)
        layout.addWidget(splitter, 1)

        table_box, table_layout = _create_standard_section(
            tab,
            "Billable presets",
            "Maintain reusable services, goods, quantities, prices, VAT defaults, and ledger accounts.",
        )
        self.catalog_table.setHorizontalHeaderLabels(
            ("ID", "Name", "Category", "Qty", "Currency", "Price", "VAT", "Account", "State")
        )
        self.catalog_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.catalog_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.catalog_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.catalog_table.itemSelectionChanged.connect(self._populate_catalog_form_from_selection)
        _configure_workspace_table(self.catalog_table, minimum_height=360)
        table_layout.addWidget(self.catalog_table)

        editor_box, editor_layout = _create_standard_section(
            tab,
            "Preset editor",
            "Presets are copied into invoice line snapshots; later price changes do not alter issued invoices.",
        )
        form = QFormLayout()
        _configure_standard_form_layout(form)
        self.catalog_name_field.setPlaceholderText("Session fee")
        self.catalog_description_field.setPlaceholderText("Description copied to invoice lines")
        self.catalog_quantity_field.setPlaceholderText("1")
        self.catalog_unit_price_field.setPlaceholderText("100.00")
        self._populate_currency_combo(self.catalog_currency_combo)
        self.catalog_vat_rate_field.setPlaceholderText("2100")
        self.catalog_vat_country_field.setPlaceholderText("NL")
        self.catalog_vat_country_field.editingFinished.connect(
            self._apply_catalog_currency_from_country
        )
        self.catalog_category_combo.setObjectName("catalogCategoryCombo")
        self.catalog_category_combo.setEditable(True)
        if self.catalog_category_combo.lineEdit() is not None:
            self.catalog_category_combo.lineEdit().setPlaceholderText("Choose category")
        self.catalog_account_combo.setObjectName("catalogLedgerAccountCombo")
        self._refresh_catalog_category_options()
        self._refresh_catalog_account_options()
        category_selector = QWidget(editor_box)
        category_selector_layout = QHBoxLayout(category_selector)
        category_selector_layout.setContentsMargins(0, 0, 0, 0)
        category_selector_layout.setSpacing(6)
        category_selector_layout.addWidget(self.catalog_category_combo, 1)
        _add_action_button(
            category_selector,
            category_selector_layout,
            "Edit Categories",
            self.open_catalog_category_admin,
        )
        account_selector = QWidget(editor_box)
        account_selector_layout = QHBoxLayout(account_selector)
        account_selector_layout.setContentsMargins(0, 0, 0, 0)
        account_selector_layout.setSpacing(6)
        account_selector_layout.addWidget(self.catalog_account_combo, 1)
        _add_action_button(
            account_selector,
            account_selector_layout,
            "Edit Accounts",
            self.open_ledger_account_admin,
        )
        self.catalog_active_check.setChecked(True)
        form.addRow("Name", self.catalog_name_field)
        form.addRow("Description", self.catalog_description_field)
        form.addRow("Default quantity", self.catalog_quantity_field)
        form.addRow("Unit price", self.catalog_unit_price_field)
        form.addRow("Currency", self.catalog_currency_combo)
        form.addRow("VAT basis points", self.catalog_vat_rate_field)
        form.addRow("VAT country", self.catalog_vat_country_field)
        form.addRow("Category", category_selector)
        form.addRow("Ledger account", account_selector)
        form.addRow("", self.catalog_active_check)
        editor_layout.addLayout(form)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        _add_action_button(editor_box, actions, "Save Preset", self.save_catalog_preset)
        new_button = QPushButton("New Preset", editor_box)
        new_button.clicked.connect(self._clear_catalog_form)
        actions.addWidget(new_button)
        actions.addStretch(1)
        editor_layout.addLayout(actions)
        editor_layout.addStretch(1)
        splitter.addWidget(editor_box)
        splitter.addWidget(table_box)
        splitter.setSizes([420, 760])
        return tab

    def _build_royalty_tab(self) -> QWidget:
        tab = QWidget(self)
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        header = QHBoxLayout()
        header.setSpacing(8)
        header.addWidget(QLabel("Contract", tab))
        self.royalty_contract_combo.currentIndexChanged.connect(
            lambda *_args: self._refresh_selected_royalty_contract_context()
        )
        self.royalty_contract_combo.setMinimumContentsLength(28)
        self.royalty_contract_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        header.addWidget(self.royalty_contract_combo, stretch=1)
        for label, slot in (
            ("Open Contract", self.open_selected_contract_workspace),
            ("Open Work", self.open_selected_work_workspace),
            ("Open Track", self.open_selected_track_workspace),
            ("Open Rights", self.open_selected_rights_workspace),
            ("Refresh", self.refresh_all),
        ):
            button = QPushButton(label, tab)
            button.clicked.connect(slot)
            header.addWidget(button)
        layout.addLayout(header)
        layout.addWidget(self.royalty_workflow_tabs)
        self.royalty_workflow_tabs.addTab(self._build_royalty_contracts_tab(), "Contracts")
        self.royalty_workflow_tabs.addTab(self._build_rights_titles_tab(), "Rights / Titles")
        self.royalty_workflow_tabs.addTab(
            self._build_royalty_sources_tab(), "Sales & Usage Imports"
        )
        self.royalty_workflow_tabs.addTab(self._build_royalty_calculation_tab(), "Calculation Runs")
        self.royalty_workflow_tabs.addTab(
            self._build_royalty_statements_tab(), "Royalty Statements"
        )
        self.royalty_workflow_tabs.addTab(self._build_disputes_tab(), "Disputes")
        self.royalty_workflow_tabs.addTab(self._build_royalty_context_tab(), "Readiness")
        return tab

    def _build_table_detail_page(
        self,
        *,
        title: str,
        description: str,
        table: QTableWidget,
        detail: QTextEdit | QTextBrowser,
        headers: tuple[str, ...],
        empty_hint: str,
        actions: tuple[tuple[str, Callable[[], None]], ...] = (),
    ) -> QWidget:
        tab = QWidget(self)
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)
        header = QHBoxLayout()
        header.setSpacing(8)
        copy = QVBoxLayout()
        title_label = QLabel(title, tab)
        title_label.setProperty("role", "heading")
        description_label = QLabel(description, tab)
        description_label.setProperty("role", "secondary")
        description_label.setWordWrap(True)
        copy.addWidget(title_label)
        copy.addWidget(description_label)
        header.addLayout(copy, 1)
        for label, slot in actions:
            _add_action_button(tab, header, label, slot)
        layout.addLayout(header)

        splitter = QSplitter(Qt.Orientation.Horizontal, tab)
        layout.addWidget(splitter, 1)
        table_box, table_layout = _create_standard_section(
            tab,
            title,
            "Scrollable table with resize-to-content columns and source-record traceability.",
        )
        table.setHorizontalHeaderLabels(headers)
        _configure_workspace_table(table, minimum_height=360)
        table_layout.addWidget(table)
        detail_box, detail_layout = _create_standard_section(
            tab,
            "Detail drawer",
            "Select a row to review formulas, source links, journal postings, payments, and audit trail.",
        )
        _configure_detail_view(detail)
        detail.setPlainText(empty_hint)
        detail_layout.addWidget(detail)
        splitter.addWidget(table_box)
        splitter.addWidget(detail_box)
        splitter.setSizes([820, 420])
        return tab

    def _build_royalty_contracts_tab(self) -> QWidget:
        return self._build_table_detail_page(
            title="Contracts",
            description=(
                "Manage royalty agreements, rights, rates, advances, recoupment, and statement cycles."
            ),
            table=self.contracts_table,
            detail=self.contract_detail_output,
            headers=(
                "Contract ID",
                "Contract name",
                "Party / Payee",
                "Type",
                "Territory",
                "Start date",
                "End date",
                "Status",
                "Statement cycle",
                "Unrecouped advance",
                "Last updated",
            ),
            empty_hint=(
                "Contract detail tabs: Overview, Parties, Rights, Rates, Advances & Recoupment, "
                "Deductions, Statement Settings, Attachments, and Audit Trail."
            ),
            actions=(
                ("Open Contract", self.open_selected_contract_workspace),
                ("View Royalty Rules", lambda: self.royalty_workflow_tabs.setCurrentIndex(2)),
            ),
        )

    def _build_rights_titles_tab(self) -> QWidget:
        tab = self._build_table_detail_page(
            title="Rights / Titles",
            description=(
                "Manage musical works, recordings, titles, identifiers, territories, and rights ownership."
            ),
            table=self.rights_titles_table,
            detail=self.rights_detail_output,
            headers=(
                "Title / Product",
                "Identifier",
                "Type",
                "Owner / Payee",
                "Contract",
                "Territory",
                "Channel",
                "Status",
                "Royalty rule",
                "Last activity",
            ),
            empty_hint=(
                "Rights detail tabs: Overview, Linked contracts, Royalty rules, Sales/usage history, "
                "Statements, and Audit Trail. Contract-to-work links are explicit; recordings are "
                "shown as traceability context only."
            ),
            actions=(
                ("Open Work", self.open_selected_work_workspace),
                ("Open Rights", self.open_selected_rights_workspace),
            ),
        )
        self.rights_titles_table.itemDoubleClicked.connect(self.open_selected_rights_title_record)
        return tab

    def _build_royalty_statements_tab(self) -> QWidget:
        tab = self._build_table_detail_page(
            title="Royalty Statements",
            description=(
                "Generate, review, approve, send, and track statements to royalty payees."
            ),
            table=self.statement_table,
            detail=self.statement_detail_output,
            headers=(
                "Statement number",
                "Payee",
                "Contract",
                "Period",
                "Gross royalty",
                "Deductions",
                "Advance recouped",
                "Net payable",
                "Currency",
                "Status",
                "Sent at",
                "Payment status",
            ),
            empty_hint=(
                "Statement detail tabs: Summary, Transactions, Deductions, Advances, Tax / VAT, "
                "Invoice / Self-billing, Payment, Attachments, and Audit Trail."
            ),
            actions=(
                ("Generate Statement", self.generate_statement_for_selected_royalty),
                ("Record Payout", self.record_artist_payout_for_selected_royalty),
            ),
        )
        return tab

    def _build_disputes_tab(self) -> QWidget:
        return self._build_table_detail_page(
            title="Disputes",
            description=(
                "Track royalty statement disputes, blocked payments, reversal needs, and audit follow-up."
            ),
            table=self.dispute_table,
            detail=QTextEdit(self),
            headers=(
                "Dispute ID",
                "Statement",
                "Payee",
                "Reason",
                "Amount",
                "Priority",
                "Status",
                "Action",
            ),
            empty_hint=(
                "Dispute detail tabs: Summary, Source transactions, Calculation explanation, "
                "Statement links, Payment hold state, and Audit Trail."
            ),
            actions=(("Refresh", self.refresh_all),),
        )

    def _build_royalty_context_tab(self) -> QWidget:
        tab = QWidget(self)
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)
        intro = QLabel(
            "Contract-linked royalty accounting starts here. The context view aggregates "
            "explicit contract-work links, related recordings, rights records, ownership splits, "
            "royalty terms, source events, and readiness issues before anything is posted.",
            tab,
        )
        intro.setProperty("role", "secondary")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        generate = QPushButton("Generate Draft Calculations", tab)
        generate.clicked.connect(self.generate_contract_royalty_calculations)
        actions.addWidget(generate)
        actions.addStretch(1)
        layout.addLayout(actions)
        self.royalty_context_output.setReadOnly(True)
        self.royalty_context_output.setProperty("role", "workspaceCanvas")
        layout.addWidget(self.royalty_context_output, 1)
        return tab

    def _build_royalty_sources_tab(self) -> QWidget:
        tab = QWidget(self)
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)
        editor_tabs = QTabWidget(tab)
        layout.addWidget(editor_tabs, 1)

        term_panel = QWidget(editor_tabs)
        term_layout = QVBoxLayout(term_panel)
        term_layout.setContentsMargins(8, 8, 8, 8)
        term_layout.setSpacing(10)
        term_splitter = QSplitter(Qt.Orientation.Horizontal, term_panel)
        term_layout.addWidget(term_splitter, 1)
        self.royalty_term_table.setHorizontalHeaderLabels(
            ("ID", "Payee", "Rate", "Basis", "Scope", "Right type", "State")
        )
        self.royalty_term_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.royalty_term_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.royalty_term_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        _configure_workspace_table(self.royalty_term_table, minimum_height=180)
        term_table_box = QGroupBox("Royalty terms for selected contract", term_panel)
        term_table_layout = QVBoxLayout(term_table_box)
        term_table_layout.setContentsMargins(8, 8, 8, 8)
        term_table_layout.setSpacing(8)
        term_table_layout.addWidget(self.royalty_term_table)

        term_box, term_box_layout = _create_standard_section(
            term_panel,
            "Add royalty term",
            "Create a scoped royalty rule for the selected contract. Grouping mirrors the "
            "posting workflow: economics first, then repertoire scope, then effective dates.",
        )
        self.royalty_term_basis_combo.addItem("Net receipts", "net")
        self.royalty_term_basis_combo.addItem("Gross receipts", "gross")
        self.royalty_term_scope_type_combo.addItem("Whole contract", "contract")
        self.royalty_term_scope_type_combo.addItem("Linked work", "work")
        self.royalty_term_scope_type_combo.addItem("Recording linked through work", "track")
        self.royalty_term_scope_type_combo.addItem("Linked release", "release")
        self.royalty_term_scope_type_combo.addItem("Rights record", "right")
        self.royalty_term_scope_type_combo.currentIndexChanged.connect(
            lambda *_args: self.refresh_royalty_context()
        )
        self.royalty_term_rate_field.setPlaceholderText("1500 = 15.00%")
        self.royalty_term_right_type_field.setPlaceholderText("composition_publishing")
        self.royalty_term_territory_field.setPlaceholderText("Worldwide")
        self.royalty_term_effective_start_field.setPlaceholderText("YYYY-MM-DD")
        self.royalty_term_effective_end_field.setPlaceholderText("YYYY-MM-DD")
        self.royalty_term_notes_field.setPlaceholderText("Optional internal note")

        economics_box, economics_layout = _create_standard_section(term_box, "Term economics")
        economics_form = QGridLayout()
        economics_form.setHorizontalSpacing(12)
        economics_form.setVerticalSpacing(8)
        economics_fields = (
            ("Payee", self.royalty_term_party_combo),
            ("Rate basis points", self.royalty_term_rate_field),
            ("Basis", self.royalty_term_basis_combo),
        )
        for index, (label, widget) in enumerate(economics_fields):
            column = index * 2
            economics_form.addWidget(QLabel(label, economics_box), 0, column)
            economics_form.addWidget(widget, 0, column + 1)
        economics_form.setColumnStretch(5, 1)
        economics_layout.addLayout(economics_form)
        term_box_layout.addWidget(economics_box)

        scope_box, scope_layout = _create_standard_section(term_box, "Scope and rights")
        scope_form = QGridLayout()
        scope_form.setHorizontalSpacing(12)
        scope_form.setVerticalSpacing(8)
        scope_fields = (
            ("Scope type", self.royalty_term_scope_type_combo),
            ("Scope record", self.royalty_term_scope_id_combo),
            ("Right type", self.royalty_term_right_type_field),
            ("Territory", self.royalty_term_territory_field),
        )
        for index, (label, widget) in enumerate(scope_fields):
            row = index // 2
            column = (index % 2) * 2
            scope_form.addWidget(QLabel(label, scope_box), row, column)
            scope_form.addWidget(widget, row, column + 1)
        scope_form.setColumnStretch(4, 1)
        scope_layout.addLayout(scope_form)
        term_box_layout.addWidget(scope_box)

        validity_box, validity_layout = _create_standard_section(term_box, "Validity and notes")
        validity_form = QGridLayout()
        validity_form.setHorizontalSpacing(12)
        validity_form.setVerticalSpacing(8)
        validity_fields = (
            ("Effective start", self.royalty_term_effective_start_field),
            ("Effective end", self.royalty_term_effective_end_field),
            ("Notes", self.royalty_term_notes_field),
        )
        for index, (label, widget) in enumerate(validity_fields):
            row = index // 2
            column = (index % 2) * 2
            validity_form.addWidget(QLabel(label, validity_box), row, column)
            validity_form.addWidget(widget, row, column + 1)
        validity_form.setColumnStretch(4, 1)
        validity_layout.addLayout(validity_form)
        term_box_layout.addWidget(validity_box)

        add_term = QPushButton("Add Royalty Term", term_box)
        add_term.clicked.connect(self.create_contract_royalty_term)
        term_actions = QHBoxLayout()
        term_actions.setSpacing(8)
        term_actions.addItem(
            QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        )
        term_actions.addWidget(add_term)
        term_box_layout.addLayout(term_actions)
        term_box_layout.addStretch(1)
        term_splitter.addWidget(term_box)
        term_splitter.addWidget(term_table_box)
        term_splitter.setSizes([460, 760])
        editor_tabs.addTab(term_panel, "Royalty Terms")

        source_panel = QWidget(editor_tabs)
        source_layout = QVBoxLayout(source_panel)
        source_layout.setContentsMargins(8, 8, 8, 8)
        source_layout.setSpacing(10)
        source_splitter = QSplitter(Qt.Orientation.Horizontal, source_panel)
        source_layout.addWidget(source_splitter, 1)
        self.royalty_source_event_table.setHorizontalHeaderLabels(
            (
                "ID",
                "Description",
                "Contract",
                "Work",
                "Track",
                "Release",
                "Period",
                "Net",
                "Gross",
            )
        )
        self.royalty_source_event_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.royalty_source_event_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.royalty_source_event_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        _configure_workspace_table(self.royalty_source_event_table, minimum_height=180)
        source_table_box = QGroupBox("Royalty source events", source_panel)
        source_table_layout = QVBoxLayout(source_table_box)
        source_table_layout.setContentsMargins(8, 8, 8, 8)
        source_table_layout.setSpacing(8)
        source_table_layout.addWidget(self.royalty_source_event_table)

        source_box, source_box_layout = _create_standard_section(
            source_panel,
            "Record source event",
            "Capture revenue or usage source data, then link it to explicit repertoire records "
            "before royalty calculation.",
        )
        self.royalty_source_description_field.setPlaceholderText("DSP statement January")
        self.royalty_source_type_field.setPlaceholderText("statement/import/manual")
        self.royalty_source_id_field.setPlaceholderText("External statement/reference ID")
        self.royalty_source_gross_field.setPlaceholderText("120.00")
        self.royalty_source_net_field.setPlaceholderText("100.00")
        self.royalty_source_event_date_field.setPlaceholderText("YYYY-MM-DD")
        self.royalty_source_period_start_field.setPlaceholderText("YYYY-MM-DD")
        self.royalty_source_period_end_field.setPlaceholderText("YYYY-MM-DD")
        self.royalty_source_metadata_field.setPlaceholderText("Optional note/source detail")

        identity_box, identity_layout = _create_standard_section(source_box, "Source identity")
        identity_form = QGridLayout()
        identity_form.setHorizontalSpacing(12)
        identity_form.setVerticalSpacing(8)
        identity_fields = (
            ("Description", self.royalty_source_description_field),
            ("Source type", self.royalty_source_type_field),
            ("Source ID", self.royalty_source_id_field),
        )
        for index, (label, widget) in enumerate(identity_fields):
            row = index // 2
            column = (index % 2) * 2
            identity_form.addWidget(QLabel(label, identity_box), row, column)
            identity_form.addWidget(widget, row, column + 1)
        identity_form.setColumnStretch(4, 1)
        identity_layout.addLayout(identity_form)
        source_box_layout.addWidget(identity_box)

        repertoire_box, repertoire_layout = _create_standard_section(
            source_box,
            "Linked repertoire",
            "Use explicit work, recording, or release links only; these references drive traceable "
            "royalty matching.",
        )
        repertoire_form = QGridLayout()
        repertoire_form.setHorizontalSpacing(12)
        repertoire_form.setVerticalSpacing(8)
        repertoire_fields = (
            ("Work", self.royalty_event_work_combo),
            ("Track", self.royalty_event_track_combo),
            ("Release", self.royalty_event_release_combo),
        )
        for index, (label, widget) in enumerate(repertoire_fields):
            row = index // 2
            column = (index % 2) * 2
            repertoire_form.addWidget(QLabel(label, repertoire_box), row, column)
            repertoire_form.addWidget(widget, row, column + 1)
        repertoire_form.setColumnStretch(4, 1)
        repertoire_layout.addLayout(repertoire_form)
        source_box_layout.addWidget(repertoire_box)

        amounts_box, amounts_layout = _create_standard_section(
            source_box,
            "Amounts and reporting period",
        )
        amounts_form = QGridLayout()
        amounts_form.setHorizontalSpacing(12)
        amounts_form.setVerticalSpacing(8)
        amount_fields = (
            ("Gross amount", self.royalty_source_gross_field),
            ("Net amount", self.royalty_source_net_field),
            ("Event date", self.royalty_source_event_date_field),
            ("Period start", self.royalty_source_period_start_field),
            ("Period end", self.royalty_source_period_end_field),
            ("Metadata note", self.royalty_source_metadata_field),
        )
        for index, (label, widget) in enumerate(amount_fields):
            row = index // 2
            column = (index % 2) * 2
            amounts_form.addWidget(QLabel(label, amounts_box), row, column)
            amounts_form.addWidget(widget, row, column + 1)
        amounts_form.setColumnStretch(4, 1)
        amounts_layout.addLayout(amounts_form)
        source_box_layout.addWidget(amounts_box)

        add_source = QPushButton("Record Source Event", source_box)
        add_source.clicked.connect(self.record_royalty_source_event)
        source_actions = QHBoxLayout()
        source_actions.setSpacing(8)
        source_actions.addItem(
            QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        )
        import_source = QPushButton("Import DSP File...", source_box)
        import_source.clicked.connect(self.import_royalty_source_events)
        source_actions.addWidget(import_source)
        source_actions.addWidget(add_source)
        source_box_layout.addLayout(source_actions)
        source_box_layout.addStretch(1)
        source_splitter.addWidget(source_box)
        source_splitter.addWidget(source_table_box)
        source_splitter.setSizes([460, 760])
        editor_tabs.addTab(source_panel, "Source Events")
        return tab

    def _build_royalty_calculation_tab(self) -> QWidget:
        tab = QWidget(self)
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        for label, slot in (
            ("Refresh", self.refresh_all),
            ("Create Calculation", self.create_royalty_calculation),
            ("Approve / Post", self.approve_selected_royalty_calculation),
            ("Generate Statement", self.generate_statement_for_selected_royalty),
            ("Record Payout", self.record_artist_payout_for_selected_royalty),
        ):
            _add_action_button(tab, buttons, label, slot)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        calculation_splitter = QSplitter(Qt.Orientation.Horizontal, tab)
        layout.addWidget(calculation_splitter, 1)
        self.royalty_table.setHorizontalHeaderLabels(
            ("ID", "Artist Party", "Status", "Payable", "Balance", "Statement", "Ledger Tx")
        )
        self.royalty_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.royalty_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.royalty_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        _configure_workspace_table(self.royalty_table, minimum_height=260)
        royalty_table_box, royalty_table_layout = _create_standard_section(
            tab,
            "Royalty ledger",
            "Posted calculations, artist balances, statements, payouts, and ledger links.",
        )
        royalty_table_layout.addWidget(self.royalty_table)

        form_tabs = QTabWidget(calculation_splitter)
        calculation_box = QGroupBox("Create manual royalty calculation", form_tabs)
        calculation_form = QFormLayout(calculation_box)
        _configure_standard_form_layout(calculation_form)
        self.royalty_amount_field.setPlaceholderText("150.00")
        self.royalty_period_start_field.setPlaceholderText("YYYY-MM-DD")
        self.royalty_period_end_field.setPlaceholderText("YYYY-MM-DD")
        calculation_form.addRow("Artist party", self.royalty_party_combo)
        calculation_form.addRow("Description", self.royalty_description_field)
        calculation_form.addRow("Net payable", self.royalty_amount_field)
        calculation_form.addRow("Period start", self.royalty_period_start_field)
        calculation_form.addRow("Period end", self.royalty_period_end_field)
        form_tabs.addTab(calculation_box, "Manual Calculation")

        payout_box = QGroupBox("Record payout for selected royalty", form_tabs)
        payout_form = QFormLayout(payout_box)
        _configure_standard_form_layout(payout_form)
        self.royalty_payout_amount_field.setPlaceholderText("150.00")
        self.royalty_payment_reference_field.setPlaceholderText("Bank/payment reference")
        payout_form.addRow("Payout amount", self.royalty_payout_amount_field)
        payout_form.addRow("Payment reference", self.royalty_payment_reference_field)
        form_tabs.addTab(payout_box, "Payout")
        calculation_splitter.addWidget(form_tabs)
        calculation_splitter.addWidget(royalty_table_box)
        calculation_splitter.setSizes([420, 760])
        return tab

    def _build_accounting_tab(self) -> QWidget:
        tab = QWidget(self)
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        header = QLabel(
            "Ledger-backed accounting views reuse the existing accounts, transactions, entries, and VAT reports.",
            tab,
        )
        header.setProperty("role", "secondary")
        header.setWordWrap(True)
        layout.addWidget(header)
        tabs = QTabWidget(tab)
        layout.addWidget(tabs, 1)

        journal_tab = QWidget(tabs)
        journal_layout = QVBoxLayout(journal_tab)
        journal_layout.setContentsMargins(8, 8, 8, 8)
        journal_layout.setSpacing(10)
        journal_splitter = QSplitter(Qt.Orientation.Horizontal, journal_tab)
        journal_layout.addWidget(journal_splitter, 1)
        detail_box, detail_layout = _create_standard_section(
            journal_tab,
            "Journal detail",
            "Header, source documents, approval state, reversal links, and audit trail.",
        )
        _configure_detail_view(self.accounting_detail_output)
        self.accounting_detail_output.setPlainText(
            "Select a journal entry to inspect source links, debit/credit lines, VAT code, "
            "contract, payee/customer, and export status."
        )
        detail_layout.addWidget(self.accounting_detail_output)
        table_panel = QWidget(journal_splitter)
        table_layout = QVBoxLayout(table_panel)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.setSpacing(10)
        self.journal_table.setHorizontalHeaderLabels(
            (
                "Journal entry ID",
                "Source type",
                "Source reference",
                "Posting date",
                "Accounting period",
                "Description",
                "Debit total",
                "Credit total",
                "Status",
                "Export status",
            )
        )
        _configure_workspace_table(self.journal_table, minimum_height=240)
        journal_box, journal_box_layout = _create_standard_section(
            table_panel,
            "Journal entries",
            "Posted transactions from invoices, statements, payments, credit notes, and reversals.",
        )
        journal_box_layout.addWidget(self.journal_table)
        table_layout.addWidget(journal_box)
        self.journal_line_table.setHorizontalHeaderLabels(
            (
                "Ledger account",
                "Description",
                "Debit",
                "Credit",
                "VAT code",
                "Cost centre",
                "Project",
                "Contract",
                "Payee/customer",
            )
        )
        _configure_workspace_table(self.journal_line_table, minimum_height=160)
        line_box, line_layout = _create_standard_section(
            table_panel,
            "Journal line preview",
            "Debit/credit preview uses existing AccountingAccounts, not duplicate account definitions.",
        )
        line_layout.addWidget(self.journal_line_table)
        table_layout.addWidget(line_box)
        journal_splitter.addWidget(detail_box)
        journal_splitter.addWidget(table_panel)
        journal_splitter.setSizes([420, 820])
        tabs.addTab(journal_tab, "Journal Entries")

        tabs.addTab(
            self._build_table_detail_page(
                title="Ledger Mapping",
                description=(
                    "Map royalty and invoice transaction types to existing ledger account records."
                ),
                table=self.ledger_mapping_table,
                detail=QTextEdit(self),
                headers=(
                    "Mapping type",
                    "Source category",
                    "Royalty/invoice type",
                    "Existing ledger account",
                    "VAT code",
                    "Cost centre rule",
                    "Active",
                    "Last updated",
                ),
                empty_hint="Ledger mappings are derived from AccountingAccounts and service policy.",
            ),
            "Ledger Mapping",
        )
        tabs.addTab(
            self._build_table_detail_page(
                title="VAT Summary",
                description="VAT output, input, reverse-charge, exempt, and exception summaries.",
                table=self.vat_summary_table,
                detail=QTextEdit(self),
                headers=(
                    "Period",
                    "VAT payable",
                    "VAT receivable",
                    "Reverse charge",
                    "Exempt",
                    "Intra-EU",
                    "Domestic VAT",
                    "Unposted items",
                    "Exceptions",
                ),
                empty_hint="VAT details reconcile to invoice VAT breakdowns and VAT ledger entries.",
            ),
            "VAT Summary",
        )
        tabs.addTab(
            self._build_table_detail_page(
                title="Period Close",
                description="Close-period readiness checks for unposted documents and unlocked runs.",
                table=self.period_close_table,
                detail=QTextEdit(self),
                headers=(
                    "Period",
                    "Unposted invoices",
                    "Unposted statements",
                    "Unmatched payments",
                    "Calculation runs not locked",
                    "Action",
                ),
                empty_hint="Period close is blocked until ledger-backed records reconcile.",
            ),
            "Period Close",
        )
        tabs.addTab(
            self._build_table_detail_page(
                title="Accounting Export",
                description="Export batches for external accounting systems when integrations are configured.",
                table=self.accounting_export_table,
                detail=QTextEdit(self),
                headers=(
                    "Export batch ID",
                    "Date",
                    "System",
                    "Period",
                    "Items",
                    "Status",
                    "Errors",
                ),
                empty_hint="No accounting export batch selected.",
            ),
            "Accounting Export",
        )
        return tab

    def _build_payments_tab(self) -> QWidget:
        tab = QWidget(self)
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        header = QLabel(
            "Payables, receivables, bank matching, and SEPA preparation stay linked to invoices, "
            "royalty statements, and ledger transactions.",
            tab,
        )
        header.setProperty("role", "secondary")
        header.setWordWrap(True)
        layout.addWidget(header)
        tabs = QTabWidget(tab)
        layout.addWidget(tabs, 1)
        tabs.addTab(
            self._build_table_detail_page(
                title="Payables",
                description="Royalty payables awaiting approval, hold/release, payout, or SEPA batching.",
                table=self.payables_table,
                detail=self.payment_detail_output,
                headers=(
                    "Payee",
                    "Statement",
                    "Invoice",
                    "Due date",
                    "Amount",
                    "Currency",
                    "Hold status",
                    "Approval status",
                    "Payment status",
                    "Actions",
                ),
                empty_hint="Select a payable to inspect statement, invoice, journal entry, and payout status.",
                actions=(("Record Payout", self.record_artist_payout_for_selected_royalty),),
            ),
            "Payables",
        )
        tabs.addTab(
            self._build_table_detail_page(
                title="Receivables",
                description="Customer invoice receivables with ledger-derived settlement state.",
                table=self.receivables_table,
                detail=QTextEdit(self),
                headers=(
                    "Customer",
                    "Invoice",
                    "Due date",
                    "Amount",
                    "Currency",
                    "Days overdue",
                    "Payment status",
                    "Actions",
                    "Trace",
                ),
                empty_hint="Select a receivable to inspect invoice lines, payments, and journal entries.",
                actions=(("Record Payment", self.record_payment_for_selected_invoice),),
            ),
            "Receivables",
        )
        tabs.addTab(
            self._build_table_detail_page(
                title="Bank Reconciliation",
                description="Import bank statements through the existing import pattern and match transactions.",
                table=self.bank_reconciliation_table,
                detail=QTextEdit(self),
                headers=(
                    "Bank row",
                    "Date",
                    "Reference",
                    "Amount",
                    "Suggested match",
                    "Confidence",
                    "Status",
                    "Action",
                ),
                empty_hint="Bank reconciliation stores references only; bank accounting remains out of scope.",
            ),
            "Bank Reconciliation",
        )
        tabs.addTab(
            self._build_table_detail_page(
                title="SEPA Payment Batches",
                description="Prepare and audit payment batches for approved royalty payables.",
                table=self.sepa_batch_table,
                detail=QTextEdit(self),
                headers=(
                    "Batch ID",
                    "Created date",
                    "Created by",
                    "Payment date",
                    "Payments",
                    "Total amount",
                    "Status",
                    "Approval",
                ),
                empty_hint="SEPA export uses approved payable records and does not mutate posted ledger entries.",
            ),
            "SEPA Payment Batches",
        )
        return tab

    def _build_report_tab(self) -> QWidget:
        tab = QWidget(self)
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        header = QHBoxLayout()
        header.setSpacing(8)
        copy = QVBoxLayout()
        title = QLabel("Reports", tab)
        title.setProperty("role", "heading")
        subtitle = QLabel(
            "Ledger-backed royalty, invoice, VAT, management, and audit reports with drill-down.",
            tab,
        )
        subtitle.setProperty("role", "secondary")
        subtitle.setWordWrap(True)
        copy.addWidget(title)
        copy.addWidget(subtitle)
        header.addLayout(copy, 1)
        refresh = QPushButton("Refresh Reports", tab)
        refresh.clicked.connect(self.refresh_reports)
        header.addWidget(refresh)
        layout.addLayout(header)

        splitter = QSplitter(Qt.Orientation.Horizontal, tab)
        layout.addWidget(splitter, 1)
        self.report_catalog_table.setHorizontalHeaderLabels(
            ("Category", "Report", "Source", "Filters", "Drill-down")
        )
        _configure_workspace_table(self.report_catalog_table, minimum_height=360)
        catalog_box, catalog_layout = _create_standard_section(
            tab,
            "Report catalog",
            "Each report must reconcile to ledger entries, invoice records, source events, or statements.",
        )
        catalog_layout.addWidget(self.report_catalog_table)
        output_box, output_layout = _create_standard_section(
            tab,
            "Current report output",
            "Concise text summary for the selected accounting profile.",
        )
        self.report_output.setReadOnly(True)
        self.report_output.setProperty("role", "workspaceCanvas")
        output_layout.addWidget(self.report_output)
        splitter.addWidget(catalog_box)
        splitter.addWidget(output_box)
        splitter.setSizes([620, 620])
        return tab

    def _build_settings_tab(self) -> QWidget:
        tab = QWidget(self)
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        header = QLabel(
            "Settings extends existing company, numbering, VAT, ledger, preset, integration, and workflow concepts.",
            tab,
        )
        header.setProperty("role", "secondary")
        header.setWordWrap(True)
        layout.addWidget(header)
        tabs = QTabWidget(tab)
        self.settings_tabs = tabs
        layout.addWidget(tabs, 1)
        settings_pages = (
            (
                "Company",
                "Company profile, legal details, VAT number, billing address, and payment details.",
            ),
            (
                "Users & Roles",
                "Approval permissions for contracts, calculations, invoices, credit notes, payments, and close.",
            ),
            (
                "VAT & Tax",
                "VAT treatments, reverse charge/exempt labels, and domestic VAT defaults.",
            ),
            (
                "Invoice Numbering",
                "Uses existing code registry sequences for invoices, credit notes, and royalty statements.",
            ),
            (
                "Integrations",
                "DSP imports, accounting export targets, e-invoice routes, and email delivery.",
            ),
            (
                "Workflows",
                "Approval, reversal, payment hold, dispute, and period-close workflow policy.",
            ),
        )
        for title, text in settings_pages:
            if title == "Company":
                tabs.addTab(self._build_company_settings_page(tabs), title)
                continue
            if title == "Users & Roles":
                tabs.addTab(self._build_users_roles_settings_page(tabs), title)
                continue
            if title == "VAT & Tax":
                tabs.addTab(self._build_vat_tax_settings_page(tabs), title)
                continue
            if title == "Invoice Numbering":
                tabs.addTab(self._build_invoice_numbering_settings_page(tabs), title)
                continue
            if title == "Integrations":
                tabs.addTab(self._build_integrations_settings_page(tabs), title)
                continue
            if title == "Workflows":
                tabs.addTab(self._build_workflows_settings_page(tabs), title)
                continue
            page = QWidget(tabs)
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(8, 8, 8, 8)
            page_layout.setSpacing(10)
            box, box_layout = _create_standard_section(page, title, text)
            output = QTextEdit(box)
            _configure_detail_view(output)
            output.setPlainText(
                f"{title} settings should extend the existing application settings screens. "
                "This workspace shows the accounting-facing entry point without duplicating "
                "global settings or theme systems."
            )
            box_layout.addWidget(output)
            page_layout.addWidget(box, 1)
            tabs.addTab(page, title)
        tabs.addTab(self._build_catalog_tab(), "Billing Presets")
        tabs.addTab(self._build_catalog_category_settings_page(tabs), "Preset Categories")
        tabs.addTab(self._build_ledger_account_settings_page(tabs), "Ledger Accounts")
        return tab

    def _build_catalog_category_settings_page(self, parent: QWidget) -> QWidget:
        page = QWidget(parent)
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(8, 8, 8, 8)
        page_layout.setSpacing(10)
        box, box_layout = _create_standard_section(
            page,
            "Preset Categories",
            "Maintain the controlled category list used by billing preset dropdowns.",
        )
        splitter = QSplitter(Qt.Orientation.Horizontal, box)

        editor = QWidget(splitter)
        editor_layout = QVBoxLayout(editor)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.setSpacing(8)
        form = QFormLayout()
        _configure_standard_form_layout(form)
        self.catalog_category_name_field.setObjectName("catalogCategoryNameField")
        self.catalog_category_name_field.setPlaceholderText("Services")
        self.catalog_category_active_check.setChecked(True)
        form.addRow("Category", self.catalog_category_name_field)
        form.addRow("", self.catalog_category_active_check)
        editor_layout.addLayout(form)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        _add_action_button(editor, actions, "Save Category", self.save_catalog_category)
        _add_action_button(editor, actions, "New Category", self._clear_catalog_category_form)
        actions.addStretch(1)
        editor_layout.addLayout(actions)
        editor_layout.addStretch(1)

        table_panel = QWidget(splitter)
        table_layout = QVBoxLayout(table_panel)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.setSpacing(8)
        self.catalog_category_table.setObjectName("catalogCategoryAdminTable")
        self.catalog_category_table.setHorizontalHeaderLabels(
            ("ID", "Category", "State", "Created", "Updated")
        )
        self.catalog_category_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.catalog_category_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.catalog_category_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.catalog_category_table.itemSelectionChanged.connect(
            self._populate_catalog_category_form_from_selection
        )
        _configure_workspace_table(self.catalog_category_table, minimum_height=320)
        table_layout.addWidget(self.catalog_category_table, 1)

        splitter.addWidget(editor)
        splitter.addWidget(table_panel)
        splitter.setSizes([420, 760])
        box_layout.addWidget(splitter, 1)
        page_layout.addWidget(box, 1)
        self._refresh_catalog_category_settings()
        return page

    def _build_ledger_account_settings_page(self, parent: QWidget) -> QWidget:
        page = QWidget(parent)
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(8, 8, 8, 8)
        page_layout.setSpacing(10)
        box, box_layout = _create_standard_section(
            page,
            "Ledger Accounts",
            "Maintain the chart-of-accounts values used by billing preset ledger account dropdowns.",
        )
        splitter = QSplitter(Qt.Orientation.Horizontal, box)

        editor = QWidget(splitter)
        editor_layout = QVBoxLayout(editor)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.setSpacing(8)
        form = QFormLayout()
        _configure_standard_form_layout(form)
        self.account_code_field.setObjectName("ledgerAccountCodeField")
        self.account_name_field.setObjectName("ledgerAccountNameField")
        self.account_type_combo.setObjectName("ledgerAccountTypeCombo")
        self.account_normal_balance_combo.setObjectName("ledgerAccountNormalBalanceCombo")
        self.account_code_field.setPlaceholderText("4100")
        self.account_name_field.setPlaceholderText("Venue Revenue")
        self.account_type_combo.clear()
        for account_type in sorted(ACCOUNT_TYPES):
            self.account_type_combo.addItem(account_type.title(), account_type)
        self.account_normal_balance_combo.clear()
        for normal_balance in sorted(NORMAL_BALANCES):
            self.account_normal_balance_combo.addItem(normal_balance.title(), normal_balance)
        self.account_active_check.setChecked(True)
        form.addRow("Code", self.account_code_field)
        form.addRow("Name", self.account_name_field)
        form.addRow("Type", self.account_type_combo)
        form.addRow("Normal balance", self.account_normal_balance_combo)
        form.addRow("", self.account_active_check)
        editor_layout.addLayout(form)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        _add_action_button(editor, actions, "Save Account", self.save_ledger_account)
        _add_action_button(editor, actions, "New Account", self._clear_ledger_account_form)
        actions.addStretch(1)
        editor_layout.addLayout(actions)
        editor_layout.addStretch(1)

        table_panel = QWidget(splitter)
        table_layout = QVBoxLayout(table_panel)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.setSpacing(8)
        self.account_admin_table.setObjectName("ledgerAccountAdminTable")
        self.account_admin_table.setHorizontalHeaderLabels(
            ("ID", "Code", "Name", "Type", "Normal", "System", "State")
        )
        self.account_admin_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.account_admin_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.account_admin_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.account_admin_table.itemSelectionChanged.connect(
            self._populate_ledger_account_form_from_selection
        )
        _configure_workspace_table(self.account_admin_table, minimum_height=320)
        table_layout.addWidget(self.account_admin_table, 1)

        splitter.addWidget(editor)
        splitter.addWidget(table_panel)
        splitter.setSizes([420, 760])
        box_layout.addWidget(splitter, 1)
        page_layout.addWidget(box, 1)
        self._refresh_account_admin_settings()
        return page

    def _build_company_settings_page(self, parent: QWidget) -> QWidget:
        page = QWidget(parent)
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(8, 8, 8, 8)
        page_layout.setSpacing(10)
        box, box_layout = _create_standard_section(
            page,
            "Company",
            "Read-only accounting identity sourced from the current Owner Party in Party Manager.",
        )
        actions = QHBoxLayout()
        actions.setSpacing(8)
        source_label = QLabel(
            "Edit legal details, VAT, address, and bank data on the Owner Party record.",
            box,
        )
        source_label.setProperty("role", "secondary")
        source_label.setWordWrap(True)
        actions.addWidget(source_label, 1)
        refresh = QPushButton("Refresh Owner Ledger", box)
        refresh.clicked.connect(self._refresh_company_settings)
        actions.addWidget(refresh, 0)
        box_layout.addLayout(actions)
        _configure_detail_view(self.company_owner_output)
        box_layout.addWidget(self.company_owner_output, 1)
        page_layout.addWidget(box, 1)
        return page

    def _build_vat_tax_settings_page(self, parent: QWidget) -> QWidget:
        page, content, page_layout = _scrollable_page(parent)
        box, box_layout = _create_standard_section(
            content,
            "VAT & Tax",
            (
                "VAT configuration view built from existing Party Manager owner data, catalog "
                "defaults, invoice snapshots, and VAT ledger entries."
            ),
        )
        actions = QHBoxLayout()
        actions.setSpacing(8)
        source_label = QLabel(
            "Edit VAT identity on the Owner Party. Edit rates and treatments through billing "
            "presets or invoice lines; posted VAT remains ledger-backed and immutable.",
            box,
        )
        source_label.setProperty("role", "secondary")
        source_label.setWordWrap(True)
        actions.addWidget(source_label, 1)
        refresh = QPushButton("Refresh VAT View", box)
        refresh.clicked.connect(self._refresh_vat_tax_settings)
        actions.addWidget(refresh, 0)
        box_layout.addLayout(actions)

        splitter = QSplitter(Qt.Orientation.Horizontal, box)
        left_panel = QWidget(splitter)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)
        treatment_box, treatment_layout = _create_standard_section(
            left_panel,
            "VAT treatments and defaults",
            "Supported treatments, active catalog defaults, and invoice-line usage.",
        )
        _configure_workspace_table(self.vat_treatment_table, minimum_height=260)
        treatment_layout.addWidget(self.vat_treatment_table, 1)
        left_layout.addWidget(treatment_box, 1)

        ledger_box, ledger_layout = _create_standard_section(
            left_panel,
            "VAT ledger activity",
            "Ledger-backed VAT output/input grouped by treatment, rate, and currency.",
        )
        _configure_workspace_table(self.vat_activity_table, minimum_height=180)
        ledger_layout.addWidget(self.vat_activity_table, 1)
        left_layout.addWidget(ledger_box, 1)

        detail_box, detail_layout = _create_standard_section(
            splitter,
            "VAT readiness and reconciliation",
            "Owner VAT identity, calculation rules, reverse-charge/exempt handling, and totals.",
        )
        _configure_detail_view(self.vat_tax_detail_output)
        detail_layout.addWidget(self.vat_tax_detail_output, 1)
        splitter.addWidget(left_panel)
        splitter.addWidget(detail_box)
        splitter.setSizes([760, 480])
        box_layout.addWidget(splitter, 1)
        page_layout.addWidget(box, 1)
        return page

    def _build_invoice_numbering_settings_page(self, parent: QWidget) -> QWidget:
        page, content, page_layout = _scrollable_page(parent)
        box, box_layout = _create_standard_section(
            content,
            "Invoice Numbering",
            (
                "Read-only accounting view of the existing Code Registry sequences used for "
                "invoices, credit notes, ledger transactions, and royalty statements."
            ),
        )
        actions = QHBoxLayout()
        actions.setSpacing(8)
        source_label = QLabel(
            "Edit prefixes and activation in the Code Registry Workspace. This page previews "
            "the next number without reserving it; final numbers are assigned only by the "
            "financial posting workflow.",
            box,
        )
        source_label.setProperty("role", "secondary")
        source_label.setWordWrap(True)
        actions.addWidget(source_label, 1)
        refresh = QPushButton("Refresh Registry Sequences", box)
        refresh.clicked.connect(self._refresh_invoice_numbering_settings)
        actions.addWidget(refresh, 0)
        box_layout.addLayout(actions)

        splitter = QSplitter(Qt.Orientation.Horizontal, box)
        left_panel = QWidget(splitter)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)

        sequence_box, sequence_layout = _create_standard_section(
            left_panel,
            "Code registry sequences",
            "Canonical categories and current-year sequence health from CodeRegistryEntries.",
        )
        _configure_workspace_table(self.numbering_sequence_table, minimum_height=260)
        sequence_layout.addWidget(self.numbering_sequence_table, 1)
        left_layout.addWidget(sequence_box, 1)

        usage_box, usage_layout = _create_standard_section(
            left_panel,
            "Document usage and guards",
            "Business records linked to registry entries, plus draft/unissued counts.",
        )
        _configure_workspace_table(self.numbering_usage_table, minimum_height=220)
        usage_layout.addWidget(self.numbering_usage_table, 1)
        left_layout.addWidget(usage_box, 1)

        detail_box, detail_layout = _create_standard_section(
            splitter,
            "Numbering rules and reconciliation",
            "Sequential numbering policy, draft behaviour, concurrency safety, and immutable guards.",
        )
        _configure_detail_view(self.invoice_numbering_detail_output)
        detail_layout.addWidget(self.invoice_numbering_detail_output, 1)
        splitter.addWidget(left_panel)
        splitter.addWidget(detail_box)
        splitter.setSizes([780, 480])
        box_layout.addWidget(splitter, 1)
        page_layout.addWidget(box, 1)
        return page

    def _build_integrations_settings_page(self, parent: QWidget) -> QWidget:
        page, content, page_layout = _scrollable_page(parent)
        box, box_layout = _create_standard_section(
            content,
            "Integrations",
            (
                "DSP statement imports reuse the existing royalty source import service, mapping "
                "dialog, and source-event storage. No separate import framework is created here."
            ),
        )

        control_box = QGroupBox("DSP statement inspection", box)
        control_layout = QVBoxLayout(control_box)
        control_layout.setContentsMargins(12, 12, 12, 12)
        control_layout.setSpacing(8)
        help_label = QLabel(
            "Select a CSV, XML, or XLSX royalty statement. The workspace suggests source-event "
            "field mappings, previews rounded minor-unit amounts, and opens the existing import "
            "wizard for final review and commit.",
            control_box,
        )
        help_label.setProperty("role", "secondary")
        help_label.setWordWrap(True)
        control_layout.addWidget(help_label)
        file_row = QHBoxLayout()
        file_row.setSpacing(8)
        self.integration_file_path_field.setPlaceholderText("DSP statement file")
        file_row.addWidget(QLabel("Statement", control_box), 0)
        file_row.addWidget(self.integration_file_path_field, 1)
        browse = QPushButton("Browse DSP File...", control_box)
        browse.clicked.connect(self._browse_integration_statement_file)
        file_row.addWidget(browse)
        inspect = QPushButton("Inspect Statement", control_box)
        inspect.clicked.connect(self._inspect_integrations_statement)
        file_row.addWidget(inspect)
        wizard = QPushButton("Open Import Wizard...", control_box)
        wizard.clicked.connect(self._open_integrations_import_wizard)
        file_row.addWidget(wizard)
        control_layout.addLayout(file_row)
        box_layout.addWidget(control_box)

        splitter = QSplitter(Qt.Orientation.Horizontal, box)
        left_panel = QWidget(splitter)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)

        profile_box, profile_layout = _create_standard_section(
            left_panel,
            "Integration profiles",
            "Available accounting-facing integrations and the existing services they use.",
        )
        _configure_workspace_table(self.integration_profile_table, minimum_height=170)
        profile_layout.addWidget(self.integration_profile_table, 1)
        left_layout.addWidget(profile_box)

        mapping_box, mapping_layout = _create_standard_section(
            left_panel,
            "Detected field mapping",
            "Suggested source-to-target mapping, sample values, currency inference, and omissions.",
        )
        _configure_workspace_table(self.integration_mapping_table, minimum_height=260)
        mapping_layout.addWidget(self.integration_mapping_table, 1)
        left_layout.addWidget(mapping_box, 1)

        right_panel = QWidget(splitter)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(10)

        preview_box, preview_layout = _create_standard_section(
            right_panel,
            "Resolved DSP preview",
            "Rows as they would resolve into RoyaltySourceEvents before posting calculations.",
        )
        _configure_workspace_table(self.integration_preview_table, minimum_height=300)
        preview_layout.addWidget(self.integration_preview_table, 1)
        right_layout.addWidget(preview_box, 1)

        detail_box, detail_layout = _create_standard_section(
            right_panel,
            "Integration readiness",
            "Import summary, rounding warnings, metadata matching limits, and next actions.",
        )
        _configure_detail_view(self.integrations_detail_output)
        detail_layout.addWidget(self.integrations_detail_output, 1)
        right_layout.addWidget(detail_box, 1)

        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([560, 760])
        box_layout.addWidget(splitter, 1)
        page_layout.addWidget(box, 1)
        page_layout.addStretch(1)
        return page

    def _build_workflows_settings_page(self, parent: QWidget) -> QWidget:
        page, content, page_layout = _scrollable_page(parent)
        box, box_layout = _create_standard_section(
            content,
            "Workflows",
            (
                "Approval, reversal, payment hold, dispute, and period-close policy derived "
                "from the existing invoice, royalty, command-log, and ledger workflow model."
            ),
        )
        actions = QHBoxLayout()
        actions.setSpacing(8)
        source_label = QLabel(
            "This is an accounting-facing control view, not a duplicate permission system. "
            "Posting, reversal, numbering, and idempotency remain enforced by the existing "
            "financial services and database guards.",
            box,
        )
        source_label.setProperty("role", "secondary")
        source_label.setWordWrap(True)
        actions.addWidget(source_label, 1)
        refresh = QPushButton("Refresh Workflow Controls", box)
        refresh.clicked.connect(self._refresh_workflows_settings)
        actions.addWidget(refresh, 0)
        box_layout.addLayout(actions)

        splitter = QSplitter(Qt.Orientation.Horizontal, box)
        left_panel = QWidget(splitter)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)

        policy_box, policy_layout = _create_standard_section(
            left_panel,
            "Workflow policy matrix",
            "Canonical document transitions and the service/table that enforces each guard.",
        )
        _configure_workspace_table(self.workflow_policy_table, minimum_height=300)
        policy_layout.addWidget(self.workflow_policy_table, 1)
        left_layout.addWidget(policy_box, 1)

        queue_box, queue_layout = _create_standard_section(
            left_panel,
            "Current workflow queue",
            "Live approval, posting, matching, and period-close blockers from existing records.",
        )
        _configure_workspace_table(self.workflow_queue_table, minimum_height=260)
        queue_layout.addWidget(self.workflow_queue_table, 1)
        left_layout.addWidget(queue_box, 1)

        right_panel = QWidget(splitter)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(10)

        command_box, command_layout = _create_standard_section(
            right_panel,
            "Financial command log",
            "Recent idempotent commands used for issue, payment, credit, royalty, and posting flows.",
        )
        _configure_workspace_table(self.workflow_command_table, minimum_height=240)
        command_layout.addWidget(self.workflow_command_table, 1)
        right_layout.addWidget(command_box, 1)

        detail_box, detail_layout = _create_standard_section(
            right_panel,
            "Workflow rules and reconciliation",
            "Operational safeguards that keep accounting actions auditable and ledger-backed.",
        )
        _configure_detail_view(self.workflow_detail_output)
        detail_layout.addWidget(self.workflow_detail_output, 1)
        right_layout.addWidget(detail_box, 1)

        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([760, 560])
        box_layout.addWidget(splitter, 1)
        page_layout.addWidget(box, 1)
        page_layout.addStretch(1)
        return page

    def _build_users_roles_settings_page(self, parent: QWidget) -> QWidget:
        page, content, page_layout = _scrollable_page(parent)
        box, box_layout = _create_standard_section(
            content,
            "Users & Roles",
            (
                "Business roles are sourced from canonical Party Manager records. "
                "This does not create a separate permission system."
            ),
        )
        actions = QHBoxLayout()
        actions.setSpacing(8)
        source_label = QLabel(
            "Use Party Manager to maintain owners, artists/payees, publishers, licensees, "
            "managers, lawyers, distributors, and billing contacts used by accounting workflows.",
            box,
        )
        source_label.setProperty("role", "secondary")
        source_label.setWordWrap(True)
        actions.addWidget(source_label, 1)
        refresh = QPushButton("Refresh Party Roles", box)
        refresh.clicked.connect(self._refresh_users_roles_settings)
        actions.addWidget(refresh, 0)
        box_layout.addLayout(actions)

        splitter = QSplitter(Qt.Orientation.Horizontal, box)
        roster_box, roster_layout = _create_standard_section(
            splitter,
            "Party Manager role roster",
            "Canonical parties grouped into accounting-facing workflow roles.",
        )
        self.users_roles_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.users_roles_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.users_roles_table.itemSelectionChanged.connect(self._refresh_users_roles_detail)
        self.users_roles_table.itemDoubleClicked.connect(self.open_selected_users_roles_party)
        _configure_workspace_table(self.users_roles_table, minimum_height=420)
        roster_layout.addWidget(self.users_roles_table, 1)

        detail_box, detail_layout = _create_standard_section(
            splitter,
            "Selected party readiness",
            "Shows contact, billing, payout, VAT, and workflow readiness from Party Manager.",
        )
        _configure_detail_view(self.users_roles_detail_output)
        detail_layout.addWidget(self.users_roles_detail_output, 1)
        splitter.addWidget(roster_box)
        splitter.addWidget(detail_box)
        splitter.setSizes([720, 520])
        box_layout.addWidget(splitter, 1)
        page_layout.addWidget(box, 1)
        return page

    def _refresh_company_settings(self) -> None:
        conn = self._conn()
        if conn is None:
            return
        try:
            owner_settings = SettingsReadService(conn).load_owner_party_settings()
        except Exception as exc:
            self.company_owner_output.setPlainText(
                "Unable to load the current Owner Party from Party Manager.\n\n" f"Reason: {exc}"
            )
            return
        self.company_owner_output.setPlainText(self._format_owner_ledger_settings(owner_settings))

    def _format_owner_ledger_settings(self, owner: OwnerPartySettings) -> str:
        if owner.party_id is None:
            return (
                "No current Owner Party is set.\n\n"
                "Set the current owner in Party Manager. The accounting workspace uses that "
                "owner ledger record for company name, legal name, VAT number, billing address, "
                "and payment details."
            )

        def value(raw_value: object | None) -> str:
            return str(raw_value or "").strip() or "-"

        display_name = (
            owner.display_name
            or owner.company_name
            or owner.artist_name
            or owner.legal_name
            or f"Party #{owner.party_id}"
        )
        street_line = " ".join(
            part for part in (owner.street_name, owner.street_number) if str(part or "").strip()
        ).strip()
        address_lines = [
            line
            for line in (
                owner.address_line1,
                owner.address_line2,
                street_line,
                " ".join(
                    part for part in (owner.postal_code, owner.city) if str(part or "").strip()
                ).strip(),
                owner.region,
                owner.country,
            )
            if str(line or "").strip()
        ]
        missing_fields = [
            label
            for label, field_value in (
                ("company/legal name", owner.company_name or owner.legal_name),
                ("billing address", "\n".join(address_lines)),
                ("VAT number", owner.vat_number),
                ("bank account", owner.bank_account_number),
            )
            if not str(field_value or "").strip()
        ]
        lines = [
            "Source: Party Manager -> Current Owner Party",
            f"Owner party ID: {owner.party_id}",
            "",
            "Identity",
            f"Display name: {value(display_name)}",
            f"Legal name: {value(owner.legal_name)}",
            f"Company name: {value(owner.company_name)}",
            "Party type: owner party",
            "",
            "Contact",
            f"Contact person: {value(owner.contact_person)}",
            f"Email: {value(owner.email)}",
            f"Alternative email: {value(owner.alternative_email)}",
            f"Phone: {value(owner.phone)}",
            f"Website: {value(owner.website)}",
            "",
            "Billing address",
        ]
        lines.extend(address_lines or ["-"])
        lines.extend(
            [
                "",
                "Registration and tax",
                f"VAT number: {value(owner.vat_number)}",
                f"Tax ID: {value(owner.tax_id)}",
                f"Chamber of Commerce: {value(owner.chamber_of_commerce_number)}",
                f"PRO affiliation: {value(owner.pro_affiliation)}",
                f"PRO number: {value(owner.pro_number)}",
                f"IPI/CAE: {value(owner.ipi_cae)}",
                "",
                "Payment details",
                f"Bank account: {value(owner.bank_account_number)}",
            ]
        )
        if str(owner.notes or "").strip():
            lines.extend(["", "Owner notes", str(owner.notes).strip()])
        if missing_fields:
            lines.extend(
                [
                    "",
                    "Readiness",
                    "Missing for invoice/accounting output: " + ", ".join(missing_fields) + ".",
                ]
            )
        return "\n".join(lines)

    def _refresh_users_roles_settings(self) -> None:
        conn = self._conn()
        if conn is None:
            return
        selected_party_id = self._selected_users_roles_party_id()
        try:
            records = PartyService(conn).list_parties()
            owner_party_id = SettingsReadService(conn).load_owner_party_id()
        except Exception as exc:
            self.users_roles_detail_output.setPlainText(
                "Unable to load role records from Party Manager.\n\n" f"Reason: {exc}"
            )
            _set_table_rows(
                self.users_roles_table,
                (
                    "Party",
                    "Party type",
                    "Accounting role",
                    "Workflow use",
                    "Contact",
                    "Readiness",
                ),
                [],
                empty_message="Unable to load Party Manager roles.",
            )
            return
        headers = (
            "Party",
            "Party type",
            "Accounting role",
            "Workflow use",
            "Contact",
            "Readiness",
        )
        self.users_roles_table.setColumnCount(len(headers))
        self.users_roles_table.setHorizontalHeaderLabels(headers)
        if not records:
            self.users_roles_table.setRowCount(1)
            for column, value in enumerate(
                ("No parties found in Party Manager.", "", "", "", "", "")
            ):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                self.users_roles_table.setItem(0, column, item)
            self.users_roles_table.resizeColumnsToContents()
            self.users_roles_detail_output.setPlainText(
                "No Party Manager records are available yet.\n\n"
                "Create parties in Party Manager first. Accounting workflows then reuse those "
                "canonical parties as invoice recipients, royalty payees, statement contacts, "
                "representatives, distributors, and the current owner identity."
            )
            return

        self.users_roles_table.setRowCount(len(records))
        selected_row = 0
        for row_index, record in enumerate(records):
            is_owner = owner_party_id is not None and int(record.id) == int(owner_party_id)
            missing = self._party_role_readiness_gaps(record, is_owner=is_owner)
            values = (
                self._party_display_label(record),
                _status_label(record.party_type),
                self._party_accounting_role(record, is_owner=is_owner),
                self._party_workflow_use(record, is_owner=is_owner),
                self._party_contact_summary(record),
                "Ready" if not missing else "Missing " + ", ".join(missing),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, int(record.id))
                self.users_roles_table.setItem(row_index, column, item)
            if selected_party_id is not None and int(record.id) == int(selected_party_id):
                selected_row = row_index
        self.users_roles_table.resizeColumnsToContents()
        self.users_roles_table.selectRow(selected_row)
        self._refresh_users_roles_detail()

    def _selected_users_roles_party_id(self) -> int | None:
        selected_items = self.users_roles_table.selectedItems()
        if not selected_items:
            return None
        value = selected_items[0].data(Qt.ItemDataRole.UserRole)
        try:
            return int(value)
        except TypeError, ValueError:
            return None

    def open_selected_users_roles_party(self, item: QTableWidgetItem | None = None) -> None:
        if self._open_party_manager is None:
            QMessageBox.warning(self, "Party Manager", "Party manager is unavailable.")
            return
        party_id = self._users_roles_party_id_from_item(item)
        if party_id is None:
            party_id = self._selected_users_roles_party_id()
        if party_id is None:
            return
        self._open_party_manager(party_id)

    def _users_roles_party_id_from_item(self, item: QTableWidgetItem | None) -> int | None:
        if item is None:
            return None
        value = item.data(Qt.ItemDataRole.UserRole)
        try:
            return int(value)
        except TypeError, ValueError:
            return None

    def _refresh_users_roles_detail(self) -> None:
        conn = self._conn()
        party_id = self._selected_users_roles_party_id()
        if conn is None or party_id is None:
            return
        try:
            service = PartyService(conn)
            record = service.fetch_party(party_id)
            owner_party_id = SettingsReadService(conn).load_owner_party_id()
        except Exception as exc:
            self.users_roles_detail_output.setPlainText(
                "Unable to load selected Party Manager role.\n\n" f"Reason: {exc}"
            )
            return
        if record is None:
            self.users_roles_detail_output.setPlainText("Selected party no longer exists.")
            return
        self.users_roles_detail_output.setPlainText(
            self._format_party_role_settings(
                record,
                is_owner=owner_party_id is not None and int(record.id) == int(owner_party_id),
            )
        )

    def _party_display_label(self, record: PartyRecord) -> str:
        return (
            record.display_name
            or record.artist_name
            or record.company_name
            or record.legal_name
            or f"Party #{record.id}"
        )

    def _party_contact_summary(self, record: PartyRecord) -> str:
        return (
            record.email or record.alternative_email or record.contact_person or record.phone or "-"
        )

    def _party_accounting_role(self, record: PartyRecord, *, is_owner: bool) -> str:
        if is_owner:
            return "Current owner / invoice issuer"
        role_map = {
            "artist": "Royalty payee / artist payout recipient",
            "publisher": "Publishing payee / rights participant",
            "subpublisher": "Publishing payee / subpublisher",
            "producer": "Royalty payee / production participant",
            "remixer": "Royalty payee / remix participant",
            "licensee": "Customer / invoice recipient",
            "label": "Rights holder / label counterparty",
            "distributor": "DSP or distributor import source",
            "manager": "Representative / approval contact",
            "lawyer": "Legal representative / contract contact",
            "organization": "Organization counterparty",
            "person": "Person counterparty",
        }
        return role_map.get(str(record.party_type or "").strip().lower(), "General counterparty")

    def _party_workflow_use(self, record: PartyRecord, *, is_owner: bool) -> str:
        if is_owner:
            return "Seller identity, VAT output, invoice template company symbols"
        party_type = str(record.party_type or "").strip().lower()
        if party_type in {"artist", "publisher", "subpublisher", "producer", "remixer"}:
            return "Royalty calculations, statements, payables, artist payouts"
        if party_type in {"licensee", "label", "organization"}:
            return "Sales invoices, contracts, receivables, credit notes"
        if party_type == "distributor":
            return "DSP imports, sales/usage source matching, statement traceability"
        if party_type in {"manager", "lawyer"}:
            return "Contract review, billing contact, escalation and approval context"
        return "Contracts, rights, invoices, statements, and audit traceability"

    def _party_role_readiness_gaps(self, record: PartyRecord, *, is_owner: bool) -> list[str]:
        missing: list[str] = []
        if not self._party_display_label(record).strip():
            missing.append("name")
        party_type = str(record.party_type or "").strip().lower()
        if not (record.email or record.alternative_email or record.contact_person or record.phone):
            missing.append("contact")
        address_text = " ".join(
            str(part or "").strip()
            for part in (
                record.address_line1,
                record.street_name,
                record.street_number,
                record.postal_code,
                record.city,
                record.country,
            )
            if str(part or "").strip()
        )
        if is_owner:
            if not address_text:
                missing.append("billing address")
            if not record.vat_number:
                missing.append("VAT")
            if not record.bank_account_number:
                missing.append("bank")
        elif party_type in {"artist", "publisher", "subpublisher", "producer", "remixer"}:
            if not record.bank_account_number:
                missing.append("payout bank")
            if not (record.tax_id or record.vat_number or record.ipi_cae or record.pro_number):
                missing.append("tax/rights ID")
        elif party_type in {"licensee", "label", "organization"}:
            if not address_text:
                missing.append("billing address")
            if not (record.vat_number or record.tax_id):
                missing.append("VAT/tax ID")
        return missing

    def _format_party_role_settings(self, record: PartyRecord, *, is_owner: bool) -> str:
        def value(raw_value: object | None) -> str:
            return str(raw_value or "").strip() or "-"

        street_line = " ".join(
            part for part in (record.street_name, record.street_number) if str(part or "").strip()
        ).strip()
        address_lines = [
            line
            for line in (
                record.address_line1,
                record.address_line2,
                street_line,
                " ".join(
                    part for part in (record.postal_code, record.city) if str(part or "").strip()
                ).strip(),
                record.region,
                record.country,
            )
            if str(line or "").strip()
        ]
        missing = self._party_role_readiness_gaps(record, is_owner=is_owner)
        lines = [
            "Source: Party Manager -> Parties",
            f"Party ID: {record.id}",
            "",
            "Business role",
            f"Accounting role: {self._party_accounting_role(record, is_owner=is_owner)}",
            f"Workflow use: {self._party_workflow_use(record, is_owner=is_owner)}",
            "Permission model: not duplicated here; application login/approval permissions "
            "must remain in the existing app settings if/when that model exists.",
            "",
            "Identity",
            f"Display name: {value(self._party_display_label(record))}",
            f"Legal name: {value(record.legal_name)}",
            f"Artist name: {value(record.artist_name)}",
            f"Company name: {value(record.company_name)}",
            f"Party type: {_status_label(record.party_type)}",
            "",
            "Contact",
            f"Contact person: {value(record.contact_person)}",
            f"Email: {value(record.email)}",
            f"Alternative email: {value(record.alternative_email)}",
            f"Phone: {value(record.phone)}",
            f"Website: {value(record.website)}",
            "",
            "Billing / payout address",
        ]
        lines.extend(address_lines or ["-"])
        lines.extend(
            [
                "",
                "Registration and payout data",
                f"VAT number: {value(record.vat_number)}",
                f"Tax ID: {value(record.tax_id)}",
                f"Chamber of Commerce: {value(record.chamber_of_commerce_number)}",
                f"PRO affiliation: {value(record.pro_affiliation)}",
                f"PRO number: {value(record.pro_number)}",
                f"IPI/CAE: {value(record.ipi_cae)}",
                f"Bank account: {value(record.bank_account_number)}",
                "",
                "Readiness",
                (
                    "Ready for accounting workflows."
                    if not missing
                    else "Missing for accounting workflows: " + ", ".join(missing) + "."
                ),
            ]
        )
        if str(record.notes or "").strip():
            lines.extend(["", "Party notes", str(record.notes).strip()])
        return "\n".join(lines)

    def _refresh_vat_tax_settings(self) -> None:
        conn = self._conn()
        if conn is None:
            return
        try:
            owner_settings = SettingsReadService(conn).load_owner_party_settings()
            catalog_defaults = self._vat_catalog_default_counts(conn)
            invoice_usage = self._vat_invoice_line_usage(conn)
            snapshot_totals = self._vat_snapshot_totals(conn)
            vat_report_rows = InvoiceAccountingReportService(conn).vat_summary_report()
        except Exception as exc:
            self.vat_tax_detail_output.setPlainText(
                "Unable to load VAT and tax data from existing records.\n\n" f"Reason: {exc}"
            )
            _set_table_rows(
                self.vat_treatment_table,
                (
                    "Treatment",
                    "Rate",
                    "Country",
                    "Active presets",
                    "Invoice lines",
                    "Taxable",
                    "VAT",
                    "Gross",
                ),
                [],
                empty_message="Unable to load VAT treatments.",
            )
            return

        treatment_keys: set[tuple[str, int | None, str]] = {
            (treatment, None, "") for treatment in sorted(VAT_TREATMENTS)
        }
        treatment_keys.update(catalog_defaults)
        treatment_keys.update(invoice_usage)
        treatment_keys.update((key[0], key[1], "") for key in snapshot_totals)
        treatment_rows: list[tuple[object, ...]] = []
        for treatment, rate, country in sorted(
            treatment_keys,
            key=lambda key: (self._vat_treatment_label(key[0]), key[1] or -1, key[2]),
        ):
            catalog_count = catalog_defaults.get((treatment, rate, country), 0)
            invoice_count, taxable_minor, vat_minor, gross_minor = invoice_usage.get(
                (treatment, rate, country),
                (0, 0, 0, 0),
            )
            snapshot_key = (treatment, rate, "EUR")
            snapshot_taxable, snapshot_vat, snapshot_gross = snapshot_totals.get(
                snapshot_key,
                (0, 0, 0),
            )
            treatment_rows.append(
                (
                    self._vat_treatment_label(treatment),
                    self._vat_rate_label(rate),
                    country or "-",
                    catalog_count,
                    invoice_count,
                    format_money(taxable_minor or snapshot_taxable),
                    format_money(vat_minor or snapshot_vat),
                    format_money(gross_minor or snapshot_gross),
                )
            )
        _set_table_rows(
            self.vat_treatment_table,
            (
                "Treatment",
                "Rate",
                "Country",
                "Active presets",
                "Invoice lines",
                "Taxable",
                "VAT",
                "Gross",
            ),
            treatment_rows,
            empty_message="No VAT treatments are configured yet.",
        )

        activity_rows = [
            (
                self._vat_treatment_label(row.vat_treatment),
                self._vat_rate_label(row.vat_rate_basis_points),
                row.currency,
                format_money(row.vat_output_minor, currency=row.currency),
                format_money(row.vat_input_minor, currency=row.currency),
                format_money(row.vat_output_minor - row.vat_input_minor, currency=row.currency),
            )
            for row in vat_report_rows
        ]
        _set_table_rows(
            self.vat_activity_table,
            (
                "Treatment",
                "Rate",
                "Currency",
                "VAT Output",
                "VAT Input",
                "Net payable",
            ),
            activity_rows,
            empty_message="No VAT ledger entries.",
        )
        self.vat_tax_detail_output.setPlainText(
            self._format_vat_tax_settings(
                owner_settings=owner_settings,
                treatment_count=len(treatment_rows),
                active_preset_count=sum(catalog_defaults.values()),
                invoice_line_count=sum(row[0] for row in invoice_usage.values()),
                snapshot_totals=snapshot_totals,
                vat_output_minor=sum(row.vat_output_minor for row in vat_report_rows),
                vat_input_minor=sum(row.vat_input_minor for row in vat_report_rows),
            )
        )

    def _vat_catalog_default_counts(
        self,
        conn: sqlite3.Connection,
    ) -> dict[tuple[str, int | None, str], int]:
        rows = conn.execute("""
            SELECT
                default_vat_treatment,
                default_vat_rate_basis_points,
                COALESCE(vat_country_code, ''),
                COUNT(*)
            FROM InvoiceCatalogItems
            WHERE active=1
            GROUP BY default_vat_treatment, default_vat_rate_basis_points, COALESCE(vat_country_code, '')
            """).fetchall()
        return {
            (
                str(row[0] or "standard"),
                int(row[1]) if row[1] is not None else None,
                str(row[2] or ""),
            ): int(row[3] or 0)
            for row in rows
        }

    def _vat_invoice_line_usage(
        self,
        conn: sqlite3.Connection,
    ) -> dict[tuple[str, int | None, str], tuple[int, int, int, int]]:
        rows = conn.execute("""
            SELECT
                vat_treatment,
                vat_rate_basis_points,
                COALESCE(vat_country_code, ''),
                COUNT(*),
                COALESCE(SUM(net_amount_minor), 0),
                COALESCE(SUM(vat_amount_minor), 0),
                COALESCE(SUM(gross_amount_minor), 0)
            FROM InvoiceLineItems
            GROUP BY vat_treatment, vat_rate_basis_points, COALESCE(vat_country_code, '')
            """).fetchall()
        return {
            (
                str(row[0] or "standard"),
                int(row[1]) if row[1] is not None else None,
                str(row[2] or ""),
            ): (
                int(row[3] or 0),
                int(row[4] or 0),
                int(row[5] or 0),
                int(row[6] or 0),
            )
            for row in rows
        }

    def _vat_snapshot_totals(
        self,
        conn: sqlite3.Connection,
    ) -> dict[tuple[str, int | None, str], tuple[int, int, int]]:
        rows = conn.execute("""
            SELECT
                vat_treatment,
                vat_rate_basis_points,
                currency,
                COALESCE(SUM(taxable_amount_minor), 0),
                COALESCE(SUM(vat_amount_minor), 0),
                COALESCE(SUM(gross_amount_minor), 0)
            FROM InvoiceVatBreakdown
            GROUP BY vat_treatment, vat_rate_basis_points, currency
            """).fetchall()
        return {
            (
                str(row[0] or "standard"),
                int(row[1]) if row[1] is not None else None,
                str(row[2] or "EUR"),
            ): (
                int(row[3] or 0),
                int(row[4] or 0),
                int(row[5] or 0),
            )
            for row in rows
        }

    def _browse_integration_statement_file(self) -> None:
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Select DSP royalty statement",
            "",
            "Royalty Statements (*.csv *.xml *.xlsx *.xlsm);;CSV Files (*.csv);;XML Files (*.xml);;Excel Files (*.xlsx *.xlsm);;All Files (*)",
        )
        if not path:
            return
        self.integration_file_path_field.setText(path)
        self._refresh_integrations_settings()

    def _inspect_integrations_statement(self) -> None:
        self._refresh_integrations_settings()

    def _open_integrations_import_wizard(self) -> None:
        conn = self._conn()
        if conn is None:
            return
        source_path = Path(self.integration_file_path_field.text().strip())
        if not source_path.is_file():
            QMessageBox.warning(self, "DSP Import", "Select a valid DSP statement file first.")
            return
        try:
            service = RoyaltySourceImportService(conn)
            inspection = service.inspect_file(source_path)
            contract_id = self._selected_royalty_contract_id()
            dialog = RoyaltySourceImportDialog(
                inspection=inspection,
                preview_callback=lambda mapping: service.preview_import(
                    source_path,
                    mapping,
                    default_contract_id=contract_id,
                ),
                parent=self,
            )
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            report = service.apply_import(
                source_path,
                dialog.mapping(),
                default_contract_id=contract_id,
            )
        except Exception as exc:
            QMessageBox.warning(self, "DSP Import", f"Unable to import statement.\n\n{exc}")
            return
        QMessageBox.information(
            self,
            "DSP Import",
            "Royalty source events imported.\n\n" + "\n".join(report.summary_lines),
        )
        self.refresh_all()

    def _refresh_integrations_settings(self) -> None:
        conn = self._conn()
        if conn is None:
            return
        _set_table_rows(
            self.integration_profile_table,
            ("Integration", "Formats / Route", "Existing service", "Mapping", "Status"),
            (
                (
                    "DSP sales and usage statements",
                    "CSV, XML, XLSX",
                    "RoyaltySourceImportService",
                    "Manual + suggested field mapping",
                    "Ready",
                ),
                (
                    "Accounting export",
                    "Ledger-backed report exports",
                    "InvoiceAccountingReportService",
                    "Uses existing ledger entries",
                    "Available in Reports",
                ),
                (
                    "E-invoice delivery",
                    "Template Workspace artifacts",
                    "ContractTemplateExportService",
                    "Reuses linked template snapshots",
                    "Not configured",
                ),
                (
                    "Email delivery",
                    "Statement and invoice delivery",
                    "Existing notification/settings boundary",
                    "No duplicate mail system",
                    "Not configured",
                ),
            ),
            empty_message="No integration profiles configured.",
        )

        path_text = self.integration_file_path_field.text().strip()
        source_path = Path(path_text) if path_text else None
        if source_path is None or not source_path.is_file():
            _set_table_rows(
                self.integration_mapping_table,
                ("Source field", "Mapped target", "Sample value", "Notes"),
                (),
                empty_message="Choose a DSP statement file to inspect mapping.",
            )
            _set_table_rows(
                self.integration_preview_table,
                ("Row", "Status", "Period", "Source", "Description", "Currency", "Net", "Issues"),
                (),
                empty_message="No DSP preview loaded.",
            )
            self.integrations_detail_output.setPlainText(
                "\n".join(
                    (
                        "Source: existing RoyaltySourceImportService + RoyaltySourceImportDialog",
                        "",
                        "Supported formats: CSV, XML, XLSX.",
                        "Supported current DSP aggregate shape: date_id,total_gbp,store_name.",
                        "This screen previews imports only. Final commit still goes through the existing mapping dialog so fields can be manually matched or omitted.",
                        "",
                        "Select the real DSP export in the Statement field and click Inspect Statement.",
                    )
                )
            )
            return

        try:
            service = RoyaltySourceImportService(conn)
            inspection = service.inspect_file(source_path)
            mapping = dict(inspection.suggested_mapping)
            report = service.preview_import(
                source_path,
                mapping,
                default_contract_id=self._selected_royalty_contract_id(),
            )
        except Exception as exc:
            _set_table_rows(
                self.integration_mapping_table,
                ("Source field", "Mapped target", "Sample value", "Notes"),
                (),
                empty_message="Unable to inspect selected statement.",
            )
            _set_table_rows(
                self.integration_preview_table,
                ("Row", "Status", "Period", "Source", "Description", "Currency", "Net", "Issues"),
                (),
                empty_message="Unable to preview selected statement.",
            )
            self.integrations_detail_output.setPlainText(
                f"Unable to inspect DSP statement.\n\nFile: {source_path}\nReason: {exc}"
            )
            return

        mapping_rows = []
        for header in inspection.headers:
            sample = self._integration_sample_value(inspection.preview_rows, header)
            target = mapping.get(header, "")
            mapping_rows.append(
                (
                    header,
                    target or "Omitted by default",
                    sample,
                    self._integration_mapping_note(header, target),
                )
            )
        _set_table_rows(
            self.integration_mapping_table,
            ("Source field", "Mapped target", "Sample value", "Notes"),
            mapping_rows,
            empty_message="No source fields detected.",
        )

        preview_rows = [
            (
                row.row_number,
                _status_label(row.status),
                f"{_display_date(row.period_start)} - {_display_date(row.period_end)}".strip(" -"),
                row.source_type or "",
                row.description,
                row.currency,
                format_money(row.net_amount_minor, currency=row.currency),
                "; ".join(row.issues),
            )
            for row in report.preview_rows[:200]
        ]
        _set_table_rows(
            self.integration_preview_table,
            ("Row", "Status", "Period", "Source", "Description", "Currency", "Net", "Issues"),
            preview_rows,
            empty_message="No rows in selected statement.",
        )
        self.integrations_detail_output.setPlainText(
            self._format_integrations_preview_detail(
                source_path=source_path,
                headers=inspection.headers,
                mapping=mapping,
                warnings=inspection.warnings,
                report=report,
            )
        )

    @staticmethod
    def _integration_sample_value(rows: Sequence[dict[str, object]], header: str) -> str:
        for row in rows:
            value = row.get(header)
            text = str(value or "").strip()
            if text:
                return text
        return ""

    @staticmethod
    def _integration_mapping_note(header: str, target: str | None) -> str:
        clean_header = header.strip().lower()
        if target in {"gross_amount", "net_amount"} and clean_header.endswith(
            ("_gbp", "_eur", "_usd")
        ):
            return (
                f"Currency inferred from amount header: {clean_header.rsplit('_', 1)[-1].upper()}."
            )
        if target == "period_start":
            return "YYYY-MM periods become period start/end dates."
        if target == "source_type":
            return "DSP/store name is retained as source type."
        if not target:
            return "Not imported unless manually mapped in the import wizard."
        return "Mapped into royalty source-event metadata."

    def _format_integrations_preview_detail(
        self,
        *,
        source_path: Path,
        headers: Sequence[str],
        mapping: dict[str, str],
        warnings: Sequence[str],
        report: object,
    ) -> str:
        preview_rows = getattr(report, "preview_rows", ())
        ready_rows = [row for row in preview_rows if row.status == "ready"]
        totals_by_currency: dict[str, int] = {}
        for row in ready_rows:
            totals_by_currency[row.currency] = totals_by_currency.get(row.currency, 0) + int(
                row.net_amount_minor
            )
        micro_or_missing = any(
            "amount rounds below one minor unit; skipped" in row.issues
            or "gross or net amount is required" in row.issues
            for row in preview_rows
        )
        unmatched_context = any(
            row.contract_id is None
            and row.work_id is None
            and row.track_id is None
            and row.release_id is None
            for row in preview_rows
        )
        lines = [
            "Source: existing RoyaltySourceImportService + RoyaltySourceImportDialog",
            "",
            f"File: {source_path}",
            f"Headers: {', '.join(headers) if headers else '-'}",
            f"Suggested mappings: {len(mapping)}",
            *[f"- {source}: {target}" for source, target in mapping.items()],
            "",
            "Preview summary",
            *getattr(report, "summary_lines", []),
            "",
            "Rounded ready totals",
        ]
        if totals_by_currency:
            lines.extend(
                f"- {currency}: {format_money(amount, currency=currency)}"
                for currency, amount in sorted(totals_by_currency.items())
            )
        else:
            lines.append("- No rows are ready to import yet.")
        if warnings:
            lines.extend(["", "Reader warnings", *[f"- {warning}" for warning in warnings]])
        lines.extend(
            [
                "",
                "Matching policy",
                "Aggregate DSP statements can be imported as royalty source events, but contract/work/track matching remains unresolved until the provider supplies identifiers or a default contract is selected.",
                "The import wizard remains the commit gate and allows manual field matching or explicit omission.",
            ]
        )
        if unmatched_context:
            lines.append(
                "Current file has rows without contract/work/track identifiers; they will appear as unmatched imports until linked."
            )
        if micro_or_missing:
            lines.append(
                "Rows with micro amounts below one minor unit are skipped, not treated as import failures. Missing amount rows remain errors. Aggregate skipped micro rows before import if you need exact sub-cent DSP totals, because accounting stores money in integer minor units."
            )
        return "\n".join(lines)

    def _refresh_workflows_settings(self) -> None:
        conn = self._conn()
        if conn is None:
            return
        try:
            policy_rows = self._workflow_policy_rows()
            queue_rows = self._workflow_queue_rows(conn)
            command_rows = self._workflow_command_rows(conn)
            _set_table_rows(
                self.workflow_policy_table,
                (
                    "Workflow",
                    "Allowed states",
                    "Gate",
                    "Existing enforcement",
                    "Correction path",
                    "Status",
                ),
                policy_rows,
                empty_message="No workflow policies configured.",
            )
            _set_table_rows(
                self.workflow_queue_table,
                ("Area", "Open items", "Amount", "Priority", "Required action", "Source"),
                queue_rows,
                empty_message="No open workflow items.",
            )
            _set_table_rows(
                self.workflow_command_table,
                (
                    "Command",
                    "Source",
                    "Result",
                    "Ledger transaction",
                    "Status",
                    "Created",
                    "Completed",
                    "Error",
                ),
                command_rows,
                empty_message="No financial commands have been recorded.",
            )
            self.workflow_detail_output.setPlainText(
                self._format_workflows_settings(
                    policy_rows=policy_rows,
                    queue_rows=queue_rows,
                    command_rows=command_rows,
                )
            )
        except Exception as exc:
            self.workflow_detail_output.setPlainText(
                "Unable to load workflow controls from the existing accounting model.\n\n"
                f"Reason: {exc}"
            )
            _set_table_rows(
                self.workflow_policy_table,
                (
                    "Workflow",
                    "Allowed states",
                    "Gate",
                    "Existing enforcement",
                    "Correction path",
                    "Status",
                ),
                [],
                empty_message="Unable to load workflow policies.",
            )
            _set_table_rows(
                self.workflow_queue_table,
                ("Area", "Open items", "Amount", "Priority", "Required action", "Source"),
                [],
                empty_message="Unable to load workflow queue.",
            )

    def _workflow_policy_rows(self) -> list[tuple[object, ...]]:
        return [
            (
                "Invoice issue",
                "draft -> issued -> sent",
                "Issue requires party, due date, lines, VAT snapshots, and Code Registry number.",
                "InvoiceService + CodeRegistryService + AccountingTransactions",
                "Credit note, voiding, or reversal; issued invoices are not hard-deleted.",
                "Enforced",
            ),
            (
                "Invoice payment",
                "unpaid -> partially paid -> paid",
                "Payment status is derived from ledger-linked InvoicePayments.",
                "InvoicePaymentService + AccountingEntries",
                "Adjustment or reversal transaction; no silent balance edits.",
                "Enforced",
            ),
            (
                "Credit note",
                "issued correction document",
                "Requires issued source invoice and its own permanent registry number.",
                "CreditNoteService + CodeRegistryService",
                "Posts reversing ledger entries linked to the original invoice.",
                "Enforced",
            ),
            (
                "Royalty calculation",
                "calculated -> reviewed -> approved -> posted",
                "Draft calculations do not affect the ledger; posting creates artist payable.",
                "RoyaltyAccountingService + AccountingTransactions",
                "Correction calculation or reversal, never mutation of posted entries.",
                "Enforced",
            ),
            (
                "Royalty statement",
                "posted -> statement_generated -> paid",
                "Statement generation requires a posted calculation and unique statement number.",
                "RoyaltyAccountingService + CodeRegistryService",
                "Statement reversal/correction path keeps source calculation traceability.",
                "Enforced",
            ),
            (
                "Payment hold / dispute",
                "open -> held/disputed -> released/resolved",
                "Held or disputed items stay visible until payment or statement action clears them.",
                "Royalty statements, disputes table, payments, and audit/source links",
                "Release hold or create correction/reversal before payment.",
                "Operational",
            ),
            (
                "Period close",
                "open -> ready -> closed outside v1",
                "Close is blocked while invoices, statements, commands, or imports need action.",
                "Period close control tables + ledger-backed reports",
                "Resolve blockers before export or external accounting handoff.",
                "Control view",
            ),
        ]

    def _workflow_queue_rows(self, conn: sqlite3.Connection) -> list[tuple[object, ...]]:
        reports = InvoiceAccountingReportService(conn)
        outstanding = reports.outstanding_invoices()
        outstanding_amount = sum(int(row.receivable_balance_minor) for row in outstanding)
        overdue_rows = [row for row in outstanding if row.due_status == "overdue"]
        overdue_amount = sum(int(row.receivable_balance_minor) for row in overdue_rows)
        draft_invoices = self._scalar("SELECT COUNT(*) FROM Invoices WHERE document_status='draft'")
        issued_unposted = self._scalar("""
            SELECT COUNT(*)
            FROM Invoices
            WHERE document_status IN ('issued', 'sent')
              AND issued_ledger_transaction_id IS NULL
            """)
        pending_calculations = self._scalar("""
            SELECT COUNT(*)
            FROM RoyaltyCalculations
            WHERE status IN ('calculated', 'reviewed')
            """)
        approved_unposted_royalties = self._scalar("""
            SELECT COUNT(*)
            FROM RoyaltyCalculations
            WHERE status='approved'
              AND ledger_transaction_id IS NULL
            """)
        posted_without_statement = self._scalar("""
            SELECT COUNT(*)
            FROM RoyaltyCalculations c
            LEFT JOIN RoyaltyStatements s ON s.calculation_id=c.id
            WHERE c.status='posted'
              AND s.id IS NULL
            """)
        payable_row = conn.execute("""
            SELECT
                COUNT(*),
                COALESCE(SUM(c.net_payable_minor - COALESCE(paid.paid_minor, 0)), 0)
            FROM RoyaltyCalculations c
            LEFT JOIN (
                SELECT royalty_calculation_id, SUM(amount_minor) AS paid_minor
                FROM ArtistPayouts
                GROUP BY royalty_calculation_id
            ) paid ON paid.royalty_calculation_id=c.id
            WHERE c.status IN ('posted', 'statement_generated')
              AND (c.net_payable_minor - COALESCE(paid.paid_minor, 0)) > 0
            """).fetchone()
        unmatched_imports = self._scalar("""
            SELECT COUNT(*)
            FROM RoyaltySourceEvents
            WHERE contract_id IS NULL
              AND work_id IS NULL
              AND track_id IS NULL
              AND release_id IS NULL
            """)
        credit_notes_unposted = self._scalar("""
            SELECT COUNT(*)
            FROM CreditNotes
            WHERE ledger_transaction_id IS NULL
            """)
        started_commands = self._scalar("""
            SELECT COUNT(*)
            FROM FinancialCommandLog
            WHERE status != 'completed'
            """)
        queue_rows = [
            (
                "Draft invoices",
                draft_invoices,
                "-",
                "Normal",
                "Review, complete, issue, or cancel stale drafts.",
                "Invoices.document_status",
            ),
            (
                "Issued invoices missing posting",
                issued_unposted,
                "-",
                "High" if issued_unposted else "Clear",
                "Post ledger transaction or investigate interrupted issue command.",
                "Invoices.issued_ledger_transaction_id",
            ),
            (
                "Outstanding receivables",
                len(outstanding),
                format_money(outstanding_amount),
                "High" if overdue_rows else "Normal",
                "Record payment, credit note, or collection follow-up.",
                "InvoiceAccountingReportService",
            ),
            (
                "Overdue invoices",
                len(overdue_rows),
                format_money(overdue_amount),
                "High" if overdue_rows else "Clear",
                "Review due status and ledger-derived settlement.",
                "Invoices + ledger entries",
            ),
            (
                "Royalty calculations awaiting review",
                pending_calculations,
                "-",
                "Normal" if pending_calculations else "Clear",
                "Review calculation detail and approve only after source traceability checks.",
                "RoyaltyCalculations.status",
            ),
            (
                "Approved royalties not posted",
                approved_unposted_royalties,
                "-",
                "High" if approved_unposted_royalties else "Clear",
                "Post payable ledger transaction before statement/payment workflows.",
                "RoyaltyCalculations.ledger_transaction_id",
            ),
            (
                "Posted royalties without statements",
                posted_without_statement,
                "-",
                "Normal" if posted_without_statement else "Clear",
                "Generate immutable statement artifact with registry number.",
                "RoyaltyStatements",
            ),
            (
                "Royalty payables awaiting release",
                int(payable_row[0] or 0),
                format_money(int(payable_row[1] or 0)),
                "High" if int(payable_row[0] or 0) else "Clear",
                "Approve payout, hold payment, or record artist payout.",
                "RoyaltyCalculations + ArtistPayouts",
            ),
            (
                "Unmatched DSP/source imports",
                unmatched_imports,
                "-",
                "High" if unmatched_imports else "Clear",
                "Map provider fields to contract/work/track context before calculation.",
                "RoyaltySourceEvents",
            ),
            (
                "Credit notes missing posting",
                credit_notes_unposted,
                "-",
                "High" if credit_notes_unposted else "Clear",
                "Investigate credit-note command; posted corrections must have ledger links.",
                "CreditNotes.ledger_transaction_id",
            ),
            (
                "Started financial commands",
                started_commands,
                "-",
                "High" if started_commands else "Clear",
                "Retry with the same idempotency key or inspect command error state.",
                "FinancialCommandLog",
            ),
        ]
        return queue_rows

    def _workflow_command_rows(self, conn: sqlite3.Connection) -> list[tuple[object, ...]]:
        rows = conn.execute("""
            SELECT
                command_type,
                COALESCE(source_type, ''),
                COALESCE(source_id, ''),
                COALESCE(result_type, ''),
                COALESCE(result_id, ''),
                ledger_transaction_id,
                status,
                created_at,
                completed_at,
                COALESCE(error_message, '')
            FROM FinancialCommandLog
            ORDER BY created_at DESC, command_key DESC
            LIMIT 80
            """).fetchall()
        return [
            (
                _status_label(row[0]),
                f"{row[1]} {row[2]}".strip() or "-",
                f"{row[3]} {row[4]}".strip() or "-",
                row[5] or "-",
                _status_label(row[6]),
                _display_date(row[7]),
                _display_date(row[8]),
                row[9],
            )
            for row in rows
        ]

    def _format_workflows_settings(
        self,
        *,
        policy_rows: Sequence[Sequence[object]],
        queue_rows: Sequence[Sequence[object]],
        command_rows: Sequence[Sequence[object]],
    ) -> str:
        high_priority = sum(1 for row in queue_rows if str(row[3]).lower() == "high")
        open_items = sum(int(row[1] or 0) for row in queue_rows if str(row[1]).isdigit())
        started_commands = sum(
            1 for row in command_rows if str(row[4]).strip().lower() != "completed"
        )
        lines = [
            "Source: existing invoice, royalty, command-log, and ledger services",
            "",
            "Workflow principles",
            "This page is a control surface over existing accounting workflows; it does not create a duplicate permissions or workflow engine.",
            "Financial commands must be idempotent and must return the original result when retried with the same command key.",
            "Final document numbers come from Code Registry only when the financial workflow reaches the issue/generation step.",
            "Posted ledger transactions and entries are immutable; corrections use credit notes, reversals, or adjustment transactions.",
            "Payment, due, and outstanding states are derived from ledger-linked business records, not manually edited status text.",
            "",
            "Approval gates",
        ]
        for row in policy_rows:
            lines.append(f"- {row[0]}: {row[2]}")
        lines.extend(
            [
                "",
                "Current controls",
                f"Open workflow rows: {open_items}",
                f"High-priority blockers: {high_priority}",
                f"Recent command-log rows: {len(command_rows)}",
                f"Commands not completed: {started_commands}",
                (
                    "Workflow queue is clear for the visible controls."
                    if high_priority == 0 and started_commands == 0
                    else "Resolve high-priority blockers before period close or accounting export."
                ),
                "",
                "Period close rule",
                "A period should not be closed while invoices are unposted, statements are unposted, DSP imports are unmatched, started financial commands exist, or credit notes are missing ledger links.",
                "",
                "Role source",
                "Actors, payees, owners, distributors, and billing contacts remain Party Manager records. Use the Users & Roles settings page to inspect workflow readiness from those canonical party records.",
            ]
        )
        return "\n".join(lines)

    def _format_vat_tax_settings(
        self,
        *,
        owner_settings: OwnerPartySettings,
        treatment_count: int,
        active_preset_count: int,
        invoice_line_count: int,
        snapshot_totals: dict[tuple[str, int | None, str], tuple[int, int, int]],
        vat_output_minor: int,
        vat_input_minor: int,
    ) -> str:
        owner_label = (
            owner_settings.company_name
            or owner_settings.display_name
            or owner_settings.legal_name
            or "Current owner party"
        )
        snapshot_taxable = sum(values[0] for values in snapshot_totals.values())
        snapshot_vat = sum(values[1] for values in snapshot_totals.values())
        snapshot_gross = sum(values[2] for values in snapshot_totals.values())
        missing: list[str] = []
        if owner_settings.party_id is None:
            missing.append("current owner party")
        if not owner_settings.vat_number:
            missing.append("owner VAT number")
        if not (owner_settings.country or owner_settings.city):
            missing.append("owner billing country/address")
        lines = [
            "Source: Party Manager + Invoice VAT snapshots + Accounting ledger",
            "",
            "Owner VAT identity",
            f"Owner: {owner_label}",
            f"Owner party ID: {owner_settings.party_id or '-'}",
            f"Seller VAT number: {owner_settings.vat_number or '-'}",
            f"Tax ID: {owner_settings.tax_id or '-'}",
            f"Country: {owner_settings.country or '-'}",
            "",
            "Supported VAT treatments",
            ", ".join(self._vat_treatment_label(treatment) for treatment in sorted(VAT_TREATMENTS)),
            "",
            "Accounting rules",
            "VAT is calculated per invoice line using integer minor units.",
            "Invoice VAT total is the sum of rounded line VAT amounts.",
            "Invoice VAT breakdowns are immutable snapshots after issue.",
            "VAT reports come from VAT ledger accounts 2100 Output and 1200 Input.",
            "Reverse-charge, exempt, zero-rated, and out-of-scope lines keep treatment labels even when VAT amount is zero.",
            "",
            "Current data",
            f"Treatment/rate rows shown: {treatment_count}",
            f"Active billing presets with VAT defaults: {active_preset_count}",
            f"Invoice lines with VAT snapshots: {invoice_line_count}",
            f"Snapshot taxable total: {format_money(snapshot_taxable)}",
            f"Snapshot VAT total: {format_money(snapshot_vat)}",
            f"Snapshot gross total: {format_money(snapshot_gross)}",
            f"Ledger VAT output: {format_money(vat_output_minor)}",
            f"Ledger VAT input: {format_money(vat_input_minor)}",
            f"Ledger net VAT payable: {format_money(vat_output_minor - vat_input_minor)}",
            "",
            "Readiness",
            (
                "Ready for VAT-aware invoice output."
                if not missing
                else "Missing for VAT-aware invoice output: " + ", ".join(missing) + "."
            ),
        ]
        return "\n".join(lines)

    def _vat_treatment_label(self, treatment: object | None) -> str:
        clean = str(treatment or "standard").strip().replace("_", " ")
        return clean.title() if clean else "Standard"

    def _vat_rate_label(self, basis_points: object | None) -> str:
        if basis_points is None:
            return "Default / unset"
        return f"{int(basis_points) / 100:.2f}%"

    def _refresh_invoice_numbering_settings(self) -> None:
        conn = self._conn()
        if conn is None:
            return
        registry_categories = (
            (
                BUILTIN_CATEGORY_INVOICE_NUMBER,
                "Invoice Number",
                "Sales invoices",
                "Assigned only when a draft invoice is issued.",
            ),
            (
                BUILTIN_CATEGORY_CREDIT_NOTE_NUMBER,
                "Credit Note Number",
                "Credit notes",
                "Assigned when a credit note is created against an issued invoice.",
            ),
            (
                BUILTIN_CATEGORY_LEDGER_TRANSACTION_NUMBER,
                "Ledger Transaction Number",
                "Posted ledger transactions",
                "Assigned by the ledger posting service for auditable financial entries.",
            ),
            (
                BUILTIN_CATEGORY_ROYALTY_STATEMENT_NUMBER,
                "Royalty Statement Number",
                "Royalty statements",
                "Assigned when a royalty statement artifact is generated.",
            ),
        )
        try:
            registry = CodeRegistryService(conn)
            year = datetime.now().year % 100
            sequence_rows: list[tuple[object, ...]] = []
            sequence_details: list[tuple[str, str, str, str, int, int, str, str]] = []
            for system_key, label, workflow, rule in registry_categories:
                category = registry.fetch_category_by_system_key(system_key)
                if category is None:
                    sequence_rows.append(
                        (label, "-", "-", "Missing", "0", "-", "-", "Registry category missing")
                    )
                    sequence_details.append(
                        (label, system_key, "-", "-", 0, 0, "missing", "Registry category missing")
                    )
                    continue
                total_entries, last_current_year, last_value = self._numbering_entry_stats(
                    conn,
                    category_id=category.id,
                    sequence_year=year,
                )
                reason = registry.generation_unavailable_reason(system_key=system_key)
                next_preview = self._numbering_next_preview(
                    prefix=category.prefix,
                    last_sequence=last_current_year,
                    sequence_year=year,
                    unavailable_reason=reason,
                )
                status = "Ready" if reason is None else "Needs setup"
                sequence_rows.append(
                    (
                        label,
                        category.prefix or "-",
                        _status_label(category.generation_strategy),
                        "Active" if category.active_flag else "Inactive",
                        total_entries,
                        last_value or "-",
                        next_preview,
                        status,
                    )
                )
                sequence_details.append(
                    (
                        label,
                        system_key,
                        category.prefix or "-",
                        workflow,
                        total_entries,
                        last_current_year,
                        status,
                        reason or rule,
                    )
                )
            _set_table_rows(
                self.numbering_sequence_table,
                (
                    "Category",
                    "Prefix",
                    "Strategy",
                    "Active",
                    "Entries",
                    "Last value",
                    "Next preview",
                    "Status",
                ),
                sequence_rows,
                empty_message="No code-registry numbering categories found.",
            )
            usage_rows = self._numbering_usage_rows(conn)
            _set_table_rows(
                self.numbering_usage_table,
                (
                    "Source",
                    "Numbered",
                    "Draft/unissued",
                    "Missing link",
                    "Last date",
                    "Guard",
                ),
                usage_rows,
                empty_message="No numbered business records found.",
            )
            self.invoice_numbering_detail_output.setPlainText(
                self._format_invoice_numbering_settings(
                    sequence_details=sequence_details,
                    usage_rows=usage_rows,
                )
            )
        except Exception as exc:
            self.invoice_numbering_detail_output.setPlainText(
                "Unable to load invoice numbering data from Code Registry.\n\n" f"Reason: {exc}"
            )
            _set_table_rows(
                self.numbering_sequence_table,
                (
                    "Category",
                    "Prefix",
                    "Strategy",
                    "Active",
                    "Entries",
                    "Last value",
                    "Next preview",
                    "Status",
                ),
                [],
                empty_message="Unable to load code-registry sequences.",
            )

    def _numbering_entry_stats(
        self,
        conn: sqlite3.Connection,
        *,
        category_id: int,
        sequence_year: int,
    ) -> tuple[int, int, str | None]:
        row = conn.execute(
            """
            SELECT
                COUNT(*),
                COALESCE(MAX(CASE WHEN sequence_year=? THEN sequence_number END), 0)
            FROM CodeRegistryEntries
            WHERE category_id=?
            """,
            (int(sequence_year), int(category_id)),
        ).fetchone()
        latest = conn.execute(
            """
            SELECT value
            FROM CodeRegistryEntries
            WHERE category_id=?
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (int(category_id),),
        ).fetchone()
        return (
            int(row[0] or 0),
            int(row[1] or 0),
            str(latest[0]) if latest and latest[0] is not None else None,
        )

    def _numbering_next_preview(
        self,
        *,
        prefix: object | None,
        last_sequence: int,
        sequence_year: int,
        unavailable_reason: str | None,
    ) -> str:
        if unavailable_reason:
            return unavailable_reason
        clean_prefix = CodeRegistryService.normalize_prefix(str(prefix or ""))
        if not clean_prefix:
            return "Prefix required"
        return f"{clean_prefix}{int(sequence_year):02d}{int(last_sequence) + 1:04d}"

    def _numbering_usage_rows(self, conn: sqlite3.Connection) -> list[tuple[object, ...]]:
        invoice_row = conn.execute("""
            SELECT
                SUM(CASE WHEN invoice_number IS NOT NULL THEN 1 ELSE 0 END),
                SUM(CASE WHEN invoice_number IS NULL THEN 1 ELSE 0 END),
                SUM(CASE WHEN invoice_number IS NOT NULL AND invoice_registry_entry_id IS NULL THEN 1 ELSE 0 END),
                MAX(COALESCE(issue_date, created_at))
            FROM Invoices
            """).fetchone()
        credit_row = conn.execute("""
            SELECT
                COUNT(*),
                0,
                SUM(CASE WHEN credit_note_number IS NOT NULL AND credit_note_registry_entry_id IS NULL THEN 1 ELSE 0 END),
                MAX(issue_date)
            FROM CreditNotes
            """).fetchone()
        ledger_row = conn.execute("""
            SELECT
                SUM(CASE WHEN transaction_number IS NOT NULL THEN 1 ELSE 0 END),
                SUM(CASE WHEN transaction_number IS NULL THEN 1 ELSE 0 END),
                SUM(CASE WHEN transaction_number IS NOT NULL AND registry_entry_id IS NULL THEN 1 ELSE 0 END),
                MAX(posted_at)
            FROM AccountingTransactions
            """).fetchone()
        statement_row = conn.execute("""
            SELECT
                SUM(CASE WHEN statement_number IS NOT NULL THEN 1 ELSE 0 END),
                SUM(CASE WHEN statement_number IS NULL THEN 1 ELSE 0 END),
                SUM(CASE WHEN statement_number IS NOT NULL AND statement_registry_entry_id IS NULL THEN 1 ELSE 0 END),
                MAX(issue_date)
            FROM RoyaltyStatements
            """).fetchone()
        return [
            (
                "Invoices",
                int(invoice_row[0] or 0),
                int(invoice_row[1] or 0),
                int(invoice_row[2] or 0),
                _display_date(invoice_row[3]),
                "Issued invoice numbers are immutable; issued invoices cannot be hard-deleted.",
            ),
            (
                "Credit notes",
                int(credit_row[0] or 0),
                int(credit_row[1] or 0),
                int(credit_row[2] or 0),
                _display_date(credit_row[3]),
                "Credit note numbers are immutable; credit notes cannot be hard-deleted.",
            ),
            (
                "Ledger transactions",
                int(ledger_row[0] or 0),
                int(ledger_row[1] or 0),
                int(ledger_row[2] or 0),
                _display_date(ledger_row[3]),
                "Posted accounting transactions and entries are append-only.",
            ),
            (
                "Royalty statements",
                int(statement_row[0] or 0),
                int(statement_row[1] or 0),
                int(statement_row[2] or 0),
                _display_date(statement_row[3]),
                "Statement numbers are permanent document identifiers.",
            ),
        ]

    def _format_invoice_numbering_settings(
        self,
        *,
        sequence_details: Sequence[tuple[str, str, str, str, int, int, str, str]],
        usage_rows: Sequence[Sequence[object]],
    ) -> str:
        missing_links = sum(int(row[3] or 0) for row in usage_rows)
        draft_unissued = sum(int(row[2] or 0) for row in usage_rows)
        ready_count = sum(1 for detail in sequence_details if detail[6] == "Ready")
        lines = [
            "Source: Code Registry Workspace + accounting document tables",
            "",
            "Numbering policy",
            "Draft invoices do not receive final invoice numbers.",
            "Final invoice numbers are assigned only when a draft invoice is issued.",
            "Credit notes, ledger transactions, and royalty statements use their own registry categories.",
            "Next preview values shown here are not reservations and do not create CodeRegistryEntries.",
            "Actual issuance uses the code registry service inside immediate database transactions.",
            "",
            "Registry categories",
        ]
        for (
            label,
            system_key,
            prefix,
            workflow,
            total_entries,
            last_sequence,
            status,
            note,
        ) in sequence_details:
            lines.extend(
                [
                    f"- {label} ({system_key})",
                    f"  Prefix: {prefix}",
                    f"  Workflow: {workflow}",
                    f"  Registry entries: {total_entries}",
                    f"  Current-year last sequence: {last_sequence}",
                    f"  Status: {status}",
                    f"  Note: {note}",
                ]
            )
        lines.extend(
            [
                "",
                "Reconciliation",
                f"Ready registry categories: {ready_count}/{len(sequence_details)}",
                f"Draft/unissued records without final numbers: {draft_unissued}",
                f"Numbered records missing registry links: {missing_links}",
                (
                    "Registry links reconcile."
                    if missing_links == 0
                    else "Investigate numbered records without registry links before relying on exports."
                ),
                "",
                "Immutability and correction rules",
                "Issued invoice numbers are unique, permanent, auditable, and non-reusable.",
                "Issued invoices are corrected through credit notes, reversals, or adjustments, not silent edits.",
                "Credit note numbers are unique, permanent, and linked back to the original invoice.",
                "Posted ledger transactions are append-only and must remain balanced per currency.",
                "Royalty statement numbers are generated once per statement artifact and should not be reused.",
            ]
        )
        return "\n".join(lines)

    def _refresh_parties(self) -> None:
        conn = self._conn()
        if conn is None:
            return
        current = self.party_combo.currentData()
        self.party_combo.clear()
        rows = conn.execute("""
            SELECT id, COALESCE(display_name, legal_name, printf('Party %d', id))
            FROM Parties
            ORDER BY COALESCE(display_name, legal_name), id
            """).fetchall()
        for row in rows:
            self.party_combo.addItem(f"{row[1]} ({row[0]})", int(row[0]))
        if current is not None:
            index = self.party_combo.findData(current)
            if index >= 0:
                self.party_combo.setCurrentIndex(index)

    @staticmethod
    def _populate_currency_combo(combo: QComboBox) -> None:
        current = combo.currentData() or DEFAULT_CURRENCY
        combo.blockSignals(True)
        combo.clear()
        for code in ISO_4217_CURRENCY_CODES:
            combo.addItem(code, code)
        index = combo.findData(current)
        combo.setCurrentIndex(index if index >= 0 else combo.findData(DEFAULT_CURRENCY))
        combo.blockSignals(False)

    @staticmethod
    def _select_combo_data(combo: QComboBox, value: object | None) -> None:
        index = combo.findData(value)
        combo.setCurrentIndex(index if index >= 0 else combo.findData(DEFAULT_CURRENCY))

    @staticmethod
    def _select_combo_text(combo: QComboBox, value: object | None) -> None:
        text = str(value or "").strip()
        index = combo.findData(text)
        if index < 0:
            index = combo.findText(text)
        if index >= 0:
            combo.setCurrentIndex(index)
        elif combo.isEditable():
            combo.setEditText(text)

    @staticmethod
    def _select_required_combo_data(combo: QComboBox, value: object | None) -> None:
        index = combo.findData(value)
        combo.setCurrentIndex(index if index >= 0 else 0)

    def _apply_catalog_currency_from_country(self) -> None:
        inferred = currency_for_country(self.catalog_vat_country_field.text())
        if inferred is not None:
            self._select_combo_data(self.catalog_currency_combo, inferred)

    def _catalog_category_value(self) -> str | None:
        return _clean_text(self.catalog_category_combo.currentText())

    def _catalog_account_code_value(self) -> str | None:
        data = self.catalog_account_combo.currentData()
        if data is not None:
            return _clean_text(data)
        text = _clean_text(self.catalog_account_combo.currentText())
        if text and " - " in text:
            return _clean_text(text.split(" - ", 1)[0])
        return text

    def _refresh_catalog_category_options(self) -> None:
        conn = self._conn()
        if conn is None:
            return
        current = self._catalog_category_value()
        categories = InvoiceCatalogCategoryService(conn).list_categories(active_only=False)
        legacy_rows = conn.execute("""
            SELECT DISTINCT category
            FROM InvoiceCatalogItems
            WHERE category IS NOT NULL AND trim(category) != ''
            ORDER BY category COLLATE NOCASE
            """).fetchall()
        seen: set[str] = set()
        self.catalog_category_combo.blockSignals(True)
        self.catalog_category_combo.clear()
        self.catalog_category_combo.addItem("Choose category...", "")
        for category in categories:
            seen.add(category.name.casefold())
            label = category.name if category.active else f"{category.name} (inactive)"
            self.catalog_category_combo.addItem(label, category.name)
        for row in legacy_rows:
            name = str(row[0] or "").strip()
            if name and name.casefold() not in seen:
                self.catalog_category_combo.addItem(name, name)
                seen.add(name.casefold())
        self.catalog_category_combo.blockSignals(False)
        if current:
            self._select_combo_text(self.catalog_category_combo, current)
        elif self.catalog_category_combo.isEditable():
            self.catalog_category_combo.setEditText("")

    def _refresh_catalog_account_options(self) -> None:
        conn = self._conn()
        if conn is None:
            return
        current = self._catalog_account_code_value()
        accounts = AccountingAccountService(conn).list_accounts(active_only=False)
        self.catalog_account_combo.blockSignals(True)
        self.catalog_account_combo.clear()
        self.catalog_account_combo.addItem("Choose ledger account...", None)
        for account in accounts:
            label = f"{account.code} - {account.name}"
            if not account.active:
                label = f"{label} (inactive)"
            self.catalog_account_combo.addItem(label, account.code)
        self.catalog_account_combo.blockSignals(False)
        preferred = current or "4100"
        index = self.catalog_account_combo.findData(preferred)
        if index >= 0:
            self.catalog_account_combo.setCurrentIndex(index)

    def _refresh_invoice_catalog(self) -> None:
        conn = self._conn()
        if conn is None:
            return
        self._refresh_catalog_category_options()
        self._refresh_catalog_account_options()
        current_combo = self.catalog_item_combo.currentData()
        current_row = self._selected_catalog_item_id()
        items = InvoiceCatalogService(conn).list_items(active_only=False)
        self.catalog_item_combo.blockSignals(True)
        self.catalog_item_combo.clear()
        self.catalog_item_combo.addItem("Choose preset...", None)
        active_items = [item for item in items if item.active]
        for item in active_items:
            quantity = format_quantity(
                Quantity(item.default_quantity_value, item.default_quantity_scale)
            )
            self.catalog_item_combo.addItem(
                f"{item.name} - {quantity} x "
                f"{format_money(item.default_unit_price_minor, currency=item.currency)}",
                int(item.id),
            )
        self.catalog_item_combo.blockSignals(False)
        if current_combo is not None:
            index = self.catalog_item_combo.findData(current_combo)
            if index >= 0:
                self.catalog_item_combo.setCurrentIndex(index)
        self.catalog_table.setRowCount(len(items))
        for row_index, item in enumerate(items):
            quantity = format_quantity(
                Quantity(item.default_quantity_value, item.default_quantity_scale)
            )
            values = (
                str(item.id),
                item.name,
                item.category or "",
                quantity,
                item.currency,
                format_money(item.default_unit_price_minor, currency=item.currency),
                f"{item.default_vat_rate_basis_points / 100:.2f}%",
                item.default_account_code or "",
                "active" if item.active else "inactive",
            )
            for col_index, value in enumerate(values):
                cell = QTableWidgetItem(value)
                if col_index == 0:
                    cell.setData(Qt.ItemDataRole.UserRole, int(item.id))
                self.catalog_table.setItem(row_index, col_index, cell)
        self.catalog_table.resizeColumnsToContents()
        if current_row is not None:
            for row in range(self.catalog_table.rowCount()):
                selected_cell = self.catalog_table.item(row, 0)
                if selected_cell is not None and int(selected_cell.text()) == int(current_row):
                    self.catalog_table.selectRow(row)
                    break

    def _selected_catalog_category_id(self) -> int | None:
        selected = self.catalog_category_table.selectedItems()
        if not selected:
            return None
        item = self.catalog_category_table.item(selected[0].row(), 0)
        if item is None:
            return None
        value = item.data(Qt.ItemDataRole.UserRole)
        return int(value) if value is not None else int(item.text())

    def _selected_ledger_account_id(self) -> int | None:
        selected = self.account_admin_table.selectedItems()
        if not selected:
            return None
        item = self.account_admin_table.item(selected[0].row(), 0)
        if item is None:
            return None
        value = item.data(Qt.ItemDataRole.UserRole)
        return int(value) if value is not None else int(item.text())

    def _refresh_catalog_category_settings(self) -> None:
        conn = self._conn()
        if conn is None:
            return
        selected_id = self._selected_catalog_category_id()
        categories = InvoiceCatalogCategoryService(conn).list_categories(active_only=False)
        self.catalog_category_table.setRowCount(len(categories))
        for row_index, category in enumerate(categories):
            values = (
                str(category.id),
                category.name,
                "active" if category.active else "inactive",
                _display_date(category.created_at),
                _display_date(category.updated_at),
            )
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                if column == 0:
                    cell.setData(Qt.ItemDataRole.UserRole, int(category.id))
                self.catalog_category_table.setItem(row_index, column, cell)
        self.catalog_category_table.resizeColumnsToContents()
        if selected_id is not None:
            for row in range(self.catalog_category_table.rowCount()):
                item = self.catalog_category_table.item(row, 0)
                if item is not None and item.data(Qt.ItemDataRole.UserRole) == selected_id:
                    self.catalog_category_table.selectRow(row)
                    break

    def _refresh_account_admin_settings(self) -> None:
        conn = self._conn()
        if conn is None:
            return
        selected_id = self._selected_ledger_account_id()
        accounts = AccountingAccountService(conn).list_accounts(active_only=False)
        self.account_admin_table.setRowCount(len(accounts))
        for row_index, account in enumerate(accounts):
            values = (
                str(account.id),
                account.code,
                account.name,
                _status_label(account.account_type),
                _status_label(account.normal_balance),
                "yes" if account.system_flag else "no",
                "active" if account.active else "inactive",
            )
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                if column == 0:
                    cell.setData(Qt.ItemDataRole.UserRole, int(account.id))
                self.account_admin_table.setItem(row_index, column, cell)
        self.account_admin_table.resizeColumnsToContents()
        if selected_id is not None:
            for row in range(self.account_admin_table.rowCount()):
                item = self.account_admin_table.item(row, 0)
                if item is not None and item.data(Qt.ItemDataRole.UserRole) == selected_id:
                    self.account_admin_table.selectRow(row)
                    break

    def _populate_catalog_category_form_from_selection(self) -> None:
        conn = self._conn()
        category_id = self._selected_catalog_category_id()
        if conn is None or category_id is None:
            return
        category = InvoiceCatalogCategoryService(conn).fetch_category(category_id)
        if category is None:
            return
        self.catalog_category_name_field.setText(category.name)
        self.catalog_category_active_check.setChecked(bool(category.active))

    def _populate_ledger_account_form_from_selection(self) -> None:
        conn = self._conn()
        account_id = self._selected_ledger_account_id()
        if conn is None or account_id is None:
            return
        account = AccountingAccountService(conn).fetch_account(account_id)
        if account is None:
            return
        self.account_code_field.setText(account.code)
        self.account_name_field.setText(account.name)
        self._select_required_combo_data(self.account_type_combo, account.account_type)
        self._select_required_combo_data(self.account_normal_balance_combo, account.normal_balance)
        self.account_active_check.setChecked(bool(account.active))

    def _clear_catalog_category_form(self) -> None:
        self.catalog_category_table.clearSelection()
        self.catalog_category_name_field.clear()
        self.catalog_category_active_check.setChecked(True)

    def _clear_ledger_account_form(self) -> None:
        self.account_admin_table.clearSelection()
        self.account_code_field.clear()
        self.account_name_field.clear()
        self._select_required_combo_data(self.account_type_combo, "income")
        self._select_required_combo_data(self.account_normal_balance_combo, "credit")
        self.account_active_check.setChecked(True)

    def _populate_catalog_form_from_selection(self) -> None:
        conn = self._conn()
        item_id = self._selected_catalog_item_id()
        if conn is None or item_id is None:
            return
        item = InvoiceCatalogService(conn).fetch_item(item_id)
        if item is None:
            return
        self.catalog_name_field.setText(item.name)
        self.catalog_description_field.setText(item.description or "")
        self.catalog_quantity_field.setText(
            format_quantity(Quantity(item.default_quantity_value, item.default_quantity_scale))
        )
        self.catalog_unit_price_field.setText(
            format_money(item.default_unit_price_minor, currency=item.currency).split(" ", 1)[1]
        )
        self._select_combo_data(self.catalog_currency_combo, item.currency)
        self.catalog_vat_rate_field.setText(str(item.default_vat_rate_basis_points))
        self.catalog_vat_country_field.setText(item.vat_country_code or "")
        self._select_combo_text(self.catalog_category_combo, item.category)
        account_index = self.catalog_account_combo.findData(item.default_account_code)
        if account_index >= 0:
            self.catalog_account_combo.setCurrentIndex(account_index)
        else:
            self.catalog_account_combo.setCurrentIndex(0)
        self.catalog_active_check.setChecked(bool(item.active))

    def _populate_line_fields_from_catalog_combo(self) -> None:
        conn = self._conn()
        item_id = self.catalog_item_combo.currentData()
        if conn is None or item_id is None:
            return
        item = InvoiceCatalogService(conn).fetch_item(int(item_id))
        if item is None:
            return
        self.description_field.setText(item.description or item.name)
        self.quantity_field.setText(
            format_quantity(Quantity(item.default_quantity_value, item.default_quantity_scale))
        )
        self.unit_price_field.setText(
            format_money(item.default_unit_price_minor, currency=item.currency).split(" ", 1)[1]
        )
        self.vat_rate_field.setText(str(item.default_vat_rate_basis_points))

    def _clear_catalog_form(self) -> None:
        self.catalog_table.clearSelection()
        for field in (
            self.catalog_name_field,
            self.catalog_description_field,
            self.catalog_quantity_field,
            self.catalog_unit_price_field,
            self.catalog_vat_rate_field,
            self.catalog_vat_country_field,
        ):
            field.clear()
        self.catalog_category_combo.setEditText("")
        self.catalog_quantity_field.setText("1")
        self._select_combo_data(self.catalog_currency_combo, DEFAULT_CURRENCY)
        default_account_index = self.catalog_account_combo.findData("4100")
        self.catalog_account_combo.setCurrentIndex(
            default_account_index if default_account_index >= 0 else 0
        )
        self.catalog_vat_rate_field.setText("2100")
        self.catalog_active_check.setChecked(True)

    def _refresh_royalty_contracts(self) -> None:
        conn = self._conn()
        if conn is None:
            return
        current = self.royalty_contract_combo.currentData()
        self.royalty_contract_combo.blockSignals(True)
        self.royalty_contract_combo.clear()
        rows = conn.execute("""
            SELECT id, title, status
            FROM Contracts
            ORDER BY
                CASE status WHEN 'active' THEN 0 ELSE 1 END,
                COALESCE(title, ''),
                id
            """).fetchall()
        for row in rows:
            title = str(row[1] or f"Contract {row[0]}")
            status = str(row[2] or "unknown")
            self.royalty_contract_combo.addItem(f"{title} ({status}, #{row[0]})", int(row[0]))
        if current is not None:
            index = self.royalty_contract_combo.findData(current)
            if index >= 0:
                self.royalty_contract_combo.setCurrentIndex(index)
        self.royalty_contract_combo.blockSignals(False)

    def _refresh_royalty_parties(self) -> None:
        conn = self._conn()
        if conn is None:
            return
        current = self.royalty_party_combo.currentData()
        self.royalty_party_combo.clear()
        term_current = self.royalty_term_party_combo.currentData()
        self.royalty_term_party_combo.clear()
        artist_rows = conn.execute("""
            SELECT id, COALESCE(artist_name, display_name, legal_name, printf('Party %d', id))
            FROM Parties
            WHERE party_type='artist' OR artist_name IS NOT NULL
            ORDER BY COALESCE(artist_name, display_name, legal_name), id
            """).fetchall()
        all_rows = conn.execute("""
            SELECT id, COALESCE(display_name, legal_name, artist_name, printf('Party %d', id))
            FROM Parties
            ORDER BY COALESCE(display_name, legal_name, artist_name), id
            """).fetchall()
        if not artist_rows:
            artist_rows = conn.execute("""
                SELECT id, COALESCE(display_name, legal_name, printf('Party %d', id))
                FROM Parties
                ORDER BY COALESCE(display_name, legal_name), id
                """).fetchall()
        for row in artist_rows:
            label = f"{row[1]} ({row[0]})"
            self.royalty_party_combo.addItem(label, int(row[0]))
        for row in all_rows:
            label = f"{row[1]} ({row[0]})"
            self.royalty_term_party_combo.addItem(label, int(row[0]))
        if current is not None:
            index = self.royalty_party_combo.findData(current)
            if index >= 0:
                self.royalty_party_combo.setCurrentIndex(index)
        if term_current is not None:
            index = self.royalty_term_party_combo.findData(term_current)
            if index >= 0:
                self.royalty_term_party_combo.setCurrentIndex(index)

    def _refresh_selected_royalty_contract_context(self) -> None:
        self.refresh_royalty_context()
        self.refresh_royalty_terms()
        self.refresh_royalty_source_events()

    def _populate_context_entity_choices(self, context: RoyaltyIntegrationContext | None) -> None:
        selected_scope_type = str(self.royalty_term_scope_type_combo.currentData() or "contract")
        selected_scope_id = self.royalty_term_scope_id_combo.currentData()
        selected_work_id = self.royalty_event_work_combo.currentData()
        selected_track_id = self.royalty_event_track_combo.currentData()
        selected_release_id = self.royalty_event_release_combo.currentData()
        self.royalty_term_scope_id_combo.clear()
        self.royalty_event_work_combo.clear()
        self.royalty_event_track_combo.clear()
        self.royalty_event_release_combo.clear()
        self.royalty_event_work_combo.addItem("No explicit work", None)
        self.royalty_event_track_combo.addItem("No explicit track", None)
        self.royalty_event_release_combo.addItem("No explicit release", None)
        if context is None:
            return
        scope_map = {
            "work": ("Works", context.work_ids),
            "track": ("Tracks", context.track_ids),
            "release": ("Releases", context.release_ids),
            "right": ("RightsRecords", context.right_ids),
        }
        table_name, ids = scope_map.get(selected_scope_type, ("", ()))
        for entity_id in ids:
            self.royalty_term_scope_id_combo.addItem(
                self._optional_id_label(table_name, entity_id),
                int(entity_id),
            )
        for entity_id in context.work_ids:
            self.royalty_event_work_combo.addItem(
                self._optional_id_label("Works", entity_id),
                int(entity_id),
            )
        for entity_id in context.track_ids:
            self.royalty_event_track_combo.addItem(
                self._optional_id_label("Tracks", entity_id),
                int(entity_id),
            )
        for entity_id in context.release_ids:
            self.royalty_event_release_combo.addItem(
                self._optional_id_label("Releases", entity_id),
                int(entity_id),
            )
        for combo, selected in (
            (self.royalty_term_scope_id_combo, selected_scope_id),
            (self.royalty_event_work_combo, selected_work_id),
            (self.royalty_event_track_combo, selected_track_id),
            (self.royalty_event_release_combo, selected_release_id),
        ):
            if selected is not None:
                index = combo.findData(selected)
                if index >= 0:
                    combo.setCurrentIndex(index)

    def _scalar(self, query: str, params: tuple[object, ...] = ()) -> int:
        conn = self._conn()
        if conn is None:
            return 0
        row = conn.execute(query, params).fetchone()
        return int(row[0] or 0) if row is not None else 0

    def _refresh_dashboard_kpi_labels(self) -> None:
        values = getattr(self, "_dashboard_kpis", {})
        labels = getattr(self, "_dashboard_kpi_labels", {})
        for key, label in labels.items():
            label.setText(str(values.get(key, label.text())))

    def _refresh_dashboard_tables(self, outstanding: Sequence[object]) -> None:
        conn = self._conn()
        if conn is None:
            return
        work_rows: list[tuple[object, ...]] = []
        for row in outstanding:
            if getattr(row, "due_status", "") == "overdue":
                work_rows.append(
                    (
                        "Invoice",
                        f"Invoice {getattr(row, 'invoice_number', '') or getattr(row, 'invoice_id', '')} is overdue",
                        f"Party {getattr(row, 'party_id', '')}",
                        _display_date(getattr(row, "due_date", "")),
                        format_money(
                            int(getattr(row, "outstanding_minor", 0)),
                            currency=str(getattr(row, "currency", "EUR")),
                        ),
                        "High",
                        "Overdue",
                        "Open invoice",
                    )
                )
        unmatched = conn.execute("""
            SELECT id, description, period_start, period_end, currency, net_amount_minor
            FROM RoyaltySourceEvents
            WHERE contract_id IS NULL AND work_id IS NULL AND track_id IS NULL AND release_id IS NULL
            ORDER BY created_at DESC, id DESC
            LIMIT 25
            """).fetchall()
        for row in unmatched:
            work_rows.append(
                (
                    "Import",
                    row[1],
                    "Unmatched",
                    f"{_display_date(row[2])} - {_display_date(row[3])}".strip(" -"),
                    format_money(int(row[5] or 0), currency=str(row[4] or "EUR")),
                    "Medium",
                    "Needs matching",
                    "Map fields",
                )
            )
        _set_table_rows(
            self.dashboard_work_queue_table,
            (
                "Type",
                "Description",
                "Related party",
                "Period",
                "Amount",
                "Priority",
                "Status",
                "Action",
            ),
            work_rows,
            empty_message="No royalty, invoice, payment, or VAT exceptions need attention.",
        )

        calculation_rows = conn.execute("""
            SELECT
                c.id,
                c.period_start,
                c.period_end,
                c.status,
                c.currency,
                c.net_payable_minor,
                COALESCE(p.paid_minor, 0)
            FROM RoyaltyCalculations c
            LEFT JOIN (
                SELECT royalty_calculation_id, SUM(amount_minor) AS paid_minor
                FROM ArtistPayouts
                GROUP BY royalty_calculation_id
            ) p ON p.royalty_calculation_id=c.id
            ORDER BY c.updated_at DESC, c.id DESC
            LIMIT 25
            """).fetchall()
        _set_table_rows(
            self.dashboard_calculation_table,
            (
                "Period",
                "Run ID",
                "Status",
                "Gross royalties",
                "Deductions",
                "Advance",
                "Net payable",
                "Exceptions",
            ),
            [
                (
                    f"{_display_date(row[1])} - {_display_date(row[2])}".strip(" -"),
                    row[0],
                    _status_label(row[3]),
                    format_money(int(row[5] or 0), currency=str(row[4] or "EUR")),
                    format_money(0, currency=str(row[4] or "EUR")),
                    format_money(0, currency=str(row[4] or "EUR")),
                    format_money(
                        max(0, int(row[5] or 0) - int(row[6] or 0)),
                        currency=str(row[4] or "EUR"),
                    ),
                    "",
                )
                for row in calculation_rows
            ],
            empty_message="No royalty calculation runs yet.",
        )

        invoice_status = conn.execute("""
            SELECT document_status, COUNT(*), COALESCE(SUM(total_minor), 0)
            FROM Invoices
            GROUP BY document_status
            ORDER BY document_status
            """).fetchall()
        _set_table_rows(
            self.dashboard_invoice_status_table,
            ("Status", "Count", "Outstanding", "Action"),
            [
                (
                    _status_label(row[0]),
                    row[1],
                    format_money(int(row[2] or 0)),
                    "Review invoices",
                )
                for row in invoice_status
            ],
            empty_message="No invoices have been created.",
        )
        self._refresh_period_close_and_exports()

        self.dashboard_detail_output.setPlainText(
            "Dashboard figures are derived from existing invoice records, royalty calculations, "
            "artist payout records, VAT ledger reports, and posted accounting entries. "
            "Use the section tabs to drill into the source documents and journal entries."
        )

    def _refresh_period_close_and_exports(self) -> None:
        unposted_invoices = self._scalar("""
            SELECT COUNT(*)
            FROM Invoices
            WHERE document_status IN ('issued', 'sent')
              AND issued_ledger_transaction_id IS NULL
            """)
        unposted_statements = self._scalar("""
            SELECT COUNT(*)
            FROM RoyaltyCalculations
            WHERE status IN ('approved', 'posted', 'statement_generated')
              AND ledger_transaction_id IS NULL
            """)
        open_periods = 1 if unposted_invoices or unposted_statements else 0
        _set_table_rows(
            self.period_close_table,
            (
                "Period",
                "Unposted invoices",
                "Unposted statements",
                "Unmatched payments",
                "Calculation runs not locked",
                "Action",
            ),
            [
                (
                    "Current open period",
                    unposted_invoices,
                    unposted_statements,
                    0,
                    self._scalar("SELECT COUNT(*) FROM RoyaltyCalculations WHERE status != 'paid'"),
                    "Close when reconciled" if open_periods else "Ready",
                )
            ],
            empty_message="No open accounting period checks.",
        )
        _set_table_rows(
            self.accounting_export_table,
            ("Export batch ID", "Date", "System", "Period", "Items", "Status", "Errors"),
            [],
            empty_message="No accounting export batches have been created.",
        )
        _set_table_rows(
            self.dashboard_accounting_control_table,
            ("Control", "Open items", "Status", "Action"),
            [
                (
                    "Unposted invoices",
                    unposted_invoices,
                    "Blocked" if unposted_invoices else "Clear",
                    "Review",
                ),
                (
                    "Unposted statements",
                    unposted_statements,
                    "Blocked" if unposted_statements else "Clear",
                    "Review",
                ),
                ("Failed journal exports", 0, "Clear", "Export accounting"),
                (
                    "Accounting periods",
                    open_periods,
                    "Open" if open_periods else "Ready",
                    "Period close",
                ),
            ],
            empty_message="No accounting controls configured.",
        )

    def _refresh_report_catalog(self) -> None:
        _set_table_rows(
            self.report_catalog_table,
            ("Category", "Report", "Source", "Filters", "Drill-down"),
            [
                (
                    "Royalty Reports",
                    "Royalty summary by payee",
                    "RoyaltyCalculations",
                    "Period / payee / contract",
                    "Calculation lines",
                ),
                (
                    "Royalty Reports",
                    "Advance recoupment report",
                    "Royalty statements",
                    "Period / contract",
                    "Statement detail",
                ),
                (
                    "Invoice Reports",
                    "Open invoices",
                    "Invoices + ledger settlement",
                    "Status / party",
                    "Invoice and payments",
                ),
                (
                    "Invoice Reports",
                    "Invoice ageing",
                    "Ledger-derived receivables",
                    "Due date / party",
                    "Journal entries",
                ),
                (
                    "VAT Reports",
                    "VAT summary by period",
                    "VAT ledger entries",
                    "Period / treatment",
                    "Invoice VAT breakdown",
                ),
                (
                    "Management Reports",
                    "Contract profitability",
                    "Contracts + invoices + royalties",
                    "Contract / period",
                    "Source transactions",
                ),
                (
                    "Audit Reports",
                    "Journal posting changes",
                    "AccountingTransactions",
                    "Date / actor",
                    "Ledger entry audit",
                ),
            ],
            empty_message="No reports configured.",
        )

    def _selected_invoice_id(self) -> int | None:
        selected = self.invoice_table.selectedItems()
        if not selected:
            return None
        row = selected[0].row()
        item = self.invoice_table.item(row, 0)
        if item is None:
            return None
        value = item.data(Qt.ItemDataRole.UserRole)
        return int(value) if value is not None else int(item.text())

    def _selected_invoice_final_storage_mode(self) -> str:
        mode = self.invoice_final_storage_combo.currentData()
        return str(mode or STORAGE_MODE_DATABASE)

    @staticmethod
    def _latest_final_invoice_artifact(
        template_service: InvoiceTemplateService,
        invoice_id: int,
    ):
        for artifact_type in ("final_pdf", "final_html", "html"):
            artifact = template_service.fetch_latest_invoice_output_artifact(
                invoice_id,
                artifact_type=artifact_type,
            )
            if artifact is not None:
                return artifact
        return None

    def _refresh_selected_invoice_final_status(self) -> None:
        conn = self._conn()
        invoice_id = self._selected_invoice_id()
        if conn is None or invoice_id is None:
            self.invoice_final_status_label.setText(
                "Final invoices created from Template Workspace appear here."
            )
            return
        invoice = InvoiceService(conn).fetch_invoice(invoice_id)
        template_service = InvoiceTemplateService(
            conn,
            data_root=self._data_root,
        )
        artifact = self._latest_final_invoice_artifact(template_service, invoice_id)
        if artifact is not None:
            self.invoice_final_status_label.setText(
                "Final invoice: "
                f"{artifact.output_filename} ({self._storage_label(artifact.storage_mode)})."
            )
            return
        if invoice is not None and invoice.document_status == "draft":
            self.invoice_final_status_label.setText(
                "Draft invoice selected. Final invoice authoring now happens in Template Workspace."
            )
        else:
            self.invoice_final_status_label.setText(
                "No final invoice artifact is stored for the selected invoice."
            )

    @staticmethod
    def _storage_label(storage_mode: str | None) -> str:
        return "managed file" if storage_mode == STORAGE_MODE_MANAGED_FILE else "database embedded"

    def _selected_invoice_line_id(self) -> int | None:
        selected = self.invoice_line_table.selectedItems()
        if not selected:
            return None
        row = selected[0].row()
        item = self.invoice_line_table.item(row, 0)
        if item is None:
            return None
        value = item.data(Qt.ItemDataRole.UserRole)
        return int(value) if value is not None else int(item.text())

    def _selected_royalty_statement_id(self) -> int | None:
        selected = self.statement_table.selectedItems()
        if not selected:
            return None
        row = selected[0].row()
        item = self.statement_table.item(row, 0)
        if item is None:
            return None
        value = item.data(Qt.ItemDataRole.UserRole)
        if value is not None:
            return int(value)
        statement_number = _clean_text(item.text())
        conn = self._conn()
        if conn is None or not statement_number:
            return None
        row_data = conn.execute(
            "SELECT id FROM RoyaltyStatements WHERE statement_number=?",
            (statement_number,),
        ).fetchone()
        return int(row_data[0]) if row_data else None

    def _selected_catalog_item_id(self) -> int | None:
        selected = self.catalog_table.selectedItems()
        if not selected:
            return None
        row = selected[0].row()
        item = self.catalog_table.item(row, 0)
        if item is None:
            return None
        value = item.data(Qt.ItemDataRole.UserRole)
        return int(value) if value is not None else int(item.text())

    def _selected_royalty_contract_id(self) -> int | None:
        return self._combo_int_data(self.royalty_contract_combo)

    def _select_invoice_id(self, invoice_id: int) -> None:
        for row in range(self.invoice_table.rowCount()):
            item = self.invoice_table.item(row, 0)
            if item is not None and int(item.text()) == int(invoice_id):
                self.invoice_table.selectRow(row)
                return

    def _selected_royalty_calculation_id(self) -> int | None:
        selected = self.royalty_table.selectedItems()
        if not selected:
            return None
        row = selected[0].row()
        item = self.royalty_table.item(row, 0)
        if item is None:
            return None
        value = item.data(Qt.ItemDataRole.UserRole)
        return int(value) if value is not None else int(item.text())

    def _select_royalty_calculation_id(self, calculation_id: int) -> None:
        for row in range(self.royalty_table.rowCount()):
            item = self.royalty_table.item(row, 0)
            if item is not None and int(item.text()) == int(calculation_id):
                self.royalty_table.selectRow(row)
                return

    def _selected_rights_titles_work_id(self) -> int | None:
        selected = self.rights_titles_table.selectedItems()
        if not selected:
            return None
        return self._rights_titles_item_id(selected[0], Qt.ItemDataRole.UserRole)

    def _selected_rights_titles_right_id(self) -> int | None:
        selected = self.rights_titles_table.selectedItems()
        if not selected:
            return None
        return self._rights_titles_item_id(selected[0], Qt.ItemDataRole.UserRole + 1)

    @staticmethod
    def _rights_titles_item_id(item: QTableWidgetItem | None, role: int) -> int | None:
        if item is None:
            return None
        value = item.data(role)
        try:
            return int(value)
        except TypeError, ValueError:
            return None

    @staticmethod
    def _combo_int_data(combo: QComboBox) -> int | None:
        value = combo.currentData()
        return int(value) if value is not None else None

    def _selected_context_work_id(self) -> int | None:
        work_id = self._combo_int_data(self.royalty_event_work_combo)
        if work_id is not None:
            return work_id
        if self.royalty_term_scope_type_combo.currentData() == "work":
            return self._combo_int_data(self.royalty_term_scope_id_combo)
        context = self._current_royalty_context()
        return context.work_ids[0] if context is not None and context.work_ids else None

    def _selected_context_track_id(self) -> int | None:
        track_id = self._combo_int_data(self.royalty_event_track_combo)
        if track_id is not None:
            return track_id
        if self.royalty_term_scope_type_combo.currentData() == "track":
            return self._combo_int_data(self.royalty_term_scope_id_combo)
        context = self._current_royalty_context()
        return context.track_ids[0] if context is not None and context.track_ids else None

    def _selected_context_right_id(self) -> int | None:
        if self.royalty_term_scope_type_combo.currentData() == "right":
            right_id = self._combo_int_data(self.royalty_term_scope_id_combo)
            if right_id is not None:
                return right_id
        context = self._current_royalty_context()
        return context.right_ids[0] if context is not None and context.right_ids else None

    def _current_royalty_context(self) -> RoyaltyIntegrationContext | None:
        conn = self._conn()
        contract_id = self._selected_royalty_contract_id()
        if conn is None or contract_id is None:
            return None
        try:
            return RoyaltyIntegrationService(conn).build_context(
                contract_id,
                period_start=_clean_text(self.royalty_period_start_field.text()),
                period_end=_clean_text(self.royalty_period_end_field.text()),
            )
        except Exception:
            return None

    def _format_named_ids(self, table_name: str, ids: tuple[int, ...]) -> str:
        if not ids:
            return "none"
        return ", ".join(self._optional_id_label(table_name, entity_id) for entity_id in ids)

    def _optional_id_label(self, table_name: str, entity_id: int | None) -> str:
        if entity_id is None:
            return ""
        conn = self._conn()
        if conn is None:
            return f"#{int(entity_id)}"
        columns = {
            str(row[1]) for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        }
        label_column = next(
            (
                column
                for column in (
                    "title",
                    "name",
                    "display_name",
                    "legal_name",
                    "isrc",
                    "right_type",
                )
                if column in columns
            ),
            None,
        )
        if label_column is None:
            return f"#{int(entity_id)}"
        row = conn.execute(
            f"SELECT {label_column} FROM {table_name} WHERE id=?",
            (int(entity_id),),
        ).fetchone()
        label = str(row[0] or "").strip() if row else ""
        return f"{label or table_name} #{int(entity_id)}"

    def _party_label(self, party_id: int | None) -> str:
        if party_id is None:
            return ""
        conn = self._conn()
        if conn is None:
            return f"Party #{int(party_id)}"
        row = conn.execute(
            """
            SELECT COALESCE(artist_name, display_name, legal_name, printf('Party %d', id))
            FROM Parties
            WHERE id=?
            """,
            (int(party_id),),
        ).fetchone()
        return str(row[0] if row else f"Party #{int(party_id)}")

    def _conn(self) -> sqlite3.Connection | None:
        return self._conn_provider()

    def _conn_or_warn(self) -> sqlite3.Connection | None:
        conn = self._conn()
        if conn is None:
            QMessageBox.warning(self, "Invoice Workspace", "Open a profile first.")
        return conn

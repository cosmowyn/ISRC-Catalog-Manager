"""Party manager dialogs."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from isrc_manager.ui_common import (
    _add_standard_dialog_header,
    _apply_compact_dialog_control_heights,
    _apply_standard_dialog_chrome,
    _apply_standard_widget_chrome,
    _configure_standard_form_layout,
    _confirm_destructive_action,
    _create_action_button_cluster,
    _create_scrollable_dialog_content,
    _create_standard_section,
)

from .models import PARTY_TYPE_CHOICES, PartyPayload, PartyRecord
from .service import PartyService


class PartyEditorDialog(QDialog):
    """Create or edit a reusable party record."""

    def __init__(
        self, *, party_service: PartyService, party: PartyRecord | None = None, parent=None
    ):
        super().__init__(parent)
        self.party_service = party_service
        self.party = party
        self._artist_aliases: list[str] = []
        self.setWindowTitle("Edit Party" if party is not None else "Create Party")
        self.resize(840, 700)
        self.setMinimumSize(700, 560)
        _apply_standard_dialog_chrome(self, "partyEditorDialog")

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)
        _add_standard_dialog_header(
            root,
            self,
            title=self.windowTitle(),
            subtitle=(
                "Create one canonical person or company record, then reuse it across works, "
                "contracts, rights, and the rest of the catalog."
            ),
        )

        self.tabs = QTabWidget(self)
        self.tabs.setObjectName("partyEditorTabs")
        self.tabs.setDocumentMode(True)
        root.addWidget(self.tabs, 1)

        def create_form_tab(tab_title: str, section_title: str, description: str) -> QFormLayout:
            page = QWidget(self.tabs)
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(0, 0, 0, 0)
            page_layout.setSpacing(0)
            scroll_area, _, content_layout = _create_scrollable_dialog_content(page)
            page_layout.addWidget(scroll_area, 1)

            box, box_layout = _create_standard_section(page, section_title, description)
            form = QFormLayout()
            _configure_standard_form_layout(form)
            box_layout.addLayout(form)
            content_layout.addWidget(box)
            content_layout.addStretch(1)
            self.tabs.addTab(page, tab_title)
            return form

        identity_form = create_form_tab(
            "Identity",
            "Party Identity",
            "Capture the canonical legal, public, and artist-facing identity used across contracts, rights, and template resolution.",
        )
        aliases_page = QWidget(self.tabs)
        aliases_layout = QVBoxLayout(aliases_page)
        aliases_layout.setContentsMargins(0, 0, 0, 0)
        aliases_layout.setSpacing(0)
        aliases_scroll, _, aliases_content = _create_scrollable_dialog_content(aliases_page)
        aliases_layout.addWidget(aliases_scroll, 1)
        aliases_box, aliases_box_layout = _create_standard_section(
            aliases_page,
            "Artist Aliases",
            "Attach multiple artist-facing names to one canonical party. These aliases stay tied to the same party for reuse and template resolution.",
        )
        aliases_content.addWidget(aliases_box)
        aliases_content.addStretch(1)
        self.tabs.addTab(aliases_page, "Artist Aliases")

        address_form = create_form_tab(
            "Address",
            "Address",
            "Store the structured address values used in agreements, invoices, and partner correspondence.",
        )
        contact_form = create_form_tab(
            "Contact",
            "Contact",
            "Store the main communication channels and contact person details used when reaching this party.",
        )
        business_form = create_form_tab(
            "Business / Legal",
            "Business / Legal",
            "Keep registration and financial identifiers in one place so templates can resolve from a single authoritative source.",
        )
        notes_page = QWidget(self.tabs)
        notes_layout = QVBoxLayout(notes_page)
        notes_layout.setContentsMargins(0, 0, 0, 0)
        notes_layout.setSpacing(0)
        notes_scroll, _, notes_content = _create_scrollable_dialog_content(notes_page)
        notes_layout.addWidget(notes_scroll, 1)
        notes_box, notes_box_layout = _create_standard_section(
            notes_page,
            "Notes",
            "Capture internal context about this party, its role, or any relationship details that should remain in the workspace.",
        )
        notes_content.addWidget(notes_box)
        notes_content.addStretch(1)
        self.tabs.addTab(notes_page, "Notes")

        self.legal_name_edit = QLineEdit()
        identity_form.addRow("Legal Name", self.legal_name_edit)

        self.display_name_edit = QLineEdit()
        identity_form.addRow("Display Name", self.display_name_edit)

        self.artist_name_edit = QLineEdit()
        identity_form.addRow("Artist Name", self.artist_name_edit)

        self.company_name_edit = QLineEdit()
        identity_form.addRow("Company Name", self.company_name_edit)

        self.first_name_edit = QLineEdit()
        identity_form.addRow("First Name", self.first_name_edit)

        self.middle_name_edit = QLineEdit()
        identity_form.addRow("Middle Name", self.middle_name_edit)

        self.last_name_edit = QLineEdit()
        identity_form.addRow("Last Name", self.last_name_edit)

        self.party_type_combo = QComboBox()
        for item in PARTY_TYPE_CHOICES:
            self.party_type_combo.addItem(item.replace("_", " ").title(), item)
        identity_form.addRow("Party Type", self.party_type_combo)

        alias_entry_row = QHBoxLayout()
        alias_entry_row.setContentsMargins(0, 0, 0, 0)
        alias_entry_row.setSpacing(8)
        self.alias_edit = QLineEdit(self)
        self.alias_edit.setPlaceholderText("Add one alias at a time")
        self.alias_edit.returnPressed.connect(self._add_alias)
        alias_entry_row.addWidget(self.alias_edit, 1)
        self.add_alias_button = QPushButton("Add Alias", self)
        self.add_alias_button.clicked.connect(self._add_alias)
        alias_entry_row.addWidget(self.add_alias_button)
        aliases_box_layout.addLayout(alias_entry_row)

        alias_actions_row = QHBoxLayout()
        alias_actions_row.setContentsMargins(0, 0, 0, 0)
        alias_actions_row.setSpacing(8)
        self.remove_alias_button = QPushButton("Remove Highlighted", self)
        self.remove_alias_button.clicked.connect(self._remove_selected_aliases)
        alias_actions_row.addWidget(self.remove_alias_button)
        alias_actions_row.addStretch(1)
        aliases_box_layout.addLayout(alias_actions_row)

        self.alias_hint_label = QLabel(
            "Use aliases for alternate artist-facing names only. Keep the canonical party identity on the Identity tab.",
            self,
        )
        self.alias_hint_label.setProperty("role", "supportingText")
        self.alias_hint_label.setWordWrap(True)
        aliases_box_layout.addWidget(self.alias_hint_label)

        self.alias_table = QTableWidget(0, 1, self)
        self.alias_table.setObjectName("partyArtistAliasTable")
        self.alias_table.setHorizontalHeaderLabels(["Artist Alias"])
        self.alias_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.alias_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.alias_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.alias_table.verticalHeader().setVisible(False)
        alias_header = self.alias_table.horizontalHeader()
        alias_header.setSectionResizeMode(0, QHeaderView.Stretch)
        self.alias_table.setMinimumHeight(180)
        aliases_box_layout.addWidget(self.alias_table, 1)

        self.contact_edit = QLineEdit()
        contact_form.addRow("Contact Person", self.contact_edit)

        self.email_edit = QLineEdit()
        contact_form.addRow("Email Address", self.email_edit)

        self.alternative_email_edit = QLineEdit()
        contact_form.addRow("Alternative Email Address", self.alternative_email_edit)

        self.phone_edit = QLineEdit()
        contact_form.addRow("Phone Number", self.phone_edit)

        self.website_edit = QLineEdit()
        contact_form.addRow("Website", self.website_edit)

        self.street_name_edit = QLineEdit()
        address_form.addRow("Street Name", self.street_name_edit)

        self.street_number_edit = QLineEdit()
        address_form.addRow("Street Number", self.street_number_edit)

        self.address_line1_edit = QLineEdit()
        address_form.addRow("Address Line 1", self.address_line1_edit)

        self.address_line2_edit = QLineEdit()
        address_form.addRow("Address Line 2", self.address_line2_edit)

        self.city_edit = QLineEdit()
        address_form.addRow("City", self.city_edit)

        self.region_edit = QLineEdit()
        address_form.addRow("Region / State", self.region_edit)

        self.postal_code_edit = QLineEdit()
        address_form.addRow("Postal Code", self.postal_code_edit)

        self.country_edit = QLineEdit()
        address_form.addRow("Country", self.country_edit)

        self.bank_account_edit = QLineEdit()
        business_form.addRow("Bank Account Number", self.bank_account_edit)

        self.vat_number_edit = QLineEdit()
        business_form.addRow("VAT Number", self.vat_number_edit)

        self.chamber_number_edit = QLineEdit()
        business_form.addRow("Chamber of Commerce Number", self.chamber_number_edit)

        self.tax_id_edit = QLineEdit()
        business_form.addRow("Tax ID", self.tax_id_edit)

        self.pro_edit = QLineEdit()
        business_form.addRow("PRO Affiliation", self.pro_edit)

        self.pro_number_edit = QLineEdit()
        business_form.addRow("PRO Number", self.pro_number_edit)

        self.ipi_edit = QLineEdit()
        business_form.addRow("IPI / CAE", self.ipi_edit)

        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setMinimumHeight(120)
        notes_box_layout.addWidget(self.notes_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        _apply_compact_dialog_control_heights(self)

        self._set_party_type_value("organization")
        if party is not None:
            self.legal_name_edit.setText(party.legal_name)
            self.display_name_edit.setText(party.display_name or "")
            self.artist_name_edit.setText(party.artist_name or "")
            self.company_name_edit.setText(party.company_name or "")
            self.first_name_edit.setText(party.first_name or "")
            self.middle_name_edit.setText(party.middle_name or "")
            self.last_name_edit.setText(party.last_name or "")
            self._set_party_type_value(party.party_type or "organization")
            self.contact_edit.setText(party.contact_person or "")
            self.email_edit.setText(party.email or "")
            self.alternative_email_edit.setText(party.alternative_email or "")
            self.phone_edit.setText(party.phone or "")
            self.website_edit.setText(party.website or "")
            self.street_name_edit.setText(party.street_name or "")
            self.street_number_edit.setText(party.street_number or "")
            self.address_line1_edit.setText(party.address_line1 or "")
            self.address_line2_edit.setText(party.address_line2 or "")
            self.city_edit.setText(party.city or "")
            self.region_edit.setText(party.region or "")
            self.postal_code_edit.setText(party.postal_code or "")
            self.country_edit.setText(party.country or "")
            self.bank_account_edit.setText(party.bank_account_number or "")
            self.vat_number_edit.setText(party.vat_number or "")
            self.chamber_number_edit.setText(party.chamber_of_commerce_number or "")
            self.tax_id_edit.setText(party.tax_id or "")
            self.pro_edit.setText(party.pro_affiliation or "")
            self.pro_number_edit.setText(party.pro_number or "")
            self.ipi_edit.setText(party.ipi_cae or "")
            self.notes_edit.setPlainText(party.notes or "")
            self._artist_aliases = list(party.artist_aliases)
            self._refresh_alias_table()

    def _set_party_type_value(self, value: str) -> None:
        clean_value = str(value or "organization").strip().lower().replace(" ", "_")
        index = self.party_type_combo.findData(clean_value)
        if index >= 0:
            self.party_type_combo.setCurrentIndex(index)
            return
        fallback_index = self.party_type_combo.findData("other")
        if fallback_index >= 0:
            self.party_type_combo.setCurrentIndex(fallback_index)

    def _refresh_alias_table(self) -> None:
        self.alias_table.setRowCount(len(self._artist_aliases))
        for row, alias_name in enumerate(self._artist_aliases):
            self.alias_table.setItem(row, 0, QTableWidgetItem(alias_name))

    def _add_alias(self) -> None:
        alias_name = self.alias_edit.text().strip()
        if not alias_name:
            return
        if alias_name.casefold() not in {item.casefold() for item in self._artist_aliases}:
            self._artist_aliases.append(alias_name)
            self._refresh_alias_table()
        self.alias_edit.clear()

    def _remove_selected_aliases(self) -> None:
        selection_model = self.alias_table.selectionModel()
        if selection_model is None:
            return
        rows = sorted({index.row() for index in selection_model.selectedRows()})
        if not rows:
            return
        for row in reversed(rows):
            if 0 <= row < len(self._artist_aliases):
                del self._artist_aliases[row]
        self._refresh_alias_table()

    def payload(self) -> PartyPayload:
        return PartyPayload(
            legal_name=self.legal_name_edit.text().strip(),
            display_name=self.display_name_edit.text().strip() or None,
            artist_name=self.artist_name_edit.text().strip() or None,
            company_name=self.company_name_edit.text().strip() or None,
            first_name=self.first_name_edit.text().strip() or None,
            middle_name=self.middle_name_edit.text().strip() or None,
            last_name=self.last_name_edit.text().strip() or None,
            party_type=str(self.party_type_combo.currentData() or "organization"),
            contact_person=self.contact_edit.text().strip() or None,
            email=self.email_edit.text().strip() or None,
            alternative_email=self.alternative_email_edit.text().strip() or None,
            phone=self.phone_edit.text().strip() or None,
            website=self.website_edit.text().strip() or None,
            street_name=self.street_name_edit.text().strip() or None,
            street_number=self.street_number_edit.text().strip() or None,
            address_line1=self.address_line1_edit.text().strip() or None,
            address_line2=self.address_line2_edit.text().strip() or None,
            city=self.city_edit.text().strip() or None,
            region=self.region_edit.text().strip() or None,
            postal_code=self.postal_code_edit.text().strip() or None,
            country=self.country_edit.text().strip() or None,
            bank_account_number=self.bank_account_edit.text().strip() or None,
            chamber_of_commerce_number=self.chamber_number_edit.text().strip() or None,
            tax_id=self.tax_id_edit.text().strip() or None,
            vat_number=self.vat_number_edit.text().strip() or None,
            pro_affiliation=self.pro_edit.text().strip() or None,
            pro_number=self.pro_number_edit.text().strip() or None,
            ipi_cae=self.ipi_edit.text().strip() or None,
            notes=self.notes_edit.toPlainText().strip() or None,
            artist_aliases=list(self._artist_aliases),
        )


class PartyManagerPanel(QWidget):
    """Browse, edit, and merge canonical party records inside a workspace panel."""

    def __init__(self, *, party_service_provider, parent=None):
        super().__init__(parent)
        self.party_service_provider = party_service_provider
        self.setObjectName("partyManagerPanel")
        _apply_standard_widget_chrome(self, "partyManagerPanel")

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(14)
        _add_standard_dialog_header(
            root,
            self,
            title="Party Manager",
            subtitle=(
                "Maintain one reusable record per important person or company, then "
                "link it across works, contracts, and rights."
            ),
        )

        controls_box, controls_layout = _create_standard_section(
            self,
            "Find and Manage",
            "Search the canonical party list, then maintain the selected records.",
        )
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(10)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(
            "Search parties by legal name, display name, artist name, alias, company, email, PRO, or Chamber number..."
        )
        self.search_edit.textChanged.connect(self.refresh)
        top_row.addWidget(self.search_edit, 1)
        self.party_type_filter_combo = QComboBox(self)
        self.party_type_filter_combo.setObjectName("partyManagerTypeFilter")
        self.party_type_filter_combo.addItem("All Types", "")
        for item in PARTY_TYPE_CHOICES:
            self.party_type_filter_combo.addItem(item.replace("_", " ").title(), item)
        self.party_type_filter_combo.currentIndexChanged.connect(self.refresh)
        top_row.addWidget(self.party_type_filter_combo)
        controls_layout.addLayout(top_row)

        add_button = QPushButton("Add")
        add_button.clicked.connect(self.create_party)
        edit_button = QPushButton("Edit")
        edit_button.clicked.connect(self.edit_selected)
        merge_button = QPushButton("Merge Selected")
        merge_button.clicked.connect(self.merge_selected)
        delete_button = QPushButton("Delete")
        delete_button.clicked.connect(self.delete_selected)
        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self.refresh)
        self.manage_actions_cluster = _create_action_button_cluster(
            self,
            [add_button, edit_button, merge_button, delete_button, refresh_button],
            columns=2,
            min_button_width=160,
            span_last_row=True,
        )
        self.manage_actions_cluster.setObjectName("partyManagerActionsCluster")
        controls_layout.addWidget(self.manage_actions_cluster)
        root.addWidget(controls_box)

        self.table = QTableWidget(0, 7, self)
        self.table.setHorizontalHeaderLabels(
            [
                "ID",
                "Primary Name",
                "Legal / Company",
                "Type",
                "Email",
                "Aliases",
                "Linked Records",
            ]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.doubleClicked.connect(lambda _index: self.edit_selected())
        table_box, table_layout = _create_standard_section(
            self,
            "Party Records",
            "Double-click a row to edit the selected party, or use multi-select to merge duplicates safely.",
        )
        table_layout.addWidget(self.table, 1)
        root.addWidget(table_box, 1)

        self.refresh()
        _apply_compact_dialog_control_heights(self)

    def _party_service(self) -> PartyService | None:
        return self.party_service_provider()

    def _restore_selection(self, party_ids: list[int]) -> None:
        if not party_ids:
            return
        selection_model = self.table.selectionModel()
        if selection_model is None:
            return
        wanted = {int(party_id) for party_id in party_ids}
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is None:
                continue
            try:
                current_party_id = int(item.text())
            except Exception:
                continue
            if current_party_id not in wanted:
                continue
            selection_model.select(
                self.table.model().index(row, 0),
                selection_model.SelectionFlag.Select | selection_model.SelectionFlag.Rows,
            )

    def focus_party(self, party_id: int | None) -> None:
        self.table.clearSelection()
        if party_id is None:
            return
        self._restore_selection([int(party_id)])

    def _selected_party_ids(self) -> list[int]:
        ids: list[int] = []
        selection_model = self.table.selectionModel()
        if selection_model is None:
            return ids
        for index in selection_model.selectedRows():
            item = self.table.item(index.row(), 0)
            if item is None:
                continue
            ids.append(int(item.text()))
        return ids

    def refresh(self) -> None:
        if not hasattr(self, "table"):
            return
        selected_ids = self._selected_party_ids()
        service = self._party_service()
        if service is None:
            self.table.setRowCount(0)
            return
        records = service.list_parties(
            search_text=self.search_edit.text(),
            party_type=str(self.party_type_filter_combo.currentData() or "") or None,
        )
        self.table.setRowCount(0)
        for record in records:
            usage = service.usage_summary(record.id)
            row = self.table.rowCount()
            self.table.insertRow(row)
            primary_name = (
                record.display_name
                or record.artist_name
                or record.company_name
                or record.legal_name
            )
            legal_or_company = record.company_name or record.legal_name
            preferred_email = record.email or record.alternative_email or ""
            aliases_preview = ", ".join(record.artist_aliases)
            values = [
                str(record.id),
                primary_name,
                legal_or_company,
                record.party_type.replace("_", " ").title(),
                preferred_email,
                aliases_preview,
                str(usage.work_count + usage.contract_count + usage.rights_count),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row, column, item)
        self.table.resizeColumnsToContents()
        self._restore_selection(selected_ids)

    def create_party(self) -> None:
        service = self._party_service()
        if service is None:
            QMessageBox.warning(self, "Party Manager", "Open a profile first.")
            return
        dialog = PartyEditorDialog(party_service=service, parent=self)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            self.focus_party(service.create_party(dialog.payload()))
        except Exception as exc:
            QMessageBox.critical(self, "Party Manager", str(exc))
            return
        self.refresh()

    def edit_selected(self) -> None:
        service = self._party_service()
        if service is None:
            QMessageBox.warning(self, "Party Manager", "Open a profile first.")
            return
        selected_ids = self._selected_party_ids()
        if not selected_ids:
            QMessageBox.information(self, "Party Manager", "Select a party first.")
            return
        party = service.fetch_party(selected_ids[0])
        if party is None:
            self.refresh()
            return
        dialog = PartyEditorDialog(party_service=service, party=party, parent=self)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            service.update_party(party.id, dialog.payload())
        except Exception as exc:
            QMessageBox.critical(self, "Party Manager", str(exc))
            return
        self.refresh()
        self.focus_party(party.id)

    def delete_selected(self) -> None:
        service = self._party_service()
        if service is None:
            QMessageBox.warning(self, "Party Manager", "Open a profile first.")
            return
        selected_ids = self._selected_party_ids()
        if not selected_ids:
            QMessageBox.information(self, "Party Manager", "Select one or more parties first.")
            return
        if not _confirm_destructive_action(
            self,
            title="Delete Parties",
            prompt=f"Delete {len(selected_ids)} selected party record(s)?",
        ):
            return
        try:
            for party_id in selected_ids:
                service.delete_party(party_id)
        except Exception as exc:
            QMessageBox.critical(self, "Party Manager", str(exc))
            return
        self.refresh()

    def merge_selected(self) -> None:
        service = self._party_service()
        if service is None:
            QMessageBox.warning(self, "Party Manager", "Open a profile first.")
            return
        selected_ids = self._selected_party_ids()
        if len(selected_ids) < 2:
            QMessageBox.information(self, "Party Manager", "Select at least two parties to merge.")
            return
        primary_id = selected_ids[0]
        try:
            service.merge_parties(primary_id, selected_ids[1:])
        except Exception as exc:
            QMessageBox.critical(self, "Party Manager", str(exc))
            return
        self.refresh()
        self.focus_party(primary_id)


class PartyManagerDialog(QDialog):
    """Compatibility dialog wrapper around the reusable party manager panel."""

    def __init__(self, *, party_service: PartyService, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Party Manager")
        self.resize(900, 620)
        _apply_standard_dialog_chrome(self, "partyManagerDialog")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.panel = PartyManagerPanel(
            party_service_provider=lambda: party_service,
            parent=self,
        )
        root.addWidget(self.panel)

    def __getattr__(self, name: str):
        panel = self.__dict__.get("panel")
        if panel is not None and hasattr(panel, name):
            return getattr(panel, name)
        raise AttributeError(name)

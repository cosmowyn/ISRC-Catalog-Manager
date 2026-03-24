"""Party manager dialogs."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
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
    _create_action_button_grid,
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
        self.setWindowTitle("Edit Party" if party is not None else "Create Party")
        self.resize(760, 620)
        self.setMinimumSize(620, 500)
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
            "The core name and classification fields used when linking this record across the catalog.",
        )
        contact_form = create_form_tab(
            "Contact",
            "Contact & Registration",
            "Store the main contact details and registry identifiers that help keep this party unique.",
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

        self.party_type_combo = QComboBox()
        self.party_type_combo.addItems(
            [item.replace("_", " ").title() for item in PARTY_TYPE_CHOICES]
        )
        identity_form.addRow("Party Type", self.party_type_combo)

        self.country_edit = QLineEdit()
        identity_form.addRow("Country", self.country_edit)

        self.contact_edit = QLineEdit()
        contact_form.addRow("Contact Person", self.contact_edit)

        self.email_edit = QLineEdit()
        contact_form.addRow("Email", self.email_edit)

        self.phone_edit = QLineEdit()
        contact_form.addRow("Phone", self.phone_edit)

        self.website_edit = QLineEdit()
        contact_form.addRow("Website", self.website_edit)

        self.pro_edit = QLineEdit()
        contact_form.addRow("PRO", self.pro_edit)

        self.ipi_edit = QLineEdit()
        contact_form.addRow("IPI / CAE", self.ipi_edit)

        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setMinimumHeight(120)
        notes_box_layout.addWidget(self.notes_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        _apply_compact_dialog_control_heights(self)

        if party is not None:
            self.legal_name_edit.setText(party.legal_name)
            self.display_name_edit.setText(party.display_name or "")
            self.party_type_combo.setCurrentText(
                (party.party_type or "organization").replace("_", " ").title()
            )
            self.contact_edit.setText(party.contact_person or "")
            self.email_edit.setText(party.email or "")
            self.phone_edit.setText(party.phone or "")
            self.website_edit.setText(party.website or "")
            self.country_edit.setText(party.country or "")
            self.pro_edit.setText(party.pro_affiliation or "")
            self.ipi_edit.setText(party.ipi_cae or "")
            self.notes_edit.setPlainText(party.notes or "")

    def payload(self) -> PartyPayload:
        return PartyPayload(
            legal_name=self.legal_name_edit.text().strip(),
            display_name=self.display_name_edit.text().strip() or None,
            party_type=self.party_type_combo.currentText().strip().lower().replace(" ", "_"),
            contact_person=self.contact_edit.text().strip() or None,
            email=self.email_edit.text().strip() or None,
            phone=self.phone_edit.text().strip() or None,
            website=self.website_edit.text().strip() or None,
            country=self.country_edit.text().strip() or None,
            pro_affiliation=self.pro_edit.text().strip() or None,
            ipi_cae=self.ipi_edit.text().strip() or None,
            notes=self.notes_edit.toPlainText().strip() or None,
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
            "Search the canonical party list, then add, edit, merge, delete, or refresh the selected records.",
        )
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(10)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search parties by name, email, or IPI/CAE...")
        self.search_edit.textChanged.connect(self.refresh)
        top_row.addWidget(self.search_edit, 1)
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
        controls_layout.addWidget(
            _create_action_button_grid(
                self,
                [add_button, edit_button, merge_button, delete_button, refresh_button],
                columns=3,
            )
        )
        root.addWidget(controls_box)

        self.table = QTableWidget(0, 6, self)
        self.table.setHorizontalHeaderLabels(
            ["ID", "Legal Name", "Display Name", "Type", "Email", "Linked Records"]
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
        selected_ids = self._selected_party_ids()
        service = self._party_service()
        if service is None:
            self.table.setRowCount(0)
            return
        records = service.list_parties(search_text=self.search_edit.text())
        self.table.setRowCount(0)
        for record in records:
            usage = service.usage_summary(record.id)
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = [
                str(record.id),
                record.legal_name,
                record.display_name or "",
                record.party_type.replace("_", " ").title(),
                record.email or "",
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
        if (
            QMessageBox.question(
                self,
                "Delete Parties",
                f"Delete {len(selected_ids)} selected party record(s)?",
            )
            != QMessageBox.Yes
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

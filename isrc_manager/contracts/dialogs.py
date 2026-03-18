"""Contract manager dialogs."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
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
    _create_scrollable_dialog_content,
    _create_standard_section,
)
from isrc_manager.file_storage import normalize_storage_mode

from .models import (
    CONTRACT_STATUS_CHOICES,
    ContractDocumentPayload,
    ContractObligationPayload,
    ContractPartyPayload,
    ContractPayload,
)
from .service import ContractService


def _parse_bool_token(value: str) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def _parse_int_list(text: str) -> list[int]:
    values: list[int] = []
    for part in str(text or "").replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        values.append(int(part))
    return values


class ContractEditorDialog(QDialog):
    """Create or edit a contract lifecycle record."""

    def __init__(self, *, contract_service: ContractService, detail=None, parent=None):
        super().__init__(parent)
        self.contract_service = contract_service
        self.detail = detail
        self.setWindowTitle("Edit Contract" if detail is not None else "Create Contract")
        self.resize(980, 780)
        self.setMinimumSize(900, 700)
        _apply_standard_dialog_chrome(self, "contractEditorDialog")

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)
        _add_standard_dialog_header(
            root,
            self,
            title=self.windowTitle(),
            subtitle=(
                "Track lifecycle dates, linked parties, obligations, and document versions "
                "for one contract without losing the connection between them."
            ),
        )
        tabs = QTabWidget(self)
        root.addWidget(tabs, 1)

        overview_scroll, _, overview_layout = _create_scrollable_dialog_content(self)
        core_box, core_layout = _create_standard_section(
            self,
            "Contract Overview",
            "Core identification fields for the agreement, plus high-level summary and notes.",
        )
        core_form = QFormLayout()
        _configure_standard_form_layout(core_form)

        self.title_edit = QLineEdit()
        core_form.addRow("Title", self.title_edit)

        self.type_edit = QLineEdit()
        core_form.addRow("Contract Type", self.type_edit)

        self.status_combo = QComboBox()
        self.status_combo.addItems(
            [value.replace("_", " ").title() for value in CONTRACT_STATUS_CHOICES]
        )
        core_form.addRow("Status", self.status_combo)

        self.summary_edit = QPlainTextEdit()
        self.summary_edit.setMinimumHeight(110)
        core_form.addRow("Summary", self.summary_edit)

        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setMinimumHeight(120)
        core_form.addRow("Notes", self.notes_edit)
        core_layout.addLayout(core_form)
        overview_layout.addWidget(core_box)

        lifecycle_box, lifecycle_layout = _create_standard_section(
            self,
            "Lifecycle Dates",
            "Keep the contract timeline in one place so notice windows, renewals, and reversion points stay visible.",
        )
        lifecycle_grid = QGridLayout()
        lifecycle_grid.setContentsMargins(0, 0, 0, 0)
        lifecycle_grid.setHorizontalSpacing(12)
        lifecycle_grid.setVerticalSpacing(10)

        def _add_lifecycle_field(row: int, column: int, label_text: str, widget: QLineEdit) -> None:
            widget.setPlaceholderText("YYYY-MM-DD")
            lifecycle_grid.addWidget(QLabel(label_text), row, column * 2)
            lifecycle_grid.addWidget(widget, row, column * 2 + 1)

        self.draft_edit = QLineEdit()
        self.signature_edit = QLineEdit()
        self.effective_edit = QLineEdit()
        self.start_edit = QLineEdit()
        self.end_edit = QLineEdit()
        self.renewal_edit = QLineEdit()
        self.notice_edit = QLineEdit()
        self.reversion_edit = QLineEdit()
        self.termination_edit = QLineEdit()
        self.option_periods_edit = QLineEdit()

        _add_lifecycle_field(0, 0, "Draft Date", self.draft_edit)
        _add_lifecycle_field(0, 1, "Signature Date", self.signature_edit)
        _add_lifecycle_field(1, 0, "Effective Date", self.effective_edit)
        _add_lifecycle_field(1, 1, "Start Date", self.start_edit)
        _add_lifecycle_field(2, 0, "End Date", self.end_edit)
        _add_lifecycle_field(2, 1, "Renewal Date", self.renewal_edit)
        _add_lifecycle_field(3, 0, "Notice Deadline", self.notice_edit)
        _add_lifecycle_field(3, 1, "Reversion Date", self.reversion_edit)
        _add_lifecycle_field(4, 0, "Termination Date", self.termination_edit)
        lifecycle_grid.addWidget(QLabel("Option Periods"), 4, 2)
        lifecycle_grid.addWidget(self.option_periods_edit, 4, 3)
        lifecycle_grid.setColumnStretch(1, 1)
        lifecycle_grid.setColumnStretch(3, 1)
        lifecycle_layout.addLayout(lifecycle_grid)
        overview_layout.addWidget(lifecycle_box)
        overview_layout.addStretch(1)
        tabs.addTab(overview_scroll, "Overview")

        links_scroll, _, links_layout = _create_scrollable_dialog_content(self)
        repertoire_box, repertoire_layout = _create_standard_section(
            self,
            "Linked Repertoire",
            "Reference the related works, tracks, and releases so the contract stays connected to the assets it governs.",
        )
        repertoire_form = QFormLayout()
        _configure_standard_form_layout(repertoire_form)

        self.work_ids_edit = QLineEdit()
        self.work_ids_edit.setPlaceholderText("Comma-separated work IDs")
        repertoire_form.addRow("Linked Work IDs", self.work_ids_edit)

        self.track_ids_edit = QLineEdit()
        self.track_ids_edit.setPlaceholderText("Comma-separated track IDs")
        repertoire_form.addRow("Linked Track IDs", self.track_ids_edit)

        self.release_ids_edit = QLineEdit()
        self.release_ids_edit.setPlaceholderText("Comma-separated release IDs")
        repertoire_form.addRow("Linked Release IDs", self.release_ids_edit)
        repertoire_layout.addLayout(repertoire_form)
        links_layout.addWidget(repertoire_box)

        parties_box, parties_layout = _create_standard_section(
            self,
            "Linked Parties",
            "Use one line per party in the form `party_id|role_label|primary` or `party_name|role_label|primary`.",
        )
        self.parties_edit = QPlainTextEdit()
        self.parties_edit.setPlaceholderText(
            "One line per party: party_id|role_label|primary\nOr: party_name|role_label|primary"
        )
        self.parties_edit.setMinimumHeight(180)
        parties_layout.addWidget(self.parties_edit)
        links_layout.addWidget(parties_box)
        links_layout.addStretch(1)
        tabs.addTab(links_scroll, "Links and Parties")

        obligations_scroll, _, obligations_layout = _create_scrollable_dialog_content(self)
        obligations_box, obligations_box_layout = _create_standard_section(
            self,
            "Obligations",
            "Use one line per obligation in the form `type|title|due_date|follow_up_date|reminder_date|completed`.",
        )
        self.obligations_edit = QPlainTextEdit()
        self.obligations_edit.setPlaceholderText(
            "One line per obligation: type|title|due_date|follow_up_date|reminder_date|completed"
        )
        self.obligations_edit.setMinimumHeight(260)
        obligations_box_layout.addWidget(self.obligations_edit)
        obligations_layout.addWidget(obligations_box)
        obligations_layout.addStretch(1)
        tabs.addTab(obligations_scroll, "Obligations")

        documents_scroll, _, documents_layout = _create_scrollable_dialog_content(self)
        documents_box, documents_box_layout = _create_standard_section(
            self,
            "Document Versions",
            "Use one line per document in the form `title|type|version|source_path|signed_all|active|storage_mode`.",
        )
        docs_label_row = QHBoxLayout()
        docs_label_row.setContentsMargins(0, 0, 0, 0)
        docs_label_row.setSpacing(8)
        docs_label_row.addStretch(1)
        add_file_button = QPushButton("Append File…")
        add_file_button.clicked.connect(self._append_document_file)
        docs_label_row.addWidget(add_file_button)
        documents_box_layout.addLayout(docs_label_row)

        self.documents_edit = QPlainTextEdit()
        self.documents_edit.setPlaceholderText(
            "One line per document: title|type|version|source_path|signed_all|active|storage_mode"
        )
        self.documents_edit.setMinimumHeight(260)
        documents_box_layout.addWidget(self.documents_edit)
        documents_layout.addWidget(documents_box)
        documents_layout.addStretch(1)
        tabs.addTab(documents_scroll, "Documents")

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        save_button = buttons.button(QDialogButtonBox.Save)
        if save_button is not None:
            save_button.setText("Save Contract")
            save_button.setDefault(True)
        root.addWidget(buttons)
        _apply_compact_dialog_control_heights(self)

        if detail is not None:
            contract = detail.contract
            self.title_edit.setText(contract.title)
            self.type_edit.setText(contract.contract_type or "")
            self.status_combo.setCurrentText(contract.status.replace("_", " ").title())
            self.draft_edit.setText(contract.draft_date or "")
            self.signature_edit.setText(contract.signature_date or "")
            self.effective_edit.setText(contract.effective_date or "")
            self.start_edit.setText(contract.start_date or "")
            self.end_edit.setText(contract.end_date or "")
            self.renewal_edit.setText(contract.renewal_date or "")
            self.notice_edit.setText(contract.notice_deadline or "")
            self.option_periods_edit.setText(contract.option_periods or "")
            self.reversion_edit.setText(contract.reversion_date or "")
            self.termination_edit.setText(contract.termination_date or "")
            self.summary_edit.setPlainText(contract.summary or "")
            self.notes_edit.setPlainText(contract.notes or "")
            self.work_ids_edit.setText(", ".join(str(item) for item in detail.work_ids))
            self.track_ids_edit.setText(", ".join(str(item) for item in detail.track_ids))
            self.release_ids_edit.setText(", ".join(str(item) for item in detail.release_ids))
            self.parties_edit.setPlainText(
                "\n".join(
                    f"{item.party_id}|{item.role_label}|{'1' if item.is_primary else '0'}"
                    for item in detail.parties
                )
            )
            self.obligations_edit.setPlainText(
                "\n".join(
                    "|".join(
                        [
                            item.obligation_type,
                            item.title,
                            item.due_date or "",
                            item.follow_up_date or "",
                            item.reminder_date or "",
                            "1" if item.completed else "0",
                        ]
                    )
                    for item in detail.obligations
                )
            )
            self.documents_edit.setPlainText(
                "\n".join(
                    "|".join(
                        [
                            item.title,
                            item.document_type,
                            item.version_label or "",
                            (
                                str(resolved)
                                if (
                                    item.file_path
                                    and (
                                        resolved := self.contract_service.resolve_document_path(
                                            item.file_path
                                        )
                                    )
                                    is not None
                                )
                                else ""
                            ),
                            "1" if item.signed_by_all_parties else "0",
                            "1" if item.active_flag else "0",
                            item.storage_mode or "",
                        ]
                    )
                    for item in detail.documents
                )
            )

    def _append_document_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select Contract Document", "")
        if not path:
            return
        title = path.rsplit("/", 1)[-1]
        line = f"{title}|signed_agreement||{path}|1|1|managed_file"
        current = self.documents_edit.toPlainText().strip()
        self.documents_edit.setPlainText(f"{current}\n{line}" if current else line)

    def payload(self) -> ContractPayload:
        parties: list[ContractPartyPayload] = []
        for line in self.parties_edit.toPlainText().splitlines():
            parts = [part.strip() for part in line.split("|")]
            if not parts or not parts[0]:
                continue
            party_id = int(parts[0]) if parts[0].isdigit() else None
            parties.append(
                ContractPartyPayload(
                    party_id=party_id,
                    name=None if party_id is not None else parts[0],
                    role_label=parts[1] if len(parts) > 1 and parts[1] else "counterparty",
                    is_primary=_parse_bool_token(parts[2]) if len(parts) > 2 else False,
                )
            )
        obligations: list[ContractObligationPayload] = []
        for line in self.obligations_edit.toPlainText().splitlines():
            parts = [part.strip() for part in line.split("|")]
            if len(parts) < 2 or not parts[1]:
                continue
            obligations.append(
                ContractObligationPayload(
                    obligation_type=parts[0] or "other",
                    title=parts[1],
                    due_date=parts[2] if len(parts) > 2 and parts[2] else None,
                    follow_up_date=parts[3] if len(parts) > 3 and parts[3] else None,
                    reminder_date=parts[4] if len(parts) > 4 and parts[4] else None,
                    completed=_parse_bool_token(parts[5]) if len(parts) > 5 else False,
                )
            )
        documents: list[ContractDocumentPayload] = []
        for line in self.documents_edit.toPlainText().splitlines():
            parts = [part.strip() for part in line.split("|")]
            if len(parts) < 1 or not parts[0]:
                continue
            source_path = parts[3] if len(parts) > 3 and parts[3] else None
            storage_mode = (
                normalize_storage_mode(parts[6], default=None) if len(parts) > 6 else None
            )
            documents.append(
                ContractDocumentPayload(
                    title=parts[0],
                    document_type=parts[1] if len(parts) > 1 and parts[1] else "other",
                    version_label=parts[2] if len(parts) > 2 and parts[2] else None,
                    source_path=source_path,
                    stored_path=None if source_path else None,
                    signed_by_all_parties=_parse_bool_token(parts[4]) if len(parts) > 4 else False,
                    active_flag=_parse_bool_token(parts[5]) if len(parts) > 5 else False,
                    storage_mode=storage_mode,
                )
            )
        return ContractPayload(
            title=self.title_edit.text().strip(),
            contract_type=self.type_edit.text().strip() or None,
            draft_date=self.draft_edit.text().strip() or None,
            signature_date=self.signature_edit.text().strip() or None,
            effective_date=self.effective_edit.text().strip() or None,
            start_date=self.start_edit.text().strip() or None,
            end_date=self.end_edit.text().strip() or None,
            renewal_date=self.renewal_edit.text().strip() or None,
            notice_deadline=self.notice_edit.text().strip() or None,
            option_periods=self.option_periods_edit.text().strip() or None,
            reversion_date=self.reversion_edit.text().strip() or None,
            termination_date=self.termination_edit.text().strip() or None,
            status=self.status_combo.currentText().strip().lower().replace(" ", "_"),
            summary=self.summary_edit.toPlainText().strip() or None,
            notes=self.notes_edit.toPlainText().strip() or None,
            parties=parties,
            obligations=obligations,
            documents=documents,
            work_ids=_parse_int_list(self.work_ids_edit.text()),
            track_ids=_parse_int_list(self.track_ids_edit.text()),
            release_ids=_parse_int_list(self.release_ids_edit.text()),
        )


class ContractBrowserPanel(QWidget):
    """Browse and edit contract lifecycle records inside a workspace panel."""

    def __init__(self, *, contract_service_provider, parent=None):
        super().__init__(parent)
        self.contract_service_provider = contract_service_provider
        self.setObjectName("contractBrowserPanel")
        _apply_standard_widget_chrome(self, "contractBrowserPanel")

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(14)
        _add_standard_dialog_header(
            root,
            self,
            title="Contract Manager",
            subtitle=(
                "See which contracts are draft, active, expiring, or blocked by missing "
                "signatures and document versions."
            ),
        )

        controls_box, controls_layout = _create_standard_section(
            self,
            "Find and Manage",
            "Search by title, contract type, linked party, or summary, then act on the selected agreement.",
        )
        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(8)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search contracts by title, type, party, or summary...")
        self.search_edit.textChanged.connect(self.refresh)
        controls.addWidget(self.search_edit, 1)
        for label, handler in (
            ("Add", self.create_contract),
            ("Edit", self.edit_selected),
            ("Delete", self.delete_selected),
            ("Export Deadlines…", self.export_deadlines),
            ("Refresh", self.refresh),
        ):
            button = QPushButton(label)
            button.clicked.connect(handler)
            controls.addWidget(button)
        controls_layout.addLayout(controls)
        root.addWidget(controls_box)

        table_box, table_layout = _create_standard_section(
            self,
            "Contracts",
            "Double-click a row to open the editor for the selected contract.",
        )
        self.table = QTableWidget(0, 7, table_box)
        self.table.setHorizontalHeaderLabels(
            ["ID", "Title", "Type", "Status", "Notice", "Obligations", "Documents"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.table.doubleClicked.connect(lambda _index: self.edit_selected())
        table_layout.addWidget(self.table, 1)
        root.addWidget(table_box, 1)

        _apply_compact_dialog_control_heights(self)

        self.refresh()

    def _contract_service(self) -> ContractService | None:
        return self.contract_service_provider()

    def _restore_selection(self, contract_id: int | None) -> None:
        if not contract_id:
            return
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is None:
                continue
            try:
                current_contract_id = int(item.text())
            except Exception:
                continue
            if current_contract_id != int(contract_id):
                continue
            self.table.selectRow(row)
            return

    def focus_contract(self, contract_id: int | None) -> None:
        self.table.clearSelection()
        self._restore_selection(contract_id)

    def _selected_contract_id(self) -> int | None:
        selection_model = self.table.selectionModel()
        if selection_model is None:
            return None
        rows = selection_model.selectedRows()
        if not rows:
            return None
        item = self.table.item(rows[0].row(), 0)
        return int(item.text()) if item is not None else None

    def refresh(self) -> None:
        selected_contract_id = self._selected_contract_id()
        service = self._contract_service()
        if service is None:
            self.table.setRowCount(0)
            return
        rows = service.list_contracts(search_text=self.search_edit.text())
        self.table.setRowCount(0)
        for record in rows:
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = [
                str(record.id),
                record.title,
                record.contract_type or "",
                record.status.replace("_", " ").title(),
                record.notice_deadline or "",
                str(record.obligation_count),
                str(record.document_count),
            ]
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))
        self.table.resizeColumnsToContents()
        self._restore_selection(selected_contract_id)

    def create_contract(self) -> None:
        service = self._contract_service()
        if service is None:
            QMessageBox.warning(self, "Contract Manager", "Open a profile first.")
            return
        dialog = ContractEditorDialog(contract_service=service, parent=self)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            contract_id = service.create_contract(dialog.payload())
        except Exception as exc:
            QMessageBox.critical(self, "Contract Manager", str(exc))
            return
        self.refresh()
        self.focus_contract(contract_id)

    def edit_selected(self) -> None:
        service = self._contract_service()
        if service is None:
            QMessageBox.warning(self, "Contract Manager", "Open a profile first.")
            return
        contract_id = self._selected_contract_id()
        if not contract_id:
            QMessageBox.information(self, "Contract Manager", "Select a contract first.")
            return
        detail = service.fetch_contract_detail(contract_id)
        if detail is None:
            self.refresh()
            return
        dialog = ContractEditorDialog(contract_service=service, detail=detail, parent=self)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            service.update_contract(contract_id, dialog.payload())
        except Exception as exc:
            QMessageBox.critical(self, "Contract Manager", str(exc))
            return
        self.refresh()
        self.focus_contract(contract_id)

    def delete_selected(self) -> None:
        service = self._contract_service()
        if service is None:
            QMessageBox.warning(self, "Contract Manager", "Open a profile first.")
            return
        contract_id = self._selected_contract_id()
        if not contract_id:
            QMessageBox.information(self, "Contract Manager", "Select a contract first.")
            return
        if (
            QMessageBox.question(self, "Delete Contract", "Delete the selected contract?")
            != QMessageBox.Yes
        ):
            return
        service.delete_contract(contract_id)
        self.refresh()

    def export_deadlines(self) -> None:
        service = self._contract_service()
        if service is None:
            QMessageBox.warning(self, "Contract Manager", "Open a profile first.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Upcoming Deadlines", "", "CSV Files (*.csv)"
        )
        if not path:
            return
        try:
            service.export_deadlines_csv(path)
        except Exception as exc:
            QMessageBox.critical(self, "Contract Manager", str(exc))


class ContractBrowserDialog(QDialog):
    """Compatibility dialog wrapper around the reusable contract manager panel."""

    def __init__(self, *, contract_service: ContractService, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Contract Manager")
        self.resize(1060, 700)
        self.setMinimumSize(940, 620)
        _apply_standard_dialog_chrome(self, "contractBrowserDialog")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.panel = ContractBrowserPanel(
            contract_service_provider=lambda: contract_service,
            parent=self,
        )
        root.addWidget(self.panel)

    def __getattr__(self, name: str):
        panel = self.__dict__.get("panel")
        if panel is not None and hasattr(panel, name):
            return getattr(panel, name)
        raise AttributeError(name)

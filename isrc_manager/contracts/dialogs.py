"""Contract manager dialogs."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

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
        self.resize(920, 760)

        root = QVBoxLayout(self)
        intro = QLabel(
            "Track lifecycle dates, linked parties, obligations, and document versions for one contract. "
            "Use the structured line formats below to keep related records together."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignTop)

        self.title_edit = QLineEdit()
        form.addRow("Title", self.title_edit)

        self.type_edit = QLineEdit()
        form.addRow("Contract Type", self.type_edit)

        self.status_combo = QComboBox()
        self.status_combo.addItems(
            [value.replace("_", " ").title() for value in CONTRACT_STATUS_CHOICES]
        )
        form.addRow("Status", self.status_combo)

        self.draft_edit = QLineEdit()
        self.draft_edit.setPlaceholderText("YYYY-MM-DD")
        form.addRow("Draft Date", self.draft_edit)

        self.signature_edit = QLineEdit()
        self.signature_edit.setPlaceholderText("YYYY-MM-DD")
        form.addRow("Signature Date", self.signature_edit)

        self.effective_edit = QLineEdit()
        self.effective_edit.setPlaceholderText("YYYY-MM-DD")
        form.addRow("Effective Date", self.effective_edit)

        self.start_edit = QLineEdit()
        self.start_edit.setPlaceholderText("YYYY-MM-DD")
        form.addRow("Start Date", self.start_edit)

        self.end_edit = QLineEdit()
        self.end_edit.setPlaceholderText("YYYY-MM-DD")
        form.addRow("End Date", self.end_edit)

        self.renewal_edit = QLineEdit()
        self.renewal_edit.setPlaceholderText("YYYY-MM-DD")
        form.addRow("Renewal Date", self.renewal_edit)

        self.notice_edit = QLineEdit()
        self.notice_edit.setPlaceholderText("YYYY-MM-DD")
        form.addRow("Notice Deadline", self.notice_edit)

        self.option_periods_edit = QLineEdit()
        form.addRow("Option Periods", self.option_periods_edit)

        self.reversion_edit = QLineEdit()
        self.reversion_edit.setPlaceholderText("YYYY-MM-DD")
        form.addRow("Reversion Date", self.reversion_edit)

        self.termination_edit = QLineEdit()
        self.termination_edit.setPlaceholderText("YYYY-MM-DD")
        form.addRow("Termination Date", self.termination_edit)

        self.summary_edit = QPlainTextEdit()
        self.summary_edit.setMaximumHeight(80)
        form.addRow("Summary", self.summary_edit)

        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setMaximumHeight(80)
        form.addRow("Notes", self.notes_edit)

        self.work_ids_edit = QLineEdit()
        self.work_ids_edit.setPlaceholderText("Comma-separated work IDs")
        form.addRow("Linked Work IDs", self.work_ids_edit)

        self.track_ids_edit = QLineEdit()
        self.track_ids_edit.setPlaceholderText("Comma-separated track IDs")
        form.addRow("Linked Track IDs", self.track_ids_edit)

        self.release_ids_edit = QLineEdit()
        self.release_ids_edit.setPlaceholderText("Comma-separated release IDs")
        form.addRow("Linked Release IDs", self.release_ids_edit)
        root.addLayout(form)

        self.parties_edit = QPlainTextEdit()
        self.parties_edit.setPlaceholderText(
            "One line per party: party_id|role_label|primary\nOr: party_name|role_label|primary"
        )
        self.parties_edit.setMinimumHeight(90)
        root.addWidget(QLabel("Linked Parties"))
        root.addWidget(self.parties_edit)

        self.obligations_edit = QPlainTextEdit()
        self.obligations_edit.setPlaceholderText(
            "One line per obligation: type|title|due_date|follow_up_date|reminder_date|completed"
        )
        self.obligations_edit.setMinimumHeight(90)
        root.addWidget(QLabel("Obligations"))
        root.addWidget(self.obligations_edit)

        docs_label_row = QHBoxLayout()
        docs_label_row.addWidget(QLabel("Documents"))
        docs_label_row.addStretch(1)
        add_file_button = QPushButton("Append File…")
        add_file_button.clicked.connect(self._append_document_file)
        docs_label_row.addWidget(add_file_button)
        root.addLayout(docs_label_row)

        self.documents_edit = QPlainTextEdit()
        self.documents_edit.setPlaceholderText(
            "One line per document: title|type|version|source_path|signed_all|active"
        )
        self.documents_edit.setMinimumHeight(110)
        root.addWidget(self.documents_edit)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        save_button = QPushButton("Save")
        save_button.clicked.connect(self.accept)
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        buttons.addWidget(save_button)
        buttons.addWidget(cancel_button)
        root.addLayout(buttons)

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
                            item.file_path or "",
                            "1" if item.signed_by_all_parties else "0",
                            "1" if item.active_flag else "0",
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
        line = f"{title}|signed_agreement||{path}|1|1"
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
            documents.append(
                ContractDocumentPayload(
                    title=parts[0],
                    document_type=parts[1] if len(parts) > 1 and parts[1] else "other",
                    version_label=parts[2] if len(parts) > 2 and parts[2] else None,
                    source_path=source_path,
                    stored_path=None if source_path else None,
                    signed_by_all_parties=_parse_bool_token(parts[4]) if len(parts) > 4 else False,
                    active_flag=_parse_bool_token(parts[5]) if len(parts) > 5 else False,
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


class ContractBrowserDialog(QDialog):
    """Browse and edit contract lifecycle records."""

    def __init__(self, *, contract_service: ContractService, parent=None):
        super().__init__(parent)
        self.contract_service = contract_service
        self.setWindowTitle("Contract Manager")
        self.resize(1000, 640)

        root = QVBoxLayout(self)
        intro = QLabel(
            "See which contracts are draft, active, expiring, or blocked by missing signatures and document versions."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        controls = QHBoxLayout()
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
        root.addLayout(controls)

        self.table = QTableWidget(0, 7, self)
        self.table.setHorizontalHeaderLabels(
            ["ID", "Title", "Type", "Status", "Notice", "Obligations", "Documents"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.doubleClicked.connect(lambda _index: self.edit_selected())
        root.addWidget(self.table, 1)

        self.refresh()

    def _selected_contract_id(self) -> int | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        item = self.table.item(rows[0].row(), 0)
        return int(item.text()) if item is not None else None

    def refresh(self) -> None:
        rows = self.contract_service.list_contracts(search_text=self.search_edit.text())
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

    def create_contract(self) -> None:
        dialog = ContractEditorDialog(contract_service=self.contract_service, parent=self)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            self.contract_service.create_contract(dialog.payload())
        except Exception as exc:
            QMessageBox.critical(self, "Contract Manager", str(exc))
            return
        self.refresh()

    def edit_selected(self) -> None:
        contract_id = self._selected_contract_id()
        if not contract_id:
            QMessageBox.information(self, "Contract Manager", "Select a contract first.")
            return
        detail = self.contract_service.fetch_contract_detail(contract_id)
        if detail is None:
            self.refresh()
            return
        dialog = ContractEditorDialog(
            contract_service=self.contract_service, detail=detail, parent=self
        )
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            self.contract_service.update_contract(contract_id, dialog.payload())
        except Exception as exc:
            QMessageBox.critical(self, "Contract Manager", str(exc))
            return
        self.refresh()

    def delete_selected(self) -> None:
        contract_id = self._selected_contract_id()
        if not contract_id:
            QMessageBox.information(self, "Contract Manager", "Select a contract first.")
            return
        if (
            QMessageBox.question(self, "Delete Contract", "Delete the selected contract?")
            != QMessageBox.Yes
        ):
            return
        self.contract_service.delete_contract(contract_id)
        self.refresh()

    def export_deadlines(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Upcoming Deadlines", "", "CSV Files (*.csv)"
        )
        if not path:
            return
        try:
            self.contract_service.export_deadlines_csv(path)
        except Exception as exc:
            QMessageBox.critical(self, "Contract Manager", str(exc))

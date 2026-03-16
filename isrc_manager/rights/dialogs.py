"""Rights matrix dialogs."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
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

from isrc_manager.contracts import ContractService
from isrc_manager.parties import PartyService

from .models import RIGHT_TYPE_CHOICES, RightPayload, RightRecord
from .service import RightsService


class RightEditorDialog(QDialog):
    """Create or edit a structured rights grant."""

    def __init__(
        self,
        *,
        rights_service: RightsService,
        party_service: PartyService,
        contract_service: ContractService,
        right: RightRecord | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.rights_service = rights_service
        self.party_service = party_service
        self.contract_service = contract_service
        self.right = right
        self.setWindowTitle("Edit Right" if right is not None else "Create Right")
        self.resize(680, 540)

        root = QVBoxLayout(self)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignTop)

        self.title_edit = QLineEdit()
        form.addRow("Title", self.title_edit)

        self.type_combo = QComboBox()
        self.type_combo.addItems([item.replace("_", " ").title() for item in RIGHT_TYPE_CHOICES])
        form.addRow("Right Type", self.type_combo)

        self.exclusive_checkbox = QCheckBox("Exclusive")
        self.perpetual_checkbox = QCheckBox("Perpetual")
        exclusivity_row = QHBoxLayout()
        exclusivity_row.addWidget(self.exclusive_checkbox)
        exclusivity_row.addWidget(self.perpetual_checkbox)
        exclusivity_row.addStretch(1)
        form.addRow("Flags", exclusivity_row)

        self.territory_edit = QLineEdit()
        form.addRow("Territory", self.territory_edit)

        self.media_use_edit = QLineEdit()
        form.addRow("Media / Use Type", self.media_use_edit)

        self.start_edit = QLineEdit()
        self.start_edit.setPlaceholderText("YYYY-MM-DD")
        form.addRow("Start Date", self.start_edit)

        self.end_edit = QLineEdit()
        self.end_edit.setPlaceholderText("YYYY-MM-DD")
        form.addRow("End Date", self.end_edit)

        self.granted_by_combo = QComboBox()
        self.granted_to_combo = QComboBox()
        self.retained_by_combo = QComboBox()
        self.contract_combo = QComboBox()
        self._populate_reference_combos()
        form.addRow("Granted By", self.granted_by_combo)
        form.addRow("Granted To", self.granted_to_combo)
        form.addRow("Retained By", self.retained_by_combo)
        form.addRow("Source Contract", self.contract_combo)

        self.work_id_edit = QLineEdit()
        form.addRow("Work ID", self.work_id_edit)
        self.track_id_edit = QLineEdit()
        form.addRow("Track ID", self.track_id_edit)
        self.release_id_edit = QLineEdit()
        form.addRow("Release ID", self.release_id_edit)

        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setMinimumHeight(100)
        form.addRow("Notes", self.notes_edit)
        root.addLayout(form)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        save_button = QPushButton("Save")
        save_button.clicked.connect(self.accept)
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        buttons.addWidget(save_button)
        buttons.addWidget(cancel_button)
        root.addLayout(buttons)

        if right is not None:
            self.title_edit.setText(right.title or "")
            self.type_combo.setCurrentText(right.right_type.replace("_", " ").title())
            self.exclusive_checkbox.setChecked(right.exclusive_flag)
            self.perpetual_checkbox.setChecked(right.perpetual_flag)
            self.territory_edit.setText(right.territory or "")
            self.media_use_edit.setText(right.media_use_type or "")
            self.start_edit.setText(right.start_date or "")
            self.end_edit.setText(right.end_date or "")
            self._set_combo_id(self.granted_by_combo, right.granted_by_party_id)
            self._set_combo_id(self.granted_to_combo, right.granted_to_party_id)
            self._set_combo_id(self.retained_by_combo, right.retained_by_party_id)
            self._set_combo_id(self.contract_combo, right.source_contract_id)
            self.work_id_edit.setText(str(right.work_id or ""))
            self.track_id_edit.setText(str(right.track_id or ""))
            self.release_id_edit.setText(str(right.release_id or ""))
            self.notes_edit.setPlainText(right.notes or "")

    def _populate_reference_combos(self) -> None:
        for combo in (
            self.granted_by_combo,
            self.granted_to_combo,
            self.retained_by_combo,
            self.contract_combo,
        ):
            combo.addItem("", None)
        for party in self.party_service.list_parties():
            label = party.display_name or party.legal_name
            self.granted_by_combo.addItem(label, party.id)
            self.granted_to_combo.addItem(label, party.id)
            self.retained_by_combo.addItem(label, party.id)
        for contract in self.contract_service.list_contracts():
            self.contract_combo.addItem(contract.title, contract.id)

    @staticmethod
    def _set_combo_id(combo: QComboBox, value: int | None) -> None:
        for index in range(combo.count()):
            if combo.itemData(index) == value:
                combo.setCurrentIndex(index)
                return

    def payload(self) -> RightPayload:
        return RightPayload(
            title=self.title_edit.text().strip() or None,
            right_type=self.type_combo.currentText().strip().lower().replace(" ", "_"),
            exclusive_flag=self.exclusive_checkbox.isChecked(),
            territory=self.territory_edit.text().strip() or None,
            media_use_type=self.media_use_edit.text().strip() or None,
            start_date=self.start_edit.text().strip() or None,
            end_date=self.end_edit.text().strip() or None,
            perpetual_flag=self.perpetual_checkbox.isChecked(),
            granted_by_party_id=self.granted_by_combo.currentData(),
            granted_to_party_id=self.granted_to_combo.currentData(),
            retained_by_party_id=self.retained_by_combo.currentData(),
            source_contract_id=self.contract_combo.currentData(),
            work_id=int(self.work_id_edit.text()) if self.work_id_edit.text().strip() else None,
            track_id=int(self.track_id_edit.text()) if self.track_id_edit.text().strip() else None,
            release_id=(
                int(self.release_id_edit.text()) if self.release_id_edit.text().strip() else None
            ),
            notes=self.notes_edit.toPlainText().strip() or None,
        )


class RightsBrowserDialog(QDialog):
    """Browse rights grants and conflicts."""

    def __init__(
        self,
        *,
        rights_service: RightsService,
        party_service: PartyService,
        contract_service: ContractService,
        parent=None,
    ):
        super().__init__(parent)
        self.rights_service = rights_service
        self.party_service = party_service
        self.contract_service = contract_service
        self.setWindowTitle("Rights Matrix")
        self.resize(1040, 640)

        root = QVBoxLayout(self)
        intro = QLabel(
            "Use the rights matrix to see who controls what, in which territory, and under which source contract."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        controls = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(
            "Search rights by type, territory, contract, or party..."
        )
        self.search_edit.textChanged.connect(self.refresh)
        controls.addWidget(self.search_edit, 1)
        for label, handler in (
            ("Add", self.create_right),
            ("Edit", self.edit_selected),
            ("Delete", self.delete_selected),
            ("Show Conflicts", self.show_conflicts),
            ("Refresh", self.refresh),
        ):
            button = QPushButton(label)
            button.clicked.connect(handler)
            controls.addWidget(button)
        root.addLayout(controls)

        self.table = QTableWidget(0, 7, self)
        self.table.setHorizontalHeaderLabels(
            ["ID", "Type", "Title", "Territory", "Exclusive", "Granted To", "Contract"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.doubleClicked.connect(lambda _index: self.edit_selected())
        root.addWidget(self.table, 1)

        self.refresh()

    def _selected_right_id(self) -> int | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        item = self.table.item(rows[0].row(), 0)
        return int(item.text()) if item is not None else None

    def refresh(self) -> None:
        rights = self.rights_service.list_rights(search_text=self.search_edit.text())
        self.table.setRowCount(0)
        for right in rights:
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = [
                str(right.id),
                right.right_type.replace("_", " ").title(),
                right.title or "",
                right.territory or "",
                "Yes" if right.exclusive_flag else "No",
                right.granted_to_name or "",
                right.source_contract_title or "",
            ]
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))
        self.table.resizeColumnsToContents()

    def create_right(self) -> None:
        dialog = RightEditorDialog(
            rights_service=self.rights_service,
            party_service=self.party_service,
            contract_service=self.contract_service,
            parent=self,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            self.rights_service.create_right(dialog.payload())
        except Exception as exc:
            QMessageBox.critical(self, "Rights Matrix", str(exc))
            return
        self.refresh()

    def edit_selected(self) -> None:
        right_id = self._selected_right_id()
        if not right_id:
            QMessageBox.information(self, "Rights Matrix", "Select a rights record first.")
            return
        right = self.rights_service.fetch_right(right_id)
        if right is None:
            self.refresh()
            return
        dialog = RightEditorDialog(
            rights_service=self.rights_service,
            party_service=self.party_service,
            contract_service=self.contract_service,
            right=right,
            parent=self,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            self.rights_service.update_right(right_id, dialog.payload())
        except Exception as exc:
            QMessageBox.critical(self, "Rights Matrix", str(exc))
            return
        self.refresh()

    def delete_selected(self) -> None:
        right_id = self._selected_right_id()
        if not right_id:
            QMessageBox.information(self, "Rights Matrix", "Select a rights record first.")
            return
        if (
            QMessageBox.question(self, "Delete Rights Record", "Delete the selected rights record?")
            != QMessageBox.Yes
        ):
            return
        self.rights_service.delete_right(right_id)
        self.refresh()

    def show_conflicts(self) -> None:
        conflicts = self.rights_service.detect_conflicts()
        if not conflicts:
            QMessageBox.information(
                self, "Rights Matrix", "No overlapping exclusive rights were detected."
            )
            return
        lines = [conflict.message for conflict in conflicts]
        QMessageBox.warning(self, "Rights Conflicts", "\n\n".join(lines))

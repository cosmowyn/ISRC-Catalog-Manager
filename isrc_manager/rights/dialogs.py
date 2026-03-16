"""Rights matrix dialogs."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
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

from isrc_manager.contracts import ContractService
from isrc_manager.parties import PartyService
from isrc_manager.ui_common import (
    _add_standard_dialog_header,
    _apply_compact_dialog_control_heights,
    _apply_standard_dialog_chrome,
    _configure_standard_form_layout,
    _create_scrollable_dialog_content,
    _create_standard_section,
)

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
        self.resize(820, 640)
        self.setMinimumSize(760, 560)
        _apply_standard_dialog_chrome(self, "rightEditorDialog")

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)
        _add_standard_dialog_header(
            root,
            self,
            title=self.windowTitle(),
            subtitle=(
                "Capture the scope of one rights grant, then link the parties, source "
                "contract, and related repertoire record."
            ),
        )

        self.granted_by_combo = QComboBox()
        self.granted_to_combo = QComboBox()
        self.retained_by_combo = QComboBox()
        self.contract_combo = QComboBox()
        self._populate_reference_combos()

        tabs = QTabWidget(self)
        root.addWidget(tabs, 1)

        definition_scroll, _, definition_layout = _create_scrollable_dialog_content(self)
        definition_box, definition_box_layout = _create_standard_section(
            self,
            "Rights Definition",
            "Describe the kind of right being granted, where it applies, and how long the grant lasts.",
        )
        definition_form = QFormLayout()
        _configure_standard_form_layout(definition_form)

        self.title_edit = QLineEdit()
        definition_form.addRow("Title", self.title_edit)

        self.type_combo = QComboBox()
        self.type_combo.addItems([item.replace("_", " ").title() for item in RIGHT_TYPE_CHOICES])
        definition_form.addRow("Right Type", self.type_combo)

        flags_widget = QWidget(self)
        flags_layout = QHBoxLayout(flags_widget)
        flags_layout.setContentsMargins(0, 0, 0, 0)
        flags_layout.setSpacing(10)
        self.exclusive_checkbox = QCheckBox("Exclusive")
        self.perpetual_checkbox = QCheckBox("Perpetual")
        flags_layout.addWidget(self.exclusive_checkbox)
        flags_layout.addWidget(self.perpetual_checkbox)
        flags_layout.addStretch(1)
        definition_form.addRow("Flags", flags_widget)

        self.territory_edit = QLineEdit()
        definition_form.addRow("Territory", self.territory_edit)

        self.media_use_edit = QLineEdit()
        definition_form.addRow("Media / Use Type", self.media_use_edit)
        definition_box_layout.addLayout(definition_form)
        definition_layout.addWidget(definition_box)

        date_box, date_box_layout = _create_standard_section(
            self,
            "Grant Window",
            "Use start and end dates when the right has a limited term. Perpetual grants can leave the end date empty.",
        )
        date_grid = QGridLayout()
        date_grid.setContentsMargins(0, 0, 0, 0)
        date_grid.setHorizontalSpacing(12)
        date_grid.setVerticalSpacing(10)
        self.start_edit = QLineEdit()
        self.start_edit.setPlaceholderText("YYYY-MM-DD")
        self.end_edit = QLineEdit()
        self.end_edit.setPlaceholderText("YYYY-MM-DD")
        date_grid.addWidget(QLabel("Start Date"), 0, 0)
        date_grid.addWidget(self.start_edit, 0, 1)
        date_grid.addWidget(QLabel("End Date"), 0, 2)
        date_grid.addWidget(self.end_edit, 0, 3)
        date_grid.setColumnStretch(1, 1)
        date_grid.setColumnStretch(3, 1)
        date_box_layout.addLayout(date_grid)
        definition_layout.addWidget(date_box)
        definition_layout.addStretch(1)
        tabs.addTab(definition_scroll, "Definition")

        links_scroll, _, links_layout = _create_scrollable_dialog_content(self)
        parties_box, parties_layout = _create_standard_section(
            self,
            "Parties and Source",
            "Link the grantor, grantee, retained rights holder, and the source contract that created the right.",
        )
        parties_form = QFormLayout()
        _configure_standard_form_layout(parties_form)
        parties_form.addRow("Granted By", self.granted_by_combo)
        parties_form.addRow("Granted To", self.granted_to_combo)
        parties_form.addRow("Retained By", self.retained_by_combo)
        parties_form.addRow("Source Contract", self.contract_combo)
        parties_layout.addLayout(parties_form)
        links_layout.addWidget(parties_box)

        repertoire_box, repertoire_layout = _create_standard_section(
            self,
            "Linked Repertoire",
            "Reference the specific work, track, or release that this rights record applies to.",
        )
        repertoire_form = QFormLayout()
        _configure_standard_form_layout(repertoire_form)
        self.work_id_edit = QLineEdit()
        repertoire_form.addRow("Work ID", self.work_id_edit)
        self.track_id_edit = QLineEdit()
        repertoire_form.addRow("Track ID", self.track_id_edit)
        self.release_id_edit = QLineEdit()
        repertoire_form.addRow("Release ID", self.release_id_edit)
        repertoire_layout.addLayout(repertoire_form)
        links_layout.addWidget(repertoire_box)

        notes_box, notes_layout = _create_standard_section(
            self,
            "Notes",
            "Capture territory nuances, carve-outs, or any supporting context that matters later.",
        )
        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setMinimumHeight(180)
        notes_layout.addWidget(self.notes_edit)
        links_layout.addWidget(notes_box)
        links_layout.addStretch(1)
        tabs.addTab(links_scroll, "Links and Notes")

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        save_button = buttons.button(QDialogButtonBox.Save)
        if save_button is not None:
            save_button.setText("Save Right")
            save_button.setDefault(True)
        root.addWidget(buttons)
        _apply_compact_dialog_control_heights(self)

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
        self.resize(1080, 700)
        self.setMinimumSize(960, 620)
        _apply_standard_dialog_chrome(self, "rightsBrowserDialog")

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)
        _add_standard_dialog_header(
            root,
            self,
            title="Rights Matrix",
            subtitle=(
                "See who controls what, in which territory, and under which source "
                "contract without leaving the catalog."
            ),
        )

        controls_box, controls_layout = _create_standard_section(
            self,
            "Find and Manage",
            "Search by right type, territory, contract, or party, then open the selected record or review conflicts.",
        )
        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(8)
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
        controls_layout.addLayout(controls)
        root.addWidget(controls_box)

        table_box, table_layout = _create_standard_section(
            self,
            "Rights Records",
            "Each row is one rights grant. Double-click a row to edit it.",
        )
        self.table = QTableWidget(0, 7, table_box)
        self.table.setHorizontalHeaderLabels(
            ["ID", "Type", "Title", "Territory", "Exclusive", "Granted To", "Contract"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.table.doubleClicked.connect(lambda _index: self.edit_selected())
        table_layout.addWidget(self.table, 1)
        root.addWidget(table_box, 1)

        _apply_compact_dialog_control_heights(self)

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

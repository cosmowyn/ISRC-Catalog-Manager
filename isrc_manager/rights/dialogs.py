"""Rights matrix dialogs."""

from __future__ import annotations

from functools import partial

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QCompleter,
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
from isrc_manager.parties.dialogs import PartyEditorDialog
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
        self.granted_by_field = self._build_party_reference_field(
            self.granted_by_combo,
            label="Granted By",
        )
        self.granted_to_field = self._build_party_reference_field(
            self.granted_to_combo,
            label="Granted To",
        )
        self.retained_by_field = self._build_party_reference_field(
            self.retained_by_combo,
            label="Retained By",
        )
        self.contract_combo = QComboBox()
        self.work_combo = QComboBox()
        self.track_combo = QComboBox()
        self.release_combo = QComboBox()
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
        parties_form.addRow("Granted By", self.granted_by_field)
        parties_form.addRow("Granted To", self.granted_to_field)
        parties_form.addRow("Retained By", self.retained_by_field)
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
        repertoire_form.addRow("Work", self.work_combo)
        repertoire_form.addRow("Track", self.track_combo)
        repertoire_form.addRow("Release", self.release_combo)
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
            self._set_combo_id(self.work_combo, right.work_id)
            self._set_combo_id(self.track_combo, right.track_id)
            self._set_combo_id(self.release_combo, right.release_id)
            self.notes_edit.setPlainText(right.notes or "")
        self._sync_party_action_state()

    def _party_choice_label(self, party) -> str:
        primary = (
            str(getattr(party, "display_name", "") or "").strip()
            or str(getattr(party, "artist_name", "") or "").strip()
            or str(getattr(party, "company_name", "") or "").strip()
            or str(getattr(party, "legal_name", "") or "").strip()
            or f"Party #{int(party.id)}"
        )
        legal_name = str(getattr(party, "legal_name", "") or "").strip()
        if legal_name and legal_name.casefold() != primary.casefold():
            return f"{primary} ({legal_name})"
        return primary

    def _party_combos(self) -> tuple[QComboBox, QComboBox, QComboBox]:
        return (
            self.granted_by_combo,
            self.granted_to_combo,
            self.retained_by_combo,
        )

    @staticmethod
    def _current_combo_id(combo: QComboBox) -> int | None:
        data = combo.currentData()
        if data in (None, ""):
            return None
        try:
            return int(data)
        except Exception:
            return None

    def _build_party_reference_field(self, combo: QComboBox, *, label: str) -> QWidget:
        container = QWidget(self)
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.NoInsert)
        layout.addWidget(combo, 1)

        new_button = QPushButton("New Party...", container)
        new_button.clicked.connect(partial(self._create_party_for_combo, combo))
        layout.addWidget(new_button)

        edit_button = QPushButton("Edit Party...", container)
        edit_button.clicked.connect(partial(self._edit_party_for_combo, combo, label))
        layout.addWidget(edit_button)

        if combo is self.granted_by_combo:
            self.granted_by_new_button = new_button
            self.granted_by_edit_button = edit_button
        elif combo is self.granted_to_combo:
            self.granted_to_new_button = new_button
            self.granted_to_edit_button = edit_button
        else:
            self.retained_by_new_button = new_button
            self.retained_by_edit_button = edit_button

        combo.currentIndexChanged.connect(self._sync_party_action_state)
        combo.currentTextChanged.connect(self._sync_party_action_state)
        return container

    def _refresh_party_combos(
        self,
        *,
        overrides: dict[QComboBox, int | None] | None = None,
    ) -> None:
        selected_ids = {
            combo: self._current_combo_id(combo)
            for combo in self._party_combos()
        }
        if overrides:
            selected_ids.update(overrides)
        labels: list[str] = []
        parties = list(self.party_service.list_parties() or [])
        for combo in self._party_combos():
            previous_state = combo.blockSignals(True)
            try:
                combo.clear()
                combo.addItem("", None)
                for party in parties:
                    label = self._party_choice_label(party)
                    combo.addItem(label, int(party.id))
                    labels.append(label)
                selected_id = selected_ids.get(combo)
                if selected_id is not None and combo.findData(int(selected_id)) < 0:
                    missing_label = f"Missing Party #{int(selected_id)}"
                    combo.addItem(missing_label, int(selected_id))
                    labels.append(missing_label)
                self._set_combo_id(combo, selected_id)
            finally:
                combo.blockSignals(previous_state)
            completer = QCompleter(labels, combo)
            completer.setCaseSensitivity(Qt.CaseInsensitive)
            combo.setCompleter(completer)
        self._sync_party_action_state()

    def _sync_party_action_state(self, *_args) -> None:
        self.granted_by_new_button.setEnabled(True)
        self.granted_to_new_button.setEnabled(True)
        self.retained_by_new_button.setEnabled(True)
        self.granted_by_edit_button.setEnabled(
            self._current_combo_id(self.granted_by_combo) is not None
        )
        self.granted_to_edit_button.setEnabled(
            self._current_combo_id(self.granted_to_combo) is not None
        )
        self.retained_by_edit_button.setEnabled(
            self._current_combo_id(self.retained_by_combo) is not None
        )

    def _create_party_for_combo(self, combo: QComboBox) -> None:
        dialog = PartyEditorDialog(party_service=self.party_service, parent=self)
        if not dialog.exec():
            return
        try:
            party_id = int(self.party_service.create_party(dialog.payload()))
        except Exception as exc:
            QMessageBox.warning(self, "Rights Matrix", str(exc))
            return
        self._refresh_party_combos(overrides={combo: party_id})

    def _edit_party_for_combo(self, combo: QComboBox, label: str) -> None:
        party_id = self._current_combo_id(combo)
        if party_id is None:
            QMessageBox.information(
                self,
                "Rights Matrix",
                f"Select a Party in {label} first.",
            )
            return
        record = self.party_service.fetch_party(int(party_id))
        if record is None:
            QMessageBox.warning(
                self,
                "Rights Matrix",
                f"Party #{int(party_id)} could not be loaded.",
            )
            return
        dialog = PartyEditorDialog(party_service=self.party_service, party=record, parent=self)
        if not dialog.exec():
            return
        try:
            self.party_service.update_party(int(record.id), dialog.payload())
        except Exception as exc:
            QMessageBox.warning(self, "Rights Matrix", str(exc))
            return
        self._refresh_party_combos(overrides={combo: int(record.id)})

    def _populate_reference_combos(self) -> None:
        for combo in (
            self.granted_by_combo,
            self.granted_to_combo,
            self.retained_by_combo,
            self.contract_combo,
            self.work_combo,
            self.track_combo,
            self.release_combo,
        ):
            combo.addItem("", None)
            combo.setEditable(True)
            combo.setInsertPolicy(QComboBox.NoInsert)
        self._refresh_party_combos()
        for contract in self.contract_service.list_contracts():
            self.contract_combo.addItem(contract.title, contract.id)
        conn = getattr(self.rights_service, "conn", None)
        if conn is not None:
            for work_id, title, iswc in conn.execute(
                """
                SELECT id, title, COALESCE(iswc, '')
                FROM Works
                ORDER BY title, id
                """
            ).fetchall():
                label = " / ".join(part for part in (str(title or ""), str(iswc or "")) if part)
                self.work_combo.addItem(label, int(work_id))
            for track_id, track_title, artist_name in conn.execute(
                """
                SELECT
                    t.id,
                    t.track_title,
                    COALESCE(a.name, '')
                FROM Tracks t
                LEFT JOIN Artists a ON a.id = t.main_artist_id
                ORDER BY t.track_title, t.id
                """
            ).fetchall():
                label = " / ".join(
                    part for part in (str(track_title or ""), str(artist_name or "")) if part
                )
                self.track_combo.addItem(label, int(track_id))
            for release_id, title, primary_artist in conn.execute(
                """
                SELECT id, title, COALESCE(primary_artist, '')
                FROM Releases
                ORDER BY title, id
                """
            ).fetchall():
                label = " / ".join(
                    part for part in (str(title or ""), str(primary_artist or "")) if part
                )
                self.release_combo.addItem(label, int(release_id))
        for combo in (
            self.granted_by_combo,
            self.granted_to_combo,
            self.retained_by_combo,
            self.contract_combo,
            self.work_combo,
            self.track_combo,
            self.release_combo,
        ):
            labels = [
                combo.itemText(index) for index in range(combo.count()) if combo.itemText(index)
            ]
            completer = QCompleter(labels, combo)
            completer.setCaseSensitivity(Qt.CaseInsensitive)
            combo.setCompleter(completer)

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
            work_id=self.work_combo.currentData(),
            track_id=self.track_combo.currentData(),
            release_id=self.release_combo.currentData(),
            notes=self.notes_edit.toPlainText().strip() or None,
        )


class RightsBrowserPanel(QWidget):
    """Browse rights grants and conflicts inside a workspace panel."""

    def __init__(
        self,
        *,
        rights_service_provider,
        party_service_provider,
        contract_service_provider,
        parent=None,
    ):
        super().__init__(parent)
        self.rights_service_provider = rights_service_provider
        self.party_service_provider = party_service_provider
        self.contract_service_provider = contract_service_provider
        self.setObjectName("rightsBrowserPanel")
        _apply_standard_widget_chrome(self, "rightsBrowserPanel")

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
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
            "Search by right type, territory, contract, or party, then work from the selected record.",
        )
        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(10)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(
            "Search rights by type, territory, contract, or party..."
        )
        self.search_edit.textChanged.connect(self.refresh)
        controls.addWidget(self.search_edit, 1)
        controls_layout.addLayout(controls)
        action_buttons: list[QPushButton] = []
        for label, handler in (
            ("Add", self.create_right),
            ("Edit", self.edit_selected),
            ("Show Conflicts", self.show_conflicts),
            ("Delete", self.delete_selected),
            ("Refresh", self.refresh),
        ):
            button = QPushButton(label)
            button.clicked.connect(handler)
            action_buttons.append(button)
        self.manage_actions_cluster = _create_action_button_cluster(
            self,
            action_buttons,
            columns=2,
            min_button_width=160,
            span_last_row=True,
        )
        self.manage_actions_cluster.setObjectName("rightsMatrixActionsCluster")
        controls_layout.addWidget(self.manage_actions_cluster)
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

    def _rights_service(self) -> RightsService | None:
        return self.rights_service_provider()

    def _party_service(self) -> PartyService | None:
        return self.party_service_provider()

    def _contract_service(self) -> ContractService | None:
        return self.contract_service_provider()

    def _restore_selection(self, right_id: int | None) -> None:
        if not right_id:
            return
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is None:
                continue
            try:
                current_right_id = int(item.text())
            except Exception:
                continue
            if current_right_id != int(right_id):
                continue
            self.table.selectRow(row)
            return

    def focus_right(self, right_id: int | None) -> None:
        self.table.clearSelection()
        self._restore_selection(right_id)

    def _selected_right_id(self) -> int | None:
        selection_model = self.table.selectionModel()
        if selection_model is None:
            return None
        rows = selection_model.selectedRows()
        if not rows:
            return None
        item = self.table.item(rows[0].row(), 0)
        return int(item.text()) if item is not None else None

    def refresh(self) -> None:
        selected_right_id = self._selected_right_id()
        service = self._rights_service()
        if service is None:
            self.table.setRowCount(0)
            return
        rights = service.list_rights(search_text=self.search_edit.text())
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
        self._restore_selection(selected_right_id)

    def create_right(self) -> None:
        rights_service = self._rights_service()
        party_service = self._party_service()
        contract_service = self._contract_service()
        if rights_service is None or party_service is None or contract_service is None:
            QMessageBox.warning(self, "Rights Matrix", "Open a profile first.")
            return
        dialog = RightEditorDialog(
            rights_service=rights_service,
            party_service=party_service,
            contract_service=contract_service,
            parent=self,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            right_id = rights_service.create_right(dialog.payload())
        except Exception as exc:
            QMessageBox.critical(self, "Rights Matrix", str(exc))
            return
        self.refresh()
        self.focus_right(right_id)

    def edit_selected(self) -> None:
        rights_service = self._rights_service()
        party_service = self._party_service()
        contract_service = self._contract_service()
        if rights_service is None or party_service is None or contract_service is None:
            QMessageBox.warning(self, "Rights Matrix", "Open a profile first.")
            return
        right_id = self._selected_right_id()
        if not right_id:
            QMessageBox.information(self, "Rights Matrix", "Select a rights record first.")
            return
        right = rights_service.fetch_right(right_id)
        if right is None:
            self.refresh()
            return
        dialog = RightEditorDialog(
            rights_service=rights_service,
            party_service=party_service,
            contract_service=contract_service,
            right=right,
            parent=self,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            rights_service.update_right(right_id, dialog.payload())
        except Exception as exc:
            QMessageBox.critical(self, "Rights Matrix", str(exc))
            return
        self.refresh()
        self.focus_right(right_id)

    def delete_selected(self) -> None:
        service = self._rights_service()
        if service is None:
            QMessageBox.warning(self, "Rights Matrix", "Open a profile first.")
            return
        right_id = self._selected_right_id()
        if not right_id:
            QMessageBox.information(self, "Rights Matrix", "Select a rights record first.")
            return
        if not _confirm_destructive_action(
            self,
            title="Delete Rights Record",
            prompt="Delete the selected rights record?",
        ):
            return
        service.delete_right(right_id)
        self.refresh()

    def show_conflicts(self) -> None:
        service = self._rights_service()
        if service is None:
            QMessageBox.warning(self, "Rights Matrix", "Open a profile first.")
            return
        conflicts = service.detect_conflicts()
        if not conflicts:
            QMessageBox.information(
                self, "Rights Matrix", "No overlapping exclusive rights were detected."
            )
            return
        lines = [conflict.message for conflict in conflicts]
        QMessageBox.warning(self, "Rights Conflicts", "\n\n".join(lines))


class RightsBrowserDialog(QDialog):
    """Compatibility dialog wrapper around the reusable rights browser panel."""

    def __init__(
        self,
        *,
        rights_service: RightsService,
        party_service: PartyService,
        contract_service: ContractService,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Rights Matrix")
        self.resize(1080, 700)
        self.setMinimumSize(960, 620)
        _apply_standard_dialog_chrome(self, "rightsBrowserDialog")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.panel = RightsBrowserPanel(
            rights_service_provider=lambda: rights_service,
            party_service_provider=lambda: party_service,
            contract_service_provider=lambda: contract_service,
            parent=self,
        )
        root.addWidget(self.panel)

    def __getattr__(self, name: str):
        panel = self.__dict__.get("panel")
        if panel is not None and hasattr(panel, name):
            return getattr(panel, name)
        raise AttributeError(name)

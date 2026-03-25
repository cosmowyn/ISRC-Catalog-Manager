"""Work manager dialogs."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from isrc_manager.parties import PartyRecord
from isrc_manager.parties.dialogs import PartyEditorDialog
from isrc_manager.selection_scope import (
    SelectionScopeBanner,
    SelectionScopeState,
    TrackChoice,
    TrackSelectionChooserDialog,
    build_selection_preview,
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

from .models import (
    WORK_CREATOR_ROLE_CHOICES,
    WORK_STATUS_CHOICES,
    WorkContributorPayload,
    WorkPayload,
    WorkRecord,
)
from .service import WorkService


class WorkEditorDialog(QDialog):
    """Create or edit a first-class composition/work record."""

    def __init__(
        self,
        *,
        work_service: WorkService,
        track_title_resolver,
        selected_track_ids_provider,
        work: WorkRecord | None = None,
        contributors: list[WorkContributorPayload] | None = None,
        track_ids: list[int] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.work_service = work_service
        self.party_service = getattr(work_service, "party_service", None)
        self.track_title_resolver = track_title_resolver
        self.selected_track_ids_provider = selected_track_ids_provider
        self.work = work
        self.setWindowTitle("Edit Work" if work is not None else "Create Work")
        self.resize(1020, 780)
        self.setMinimumSize(900, 700)
        _apply_standard_dialog_chrome(self, "workEditorDialog")

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)
        _add_standard_dialog_header(
            root,
            self,
            title=self.windowTitle(),
            subtitle=(
                "Works are separate from recordings. Capture composition metadata, splits, "
                "and linked recordings without mixing them into release data."
            ),
        )

        tabs = QTabWidget(self)
        root.addWidget(tabs, 1)

        metadata_scroll, _, metadata_layout = _create_scrollable_dialog_content(self)
        identity_box, identity_layout = _create_standard_section(
            self,
            "Work Metadata",
            "Core composition fields, alternate titles, and registration references for the work itself.",
        )
        identity_form = QFormLayout()
        _configure_standard_form_layout(identity_form)

        self.title_edit = QLineEdit()
        identity_form.addRow("Work Title", self.title_edit)

        self.alt_titles_edit = QPlainTextEdit()
        self.alt_titles_edit.setPlaceholderText("One alternate title per line")
        self.alt_titles_edit.setMinimumHeight(104)
        identity_form.addRow("Alternate Titles", self.alt_titles_edit)

        self.subtitle_edit = QLineEdit()
        identity_form.addRow("Subtitle / Version", self.subtitle_edit)

        self.language_edit = QLineEdit()
        identity_form.addRow("Language", self.language_edit)

        self.genre_edit = QLineEdit()
        identity_form.addRow("Genre / Style", self.genre_edit)

        self.iswc_edit = QLineEdit()
        identity_form.addRow("ISWC", self.iswc_edit)

        self.registration_edit = QLineEdit()
        identity_form.addRow("Registration #", self.registration_edit)
        identity_layout.addLayout(identity_form)
        metadata_layout.addWidget(identity_box)

        workflow_box, workflow_layout = _create_standard_section(
            self,
            "Workflow and Notes",
            "Track the current work status and mark which readiness items are already complete.",
        )
        workflow_form = QFormLayout()
        _configure_standard_form_layout(workflow_form)

        self.status_combo = QComboBox()
        self.status_combo.addItem("")
        self.status_combo.addItems(
            [value.replace("_", " ").title() for value in WORK_STATUS_CHOICES]
        )
        workflow_form.addRow("Work Status", self.status_combo)

        checklist_widget = QWidget(self)
        checklist_layout = QGridLayout(checklist_widget)
        checklist_layout.setContentsMargins(0, 0, 0, 0)
        checklist_layout.setHorizontalSpacing(10)
        checklist_layout.setVerticalSpacing(6)
        self.lyrics_checkbox = QCheckBox("Lyrics-based")
        self.instrumental_checkbox = QCheckBox("Instrumental")
        self.metadata_checkbox = QCheckBox("Metadata Complete")
        self.contract_checkbox = QCheckBox("Contract Signed")
        self.rights_checkbox = QCheckBox("Rights Verified")
        checklist_widgets = (
            self.lyrics_checkbox,
            self.instrumental_checkbox,
            self.metadata_checkbox,
            self.contract_checkbox,
            self.rights_checkbox,
        )
        for index, widget in enumerate(checklist_widgets):
            checklist_layout.addWidget(widget, index // 2, index % 2)
        checklist_layout.setColumnStretch(2, 1)
        workflow_form.addRow("Checklist", checklist_widget)

        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setMinimumHeight(132)
        workflow_form.addRow("Notes", self.notes_edit)
        workflow_layout.addLayout(workflow_form)
        metadata_layout.addWidget(workflow_box)
        metadata_layout.addStretch(1)
        tabs.addTab(metadata_scroll, "Metadata")

        links_tab = QWidget(self)
        links_layout = QVBoxLayout(links_tab)
        links_layout.setContentsMargins(0, 0, 0, 0)
        links_layout.setSpacing(12)

        splitter = QSplitter(Qt.Vertical, links_tab)
        splitter.setChildrenCollapsible(False)
        links_layout.addWidget(splitter, 1)

        contributors_box = QGroupBox("Creators / Publishers", links_tab)
        contributors_layout = QVBoxLayout(contributors_box)
        contributors_layout.setContentsMargins(14, 18, 14, 14)
        contributors_layout.setSpacing(10)
        contributors_layout.addWidget(
            QLabel(
                "Choose a canonical Party for each credited contributor when available. "
                "Typed credit names remain available as a transitional fallback."
            )
        )
        contributors_actions = QHBoxLayout()
        self.add_contributor_button = QPushButton("Add Contributor")
        self.add_contributor_button.clicked.connect(self._add_contributor_row)
        self.remove_contributor_button = QPushButton("Remove Highlighted")
        self.remove_contributor_button.clicked.connect(self._remove_contributor_rows)
        self.new_contributor_party_button = QPushButton("New Party...")
        self.new_contributor_party_button.clicked.connect(self._create_contributor_party)
        self.edit_contributor_party_button = QPushButton("Edit Linked Party...")
        self.edit_contributor_party_button.clicked.connect(self._edit_contributor_party)
        contributors_actions.addWidget(self.add_contributor_button)
        contributors_actions.addWidget(self.remove_contributor_button)
        contributors_actions.addWidget(self.new_contributor_party_button)
        contributors_actions.addWidget(self.edit_contributor_party_button)
        contributors_actions.addStretch(1)
        contributors_layout.addLayout(contributors_actions)

        self.contributors_table = QTableWidget(0, 4, contributors_box)
        self.contributors_table.setHorizontalHeaderLabels(
            ["Party / Credit", "Role", "Share %", "Role Share %"]
        )
        self.contributors_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.contributors_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.contributors_table.verticalHeader().setVisible(False)
        self.contributors_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.contributors_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeToContents
        )
        self.contributors_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeToContents
        )
        self.contributors_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeToContents
        )
        self.contributors_table.itemSelectionChanged.connect(
            self._refresh_contributor_party_action_state
        )
        contributors_layout.addWidget(self.contributors_table, 1)
        splitter.addWidget(contributors_box)

        tracks_box = QGroupBox("Linked Recordings / Tracks", links_tab)
        tracks_layout = QVBoxLayout(tracks_box)
        tracks_layout.setContentsMargins(14, 18, 14, 14)
        tracks_layout.setSpacing(10)
        tracks_layout.addWidget(
            QLabel(
                "Link one or more recordings to this work. Releases remain attached to recordings instead of directly to the work."
            )
        )
        track_actions = QHBoxLayout()
        add_selected_button = QPushButton("Link Selected Tracks")
        add_selected_button.clicked.connect(self._add_selected_tracks)
        remove_track_button = QPushButton("Remove Highlighted")
        remove_track_button.clicked.connect(self._remove_track_rows)
        track_actions.addWidget(add_selected_button)
        track_actions.addWidget(remove_track_button)
        track_actions.addStretch(1)
        tracks_layout.addLayout(track_actions)

        self.track_table = QTableWidget(0, 2, tracks_box)
        self.track_table.setHorizontalHeaderLabels(["Track ID", "Track Title"])
        self.track_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.track_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.track_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.track_table.verticalHeader().setVisible(False)
        self.track_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.track_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        tracks_layout.addWidget(self.track_table, 1)
        splitter.addWidget(tracks_box)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        tabs.addTab(links_tab, "Contributors and Links")

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        save_button = buttons.button(QDialogButtonBox.Save)
        if save_button is not None:
            save_button.setText("Save Work")
            save_button.setDefault(True)
        root.addWidget(buttons)
        _apply_compact_dialog_control_heights(self)

        if work is not None:
            self.title_edit.setText(work.title)
            self.alt_titles_edit.setPlainText("\n".join(work.alternate_titles))
            self.subtitle_edit.setText(work.version_subtitle or "")
            self.language_edit.setText(work.language or "")
            self.genre_edit.setText(work.genre_notes or "")
            self.iswc_edit.setText(work.iswc or "")
            self.registration_edit.setText(work.registration_number or "")
            self.status_combo.setCurrentText((work.work_status or "").replace("_", " ").title())
            self.lyrics_checkbox.setChecked(work.lyrics_flag)
            self.instrumental_checkbox.setChecked(work.instrumental_flag)
            self.metadata_checkbox.setChecked(work.metadata_complete)
            self.contract_checkbox.setChecked(work.contract_signed)
            self.rights_checkbox.setChecked(work.rights_verified)
            self.notes_edit.setPlainText(work.notes or "")
        for contributor in contributors or []:
            self._add_contributor_row(contributor)
        for track_id in track_ids or []:
            self._append_track_row(int(track_id))
        self._refresh_contributor_party_action_state()

    @staticmethod
    def _contributor_party_primary_label(record: PartyRecord) -> str:
        return (
            str(record.display_name or "").strip()
            or str(record.artist_name or "").strip()
            or str(record.company_name or "").strip()
            or str(record.legal_name or "").strip()
            or f"Party #{int(record.id)}"
        )

    @classmethod
    def _contributor_party_choice_label(cls, record: PartyRecord) -> str:
        primary = cls._contributor_party_primary_label(record)
        legal_name = str(record.legal_name or "").strip()
        if legal_name and legal_name.casefold() != primary.casefold():
            return f"{primary} ({legal_name})"
        return primary

    def _contributor_party_records(self) -> list[PartyRecord]:
        if self.party_service is None:
            return []
        try:
            return list(self.party_service.list_parties() or [])
        except Exception:
            return []

    def _configure_contributor_party_combo(
        self,
        combo: QComboBox,
        *,
        selected_party_id: int | None = None,
        current_text: str | None = None,
    ) -> None:
        clean_text = str(current_text or "").strip()
        labels: list[str] = []
        previous_state = combo.blockSignals(True)
        try:
            combo.clear()
            combo.setEditable(True)
            combo.setInsertPolicy(QComboBox.NoInsert)
            combo.addItem("", None)
            for record in self._contributor_party_records():
                primary_label = self._contributor_party_primary_label(record)
                label = self._contributor_party_choice_label(record)
                combo.addItem(label, int(record.id))
                combo.setItemData(combo.count() - 1, primary_label, Qt.UserRole + 1)
                labels.append(label)
            if selected_party_id is not None and combo.findData(int(selected_party_id)) < 0:
                fallback_label = clean_text or f"Party #{int(selected_party_id)}"
                combo.addItem(fallback_label, int(selected_party_id))
                combo.setItemData(combo.count() - 1, fallback_label, Qt.UserRole + 1)
                labels.append(fallback_label)
            completer = QCompleter(labels, combo)
            completer.setCaseSensitivity(Qt.CaseInsensitive)
            combo.setCompleter(completer)
            if selected_party_id is not None:
                index = combo.findData(int(selected_party_id))
                combo.setCurrentIndex(index if index >= 0 else 0)
            elif clean_text:
                combo.setCurrentIndex(-1)
                combo.setEditText(clean_text)
            else:
                combo.setCurrentIndex(0)
        finally:
            combo.blockSignals(previous_state)

    @staticmethod
    def _resolve_contributor_party_choice(combo: QComboBox) -> tuple[str, int | None]:
        clean = str(combo.currentText() or "").strip()
        if not clean:
            return "", None
        current_index = combo.currentIndex()
        if current_index > 0:
            data = combo.itemData(current_index)
            label = str(combo.itemText(current_index) or "").strip()
            if data not in (None, "") and clean.casefold() == label.casefold():
                primary_label = str(combo.itemData(current_index, Qt.UserRole + 1) or label).strip()
                return primary_label or label, int(data)
        for index in range(1, combo.count()):
            label = str(combo.itemText(index) or "").strip()
            if clean.casefold() != label.casefold():
                continue
            data = combo.itemData(index)
            if data not in (None, ""):
                primary_label = str(combo.itemData(index, Qt.UserRole + 1) or label).strip()
                return primary_label or label, int(data)
        return clean, None

    def _contributor_party_combo(self, row: int) -> QComboBox | None:
        if row < 0:
            return None
        widget = self.contributors_table.cellWidget(row, 0)
        return widget if isinstance(widget, QComboBox) else None

    def _selected_contributor_row(self) -> int | None:
        current_row = self.contributors_table.currentRow()
        if current_row >= 0:
            return int(current_row)
        selected_rows = sorted({index.row() for index in self.contributors_table.selectedIndexes()})
        return int(selected_rows[0]) if selected_rows else None

    def _refresh_all_contributor_party_combos(self) -> None:
        for row in range(self.contributors_table.rowCount()):
            combo = self._contributor_party_combo(row)
            if combo is None:
                continue
            current_text, selected_party_id = self._resolve_contributor_party_choice(combo)
            self._configure_contributor_party_combo(
                combo,
                selected_party_id=selected_party_id,
                current_text=current_text,
            )
        self._refresh_contributor_party_action_state()

    def _refresh_contributor_party_action_state(self) -> None:
        has_party_service = self.party_service is not None
        self.new_contributor_party_button.setEnabled(has_party_service)
        row = self._selected_contributor_row()
        combo = self._contributor_party_combo(row) if row is not None else None
        _name, selected_party_id = (
            self._resolve_contributor_party_choice(combo)
            if combo is not None
            else ("", None)
        )
        self.edit_contributor_party_button.setEnabled(
            has_party_service and combo is not None and selected_party_id is not None
        )

    def _create_contributor_party(self) -> None:
        if self.party_service is None:
            return
        dialog = PartyEditorDialog(party_service=self.party_service, parent=self)
        if not dialog.exec():
            return
        try:
            party_id = int(self.party_service.create_party(dialog.payload()))
        except Exception as exc:
            QMessageBox.warning(self, "Work Contributor", str(exc))
            return
        row = self._selected_contributor_row()
        if row is None:
            self._add_contributor_row()
            row = self.contributors_table.rowCount() - 1
            self.contributors_table.selectRow(row)
        self._refresh_all_contributor_party_combos()
        combo = self._contributor_party_combo(int(row))
        if combo is not None:
            index = combo.findData(int(party_id))
            if index >= 0:
                combo.setCurrentIndex(index)
        self._refresh_contributor_party_action_state()

    def _edit_contributor_party(self) -> None:
        if self.party_service is None:
            return
        row = self._selected_contributor_row()
        combo = self._contributor_party_combo(row) if row is not None else None
        _name, selected_party_id = (
            self._resolve_contributor_party_choice(combo)
            if combo is not None
            else ("", None)
        )
        if selected_party_id is None:
            QMessageBox.information(
                self,
                "Work Contributor",
                "Select a contributor row linked to a Party first.",
            )
            return
        record = self.party_service.fetch_party(int(selected_party_id))
        if record is None:
            QMessageBox.warning(
                self,
                "Work Contributor",
                f"Party #{int(selected_party_id)} could not be loaded.",
            )
            return
        dialog = PartyEditorDialog(party_service=self.party_service, party=record, parent=self)
        if not dialog.exec():
            return
        try:
            self.party_service.update_party(int(record.id), dialog.payload())
        except Exception as exc:
            QMessageBox.warning(self, "Work Contributor", str(exc))
            return
        self._refresh_all_contributor_party_combos()
        refreshed_combo = self._contributor_party_combo(int(row)) if row is not None else None
        if refreshed_combo is not None:
            index = refreshed_combo.findData(int(record.id))
            if index >= 0:
                refreshed_combo.setCurrentIndex(index)
        self._refresh_contributor_party_action_state()

    def _add_contributor_row(self, contributor: WorkContributorPayload | None = None) -> None:
        row = self.contributors_table.rowCount()
        self.contributors_table.insertRow(row)
        party_combo = QComboBox(self.contributors_table)
        self._configure_contributor_party_combo(
            party_combo,
            selected_party_id=contributor.party_id if contributor is not None else None,
            current_text=contributor.name if contributor is not None else None,
        )
        party_combo.currentIndexChanged.connect(
            lambda _index, self=self: self._refresh_contributor_party_action_state()
        )
        party_combo.editTextChanged.connect(
            lambda _text, self=self: self._refresh_contributor_party_action_state()
        )
        self.contributors_table.setCellWidget(row, 0, party_combo)

        role_combo = QComboBox(self.contributors_table)
        role_combo.addItems([item.replace("_", " ").title() for item in WORK_CREATOR_ROLE_CHOICES])
        role_combo.setCurrentText(
            (contributor.role if contributor is not None else "songwriter")
            .replace("_", " ")
            .title()
        )
        self.contributors_table.setCellWidget(row, 1, role_combo)

        share_item = QTableWidgetItem(
            ""
            if contributor is None or contributor.share_percent is None
            else str(contributor.share_percent)
        )
        role_share_item = QTableWidgetItem(
            ""
            if contributor is None or contributor.role_share_percent is None
            else str(contributor.role_share_percent)
        )
        self.contributors_table.setItem(row, 2, share_item)
        self.contributors_table.setItem(row, 3, role_share_item)
        self.contributors_table.setCurrentCell(row, 0)
        self._refresh_contributor_party_action_state()

    def _remove_contributor_rows(self) -> None:
        for row in sorted(
            {index.row() for index in self.contributors_table.selectedIndexes()}, reverse=True
        ):
            self.contributors_table.removeRow(row)
        self._refresh_contributor_party_action_state()

    def _append_track_row(self, track_id: int) -> None:
        existing = {
            int(self.track_table.item(row, 0).text())
            for row in range(self.track_table.rowCount())
            if self.track_table.item(row, 0) is not None
        }
        if track_id in existing:
            return
        row = self.track_table.rowCount()
        self.track_table.insertRow(row)
        self.track_table.setItem(row, 0, QTableWidgetItem(str(track_id)))
        self.track_table.setItem(row, 1, QTableWidgetItem(self.track_title_resolver(track_id)))

    def _add_selected_tracks(self) -> None:
        for track_id in list(self.selected_track_ids_provider() or []):
            self._append_track_row(int(track_id))

    def _remove_track_rows(self) -> None:
        for row in sorted(
            {index.row() for index in self.track_table.selectedIndexes()}, reverse=True
        ):
            self.track_table.removeRow(row)

    def payload(self) -> WorkPayload:
        contributors: list[WorkContributorPayload] = []
        for row in range(self.contributors_table.rowCount()):
            identity_widget = self.contributors_table.cellWidget(row, 0)
            role_widget = self.contributors_table.cellWidget(row, 1)
            share_item = self.contributors_table.item(row, 2)
            role_share_item = self.contributors_table.item(row, 3)
            if isinstance(identity_widget, QComboBox):
                name, party_id = self._resolve_contributor_party_choice(identity_widget)
            else:
                name_item = self.contributors_table.item(row, 0)
                name = name_item.text().strip() if name_item is not None else ""
                party_id = None
            if not name:
                continue
            role = (
                role_widget.currentText().strip().lower().replace(" ", "_")
                if isinstance(role_widget, QComboBox)
                else "songwriter"
            )
            share_text = share_item.text().strip() if share_item is not None else ""
            role_share_text = role_share_item.text().strip() if role_share_item is not None else ""
            contributors.append(
                WorkContributorPayload(
                    role=role,
                    name=name,
                    share_percent=float(share_text) if share_text else None,
                    role_share_percent=float(role_share_text) if role_share_text else None,
                    party_id=party_id,
                )
            )
        track_ids = []
        for row in range(self.track_table.rowCount()):
            item = self.track_table.item(row, 0)
            if item is None:
                continue
            track_ids.append(int(item.text()))
        return WorkPayload(
            title=self.title_edit.text().strip(),
            alternate_titles=[
                line.strip()
                for line in self.alt_titles_edit.toPlainText().splitlines()
                if line.strip()
            ],
            version_subtitle=self.subtitle_edit.text().strip() or None,
            language=self.language_edit.text().strip() or None,
            lyrics_flag=self.lyrics_checkbox.isChecked(),
            instrumental_flag=self.instrumental_checkbox.isChecked(),
            genre_notes=self.genre_edit.text().strip() or None,
            iswc=self.iswc_edit.text().strip() or None,
            registration_number=self.registration_edit.text().strip() or None,
            work_status=self.status_combo.currentText().strip().lower().replace(" ", "_") or None,
            metadata_complete=self.metadata_checkbox.isChecked(),
            contract_signed=self.contract_checkbox.isChecked(),
            rights_verified=self.rights_checkbox.isChecked(),
            notes=self.notes_edit.toPlainText().strip() or None,
            contributors=contributors,
            track_ids=track_ids,
        )


class WorkBrowserPanel(QWidget):
    """Browse, create, duplicate, and link first-class work records inside a workspace panel."""

    filter_requested = Signal(list)
    create_requested = Signal(object)
    create_child_track_requested = Signal(int)
    create_album_for_work_requested = Signal(int)
    update_requested = Signal(int, object)
    duplicate_requested = Signal(int)
    link_tracks_requested = Signal(int, list)
    delete_requested = Signal(int)

    def __init__(
        self,
        *,
        work_service_provider,
        track_title_resolver,
        selected_track_ids_provider,
        track_choice_provider=None,
        linked_track_id: int | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.work_service_provider = work_service_provider
        self.track_title_resolver = track_title_resolver
        self.selected_track_ids_provider = selected_track_ids_provider
        self.track_choice_provider = track_choice_provider or (lambda: [])
        self.linked_track_id = linked_track_id
        self._selection_override_track_ids: list[int] = []
        self.setObjectName("workBrowserPanel")
        _apply_standard_widget_chrome(self, "workBrowserPanel")

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(14)
        _add_standard_dialog_header(
            root,
            self,
            title="Work Manager",
            subtitle=(
                "Use works as the governance layer for creation. Start here to create a work, "
                "add governed child tracks or album batches, then use linking and filtering for operational follow-up."
            ),
        )

        controls_box, controls_layout = _create_standard_section(
            self,
            "Find and Manage",
            "Search by work title, alternate title, ISWC, or registration number, then create and govern child recordings from the selected work.",
        )
        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(10)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(
            "Search works by title, alternate title, ISWC, or registration #..."
        )
        self.search_edit.textChanged.connect(self.refresh)
        controls.addWidget(self.search_edit, 1)

        add_button = QPushButton("Add")
        add_button.clicked.connect(self.create_work)
        self.create_child_track_button = QPushButton("Add Track to Work")
        self.create_child_track_button.clicked.connect(self.create_child_track)
        self.create_album_for_work_button = QPushButton("Add Album to Work")
        self.create_album_for_work_button.clicked.connect(self.create_album_for_work)
        edit_button = QPushButton("Edit")
        edit_button.clicked.connect(self.edit_selected)
        duplicate_button = QPushButton("Duplicate")
        duplicate_button.clicked.connect(self.duplicate_selected)
        link_button = QPushButton("Link Selected Tracks")
        link_button.clicked.connect(self.link_selected_tracks)
        delete_button = QPushButton("Delete")
        delete_button.clicked.connect(self.delete_selected)
        open_filter_button = QPushButton("Filter Main Table")
        open_filter_button.clicked.connect(self.filter_by_work_tracks)
        controls_layout.addLayout(controls)
        self.manage_actions_cluster = _create_action_button_cluster(
            self,
            [
                add_button,
                self.create_child_track_button,
                self.create_album_for_work_button,
                edit_button,
                duplicate_button,
                link_button,
                delete_button,
                open_filter_button,
            ],
            columns=2,
            min_button_width=180,
        )
        self.manage_actions_cluster.setObjectName("workManagerActionsCluster")
        controls_layout.addWidget(self.manage_actions_cluster)
        self.selection_banner = SelectionScopeBanner(
            chooser_label="Choose Tracks",
            parent=self,
        )
        self.selection_banner.use_current_button.clicked.connect(self._use_current_selection)
        self.selection_banner.choose_button.clicked.connect(self._choose_tracks)
        self.selection_banner.clear_override_button.clicked.connect(self._clear_selection_override)
        controls_layout.addWidget(self.selection_banner)
        root.addWidget(controls_box)

        table_box, table_layout = _create_standard_section(
            self,
            "Works",
            "Each row is a separate composition record. Double-click a row to edit it.",
        )
        self.table = QTableWidget(0, 6, table_box)
        self.table.setHorizontalHeaderLabels(
            ["ID", "Title", "ISWC", "Status", "Tracks", "Contributors"]
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
        self.table.doubleClicked.connect(lambda _index: self.edit_selected())
        table_layout.addWidget(self.table, 1)
        root.addWidget(table_box, 1)

        _apply_compact_dialog_control_heights(self)

        self.refresh()
        self.refresh_selection_scope()

    def _work_service(self) -> WorkService | None:
        service = self.work_service_provider()
        return service

    def set_linked_track_id(self, linked_track_id: int | None) -> None:
        self.linked_track_id = int(linked_track_id) if linked_track_id is not None else None
        self.refresh()

    def _selected_work_id(self) -> int | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        item = self.table.item(rows[0].row(), 0)
        return int(item.text()) if item is not None else None

    def _restore_selection(self, work_id: int | None) -> None:
        if not work_id:
            return
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is None:
                continue
            try:
                current_work_id = int(item.text())
            except Exception:
                continue
            if current_work_id != int(work_id):
                continue
            self.table.selectRow(row)
            return

    def focus_work(self, work_id: int | None) -> None:
        if not work_id:
            return
        self._restore_selection(int(work_id))

    def refresh(self) -> None:
        selected_work_id = self._selected_work_id()
        service = self._work_service()
        if service is None:
            self.table.setRowCount(0)
            self.refresh_selection_scope()
            return

        rows = service.list_works(
            search_text=self.search_edit.text(),
            linked_track_id=self.linked_track_id,
        )
        self.table.setRowCount(0)
        for record in rows:
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = [
                str(record.id),
                record.title,
                record.iswc or "",
                (record.work_status or "").replace("_", " ").title(),
                str(record.track_count),
                str(record.contributor_count),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row, column, item)
        self.table.resizeColumnsToContents()
        self._restore_selection(selected_work_id)
        self.refresh_selection_scope()

    def selected_track_ids(self) -> list[int]:
        if self._selection_override_track_ids:
            return [int(track_id) for track_id in self._selection_override_track_ids]
        try:
            return [int(track_id) for track_id in (self.selected_track_ids_provider() or [])]
        except Exception:
            return []

    def selection_scope_state(self) -> SelectionScopeState:
        track_ids = tuple(self.selected_track_ids())
        override_active = bool(self._selection_override_track_ids)
        source_label = "Pinned chooser override" if override_active else "Catalog selection"
        return SelectionScopeState(
            source_label=source_label,
            track_ids=track_ids,
            preview_text=build_selection_preview(track_ids, self.track_title_resolver),
            override_active=override_active,
        )

    def refresh_selection_scope(self) -> None:
        self.selection_banner.set_state(self.selection_scope_state())

    def _use_current_selection(self) -> None:
        self._selection_override_track_ids = []
        self.refresh_selection_scope()

    def _clear_selection_override(self) -> None:
        self._selection_override_track_ids = []
        self.refresh_selection_scope()

    def _available_track_choices(self) -> list[TrackChoice]:
        try:
            choices = list(self.track_choice_provider() or [])
        except Exception:
            choices = []
        normalized: list[TrackChoice] = []
        seen: set[int] = set()
        for choice in choices:
            if isinstance(choice, TrackChoice):
                track_id = int(choice.track_id)
                title = choice.title
                subtitle = choice.subtitle
            else:
                try:
                    track_id = int(choice["track_id"])
                except Exception:
                    continue
                title = str(choice.get("title") or "").strip()
                subtitle = str(choice.get("subtitle") or "").strip()
            if track_id <= 0 or track_id in seen:
                continue
            seen.add(track_id)
            normalized.append(
                TrackChoice(
                    track_id=track_id,
                    title=title or self.track_title_resolver(track_id),
                    subtitle=subtitle,
                )
            )
        return normalized

    def _choose_tracks(self) -> None:
        dialog = TrackSelectionChooserDialog(
            track_choices=self._available_track_choices(),
            initial_track_ids=self.selected_track_ids(),
            title="Choose Work Scope Tracks",
            parent=self,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        self._selection_override_track_ids = dialog.selected_track_ids()
        self.refresh_selection_scope()

    def _edit_dialog_for(self, work_id: int | None = None) -> WorkEditorDialog:
        service = self._work_service()
        detail = service.fetch_work_detail(work_id) if service is not None and work_id else None
        contributors = []
        track_ids = []
        if detail is not None:
            contributors = [
                WorkContributorPayload(
                    role=item.role,
                    name=item.display_name or "",
                    share_percent=item.share_percent,
                    role_share_percent=item.role_share_percent,
                    party_id=item.party_id,
                    notes=item.notes,
                )
                for item in detail.contributors
            ]
            track_ids = list(detail.track_ids)
        elif work_id is None:
            track_ids = list(self.selected_track_ids())
        return WorkEditorDialog(
            work_service=service,
            track_title_resolver=self.track_title_resolver,
            selected_track_ids_provider=self.selected_track_ids,
            work=detail.work if detail is not None else None,
            contributors=contributors,
            track_ids=track_ids,
            parent=self,
        )

    def create_work(self) -> None:
        service = self._work_service()
        if service is None:
            QMessageBox.warning(self, "Work Manager", "Open a profile first.")
            return
        dialog = self._edit_dialog_for()
        if dialog.exec() != QDialog.Accepted:
            return
        self.create_requested.emit(dialog.payload())

    def create_child_track(self) -> None:
        service = self._work_service()
        if service is None:
            QMessageBox.warning(self, "Work Manager", "Open a profile first.")
            return
        work_id = self._selected_work_id()
        if not work_id:
            QMessageBox.information(self, "Work Manager", "Select a work first.")
            return
        self.create_child_track_requested.emit(work_id)

    def create_album_for_work(self) -> None:
        service = self._work_service()
        if service is None:
            QMessageBox.warning(self, "Work Manager", "Open a profile first.")
            return
        work_id = self._selected_work_id()
        if not work_id:
            QMessageBox.information(self, "Work Manager", "Select a work first.")
            return
        self.create_album_for_work_requested.emit(work_id)

    def edit_selected(self) -> None:
        service = self._work_service()
        if service is None:
            QMessageBox.warning(self, "Work Manager", "Open a profile first.")
            return
        work_id = self._selected_work_id()
        if not work_id:
            QMessageBox.information(self, "Work Manager", "Select a work first.")
            return
        dialog = self._edit_dialog_for(work_id)
        if dialog.exec() != QDialog.Accepted:
            return
        self.update_requested.emit(work_id, dialog.payload())

    def duplicate_selected(self) -> None:
        service = self._work_service()
        if service is None:
            QMessageBox.warning(self, "Work Manager", "Open a profile first.")
            return
        work_id = self._selected_work_id()
        if not work_id:
            QMessageBox.information(self, "Work Manager", "Select a work first.")
            return
        self.duplicate_requested.emit(work_id)

    def link_selected_tracks(self) -> None:
        service = self._work_service()
        if service is None:
            QMessageBox.warning(self, "Work Manager", "Open a profile first.")
            return
        work_id = self._selected_work_id()
        if not work_id:
            QMessageBox.information(self, "Work Manager", "Select a work first.")
            return
        track_ids = list(self.selected_track_ids())
        if not track_ids:
            QMessageBox.information(
                self, "Work Manager", "Select one or more tracks in the main table first."
            )
            return
        self.link_tracks_requested.emit(work_id, track_ids)

    def delete_selected(self) -> None:
        service = self._work_service()
        if service is None:
            QMessageBox.warning(self, "Work Manager", "Open a profile first.")
            return
        work_id = self._selected_work_id()
        if not work_id:
            QMessageBox.information(self, "Work Manager", "Select a work first.")
            return
        if not _confirm_destructive_action(
            self,
            title="Delete Work",
            prompt="Delete the selected work?",
        ):
            return
        self.delete_requested.emit(work_id)

    def filter_by_work_tracks(self) -> None:
        service = self._work_service()
        if service is None:
            QMessageBox.warning(self, "Work Manager", "Open a profile first.")
            return
        work_id = self._selected_work_id()
        if not work_id:
            QMessageBox.information(self, "Work Manager", "Select a work first.")
            return
        detail = service.fetch_work_detail(work_id)
        if detail is None:
            return
        self.filter_requested.emit(list(detail.track_ids))


class WorkBrowserDialog(QDialog):
    """Compatibility dialog wrapper around the reusable work manager panel."""

    filter_requested = Signal(list)
    create_requested = Signal(object)
    create_child_track_requested = Signal(int)
    create_album_for_work_requested = Signal(int)
    update_requested = Signal(int, object)
    duplicate_requested = Signal(int)
    link_tracks_requested = Signal(int, list)
    delete_requested = Signal(int)

    def __init__(
        self,
        *,
        work_service: WorkService,
        track_title_resolver,
        selected_track_ids_provider,
        track_choice_provider=None,
        linked_track_id: int | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Work Manager")
        self.resize(1040, 700)
        self.setMinimumSize(920, 620)
        _apply_standard_dialog_chrome(self, "workBrowserDialog")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.panel = WorkBrowserPanel(
            work_service_provider=lambda: work_service,
            track_title_resolver=track_title_resolver,
            selected_track_ids_provider=selected_track_ids_provider,
            track_choice_provider=track_choice_provider,
            linked_track_id=linked_track_id,
            parent=self,
        )
        self.panel.filter_requested.connect(self.filter_requested.emit)
        self.panel.create_requested.connect(self.create_requested.emit)
        self.panel.create_child_track_requested.connect(self.create_child_track_requested.emit)
        self.panel.create_album_for_work_requested.connect(
            self.create_album_for_work_requested.emit
        )
        self.panel.update_requested.connect(self.update_requested.emit)
        self.panel.duplicate_requested.connect(self.duplicate_requested.emit)
        self.panel.link_tracks_requested.connect(self.link_tracks_requested.emit)
        self.panel.delete_requested.connect(self.delete_requested.emit)
        root.addWidget(self.panel)

    def __getattr__(self, name: str):
        panel = self.__dict__.get("panel")
        if panel is not None and hasattr(panel, name):
            return getattr(panel, name)
        raise AttributeError(name)

"""Work manager dialogs."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
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
        self.track_title_resolver = track_title_resolver
        self.selected_track_ids_provider = selected_track_ids_provider
        self.work = work
        self.setWindowTitle("Edit Work" if work is not None else "Create Work")
        self.resize(980, 760)

        root = QVBoxLayout(self)

        intro = QLabel(
            "Works are separate from recordings. Use this dialog to manage composition metadata, splits, and linked track recordings."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        form_box = QGroupBox("Work Metadata", self)
        form = QFormLayout(form_box)
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignTop)

        self.title_edit = QLineEdit()
        form.addRow("Work Title", self.title_edit)

        self.alt_titles_edit = QPlainTextEdit()
        self.alt_titles_edit.setPlaceholderText("One alternate title per line")
        self.alt_titles_edit.setMaximumHeight(90)
        form.addRow("Alternate Titles", self.alt_titles_edit)

        self.subtitle_edit = QLineEdit()
        form.addRow("Subtitle / Version", self.subtitle_edit)

        self.language_edit = QLineEdit()
        form.addRow("Language", self.language_edit)

        self.genre_edit = QLineEdit()
        form.addRow("Genre / Style", self.genre_edit)

        self.iswc_edit = QLineEdit()
        form.addRow("ISWC", self.iswc_edit)

        self.registration_edit = QLineEdit()
        form.addRow("Registration #", self.registration_edit)

        self.status_combo = QComboBox()
        self.status_combo.addItem("")
        self.status_combo.addItems(
            [value.replace("_", " ").title() for value in WORK_STATUS_CHOICES]
        )
        form.addRow("Work Status", self.status_combo)

        flags_row = QHBoxLayout()
        self.lyrics_checkbox = QCheckBox("Lyrics-based")
        self.instrumental_checkbox = QCheckBox("Instrumental")
        self.metadata_checkbox = QCheckBox("Metadata Complete")
        self.contract_checkbox = QCheckBox("Contract Signed")
        self.rights_checkbox = QCheckBox("Rights Verified")
        for widget in (
            self.lyrics_checkbox,
            self.instrumental_checkbox,
            self.metadata_checkbox,
            self.contract_checkbox,
            self.rights_checkbox,
        ):
            flags_row.addWidget(widget)
        flags_row.addStretch(1)
        form.addRow("Checklist", flags_row)

        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setMinimumHeight(90)
        form.addRow("Notes", self.notes_edit)
        root.addWidget(form_box)

        contributors_box = QGroupBox("Creators / Publishers", self)
        contributors_layout = QVBoxLayout(contributors_box)
        contributors_actions = QHBoxLayout()
        add_contributor_button = QPushButton("Add Contributor")
        add_contributor_button.clicked.connect(self._add_contributor_row)
        remove_contributor_button = QPushButton("Remove Highlighted")
        remove_contributor_button.clicked.connect(self._remove_contributor_rows)
        contributors_actions.addWidget(add_contributor_button)
        contributors_actions.addWidget(remove_contributor_button)
        contributors_actions.addStretch(1)
        contributors_layout.addLayout(contributors_actions)

        self.contributors_table = QTableWidget(0, 4, contributors_box)
        self.contributors_table.setHorizontalHeaderLabels(
            ["Name", "Role", "Share %", "Role Share %"]
        )
        self.contributors_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.contributors_table.horizontalHeader().setStretchLastSection(True)
        contributors_layout.addWidget(self.contributors_table, 1)
        root.addWidget(contributors_box, 1)

        tracks_box = QGroupBox("Linked Recordings / Tracks", self)
        tracks_layout = QVBoxLayout(tracks_box)
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
        self.track_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.track_table.horizontalHeader().setStretchLastSection(True)
        tracks_layout.addWidget(self.track_table, 1)
        root.addWidget(tracks_box, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        save_button = QPushButton("Save")
        save_button.clicked.connect(self.accept)
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        buttons.addWidget(save_button)
        buttons.addWidget(cancel_button)
        root.addLayout(buttons)

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

    def _add_contributor_row(self, contributor: WorkContributorPayload | None = None) -> None:
        row = self.contributors_table.rowCount()
        self.contributors_table.insertRow(row)
        name_item = QTableWidgetItem(contributor.name if contributor is not None else "")
        self.contributors_table.setItem(row, 0, name_item)

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

    def _remove_contributor_rows(self) -> None:
        for row in sorted(
            {index.row() for index in self.contributors_table.selectedIndexes()}, reverse=True
        ):
            self.contributors_table.removeRow(row)

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
            name_item = self.contributors_table.item(row, 0)
            role_widget = self.contributors_table.cellWidget(row, 1)
            share_item = self.contributors_table.item(row, 2)
            role_share_item = self.contributors_table.item(row, 3)
            name = name_item.text().strip() if name_item is not None else ""
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


class WorkBrowserDialog(QDialog):
    """Browse, create, duplicate, and link first-class work records."""

    filter_requested = Signal(list)

    def __init__(
        self,
        *,
        work_service: WorkService,
        track_title_resolver,
        selected_track_ids_provider,
        linked_track_id: int | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.work_service = work_service
        self.track_title_resolver = track_title_resolver
        self.selected_track_ids_provider = selected_track_ids_provider
        self.linked_track_id = linked_track_id
        self.setWindowTitle("Work Manager")
        self.resize(980, 640)

        root = QVBoxLayout(self)
        intro = QLabel(
            "Browse compositions separately from recordings, validate splits, and attach selected tracks to the correct work."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        controls = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(
            "Search works by title, alternate title, ISWC, or registration #..."
        )
        self.search_edit.textChanged.connect(self.refresh)
        controls.addWidget(self.search_edit, 1)

        add_button = QPushButton("Add")
        add_button.clicked.connect(self.create_work)
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
        for button in (
            add_button,
            edit_button,
            duplicate_button,
            link_button,
            delete_button,
            open_filter_button,
        ):
            controls.addWidget(button)
        root.addLayout(controls)

        self.table = QTableWidget(0, 6, self)
        self.table.setHorizontalHeaderLabels(
            ["ID", "Title", "ISWC", "Status", "Tracks", "Contributors"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.doubleClicked.connect(lambda _index: self.edit_selected())
        root.addWidget(self.table, 1)

        self.refresh()

    def _selected_work_id(self) -> int | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        item = self.table.item(rows[0].row(), 0)
        return int(item.text()) if item is not None else None

    def refresh(self) -> None:
        rows = self.work_service.list_works(
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

    def _edit_dialog_for(self, work_id: int | None = None) -> WorkEditorDialog:
        detail = self.work_service.fetch_work_detail(work_id) if work_id else None
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
        return WorkEditorDialog(
            work_service=self.work_service,
            track_title_resolver=self.track_title_resolver,
            selected_track_ids_provider=self.selected_track_ids_provider,
            work=detail.work if detail is not None else None,
            contributors=contributors,
            track_ids=track_ids,
            parent=self,
        )

    def create_work(self) -> None:
        dialog = self._edit_dialog_for()
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            self.work_service.create_work(dialog.payload())
        except Exception as exc:
            QMessageBox.critical(self, "Work Manager", str(exc))
            return
        self.refresh()

    def edit_selected(self) -> None:
        work_id = self._selected_work_id()
        if not work_id:
            QMessageBox.information(self, "Work Manager", "Select a work first.")
            return
        dialog = self._edit_dialog_for(work_id)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            self.work_service.update_work(work_id, dialog.payload())
        except Exception as exc:
            QMessageBox.critical(self, "Work Manager", str(exc))
            return
        self.refresh()

    def duplicate_selected(self) -> None:
        work_id = self._selected_work_id()
        if not work_id:
            QMessageBox.information(self, "Work Manager", "Select a work first.")
            return
        try:
            self.work_service.duplicate_work(work_id)
        except Exception as exc:
            QMessageBox.critical(self, "Work Manager", str(exc))
            return
        self.refresh()

    def link_selected_tracks(self) -> None:
        work_id = self._selected_work_id()
        if not work_id:
            QMessageBox.information(self, "Work Manager", "Select a work first.")
            return
        track_ids = list(self.selected_track_ids_provider() or [])
        if not track_ids:
            QMessageBox.information(
                self, "Work Manager", "Select one or more tracks in the main table first."
            )
            return
        self.work_service.link_tracks_to_work(work_id, track_ids)
        self.refresh()

    def delete_selected(self) -> None:
        work_id = self._selected_work_id()
        if not work_id:
            QMessageBox.information(self, "Work Manager", "Select a work first.")
            return
        if (
            QMessageBox.question(self, "Delete Work", "Delete the selected work?")
            != QMessageBox.Yes
        ):
            return
        self.work_service.delete_work(work_id)
        self.refresh()

    def filter_by_work_tracks(self) -> None:
        work_id = self._selected_work_id()
        if not work_id:
            QMessageBox.information(self, "Work Manager", "Select a work first.")
            return
        detail = self.work_service.fetch_work_detail(work_id)
        if detail is None:
            return
        self.filter_requested.emit(list(detail.track_ids))

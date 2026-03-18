"""Release management dialogs."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
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

from isrc_manager.file_storage import (
    STORAGE_MODE_DATABASE,
    STORAGE_MODE_MANAGED_FILE,
    normalize_storage_mode,
)
from isrc_manager.services.repertoire_status import REPERTOIRE_STATUS_CHOICES
from isrc_manager.ui_common import (
    _add_standard_dialog_header,
    _apply_compact_dialog_control_heights,
    _apply_standard_dialog_chrome,
    _apply_standard_widget_chrome,
    _configure_standard_form_layout,
    _create_scrollable_dialog_content,
    _create_standard_section,
)

from .models import ReleasePayload, ReleaseRecord, ReleaseSummary, ReleaseTrackPlacement
from .service import RELEASE_TYPE_CHOICES, ReleaseService


class ReleaseEditorDialog(QDialog):
    """Create or edit a release with ordered track placements."""

    def __init__(
        self,
        *,
        release_service: ReleaseService,
        track_title_resolver,
        selected_track_ids_provider,
        release: ReleaseRecord | None = None,
        placements: list[ReleaseTrackPlacement] | None = None,
        profile_name: str | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.release_service = release_service
        self.track_title_resolver = track_title_resolver
        self.selected_track_ids_provider = selected_track_ids_provider
        self.release = release
        self.profile_name = profile_name
        self.setWindowTitle("Edit Release" if release is not None else "Create Release")
        self.resize(980, 760)
        self.setModal(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        intro = QLabel(
            "Manage release-level metadata separately from track metadata, then attach and order tracks below."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        splitter = QSplitter(Qt.Horizontal, self)
        root.addWidget(splitter, 1)

        metadata_panel = QWidget(splitter)
        metadata_layout = QVBoxLayout(metadata_panel)
        metadata_layout.setContentsMargins(0, 0, 0, 0)
        metadata_layout.setSpacing(12)

        metadata_box = QGroupBox("Release Metadata", metadata_panel)
        form = QFormLayout(metadata_box)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignTop)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)

        self.title_edit = QLineEdit()
        form.addRow("Release Title", self.title_edit)

        self.subtitle_edit = QLineEdit()
        form.addRow("Version / Subtitle", self.subtitle_edit)

        self.primary_artist_edit = QLineEdit()
        form.addRow("Primary Artist", self.primary_artist_edit)

        self.album_artist_edit = QLineEdit()
        form.addRow("Album Artist", self.album_artist_edit)

        self.release_type_combo = QComboBox()
        self.release_type_combo.addItems(
            [value.replace("_", " ").title() for value in RELEASE_TYPE_CHOICES]
        )
        form.addRow("Release Type", self.release_type_combo)

        self.release_date_edit = QLineEdit()
        self.release_date_edit.setPlaceholderText("YYYY-MM-DD")
        form.addRow("Release Date", self.release_date_edit)

        self.original_release_date_edit = QLineEdit()
        self.original_release_date_edit.setPlaceholderText("YYYY-MM-DD")
        form.addRow("Original Release Date", self.original_release_date_edit)

        self.label_edit = QLineEdit()
        form.addRow("Label", self.label_edit)

        self.sublabel_edit = QLineEdit()
        form.addRow("Sublabel", self.sublabel_edit)

        self.catalog_number_edit = QLineEdit()
        form.addRow("Catalog#", self.catalog_number_edit)

        self.upc_edit = QLineEdit()
        form.addRow("UPC / EAN", self.upc_edit)

        self.territory_edit = QLineEdit()
        self.territory_edit.setPlaceholderText("Worldwide / EU / NL / etc.")
        form.addRow("Territory / Market", self.territory_edit)

        self.status_combo = QComboBox()
        self.status_combo.addItem("")
        self.status_combo.addItems(
            [value.replace("_", " ").title() for value in REPERTOIRE_STATUS_CHOICES]
        )
        form.addRow("Workflow Status", self.status_combo)

        self.explicit_checkbox = QCheckBox("Explicit release")
        self.metadata_checkbox = QCheckBox("Metadata Complete")
        self.contract_checkbox = QCheckBox("Contract Signed")
        self.rights_checkbox = QCheckBox("Rights Verified")
        checklist_row = QWidget()
        checklist_layout = QHBoxLayout(checklist_row)
        checklist_layout.setContentsMargins(0, 0, 0, 0)
        checklist_layout.setSpacing(8)
        for widget in (
            self.explicit_checkbox,
            self.metadata_checkbox,
            self.contract_checkbox,
            self.rights_checkbox,
        ):
            checklist_layout.addWidget(widget)
        checklist_layout.addStretch(1)
        form.addRow("Checklist", checklist_row)

        self.artwork_path_edit = QLineEdit()
        self.artwork_path_edit.setReadOnly(True)
        artwork_row = QWidget()
        artwork_layout = QHBoxLayout(artwork_row)
        artwork_layout.setContentsMargins(0, 0, 0, 0)
        artwork_layout.setSpacing(8)
        artwork_layout.addWidget(self.artwork_path_edit, 1)
        browse_button = QPushButton("Browse…")
        browse_button.clicked.connect(self._pick_artwork)
        clear_button = QPushButton("Clear")
        clear_button.clicked.connect(self._clear_artwork)
        artwork_layout.addWidget(browse_button)
        artwork_layout.addWidget(clear_button)
        form.addRow("Artwork", artwork_row)

        self.artwork_storage_mode_combo = QComboBox()
        self.artwork_storage_mode_combo.addItem("Database (BLOB)", STORAGE_MODE_DATABASE)
        self.artwork_storage_mode_combo.addItem("Managed file", STORAGE_MODE_MANAGED_FILE)
        form.addRow("Artwork Storage", self.artwork_storage_mode_combo)

        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setMinimumHeight(120)
        form.addRow("Release Notes", self.notes_edit)

        metadata_layout.addWidget(metadata_box)
        metadata_layout.addStretch(1)
        splitter.addWidget(metadata_panel)

        tracks_panel = QWidget(splitter)
        tracks_layout = QVBoxLayout(tracks_panel)
        tracks_layout.setContentsMargins(0, 0, 0, 0)
        tracks_layout.setSpacing(12)

        tracks_box = QGroupBox("Release Track Order", tracks_panel)
        tracks_box_layout = QVBoxLayout(tracks_box)
        tracks_box_layout.setContentsMargins(12, 12, 12, 12)
        tracks_box_layout.setSpacing(10)

        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(8)
        action_row.addStretch(1)

        add_selected_button = QPushButton("Add Selected Tracks")
        add_selected_button.clicked.connect(self._add_selected_tracks)
        action_row.addWidget(add_selected_button)

        remove_rows_button = QPushButton("Remove Highlighted")
        remove_rows_button.clicked.connect(self._remove_selected_rows)
        action_row.addWidget(remove_rows_button)

        move_up_button = QPushButton("Move Up")
        move_up_button.clicked.connect(lambda: self._move_selected_row(-1))
        action_row.addWidget(move_up_button)

        move_down_button = QPushButton("Move Down")
        move_down_button.clicked.connect(lambda: self._move_selected_row(1))
        action_row.addWidget(move_down_button)

        renumber_button = QPushButton("Renumber")
        renumber_button.clicked.connect(self._renumber_rows)
        action_row.addWidget(renumber_button)
        tracks_box_layout.addLayout(action_row)

        self.tracks_table = QTableWidget(0, 5, tracks_box)
        self.tracks_table.setHorizontalHeaderLabels(
            ["Track ID", "Track Title", "Disc #", "Track #", "Sequence"]
        )
        self.tracks_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tracks_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tracks_table.setEditTriggers(
            QAbstractItemView.DoubleClicked
            | QAbstractItemView.EditKeyPressed
            | QAbstractItemView.SelectedClicked
        )
        self.tracks_table.verticalHeader().setVisible(False)
        self.tracks_table.horizontalHeader().setStretchLastSection(True)
        tracks_box_layout.addWidget(self.tracks_table, 1)
        tracks_layout.addWidget(tracks_box, 1)
        splitter.addWidget(tracks_panel)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 5)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(8)
        buttons.addStretch(1)
        save_button = QPushButton("Save Release")
        save_button.setDefault(True)
        save_button.clicked.connect(self.accept)
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        buttons.addWidget(save_button)
        buttons.addWidget(cancel_button)
        root.addLayout(buttons)

        self._clear_artwork_requested = False
        self._original_artwork_display_path = ""
        self._populate(release, placements or [])

    def _populate(
        self, release: ReleaseRecord | None, placements: list[ReleaseTrackPlacement]
    ) -> None:
        if release is None:
            self.release_type_combo.setCurrentText("Album")
            self.artwork_storage_mode_combo.setCurrentIndex(1)
            self._original_artwork_display_path = ""
            self._load_placements(placements)
            return

        self.title_edit.setText(release.title or "")
        self.subtitle_edit.setText(release.version_subtitle or "")
        self.primary_artist_edit.setText(release.primary_artist or "")
        self.album_artist_edit.setText(release.album_artist or "")
        self.release_type_combo.setCurrentText(
            (release.release_type or "album").replace("_", " ").title()
        )
        self.release_date_edit.setText(release.release_date or "")
        self.original_release_date_edit.setText(release.original_release_date or "")
        self.label_edit.setText(release.label or "")
        self.sublabel_edit.setText(release.sublabel or "")
        self.catalog_number_edit.setText(release.catalog_number or "")
        self.upc_edit.setText(release.upc or "")
        self.territory_edit.setText(release.territory or "")
        self.status_combo.setCurrentText(
            (release.repertoire_status or "").replace("_", " ").title()
        )
        self.explicit_checkbox.setChecked(bool(release.explicit_flag))
        self.metadata_checkbox.setChecked(bool(release.metadata_complete))
        self.contract_checkbox.setChecked(bool(release.contract_signed))
        self.rights_checkbox.setChecked(bool(release.rights_verified))
        self.notes_edit.setPlainText(release.notes or "")
        artwork_path = self.release_service.resolve_artwork_path(release.artwork_path)
        self._original_artwork_display_path = str(artwork_path) if artwork_path is not None else ""
        self.artwork_path_edit.setText(self._original_artwork_display_path)
        self.artwork_storage_mode_combo.setCurrentIndex(
            0
            if normalize_storage_mode(
                release.artwork_storage_mode, default=STORAGE_MODE_MANAGED_FILE
            )
            == STORAGE_MODE_DATABASE
            else 1
        )
        self._load_placements(placements)

    def _load_placements(self, placements: list[ReleaseTrackPlacement]) -> None:
        self.tracks_table.setRowCount(0)
        for placement in placements:
            self._append_placement_row(placement)
        if self.tracks_table.rowCount() == 0:
            self._add_selected_tracks()

    def _append_placement_row(self, placement: ReleaseTrackPlacement) -> None:
        row = self.tracks_table.rowCount()
        self.tracks_table.insertRow(row)
        values = [
            str(int(placement.track_id)),
            self.track_title_resolver(int(placement.track_id)),
            str(max(1, int(placement.disc_number or 1))),
            str(max(1, int(placement.track_number or row + 1))),
            str(max(1, int(placement.sequence_number or row + 1))),
        ]
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            if column in {0, 1}:
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self.tracks_table.setItem(row, column, item)

    def _pick_artwork(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose Release Artwork",
            "",
            "Images (*.png *.jpg *.jpeg *.webp *.gif *.bmp *.tif *.tiff);;All files (*)",
        )
        if not path:
            return
        self._clear_artwork_requested = False
        self.artwork_path_edit.setText(path)

    def _clear_artwork(self) -> None:
        self._clear_artwork_requested = True
        self.artwork_path_edit.clear()

    def _add_selected_tracks(self) -> None:
        selected_track_ids = list(self.selected_track_ids_provider() or [])
        existing_track_ids = {
            int(self.tracks_table.item(row, 0).text())
            for row in range(self.tracks_table.rowCount())
            if self.tracks_table.item(row, 0) is not None
        }
        next_sequence = self.tracks_table.rowCount() + 1
        for track_id in selected_track_ids:
            clean_track_id = int(track_id)
            if clean_track_id <= 0 or clean_track_id in existing_track_ids:
                continue
            self._append_placement_row(
                ReleaseTrackPlacement(
                    track_id=clean_track_id,
                    disc_number=1,
                    track_number=next_sequence,
                    sequence_number=next_sequence,
                )
            )
            existing_track_ids.add(clean_track_id)
            next_sequence += 1

    def _remove_selected_rows(self) -> None:
        rows = sorted({index.row() for index in self.tracks_table.selectedIndexes()}, reverse=True)
        for row in rows:
            self.tracks_table.removeRow(row)
        self._renumber_rows()

    def _move_selected_row(self, offset: int) -> None:
        row = self.tracks_table.currentRow()
        if row < 0:
            return
        target = row + offset
        if target < 0 or target >= self.tracks_table.rowCount():
            return
        values = [
            self.tracks_table.item(row, column).text()
            for column in range(self.tracks_table.columnCount())
        ]
        target_values = [
            self.tracks_table.item(target, column).text()
            for column in range(self.tracks_table.columnCount())
        ]
        for column, value in enumerate(target_values):
            self.tracks_table.item(row, column).setText(value)
        for column, value in enumerate(values):
            self.tracks_table.item(target, column).setText(value)
        self.tracks_table.selectRow(target)
        self._renumber_rows()

    def _renumber_rows(self) -> None:
        for row in range(self.tracks_table.rowCount()):
            track_item = self.tracks_table.item(row, 3)
            sequence_item = self.tracks_table.item(row, 4)
            if track_item is not None and not track_item.text().strip():
                track_item.setText(str(row + 1))
            if sequence_item is not None:
                sequence_item.setText(str(row + 1))

    def placements(self) -> list[ReleaseTrackPlacement]:
        placements: list[ReleaseTrackPlacement] = []
        seen: set[int] = set()
        for row in range(self.tracks_table.rowCount()):
            try:
                track_id = int(self.tracks_table.item(row, 0).text())
            except Exception:
                continue
            if track_id <= 0 or track_id in seen:
                continue
            seen.add(track_id)
            placements.append(
                ReleaseTrackPlacement(
                    track_id=track_id,
                    disc_number=max(1, int(self.tracks_table.item(row, 2).text() or 1)),
                    track_number=max(1, int(self.tracks_table.item(row, 3).text() or row + 1)),
                    sequence_number=max(1, int(self.tracks_table.item(row, 4).text() or row + 1)),
                )
            )
        return placements

    def payload(self) -> ReleasePayload:
        release_type = self.release_type_combo.currentText().strip().lower().replace(" ", "_")
        artwork_source_path = self.artwork_path_edit.text().strip() or None
        if artwork_source_path == self._original_artwork_display_path:
            artwork_source_path = None
        artwork_storage_mode = self.artwork_storage_mode_combo.currentData()
        if not artwork_source_path and self._clear_artwork_requested:
            artwork_storage_mode = None
        return ReleasePayload(
            title=self.title_edit.text().strip(),
            version_subtitle=self.subtitle_edit.text().strip() or None,
            primary_artist=self.primary_artist_edit.text().strip() or None,
            album_artist=self.album_artist_edit.text().strip() or None,
            release_type=release_type,
            release_date=self.release_date_edit.text().strip() or None,
            original_release_date=self.original_release_date_edit.text().strip() or None,
            label=self.label_edit.text().strip() or None,
            sublabel=self.sublabel_edit.text().strip() or None,
            catalog_number=self.catalog_number_edit.text().strip() or None,
            upc=self.upc_edit.text().strip() or None,
            territory=self.territory_edit.text().strip() or None,
            explicit_flag=self.explicit_checkbox.isChecked(),
            repertoire_status=self.status_combo.currentText().strip().lower().replace(" ", "_")
            or None,
            metadata_complete=self.metadata_checkbox.isChecked(),
            contract_signed=self.contract_checkbox.isChecked(),
            rights_verified=self.rights_checkbox.isChecked(),
            notes=self.notes_edit.toPlainText().strip() or None,
            artwork_source_path=artwork_source_path,
            artwork_storage_mode=artwork_storage_mode,
            clear_artwork=bool(self._clear_artwork_requested and not artwork_source_path),
            profile_name=self.profile_name,
            placements=self.placements(),
        )

    def accept(self) -> None:
        payload = self.payload()
        issues = self.release_service.validate_release(
            payload,
            release_id=self.release.id if self.release is not None else None,
        )
        errors = [issue.message for issue in issues if issue.severity == "error"]
        if errors:
            QMessageBox.warning(self, "Release Validation", "\n".join(errors))
            return
        if not payload.placements:
            QMessageBox.warning(
                self, "Release Validation", "Attach at least one track to the release."
            )
            return
        super().accept()


class ReleaseBrowserPanel(QWidget):
    """Browse, edit, and inspect first-class releases inside a reusable workspace panel."""

    filter_requested = Signal(list)
    open_track_requested = Signal(int)
    edit_release_requested = Signal(int)
    duplicate_release_requested = Signal(int)
    add_selected_tracks_requested = Signal(int)
    create_release_requested = Signal()
    close_requested = Signal()

    def __init__(
        self,
        *,
        release_service_provider,
        track_title_resolver,
        parent=None,
    ):
        super().__init__(parent)
        self.release_service_provider = release_service_provider
        self.track_title_resolver = track_title_resolver
        self._release_ids_by_row: list[int] = []
        self._current_summary: ReleaseSummary | None = None

        self.setObjectName("releaseBrowserPanel")
        _apply_standard_widget_chrome(self, "releaseBrowserPanel")

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(14)
        _add_standard_dialog_header(
            root,
            self,
            title="Release Browser",
            subtitle=(
                "Browse releases, inspect summary metadata, and attach the current track "
                "selection without leaving the catalog."
            ),
        )

        controls_box, controls_layout = _create_standard_section(
            self,
            "Find and Create",
            "Search releases by title or artist, then create a new release when you need a new container for the current catalog selection.",
        )
        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(8)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search releases...")
        self.search_edit.textChanged.connect(self.refresh)
        controls.addWidget(self.search_edit, 1)

        new_button = QPushButton("Create Release")
        new_button.clicked.connect(self.create_release_requested.emit)
        controls.addWidget(new_button)
        controls_layout.addLayout(controls)
        root.addWidget(controls_box)

        splitter = QSplitter(Qt.Horizontal, self)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, 1)

        list_panel = QWidget(splitter)
        list_layout = QVBoxLayout(list_panel)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(0)
        list_box, list_box_layout = _create_standard_section(
            self,
            "Releases",
            "Select a release to inspect its overview and track list on the right.",
        )

        self.release_table = QTableWidget(0, 7, list_box)
        self.release_table.setHorizontalHeaderLabels(
            ["ID", "Title", "Artist", "Type", "Status", "Release Date", "Tracks"]
        )
        self.release_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.release_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.release_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.release_table.verticalHeader().setVisible(False)
        self.release_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.release_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.release_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.release_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.release_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.release_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.release_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.release_table.itemSelectionChanged.connect(self._load_selected_release)
        list_box_layout.addWidget(self.release_table, 1)
        self.release_count_label = QLabel("No releases loaded.")
        self.release_count_label.setProperty("role", "secondary")
        list_box_layout.addWidget(self.release_count_label)
        list_layout.addWidget(list_box, 1)
        splitter.addWidget(list_panel)

        detail_panel = QWidget(splitter)
        detail_layout = QVBoxLayout(detail_panel)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.setSpacing(10)

        detail_tabs = QTabWidget(detail_panel)
        detail_layout.addWidget(detail_tabs, 1)

        overview_tab = QWidget(detail_tabs)
        overview_tab_layout = QVBoxLayout(overview_tab)
        overview_tab_layout.setContentsMargins(0, 0, 0, 0)
        overview_tab_layout.setSpacing(0)
        overview_scroll, _, overview_layout = _create_scrollable_dialog_content(self)

        identity_box, identity_layout = _create_standard_section(
            self,
            "Release Overview",
            "Core release identity, barcode, catalog number, and market-facing information.",
        )
        identity_form = QFormLayout()
        _configure_standard_form_layout(identity_form)
        self._summary_fields: dict[str, QLabel] = {}

        def _summary_label() -> QLabel:
            label = QLabel("")
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
            return label

        for key, title in (
            ("title", "Title"),
            ("primary_artist", "Primary Artist"),
            ("album_artist", "Album Artist"),
            ("release_type", "Type"),
            ("release_date", "Release Date"),
            ("original_release_date", "Original Release Date"),
            ("label", "Label"),
            ("sublabel", "Sublabel"),
            ("catalog_number", "Catalog #"),
            ("upc", "UPC / EAN"),
            ("barcode_status", "Barcode Status"),
            ("territory", "Territory"),
            ("artwork_path", "Artwork"),
        ):
            value_label = _summary_label()
            self._summary_fields[key] = value_label
            identity_form.addRow(title, value_label)
        identity_layout.addLayout(identity_form)
        overview_layout.addWidget(identity_box)

        workflow_box, workflow_layout = _create_standard_section(
            self,
            "Workflow and Validation",
            "Operational status and readiness fields for the selected release.",
        )
        workflow_form = QFormLayout()
        _configure_standard_form_layout(workflow_form)
        for key, title in (
            ("workflow_status", "Workflow Status"),
            ("track_count", "Track Count"),
            ("explicit", "Explicit"),
            ("metadata_complete", "Metadata Complete"),
            ("contract_signed", "Contract Signed"),
            ("rights_verified", "Rights Verified"),
        ):
            value_label = _summary_label()
            self._summary_fields[key] = value_label
            workflow_form.addRow(title, value_label)
        workflow_layout.addLayout(workflow_form)
        overview_layout.addWidget(workflow_box)
        overview_layout.addStretch(1)
        overview_tab_layout.addWidget(overview_scroll, 1)
        detail_tabs.addTab(overview_tab, "Overview")

        tracks_tab = QWidget(detail_tabs)
        tracks_tab_layout = QVBoxLayout(tracks_tab)
        tracks_tab_layout.setContentsMargins(0, 0, 0, 0)
        tracks_tab_layout.setSpacing(0)
        tracks_box, tracks_box_layout = _create_standard_section(
            self,
            "Release Track List",
            "Track order for the selected release. Select a row and use the action below to open the corresponding catalog track.",
        )
        self.track_table = QTableWidget(0, 4, tracks_box)
        self.track_table.setHorizontalHeaderLabels(["Track ID", "Track Title", "Disc #", "Track #"])
        self.track_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.track_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.track_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.track_table.verticalHeader().setVisible(False)
        self.track_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.track_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.track_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.track_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        tracks_box_layout.addWidget(self.track_table, 1)
        tracks_tab_layout.addWidget(tracks_box, 1)
        detail_tabs.addTab(tracks_tab, "Tracks")

        actions_box, actions_layout = _create_standard_section(
            self,
            "Release Actions",
            "Edit or duplicate the release, attach the current selection, filter the main table, or open the highlighted track.",
        )
        action_grid = QGridLayout()
        action_grid.setContentsMargins(0, 0, 0, 0)
        action_grid.setHorizontalSpacing(8)
        action_grid.setVerticalSpacing(8)
        edit_button = QPushButton("Edit Release")
        edit_button.clicked.connect(self._emit_edit_current)
        action_grid.addWidget(edit_button, 0, 0)
        duplicate_button = QPushButton("Duplicate Release")
        duplicate_button.clicked.connect(self._emit_duplicate_current)
        action_grid.addWidget(duplicate_button, 0, 1)
        add_selection_button = QPushButton("Add Selected Tracks")
        add_selection_button.clicked.connect(self._emit_add_selected_current)
        action_grid.addWidget(add_selection_button, 1, 0)
        filter_button = QPushButton("Filter Catalog To Release")
        filter_button.clicked.connect(self._emit_filter_current)
        action_grid.addWidget(filter_button, 1, 1)
        open_track_button = QPushButton("Open Selected Track")
        open_track_button.clicked.connect(self._emit_open_track_current)
        action_grid.addWidget(open_track_button, 2, 0, 1, 2)
        actions_layout.addLayout(action_grid)
        detail_layout.addWidget(actions_box)

        splitter.addWidget(detail_panel)
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 4)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.close_requested.emit)
        buttons.addWidget(close_button)
        root.addLayout(buttons)

        _apply_compact_dialog_control_heights(self)
        self.refresh()

    def _release_service(self) -> ReleaseService | None:
        service = self.release_service_provider()
        return service

    def refresh(self) -> None:
        service = self._release_service()
        if service is None:
            self._release_ids_by_row = []
            self.release_table.setRowCount(0)
            self.track_table.setRowCount(0)
            self.release_count_label.setText("Open a profile first to browse releases.")
            for label in self._summary_fields.values():
                label.setText("")
            return

        releases = service.list_releases(search_text=self.search_edit.text().strip())
        self._release_ids_by_row = [release.id for release in releases]
        self.release_count_label.setText(
            f"{len(releases)} release{'s' if len(releases) != 1 else ''} shown."
        )
        self.release_table.setRowCount(len(releases))
        for row, release in enumerate(releases):
            values = [
                str(release.id),
                release.title,
                release.primary_artist or "",
                release.release_type.replace("_", " ").title(),
                (release.repertoire_status or "").replace("_", " ").title(),
                release.release_date or "",
                str(release.track_count),
            ]
            for column, value in enumerate(values):
                self.release_table.setItem(row, column, QTableWidgetItem(value))
        if releases:
            self.release_table.selectRow(0)
        else:
            for label in self._summary_fields.values():
                label.setText("")
            self.track_table.setRowCount(0)

    def _selected_release_id(self) -> int | None:
        row = self.release_table.currentRow()
        if row < 0 or row >= len(self._release_ids_by_row):
            return None
        return int(self._release_ids_by_row[row])

    def _load_selected_release(self) -> None:
        service = self._release_service()
        release_id = self._selected_release_id()
        if service is None or release_id is None:
            self._current_summary = None
            for label in self._summary_fields.values():
                label.setText("")
            self.track_table.setRowCount(0)
            return
        self._current_summary = service.fetch_release_summary(release_id)
        if self._current_summary is None:
            return
        release = self._current_summary.release
        summary_values = {
            "title": release.title,
            "primary_artist": release.primary_artist or "",
            "album_artist": release.album_artist or "",
            "release_type": release.release_type.replace("_", " ").title(),
            "release_date": release.release_date or "",
            "original_release_date": release.original_release_date or "",
            "label": release.label or "",
            "sublabel": release.sublabel or "",
            "catalog_number": release.catalog_number or "",
            "upc": release.upc or "",
            "barcode_status": release.barcode_validation_status or "",
            "territory": release.territory or "",
            "workflow_status": (release.repertoire_status or "").replace("_", " ").title(),
            "track_count": str(len(self._current_summary.tracks)),
            "explicit": "Yes" if release.explicit_flag else "No",
            "metadata_complete": "Yes" if release.metadata_complete else "No",
            "contract_signed": "Yes" if release.contract_signed else "No",
            "rights_verified": "Yes" if release.rights_verified else "No",
            "artwork_path": release.artwork_path or "",
        }
        for key, label in self._summary_fields.items():
            label.setText(summary_values.get(key, ""))
        self.track_table.setRowCount(len(self._current_summary.tracks))
        for row, placement in enumerate(self._current_summary.tracks):
            values = [
                str(placement.track_id),
                self.track_title_resolver(placement.track_id),
                str(placement.disc_number),
                str(placement.track_number),
            ]
            for column, value in enumerate(values):
                self.track_table.setItem(row, column, QTableWidgetItem(value))

    def _emit_edit_current(self) -> None:
        release_id = self._selected_release_id()
        if release_id is not None:
            self.edit_release_requested.emit(release_id)

    def _emit_duplicate_current(self) -> None:
        release_id = self._selected_release_id()
        if release_id is not None:
            self.duplicate_release_requested.emit(release_id)

    def _emit_add_selected_current(self) -> None:
        release_id = self._selected_release_id()
        if release_id is not None:
            self.add_selected_tracks_requested.emit(release_id)

    def _emit_filter_current(self) -> None:
        if self._current_summary is None:
            return
        self.filter_requested.emit(
            [placement.track_id for placement in self._current_summary.tracks]
        )

    def _emit_open_track_current(self) -> None:
        row = self.track_table.currentRow()
        if row < 0 or self.track_table.item(row, 0) is None:
            return
        try:
            track_id = int(self.track_table.item(row, 0).text())
        except Exception:
            return
        if track_id > 0:
            self.open_track_requested.emit(track_id)


class ReleaseBrowserDialog(QDialog):
    """Compatibility dialog wrapper around the reusable release browser panel."""

    filter_requested = Signal(list)
    open_track_requested = Signal(int)
    edit_release_requested = Signal(int)
    duplicate_release_requested = Signal(int)
    add_selected_tracks_requested = Signal(int)
    create_release_requested = Signal()

    def __init__(
        self,
        *,
        release_service: ReleaseService,
        track_title_resolver,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Release Browser")
        self.resize(1160, 780)
        self.setMinimumSize(1020, 700)
        _apply_standard_dialog_chrome(self, "releaseBrowserDialog")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.panel = ReleaseBrowserPanel(
            release_service_provider=lambda: release_service,
            track_title_resolver=track_title_resolver,
            parent=self,
        )
        self.panel.filter_requested.connect(self.filter_requested.emit)
        self.panel.open_track_requested.connect(self.open_track_requested.emit)
        self.panel.edit_release_requested.connect(self.edit_release_requested.emit)
        self.panel.duplicate_release_requested.connect(self.duplicate_release_requested.emit)
        self.panel.add_selected_tracks_requested.connect(self.add_selected_tracks_requested.emit)
        self.panel.create_release_requested.connect(self.create_release_requested.emit)
        self.panel.close_requested.connect(self.accept)
        root.addWidget(self.panel)

    def __getattr__(self, name: str):
        panel = self.__dict__.get("panel")
        if panel is not None and hasattr(panel, name):
            return getattr(panel, name)
        raise AttributeError(name)

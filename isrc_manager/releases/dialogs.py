"""Release management dialogs."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QCompleter,
    QDialog,
    QFileDialog,
    QFormLayout,
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
from isrc_manager.selection_scope import (
    SelectionScopeBanner,
    SelectionScopeState,
    TrackChoice,
    TrackSelectionChooserDialog,
    build_selection_preview,
)
from isrc_manager.services.repertoire_status import REPERTOIRE_STATUS_CHOICES
from isrc_manager.ui_common import (
    FocusWheelComboBox,
    _add_standard_dialog_header,
    _apply_compact_dialog_control_heights,
    _apply_standard_dialog_chrome,
    _apply_standard_widget_chrome,
    _configure_standard_form_layout,
    _create_action_button_cluster,
    _create_action_button_grid,
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
        self.setObjectName("releaseEditorDialog")
        self.setWindowTitle("Edit Release" if release is not None else "Create Release")
        self.resize(960, 720)
        self.setMinimumSize(880, 640)
        self.setModal(True)
        _apply_standard_dialog_chrome(self, "releaseEditorDialog")

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        _add_standard_dialog_header(
            root,
            self,
            title=self.windowTitle(),
            subtitle=(
                "Keep release identity, dates, artwork, and ordered track placement together "
                "without leaving the current selection workflow."
            ),
        )

        splitter = QSplitter(Qt.Horizontal, self)
        root.addWidget(splitter, 1)

        metadata_scroll, _, metadata_layout = _create_scrollable_dialog_content(splitter)
        metadata_layout.setSpacing(12)

        def stored_value_combo(query: str) -> FocusWheelComboBox:
            combo = FocusWheelComboBox(self)
            combo.setEditable(True)
            combo.addItem("")
            values: list[str] = []
            seen: set[str] = set()
            conn = getattr(self.release_service, "conn", None)
            if conn is not None:
                for row in conn.execute(query).fetchall():
                    value = str(row[0] or "").strip()
                    if not value or value in seen:
                        continue
                    seen.add(value)
                    values.append(value)
            combo.addItems(values)
            completer = QCompleter(values, combo)
            completer.setCaseSensitivity(Qt.CaseInsensitive)
            combo.setCompleter(completer)
            return combo

        metadata_box = QGroupBox("Release Metadata", metadata_scroll)
        metadata_box_layout = QVBoxLayout(metadata_box)
        metadata_box_layout.setContentsMargins(12, 12, 12, 12)
        metadata_box_layout.setSpacing(12)

        identity_group = QGroupBox("Identity & Credits", metadata_box)
        identity_form = QFormLayout(identity_group)
        _configure_standard_form_layout(identity_form)

        scheduling_group = QGroupBox("Release Details", metadata_box)
        scheduling_form = QFormLayout(scheduling_group)
        _configure_standard_form_layout(scheduling_form)

        artwork_group = QGroupBox("Artwork & Notes", metadata_box)
        artwork_form = QFormLayout(artwork_group)
        _configure_standard_form_layout(artwork_form)

        self.title_edit = QLineEdit()
        identity_form.addRow("Release Title", self.title_edit)

        self.subtitle_edit = QLineEdit()
        identity_form.addRow("Version / Subtitle", self.subtitle_edit)

        self.primary_artist_edit = stored_value_combo(
            """
            SELECT value
            FROM (
                SELECT name AS value
                FROM Artists
                WHERE name IS NOT NULL AND name != ''
                UNION
                SELECT primary_artist AS value
                FROM Releases
                WHERE primary_artist IS NOT NULL AND primary_artist != ''
                UNION
                SELECT album_artist AS value
                FROM Releases
                WHERE album_artist IS NOT NULL AND album_artist != ''
            )
            ORDER BY value
            """
        )
        identity_form.addRow("Primary Artist", self.primary_artist_edit)

        self.album_artist_edit = stored_value_combo(
            """
            SELECT value
            FROM (
                SELECT name AS value
                FROM Artists
                WHERE name IS NOT NULL AND name != ''
                UNION
                SELECT primary_artist AS value
                FROM Releases
                WHERE primary_artist IS NOT NULL AND primary_artist != ''
                UNION
                SELECT album_artist AS value
                FROM Releases
                WHERE album_artist IS NOT NULL AND album_artist != ''
            )
            ORDER BY value
            """
        )
        identity_form.addRow("Album Artist", self.album_artist_edit)

        self.release_type_combo = QComboBox()
        self.release_type_combo.addItems(
            [value.replace("_", " ").title() for value in RELEASE_TYPE_CHOICES]
        )
        scheduling_form.addRow("Release Type", self.release_type_combo)

        self.release_date_edit = QLineEdit()
        self.release_date_edit.setPlaceholderText("YYYY-MM-DD")
        scheduling_form.addRow("Release Date", self.release_date_edit)

        self.original_release_date_edit = QLineEdit()
        self.original_release_date_edit.setPlaceholderText("YYYY-MM-DD")
        scheduling_form.addRow("Original Release Date", self.original_release_date_edit)

        self.label_edit = stored_value_combo(
            """
            SELECT value
            FROM (
                SELECT publisher AS value
                FROM Tracks
                WHERE publisher IS NOT NULL AND publisher != ''
                UNION
                SELECT label AS value
                FROM Releases
                WHERE label IS NOT NULL AND label != ''
            )
            ORDER BY value
            """
        )
        identity_form.addRow("Label", self.label_edit)

        self.sublabel_edit = stored_value_combo(
            """
            SELECT sublabel
            FROM Releases
            WHERE sublabel IS NOT NULL AND sublabel != ''
            GROUP BY sublabel
            ORDER BY sublabel
            """
        )
        identity_form.addRow("Sublabel", self.sublabel_edit)

        self.catalog_number_edit = stored_value_combo(
            """
            SELECT value
            FROM (
                SELECT catalog_number AS value
                FROM Tracks
                WHERE catalog_number IS NOT NULL AND catalog_number != ''
                UNION
                SELECT catalog_number AS value
                FROM Releases
                WHERE catalog_number IS NOT NULL AND catalog_number != ''
            )
            ORDER BY value
            """
        )
        scheduling_form.addRow("Catalog#", self.catalog_number_edit)

        self.upc_edit = stored_value_combo(
            """
            SELECT value
            FROM (
                SELECT upc AS value FROM Tracks WHERE upc IS NOT NULL AND upc != ''
                UNION
                SELECT upc AS value FROM Releases WHERE upc IS NOT NULL AND upc != ''
            )
            ORDER BY value
            """
        )
        scheduling_form.addRow("UPC / EAN", self.upc_edit)

        self.territory_edit = QLineEdit()
        self.territory_edit.setPlaceholderText("Worldwide / EU / NL / etc.")
        scheduling_form.addRow("Territory / Market", self.territory_edit)

        self.status_combo = QComboBox()
        self.status_combo.addItem("")
        self.status_combo.addItems(
            [value.replace("_", " ").title() for value in REPERTOIRE_STATUS_CHOICES]
        )
        scheduling_form.addRow("Workflow Status", self.status_combo)

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
        scheduling_form.addRow("Checklist", checklist_row)

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
        artwork_form.addRow("Artwork", artwork_row)

        self.artwork_storage_mode_combo = QComboBox()
        self.artwork_storage_mode_combo.addItem("Stored in Database", STORAGE_MODE_DATABASE)
        self.artwork_storage_mode_combo.addItem("Managed File", STORAGE_MODE_MANAGED_FILE)
        artwork_form.addRow("Artwork Storage", self.artwork_storage_mode_combo)

        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setMinimumHeight(120)
        artwork_form.addRow("Release Notes", self.notes_edit)

        metadata_box_layout.addWidget(identity_group)
        metadata_box_layout.addWidget(scheduling_group)
        metadata_box_layout.addWidget(artwork_group)

        metadata_layout.addWidget(metadata_box)
        metadata_layout.addStretch(1)
        splitter.addWidget(metadata_scroll)

        tracks_panel = QWidget(splitter)
        tracks_layout = QVBoxLayout(tracks_panel)
        tracks_layout.setContentsMargins(0, 0, 0, 0)
        tracks_layout.setSpacing(12)

        tracks_box = QGroupBox("Release Track Order", tracks_panel)
        tracks_box_layout = QVBoxLayout(tracks_box)
        tracks_box_layout.setContentsMargins(12, 12, 12, 12)
        tracks_box_layout.setSpacing(10)

        add_selected_button = QPushButton("Add Selected Tracks")
        add_selected_button.clicked.connect(self._add_selected_tracks)

        remove_rows_button = QPushButton("Remove Highlighted")
        remove_rows_button.clicked.connect(self._remove_selected_rows)

        move_up_button = QPushButton("Move Up")
        move_up_button.clicked.connect(lambda: self._move_selected_row(-1))

        move_down_button = QPushButton("Move Down")
        move_down_button.clicked.connect(lambda: self._move_selected_row(1))

        renumber_button = QPushButton("Renumber")
        renumber_button.clicked.connect(self._renumber_rows)
        tracks_box_layout.addWidget(
            _create_action_button_grid(
                tracks_box,
                [
                    add_selected_button,
                    remove_rows_button,
                    move_up_button,
                    move_down_button,
                    renumber_button,
                ],
                columns=2,
            )
        )

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
        _apply_compact_dialog_control_heights(self)

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
        self.primary_artist_edit.setCurrentText(release.primary_artist or "")
        self.album_artist_edit.setCurrentText(release.album_artist or "")
        self.release_type_combo.setCurrentText(
            (release.release_type or "album").replace("_", " ").title()
        )
        self.release_date_edit.setText(release.release_date or "")
        self.original_release_date_edit.setText(release.original_release_date or "")
        self.label_edit.setCurrentText(release.label or "")
        self.sublabel_edit.setCurrentText(release.sublabel or "")
        self.catalog_number_edit.setCurrentText(release.catalog_number or "")
        self.upc_edit.setCurrentText(release.upc or "")
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
            primary_artist=self.primary_artist_edit.currentText().strip() or None,
            album_artist=self.album_artist_edit.currentText().strip() or None,
            release_type=release_type,
            release_date=self.release_date_edit.text().strip() or None,
            original_release_date=self.original_release_date_edit.text().strip() or None,
            label=self.label_edit.currentText().strip() or None,
            sublabel=self.sublabel_edit.currentText().strip() or None,
            catalog_number=self.catalog_number_edit.currentText().strip() or None,
            upc=self.upc_edit.currentText().strip() or None,
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
    add_selected_tracks_requested = Signal(int, list)
    create_release_requested = Signal(list)
    close_requested = Signal()

    def __init__(
        self,
        *,
        release_service_provider,
        track_title_resolver,
        selected_track_ids_provider=None,
        track_choice_provider=None,
        parent=None,
    ):
        super().__init__(parent)
        self.release_service_provider = release_service_provider
        self.track_title_resolver = track_title_resolver
        self.selected_track_ids_provider = selected_track_ids_provider or (lambda: [])
        self.track_choice_provider = track_choice_provider or (lambda: [])
        self._release_ids_by_row: list[int] = []
        self._current_summary: ReleaseSummary | None = None
        self._selection_override_track_ids: list[int] = []

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
        controls.setSpacing(10)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search releases...")
        self.search_edit.textChanged.connect(self.refresh)
        controls.addWidget(self.search_edit, 1)

        new_button = QPushButton("Create Release")
        new_button.clicked.connect(self._emit_create_release_current)
        controls.addWidget(new_button)
        controls_layout.addLayout(controls)
        self.selection_banner = SelectionScopeBanner(parent=self)
        self.selection_banner.use_current_button.clicked.connect(self._use_current_selection)
        self.selection_banner.choose_button.clicked.connect(self._choose_tracks)
        self.selection_banner.clear_override_button.clicked.connect(self._clear_selection_override)
        controls_layout.addWidget(self.selection_banner)
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

        self.detail_scroll_area, _, detail_content_layout = _create_scrollable_dialog_content(
            splitter
        )
        self.detail_scroll_area.setObjectName("releaseBrowserDetailScrollArea")
        detail_content_layout.setSpacing(10)

        self.detail_tabs = QTabWidget(self.detail_scroll_area)
        self.detail_tabs.setMinimumHeight(420)
        detail_content_layout.addWidget(self.detail_tabs, 1)

        overview_tab = QWidget(self.detail_tabs)
        overview_tab.setProperty("role", "workspaceCanvas")
        self.overview_tab = overview_tab
        overview_tab_layout = QVBoxLayout(overview_tab)
        overview_tab_layout.setContentsMargins(0, 8, 0, 0)
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
        self.detail_tabs.addTab(overview_tab, "Overview")

        tracks_tab = QWidget(self.detail_tabs)
        tracks_tab.setProperty("role", "workspaceCanvas")
        self.tracks_tab = tracks_tab
        tracks_tab_layout = QVBoxLayout(tracks_tab)
        tracks_tab_layout.setContentsMargins(0, 8, 0, 0)
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
        self.detail_tabs.addTab(tracks_tab, "Tracks")

        actions_box, actions_layout = _create_standard_section(
            self,
            "Release Actions",
            "Edit or duplicate the release, attach the current selection, filter the main table, or open the highlighted track.",
        )
        edit_button = QPushButton("Edit Release")
        edit_button.clicked.connect(self._emit_edit_current)
        duplicate_button = QPushButton("Duplicate Release")
        duplicate_button.clicked.connect(self._emit_duplicate_current)
        add_selection_button = QPushButton("Add Selected Tracks")
        add_selection_button.clicked.connect(self._emit_add_selected_current)
        filter_button = QPushButton("Filter Catalog To Release")
        filter_button.clicked.connect(self._emit_filter_current)
        open_track_button = QPushButton("Open Selected Track")
        open_track_button.clicked.connect(self._emit_open_track_current)
        self.actions_cluster = _create_action_button_cluster(
            actions_box,
            [
                edit_button,
                duplicate_button,
                add_selection_button,
                filter_button,
                open_track_button,
            ],
            columns=2,
            min_button_width=180,
            span_last_row=True,
        )
        self.actions_cluster.setObjectName("releaseBrowserActionsCluster")
        actions_layout.addWidget(self.actions_cluster)
        detail_content_layout.addWidget(actions_box)
        detail_content_layout.addStretch(1)

        splitter.addWidget(self.detail_scroll_area)
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
        self.refresh_selection_scope()

    def _release_service(self) -> ReleaseService | None:
        service = self.release_service_provider()
        return service

    def refresh(self) -> None:
        selected_release_id = self._selected_release_id()
        service = self._release_service()
        if service is None:
            self._release_ids_by_row = []
            self.release_table.setRowCount(0)
            self.track_table.setRowCount(0)
            self.release_count_label.setText("Open a profile first to browse releases.")
            for label in self._summary_fields.values():
                label.setText("")
            self.refresh_selection_scope()
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
        restored = self._restore_release_selection(selected_release_id)
        if releases:
            if not restored:
                self.release_table.selectRow(0)
        else:
            for label in self._summary_fields.values():
                label.setText("")
            self.track_table.setRowCount(0)
        self.refresh_selection_scope()

    def _selected_release_id(self) -> int | None:
        row = self.release_table.currentRow()
        if row < 0 or row >= len(self._release_ids_by_row):
            return None
        return int(self._release_ids_by_row[row])

    def _restore_release_selection(self, release_id: int | None) -> bool:
        if not release_id:
            return False
        for row, current_release_id in enumerate(self._release_ids_by_row):
            if int(current_release_id) != int(release_id):
                continue
            self.release_table.selectRow(row)
            return True
        return False

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
            title="Choose Release Scope Tracks",
            parent=self,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        self._selection_override_track_ids = dialog.selected_track_ids()
        self.refresh_selection_scope()

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
            self.add_selected_tracks_requested.emit(release_id, self.selected_track_ids())

    def _emit_create_release_current(self) -> None:
        self.create_release_requested.emit(self.selected_track_ids())

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
    add_selected_tracks_requested = Signal(int, list)
    create_release_requested = Signal(list)

    def __init__(
        self,
        *,
        release_service: ReleaseService,
        track_title_resolver,
        selected_track_ids_provider=None,
        track_choice_provider=None,
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
            selected_track_ids_provider=selected_track_ids_provider,
            track_choice_provider=track_choice_provider,
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

"""Album entry dialog and track-entry section."""

from __future__ import annotations

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QCompleter,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from isrc_manager.code_registry import CatalogIdentifierField
from isrc_manager.domain.codes import (
    is_blank,
    is_valid_isrc_compact_or_iso,
    is_valid_iswc_any,
    to_compact_isrc,
    to_iso_isrc,
    to_iso_iswc,
    valid_upc_ean,
)
from isrc_manager.domain.timecode import hms_to_seconds
from isrc_manager.parties import party_authority_notifier
from isrc_manager.services import TrackCreatePayload
from isrc_manager.services.import_governance import GovernedImportCoordinator
from isrc_manager.tasks.history_helpers import run_snapshot_history_action
from isrc_manager.tracks.host_protocols import AlbumEditorHost
from isrc_manager.ui_common import (
    DatePickerDialog,
    FocusWheelComboBox,
    FocusWheelSpinBox,
    TwoDigitSpinBox,
    _add_standard_dialog_header,
    _apply_standard_dialog_chrome,
    _create_standard_section,
)


class _AlbumTrackSection(QWidget):
    """Reusable track-entry section for the Add Album dialog."""

    def __init__(self, dialog: "AlbumEntryDialog", number: int):
        super().__init__(dialog)
        self.dialog = dialog
        self.app: AlbumEditorHost = dialog.app
        self._display_title = ""
        self._track_number_dirty = False
        self._setting_track_number_default = False
        self.setObjectName("albumTrackSection")
        self.setProperty("role", "tabPaneCanvas")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 8, 6, 10)
        root.setSpacing(12)

        self.track_note = QLabel(
            "Track-specific governance, metadata, timing, codes, and managed audio."
        )
        self.track_note.setProperty("role", "secondary")
        self.track_note.setWordWrap(True)
        root.addWidget(self.track_note)

        self.section_tabs = QTabWidget(self)
        self.section_tabs.setObjectName("albumTrackSectionTabs")
        self.section_tabs.setDocumentMode(True)
        self.section_tabs.setUsesScrollButtons(False)
        root.addWidget(self.section_tabs, 1)

        def create_tab(
            tab_title: str, section_title: str, description: str | None = None
        ) -> QVBoxLayout:
            page = QWidget(self.section_tabs)
            page.setProperty("role", "tabPaneCanvas")
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(0, 0, 0, 0)
            page_layout.setSpacing(10)

            if description:
                intro = QLabel(description, page)
                intro.setWordWrap(True)
                intro.setProperty("role", "secondary")
                page_layout.addWidget(intro)

            box, box_layout = _create_standard_section(page, section_title)
            box_layout.setContentsMargins(14, 18, 14, 14)
            box_layout.setSpacing(10)
            page_layout.addWidget(box)
            page_layout.addStretch(1)
            self.section_tabs.addTab(page, tab_title)
            return box_layout

        governance_layout = create_tab(
            "Governance",
            "Work Governance",
            "Resolve this row to either an existing Work or a new Work created from this track before save.",
        )
        details_layout = create_tab(
            "Details",
            "Track Details",
            "Capture the track-facing metadata and timing for this album row.",
        )
        codes_layout = create_tab(
            "Codes",
            "Track Codes",
            "Keep registration identifiers and export-facing codes together.",
        )
        media_layout = create_tab(
            "Media",
            "Managed Audio",
            "Attach the source audio file used when saving these album tracks.",
        )

        self.governance_summary = QLabel("")
        self.governance_summary.setWordWrap(True)
        self.governance_summary.setProperty("role", "sectionTitle")
        governance_layout.addWidget(self.governance_summary)

        self.governance_hint = QLabel("")
        self.governance_hint.setWordWrap(True)
        self.governance_hint.setProperty("role", "secondary")
        governance_layout.addWidget(self.governance_hint)

        self.governance_mode = FocusWheelComboBox()
        self.governance_mode.setEditable(False)
        self.dialog._apply_input_height(self.governance_mode)
        self.governance_mode.addItem("Create New Work from This Track", "create_new_work")
        self.governance_mode.addItem("Link to Existing Work", "link_existing_work")
        self.governance_mode.currentIndexChanged.connect(self._refresh_governance_state)
        self._add_labeled_widget(governance_layout, "Governance", self.governance_mode)

        self.parent_work = FocusWheelComboBox()
        self.parent_work.setEditable(False)
        self.dialog._apply_input_height(self.parent_work)
        self.parent_work.currentIndexChanged.connect(self._refresh_governance_state)
        self._add_labeled_widget(governance_layout, "Work", self.parent_work)

        self.relationship_type = FocusWheelComboBox()
        self.relationship_type.setEditable(False)
        self.dialog._apply_input_height(self.relationship_type)
        for value in self.app._work_track_relationship_choices():
            self.relationship_type.addItem(
                self.app._work_track_relationship_label(value),
                value,
            )
        self.relationship_type.currentIndexChanged.connect(self._refresh_governance_state)
        self._add_labeled_widget(governance_layout, "Child Relationship", self.relationship_type)

        self.parent_track = FocusWheelComboBox()
        self.parent_track.setEditable(False)
        self.dialog._apply_input_height(self.parent_track)
        self.parent_track.currentIndexChanged.connect(self._refresh_governance_state)
        self._add_labeled_widget(governance_layout, "Parent Track", self.parent_track)

        self.track_title = QLineEdit()
        self.track_title.setPlaceholderText("Track title")
        self.dialog._apply_input_height(self.track_title)
        self._add_labeled_widget(details_layout, "Track Title", self.track_title)

        self.artist_name = self.dialog._build_artist_combo(allow_empty=True)
        self.artist_name.setCurrentText("")
        self._add_labeled_widget(details_layout, "Main Artist", self.artist_name)

        self.additional_artists = self.dialog._build_artist_combo(allow_empty=True)
        self.additional_artists.setCurrentText("")
        self._add_labeled_widget(details_layout, "Additional Artists", self.additional_artists)

        self.track_number_field = FocusWheelSpinBox()
        self.track_number_field.setRange(1, 9999)
        self.track_number_field.valueChanged.connect(self._handle_track_number_changed)
        self.dialog._apply_input_height(self.track_number_field)
        self._add_labeled_widget(details_layout, "Track Number", self.track_number_field)

        self.release_date = QLineEdit()
        self.release_date.setReadOnly(True)
        self.release_date.setPlaceholderText("No release date selected")
        self.dialog._apply_input_height(self.release_date)
        release_row = QWidget(self)
        release_layout = QHBoxLayout(release_row)
        release_layout.setContentsMargins(0, 0, 0, 0)
        release_layout.setSpacing(8)
        release_layout.addWidget(self.release_date, 1)
        self.release_date_pick_button = QPushButton("Pick…")
        self.release_date_pick_button.setAutoDefault(False)
        self.dialog._apply_button_height(self.release_date_pick_button)
        self.release_date_pick_button.clicked.connect(self._pick_release_date)
        self.release_date_today_button = QPushButton("Today")
        self.release_date_today_button.setAutoDefault(False)
        self.dialog._apply_button_height(self.release_date_today_button)
        self.release_date_today_button.clicked.connect(
            lambda: self.set_release_date_iso(QDate.currentDate().toString("yyyy-MM-dd"))
        )
        self.release_date_clear_button = QPushButton("Clear")
        self.release_date_clear_button.setAutoDefault(False)
        self.dialog._apply_button_height(self.release_date_clear_button)
        self.release_date_clear_button.clicked.connect(lambda: self.set_release_date_iso(None))
        release_layout.addWidget(self.release_date_pick_button)
        release_layout.addWidget(self.release_date_today_button)
        release_layout.addWidget(self.release_date_clear_button)
        self._add_labeled_widget(details_layout, "Release Date", release_row)

        self.len_h = TwoDigitSpinBox()
        self.len_h.setRange(0, 99)
        self.len_h.setFixedWidth(60)
        self.len_m = TwoDigitSpinBox()
        self.len_m.setRange(0, 59)
        self.len_m.setFixedWidth(50)
        self.len_s = TwoDigitSpinBox()
        self.len_s.setRange(0, 59)
        self.len_s.setFixedWidth(50)
        length_group = QFrame(self)
        length_group.setProperty("role", "compactControlGroup")
        length_group.setAttribute(Qt.WA_StyledBackground, True)
        length_group.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        length_layout = QHBoxLayout(length_group)
        length_layout.setContentsMargins(10, 8, 10, 8)
        length_layout.setSpacing(6)
        length_layout.addWidget(self.len_h)
        length_layout.addWidget(QLabel(":"))
        length_layout.addWidget(self.len_m)
        length_layout.addWidget(QLabel(":"))
        length_layout.addWidget(self.len_s)
        self._add_labeled_widget(details_layout, "Track Length (hh:mm:ss)", length_group)

        self.isrc = QLineEdit()
        if self.dialog.auto_isrc_enabled:
            self.isrc.setPlaceholderText("Leave blank to auto-generate on save")
        else:
            self.isrc.setPlaceholderText("Leave blank if this track has no ISRC yet")
        self.dialog._apply_input_height(self.isrc)
        self._add_labeled_widget(codes_layout, "ISRC", self.isrc)

        isrc_note = QLabel(self.dialog.isrc_help_text)
        isrc_note.setProperty("role", "secondary")
        isrc_note.setWordWrap(True)
        codes_layout.addWidget(isrc_note)

        self.iswc = QLineEdit()
        self.iswc.setPlaceholderText("Optional ISWC")
        self.dialog._apply_input_height(self.iswc)
        self._add_labeled_widget(codes_layout, "ISWC", self.iswc)

        self.buma_work_number = QLineEdit()
        self.buma_work_number.setPlaceholderText("Optional BUMA work number")
        self.dialog._apply_input_height(self.buma_work_number)
        self._add_labeled_widget(codes_layout, "BUMA Wnr.", self.buma_work_number)

        self.audio_file = QLineEdit()
        self.audio_file.setReadOnly(True)
        self.audio_file.setPlaceholderText("No audio file selected")
        self.dialog._apply_input_height(self.audio_file)
        audio_row = QWidget(self)
        audio_layout = QHBoxLayout(audio_row)
        audio_layout.setContentsMargins(0, 0, 0, 0)
        audio_layout.setSpacing(8)
        audio_layout.addWidget(self.audio_file, 1)
        self.audio_browse_button = QPushButton("Browse…")
        self.audio_browse_button.setAutoDefault(False)
        self.dialog._apply_button_height(self.audio_browse_button)
        self.audio_browse_button.clicked.connect(
            lambda: self.app._choose_media_into_line_edit(
                "audio_file",
                self.audio_file,
                parent_widget=self.dialog,
                hours_widget=self.len_h,
                minutes_widget=self.len_m,
                seconds_widget=self.len_s,
            )
        )
        self.audio_clear_button = QPushButton("Clear")
        self.audio_clear_button.setAutoDefault(False)
        self.dialog._apply_button_height(self.audio_clear_button)
        self.audio_clear_button.clicked.connect(self.audio_file.clear)
        audio_layout.addWidget(self.audio_browse_button)
        audio_layout.addWidget(self.audio_clear_button)
        audio_container = QWidget(self)
        audio_container_layout = QVBoxLayout(audio_container)
        audio_container_layout.setContentsMargins(0, 0, 0, 0)
        audio_container_layout.setSpacing(6)
        audio_container_layout.addWidget(audio_row)
        self.audio_file_warning_label = QLabel("")
        self.audio_file_warning_label.setWordWrap(True)
        self.audio_file_warning_label.setProperty("role", "supportingText")
        self.audio_file_warning_label.setVisible(False)
        audio_container_layout.addWidget(self.audio_file_warning_label)
        self.audio_file._lossy_audio_warning_label = self.audio_file_warning_label
        self.audio_file.textChanged.connect(
            lambda _text: self.app._refresh_line_edit_lossy_audio_warning(self.audio_file)
        )
        self.app._refresh_line_edit_lossy_audio_warning(self.audio_file)
        self._add_labeled_widget(media_layout, "Audio File", audio_container)

        root.addStretch(1)
        self.set_track_number(number)
        self.apply_governance_seed(
            work_id=self.dialog._selected_work_id_seed,
            relationship_type=self.dialog._initial_relationship_type,
        )

    @staticmethod
    def _add_labeled_widget(layout: QVBoxLayout, label_text: str, widget: QWidget) -> None:
        row = QVBoxLayout()
        row.setContentsMargins(0, 0, 0, 4)
        row.setSpacing(6)
        label = QLabel(label_text)
        row.addWidget(label)
        row.addWidget(widget)
        layout.addLayout(row)

    def set_track_number(self, number: int) -> None:
        self._display_title = f"Track {int(number):02d}"
        if not self._track_number_dirty:
            previous_state = self.track_number_field.blockSignals(True)
            self._setting_track_number_default = True
            try:
                self.track_number_field.setValue(max(1, int(number)))
            finally:
                self._setting_track_number_default = False
                self.track_number_field.blockSignals(previous_state)

    def title(self) -> str:
        return self._display_title

    def track_number_value(self) -> int:
        return max(1, int(self.track_number_field.value() or 1))

    def set_release_date_iso(self, iso_date: str | None) -> None:
        clean_value = str(iso_date or "").strip()
        self.release_date.setText(clean_value)

    def release_date_iso(self) -> str | None:
        clean_value = (self.release_date.text() or "").strip()
        return clean_value or None

    def track_length_seconds(self) -> int:
        return hms_to_seconds(self.len_h.value(), self.len_m.value(), self.len_s.value())

    def _selected_governance_mode(self) -> str:
        return str(self.governance_mode.currentData() or "create_new_work")

    def selected_work_id(self) -> int | None:
        value = self.parent_work.currentData()
        try:
            return int(value) if value not in (None, "") else None
        except (TypeError, ValueError):
            return None

    def selected_relationship_type(self) -> str:
        return self.app._normalize_work_track_relationship(self.relationship_type.currentData())

    def selected_parent_track_id(self) -> int | None:
        value = self.parent_track.currentData()
        try:
            return int(value) if value not in (None, "") else None
        except (TypeError, ValueError):
            return None

    def selected_governance_mode(self) -> str:
        return self._selected_governance_mode()

    def apply_governance_seed(
        self,
        *,
        work_id: int | None,
        relationship_type: str | None,
    ) -> None:
        previous_mode_state = self.governance_mode.blockSignals(True)
        previous_relationship_state = self.relationship_type.blockSignals(True)
        try:
            mode = "link_existing_work" if work_id is not None else "create_new_work"
            mode_index = self.governance_mode.findData(mode)
            self.governance_mode.setCurrentIndex(mode_index if mode_index >= 0 else 0)
            relationship_index = self.relationship_type.findData(
                self.app._normalize_work_track_relationship(relationship_type)
            )
            self.relationship_type.setCurrentIndex(
                relationship_index if relationship_index >= 0 else 0
            )
        finally:
            self.governance_mode.blockSignals(previous_mode_state)
            self.relationship_type.blockSignals(previous_relationship_state)
        self._populate_parent_work_combo(selected_work_id=work_id)
        self._refresh_governance_state()

    def _populate_parent_work_combo(self, *, selected_work_id: int | None) -> None:
        previous_state = self.parent_work.blockSignals(True)
        try:
            self.parent_work.clear()
            self.parent_work.addItem("Choose the governing Work…", None)
            for record in self.dialog._available_work_records():
                try:
                    work_id = int(getattr(record, "id", 0) or 0)
                except (TypeError, ValueError):
                    continue
                if work_id <= 0:
                    continue
                self.parent_work.addItem(self.dialog._work_choice_label(record), work_id)
            if (
                selected_work_id is not None
                and self.parent_work.findData(int(selected_work_id)) < 0
            ):
                self.parent_work.addItem(
                    f"Missing Work #{int(selected_work_id)}", int(selected_work_id)
                )
            selected_index = (
                self.parent_work.findData(int(selected_work_id))
                if selected_work_id is not None
                else 0
            )
            self.parent_work.setCurrentIndex(selected_index if selected_index >= 0 else 0)
        finally:
            self.parent_work.blockSignals(previous_state)

    def _refresh_governance_state(self) -> None:
        mode = self._selected_governance_mode()
        work_id = self.selected_work_id()
        detail = (
            self.app.work_service.fetch_work_detail(int(work_id))
            if work_id is not None and self.app.work_service is not None
            else None
        )

        track_choices: list[tuple[int, str]] = []
        if detail is not None:
            for track_id in detail.track_ids:
                title = str(self.app._get_track_title(int(track_id)) or "").strip()
                track_choices.append((int(track_id), title or f"Track #{int(track_id)}"))

        previous_parent_state = self.parent_track.blockSignals(True)
        try:
            current_parent_track_id = self.selected_parent_track_id()
            self.parent_track.clear()
            self.parent_track.addItem("No direct parent track", None)
            for track_id, title in track_choices:
                self.parent_track.addItem(title, int(track_id))
            parent_index = (
                self.parent_track.findData(int(current_parent_track_id))
                if current_parent_track_id is not None
                else 0
            )
            self.parent_track.setCurrentIndex(parent_index if parent_index >= 0 else 0)
        finally:
            self.parent_track.blockSignals(previous_parent_state)

        if mode == "create_new_work":
            self.parent_work.setEnabled(False)
            self.relationship_type.setEnabled(False)
            self.parent_track.setEnabled(False)
            self.governance_summary.setText(
                "This row will create a new Work from the track title, ISWC, and registration number, then save the track as that Work's first governed original."
            )
            self.governance_hint.setText(
                "Artist names resolve through Party records on save so this row can seed authoritative identity without making you enter shared data twice."
            )
            return

        self.parent_work.setEnabled(True)
        self.relationship_type.setEnabled(detail is not None)
        self.parent_track.setEnabled(bool(track_choices))
        if detail is None:
            self.governance_summary.setText(
                "Choose the existing Work that should govern this row before saving the album batch."
            )
            self.governance_hint.setText(
                "Use the child relationship and optional parent track when this row is a version, remix, alternate master, edit, live take, or other derivative under that Work."
            )
            return

        relationship_label = self.app._work_track_relationship_label(
            self.selected_relationship_type()
        )
        work_title = str(detail.work.title or "").strip() or f"Work #{int(detail.work.id)}"
        self.governance_summary.setText(
            f"This row will link to Work #{int(detail.work.id)}: {work_title} as {relationship_label}."
        )
        if track_choices:
            self.governance_hint.setText(
                f"{len(track_choices)} governed track{'s' if len(track_choices) != 1 else ''} already sit under this Work. "
                "Choose a parent track when this row derives from one of them."
            )
        else:
            self.governance_hint.setText(
                "This Work does not have any linked tracks yet. Saving this row will create the first governed track under it."
            )

    def is_effectively_blank(self) -> bool:
        return all(
            (
                not (self.track_title.text() or "").strip(),
                not self.artist_name.currentText().strip(),
                not self.additional_artists.currentText().strip(),
                not self.release_date_iso(),
                self.track_length_seconds() == 0,
                not (self.isrc.text() or "").strip(),
                not (self.iswc.text() or "").strip(),
                not (self.buma_work_number.text() or "").strip(),
                not (self.audio_file.text() or "").strip(),
            )
        )

    def _pick_release_date(self) -> None:
        dlg = DatePickerDialog(
            self.dialog,
            initial_iso_date=self.release_date_iso(),
            title=f"Pick Release Date for {self.title()}",
        )
        if dlg.exec() == QDialog.Accepted:
            self.set_release_date_iso(dlg.selected_iso())

    def _handle_track_number_changed(self, _value: int) -> None:
        if self._setting_track_number_default:
            return
        self._track_number_dirty = True


class AlbumEntryDialog(QDialog):
    """Creates multiple tracks for a shared album from one structured dialog."""

    EXTRA_QSS = """
    QDialog#albumEntryDialog QCheckBox {
        spacing: 6px;
    }
    QDialog#albumEntryDialog QTabWidget#albumEntryPrimaryTabs::pane,
    QDialog#albumEntryDialog QTabWidget#albumEntryTrackTabs::pane {
        margin-top: 8px;
    }
    QDialog#albumEntryDialog QTabBar::tab {
        min-width: 104px;
        padding: 7px 14px;
    }
    QDialog#albumEntryDialog QTabBar::tab:selected {
        font-weight: 600;
    }
    QDialog#albumEntryDialog QScrollArea {
        background: transparent;
    }
    """

    @staticmethod
    def _create_tab_page(owner: QWidget) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget(owner)
        page.setProperty("role", "workspaceCanvas")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(14)
        return page, layout

    @staticmethod
    def _scaled_control_height(widget: QWidget, *, extra_padding: int) -> int:
        hint_height = 0
        try:
            hint_height = int(widget.sizeHint().height())
        except Exception:
            hint_height = 0
        try:
            font_height = int(widget.fontMetrics().height())
        except Exception:
            font_height = 0
        return max(hint_height, font_height + extra_padding)

    def _apply_input_height(self, widget: QWidget) -> None:
        widget.setMinimumHeight(self._scaled_control_height(widget, extra_padding=6))

    def _apply_button_height(self, widget: QWidget) -> None:
        widget.setMinimumHeight(self._scaled_control_height(widget, extra_padding=8))

    @staticmethod
    def _work_choice_label(record) -> str:
        title = str(getattr(record, "title", "") or "").strip()
        work_id = int(getattr(record, "id", 0) or 0)
        iswc = str(getattr(record, "iswc", "") or "").strip()
        base = title or (f"Work #{work_id}" if work_id > 0 else "Untitled Work")
        return f"{base} ({iswc})" if iswc else base

    def _available_work_records(self) -> list:
        if self.app.work_service is None:
            return []
        try:
            return list(self.app.work_service.list_works())
        except Exception:
            return []

    def __init__(
        self,
        app: AlbumEditorHost,
        *,
        work_id: int | None = None,
        lock_work: bool = False,
        relationship_type: str | None = None,
    ):
        super().__init__(app)
        self.app: AlbumEditorHost = app
        self.created_track_ids: list[int] = []
        self._track_sections: list[_AlbumTrackSection] = []
        self._track_pages: dict[_AlbumTrackSection, QWidget] = {}
        self._selected_work_id_seed = int(work_id) if work_id is not None else None
        self._lock_work = bool(lock_work and self._selected_work_id_seed is not None)
        self._initial_relationship_type = self.app._normalize_work_track_relationship(
            relationship_type
        )

        state, state_message = self.app._isrc_generation_state()
        self.auto_isrc_enabled = state == "ready"
        self.isrc_help_text = (
            "Leave ISRC blank to auto-generate it on save using the current prefix, artist code, and track release-year rule."
            if self.auto_isrc_enabled
            else state_message
        )

        self.setWindowTitle("Add Album")
        self.setModal(True)
        self.resize(960, 960)
        self.setMinimumSize(820, 760)
        _apply_standard_dialog_chrome(self, "albumEntryDialog", extra_qss=self.EXTRA_QSS)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(18, 18, 18, 18)
        main_layout.setSpacing(14)
        _add_standard_dialog_header(
            main_layout,
            self,
            title=self.windowTitle(),
            subtitle=(
                "Capture shared album metadata once, then use the Tracks tab to work through one tab per track. "
                "Each populated row must resolve its own Work governance before save."
                + (
                    " Rows currently start seeded from the selected Work."
                    if self._selected_work_id_seed is not None
                    else ""
                )
            ),
            help_topic_id="album-entry",
        )

        self.primary_tabs = QTabWidget(self)
        self.primary_tabs.setObjectName("albumEntryPrimaryTabs")
        self.primary_tabs.setDocumentMode(False)
        self.primary_tabs.setUsesScrollButtons(False)
        main_layout.addWidget(self.primary_tabs, 1)

        self.album_details_tab, album_details_layout = self._create_tab_page(self.primary_tabs)
        self.track_workspace_tab, track_workspace_layout = self._create_tab_page(self.primary_tabs)
        self.primary_tabs.addTab(self.album_details_tab, "Album Details")
        self.primary_tabs.addTab(self.track_workspace_tab, "Tracks")

        work_context_box, work_context_layout = _create_standard_section(
            self.album_details_tab,
            "Governance Rules",
            "Add Album is batch Add Track: each populated row must either link to an existing Work or create a new Work from that row before save.",
        )
        self.work_context_summary = QLabel(
            "Every saved album row must end in one of two explicit outcomes: link that row to an existing Work, or create a new Work from that row and save the track as its first governed original."
        )
        self.work_context_summary.setWordWrap(True)
        self.work_context_summary.setProperty("role", "sectionTitle")
        work_context_layout.addWidget(self.work_context_summary)
        self.work_context_hint = QLabel(
            "Open the Governance tab inside each track row to make that choice. If this dialog opened from Work Manager, each row starts preselected to that Work, but you can still change any row before save."
        )
        self.work_context_hint.setWordWrap(True)
        self.work_context_hint.setProperty("role", "secondary")
        work_context_layout.addWidget(self.work_context_hint)
        album_details_layout.addWidget(work_context_box)

        summary_box, summary_layout = _create_standard_section(
            self.album_details_tab,
            "Workflow Notes",
            "Album-level values apply to every saved track in this dialog, while each track section keeps its own metadata and audio file.",
        )
        summary_label = QLabel(
            "Album Title, UPC/EAN, Genre, Catalog#, and Album Art are shared across the new album tracks. "
            + self.isrc_help_text
            + " Each populated track row still resolves its own Work governance before save so the batch never creates orphan tracks."
        )
        summary_label.setWordWrap(True)
        summary_label.setProperty("role", "supportingText")
        summary_layout.addWidget(summary_label)
        album_details_layout.addWidget(summary_box)

        overview_box, overview_layout = _create_standard_section(
            self.album_details_tab, "Album Overview"
        )
        overview_layout.setSpacing(10)
        self.album_title = self._build_album_combo()
        self._add_labeled_widget(overview_layout, "Album Title", self.album_title)

        self.upc = self._build_upc_combo()
        self._add_labeled_widget(overview_layout, "UPC / EAN", self.upc)

        self.genre = self._build_genre_combo()
        self._add_labeled_widget(overview_layout, "Genre", self.genre)

        self.catalog_number = CatalogIdentifierField(
            service_provider=lambda: getattr(self.app, "code_registry_service", None),
            created_via="album_entry",
            parent=self,
        )
        self.catalog_number.setCurrentText("")
        self._add_labeled_widget(overview_layout, "Catalog#", self.catalog_number)

        self.album_art = QLineEdit()
        self.album_art.setReadOnly(True)
        self.album_art.setPlaceholderText("No album art selected")
        self._apply_input_height(self.album_art)
        art_row = QWidget(self)
        art_layout = QHBoxLayout(art_row)
        art_layout.setContentsMargins(0, 0, 0, 0)
        art_layout.setSpacing(8)
        art_layout.addWidget(self.album_art, 1)
        self.album_art_browse_button = QPushButton("Browse…")
        self.album_art_browse_button.setAutoDefault(False)
        self._apply_button_height(self.album_art_browse_button)
        self.album_art_browse_button.clicked.connect(
            lambda: self.app._choose_media_into_line_edit(
                "album_art", self.album_art, parent_widget=self
            )
        )
        self.album_art_clear_button = QPushButton("Clear")
        self.album_art_clear_button.setAutoDefault(False)
        self._apply_button_height(self.album_art_clear_button)
        self.album_art_clear_button.clicked.connect(self.album_art.clear)
        art_layout.addWidget(self.album_art_browse_button)
        art_layout.addWidget(self.album_art_clear_button)
        self._add_labeled_widget(overview_layout, "Album Art", art_row)

        self.use_release_year = QCheckBox(
            "Use each track release year when auto-generating blank ISRC values"
        )
        self.use_release_year.setChecked(False)
        self.use_release_year.setEnabled(self.auto_isrc_enabled)
        self.use_release_year.setToolTip(self.isrc_help_text)
        self.use_release_year.setContentsMargins(0, 4, 0, 0)
        overview_layout.addWidget(self.use_release_year)
        overview_layout.addStretch(1)
        album_details_layout.addWidget(overview_box)
        album_details_layout.addStretch(1)

        tracks_box, tracks_box_layout = _create_standard_section(
            self.track_workspace_tab,
            "Tracks",
            "Start with two track tabs, add more whenever needed, and remove the current tab when you no longer need it.",
        )
        controls_row = QHBoxLayout()
        controls_row.setContentsMargins(0, 0, 0, 0)
        controls_row.setSpacing(8)
        self.track_count_label = QLabel()
        self.track_count_label.setProperty("role", "meta")
        controls_row.addWidget(self.track_count_label)
        controls_row.addStretch(1)
        self.add_track_button = QPushButton("Add Track")
        self.add_track_button.setAutoDefault(False)
        self._apply_button_height(self.add_track_button)
        self.add_track_button.clicked.connect(self.add_track_section)
        controls_row.addWidget(self.add_track_button)
        self.remove_track_button = QPushButton("Remove Current Track")
        self.remove_track_button.setAutoDefault(False)
        self._apply_button_height(self.remove_track_button)
        self.remove_track_button.clicked.connect(self.remove_current_track_section)
        controls_row.addWidget(self.remove_track_button)
        tracks_box_layout.addLayout(controls_row)
        tracks_box_layout.addSpacing(6)

        self.track_tabs = QTabWidget(self.track_workspace_tab)
        self.track_tabs.setObjectName("albumEntryTrackTabs")
        self.track_tabs.setDocumentMode(False)
        self.track_tabs.setUsesScrollButtons(True)
        self.track_tabs.setElideMode(Qt.ElideRight)
        tracks_box_layout.addWidget(self.track_tabs, 1)
        track_workspace_layout.addWidget(tracks_box, 1)

        for _ in range(2):
            self.add_track_section()

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(8)
        buttons.addStretch(1)
        self.save_button = QPushButton("Save Album Batch")
        self.save_button.setDefault(True)
        self._apply_button_height(self.save_button)
        self.save_button.clicked.connect(self.save_album)
        self.cancel_button = QPushButton("Cancel")
        self._apply_button_height(self.cancel_button)
        self.cancel_button.clicked.connect(self.reject)
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.cancel_button)
        main_layout.addLayout(buttons)
        party_authority_notifier().changed.connect(self._refresh_artist_party_combos)

    def _combo_from_query(self, query: str, *, allow_empty: bool = True) -> FocusWheelComboBox:
        combo = FocusWheelComboBox()
        combo.setEditable(True)
        values = [
            str(row[0] or "").strip()
            for row in self.app.cursor.execute(query).fetchall()
            if str(row[0] or "").strip()
        ]
        if allow_empty:
            combo.addItem("")
        combo.addItems(values)
        completer = QCompleter(values)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        combo.setCompleter(completer)
        self._apply_input_height(combo)
        return combo

    def _build_artist_combo(self, *, allow_empty: bool) -> FocusWheelComboBox:
        combo = FocusWheelComboBox()
        self.app._configure_artist_party_combo(combo, allow_empty=allow_empty)
        self._apply_input_height(combo)
        return combo

    def _refresh_artist_party_combos(self) -> None:
        for section in self._track_sections:
            for combo, allow_empty in (
                (getattr(section, "artist_name", None), True),
                (getattr(section, "additional_artists", None), True),
            ):
                if not isinstance(combo, QComboBox):
                    continue
                current_text, selected_party_id = self.app._resolve_artist_party_choice(combo)
                self.app._configure_artist_party_combo(
                    combo,
                    allow_empty=allow_empty,
                    selected_party_id=selected_party_id,
                    current_text=current_text,
                )

    def _build_album_combo(self) -> FocusWheelComboBox:
        return self._combo_from_query(
            "SELECT DISTINCT title FROM Albums WHERE title IS NOT NULL AND title != '' ORDER BY title",
            allow_empty=True,
        )

    def _build_upc_combo(self) -> FocusWheelComboBox:
        return self._combo_from_query(
            """
            SELECT value
            FROM (
                SELECT upc AS value FROM Tracks WHERE upc IS NOT NULL AND upc != ''
                UNION
                SELECT upc AS value FROM Releases WHERE upc IS NOT NULL AND upc != ''
            )
            ORDER BY value
            """,
            allow_empty=True,
        )

    def _build_genre_combo(self) -> FocusWheelComboBox:
        return self._combo_from_query(
            "SELECT DISTINCT genre FROM Tracks WHERE genre IS NOT NULL AND genre != '' ORDER BY genre",
            allow_empty=True,
        )

    def _build_catalog_number_combo(self) -> FocusWheelComboBox:
        return self._combo_from_query(
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
            """,
            allow_empty=True,
        )

    @staticmethod
    def _add_labeled_widget(layout: QVBoxLayout, label_text: str, widget: QWidget) -> None:
        row = QVBoxLayout()
        row.setContentsMargins(0, 0, 0, 2)
        row.setSpacing(4)
        label = QLabel(label_text)
        row.addWidget(label)
        row.addWidget(widget)
        layout.addLayout(row)

    def _refresh_track_section_titles(self) -> None:
        for index, section in enumerate(self._track_sections, start=1):
            section.set_track_number(index)
            page = self._track_pages.get(section)
            tab_index = self.track_tabs.indexOf(page) if page is not None else -1
            if tab_index >= 0:
                tab_title = section.title()
                self.track_tabs.setTabText(tab_index, tab_title)
                self.track_tabs.setTabToolTip(tab_index, tab_title)
        track_count = len(self._track_sections)
        self.track_count_label.setText(
            f"{track_count} track tab{'s' if track_count != 1 else ''} available"
        )
        self.remove_track_button.setEnabled(track_count > 1)

    def add_track_section(self) -> None:
        section = _AlbumTrackSection(self, len(self._track_sections) + 1)
        self._track_sections.append(section)
        page = QWidget(self.track_tabs)
        page.setProperty("role", "workspaceCanvas")
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 6, 0, 0)
        page_layout.setSpacing(0)
        scroll = QScrollArea(page)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setProperty("role", "workspaceCanvas")
        viewport = scroll.viewport()
        if viewport is not None:
            viewport.setProperty("role", "workspaceCanvas")
        scroll.setWidget(section)
        page_layout.addWidget(scroll)
        self._track_pages[section] = page
        self.track_tabs.addTab(page, "")
        self._refresh_track_section_titles()
        self.track_tabs.setCurrentWidget(page)
        self.primary_tabs.setCurrentWidget(self.track_workspace_tab)

    def _focus_track_section(self, section: _AlbumTrackSection) -> None:
        page = self._track_pages.get(section)
        if page is None:
            return
        self.primary_tabs.setCurrentWidget(self.track_workspace_tab)
        self.track_tabs.setCurrentWidget(page)

    def remove_current_track_section(self) -> None:
        current_page = self.track_tabs.currentWidget()
        if current_page is None:
            return
        for section, page in list(self._track_pages.items()):
            if page is current_page:
                self.remove_track_section(section)
                break

    def remove_track_section(self, section: _AlbumTrackSection) -> None:
        if section not in self._track_sections or len(self._track_sections) <= 1:
            return
        page = self._track_pages.pop(section, None)
        current_index = self.track_tabs.indexOf(page) if page is not None else -1
        self._track_sections.remove(section)
        if current_index >= 0:
            self.track_tabs.removeTab(current_index)
        section.setParent(None)
        section.deleteLater()
        if page is not None:
            page.deleteLater()
        self._refresh_track_section_titles()
        if self.track_tabs.count() > 0:
            self.track_tabs.setCurrentIndex(max(0, min(current_index, self.track_tabs.count() - 1)))

    def _build_track_payloads(self) -> list[TrackCreatePayload] | None:
        album_title = self.album_title.currentText().strip()
        if is_blank(album_title):
            self.primary_tabs.setCurrentWidget(self.album_details_tab)
            QMessageBox.warning(
                self,
                "Missing Album Title",
                "Album Title is required when using Album Batch Entry.",
            )
            return None

        upc_raw = self.upc.currentText().strip()
        if upc_raw and not valid_upc_ean(upc_raw):
            self.primary_tabs.setCurrentWidget(self.album_details_tab)
            QMessageBox.warning(
                self, "Invalid UPC/EAN", "UPC/EAN must be 12 or 13 digits (or leave empty)."
            )
            return None

        genre = self.genre.currentText().strip() or None
        catalog_number = self.catalog_number.currentText().strip() or None
        album_art_source_path = self.album_art.text().strip() or None
        use_release_year = bool(self.use_release_year.isChecked())
        any_audio_source_path = any(
            (section.audio_file.text() or "").strip() for section in self._track_sections
        )
        if any_audio_source_path and not self.app._confirm_lossy_primary_audio_selection(
            [
                (section.audio_file.text() or "").strip()
                for section in self._track_sections
                if (section.audio_file.text() or "").strip()
            ],
            title="Save Album Media",
            action_label="Saving this album",
        ):
            return None
        media_modes = self.app._choose_track_media_storage_modes(
            audio_source_path="present" if any_audio_source_path else None,
            album_art_source_path=album_art_source_path,
            title="Save Album Media",
        )
        if media_modes is None:
            return None
        default_audio_storage_mode, album_art_storage_mode = media_modes

        active_sections = [
            section for section in self._track_sections if not section.is_effectively_blank()
        ]
        if not active_sections:
            self.primary_tabs.setCurrentWidget(self.track_workspace_tab)
            QMessageBox.warning(
                self, "No Tracks", "Add at least one track before saving the album."
            )
            return None

        payloads: list[TrackCreatePayload] = []
        reserved_compacts: set[str] = set()

        for index, section in enumerate(active_sections, start=1):
            track_title = (section.track_title.text() or "").strip()
            artist_name = section.artist_name.currentText().strip()
            if is_blank(track_title) or is_blank(artist_name):
                self._focus_track_section(section)
                QMessageBox.warning(
                    self,
                    "Missing Track Data",
                    f"{section.title()} needs both a Track Title and a Main Artist.",
                )
                return None
            if (
                section.selected_governance_mode() == "link_existing_work"
                and section.selected_work_id() is None
            ):
                self._focus_track_section(section)
                QMessageBox.warning(
                    self,
                    "Missing Work",
                    f"{section.title()} must choose the existing Work that governs this row, or switch the row back to creating a new Work from the track.",
                )
                return None

            raw_isrc = (section.isrc.text() or "").strip()
            iso_isrc = ""
            compact_isrc = ""
            if raw_isrc:
                iso_isrc = to_iso_isrc(raw_isrc)
                compact_isrc = to_compact_isrc(iso_isrc)
                if not compact_isrc or not is_valid_isrc_compact_or_iso(iso_isrc):
                    self._focus_track_section(section)
                    QMessageBox.warning(
                        self,
                        "Invalid ISRC",
                        f"{section.title()} has an invalid ISRC. Use CC-XXX-YY-NNNNN or leave it blank.",
                    )
                    return None
            elif self.auto_isrc_enabled:
                release_qdate = QDate.fromString(section.release_date_iso() or "", "yyyy-MM-dd")
                iso_isrc = self.app._next_generated_isrc(
                    release_date=release_qdate if release_qdate.isValid() else None,
                    use_release_year=use_release_year,
                    reserved_compacts=reserved_compacts,
                )
                compact_isrc = to_compact_isrc(iso_isrc)
                if not compact_isrc:
                    self._focus_track_section(section)
                    QMessageBox.warning(
                        self,
                        "ISRC Exhausted",
                        f"{section.title()} could not get a new ISRC. No free sequence is available right now.",
                    )
                    return None

            if compact_isrc:
                if compact_isrc in reserved_compacts or self.app.is_isrc_taken_normalized(iso_isrc):
                    self._focus_track_section(section)
                    QMessageBox.warning(
                        self,
                        "Duplicate ISRC",
                        f"{section.title()} uses an ISRC that already exists in the current album batch or profile.",
                    )
                    return None
                reserved_compacts.add(compact_isrc)

            raw_iswc = (section.iswc.text() or "").strip()
            iso_iswc = None
            if raw_iswc:
                iso_iswc = to_iso_iswc(raw_iswc)
                if not iso_iswc or not is_valid_iswc_any(iso_iswc):
                    self._focus_track_section(section)
                    QMessageBox.warning(
                        self,
                        "Invalid ISWC",
                        f"{section.title()} has an invalid ISWC. Use T-123.456.789-0 or leave it blank.",
                    )
                    return None

            selected_artist_name, selected_artist_party_id = self.app._resolve_artist_party_choice(
                section.artist_name
            )
            resolved_artist_name, _artist_party_id = self.app._resolve_party_backed_artist_name(
                selected_artist_name or artist_name,
                selected_party_id=selected_artist_party_id,
                cursor=self.app.cursor,
            )
            resolved_additional_artists = self.app._resolve_party_backed_additional_artist_names(
                self.app._parse_additional_artists(section.additional_artists.currentText()),
                cursor=self.app.cursor,
            )
            section.artist_name.setCurrentText(resolved_artist_name)
            section.additional_artists.setCurrentText(", ".join(resolved_additional_artists))

            selected_work_id = (
                section.selected_work_id()
                if section.selected_governance_mode() == "link_existing_work"
                else None
            )
            relationship_type = (
                section.selected_relationship_type()
                if section.selected_governance_mode() == "link_existing_work"
                else "original"
            )
            parent_track_id = (
                section.selected_parent_track_id()
                if section.selected_governance_mode() == "link_existing_work"
                else None
            )

            payloads.append(
                TrackCreatePayload(
                    isrc=iso_isrc,
                    track_title=track_title,
                    artist_name=resolved_artist_name,
                    additional_artists=resolved_additional_artists,
                    album_title=album_title,
                    release_date=section.release_date_iso(),
                    track_length_sec=section.track_length_seconds(),
                    iswc=(iso_iswc or None),
                    upc=(upc_raw or None),
                    genre=genre,
                    track_number=section.track_number_value(),
                    catalog_number=catalog_number,
                    catalog_number_mode=(
                        self.catalog_number.identifier_mode()
                        if hasattr(self.catalog_number, "identifier_mode")
                        else None
                    ),
                    catalog_registry_entry_id=(
                        self.catalog_number.catalog_registry_entry_id()
                        if hasattr(self.catalog_number, "catalog_registry_entry_id")
                        else None
                    ),
                    catalog_external_code_identifier_id=(
                        self.catalog_number.external_code_identifier_id()
                        if hasattr(self.catalog_number, "external_code_identifier_id")
                        else None
                    ),
                    external_catalog_identifier_id=(
                        self.catalog_number.external_catalog_identifier_id()
                        if hasattr(self.catalog_number, "external_catalog_identifier_id")
                        else None
                    ),
                    buma_work_number=(section.buma_work_number.text().strip() or None),
                    work_id=selected_work_id,
                    parent_track_id=parent_track_id,
                    relationship_type=relationship_type,
                    audio_file_source_path=(section.audio_file.text().strip() or None),
                    audio_file_storage_mode=(
                        default_audio_storage_mode
                        if (section.audio_file.text() or "").strip()
                        else None
                    ),
                    album_art_source_path=album_art_source_path if index == 1 else None,
                    album_art_storage_mode=album_art_storage_mode if index == 1 else None,
                )
            )

        self.app._warn_duplicate_track_numbers(
            album_title=album_title,
            planned_rows=[(payload.track_number, payload.track_title) for payload in payloads],
            parent_widget=self,
            title="Duplicate Album Track Numbers",
            track_service=self.app.track_service,
            cursor=self.app.cursor,
        )
        return payloads

    def save_album(self) -> None:
        payloads = self._build_track_payloads()
        if payloads is None:
            return
        reserved_isrcs: list[str] = []
        for payload in payloads:
            if not payload.isrc:
                continue
            if not self.app._reserve_isrc_claim_for_profile(
                payload.isrc,
                track_title=payload.track_title,
                claim_kind="album_batch",
                parent_widget=self,
            ):
                for reserved_isrc in reserved_isrcs:
                    self.app._release_reserved_isrc_claim(reserved_isrc)
                return
            reserved_isrcs.append(payload.isrc)

        album_title = payloads[0].album_title or "Album"
        refresh_request = self.app._capture_catalog_refresh_request()
        profile_name = self.app._current_profile_name()

        def _worker(bundle, ctx):
            ctx.report_progress(
                value=0,
                maximum=100,
                message="Saving album tracks, media, and work governance...",
            )
            governed_service = GovernedImportCoordinator(
                bundle.conn,
                track_service=bundle.track_service,
                party_service=bundle.party_service,
                work_service=bundle.work_service,
                profile_name=profile_name,
            )

            def _mutation():
                cur = bundle.conn.cursor()
                results = governed_service.create_governed_tracks_batch(
                    payloads,
                    cursor=cur,
                    profile_name=profile_name,
                    progress_callback=self.app._scaled_progress_callback(
                        ctx.report_progress,
                        start=4,
                        end=40,
                    ),
                )
                created_track_ids = [int(result.track_id) for result in results]
                created_work_ids = [int(result.work_id) for result in results]
                ctx.report_progress(
                    value=44,
                    maximum=100,
                    message="Synchronizing release records for the saved album...",
                )
                release_ids = self.app._sync_releases_for_tracks(
                    created_track_ids,
                    cursor=cur,
                    track_service=bundle.track_service,
                    release_service=bundle.release_service,
                    profile_name=profile_name,
                )
                return {
                    "track_ids": created_track_ids,
                    "work_ids": created_work_ids,
                    "release_ids": list(release_ids),
                }

            result_payload = run_snapshot_history_action(
                history_manager=bundle.history_manager,
                action_label=f"Create Album Batch: {album_title}",
                action_type="album.create",
                entity_type="Album",
                entity_id=album_title,
                payload={
                    "album_title": album_title,
                    "track_count": len(payloads),
                },
                mutation=_mutation,
                progress_callback=ctx.report_progress,
                post_mutation_progress=(50, "Capturing album-save history snapshot..."),
                record_progress=(58, "Recording album-save history..."),
                logger=self.app.logger,
            )
            ctx.report_progress(
                value=60,
                maximum=100,
                message="Loading refreshed catalog rows, media badges, and lookup values...",
            )
            result_payload["dataset"] = self.app._load_catalog_ui_dataset_from_bundle(
                bundle,
                ctx,
                progress_start=62,
                progress_end=88,
            )
            return result_payload

        def _before_cleanup(result_payload: dict[str, object], ui_progress) -> None:
            try:
                self.app.conn.commit()
            except Exception:
                pass
            focus_id = None
            track_ids = list(result_payload.get("track_ids") or [])
            for track_id, track_payload in zip(track_ids, payloads):
                self.app._activate_isrc_claim_for_track(
                    track_payload.isrc,
                    track_id=int(track_id),
                    track_title=track_payload.track_title,
                    claim_kind="album_batch",
                )
            if track_ids:
                focus_id = int(track_ids[0])
            refresh_payload = dict(refresh_request)
            refresh_payload["focus_id"] = focus_id
            self.app._apply_catalog_refresh_request(
                dict(result_payload.get("dataset") or {}),
                refresh_payload,
                progress_callback=self.app._scaled_ui_progress_callback(
                    ui_progress,
                    start=90,
                    end=97,
                ),
            )
            self.created_track_ids = track_ids
            self.app._advance_task_ui_progress(
                ui_progress,
                value=98,
                message="Refreshing work manager and final album state...",
            )
            if result_payload.get("work_ids"):
                self.app._refresh_work_manager_panel()
                self.app._focus_work_in_manager(int(result_payload["work_ids"][0]))
            self.app._advance_task_ui_progress(
                ui_progress,
                value=100,
                message="Album saved and catalog UI is ready.",
            )

        def _after_cleanup(result_payload: dict[str, object]) -> None:
            track_ids = list(result_payload.get("track_ids") or [])
            release_ids = list(result_payload.get("release_ids") or [])
            self.app._log_event(
                "album.create",
                "Album created",
                album_title=album_title,
                track_ids=track_ids,
                track_count=len(track_ids),
                release_ids=release_ids,
            )
            for track_id, track_payload in zip(track_ids, payloads):
                self.app._audit(
                    "CREATE", "Track", ref_id=track_id, details=f"isrc={track_payload.isrc}"
                )
            self.app._audit_commit()
            if hasattr(self.app, "statusBar"):
                self.app.statusBar().showMessage(
                    f"Saved album '{album_title}' with {len(track_ids)} track{'s' if len(track_ids) != 1 else ''}.",
                    5000,
                )
            self.accept()

        self.app._submit_background_bundle_task(
            title="Save Album",
            description="Saving album tracks, media, and work governance...",
            task_fn=_worker,
            kind="write",
            unique_key=f"album.create.{album_title.strip().casefold()}",
            owner=self.app,
            worker_completion_progress=(89, "Finalizing background album save..."),
            on_success_before_cleanup=_before_cleanup,
            on_success_after_cleanup=_after_cleanup,
            on_error=lambda failure: (
                [self.app._release_reserved_isrc_claim(isrc) for isrc in reserved_isrcs],
                self.app._show_background_task_error(
                    "Save Album",
                    failure,
                    user_message="Could not save the album:",
                ),
            ),
        )

__all__ = ["AlbumEntryDialog", "_AlbumTrackSection"]

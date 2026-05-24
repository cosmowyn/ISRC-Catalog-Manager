"""Track edit dialog."""

from __future__ import annotations

from PySide6.QtCore import QDate, QEvent, Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QCalendarWidget,
    QComboBox,
    QCompleter,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
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
    normalize_isrc,
    normalize_iswc,
    to_compact_isrc,
    to_iso_isrc,
    to_iso_iswc,
    valid_upc_ean,
)
from isrc_manager.domain.timecode import hms_to_seconds, seconds_to_hms
from isrc_manager.file_storage import STORAGE_MODE_DATABASE, normalize_storage_mode
from isrc_manager.gs1_dialog import GS1MetadataDialog
from isrc_manager.parties import party_authority_notifier
from isrc_manager.services import TrackSnapshot, TrackUpdatePayload
from isrc_manager.services.bulk_edit import MIXED_VALUE, shared_bulk_value, should_apply_bulk_change
from isrc_manager.tasks.history_helpers import run_snapshot_history_action
from isrc_manager.tracks.host_protocols import TrackEditorHost
from isrc_manager.ui_common import (
    FocusWheelCalendarWidget,
    FocusWheelComboBox,
    FocusWheelSpinBox,
    TwoDigitSpinBox,
    _add_standard_dialog_header,
    _apply_standard_dialog_chrome,
    _create_standard_section,
)


class EditDialog(QDialog):
    """Edits one or more Track rows, including promoted standard fields."""

    BULK_MIXED_TEXT = "{Multiple values}"
    BULK_VIEW_ONLY_FIELDS = {
        "isrc",
        "iswc",
        "track_title",
        "track_number",
        "audio_file",
        "track_length_sec",
        "buma_work_number",
    }
    SINGLE_EDIT_ALBUM_SHARED_FIELDS = {
        "artist_name": "Artist",
        "album_title": "Album Title",
        "release_date": "Release Date",
        "upc": "UPC/EAN",
        "genre": "Genre",
        "catalog_number": "Catalog#",
        "album_art": "Album Art",
    }
    BULK_MIXED_TOOLTIP = "Selected records currently have different values. Replace this field to update every selected record."

    def __init__(
        self,
        track_id: int,
        parent: TrackEditorHost,
        batch_track_ids: list[int] | None = None,
        initial_focus_target: str | None = None,
    ):
        super().__init__(parent)
        self.parent: TrackEditorHost = parent
        self.track_id = int(track_id)
        self.batch_track_ids = self._normalize_batch_track_ids(track_id, batch_track_ids)
        self._initial_focus_target = str(initial_focus_target or "").strip() or None
        self._is_bulk_edit = len(self.batch_track_ids) > 1
        self._bulk_loading = True
        self._bulk_field_state: dict[str, dict[str, object]] = {}
        self._bulk_focus_targets: dict[object, str] = {}
        self._editor_tab_indices: dict[str, int] = {}

        self._bulk_snapshots = self._load_bulk_snapshots()
        self._album_art_edit_states = self._load_album_art_edit_states()
        self.snapshot = next(
            snapshot for snapshot in self._bulk_snapshots if snapshot.track_id == self.track_id
        )
        self._build_bulk_field_states()

        self._existing_audio_display_path = self._resolve_audio_file_display(self.snapshot)
        self._existing_album_art_display_path = self._resolve_album_art_display(self.snapshot)
        self._album_art_hint_owner_targets: list[tuple[int, str]] = []
        self._clear_audio_file = False
        self._clear_album_art = False

        self.setWindowTitle(
            f"Bulk Edit {len(self.batch_track_ids)} Tracks" if self._is_bulk_edit else "Edit Track"
        )
        self.setModal(True)
        self.resize(760, 920 if self._is_bulk_edit else 860)
        self.setMinimumSize(700, 780)
        _apply_standard_dialog_chrome(self, "editDialog")

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(18, 18, 18, 18)
        main_layout.setSpacing(14)
        header_subtitle = (
            "Replace only the fields you want to change across the selected records. Mixed values stay untouched unless you enter a new one."
            if self._is_bulk_edit
            else "Update track details, release metadata, registration codes, and managed media from one organized editor."
        )
        _add_standard_dialog_header(
            main_layout,
            self,
            title=(
                f"Bulk Edit {len(self.batch_track_ids)} Tracks"
                if self._is_bulk_edit
                else "Edit Track"
            ),
            subtitle=header_subtitle,
            help_topic_id="edit-entry",
        )

        if self._is_bulk_edit:
            bulk_box, bulk_layout = _create_standard_section(
                self,
                "Bulk Edit Rules",
                "Only changed fields are applied to every selected record. Locked identifiers stay view-only in this editor.",
            )
            bulk_notice = QLabel(
                f"Bulk editing {len(self.batch_track_ids)} selected tracks. "
                f"Fields showing {self.BULK_MIXED_TEXT} stay unchanged unless you replace them. "
                "ISRC, ISWC, Track Title, Track Number, Audio File, Track Length, and BUMA Wnr. are view-only in this window."
            )
            bulk_notice.setWordWrap(True)
            bulk_notice.setProperty("role", "supportingText")
            bulk_layout.addWidget(bulk_notice)
            main_layout.addWidget(bulk_box)

        self.editor_tabs = QTabWidget(self)
        self.editor_tabs.setObjectName("editDialogTabs")
        self.editor_tabs.setDocumentMode(True)
        self.editor_tabs.setUsesScrollButtons(False)
        main_layout.addWidget(self.editor_tabs, 1)

        def create_tab(tab_key: str, title: str, description: str) -> QVBoxLayout:
            page = QWidget(self.editor_tabs)
            page.setProperty("role", "workspaceCanvas")
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(0, 0, 0, 0)
            page_layout.setSpacing(10)

            intro = QLabel(description, page)
            intro.setWordWrap(True)
            intro.setProperty("role", "secondary")
            page_layout.addWidget(intro)

            scroll = QScrollArea(page)
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setProperty("role", "workspaceCanvas")
            viewport = scroll.viewport()
            if viewport is not None:
                viewport.setProperty("role", "workspaceCanvas")

            content = QWidget(scroll)
            content.setProperty("role", "workspaceCanvas")
            content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
            content_layout = QVBoxLayout(content)
            content_layout.setContentsMargins(0, 0, 0, 0)
            content_layout.setSpacing(12)

            scroll.setWidget(content)
            page_layout.addWidget(scroll, 1)
            self._editor_tab_indices[tab_key] = int(self.editor_tabs.addTab(page, title))
            return content_layout

        def create_section(target_layout: QVBoxLayout, title: str, description: str | None = None):
            box, box_layout = _create_standard_section(self, title, description)
            target_layout.addWidget(box)
            return box_layout

        def add_row(target_layout, label_text, widget):
            row = QVBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(4)
            lbl = QLabel(label_text)
            row.addWidget(lbl)
            row.addWidget(widget)
            target_layout.addLayout(row)

        def combo(
            target_layout,
            label,
            field_name,
            value,
            source_query=None,
            allow_empty=True,
            source_values: list[str] | None = None,
        ):
            cb = FocusWheelComboBox()
            cb.setEditable(True)
            items: list[str] = []
            seen: set[str] = set()
            if source_values is not None:
                for raw_text in source_values:
                    text = str(raw_text or "").strip()
                    if not text or text in seen:
                        continue
                    seen.add(text)
                    items.append(text)
            elif source_query:
                for row in self.parent.cursor.execute(source_query).fetchall():
                    text = str(row[0] or "").strip()
                    if not text or text in seen:
                        continue
                    seen.add(text)
                    items.append(text)
            display_value = self._display_value_for_field(field_name, value).strip()
            if (
                display_value
                and display_value != self.BULK_MIXED_TEXT
                and display_value not in seen
            ):
                items.append(display_value)
            if allow_empty:
                cb.addItem("")
            cb.addItems(items)
            comp = QCompleter(items)
            comp.setCaseSensitivity(Qt.CaseInsensitive)
            cb.setCompleter(comp)
            self._configure_combo_field(cb, field_name, value)
            add_row(target_layout, label, cb)
            return cb

        track_tab_layout = create_tab(
            "track",
            "Track",
            "Edit the main track-facing fields here, including credits, title, and genre.",
        )
        release_tab_layout = create_tab(
            "release",
            "Release",
            "Keep album grouping, release timing, and track duration together in one place.",
        )
        codes_tab_layout = create_tab(
            "codes",
            "Codes",
            "Manage identifiers, registration values, and catalog metadata used by exports and rights workflows.",
        )
        media_tab_layout = create_tab(
            "media",
            "Media",
            "Review and replace the managed audio and artwork files linked to this track.",
        )

        core_layout = create_section(
            track_tab_layout,
            "Core Details",
            "These fields describe the selected track directly and are shown throughout the catalog.",
        )
        album_release_layout = create_section(
            release_tab_layout,
            "Album & Release",
            "Changes here can affect release synchronization and, in single-track edit mode, shared album metadata.",
        )
        identifiers_layout = create_section(
            codes_tab_layout,
            "Identifiers",
            "ISRC and ISWC remain the primary recording and work identifiers for this track.",
        )
        registration_layout = create_section(
            codes_tab_layout,
            "Registration & Catalog",
            "Product-level codes and registration values used for distribution, GS1, and collection-society workflows.",
        )
        audio_layout_section = create_section(
            media_tab_layout,
            "Managed Audio",
            "Attach or replace the stored audio file used by preview and metadata workflows.",
        )
        artwork_layout_section = create_section(
            media_tab_layout,
            "Artwork & Shared Album Media",
            "Album art can propagate to sibling tracks when you update shared album metadata.",
        )

        self.isrc_field = QLineEdit()
        self._configure_text_field(self.isrc_field, "isrc", self.snapshot.isrc, lock_in_bulk=True)
        add_row(identifiers_layout, "ISRC", self.isrc_field)

        row_isrc_btns = QHBoxLayout()
        self.btn_isrc_copy_iso = QPushButton("Copy ISO")
        self.btn_isrc_copy_compact = QPushButton("Copy compact")
        row_isrc_btns.addWidget(self.btn_isrc_copy_iso)
        row_isrc_btns.addWidget(self.btn_isrc_copy_compact)
        row_isrc_btns.addStretch(1)
        identifiers_layout.addLayout(row_isrc_btns)
        self.btn_isrc_copy_iso.clicked.connect(self._copy_isrc_iso)
        self.btn_isrc_copy_iso.setDefault(False)
        self.btn_isrc_copy_compact.clicked.connect(self._copy_isrc_compact)

        self.entry_date_field = QLineEdit()
        self._configure_text_field(
            self.entry_date_field,
            "db_entry_date",
            self.snapshot.db_entry_date or "",
            read_only=True,
            track_changes=False,
        )

        self.track_title = QLineEdit()
        self._configure_text_field(self.track_title, "track_title", self.snapshot.track_title)
        add_row(core_layout, "Track Title", self.track_title)

        self.artist_name = combo(
            core_layout,
            "Artist",
            "artist_name",
            self.snapshot.artist_name,
            allow_empty=False,
            source_values=self.parent._artist_lookup_values(),
        )
        self.additional_artist = combo(
            core_layout,
            "Additional Artist(s)",
            "additional_artists",
            ", ".join(self.snapshot.additional_artists),
            source_values=self.parent._artist_lookup_values(),
        )
        self.album_title = combo(
            album_release_layout,
            "Album Title",
            "album_title",
            self.snapshot.album_title or "",
            "SELECT DISTINCT title FROM Albums ORDER BY title",
        )
        self.track_number = FocusWheelSpinBox()
        self.track_number.setRange(0, 9999)
        self.track_number.setSpecialValueText("Unset")
        current_track_number = int(self.snapshot.track_number or 0)
        if self._is_bulk_edit and not self._bulk_field_is_mixed("track_number"):
            current_track_number = int(self._bulk_field_initial("track_number") or 0)
        self.track_number.setValue(max(0, current_track_number))
        track_number_widget = QWidget(self)
        track_number_layout = QVBoxLayout(track_number_widget)
        track_number_layout.setContentsMargins(0, 0, 0, 0)
        track_number_layout.setSpacing(6)
        track_number_layout.addWidget(self.track_number, 0, Qt.AlignLeft)
        track_number_note = self._create_bulk_note(
            "track_number",
            "Track Number is view-only during bulk edit. Selected tracks currently use different numbers.",
        )
        if track_number_note is not None:
            track_number_layout.addWidget(track_number_note)
        elif self._is_bulk_edit and self._is_bulk_locked_field("track_number"):
            locked_track_number_note = QLabel("Track Number is view-only during bulk edit.")
            locked_track_number_note.setWordWrap(True)
            track_number_layout.addWidget(locked_track_number_note)
        if self._is_bulk_edit and self._is_bulk_locked_field("track_number"):
            self.track_number.setEnabled(False)
        add_row(album_release_layout, "Track Number", track_number_widget)
        self.genre = combo(
            core_layout,
            "Genre",
            "genre",
            self.snapshot.genre or "",
            "SELECT DISTINCT genre FROM Tracks WHERE genre IS NOT NULL AND genre != '' ORDER BY genre",
        )

        self.audio_file = QLineEdit()
        self._configure_text_field(
            self.audio_file,
            "audio_file",
            self._existing_audio_display_path,
            read_only=True,
        )
        audio_row = QWidget(self)
        audio_layout = QHBoxLayout(audio_row)
        audio_layout.setContentsMargins(0, 0, 0, 0)
        audio_layout.setSpacing(8)
        audio_layout.addWidget(self.audio_file, 1)
        self.audio_file_browse_button = QPushButton("Browse…")
        self.audio_file_clear_button = QPushButton("Clear")
        self.audio_file_browse_button.clicked.connect(
            lambda: self._choose_track_media(
                "audio_file", self.audio_file, clear_attr="_clear_audio_file"
            )
        )
        self.audio_file_clear_button.clicked.connect(
            lambda: self._clear_track_media(self.audio_file, clear_attr="_clear_audio_file")
        )
        if self._is_bulk_edit and self._is_bulk_locked_field("audio_file"):
            self.audio_file_browse_button.setEnabled(False)
            self.audio_file_clear_button.setEnabled(False)
        audio_layout.addWidget(self.audio_file_browse_button)
        audio_layout.addWidget(self.audio_file_clear_button)
        audio_widget = QWidget(self)
        audio_widget_layout = QVBoxLayout(audio_widget)
        audio_widget_layout.setContentsMargins(0, 0, 0, 0)
        audio_widget_layout.setSpacing(6)
        audio_widget_layout.addWidget(audio_row)
        self.audio_file_warning_label = QLabel("")
        self.audio_file_warning_label.setWordWrap(True)
        self.audio_file_warning_label.setProperty("role", "supportingText")
        self.audio_file_warning_label.setVisible(False)
        audio_widget_layout.addWidget(self.audio_file_warning_label)
        self.audio_file._lossy_audio_warning_label = self.audio_file_warning_label
        self.audio_file.textChanged.connect(
            lambda _text: self.parent._refresh_line_edit_lossy_audio_warning(self.audio_file)
        )
        self.parent._refresh_line_edit_lossy_audio_warning(self.audio_file)
        add_row(audio_layout_section, "Audio File", audio_widget)

        self.album_art = QLineEdit()
        self._configure_text_field(
            self.album_art,
            "album_art",
            self._existing_album_art_display_path,
            read_only=True,
        )
        art_row = QWidget(self)
        art_layout = QHBoxLayout(art_row)
        art_layout.setContentsMargins(0, 0, 0, 0)
        art_layout.setSpacing(8)
        art_layout.addWidget(self.album_art, 1)
        self.album_art_browse_button = QPushButton("Browse…")
        self.album_art_clear_button = QPushButton("Clear")
        self.album_art_browse_button.clicked.connect(
            lambda: self._choose_track_media(
                "album_art", self.album_art, clear_attr="_clear_album_art"
            )
        )
        self.album_art_clear_button.clicked.connect(
            lambda: self._clear_track_media(self.album_art, clear_attr="_clear_album_art")
        )
        art_layout.addWidget(self.album_art_browse_button)
        art_layout.addWidget(self.album_art_clear_button)
        add_row(artwork_layout_section, "Album Art", art_row)
        hint_row = QWidget(self)
        hint_layout = QHBoxLayout(hint_row)
        hint_layout.setContentsMargins(0, 0, 0, 0)
        hint_layout.setSpacing(8)
        self.album_art_hint_label = QLabel("")
        self.album_art_hint_label.setWordWrap(True)
        self.album_art_hint_label.setProperty("role", "supportingText")
        hint_layout.addWidget(self.album_art_hint_label, 1)
        self.album_art_open_master_button = QPushButton("Open Master Record")
        self.album_art_open_master_button.setObjectName("albumArtOpenMasterButton")
        self.album_art_open_master_button.setAutoDefault(False)
        self.album_art_open_master_button.clicked.connect(self._open_album_art_owner_from_hint)
        hint_layout.addWidget(self.album_art_open_master_button, 0, Qt.AlignTop)
        artwork_layout_section.addWidget(hint_row)
        self._refresh_album_art_controls()

        self.catalog_number = CatalogIdentifierField(
            service_provider=lambda: getattr(self.parent, "code_registry_service", None),
            allow_generate=not self._is_bulk_edit,
            created_via=("track.bulk_edit" if self._is_bulk_edit else "track.editor"),
            parent=self,
        )
        if not self._is_bulk_edit:
            self.catalog_number.set_assignment(
                value=self.snapshot.catalog_number or "",
                registry_entry_id=self.snapshot.catalog_registry_entry_id,
                external_identifier_id=(
                    self.snapshot.catalog_external_code_identifier_id
                    if self.snapshot.catalog_external_code_identifier_id is not None
                    else self.snapshot.external_catalog_identifier_id
                ),
                mode=self.snapshot.catalog_number_mode,
            )
        else:
            self.catalog_number.set_assignment(
                value=self._display_value_for_field(
                    "catalog_number", self.snapshot.catalog_number or ""
                ),
                registry_entry_id=None,
                external_identifier_id=None,
                mode=None,
            )
            self._set_bulk_hint(self.catalog_number.combo, "catalog_number")
            line_edit = self.catalog_number.lineEdit()
            if line_edit is not None:
                self._set_bulk_hint(line_edit, "catalog_number")
                self._register_bulk_focus_target(line_edit, "catalog_number")
            self.catalog_number.valueChanged.connect(
                lambda: self._mark_bulk_field_modified("catalog_number")
            )
        add_row(registration_layout, "Catalog#", self.catalog_number)

        self.buma_work_number = QLineEdit()
        self._buma_work_number_managed_by_work = self._buma_work_number_is_work_managed()
        self._configure_text_field(
            self.buma_work_number,
            "buma_work_number",
            self._resolved_buma_work_number_text(),
        )
        buma_work_number_widget: QWidget = self.buma_work_number
        if self._buma_work_number_managed_by_work and not self._is_bulk_edit:
            self.buma_work_number.setReadOnly(True)
            self.buma_work_number.setToolTip(
                "Managed by the linked Work. Open Work Manager to update the BUMA Wnr."
            )
            buma_work_number_widget = QWidget(self)
            buma_work_number_layout = QVBoxLayout(buma_work_number_widget)
            buma_work_number_layout.setContentsMargins(0, 0, 0, 0)
            buma_work_number_layout.setSpacing(6)
            buma_work_number_layout.addWidget(self.buma_work_number)
            buma_work_number_note = QLabel(
                "Managed by the linked Work. Open Work Manager to change this value."
            )
            buma_work_number_note.setWordWrap(True)
            buma_work_number_note.setProperty("role", "supportingText")
            buma_work_number_layout.addWidget(buma_work_number_note)

        self.release_date = FocusWheelCalendarWidget()
        self.release_date.setVerticalHeaderFormat(QCalendarWidget.NoVerticalHeader)
        self.release_date.setHorizontalHeaderFormat(QCalendarWidget.ShortDayNames)
        self.release_date.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        release_iso = self.snapshot.release_date or ""
        if self._is_bulk_edit and not self._bulk_field_is_mixed("release_date"):
            release_iso = str(self._bulk_field_initial("release_date") or "")
        release_qdate = QDate.fromString(release_iso, "yyyy-MM-dd")
        self.release_date.setSelectedDate(
            release_qdate if release_qdate.isValid() else QDate.currentDate()
        )
        calendar_width = max(420, self.release_date.sizeHint().width())
        calendar_height = max(320, self.release_date.sizeHint().height())
        self.release_date.setFixedSize(calendar_width, calendar_height)
        if self._is_bulk_edit:
            self.release_date.selectionChanged.connect(
                lambda: self._mark_bulk_field_modified("release_date")
            )
            self.release_date.clicked.connect(
                lambda _date: self._mark_bulk_field_modified("release_date")
            )
        release_widget = QWidget(self)
        release_layout = QVBoxLayout(release_widget)
        release_layout.setContentsMargins(0, 0, 0, 0)
        release_layout.setSpacing(6)
        release_layout.addWidget(self.release_date, 0, Qt.AlignLeft)
        release_note = self._create_bulk_note(
            "release_date",
            "Selected tracks currently use different release dates. Pick a date to replace them all.",
        )
        if release_note is not None:
            release_layout.addWidget(release_note)
        add_row(album_release_layout, "Release Date", release_widget)

        self.len_h = TwoDigitSpinBox()
        self.len_h.setRange(0, 99)
        self.len_h.setFixedWidth(60)
        self.len_m = TwoDigitSpinBox()
        self.len_m.setRange(0, 59)
        self.len_m.setFixedWidth(50)
        self.len_s = TwoDigitSpinBox()
        self.len_s.setRange(0, 59)
        self.len_s.setFixedWidth(50)
        current_length_seconds = int(self.snapshot.track_length_sec or 0)
        if self._is_bulk_edit and not self._bulk_field_is_mixed("track_length_sec"):
            current_length_seconds = int(self._bulk_field_initial("track_length_sec") or 0)
        current_length = seconds_to_hms(current_length_seconds)
        try:
            parts = current_length.split(":")
            self.len_h.setValue(int(parts[0]))
            self.len_m.setValue(int(parts[1]))
            self.len_s.setValue(int(parts[2]))
        except Exception:
            pass
        if self._is_bulk_edit:
            self.len_h.valueChanged.connect(
                lambda _value: self._mark_bulk_field_modified("track_length_sec")
            )
            self.len_m.valueChanged.connect(
                lambda _value: self._mark_bulk_field_modified("track_length_sec")
            )
            self.len_s.valueChanged.connect(
                lambda _value: self._mark_bulk_field_modified("track_length_sec")
            )
        tl_group = QFrame(self)
        tl_group.setProperty("role", "compactControlGroup")
        tl_group.setAttribute(Qt.WA_StyledBackground, True)
        tl_group.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        tl = QHBoxLayout(tl_group)
        tl.setContentsMargins(10, 8, 10, 8)
        tl.setSpacing(6)
        tl.addWidget(self.len_h)
        tl.addWidget(QLabel(":"))
        tl.addWidget(self.len_m)
        tl.addWidget(QLabel(":"))
        tl.addWidget(self.len_s)
        self.set_length_from_saved_audio_button = QPushButton("Set Length from Saved Audio")
        self.set_length_from_saved_audio_button.setObjectName("setLengthFromSavedAudioButton")
        self.set_length_from_saved_audio_button.setAutoDefault(False)
        self.set_length_from_saved_audio_button.setToolTip(
            "Read the saved audio file duration into the track length fields."
        )
        self.set_length_from_saved_audio_button.clicked.connect(
            self._set_track_length_from_saved_audio
        )
        can_read_saved_audio = not self._is_bulk_edit and (
            bool(self.snapshot.audio_file_path)
            or normalize_storage_mode(self.snapshot.audio_file_storage_mode, default=None)
            == STORAGE_MODE_DATABASE
            or bool(self.snapshot.audio_file_blob_b64)
        )
        self.set_length_from_saved_audio_button.setEnabled(can_read_saved_audio)
        if self._is_bulk_edit:
            self.set_length_from_saved_audio_button.setToolTip(
                "Saved audio length can be read when editing a single track."
            )
        elif not can_read_saved_audio:
            self.set_length_from_saved_audio_button.setToolTip(
                "No saved audio file is attached to this track."
            )
        tl.addSpacing(10)
        tl.addWidget(self.set_length_from_saved_audio_button)
        tlw = QWidget()
        tlw_layout = QVBoxLayout(tlw)
        tlw_layout.setContentsMargins(0, 0, 0, 0)
        tlw_layout.setSpacing(6)
        tlw_layout.addWidget(tl_group, 0, Qt.AlignLeft)
        length_note = self._create_bulk_note(
            "track_length_sec",
            "Track Length is view-only during bulk edit. Selected tracks currently use different lengths.",
        )
        if length_note is not None:
            tlw_layout.addWidget(length_note)
        elif self._is_bulk_edit and self._is_bulk_locked_field("track_length_sec"):
            locked_length_note = QLabel("Track Length is view-only during bulk edit.")
            locked_length_note.setWordWrap(True)
            tlw_layout.addWidget(locked_length_note)
        if self._is_bulk_edit and self._is_bulk_locked_field("track_length_sec"):
            self.len_h.setEnabled(False)
            self.len_m.setEnabled(False)
            self.len_s.setEnabled(False)
        add_row(album_release_layout, "Track Length (hh:mm:ss)", tlw)

        self.iswc = QLineEdit()
        self._configure_text_field(self.iswc, "iswc", self.snapshot.iswc or "", lock_in_bulk=True)
        add_row(identifiers_layout, "ISWC", self.iswc)

        row_iswc_btns = QHBoxLayout()
        self.btn_iswc_copy_iso = QPushButton("Copy ISO")
        self.btn_iswc_copy_compact = QPushButton("Copy compact")
        row_iswc_btns.addWidget(self.btn_iswc_copy_iso)
        row_iswc_btns.addWidget(self.btn_iswc_copy_compact)
        row_iswc_btns.addStretch(1)
        identifiers_layout.addLayout(row_iswc_btns)
        self.btn_iswc_copy_iso.clicked.connect(self._copy_iswc_iso)
        self.btn_iswc_copy_iso.setDefault(False)
        self.btn_iswc_copy_compact.clicked.connect(self._copy_iswc_compact)

        self.upc = combo(
            registration_layout,
            "UPC/EAN",
            "upc",
            self.snapshot.upc or "",
            """
            SELECT value
            FROM (
                SELECT upc AS value FROM Tracks WHERE upc IS NOT NULL AND upc != ''
                UNION
                SELECT upc AS value FROM Releases WHERE upc IS NOT NULL AND upc != ''
            )
            ORDER BY value
            """,
        )
        self.upc.setInsertPolicy(QComboBox.NoInsert)
        add_row(registration_layout, "BUMA Wnr.", buma_work_number_widget)
        add_row(registration_layout, "Entry Date", self.entry_date_field)

        track_tab_layout.addStretch(1)
        release_tab_layout.addStretch(1)
        codes_tab_layout.addStretch(1)
        media_tab_layout.addStretch(1)

        btns = QHBoxLayout()
        gs1_btn = QPushButton("GS1 Metadata…")
        gs1_btn.setAutoDefault(False)
        gs1_btn.clicked.connect(self._open_gs1_metadata)
        if self._is_bulk_edit:
            gs1_btn.setToolTip(
                "Open GS1 metadata for the same selected tracks shown in this bulk edit window."
            )
        btns.addWidget(gs1_btn)
        btns.addStretch(1)
        save_btn = QPushButton("Apply Changes" if self._is_bulk_edit else "Save Changes")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self.save_changes)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btns.addWidget(save_btn)
        btns.addWidget(cancel_btn)
        main_layout.addLayout(btns)

        if self._is_bulk_edit:
            self.btn_isrc_copy_iso.setEnabled(False)
            self.btn_isrc_copy_compact.setEnabled(False)
            self.btn_iswc_copy_iso.setEnabled(False)
            self.btn_iswc_copy_compact.setEnabled(False)

        self._bulk_loading = False
        party_authority_notifier().changed.connect(self._handle_party_authority_changed)
        if self._initial_focus_target:
            QTimer.singleShot(0, lambda: self._apply_initial_focus_target())

    @staticmethod
    def _normalize_batch_track_ids(track_id: int, batch_track_ids: list[int] | None) -> list[int]:
        normalized: list[int] = []
        seen: set[int] = set()
        candidates = [track_id]
        if batch_track_ids:
            candidates.extend(batch_track_ids)
        for candidate in candidates:
            try:
                value = int(candidate)
            except (TypeError, ValueError):
                continue
            if value <= 0 or value in seen:
                continue
            seen.add(value)
            normalized.append(value)
        if not normalized:
            normalized.append(int(track_id))
        return normalized

    def _load_bulk_snapshots(self) -> list[TrackSnapshot]:
        snapshots: list[TrackSnapshot] = []
        for candidate_id in self.batch_track_ids:
            snapshot = self.parent.track_service.fetch_track_snapshot(candidate_id)
            if snapshot is None:
                raise ValueError(f"Track {candidate_id} not found")
            snapshots.append(snapshot)
        return snapshots

    def _load_album_art_edit_states(self) -> dict[int, object]:
        track_service = getattr(self.parent, "track_service", None)
        if track_service is None:
            return {}
        return {
            snapshot.track_id: track_service.describe_album_art_edit_state(snapshot.track_id)
            for snapshot in self._bulk_snapshots
        }

    @staticmethod
    def _refresh_editable_combo_items(
        combo: QComboBox,
        source_values: list[str],
        *,
        current_text: str,
        allow_empty: bool,
    ) -> None:
        items: list[str] = []
        seen: set[str] = set()
        for raw_value in source_values:
            clean_value = str(raw_value or "").strip()
            if not clean_value or clean_value in seen:
                continue
            seen.add(clean_value)
            items.append(clean_value)
        previous_state = combo.blockSignals(True)
        try:
            combo.clear()
            combo.setEditable(True)
            combo.setInsertPolicy(QComboBox.NoInsert)
            if allow_empty:
                combo.addItem("")
            combo.addItems(items)
            completer = QCompleter(items, combo)
            completer.setCaseSensitivity(Qt.CaseInsensitive)
            combo.setCompleter(completer)
            clean_current = str(current_text or "").strip()
            if clean_current:
                combo.setCurrentIndex(-1)
                combo.setEditText(clean_current)
            elif allow_empty:
                combo.setCurrentIndex(0)
            else:
                combo.setCurrentIndex(-1)
        finally:
            combo.blockSignals(previous_state)

    def _party_backed_artist_field_text(self) -> str:
        current_text = str(self.artist_name.currentText() or "").strip()
        if self._is_bulk_edit:
            return current_text
        snapshot_text = str(self.snapshot.artist_name or "").strip()
        party_id = getattr(self.snapshot, "main_artist_party_id", None)
        if party_id not in (None, "") and (not current_text or current_text == snapshot_text):
            record = self.parent.party_service.fetch_party(int(party_id))
            if record is not None:
                return self.parent._artist_party_primary_label(record)
        return current_text or snapshot_text

    def _party_backed_additional_artist_text(self) -> str:
        current_text = str(self.additional_artist.currentText() or "").strip()
        if self._is_bulk_edit:
            return current_text
        snapshot_text = ", ".join(self.snapshot.additional_artists)
        party_ids = list(getattr(self.snapshot, "additional_artist_party_ids", []) or [])
        if party_ids and (not current_text or current_text == snapshot_text):
            labels: list[str] = []
            seen: set[str] = set()
            for party_id in party_ids:
                record = self.parent.party_service.fetch_party(int(party_id))
                if record is None:
                    continue
                label = self.parent._artist_party_primary_label(record)
                normalized = label.casefold()
                if not label or normalized in seen:
                    continue
                seen.add(normalized)
                labels.append(label)
            if labels:
                return ", ".join(labels)
        return current_text or snapshot_text

    def _refresh_artist_combo_sources(self) -> None:
        source_values = self.parent._artist_lookup_values()
        self._refresh_editable_combo_items(
            self.artist_name,
            source_values,
            current_text=self._party_backed_artist_field_text(),
            allow_empty=False,
        )
        self._refresh_editable_combo_items(
            self.additional_artist,
            source_values,
            current_text=self._party_backed_additional_artist_text(),
            allow_empty=True,
        )

    def _handle_party_authority_changed(self) -> None:
        self._refresh_artist_combo_sources()

    def _apply_initial_focus_target(self) -> None:
        self.focus_editor_target(self._initial_focus_target)

    @staticmethod
    def _preferred_focus_widget(widget: QWidget | None) -> QWidget | None:
        if widget is None:
            return None
        line_edit_getter = getattr(widget, "lineEdit", None)
        if callable(line_edit_getter):
            try:
                line_edit = line_edit_getter()
            except Exception:
                line_edit = None
            if isinstance(line_edit, QWidget):
                return line_edit
        if isinstance(widget, QComboBox):
            line_edit = widget.lineEdit()
            if isinstance(line_edit, QWidget):
                return line_edit
        return widget

    def focus_editor_target(self, target: str | None) -> bool:
        clean_target = str(target or "").strip().lower()
        if not clean_target:
            return False
        focus_map: dict[str, tuple[str, QWidget | None]] = {
            "track_title": ("track", self.track_title),
            "artist_name": ("track", self.artist_name),
            "additional_artists": ("track", self.additional_artist),
            "genre": ("track", self.genre),
            "album_title": ("release", self.album_title),
            "track_number": ("release", self.track_number),
            "release_date": ("release", self.release_date),
            "track_length_sec": ("release", self.len_h),
            "isrc": ("codes", self.isrc_field),
            "iswc": ("codes", self.iswc),
            "upc": ("codes", self.upc),
            "catalog_number": ("codes", self.catalog_number),
            "buma_work_number": ("codes", self.buma_work_number),
            "db_entry_date": ("codes", self.entry_date_field),
            "audio_file": ("media", self.audio_file_browse_button),
            "album_art": ("media", self.album_art_browse_button),
        }
        focus_target = focus_map.get(clean_target)
        if focus_target is None:
            return False
        tab_key, raw_widget = focus_target
        widget = self._preferred_focus_widget(raw_widget)
        if widget is None or not widget.isEnabled():
            return False
        tab_index = self._editor_tab_indices.get(tab_key)
        if tab_index is None:
            return False
        self.editor_tabs.setCurrentIndex(int(tab_index))
        widget.setFocus(Qt.OtherFocusReason)
        if isinstance(widget, QLineEdit) and not widget.isReadOnly():
            widget.selectAll()
        return widget.hasFocus()

    def _resolved_buma_work_number_text(self, snapshot: TrackSnapshot | None = None) -> str:
        source_snapshot = snapshot or self.snapshot
        work_id = getattr(source_snapshot, "work_id", None)
        if work_id is not None and self.parent.work_service is not None:
            work = self.parent.work_service.fetch_work(int(work_id))
            if work is not None:
                resolved_value = str(getattr(work, "registration_number", "") or "").strip()
                if resolved_value:
                    return resolved_value
        return str(getattr(source_snapshot, "buma_work_number", "") or "").strip()

    def _buma_work_number_is_work_managed(self, snapshot: TrackSnapshot | None = None) -> bool:
        source_snapshot = snapshot or self.snapshot
        return bool(
            getattr(source_snapshot, "work_id", None) is not None
            and self.parent.work_service is not None
        )

    def _resolve_snapshot_media_display(self, stored_path: str | None) -> str:
        return str(self.parent.track_service.resolve_media_path(stored_path) or "")

    def _resolve_audio_file_display(self, snapshot: TrackSnapshot) -> str:
        resolved = self._resolve_snapshot_media_display(snapshot.audio_file_path)
        if resolved:
            return resolved
        if (
            normalize_storage_mode(snapshot.audio_file_storage_mode, default=None)
            == STORAGE_MODE_DATABASE
            or snapshot.audio_file_blob_b64
        ):
            filename = str(snapshot.audio_file_filename or "").strip()
            if filename:
                return f"{filename} (stored in database)"
            return "Stored in database"
        return ""

    def _resolve_album_art_display(self, snapshot: TrackSnapshot) -> str:
        resolved = self._resolve_snapshot_media_display(snapshot.album_art_path)
        if resolved:
            return resolved
        if (
            normalize_storage_mode(snapshot.album_art_storage_mode, default=None)
            == STORAGE_MODE_DATABASE
            or snapshot.album_art_blob_b64
        ):
            filename = str(snapshot.album_art_filename or "").strip()
            if filename:
                return f"{filename} (stored in database)"
            return "Stored in database"
        return ""

    @staticmethod
    def _album_art_owner_label(state: object) -> str:
        owner_track_id = getattr(state, "owner_track_id", None)
        owner_track_title = str(getattr(state, "owner_track_title", "") or "").strip()
        if owner_track_id is None:
            return "another track"
        if owner_track_title:
            return f'Track #{int(owner_track_id)} "{owner_track_title}"'
        return f"Track #{int(owner_track_id)}"

    def _album_art_owner_targets(self) -> list[tuple[int, str]]:
        targets: list[tuple[int, str]] = []
        seen: set[int] = set()
        for state in self._album_art_edit_states.values():
            if not bool(getattr(state, "is_shared_reference", False)):
                continue
            owner_track_id = getattr(state, "owner_track_id", None)
            if owner_track_id is None:
                continue
            owner_track_id = int(owner_track_id)
            if owner_track_id in seen:
                continue
            seen.add(owner_track_id)
            targets.append((owner_track_id, self._album_art_owner_label(state)))
        return targets

    def _single_album_art_hint_text(self) -> str:
        state = self._album_art_edit_states.get(self.track_id)
        if state is None or not bool(getattr(state, "is_shared_reference", False)):
            return ""
        return (
            "This track uses shared album art managed by "
            f"{self._album_art_owner_label(state)}. "
            "Edit that record to replace the shared image."
        )

    def _bulk_album_art_hint_text(self) -> str:
        owners: list[str] = []
        seen: set[str] = set()
        for state in self._album_art_edit_states.values():
            if not bool(getattr(state, "is_shared_reference", False)):
                continue
            label = self._album_art_owner_label(state)
            if label in seen:
                continue
            seen.add(label)
            owners.append(label)
        if not owners:
            return ""
        if len(owners) == 1:
            return (
                "Some selected tracks use shared album art managed by "
                f"{owners[0]}. Edit that record to replace the shared image."
            )
        owner_list = "; ".join(owners[:4])
        if len(owners) > 4:
            owner_list += "; …"
        return (
            "Some selected tracks use shared album art managed by "
            f"{owner_list}. Edit those records to replace the shared image."
        )

    def _open_album_art_owner_track(self, owner_track_id: int) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        parent.refresh_table_preserve_view(focus_id=int(owner_track_id))
        parent.open_track_editor(int(owner_track_id), batch_track_ids=[int(owner_track_id)])

    def _open_album_art_owner_from_hint(self) -> None:
        if len(self._album_art_hint_owner_targets) == 1:
            self._open_album_art_owner_track(self._album_art_hint_owner_targets[0][0])
            return
        if not self._album_art_hint_owner_targets:
            return
        menu = QMenu(self.album_art_open_master_button)
        for owner_track_id, owner_label in self._album_art_hint_owner_targets:
            action = menu.addAction(owner_label)
            action.triggered.connect(
                lambda _checked=False, track_id=owner_track_id: self._open_album_art_owner_track(
                    track_id
                )
            )
        menu.exec(
            self.album_art_open_master_button.mapToGlobal(
                self.album_art_open_master_button.rect().bottomLeft()
            )
        )

    def _refresh_album_art_controls(self) -> None:
        browse_enabled = True
        hint_text = ""
        if self._is_bulk_edit:
            browse_enabled = all(
                bool(getattr(state, "can_replace_directly", True))
                for state in self._album_art_edit_states.values()
            )
            hint_text = self._bulk_album_art_hint_text()
        else:
            state = self._album_art_edit_states.get(self.track_id)
            browse_enabled = bool(getattr(state, "can_replace_directly", True))
            hint_text = self._single_album_art_hint_text()
        self._album_art_hint_owner_targets = self._album_art_owner_targets()
        self.album_art_browse_button.setEnabled(browse_enabled)
        self.album_art_clear_button.setEnabled(True)
        self.album_art_hint_label.setText(hint_text)
        self.album_art_hint_label.setVisible(bool(hint_text))
        has_owner_targets = bool(self._album_art_hint_owner_targets)
        self.album_art_open_master_button.setVisible(has_owner_targets)
        self.album_art_open_master_button.setEnabled(has_owner_targets)
        if len(self._album_art_hint_owner_targets) > 1:
            self.album_art_open_master_button.setText("Open Master Record…")
            self.album_art_open_master_button.setToolTip("Choose which master record to open.")
        else:
            self.album_art_open_master_button.setText("Open Master Record")
            self.album_art_open_master_button.setToolTip("")

    def _build_bulk_field_states(self) -> None:
        if not self._is_bulk_edit:
            return
        snapshots = self._bulk_snapshots
        self._set_bulk_field_state("isrc", [snapshot.isrc or "" for snapshot in snapshots])
        self._set_bulk_field_state(
            "db_entry_date", [snapshot.db_entry_date or "" for snapshot in snapshots]
        )
        self._set_bulk_field_state(
            "track_title", [snapshot.track_title or "" for snapshot in snapshots]
        )
        self._set_bulk_field_state(
            "artist_name", [snapshot.artist_name or "" for snapshot in snapshots]
        )
        self._set_bulk_field_state(
            "additional_artists",
            [tuple(snapshot.additional_artists or []) for snapshot in snapshots],
        )
        self._set_bulk_field_state(
            "album_title", [snapshot.album_title or "" for snapshot in snapshots]
        )
        self._set_bulk_field_state(
            "track_number", [int(snapshot.track_number or 0) for snapshot in snapshots]
        )
        self._set_bulk_field_state("genre", [snapshot.genre or "" for snapshot in snapshots])
        self._set_bulk_field_state(
            "audio_file",
            [
                self._resolve_snapshot_media_display(snapshot.audio_file_path)
                for snapshot in snapshots
            ],
        )
        self._set_bulk_field_state(
            "album_art",
            [self._resolve_album_art_display(snapshot) for snapshot in snapshots],
        )
        self._set_bulk_field_state(
            "catalog_number", [snapshot.catalog_number or "" for snapshot in snapshots]
        )
        self._set_bulk_field_state(
            "buma_work_number",
            [self._resolved_buma_work_number_text(snapshot) for snapshot in snapshots],
        )
        self._set_bulk_field_state(
            "release_date", [snapshot.release_date or "" for snapshot in snapshots]
        )
        self._set_bulk_field_state(
            "track_length_sec", [int(snapshot.track_length_sec or 0) for snapshot in snapshots]
        )
        self._set_bulk_field_state("iswc", [snapshot.iswc or "" for snapshot in snapshots])
        self._set_bulk_field_state("upc", [snapshot.upc or "" for snapshot in snapshots])

    def _set_bulk_field_state(self, field_name: str, values) -> None:
        shared_value = shared_bulk_value(values)
        self._bulk_field_state[field_name] = {
            "mixed": shared_value is MIXED_VALUE,
            "initial": None if shared_value is MIXED_VALUE else shared_value,
            "modified": False,
        }

    @staticmethod
    def _display_value(value) -> str:
        if value is None:
            return ""
        if isinstance(value, (list, tuple)):
            return ", ".join(str(part) for part in value if str(part).strip())
        return str(value)

    def _is_bulk_locked_field(self, field_name: str) -> bool:
        return self._is_bulk_edit and field_name in self.BULK_VIEW_ONLY_FIELDS

    def _bulk_field_is_mixed(self, field_name: str) -> bool:
        return bool(self._bulk_field_state.get(field_name, {}).get("mixed"))

    def _bulk_field_initial(self, field_name: str):
        return self._bulk_field_state.get(field_name, {}).get("initial")

    def _bulk_field_modified(self, field_name: str) -> bool:
        return bool(self._bulk_field_state.get(field_name, {}).get("modified"))

    def _mark_bulk_field_modified(self, field_name: str) -> None:
        if not self._is_bulk_edit or self._bulk_loading:
            return
        state = self._bulk_field_state.get(field_name)
        if state is None:
            return
        state["modified"] = True

    def _register_bulk_focus_target(self, widget, field_name: str) -> None:
        if not self._is_bulk_edit:
            return
        self._bulk_focus_targets[widget] = field_name
        widget.installEventFilter(self)

    def _display_value_for_field(self, field_name: str, single_value) -> str:
        if not self._is_bulk_edit or field_name not in self._bulk_field_state:
            return self._display_value(single_value)
        if self._bulk_field_is_mixed(field_name):
            return self.BULK_MIXED_TEXT
        return self._display_value(self._bulk_field_initial(field_name))

    def _set_bulk_hint(self, widget, field_name: str) -> None:
        if not self._is_bulk_edit:
            return
        tips = []
        if self._is_bulk_locked_field(field_name):
            tips.append("This field is view-only during bulk edit.")
        if self._bulk_field_is_mixed(field_name):
            tips.append(self.BULK_MIXED_TOOLTIP)
        if tips:
            widget.setToolTip(" ".join(tips))

    def _configure_text_field(
        self,
        widget: QLineEdit,
        field_name: str,
        single_value,
        *,
        read_only: bool = False,
        lock_in_bulk: bool = False,
        track_changes: bool = True,
    ) -> None:
        widget.setText(self._display_value_for_field(field_name, single_value))
        widget.setReadOnly(read_only or lock_in_bulk or self._is_bulk_locked_field(field_name))
        self._set_bulk_hint(widget, field_name)
        if self._is_bulk_edit and track_changes and not lock_in_bulk:
            widget.textChanged.connect(
                lambda _text, name=field_name: self._mark_bulk_field_modified(name)
            )
            if not widget.isReadOnly():
                self._register_bulk_focus_target(widget, field_name)

    def _configure_combo_field(self, combo: QComboBox, field_name: str, single_value) -> None:
        combo.setCurrentText(self._display_value_for_field(field_name, single_value))
        self._set_bulk_hint(combo, field_name)
        if self._is_bulk_edit:
            combo.currentTextChanged.connect(
                lambda _text, name=field_name: self._mark_bulk_field_modified(name)
            )
            line_edit = combo.lineEdit()
            if line_edit is not None:
                self._set_bulk_hint(line_edit, field_name)
                self._register_bulk_focus_target(line_edit, field_name)

    def _create_bulk_note(self, field_name: str, text: str) -> QLabel | None:
        if not self._is_bulk_edit or not self._bulk_field_is_mixed(field_name):
            return None
        label = QLabel(text)
        label.setWordWrap(True)
        return label

    def eventFilter(self, source, event):
        if (
            self._is_bulk_edit
            and event.type() == QEvent.FocusIn
            and source in self._bulk_focus_targets
        ):
            field_name = self._bulk_focus_targets[source]
            if (
                self._bulk_field_is_mixed(field_name)
                and not self._bulk_field_modified(field_name)
                and hasattr(source, "text")
                and source.text() == self.BULK_MIXED_TEXT
                and hasattr(source, "selectAll")
            ):
                QTimer.singleShot(0, source.selectAll)
        return super().eventFilter(source, event)

    def _choose_track_media(self, media_key: str, line_edit: QLineEdit, *, clear_attr: str) -> None:
        path = self.parent._browse_track_media_file(media_key, parent_widget=self)
        if path:
            setattr(self, clear_attr, False)
            line_edit.setText(path)
            if media_key == "audio_file":
                self.parent._refresh_line_edit_lossy_audio_warning(line_edit)
                self.parent._apply_audio_duration_to_widgets(
                    path,
                    hours_widget=self.len_h,
                    minutes_widget=self.len_m,
                    seconds_widget=self.len_s,
                )

    def _set_track_length_from_saved_audio(self) -> None:
        if self._is_bulk_edit:
            return
        track_service = getattr(self.parent, "track_service", None)
        if track_service is None:
            QMessageBox.warning(self, "Track Length", "Open a profile before reading saved audio.")
            return
        try:
            source_handle = track_service.resolve_media_source(self.track_id, "audio_file")
        except FileNotFoundError:
            QMessageBox.warning(
                self,
                "Track Length",
                "This track does not have a saved audio file to read.",
            )
            return
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Track Length",
                f"Could not open the saved audio file:\n{exc}",
            )
            return

        try:
            with source_handle.materialize_path() as source_path:
                duration_seconds = track_service.derive_audio_duration_seconds(source_path)
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Track Length",
                f"Could not read the saved audio file:\n{exc}",
            )
            return
        if duration_seconds is None:
            QMessageBox.warning(
                self,
                "Track Length",
                "Could not read a duration from the saved audio file.",
            )
            return

        self.parent._set_track_length_widgets(
            self.len_h,
            self.len_m,
            self.len_s,
            int(duration_seconds),
        )
        status_bar = self.parent.statusBar() if hasattr(self.parent, "statusBar") else None
        if status_bar is not None:
            status_bar.showMessage(
                f"Track length set from saved audio: {seconds_to_hms(int(duration_seconds))}",
                4000,
            )

    def _clear_track_media(self, line_edit: QLineEdit, *, clear_attr: str) -> None:
        setattr(self, clear_attr, True)
        line_edit.clear()
        self.parent._refresh_line_edit_lossy_audio_warning(line_edit)

    # --- Copy helpers ---
    def _copy_isrc_iso(self):
        txt = (self.isrc_field.text() or "").strip()
        iso = to_iso_isrc(txt) or txt
        QApplication.clipboard().setText(iso)

    def _copy_isrc_compact(self):
        txt = (self.isrc_field.text() or "").strip()
        compact = to_compact_isrc(txt)
        QApplication.clipboard().setText(compact or normalize_isrc(txt))

    def _copy_iswc_iso(self):
        txt = (self.iswc.text() or "").strip()
        iso = to_iso_iswc(txt) or txt
        QApplication.clipboard().setText(iso)

    def _copy_iswc_compact(self):
        txt = (self.iswc.text() or "").strip()
        compact = normalize_iswc(txt)
        QApplication.clipboard().setText(compact)

    def _open_gs1_metadata(self):
        try:
            dlg = GS1MetadataDialog(
                app=self.parent,
                track_id=self.track_id,
                batch_track_ids=list(self.batch_track_ids),
                parent=self,
            )
        except ValueError as exc:
            QMessageBox.warning(self, "GS1 Metadata", str(exc))
            return
        dlg.exec()

    def _bulk_field_should_apply(self, field_name: str, final_value) -> bool:
        if self._is_bulk_locked_field(field_name):
            return False
        return should_apply_bulk_change(
            mixed=self._bulk_field_is_mixed(field_name),
            modified=self._bulk_field_modified(field_name),
            initial_value=self._bulk_field_initial(field_name),
            final_value=final_value,
        )

    def _bulk_media_should_apply(
        self, field_name: str, final_path: str, *, clear_attr: str
    ) -> bool:
        if self._is_bulk_locked_field(field_name):
            return False
        clear_requested = bool(getattr(self, clear_attr) and not final_path)
        if not self._is_bulk_edit:
            return bool(clear_requested or final_path)
        if not self._bulk_field_modified(field_name) and not clear_requested:
            return False
        if self._bulk_field_is_mixed(field_name):
            return True
        initial_path = self._display_value(self._bulk_field_initial(field_name))
        if clear_requested:
            return True
        return (final_path or "") != initial_path

    def _single_edit_album_field_updates(
        self,
        before_snapshot: TrackSnapshot,
        *,
        artist_name: str,
        album_title: str | None,
        release_date: str | None,
        upc: str | None,
        genre: str | None,
        catalog_number: str | None,
    ) -> dict[str, object]:
        updates: dict[str, object] = {}
        if artist_name != before_snapshot.artist_name:
            updates["artist_name"] = artist_name
        if album_title != before_snapshot.album_title:
            updates["album_title"] = album_title
        if release_date != before_snapshot.release_date:
            updates["release_date"] = release_date
        if upc != before_snapshot.upc:
            updates["upc"] = upc
        if genre != before_snapshot.genre:
            updates["genre"] = genre
        if catalog_number != before_snapshot.catalog_number:
            updates["catalog_number"] = catalog_number
        return updates

    def _single_edit_album_art_changed(self, album_art_source_path: str | None) -> bool:
        clear_requested = bool(self._clear_album_art and not album_art_source_path)
        return bool(clear_requested or album_art_source_path)

    def _album_art_upload_block_message(self, track_ids: list[int]) -> str | None:
        track_service = getattr(self.parent, "track_service", None)
        if track_service is None:
            return None
        messages: list[str] = []
        seen: set[str] = set()
        for track_id in track_ids:
            message = track_service.album_art_replacement_message(track_id)
            if not message or message in seen:
                continue
            seen.add(message)
            messages.append(message)
        if not messages:
            return None
        if len(messages) == 1:
            return messages[0]
        return "Album art cannot be replaced for some selected tracks:\n- " + "\n- ".join(
            messages[:6]
        )

    def _display_album_shared_field_names(self, field_names: list[str]) -> list[str]:
        labels: list[str] = []
        for field_name in field_names:
            label = self.SINGLE_EDIT_ALBUM_SHARED_FIELDS.get(field_name)
            if label and label not in labels:
                labels.append(label)
        return labels

    @staticmethod
    def _album_art_update_group_key(payload: TrackUpdatePayload) -> tuple[str, object]:
        album_title = str(payload.album_title or "").strip()
        if album_title and album_title.casefold() != "single":
            return ("album", album_title.casefold())
        return ("track", int(payload.track_id))

    def _deduplicate_bulk_album_art_updates(
        self,
        update_payloads: list[TrackUpdatePayload],
    ) -> None:
        seen_group_keys: set[tuple[str, object]] = set()
        for payload in update_payloads:
            if not payload.album_art_source_path:
                continue
            group_key = self._album_art_update_group_key(payload)
            if group_key in seen_group_keys:
                payload.album_art_source_path = None
                payload.album_art_storage_mode = None
                continue
            seen_group_keys.add(group_key)

    def save_changes(self):
        if self._is_bulk_edit:
            self._save_bulk_changes()
            return
        self._save_single_changes()

    def _save_single_changes(self):
        new_isrc_raw = (self.isrc_field.text() or "").strip()
        new_iswc_raw = (
            self.iswc.currentText() if hasattr(self.iswc, "currentText") else self.iswc.text()
        ).strip()
        new_upc_raw = (
            self.upc.currentText() if hasattr(self.upc, "currentText") else self.upc.text()
        ).strip()
        new_genre = (
            self.genre.currentText() if hasattr(self.genre, "currentText") else self.genre.text()
        ).strip()
        new_track_title = (self.track_title.text() or "").strip()
        new_artist_name = self.artist_name.currentText().strip()
        new_album_title = self.album_title.currentText().strip() or None
        new_track_number = int(self.track_number.value() or 0)
        new_release_date = self.release_date.selectedDate().toString("yyyy-MM-dd")
        new_catalog_number = (
            self.catalog_number.currentText()
            if hasattr(self.catalog_number, "currentText")
            else self.catalog_number.text()
        ).strip() or None
        new_buma_work_number = (
            self.snapshot.buma_work_number
            if getattr(self, "_buma_work_number_managed_by_work", False)
            else (self.buma_work_number.text().strip() or None)
        )
        new_additional_artist = self.parent._parse_additional_artists(
            (
                self.additional_artist.currentText()
                if hasattr(self.additional_artist, "currentText")
                else self.additional_artist.text()
            ).strip()
        )
        selected_artist_name, selected_artist_party_id = self.parent._resolve_artist_party_choice(
            self.artist_name
        )
        resolved_artist_name, _artist_party_id = self.parent._resolve_party_backed_artist_name(
            selected_artist_name or new_artist_name,
            selected_party_id=selected_artist_party_id,
            cursor=self.parent.cursor,
        )
        resolved_additional_artists = self.parent._resolve_party_backed_additional_artist_names(
            new_additional_artist,
            cursor=self.parent.cursor,
        )
        new_artist_name = resolved_artist_name
        new_additional_artist = resolved_additional_artists
        self.artist_name.setCurrentText(resolved_artist_name)
        self.additional_artist.setCurrentText(", ".join(resolved_additional_artists))

        iso_isrc = ""
        if new_isrc_raw:
            iso_isrc = to_iso_isrc(new_isrc_raw)
            comp = to_compact_isrc(iso_isrc)
            if not comp or not is_valid_isrc_compact_or_iso(iso_isrc):
                QMessageBox.warning(
                    self, "Invalid ISRC", "ISRC must look like CCXXXYYNNNNN or CC-XXX-YY-NNNNN."
                )
                return

        iso_iswc = None
        if new_iswc_raw:
            iso_iswc = to_iso_iswc(new_iswc_raw)
            if not iso_iswc or not is_valid_iswc_any(iso_iswc):
                QMessageBox.warning(
                    self,
                    "Invalid ISWC",
                    "ISWC must be like T-123.456.789-0 or T1234567890 (checksum 0–9 or X), or leave empty.",
                )
                return

        if is_blank(self.track_title.text()) or is_blank(new_artist_name):
            QMessageBox.warning(self, "Missing data", "Track Title and Artist are required.")
            return

        if new_upc_raw and not valid_upc_ean(new_upc_raw):
            QMessageBox.warning(
                self, "Invalid UPC/EAN", "UPC/EAN must be 12 or 13 digits (or leave empty)."
            )
            return

        try:
            parent = self.parentWidget()
            if parent is None:
                QMessageBox.critical(self, "Update Error", "No parent window set.")
                return

            row_id = int(self.track_id)
            before_snapshot = parent.track_service.fetch_track_snapshot(row_id)
            if before_snapshot is None:
                QMessageBox.warning(self, "Update Error", "Could not load the selected track.")
                return

            if iso_isrc and parent.is_isrc_taken_normalized(iso_isrc, exclude_track_id=row_id):
                QMessageBox.critical(
                    self, "Duplicate ISRC", "Another record already uses this ISRC."
                )
                return

            parent._warn_duplicate_track_numbers(
                album_title=new_album_title,
                planned_rows=[(new_track_number, new_track_title)],
                exclude_track_ids=[row_id],
                parent_widget=self,
                title="Duplicate Track Number",
                track_service=parent.track_service,
                cursor=parent.cursor,
            )

            audio_source_path = (self.audio_file.text() or "").strip()
            album_art_source_path = (self.album_art.text() or "").strip()
            if audio_source_path == self._existing_audio_display_path:
                audio_source_path = None
            if album_art_source_path == self._existing_album_art_display_path:
                album_art_source_path = None
            if audio_source_path and not parent._confirm_lossy_primary_audio_selection(
                [audio_source_path],
                title="Update Track Media",
                action_label="Saving these changes",
            ):
                return
            if album_art_source_path:
                album_art_block_message = self._album_art_upload_block_message([row_id])
                if album_art_block_message:
                    QMessageBox.warning(
                        self,
                        "Album Art Managed Elsewhere",
                        album_art_block_message,
                    )
                    return
            media_modes = parent._choose_track_media_storage_modes(
                audio_source_path=audio_source_path,
                album_art_source_path=album_art_source_path,
                title="Update Track Media",
            )
            if media_modes is None:
                return
            audio_storage_mode, album_art_storage_mode = media_modes
            source_payload = TrackUpdatePayload(
                track_id=row_id,
                isrc=iso_isrc,
                track_title=new_track_title,
                artist_name=new_artist_name,
                additional_artists=new_additional_artist,
                album_title=new_album_title,
                release_date=new_release_date,
                track_length_sec=hms_to_seconds(
                    self.len_h.value(), self.len_m.value(), self.len_s.value()
                ),
                iswc=(iso_iswc or None),
                upc=(new_upc_raw or None),
                genre=(new_genre or None),
                track_number=new_track_number,
                catalog_number=new_catalog_number,
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
                buma_work_number=new_buma_work_number,
                audio_file_source_path=audio_source_path,
                audio_file_storage_mode=audio_storage_mode,
                album_art_source_path=album_art_source_path,
                album_art_storage_mode=album_art_storage_mode,
                clear_audio_file=bool(self._clear_audio_file and not audio_source_path),
                clear_album_art=bool(self._clear_album_art and not album_art_source_path),
            )

            album_field_updates = self._single_edit_album_field_updates(
                before_snapshot,
                artist_name=new_artist_name,
                album_title=new_album_title,
                release_date=new_release_date,
                upc=(new_upc_raw or None),
                genre=(new_genre or None),
                catalog_number=new_catalog_number,
            )
            album_art_changed = self._single_edit_album_art_changed(album_art_source_path)
            album_group_track_ids = parent.track_service.list_album_group_track_ids(row_id)
            propagated_track_ids = [
                track_id for track_id in album_group_track_ids if track_id != row_id
            ]
            album_shared_fields_changed = list(album_field_updates.keys())
            propagated_field_labels: list[str] = []
            if album_art_changed:
                album_shared_fields_changed.append("album_art")
            propagated_mode = bool(propagated_track_ids and album_shared_fields_changed)
            needs_peer_album_metadata_update = bool(propagated_track_ids and album_field_updates)

            if propagated_mode:
                propagated_field_labels = self._display_album_shared_field_names(
                    album_shared_fields_changed
                )

            cleanup_artist_names, cleanup_album_titles = parent._collect_catalog_cleanup_targets(
                artist_name=new_artist_name,
                additional_artists=new_additional_artist,
                album_title=new_album_title,
            )
            profile_name = parent._current_profile_name()
            refresh_request = parent._capture_catalog_refresh_request(focus_id=row_id)
            action_label = (
                f"Update Album Metadata: {new_track_title}"
                if propagated_mode
                else f"Update Track: {new_track_title}"
            )
            action_type = "track.update_album_metadata" if propagated_mode else "track.update"
            history_payload = (
                {
                    "track_id": row_id,
                    "track_title": new_track_title,
                    "propagated_track_ids": propagated_track_ids,
                    "propagated_fields": propagated_field_labels,
                }
                if propagated_mode
                else {
                    "track_id": row_id,
                    "track_title": new_track_title,
                    "cleanup_artist_names": cleanup_artist_names,
                    "cleanup_album_titles": cleanup_album_titles,
                }
            )

            def _worker(bundle, ctx):
                total_steps = 3 if needs_peer_album_metadata_update else 2

                def _mutation():
                    with bundle.conn:
                        cur = bundle.conn.cursor()
                        ctx.report_progress(0, total_steps, message="Saving track changes...")
                        bundle.track_service.update_track(source_payload, cursor=cur)
                        sync_track_ids = [row_id]
                        if propagated_mode:
                            sync_track_ids = [row_id, *propagated_track_ids]
                        if needs_peer_album_metadata_update:
                            ctx.report_progress(
                                1, total_steps, message="Propagating shared album fields..."
                            )
                            bundle.track_service.apply_album_metadata_to_tracks(
                                propagated_track_ids,
                                field_updates=album_field_updates,
                                cursor=cur,
                            )
                        ctx.report_progress(
                            total_steps - 1, total_steps, message="Synchronizing release records..."
                        )
                        parent._sync_releases_for_tracks(
                            sync_track_ids,
                            cursor=cur,
                            track_service=bundle.track_service,
                            release_service=bundle.release_service,
                            profile_name=profile_name,
                        )
                    ctx.report_progress(total_steps, total_steps, message="Track update complete.")
                    return {
                        "focus_id": row_id,
                        "propagated": propagated_mode,
                        "propagated_track_ids": list(propagated_track_ids),
                        "propagated_fields": list(propagated_field_labels),
                    }

                result_payload = run_snapshot_history_action(
                    history_manager=bundle.history_manager,
                    action_label=action_label,
                    action_type=action_type,
                    entity_type="Track",
                    entity_id=row_id,
                    payload=history_payload,
                    mutation=_mutation,
                    progress_callback=ctx.report_progress,
                    post_mutation_progress=(48, "Capturing track-update history snapshot..."),
                    record_progress=(56, "Recording track-update history..."),
                    logger=parent.logger,
                )
                ctx.report_progress(
                    value=60,
                    maximum=100,
                    message="Loading refreshed catalog rows, media badges, and lookup values...",
                )
                result_payload["dataset"] = parent._load_catalog_ui_dataset_from_bundle(
                    bundle,
                    ctx,
                    progress_start=62,
                    progress_end=88,
                )
                return result_payload

            def _before_cleanup(result: dict[str, object], ui_progress) -> None:
                try:
                    parent.conn.commit()
                except Exception:
                    pass
                parent._sync_application_isrc_registry()
                parent._apply_catalog_refresh_request(
                    dict(result.get("dataset") or {}),
                    refresh_request,
                    progress_callback=parent._scaled_ui_progress_callback(
                        ui_progress,
                        start=90,
                        end=98,
                    ),
                )
                parent._advance_task_ui_progress(
                    ui_progress,
                    value=100,
                    message="Track changes saved and catalog UI is ready.",
                )

            def _after_cleanup(result: dict[str, object]) -> None:
                if propagated_mode:
                    parent._log_event(
                        "track.update",
                        "Track updated with album-level propagation",
                        track_id=row_id,
                        isrc=iso_isrc,
                        track_title=new_track_title,
                        propagated_track_ids=propagated_track_ids,
                        propagated_fields=propagated_field_labels,
                    )
                    parent._audit(
                        "UPDATE",
                        "Track",
                        ref_id=row_id,
                        details=(
                            f"isrc={iso_isrc}; "
                            f"propagated_track_ids={','.join(str(track_id) for track_id in propagated_track_ids)}; "
                            f"propagated_fields={','.join(propagated_field_labels)}"
                        ),
                    )
                else:
                    parent._log_event(
                        "track.update",
                        "Track updated",
                        track_id=row_id,
                        isrc=iso_isrc,
                        track_title=new_track_title,
                    )
                    parent._audit("UPDATE", "Track", ref_id=row_id, details=f"isrc={iso_isrc}")
                parent._audit_commit()
                self.accept()

            parent._submit_background_bundle_task(
                title="Update Track",
                description="Saving track changes...",
                task_fn=_worker,
                kind="write",
                unique_key=f"track.update.{row_id}",
                owner=self,
                worker_completion_progress=(89, "Finalizing background track update..."),
                on_success_before_cleanup=_before_cleanup,
                on_success_after_cleanup=_after_cleanup,
                on_error=lambda failure: parent._show_background_task_error(
                    "Update Error",
                    failure,
                    user_message="Failed to update record:",
                ),
            )

        except Exception as e:
            parent = self.parentWidget()
            if parent and hasattr(parent, "conn"):
                parent.conn.rollback()
                parent.logger.exception(f"Update failed: {e}")
            QMessageBox.critical(self, "Update Error", f"Failed to update record:\n{e}")

    def _save_bulk_changes(self):
        parent = self.parentWidget()
        if parent is None:
            QMessageBox.critical(self, "Update Error", "No parent window set.")
            return

        new_track_title = (self.track_title.text() or "").strip()
        new_artist_name = self.artist_name.currentText().strip()
        new_additional_artist = self.parent._parse_additional_artists(
            self.additional_artist.currentText().strip()
        )
        if self._bulk_field_should_apply("artist_name", new_artist_name):
            selected_artist_name, selected_artist_party_id = (
                self.parent._resolve_artist_party_choice(self.artist_name)
            )
            new_artist_name, _artist_party_id = self.parent._resolve_party_backed_artist_name(
                selected_artist_name or new_artist_name,
                selected_party_id=selected_artist_party_id,
                cursor=self.parent.cursor,
            )
            self.artist_name.setCurrentText(new_artist_name)
        if self._bulk_field_should_apply("additional_artists", tuple(new_additional_artist)):
            new_additional_artist = self.parent._resolve_party_backed_additional_artist_names(
                new_additional_artist,
                cursor=self.parent.cursor,
            )
            self.additional_artist.setCurrentText(", ".join(new_additional_artist))
        new_album_title = self.album_title.currentText().strip()
        new_genre = self.genre.currentText().strip()
        new_upc_raw = (
            self.upc.currentText() if hasattr(self.upc, "currentText") else self.upc.text()
        ).strip()
        new_catalog_number = (
            self.catalog_number.currentText()
            if hasattr(self.catalog_number, "currentText")
            else self.catalog_number.text()
        ).strip()
        new_buma_work_number = (self.buma_work_number.text() or "").strip()
        new_release_date = self.release_date.selectedDate().toString("yyyy-MM-dd")
        new_track_length_sec = hms_to_seconds(
            self.len_h.value(), self.len_m.value(), self.len_s.value()
        )
        new_audio_path = (self.audio_file.text() or "").strip()
        new_album_art_path = (self.album_art.text() or "").strip()

        apply_track_title = self._bulk_field_should_apply("track_title", new_track_title)
        apply_artist_name = self._bulk_field_should_apply("artist_name", new_artist_name)
        apply_additional_artist = self._bulk_field_should_apply(
            "additional_artists", tuple(new_additional_artist)
        )
        apply_album_title = self._bulk_field_should_apply("album_title", new_album_title)
        apply_genre = self._bulk_field_should_apply("genre", new_genre)
        apply_release_date = self._bulk_field_should_apply("release_date", new_release_date)
        apply_track_length = self._bulk_field_should_apply("track_length_sec", new_track_length_sec)
        apply_upc = self._bulk_field_should_apply("upc", new_upc_raw)
        apply_catalog_number = self._bulk_field_should_apply("catalog_number", new_catalog_number)
        apply_buma_work_number = self._bulk_field_should_apply(
            "buma_work_number", new_buma_work_number
        )
        apply_audio = self._bulk_media_should_apply(
            "audio_file", new_audio_path, clear_attr="_clear_audio_file"
        )
        apply_album_art = self._bulk_media_should_apply(
            "album_art", new_album_art_path, clear_attr="_clear_album_art"
        )

        if apply_track_title and is_blank(new_track_title):
            QMessageBox.warning(
                self, "Missing data", "Track Title cannot be blank when bulk editing."
            )
            return
        if apply_artist_name and is_blank(new_artist_name):
            QMessageBox.warning(self, "Missing data", "Artist cannot be blank when bulk editing.")
            return
        if apply_upc and new_upc_raw and not valid_upc_ean(new_upc_raw):
            QMessageBox.warning(
                self, "Invalid UPC/EAN", "UPC/EAN must be 12 or 13 digits (or leave empty)."
            )
            return
        if apply_album_art and new_album_art_path:
            album_art_block_message = self._album_art_upload_block_message(self.batch_track_ids)
            if album_art_block_message:
                QMessageBox.warning(
                    self,
                    "Album Art Managed Elsewhere",
                    album_art_block_message,
                )
                return

        changed_fields = []
        if apply_track_title:
            changed_fields.append("Track Title")
        if apply_artist_name:
            changed_fields.append("Artist")
        if apply_additional_artist:
            changed_fields.append("Additional Artist(s)")
        if apply_album_title:
            changed_fields.append("Album Title")
        if apply_genre:
            changed_fields.append("Genre")
        if apply_release_date:
            changed_fields.append("Release Date")
        if apply_track_length:
            changed_fields.append("Track Length")
        if apply_upc:
            changed_fields.append("UPC/EAN")
        if apply_catalog_number:
            changed_fields.append("Catalog#")
        if apply_buma_work_number:
            changed_fields.append("BUMA Wnr.")
        if apply_audio:
            changed_fields.append("Audio File")
        if apply_album_art:
            changed_fields.append("Album Art")

        if not changed_fields:
            QMessageBox.information(self, "Bulk Edit", "No editable fields were changed.")
            return

        media_modes = parent._choose_track_media_storage_modes(
            audio_source_path=(
                (new_audio_path or None) if apply_audio and not self._clear_audio_file else None
            ),
            album_art_source_path=(
                (new_album_art_path or None)
                if apply_album_art and not self._clear_album_art
                else None
            ),
            title="Bulk Update Media",
        )
        if media_modes is None:
            return
        bulk_audio_storage_mode, bulk_album_art_storage_mode = media_modes

        profile_name = parent._current_profile_name()
        update_payloads = [
            TrackUpdatePayload(
                track_id=snapshot.track_id,
                isrc=snapshot.isrc,
                track_title=new_track_title if apply_track_title else snapshot.track_title,
                artist_name=new_artist_name if apply_artist_name else snapshot.artist_name,
                additional_artists=(
                    new_additional_artist
                    if apply_additional_artist
                    else list(snapshot.additional_artists)
                ),
                album_title=(
                    (new_album_title or None) if apply_album_title else snapshot.album_title
                ),
                release_date=new_release_date if apply_release_date else snapshot.release_date,
                track_length_sec=(
                    new_track_length_sec
                    if apply_track_length
                    else int(snapshot.track_length_sec or 0)
                ),
                iswc=snapshot.iswc,
                upc=(new_upc_raw or None) if apply_upc else snapshot.upc,
                genre=(new_genre or None) if apply_genre else snapshot.genre,
                catalog_number=(
                    (new_catalog_number or None)
                    if apply_catalog_number
                    else snapshot.catalog_number
                ),
                catalog_number_mode=(
                    (
                        self.catalog_number.identifier_mode()
                        if hasattr(self.catalog_number, "identifier_mode")
                        else None
                    )
                    if apply_catalog_number
                    else snapshot.catalog_number_mode
                ),
                catalog_registry_entry_id=(
                    (
                        self.catalog_number.catalog_registry_entry_id()
                        if hasattr(self.catalog_number, "catalog_registry_entry_id")
                        else None
                    )
                    if apply_catalog_number
                    else snapshot.catalog_registry_entry_id
                ),
                catalog_external_code_identifier_id=(
                    (
                        self.catalog_number.external_code_identifier_id()
                        if hasattr(self.catalog_number, "external_code_identifier_id")
                        else None
                    )
                    if apply_catalog_number
                    else snapshot.catalog_external_code_identifier_id
                ),
                external_catalog_identifier_id=(
                    (
                        self.catalog_number.external_catalog_identifier_id()
                        if hasattr(self.catalog_number, "external_catalog_identifier_id")
                        else None
                    )
                    if apply_catalog_number
                    else snapshot.external_catalog_identifier_id
                ),
                buma_work_number=(
                    (new_buma_work_number or None)
                    if apply_buma_work_number
                    else snapshot.buma_work_number
                ),
                audio_file_source_path=(
                    (new_audio_path or None) if apply_audio and not self._clear_audio_file else None
                ),
                audio_file_storage_mode=(
                    bulk_audio_storage_mode
                    if apply_audio and not self._clear_audio_file and new_audio_path
                    else None
                ),
                album_art_source_path=(
                    (new_album_art_path or None)
                    if apply_album_art and not self._clear_album_art
                    else None
                ),
                album_art_storage_mode=(
                    bulk_album_art_storage_mode
                    if apply_album_art and not self._clear_album_art and new_album_art_path
                    else None
                ),
                clear_audio_file=bool(
                    apply_audio and self._clear_audio_file and not new_audio_path
                ),
                clear_album_art=bool(
                    apply_album_art and self._clear_album_art and not new_album_art_path
                ),
            )
            for snapshot in self._bulk_snapshots
        ]
        self._deduplicate_bulk_album_art_updates(update_payloads)
        refresh_request = parent._capture_catalog_refresh_request(
            focus_id=(self.batch_track_ids[0] if self.batch_track_ids else None)
        )

        def _worker(bundle, ctx):
            total = max(1, len(update_payloads))

            def _mutation():
                with bundle.conn:
                    cur = bundle.conn.cursor()
                    for index, payload in enumerate(update_payloads, start=1):
                        ctx.report_progress(
                            value=index - 1,
                            maximum=total + 1,
                            message=f"Updating track {index} of {total}...",
                        )
                        bundle.track_service.update_track(payload, cursor=cur)
                    ctx.report_progress(
                        value=total,
                        maximum=total + 1,
                        message="Synchronizing release records...",
                    )
                    parent._sync_releases_for_tracks(
                        self.batch_track_ids,
                        cursor=cur,
                        track_service=bundle.track_service,
                        release_service=bundle.release_service,
                        profile_name=profile_name,
                    )
                ctx.report_progress(total + 1, total + 1, message="Bulk update complete.")
                return {"focus_id": self.batch_track_ids[0] if self.batch_track_ids else None}

            result_payload = run_snapshot_history_action(
                history_manager=bundle.history_manager,
                action_label=f"Bulk Edit Tracks ({len(self.batch_track_ids)})",
                action_type="track.bulk_update",
                entity_type="Track",
                entity_id="batch",
                payload={"track_ids": self.batch_track_ids, "fields": changed_fields},
                mutation=_mutation,
                progress_callback=ctx.report_progress,
                post_mutation_progress=(48, "Capturing bulk track history snapshot..."),
                record_progress=(56, "Recording bulk track history..."),
                logger=parent.logger,
            )
            ctx.report_progress(
                value=60,
                maximum=100,
                message="Loading refreshed catalog rows, media badges, and lookup values...",
            )
            result_payload["dataset"] = parent._load_catalog_ui_dataset_from_bundle(
                bundle,
                ctx,
                progress_start=62,
                progress_end=88,
            )
            return result_payload

        def _before_cleanup(result: dict[str, object], ui_progress) -> None:
            try:
                parent.conn.commit()
            except Exception:
                pass
            refresh_payload = dict(refresh_request)
            if result.get("focus_id") is not None:
                refresh_payload["focus_id"] = int(result["focus_id"])
            parent._apply_catalog_refresh_request(
                dict(result.get("dataset") or {}),
                refresh_payload,
                progress_callback=parent._scaled_ui_progress_callback(
                    ui_progress,
                    start=90,
                    end=98,
                ),
            )
            parent._advance_task_ui_progress(
                ui_progress,
                value=100,
                message="Bulk track changes saved and catalog UI is ready.",
            )

        def _after_cleanup(result: dict[str, object]) -> None:
            parent._log_event(
                "track.bulk_update",
                "Bulk updated tracks",
                track_ids=self.batch_track_ids,
                changed_fields=changed_fields,
            )
            parent._audit(
                "UPDATE",
                "Track",
                ref_id="batch",
                details=(
                    f"track_ids={','.join(str(track_id) for track_id in self.batch_track_ids)}; "
                    f"fields={','.join(changed_fields)}"
                ),
            )
            parent._audit_commit()
            self.accept()

        try:
            parent._submit_background_bundle_task(
                title="Bulk Edit",
                description="Applying bulk changes to the selected tracks...",
                task_fn=_worker,
                kind="write",
                unique_key=f"track.bulk_update.{','.join(str(track_id) for track_id in self.batch_track_ids)}",
                owner=self,
                worker_completion_progress=(89, "Finalizing background bulk track update..."),
                on_success_before_cleanup=_before_cleanup,
                on_success_after_cleanup=_after_cleanup,
                on_error=lambda failure: parent._show_background_task_error(
                    "Update Error",
                    failure,
                    user_message="Failed to update selected records:",
                ),
            )
        except Exception as e:
            if hasattr(parent, "conn"):
                parent.conn.rollback()
                parent.logger.exception(f"Bulk update failed: {e}")
            QMessageBox.critical(self, "Update Error", f"Failed to update selected records:\n{e}")

__all__ = ["EditDialog"]

"""Qt dialog for template-driven conversion workflows."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
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
    _create_scrollable_dialog_content,
    _create_standard_section,
)

from .mapping import (
    available_transforms,
    normalize_field_name,
    transform_label,
)
from .models import (
    MAPPING_KIND_CONSTANT,
    MAPPING_KIND_SKIP,
    MAPPING_KIND_SOURCE,
    MAPPING_KIND_UNMAPPED,
    SOURCE_MODE_DATABASE_TRACKS,
    SOURCE_MODE_FILE,
    ConversionMappingEntry,
    ConversionPreview,
)

_MODE_FILE = SOURCE_MODE_FILE
_MODE_DATABASE = SOURCE_MODE_DATABASE_TRACKS
_MAP_TO_UNMAPPED = "__conversion_unmapped__"
_MAP_TO_SKIP = "__conversion_skip__"
_MAP_TO_CONSTANT = "__conversion_constant__"


class ConversionDialog(QDialog):
    """Load a template, inspect a source, and preview faithful export output."""

    def __init__(
        self,
        *,
        service,
        settings,
        template_store_service=None,
        export_callback,
        exports_dir: str | Path,
        profile_available: bool,
        default_database_track_ids_provider=None,
        track_choices_provider=None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.settings = settings
        self.template_store_service = template_store_service
        self.export_callback = export_callback
        self.exports_dir = Path(exports_dir)
        self.profile_available = bool(profile_available)
        self.default_database_track_ids_provider = default_database_track_ids_provider
        self.track_choices_provider = track_choices_provider

        self.template_profile = None
        self.source_profile = None
        self._file_source_profile = None
        self._database_source_profile = None
        self.session = None
        self.preview: ConversionPreview | None = None
        self._template_path = ""
        self._source_path = ""
        self._source_included_indices: set[int] = set()
        self._database_override_track_ids: list[int] = []
        self._database_override_active = False
        self._available_track_choices: list[TrackChoice] = []
        self._track_title_by_id: dict[int, str] = {}
        self._source_table_sync = False
        self._mapping_table_sync = False
        self._pending_saved_template_mapping_payload = ""

        self.setWindowTitle("Template Conversion")
        self.resize(1220, 860)
        self.setMinimumSize(1060, 760)
        _apply_standard_dialog_chrome(self, "conversionDialog")

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)
        self.main_scroll_area, self.scroll_content, content_layout = (
            _create_scrollable_dialog_content(self)
        )
        content_layout.setSpacing(16)
        root.addWidget(self.main_scroll_area, 1)
        _add_standard_dialog_header(
            content_layout,
            self,
            title="Template Conversion",
            subtitle=(
                "Load a rigid target template, inspect either a source file or current-profile track data, "
                "review the mapping, and export a new file that preserves the template structure."
            ),
            help_topic_id="conversion",
        )

        setup_box, setup_layout = _create_standard_section(
            self,
            "Setup",
            "Choose the target template and the source mode before reviewing the mapped output preview.",
        )
        setup_grid = QGridLayout()
        setup_grid.setContentsMargins(0, 0, 0, 0)
        setup_grid.setHorizontalSpacing(14)
        setup_grid.setVerticalSpacing(12)
        setup_grid.setColumnStretch(1, 1)
        setup_layout.addLayout(setup_grid)

        setup_grid.addWidget(QLabel("Target template"), 0, 0)
        template_row = QHBoxLayout()
        template_row.setContentsMargins(0, 0, 0, 0)
        template_row.setSpacing(8)
        self.template_path_label = QLabel("No template selected.")
        self.template_path_label.setWordWrap(True)
        template_row.addWidget(self.template_path_label, 1)
        self.choose_template_button = QPushButton("Choose Template…", self)
        self.choose_template_button.setMinimumWidth(154)
        self.choose_template_button.clicked.connect(self._choose_template)
        template_row.addWidget(self.choose_template_button)
        setup_grid.addLayout(template_row, 0, 1)

        self.saved_template_load_row = QWidget(self)
        saved_template_load_layout = QHBoxLayout(self.saved_template_load_row)
        saved_template_load_layout.setContentsMargins(0, 0, 0, 0)
        saved_template_load_layout.setSpacing(8)
        self.saved_template_combo = QComboBox(self)
        self.saved_template_combo.setMinimumWidth(260)
        saved_template_load_layout.addWidget(self.saved_template_combo, 1)
        self.load_saved_template_button = QPushButton("Load Saved", self)
        self.load_saved_template_button.setMinimumWidth(120)
        self.load_saved_template_button.clicked.connect(self._load_selected_saved_template)
        saved_template_load_layout.addWidget(self.load_saved_template_button)
        self.saved_template_load_label = QLabel("Saved templates")
        setup_grid.addWidget(self.saved_template_load_label, 1, 0)
        setup_grid.addWidget(self.saved_template_load_row, 1, 1)

        self.saved_template_save_row = QWidget(self)
        saved_template_save_layout = QHBoxLayout(self.saved_template_save_row)
        saved_template_save_layout.setContentsMargins(0, 0, 0, 0)
        saved_template_save_layout.setSpacing(8)
        self.saved_template_name_edit = QLineEdit(self)
        self.saved_template_name_edit.setPlaceholderText("Profile template name")
        self.saved_template_name_edit.setMinimumWidth(220)
        saved_template_save_layout.addWidget(self.saved_template_name_edit, 1)
        self.include_mapping_in_saved_template_checkbox = QCheckBox("Include current mapping", self)
        self.include_mapping_in_saved_template_checkbox.setChecked(True)
        saved_template_save_layout.addWidget(self.include_mapping_in_saved_template_checkbox)
        self.save_template_to_profile_button = QPushButton("Save To Profile", self)
        self.save_template_to_profile_button.setMinimumWidth(140)
        self.save_template_to_profile_button.clicked.connect(self._save_template_to_profile)
        saved_template_save_layout.addWidget(self.save_template_to_profile_button)
        self.saved_template_save_label = QLabel("Save template")
        setup_grid.addWidget(self.saved_template_save_label, 2, 0)
        setup_grid.addWidget(self.saved_template_save_row, 2, 1)

        setup_grid.addWidget(QLabel("Source mode"), 3, 0)
        source_mode_row = QHBoxLayout()
        source_mode_row.setContentsMargins(0, 0, 0, 0)
        source_mode_row.setSpacing(8)
        self.source_mode_combo = QComboBox(self)
        self.source_mode_combo.setMinimumWidth(220)
        self.source_mode_combo.addItem("Source File", _MODE_FILE)
        self.source_mode_combo.addItem("Current Profile Tracks", _MODE_DATABASE)
        model_item = self.source_mode_combo.model().item(1)
        if model_item is not None:
            model_item.setEnabled(self.profile_available)
        self.source_mode_combo.currentIndexChanged.connect(self._on_source_mode_changed)
        source_mode_row.addWidget(self.source_mode_combo)
        self.source_mode_hint = QLabel("")
        self.source_mode_hint.setWordWrap(True)
        self.source_mode_hint.setProperty("role", "secondary")
        source_mode_row.addWidget(self.source_mode_hint, 1)
        setup_grid.addLayout(source_mode_row, 3, 1)

        self.source_file_row = QWidget(self)
        source_file_layout = QHBoxLayout(self.source_file_row)
        source_file_layout.setContentsMargins(0, 0, 0, 0)
        source_file_layout.setSpacing(8)
        self.source_path_label = QLabel("No source file selected.")
        self.source_path_label.setWordWrap(True)
        source_file_layout.addWidget(self.source_path_label, 1)
        self.choose_source_button = QPushButton("Choose Source File…", self)
        self.choose_source_button.setMinimumWidth(154)
        self.choose_source_button.clicked.connect(self._choose_source_file)
        source_file_layout.addWidget(self.choose_source_button)
        setup_grid.addWidget(QLabel("Source file"), 4, 0)
        setup_grid.addWidget(self.source_file_row, 4, 1)

        self.csv_controls_row = QWidget(self)
        csv_layout = QHBoxLayout(self.csv_controls_row)
        csv_layout.setContentsMargins(0, 0, 0, 0)
        csv_layout.setSpacing(8)
        csv_layout.addWidget(QLabel("CSV delimiter"))
        self.csv_delimiter_combo = QComboBox(self)
        self.csv_delimiter_combo.setMinimumWidth(150)
        self.csv_delimiter_combo.addItem("Auto detect", "auto")
        self.csv_delimiter_combo.addItem("Comma (,)", ",")
        self.csv_delimiter_combo.addItem("Semicolon (;)", ";")
        self.csv_delimiter_combo.addItem("Tab", "\t")
        self.csv_delimiter_combo.addItem("Pipe (|)", "|")
        self.csv_delimiter_combo.addItem("Custom delimiter", "custom")
        self.csv_delimiter_combo.currentIndexChanged.connect(self._on_csv_delimiter_changed)
        csv_layout.addWidget(self.csv_delimiter_combo)
        self.csv_custom_delimiter_edit = QLineEdit(self)
        self.csv_custom_delimiter_edit.setPlaceholderText("One character")
        self.csv_custom_delimiter_edit.setMaximumWidth(120)
        self.csv_custom_delimiter_edit.textChanged.connect(self._on_csv_delimiter_changed)
        csv_layout.addWidget(self.csv_custom_delimiter_edit)
        self.csv_error_label = QLabel("")
        self.csv_error_label.setWordWrap(True)
        self.csv_error_label.setProperty("role", "secondary")
        csv_layout.addWidget(self.csv_error_label, 1)
        setup_grid.addWidget(QLabel("CSV options"), 5, 0)
        setup_grid.addWidget(self.csv_controls_row, 5, 1)

        self.database_scope_box = QWidget(self)
        database_scope_layout = QVBoxLayout(self.database_scope_box)
        database_scope_layout.setContentsMargins(0, 0, 0, 0)
        database_scope_layout.setSpacing(8)
        self.selection_banner = SelectionScopeBanner(
            chooser_label="Choose Tracks",
            parent=self.database_scope_box,
        )
        self.selection_banner.use_current_button.clicked.connect(
            self._use_current_database_selection
        )
        self.selection_banner.choose_button.clicked.connect(self._choose_database_tracks)
        self.selection_banner.clear_override_button.clicked.connect(self._clear_database_override)
        database_scope_layout.addWidget(self.selection_banner)
        setup_grid.addWidget(QLabel("Track selection"), 6, 0)
        setup_grid.addWidget(self.database_scope_box, 6, 1)

        self.template_scope_row = QWidget(self)
        template_scope_layout = QHBoxLayout(self.template_scope_row)
        template_scope_layout.setContentsMargins(0, 0, 0, 0)
        template_scope_layout.setSpacing(8)
        template_scope_layout.addWidget(QLabel("Template scope"))
        self.template_scope_combo = QComboBox(self)
        self.template_scope_combo.currentIndexChanged.connect(self._on_template_scope_changed)
        template_scope_layout.addWidget(self.template_scope_combo, 1)
        setup_grid.addWidget(QLabel("Template scope"), 7, 0)
        setup_grid.addWidget(self.template_scope_row, 7, 1)

        self.source_scope_row = QWidget(self)
        source_scope_layout = QHBoxLayout(self.source_scope_row)
        source_scope_layout.setContentsMargins(0, 0, 0, 0)
        source_scope_layout.setSpacing(8)
        source_scope_layout.addWidget(QLabel("Source scope"))
        self.source_scope_combo = QComboBox(self)
        self.source_scope_combo.currentIndexChanged.connect(self._on_source_scope_changed)
        source_scope_layout.addWidget(self.source_scope_combo, 1)
        setup_grid.addWidget(QLabel("Source scope"), 8, 0)
        setup_grid.addWidget(self.source_scope_row, 8, 1)

        content_layout.addWidget(setup_box)

        self.content_tabs = QTabWidget(self)
        self.content_tabs.setObjectName("conversionTabs")
        self.content_tabs.setDocumentMode(True)
        self.content_tabs.setMinimumHeight(500)
        content_layout.addWidget(self.content_tabs, 1)

        self.template_page = QWidget(self.content_tabs)
        self.template_page.setProperty("role", "workspaceCanvas")
        self.source_page = QWidget(self.content_tabs)
        self.source_page.setProperty("role", "workspaceCanvas")
        self.mapping_page = QWidget(self.content_tabs)
        self.mapping_page.setProperty("role", "workspaceCanvas")
        self.output_page = QWidget(self.content_tabs)
        self.output_page.setProperty("role", "workspaceCanvas")
        self.content_tabs.addTab(self.template_page, "Template")
        self.content_tabs.addTab(self.source_page, "Source")
        self.content_tabs.addTab(self.mapping_page, "Mapping")
        self.content_tabs.addTab(self.output_page, "Output Preview")

        template_layout = QVBoxLayout(self.template_page)
        template_layout.setContentsMargins(0, 0, 0, 0)
        template_layout.setSpacing(10)
        self.template_summary_label = QLabel("Choose a target template to inspect its structure.")
        self.template_summary_label.setWordWrap(True)
        template_layout.addWidget(self.template_summary_label)
        self.template_fields_table = QTableWidget(0, 3, self)
        self.template_fields_table.setObjectName("conversionTemplateFieldsTable")
        self.template_fields_table.setHorizontalHeaderLabels(["Field", "Location", "Required"])
        self.template_fields_table.verticalHeader().setVisible(False)
        self.template_fields_table.horizontalHeader().setStretchLastSection(True)
        self.template_fields_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.template_fields_table.setMinimumHeight(240)
        template_layout.addWidget(self.template_fields_table, 1)

        source_layout = QVBoxLayout(self.source_page)
        source_layout.setContentsMargins(0, 0, 0, 0)
        source_layout.setSpacing(10)
        self.source_summary_label = QLabel("Choose a source file or current-profile tracks.")
        self.source_summary_label.setWordWrap(True)
        source_layout.addWidget(self.source_summary_label)
        self.source_table = QTableWidget(0, 1, self)
        self.source_table.setObjectName("conversionSourceTable")
        self.source_table.verticalHeader().setVisible(False)
        self.source_table.horizontalHeader().setStretchLastSection(True)
        self.source_table.itemChanged.connect(self._on_source_table_item_changed)
        self.source_table.setMinimumHeight(260)
        source_layout.addWidget(self.source_table, 1)

        mapping_layout = QVBoxLayout(self.mapping_page)
        mapping_layout.setContentsMargins(0, 0, 0, 0)
        mapping_layout.setSpacing(10)
        preset_row = QHBoxLayout()
        preset_row.setContentsMargins(0, 0, 0, 0)
        preset_row.setSpacing(10)
        preset_row.addWidget(QLabel("Mapping preset"))
        self.preset_combo = QComboBox(self)
        self.preset_combo.setMinimumWidth(260)
        preset_row.addWidget(self.preset_combo, 1)
        load_preset_button = QPushButton("Load Preset", self)
        load_preset_button.setMinimumWidth(112)
        load_preset_button.clicked.connect(self._load_selected_preset)
        preset_row.addWidget(load_preset_button)
        self.preset_name_edit = QLineEdit(self)
        self.preset_name_edit.setPlaceholderText("Preset name")
        self.preset_name_edit.setMinimumWidth(170)
        preset_row.addWidget(self.preset_name_edit)
        save_preset_button = QPushButton("Save Preset", self)
        save_preset_button.setMinimumWidth(112)
        save_preset_button.clicked.connect(self._save_current_preset)
        preset_row.addWidget(save_preset_button)
        auto_match_button = QPushButton("Auto Match", self)
        auto_match_button.setMinimumWidth(104)
        auto_match_button.clicked.connect(self._apply_suggested_mapping)
        preset_row.addWidget(auto_match_button)
        mapping_layout.addLayout(preset_row)
        self.mapping_table = QTableWidget(0, 7, self)
        self.mapping_table.setObjectName("conversionMappingTable")
        self.mapping_table.setHorizontalHeaderLabels(
            ["Target", "Required", "Map To", "Constant", "Transform", "Sample", "Status"]
        )
        self.mapping_table.verticalHeader().setVisible(False)
        self.mapping_table.horizontalHeader().setStretchLastSection(True)
        self.mapping_table.setMinimumHeight(320)
        self.mapping_table.setColumnWidth(0, 220)
        self.mapping_table.setColumnWidth(1, 96)
        self.mapping_table.setColumnWidth(2, 180)
        self.mapping_table.setColumnWidth(3, 190)
        self.mapping_table.setColumnWidth(4, 150)
        self.mapping_table.setColumnWidth(5, 220)
        mapping_layout.addWidget(self.mapping_table, 1)

        output_layout = QVBoxLayout(self.output_page)
        output_layout.setContentsMargins(0, 0, 0, 0)
        output_layout.setSpacing(10)
        self.output_status_label = QLabel("Load a template and source to build a preview.")
        self.output_status_label.setWordWrap(True)
        output_layout.addWidget(self.output_status_label)
        self.output_table = QTableWidget(0, 0, self)
        self.output_table.setObjectName("conversionOutputTable")
        self.output_table.verticalHeader().setVisible(False)
        self.output_table.horizontalHeader().setStretchLastSection(True)
        self.output_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.output_table.setMinimumHeight(220)
        output_layout.addWidget(self.output_table, 1)
        xml_label = QLabel("Rendered XML")
        output_layout.addWidget(xml_label)
        self.xml_preview_edit = QPlainTextEdit(self)
        self.xml_preview_edit.setObjectName("conversionXmlPreview")
        self.xml_preview_edit.setReadOnly(True)
        self.xml_preview_edit.setMinimumHeight(180)
        output_layout.addWidget(self.xml_preview_edit, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.export_button = QPushButton("Export…", self)
        self.export_button.setDefault(True)
        self.export_button.clicked.connect(self._export_current_preview)
        close_button = QPushButton("Close", self)
        close_button.clicked.connect(self.reject)
        buttons.addWidget(self.export_button)
        buttons.addWidget(close_button)
        root.addLayout(buttons)

        self._apply_compact_defaults()
        self._reload_track_choices()
        self._reload_saved_template_names()
        self._update_source_mode_state()
        self._update_template_ui()
        self._update_source_ui()
        self._update_mapping_ui()
        self._update_output_ui()

    def _apply_compact_defaults(self) -> None:
        _apply_compact_dialog_control_heights(self)
        self.template_scope_row.hide()
        self.source_scope_row.hide()
        self.csv_controls_row.hide()
        self.database_scope_box.hide()
        self.export_button.setEnabled(False)
        has_store = self.template_store_service is not None
        self.saved_template_load_label.setVisible(has_store)
        self.saved_template_save_label.setVisible(has_store)
        self.saved_template_load_row.setVisible(has_store)
        self.saved_template_save_row.setVisible(has_store)
        if not has_store:
            self.saved_template_combo.hide()
            self.saved_template_name_edit.hide()
            self.include_mapping_in_saved_template_checkbox.hide()
            self.save_template_to_profile_button.hide()

    def _reload_track_choices(self) -> None:
        if not callable(self.track_choices_provider):
            self._available_track_choices = []
            self._track_title_by_id = {}
            return
        try:
            choices = list(self.track_choices_provider() or [])
        except Exception:
            choices = []
        self._available_track_choices = [
            (
                choice
                if isinstance(choice, TrackChoice)
                else TrackChoice(
                    track_id=int(getattr(choice, "track_id", 0) or 0),
                    title=str(getattr(choice, "title", "") or ""),
                    subtitle=str(getattr(choice, "subtitle", "") or ""),
                )
            )
            for choice in choices
            if int(getattr(choice, "track_id", 0) or 0) > 0
        ]
        self._track_title_by_id = {
            int(choice.track_id): str(choice.title or "").strip() or f"Track {choice.track_id}"
            for choice in self._available_track_choices
        }

    def _choose_template(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose Conversion Template",
            "",
            "Supported Templates (*.csv *.xlsx *.xlsm *.xltx *.xltm *.xml)",
        )
        if not path:
            return
        try:
            self.template_profile = self.service.inspect_template(path)
        except Exception as exc:
            QMessageBox.warning(self, "Template Conversion", str(exc))
            return
        self._pending_saved_template_mapping_payload = ""
        self._template_path = path
        self.template_path_label.setText(str(path))
        if not self.saved_template_name_edit.text().strip():
            self.saved_template_name_edit.setText(Path(path).stem)
        self._populate_scope_combo(
            self.template_scope_combo, self.template_profile.available_scopes
        )
        self.template_scope_row.setVisible(bool(self.template_profile.available_scopes))
        self._rebuild_session_preview()

    def _choose_source_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose Conversion Source File",
            "",
            "Supported Sources (*.csv *.xlsx *.xlsm *.xltx *.xltm *.xml *.json)",
        )
        if not path:
            return
        self._inspect_source_file(path)

    def _inspect_source_file(self, path: str) -> None:
        try:
            self._file_source_profile = self.service.inspect_source_file(
                path,
                preferred_csv_delimiter=self._requested_csv_delimiter(),
            )
        except Exception as exc:
            QMessageBox.warning(self, "Template Conversion", str(exc))
            return
        self.source_profile = self._file_source_profile
        self._source_path = path
        self.source_path_label.setText(str(path))
        self._populate_scope_combo(self.source_scope_combo, self.source_profile.available_scopes)
        self.source_scope_row.setVisible(bool(self.source_profile.available_scopes))
        self._set_default_source_inclusion()
        self._rebuild_session_preview()

    def _on_source_mode_changed(self) -> None:
        self._update_source_mode_state()
        self._rebuild_session_preview()

    def _update_source_mode_state(self) -> None:
        mode = self._current_source_mode()
        file_mode = mode == _MODE_FILE
        self.source_file_row.setVisible(file_mode)
        self.database_scope_box.setVisible(not file_mode)
        self.source_mode_hint.setText(
            "Inspect a structured source file and map its fields into the template."
            if file_mode
            else "Use flattened track-centric export rows from the current profile."
        )
        if not file_mode:
            self._refresh_database_selection_banner()
            if self.profile_available and self._database_source_profile is None:
                self._load_database_source()
            else:
                self.source_profile = self._database_source_profile
        else:
            self.source_profile = self._file_source_profile
            self.csv_controls_row.setVisible(
                bool(self.source_profile and self.source_profile.format_name == "csv")
            )

    def _requested_csv_delimiter(self) -> str | None:
        if self._current_source_mode() != _MODE_FILE:
            return None
        current = str(self.csv_delimiter_combo.currentData() or "")
        if current == "auto":
            return None
        if current == "custom":
            custom = self.csv_custom_delimiter_edit.text()
            if len(custom) != 1 or custom == "\t":
                return None
            return custom
        return current or None

    def _on_csv_delimiter_changed(self) -> None:
        if not self._source_path or not self._source_path.lower().endswith(".csv"):
            return
        current = str(self.csv_delimiter_combo.currentData() or "")
        if current == "custom":
            custom = self.csv_custom_delimiter_edit.text()
            if len(custom) != 1:
                self.csv_error_label.setText("Custom delimiters must be exactly one character.")
                self.export_button.setEnabled(False)
                return
            if custom == "\t":
                self.csv_error_label.setText(
                    "Use the dedicated Tab option instead of a custom tab."
                )
                self.export_button.setEnabled(False)
                return
        self.csv_error_label.setText("")
        self._inspect_source_file(self._source_path)

    def _populate_scope_combo(
        self,
        combo: QComboBox,
        scopes: tuple[tuple[str, str], ...],
    ) -> None:
        combo.blockSignals(True)
        combo.clear()
        for scope_key, scope_label in scopes:
            combo.addItem(str(scope_label), str(scope_key))
        combo.blockSignals(False)

    def _on_template_scope_changed(self) -> None:
        if self.template_profile is None:
            return
        scope_key = str(self.template_scope_combo.currentData() or "")
        if not scope_key:
            return
        self.template_profile = self.service.select_template_scope(self.template_profile, scope_key)
        self._rebuild_session_preview()

    def _on_source_scope_changed(self) -> None:
        if self.source_profile is None:
            return
        scope_key = str(self.source_scope_combo.currentData() or "")
        if not scope_key:
            return
        self.source_profile = self.service.select_source_scope(self.source_profile, scope_key)
        if self._current_source_mode() == _MODE_FILE:
            self._file_source_profile = self.source_profile
        else:
            self._database_source_profile = self.source_profile
        self._set_default_source_inclusion()
        self._rebuild_session_preview()

    def _current_source_mode(self) -> str:
        return str(self.source_mode_combo.currentData() or _MODE_FILE)

    def _use_current_database_selection(self) -> None:
        self._database_override_active = False
        self._database_override_track_ids = []
        self._load_database_source()

    def _choose_database_tracks(self) -> None:
        self._reload_track_choices()
        dialog = TrackSelectionChooserDialog(
            track_choices=self._available_track_choices,
            initial_track_ids=self._database_current_track_ids(),
            title="Choose Tracks",
            subtitle="Choose the tracks that should feed the conversion source rows.",
            parent=self,
        )
        try:
            if dialog.exec() != QDialog.Accepted:
                return
            self._database_override_track_ids = dialog.selected_track_ids()
            self._database_override_active = True
            self._load_database_source()
        finally:
            dialog.close()

    def _clear_database_override(self) -> None:
        self._database_override_track_ids = []
        self._database_override_active = False
        self._load_database_source()

    def _database_default_track_ids(self) -> list[int]:
        if not callable(self.default_database_track_ids_provider):
            return []
        try:
            return [
                int(track_id)
                for track_id in list(self.default_database_track_ids_provider() or [])
                if int(track_id) > 0
            ]
        except Exception:
            return []

    def _database_current_track_ids(self) -> list[int]:
        if self._database_override_active:
            return list(self._database_override_track_ids)
        return self._database_default_track_ids()

    def _refresh_database_selection_banner(self) -> None:
        track_ids = self._database_current_track_ids()
        self.selection_banner.set_state(
            SelectionScopeState(
                source_label=(
                    "Pinned track selection"
                    if self._database_override_active
                    else "Catalog selection"
                ),
                track_ids=tuple(track_ids),
                preview_text=(
                    build_selection_preview(track_ids, self._track_title_by_id.get)
                    if track_ids
                    else "No tracks selected yet."
                ),
                override_active=self._database_override_active,
            )
        )

    def _load_database_source(self) -> None:
        if not self.profile_available:
            return
        track_ids = self._database_current_track_ids()
        self._refresh_database_selection_banner()
        if not track_ids:
            self._database_source_profile = None
            self.source_profile = None
            self._set_default_source_inclusion()
            self._rebuild_session_preview()
            return
        try:
            self._database_source_profile = self.service.inspect_database_tracks(track_ids)
        except Exception as exc:
            QMessageBox.warning(self, "Template Conversion", str(exc))
            return
        self.source_profile = self._database_source_profile
        self._set_default_source_inclusion()
        self._rebuild_session_preview()

    def _set_default_source_inclusion(self) -> None:
        row_count = len(self.source_profile.rows) if self.source_profile is not None else 0
        self._source_included_indices = set(range(row_count))

    def _capture_current_mapping_entries(self) -> dict[str, ConversionMappingEntry]:
        if self.session is None:
            return {}
        return {
            entry.target_field_key: entry for entry in tuple(self.session.mapping_entries or ())
        }

    def _entry_is_compatible(self, entry: ConversionMappingEntry) -> bool:
        if self.source_profile is None:
            return entry.mapping_kind != MAPPING_KIND_SOURCE
        if entry.mapping_kind == MAPPING_KIND_SOURCE:
            return entry.source_field in set(self.source_profile.headers)
        return True

    def _rebuild_session_preview(self) -> None:
        previous_entries = self._capture_current_mapping_entries()
        if self.template_profile is None or self.source_profile is None:
            self.session = None
            self.preview = None
            self._update_template_ui()
            self._update_source_ui()
            self._update_mapping_ui()
            self._update_output_ui()
            return
        self.session = self.service.build_session(self.template_profile, self.source_profile)
        suggestions = self.service.suggest_mapping(self.session)
        loaded_entries_by_key: dict[str, ConversionMappingEntry] = {}
        if self._pending_saved_template_mapping_payload and self.template_profile is not None:
            loaded_entries = self.service.deserialize_mapping_entries(
                self._pending_saved_template_mapping_payload,
                self.template_profile,
            )
            loaded_entries_by_key = {
                entry.target_field_key: entry
                for entry in loaded_entries
                if self._entry_is_compatible(entry)
            }
            self._pending_saved_template_mapping_payload = ""
        merged_entries: list[ConversionMappingEntry] = []
        for field in self.template_profile.target_fields:
            preferred = loaded_entries_by_key.get(field.field_key) or previous_entries.get(
                field.field_key
            )
            if preferred is not None and self._entry_is_compatible(preferred):
                merged_entries.append(preferred)
            else:
                merged_entries.append(
                    suggestions.get(field.field_key)
                    or ConversionMappingEntry(
                        target_field_key=field.field_key,
                        target_display_name=field.display_name,
                    )
                )
        self.session.mapping_entries = tuple(merged_entries)
        self.session.included_row_indices = tuple(sorted(self._source_included_indices))
        self.preview = self.service.build_preview(self.session)
        self._update_template_ui()
        self._update_source_ui()
        self._reload_preset_names()
        self._update_mapping_ui()
        self._update_output_ui()

    def _update_template_ui(self) -> None:
        if self.template_profile is None:
            self.template_summary_label.setText(
                "Choose a target template to inspect its structure."
            )
            self.template_fields_table.setRowCount(0)
            self.template_scope_row.hide()
            return
        template_source_label = str(
            self.template_profile.adapter_state.get("source_label")
            or self.template_profile.template_path
        )
        warnings_text = (
            "<br/>".join(f"- {warning}" for warning in self.template_profile.warnings)
            if self.template_profile.warnings
            else "No template warnings."
        )
        self.template_summary_label.setText(
            "<br/>".join(
                [
                    f"<b>Template:</b> {template_source_label}",
                    f"<b>Format:</b> {self.template_profile.format_name.upper()}",
                    f"<b>Structure:</b> {self.template_profile.structure_label}",
                    f"<b>Scope:</b> {self.template_profile.chosen_scope or 'Default'}",
                    f"<b>Warnings:</b><br/>{warnings_text}",
                ]
            )
        )
        fields = tuple(self.template_profile.target_fields)
        self.template_fields_table.setRowCount(len(fields))
        for row_index, field in enumerate(fields):
            self.template_fields_table.setItem(row_index, 0, QTableWidgetItem(field.display_name))
            self.template_fields_table.setItem(row_index, 1, QTableWidgetItem(field.location))
            self.template_fields_table.setItem(
                row_index,
                2,
                QTableWidgetItem(field.required_status.title()),
            )

    def _update_source_ui(self) -> None:
        if self.source_profile is None:
            self.source_summary_label.setText("Choose a source file or current-profile tracks.")
            self.source_table.setRowCount(0)
            self.source_table.setColumnCount(1)
            self.source_table.setHorizontalHeaderLabels(["Use"])
            self.csv_controls_row.setVisible(False)
            self.source_scope_row.hide()
            return
        self.csv_controls_row.setVisible(self.source_profile.format_name == "csv")
        warnings_text = (
            "<br/>".join(f"- {warning}" for warning in self.source_profile.warnings)
            if self.source_profile.warnings
            else "No source warnings."
        )
        details = [
            f"<b>Source:</b> {self.source_profile.source_label}",
            f"<b>Mode:</b> {'Current Profile Tracks' if self.source_profile.source_mode == _MODE_DATABASE else self.source_profile.format_name.upper()}",
            f"<b>Rows:</b> {len(self.source_profile.rows)}",
            f"<b>Warnings:</b><br/>{warnings_text}",
        ]
        if self.source_profile.resolved_delimiter:
            details.append(
                f"<b>Delimiter:</b> {self._delimiter_label(self.source_profile.resolved_delimiter)}"
            )
        self.source_summary_label.setText("<br/>".join(details))
        headers = ["Use", *self.source_profile.headers]
        self._source_table_sync = True
        try:
            self.source_table.setRowCount(len(self.source_profile.rows))
            self.source_table.setColumnCount(len(headers))
            self.source_table.setHorizontalHeaderLabels(headers)
            for row_index, row in enumerate(self.source_profile.rows):
                use_item = QTableWidgetItem("")
                use_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
                use_item.setCheckState(
                    Qt.Checked if row_index in self._source_included_indices else Qt.Unchecked
                )
                self.source_table.setItem(row_index, 0, use_item)
                for column_index, header in enumerate(self.source_profile.headers, start=1):
                    self.source_table.setItem(
                        row_index,
                        column_index,
                        QTableWidgetItem("" if row.get(header) is None else str(row.get(header))),
                    )
        finally:
            self._source_table_sync = False

    def _on_source_table_item_changed(self, item: QTableWidgetItem) -> None:
        if self._source_table_sync or item.column() != 0:
            return
        if item.checkState() == Qt.Checked:
            self._source_included_indices.add(item.row())
        else:
            self._source_included_indices.discard(item.row())
        if self.session is not None:
            self.session.included_row_indices = tuple(sorted(self._source_included_indices))
        if self.session is not None:
            self.preview = self.service.build_preview(self.session)
        self._update_mapping_ui()
        self._update_output_ui()

    def _update_mapping_ui(self) -> None:
        if self.session is None or self.preview is None:
            self.mapping_table.setRowCount(0)
            return
        self._mapping_table_sync = True
        try:
            entries = tuple(self.preview.mapping_entries)
            self.mapping_table.setRowCount(len(entries))
            source_headers = tuple(
                self.source_profile.headers if self.source_profile is not None else ()
            )
            for row_index, entry in enumerate(entries):
                target_item = QTableWidgetItem(entry.target_display_name)
                target_item.setData(Qt.UserRole, entry.target_field_key)
                self.mapping_table.setItem(row_index, 0, target_item)
                required_status = next(
                    (
                        field.required_status.title()
                        for field in self.template_profile.target_fields
                        if field.field_key == entry.target_field_key
                    ),
                    "",
                )
                self.mapping_table.setItem(row_index, 1, QTableWidgetItem(required_status))

                mapping_combo = QComboBox(self.mapping_table)
                mapping_combo.addItem("Unmapped", _MAP_TO_UNMAPPED)
                mapping_combo.addItem("Skip Field", _MAP_TO_SKIP)
                mapping_combo.addItem("Constant Value", _MAP_TO_CONSTANT)
                for header in source_headers:
                    mapping_combo.addItem(str(header), str(header))
                if entry.mapping_kind == MAPPING_KIND_SOURCE and entry.source_field:
                    target_index = mapping_combo.findData(entry.source_field)
                elif entry.mapping_kind == MAPPING_KIND_SKIP:
                    target_index = mapping_combo.findData(_MAP_TO_SKIP)
                elif entry.mapping_kind == MAPPING_KIND_CONSTANT:
                    target_index = mapping_combo.findData(_MAP_TO_CONSTANT)
                else:
                    target_index = mapping_combo.findData(_MAP_TO_UNMAPPED)
                mapping_combo.setCurrentIndex(max(target_index, 0))
                mapping_combo.currentIndexChanged.connect(
                    lambda _index, target_key=entry.target_field_key: self._on_mapping_widget_changed(
                        target_key
                    )
                )
                self.mapping_table.setCellWidget(row_index, 2, mapping_combo)

                constant_edit = QLineEdit(self.mapping_table)
                constant_edit.setText(entry.constant_value)
                constant_edit.setEnabled(entry.mapping_kind == MAPPING_KIND_CONSTANT)
                constant_edit.textEdited.connect(
                    lambda _text, target_key=entry.target_field_key: self._on_mapping_widget_changed(
                        target_key
                    )
                )
                self.mapping_table.setCellWidget(row_index, 3, constant_edit)

                transform_combo = QComboBox(self.mapping_table)
                for transform_name in available_transforms():
                    transform_combo.addItem(transform_label(transform_name), transform_name)
                transform_index = transform_combo.findData(entry.transform_name)
                transform_combo.setCurrentIndex(max(transform_index, 0))
                transform_combo.setEnabled(
                    entry.mapping_kind in {MAPPING_KIND_SOURCE, MAPPING_KIND_CONSTANT}
                )
                transform_combo.currentIndexChanged.connect(
                    lambda _index, target_key=entry.target_field_key: self._on_mapping_widget_changed(
                        target_key
                    )
                )
                self.mapping_table.setCellWidget(row_index, 4, transform_combo)

                self.mapping_table.setItem(row_index, 5, QTableWidgetItem(entry.sample_value))
                self.mapping_table.setItem(
                    row_index, 6, QTableWidgetItem(entry.message or entry.status)
                )
        finally:
            self._mapping_table_sync = False

    def _on_mapping_widget_changed(self, _target_key: str) -> None:
        if self._mapping_table_sync or self.session is None:
            return
        self.session.mapping_entries = tuple(self._collect_mapping_entries_from_table())
        self.preview = self.service.build_preview(self.session)
        self._refresh_mapping_feedback()
        self._update_output_ui()

    def _collect_mapping_entries_from_table(self) -> list[ConversionMappingEntry]:
        field_by_key = {
            field.field_key: field for field in tuple(self.template_profile.target_fields or ())
        }
        updated_entries: list[ConversionMappingEntry] = []
        for row_index in range(self.mapping_table.rowCount()):
            target_item = self.mapping_table.item(row_index, 0)
            if target_item is None:
                continue
            field_key = str(target_item.data(Qt.UserRole) or "").strip()
            field = field_by_key.get(field_key)
            if field is None:
                continue
            mapping_combo = self.mapping_table.cellWidget(row_index, 2)
            constant_edit = self.mapping_table.cellWidget(row_index, 3)
            transform_combo = self.mapping_table.cellWidget(row_index, 4)
            map_value = str(mapping_combo.currentData() or _MAP_TO_UNMAPPED)
            constant_value = constant_edit.text() if isinstance(constant_edit, QLineEdit) else ""
            transform_name = (
                str(transform_combo.currentData() or "identity")
                if isinstance(transform_combo, QComboBox)
                else "identity"
            )
            if isinstance(constant_edit, QLineEdit):
                constant_edit.setEnabled(map_value == _MAP_TO_CONSTANT)
            if map_value == _MAP_TO_CONSTANT:
                updated_entries.append(
                    ConversionMappingEntry(
                        target_field_key=field.field_key,
                        target_display_name=field.display_name,
                        mapping_kind=MAPPING_KIND_CONSTANT,
                        constant_value=constant_value,
                        transform_name=transform_name,
                    )
                )
            elif map_value == _MAP_TO_SKIP:
                updated_entries.append(
                    ConversionMappingEntry(
                        target_field_key=field.field_key,
                        target_display_name=field.display_name,
                        mapping_kind=MAPPING_KIND_SKIP,
                        transform_name=transform_name,
                    )
                )
            elif map_value == _MAP_TO_UNMAPPED:
                updated_entries.append(
                    ConversionMappingEntry(
                        target_field_key=field.field_key,
                        target_display_name=field.display_name,
                        mapping_kind=MAPPING_KIND_UNMAPPED,
                        transform_name=transform_name,
                    )
                )
            else:
                updated_entries.append(
                    ConversionMappingEntry(
                        target_field_key=field.field_key,
                        target_display_name=field.display_name,
                        mapping_kind=MAPPING_KIND_SOURCE,
                        source_field=map_value,
                        transform_name=transform_name,
                    )
                )
        return updated_entries

    def _refresh_mapping_feedback(self) -> None:
        if self.preview is None:
            return
        self._mapping_table_sync = True
        try:
            preview_by_key = {
                entry.target_field_key: entry for entry in tuple(self.preview.mapping_entries or ())
            }
            for row_index in range(self.mapping_table.rowCount()):
                target_item = self.mapping_table.item(row_index, 0)
                if target_item is None:
                    continue
                field_key = str(target_item.data(Qt.UserRole) or "").strip()
                entry = preview_by_key.get(field_key)
                if entry is None:
                    continue
                mapping_combo = self.mapping_table.cellWidget(row_index, 2)
                constant_edit = self.mapping_table.cellWidget(row_index, 3)
                transform_combo = self.mapping_table.cellWidget(row_index, 4)
                if isinstance(mapping_combo, QComboBox):
                    map_value = str(mapping_combo.currentData() or _MAP_TO_UNMAPPED)
                else:
                    map_value = _MAP_TO_UNMAPPED
                if isinstance(constant_edit, QLineEdit):
                    constant_edit.setEnabled(map_value == _MAP_TO_CONSTANT)
                if isinstance(transform_combo, QComboBox):
                    transform_combo.setEnabled(map_value not in {_MAP_TO_UNMAPPED, _MAP_TO_SKIP})
                sample_item = self.mapping_table.item(row_index, 5)
                if sample_item is None:
                    sample_item = QTableWidgetItem("")
                    self.mapping_table.setItem(row_index, 5, sample_item)
                sample_item.setText(entry.sample_value)
                status_item = self.mapping_table.item(row_index, 6)
                if status_item is None:
                    status_item = QTableWidgetItem("")
                    self.mapping_table.setItem(row_index, 6, status_item)
                status_item.setText(entry.message or entry.status)
        finally:
            self._mapping_table_sync = False

    def _apply_suggested_mapping(self) -> None:
        if self.session is None:
            return
        suggestions = self.service.suggest_mapping(self.session)
        self.session.mapping_entries = tuple(
            suggestions.get(field.field_key)
            or ConversionMappingEntry(
                target_field_key=field.field_key,
                target_display_name=field.display_name,
            )
            for field in self.template_profile.target_fields
        )
        self.preview = self.service.build_preview(self.session)
        self._update_mapping_ui()
        self._update_output_ui()

    def _update_output_ui(self) -> None:
        if self.preview is None:
            self.output_status_label.setText("Load a template and source to build a preview.")
            self.output_table.setRowCount(0)
            self.output_table.setColumnCount(0)
            self.xml_preview_edit.clear()
            self.export_button.setEnabled(False)
            self._update_saved_template_actions()
            return
        status_lines: list[str] = [
            f"<b>Included rows:</b> {len(self.preview.included_row_indices)}",
            f"<b>Rendered output rows:</b> {len(self.preview.rendered_rows)}",
        ]
        if self.preview.blocking_issues:
            status_lines.append(
                "<b>Blocking issues:</b><br/>"
                + "<br/>".join(f"- {issue}" for issue in self.preview.blocking_issues)
            )
        if self.preview.warnings:
            status_lines.append(
                "<b>Warnings:</b><br/>"
                + "<br/>".join(f"- {warning}" for warning in self.preview.warnings)
            )
        self.output_status_label.setText("<br/>".join(status_lines))
        headers = tuple(self.preview.rendered_headers)
        self.output_table.setRowCount(len(self.preview.rendered_rows))
        self.output_table.setColumnCount(len(headers))
        self.output_table.setHorizontalHeaderLabels(list(headers))
        for row_index, row in enumerate(self.preview.rendered_rows):
            for column_index, value in enumerate(row):
                self.output_table.setItem(row_index, column_index, QTableWidgetItem(str(value)))
        self.xml_preview_edit.setPlainText(self.preview.rendered_xml_text or "")
        self.xml_preview_edit.setVisible(self.preview.template_profile.format_name == "xml")
        self.export_button.setEnabled(
            not self.preview.blocking_issues and bool(self.preview.rendered_rows)
        )
        self._update_saved_template_actions()

    def _export_current_preview(self) -> None:
        if self.preview is None:
            return
        default_name = self._suggest_output_name()
        format_name = self.preview.template_profile.format_name
        file_filter = {
            "csv": "CSV Files (*.csv)",
            "xlsx": "Excel Workbook (*.xlsx *.xlsm *.xltx *.xltm)",
            "xml": "XML Files (*.xml)",
        }.get(format_name, "All files (*)")
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Conversion Output",
            str(self.exports_dir / default_name),
            file_filter,
        )
        if not path:
            return
        self.export_callback(self.preview, path)

    def _suggest_output_name(self) -> str:
        suffix = self.preview.template_profile.output_suffix if self.preview else ".out"
        template_stem = (
            self.preview.template_profile.template_path.stem
            if self.preview is not None
            else "template"
        )
        return f"conversion_{normalize_field_name(template_stem) or 'template'}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{suffix}"

    def _reload_saved_template_names(self) -> None:
        if self.template_store_service is None:
            return
        current_id = int(self.saved_template_combo.currentData() or 0)
        self.saved_template_combo.blockSignals(True)
        self.saved_template_combo.clear()
        try:
            templates = tuple(self.template_store_service.list_saved_templates() or ())
        except Exception:
            templates = ()
        for record in templates:
            label = (
                f"{record.name} ({record.filename})"
                if record.filename and record.filename.casefold() != record.name.casefold()
                else record.name
            )
            self.saved_template_combo.addItem(label, int(record.id))
        self.saved_template_combo.blockSignals(False)
        if current_id > 0:
            existing_index = self.saved_template_combo.findData(current_id)
            if existing_index >= 0:
                self.saved_template_combo.setCurrentIndex(existing_index)
        self._update_saved_template_actions()

    def _update_saved_template_actions(self) -> None:
        if self.template_store_service is None:
            return
        has_saved_templates = self.saved_template_combo.count() > 0
        self.load_saved_template_button.setEnabled(has_saved_templates)
        self.save_template_to_profile_button.setEnabled(self.template_profile is not None)
        has_mapping = self.session is not None and bool(self.session.mapping_entries)
        self.include_mapping_in_saved_template_checkbox.setEnabled(has_mapping)
        if not has_mapping:
            self.include_mapping_in_saved_template_checkbox.setChecked(False)

    def _load_selected_saved_template(self) -> None:
        if self.template_store_service is None:
            return
        template_id = int(self.saved_template_combo.currentData() or 0)
        if template_id <= 0:
            return
        try:
            record = self.template_store_service.load_saved_template(template_id)
            if record.template_bytes is None:
                raise ValueError("The saved conversion template is missing its stored file bytes.")
            self.template_profile = self.service.inspect_template_bytes(
                record.filename,
                record.template_bytes,
                source_label=f"Saved in profile: {record.name} ({record.filename})",
                source_path=record.source_path,
            )
            if record.chosen_scope:
                self.template_profile = self.service.select_template_scope(
                    self.template_profile,
                    record.chosen_scope,
                )
        except Exception as exc:
            QMessageBox.warning(self, "Template Conversion", str(exc))
            return
        self._pending_saved_template_mapping_payload = str(record.mapping_payload or "")
        self._template_path = ""
        self.template_path_label.setText(f"Saved in profile: {record.name} ({record.filename})")
        self.saved_template_name_edit.setText(record.name)
        self._populate_scope_combo(
            self.template_scope_combo, self.template_profile.available_scopes
        )
        self.template_scope_row.setVisible(bool(self.template_profile.available_scopes))
        target_mode = str(record.source_mode or "").strip()
        target_index = self.source_mode_combo.findData(target_mode) if target_mode else -1
        if (
            target_index >= 0
            and (target_mode != _MODE_DATABASE or self.profile_available)
            and target_index != self.source_mode_combo.currentIndex()
        ):
            self.source_mode_combo.setCurrentIndex(target_index)
            return
        self._rebuild_session_preview()

    def _save_template_to_profile(self) -> None:
        if self.template_store_service is None:
            return
        if self.template_profile is None:
            QMessageBox.information(
                self,
                "Template Conversion",
                "Choose or load a template before saving it to the profile database.",
            )
            return
        name = self.saved_template_name_edit.text().strip()
        if not name:
            QMessageBox.information(
                self,
                "Template Conversion",
                "Enter a profile template name first.",
            )
            return
        mapping_payload = ""
        if self.include_mapping_in_saved_template_checkbox.isChecked() and self.session is not None:
            current_entries = tuple(self._collect_mapping_entries_from_table())
            self.session.mapping_entries = current_entries
            mapping_payload = self.service.serialize_mapping_entries(current_entries)
        try:
            record = self.template_store_service.save_template(
                name=name,
                template_profile=self.template_profile,
                mapping_payload=mapping_payload,
                source_mode=self._current_source_mode(),
            )
        except Exception as exc:
            QMessageBox.warning(self, "Template Conversion", str(exc))
            return
        self._reload_saved_template_names()
        saved_index = self.saved_template_combo.findData(int(record.id))
        if saved_index >= 0:
            self.saved_template_combo.setCurrentIndex(saved_index)
        QMessageBox.information(
            self,
            "Template Conversion",
            (
                f"Saved '{record.name}' to the profile database."
                + ("\nThe current mapping was stored with it." if mapping_payload else "")
            ),
        )

    def _reload_preset_names(self) -> None:
        self.preset_combo.clear()
        for name in sorted(self._preset_payload()):
            self.preset_combo.addItem(name)

    def _preset_settings_key(self) -> str | None:
        if self.template_profile is None or self.source_profile is None:
            return None
        return (
            f"conversion/presets/"
            f"{self.template_profile.template_signature}/"
            f"{self.source_profile.source_mode}/"
            f"{self.template_profile.format_name}"
        )

    def _preset_payload(self) -> dict[str, str]:
        key = self._preset_settings_key()
        if not key:
            return {}
        raw = self.settings.value(key, "{}")
        try:
            payload = json.loads(str(raw or "{}"))
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            return {}
        return {str(name): str(value) for name, value in payload.items()}

    def _save_current_preset(self) -> None:
        if self.session is None:
            return
        name = self.preset_name_edit.text().strip()
        if not name:
            QMessageBox.information(self, "Template Conversion", "Enter a preset name first.")
            return
        current_entries = tuple(self._collect_mapping_entries_from_table())
        self.session.mapping_entries = current_entries
        payload = self._preset_payload()
        payload[name] = self.service.serialize_mapping_entries(current_entries)
        key = self._preset_settings_key()
        if not key:
            return
        self.settings.setValue(key, json.dumps(payload, ensure_ascii=False, sort_keys=True))
        self.settings.sync()
        self._reload_preset_names()
        self.preset_combo.setCurrentText(name)

    def _load_selected_preset(self) -> None:
        if self.session is None or self.template_profile is None:
            return
        name = self.preset_combo.currentText().strip()
        payload = self._preset_payload().get(name)
        if not payload:
            return
        loaded_entries = self.service.deserialize_mapping_entries(payload, self.template_profile)
        if not loaded_entries:
            return
        merged_by_key = {entry.target_field_key: entry for entry in loaded_entries}
        self.session.mapping_entries = tuple(
            merged_by_key.get(field.field_key)
            or ConversionMappingEntry(
                target_field_key=field.field_key,
                target_display_name=field.display_name,
            )
            for field in self.template_profile.target_fields
        )
        self.preview = self.service.build_preview(self.session)
        self._update_mapping_ui()
        self._update_output_ui()

    @staticmethod
    def _delimiter_label(delimiter: str) -> str:
        if delimiter == "\t":
            return "Tab"
        if delimiter == ";":
            return "Semicolon (;)"
        if delimiter == "|":
            return "Pipe (|)"
        if delimiter == ",":
            return "Comma (,)"
        return delimiter

"""Application settings dialog."""

from __future__ import annotations

import json
import re
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QColorDialog,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QMenuBar,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSlider,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextBrowser,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from isrc_manager.app_prompts import (
    get_name_from_editable_choice_dialog as _get_name_from_editable_choice_dialog,
)
from isrc_manager.blob_icons import (
    BlobIconEditorWidget,
    icon_from_blob_icon_spec,
    normalize_blob_icon_settings,
)
from isrc_manager.qss_autocomplete import QssCodeEditor, validate_qss_document
from isrc_manager.qss_reference import (
    QssReferenceEntry,
    collect_qss_reference_entries,
)
from isrc_manager.qss_reference import (
    ensure_widget_object_names as _ensure_qss_widget_object_names,
)
from isrc_manager.qss_reference import (
    repolish_widget_tree as _repolish_qss_widget_tree,
)
from isrc_manager.theme_builder import (
    build_theme_stylesheet as build_app_theme_stylesheet,
)
from isrc_manager.theme_builder import (
    effective_theme_settings as build_effective_theme_settings,
)
from isrc_manager.theme_builder import (
    normalize_theme_settings as normalize_app_theme_settings,
)
from isrc_manager.theme_builder import (
    theme_setting_defaults as default_theme_settings,
)
from isrc_manager.ui_common import (
    FocusWheelComboBox,
    FocusWheelSlider,
    FocusWheelSpinBox,
    _create_round_help_button,
)


class ApplicationSettingsThemeMixin:
    def _create_color_editor(self, key: str, value: str, *, placeholder: str = "Auto") -> QWidget:
        row = QWidget(self)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        swatch = QLabel(row)
        swatch.setProperty("role", "colorSwatch")
        swatch.setObjectName(f"{key}Swatch")
        swatch.setFixedSize(30, 24)
        swatch.setAlignment(Qt.AlignCenter)

        edit = QLineEdit(value.strip())
        edit.setClearButtonEnabled(True)
        edit.setPlaceholderText(placeholder)
        edit.setMinimumWidth(170)
        edit.setMaximumWidth(230)

        pick_btn = QPushButton("Pick…", row)
        pick_btn.setAutoDefault(False)
        clear_btn = QPushButton("Default", row)
        clear_btn.setAutoDefault(False)

        layout.addWidget(swatch)
        layout.addWidget(edit)
        layout.addWidget(pick_btn)
        layout.addWidget(clear_btn)
        layout.addStretch(1)

        self._theme_color_edits[key] = edit
        self._theme_color_swatches[key] = swatch
        edit.textChanged.connect(lambda _text, name=key: self._sync_color_swatch(name))
        pick_btn.clicked.connect(lambda *_args, name=key: self._pick_theme_color(name))
        clear_btn.clicked.connect(edit.clear)
        self._sync_color_swatch(key)
        return row

    def _create_metric_editor(self, spec) -> FocusWheelSpinBox:
        spin = FocusWheelSpinBox(self)
        spin.setRange(spec.minimum, spec.maximum)
        spin.setValue(
            max(
                spec.minimum,
                min(spec.maximum, int(self._theme_settings.get(spec.key) or spec.default)),
            )
        )
        if spec.suffix:
            spin.setSuffix(spec.suffix)
        spin.setMinimumWidth(160)
        spin.setMaximumWidth(220)
        self._theme_metric_spins[spec.key] = spin
        if spec.key == "font_size":
            self.theme_font_size_spin = spin
        return spin

    @staticmethod
    def _group_theme_specs_by_section(specs):
        grouped: dict[str, list[object]] = {}
        for spec in specs:
            grouped.setdefault(spec.section, []).append(spec)
        return grouped

    def _build_theme_builder_tabs(self) -> None:
        self._theme_builder_page_keys = []
        for page_key, page_title, page_description in self._settings_builder_specs:
            if page_key == "advanced":
                page = self._build_theme_advanced_page()
            elif page_key == "blob_icons":
                page = self._build_blob_icon_builder_page(page_description)
            else:
                page = self._build_theme_builder_page(page_key, page_description)
            self.theme_builder_tabs.addTab(page, page_title)
            self._theme_builder_page_keys.append(page_key)

    def _build_theme_builder_page(self, page_key: str, description: str) -> QWidget:
        page = QWidget(self)
        page.setProperty("role", "workspaceCanvas")
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(12)

        intro = QLabel(description, page)
        intro.setWordWrap(True)
        intro.setProperty("role", "secondary")
        page_layout.addWidget(intro)

        color_specs = [spec for spec in self.COLOR_FIELD_SPECS if spec.page == page_key]
        metric_specs = [spec for spec in self.METRIC_FIELD_SPECS if spec.page == page_key]

        if page_key == "typography":
            typography_box = QGroupBox("Fonts & Readability", page)
            typography_grid = QGridLayout(typography_box)
            self._configure_grid(typography_grid)
            self._add_row(
                typography_grid,
                0,
                "Application Font",
                self.theme_font_family_combo,
                "Used across menus, dialogs, inputs, tables, and labels unless overridden by advanced QSS.",
            )
            self._add_row(
                typography_grid,
                1,
                "Text Contrast Guard",
                self.theme_auto_contrast_check,
                "Keeps foreground colors readable against their backgrounds. Turn this off to fully override colors yourself.",
            )
            page_layout.addWidget(typography_box)

        for section_title, section_specs in self._group_theme_specs_by_section(color_specs).items():
            group = QGroupBox(section_title, page)
            grid = QGridLayout(group)
            self._configure_grid(grid)
            for row, spec in enumerate(section_specs):
                editor = self._create_color_editor(
                    spec.key,
                    str(self._theme_settings.get(spec.key) or ""),
                    placeholder=spec.placeholder,
                )
                self._add_row(grid, row, spec.label, editor, spec.hint)
            page_layout.addWidget(group)

        for section_title, section_specs in self._group_theme_specs_by_section(
            metric_specs
        ).items():
            group = QGroupBox(section_title, page)
            grid = QGridLayout(group)
            self._configure_grid(grid)
            for row, spec in enumerate(section_specs):
                editor = self._create_metric_editor(spec)
                self._add_row(grid, row, spec.label, editor, spec.hint)
            page_layout.addWidget(group)

        page_layout.addStretch(1)
        return self._wrap_tab_page(page)

    def _build_blob_icon_builder_page(self, description: str) -> QWidget:
        page = QWidget(self)
        page.setProperty("role", "workspaceCanvas")
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(12)

        intro = QLabel(description, page)
        intro.setWordWrap(True)
        intro.setProperty("role", "secondary")
        page_layout.addWidget(intro)

        builder_box = QGroupBox("Blob Media Icons", page)
        builder_grid = QGridLayout(builder_box)
        self._configure_grid(builder_grid)

        editor_specs = (
            (
                "audio_managed",
                "Managed Audio Icon",
                "Shown when primary audio is stored as a managed file.",
            ),
            (
                "audio_database",
                "Database Audio Icon",
                "Shown when primary audio is stored directly inside the database.",
            ),
            (
                "audio_lossy_managed",
                "Managed Lossy Audio Icon",
                "Shown when a lossy primary audio source such as MP3, AAC, or OGG is stored as a managed file.",
            ),
            (
                "audio_lossy_database",
                "Database Lossy Audio Icon",
                "Shown when a lossy primary audio source is stored directly inside the database.",
            ),
            (
                "image_managed",
                "Managed Image Icon",
                "Shown when Album Art or an inherited image BLOB field is stored as a managed file.",
            ),
            (
                "image_database",
                "Database Image Icon",
                "Shown when Album Art or an inherited image BLOB field is stored directly inside the database.",
            ),
        )
        for row_index, (kind, label, help_text) in enumerate(editor_specs):
            editor = BlobIconEditorWidget(kind=kind, allow_inherit=False, parent=builder_box)
            editor.set_spec(self._blob_icon_settings.get(kind))
            self._blob_icon_editors[kind] = editor
            self._add_row(
                builder_grid,
                row_index,
                label,
                editor,
                help_text,
            )
        page_layout.addWidget(builder_box)

        note_box = QGroupBox("How It Works", page)
        note_layout = QVBoxLayout(note_box)
        note_layout.setContentsMargins(14, 18, 14, 14)
        note_layout.setSpacing(8)
        for text in (
            "Media icons are profile-specific and stay separate from visual theme presets.",
            "Managed-file media and database-backed media can use different icons without changing the underlying storage behavior.",
            "Primary audio can keep a dedicated lossy badge so MP3/AAC/OGG sources still stand apart from WAV, FLAC, and AIFF masters.",
            "Platform icons use the current operating system's built-in icon set through Qt.",
            "Custom images are scaled down and compressed before they are written into the database, so large source files only occupy a small amount of storage.",
            "Custom BLOB columns can either inherit these global storage-aware defaults or define their own icon override.",
        ):
            label = QLabel(text, note_box)
            label.setWordWrap(True)
            label.setProperty("role", "secondary")
            note_layout.addWidget(label)
        page_layout.addWidget(note_box)
        page_layout.addStretch(1)
        return self._wrap_tab_page(page)

    def _build_theme_advanced_page(self) -> QWidget:
        advanced_page = QWidget(self)
        advanced_page.setProperty("role", "workspaceCanvas")
        advanced_layout = QVBoxLayout(advanced_page)
        advanced_layout.setContentsMargins(0, 0, 0, 0)
        advanced_layout.setSpacing(10)

        advanced_note = QLabel(
            "All visible controls receive object names automatically, so you can target specific widgets here. "
            "Attribute-backed widgets use their attribute name when available; other widgets receive generated names."
        )
        advanced_note.setProperty("role", "themeNote")
        advanced_note.setWordWrap(True)
        advanced_layout.addWidget(advanced_note)

        qss_help = QLabel(
            "Example selectors: `QPushButton`, `QLineEdit`, `QDockWidget::title`, `#profilesToolbar QPushButton`, or `QToolBar#actionRibbonToolbar`. "
            "Press Ctrl+Space in the editor for context-aware autocomplete with selectors, pseudo-states, subcontrols, "
            "property lines, value suggestions, and full rule templates. Use the selector catalog to insert a complete working template, including a short note about what the selector targets, when you want to start from a full example instead of an empty block."
        )
        qss_help.setProperty("role", "hint")
        qss_help.setWordWrap(True)
        advanced_layout.addWidget(qss_help)

        self.theme_qss_tabs = QTabWidget(self)
        self.theme_qss_tabs.setDocumentMode(True)
        advanced_layout.addWidget(self.theme_qss_tabs, 1)

        qss_editor_page = QWidget(self)
        qss_editor_page.setProperty("role", "workspaceCanvas")
        qss_editor_layout = QVBoxLayout(qss_editor_page)
        qss_editor_layout.setContentsMargins(0, 0, 0, 0)
        qss_editor_layout.setSpacing(10)
        self.theme_custom_qss_edit = QssCodeEditor(self)
        self.theme_custom_qss_edit.setPlaceholderText(
            "/* Advanced QSS */\nQPushButton#saveButton {\n    font-weight: 600;\n}\n"
        )
        self.theme_custom_qss_edit.setMinimumHeight(220)
        self.theme_custom_qss_edit.setPlainText(str(self._theme_settings.get("custom_qss") or ""))
        qss_editor_layout.addWidget(self.theme_custom_qss_edit, 1)
        self.theme_custom_qss_status_label = QLabel("", self)
        self.theme_custom_qss_status_label.setWordWrap(True)
        self.theme_custom_qss_status_label.setProperty("role", "secondary")
        qss_editor_layout.addWidget(self.theme_custom_qss_status_label)
        self.theme_qss_tabs.addTab(qss_editor_page, "Editor")

        qss_reference_page = QWidget(self)
        qss_reference_page.setProperty("role", "workspaceCanvas")
        qss_reference_layout = QVBoxLayout(qss_reference_page)
        qss_reference_layout.setContentsMargins(0, 0, 0, 0)
        qss_reference_layout.setSpacing(10)

        qss_reference_note = QLabel(
            "The reference catalog is built from the currently open app windows and dialogs. "
            "Open the screen you want to style, then refresh the catalog to harvest its generated object names. "
            "Double-click a row or use Insert Full Template when you want a complete scaffold first. Use Insert Selector Only when you explicitly want just the raw selector text."
        )
        qss_reference_note.setWordWrap(True)
        qss_reference_note.setProperty("role", "hint")
        qss_reference_layout.addWidget(qss_reference_note)

        qss_reference_controls = QWidget(self)
        qss_reference_controls_layout = QHBoxLayout(qss_reference_controls)
        qss_reference_controls_layout.setContentsMargins(0, 0, 0, 0)
        qss_reference_controls_layout.setSpacing(8)
        self.qss_reference_filter_edit = QLineEdit(self)
        self.qss_reference_filter_edit.setPlaceholderText(
            "Filter selectors by widget type, object name, role, or note..."
        )
        self.qss_reference_filter_edit.setClearButtonEnabled(True)
        self.qss_reference_filter_edit.textChanged.connect(self._apply_qss_reference_filter)
        self.qss_reference_refresh_button = QPushButton("Refresh Catalog", self)
        self.qss_reference_refresh_button.setAutoDefault(False)
        self.qss_reference_refresh_button.clicked.connect(self._refresh_qss_selector_reference)
        self.qss_reference_status_label = QLabel("", self)
        self.qss_reference_status_label.setProperty("role", "secondary")
        self.qss_reference_status_label.setWordWrap(True)
        qss_reference_controls_layout.addWidget(self.qss_reference_filter_edit, 1)
        qss_reference_controls_layout.addWidget(self.qss_reference_refresh_button)
        qss_reference_layout.addWidget(qss_reference_controls)
        qss_reference_layout.addWidget(self.qss_reference_status_label)

        self.qss_reference_table = QTableWidget(0, 3, self)
        self.qss_reference_table.setHorizontalHeaderLabels(["Category", "Selector", "Details"])
        self.qss_reference_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.qss_reference_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.qss_reference_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.qss_reference_table.verticalHeader().setVisible(False)
        qss_reference_header = self.qss_reference_table.horizontalHeader()
        qss_reference_header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        # Keep the selector browser compact even as the reference catalog grows.
        qss_reference_header.setSectionResizeMode(1, QHeaderView.Interactive)
        qss_reference_header.setSectionResizeMode(2, QHeaderView.Stretch)
        self.qss_reference_table.setColumnWidth(1, 320)
        self.qss_reference_table.itemSelectionChanged.connect(self._update_qss_reference_actions)
        self.qss_reference_table.doubleClicked.connect(
            lambda _index: self._insert_selected_qss_template()
        )
        qss_reference_layout.addWidget(self.qss_reference_table, 1)

        qss_reference_button_row = QHBoxLayout()
        qss_reference_button_row.setContentsMargins(0, 0, 0, 0)
        qss_reference_button_row.setSpacing(8)
        qss_reference_button_row.addStretch(1)
        self.qss_reference_copy_button = QPushButton("Copy Selector", self)
        self.qss_reference_copy_button.setAutoDefault(False)
        self.qss_reference_copy_button.clicked.connect(self._copy_selected_qss_selector)
        self.qss_reference_insert_button = QPushButton("Insert Selector Only", self)
        self.qss_reference_insert_button.setAutoDefault(False)
        self.qss_reference_insert_button.clicked.connect(self._insert_selected_qss_selector)
        self.qss_reference_insert_template_button = QPushButton("Insert Full Template", self)
        self.qss_reference_insert_template_button.setAutoDefault(False)
        self.qss_reference_insert_template_button.clicked.connect(
            self._insert_selected_qss_template
        )
        qss_reference_button_row.addWidget(self.qss_reference_copy_button)
        qss_reference_button_row.addWidget(self.qss_reference_insert_button)
        qss_reference_button_row.addWidget(self.qss_reference_insert_template_button)
        qss_reference_layout.addLayout(qss_reference_button_row)
        self.theme_qss_tabs.addTab(qss_reference_page, "Selector Reference")

        return advanced_page

    def _build_theme_preview_tabs(self) -> None:
        self._theme_preview_roots = []
        self._theme_preview_tab_indices = {}
        self._theme_preview_labels = {
            "typography": "Typography",
            "surfaces": "Surfaces",
            "buttons": "Buttons",
            "inputs": "Inputs",
            "data_views": "Data Views",
            "navigation": "Navigation",
            "action_ribbon": "Action Ribbon",
            "blob_icons": "Blob Icons",
            "advanced": "Advanced QSS",
        }
        preview_factories = {
            "typography": self._build_theme_preview_typography_page,
            "surfaces": self._build_theme_preview_surfaces_page,
            "buttons": self._build_theme_preview_buttons_page,
            "inputs": self._build_theme_preview_inputs_page,
            "data_views": self._build_theme_preview_data_views_page,
            "navigation": self._build_theme_preview_navigation_page,
            "action_ribbon": self._build_theme_preview_action_ribbon_page,
            "blob_icons": self._build_theme_preview_blob_icons_page,
            "advanced": self._build_theme_preview_advanced_page,
        }
        for page_key, _page_title, _page_description in self._settings_builder_specs:
            preview_page = preview_factories[page_key]()
            preview_index = self.theme_preview_tabs.addTab(
                preview_page, self._theme_preview_labels[page_key]
            )
            self._theme_preview_tab_indices[page_key] = preview_index
        self.theme_builder_tabs.currentChanged.connect(self._sync_theme_preview_to_builder_tab)
        self._sync_theme_preview_to_builder_tab(self.theme_builder_tabs.currentIndex())
        self._refresh_theme_previews()

    def _create_theme_preview_page(self, object_name: str) -> tuple[QWidget, QWidget, QVBoxLayout]:
        page = QWidget(self)
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(0)

        preview_root = QWidget(page)
        preview_root.setObjectName(object_name)
        preview_root.setProperty("role", "panel")
        layout = QVBoxLayout(preview_root)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        page_layout.addWidget(self._wrap_tab_page(preview_root), 1)
        self._theme_preview_roots.append(preview_root)
        return page, preview_root, layout

    def _build_theme_preview_typography_page(self) -> QWidget:
        page, preview_root, layout = self._create_theme_preview_page("themePreviewTypographyRoot")

        hero_box = QGroupBox("Text Hierarchy", preview_root)
        hero_layout = QVBoxLayout(hero_box)
        hero_layout.setContentsMargins(14, 18, 14, 14)
        hero_layout.setSpacing(8)
        title = QLabel("Theme Builder Preview", hero_box)
        title.setProperty("role", "dialogTitle")
        subtitle = QLabel(
            "Review how the selected font and size scale across titles, subtitles, body text, and support text.",
            hero_box,
        )
        subtitle.setProperty("role", "dialogSubtitle")
        subtitle.setWordWrap(True)
        hero_layout.addWidget(title)
        hero_layout.addWidget(subtitle)
        section_title = QLabel("Section Title Example", hero_box)
        section_title.setProperty("role", "sectionTitle")
        hero_layout.addWidget(section_title)
        body = QLabel(
            "Body text stays readable across the application and should remain comfortable for long metadata sessions.",
            hero_box,
        )
        body.setWordWrap(True)
        hero_layout.addWidget(body)
        secondary = QLabel(
            "Secondary text, metadata captions, and helper text use a softer hierarchy without feeling disconnected.",
            hero_box,
        )
        secondary.setProperty("role", "secondary")
        secondary.setWordWrap(True)
        hero_layout.addWidget(secondary)
        hint = QLabel("Hint text sample used under forms and grouped settings.", hero_box)
        hint.setProperty("role", "hint")
        hint.setWordWrap(True)
        hero_layout.addWidget(hint)
        layout.addWidget(hero_box)

        controls_box = QGroupBox("Text In Controls", preview_root)
        controls_layout = QVBoxLayout(controls_box)
        controls_layout.setContentsMargins(14, 18, 14, 14)
        controls_layout.setSpacing(10)
        control_row = QWidget(controls_box)
        control_row_layout = QHBoxLayout(control_row)
        control_row_layout.setContentsMargins(0, 0, 0, 0)
        control_row_layout.setSpacing(10)
        line_edit = QLineEdit("Line edit text preview", control_row)
        combo = FocusWheelComboBox(control_row)
        combo.addItems(["Font sample", "Secondary sample", "Compact sample"])
        combo.setCurrentIndex(0)
        button = QPushButton("Button Label", control_row)
        control_row_layout.addWidget(line_edit, 2)
        control_row_layout.addWidget(combo, 1)
        control_row_layout.addWidget(button)
        controls_layout.addWidget(control_row)
        layout.addWidget(controls_box)
        layout.addStretch(1)
        return page

    def _build_theme_preview_surfaces_page(self) -> QWidget:
        page, preview_root, layout = self._create_theme_preview_page("themePreviewSurfacesRoot")

        primary_panel = QGroupBox("Primary Surface", preview_root)
        primary_layout = QVBoxLayout(primary_panel)
        primary_layout.setContentsMargins(14, 18, 14, 14)
        primary_layout.setSpacing(8)
        primary_layout.addWidget(
            QLabel("Panels, borders, and helper text are previewed here.", primary_panel)
        )
        secondary = QLabel(
            "Adjust surface colors, panel backgrounds, borders, overlays, tooltips, and supporting text without unrelated controls crowding the preview.",
            primary_panel,
        )
        secondary.setProperty("role", "secondary")
        secondary.setWordWrap(True)
        primary_layout.addWidget(secondary)
        layout.addWidget(primary_panel)

        secondary_panel = QGroupBox("Secondary Surface", preview_root)
        secondary_layout = QVBoxLayout(secondary_panel)
        secondary_layout.setContentsMargins(14, 18, 14, 14)
        secondary_layout.setSpacing(8)
        workspace_canvas = QFrame(secondary_panel)
        workspace_canvas.setProperty("role", "workspaceCanvas")
        workspace_canvas_layout = QVBoxLayout(workspace_canvas)
        workspace_canvas_layout.setContentsMargins(10, 10, 10, 10)
        workspace_canvas_layout.setSpacing(6)
        workspace_canvas_layout.addWidget(QLabel("Workspace canvas preview", workspace_canvas))
        workspace_note = QLabel(
            "Use this color for large page backgrounds, dock canvases, and the empty workspace area.",
            workspace_canvas,
        )
        workspace_note.setWordWrap(True)
        workspace_note.setProperty("role", "secondary")
        workspace_canvas_layout.addWidget(workspace_note)
        secondary_layout.addWidget(workspace_canvas)
        hint = QLabel("Hint text example", secondary_panel)
        hint.setProperty("role", "hint")
        secondary_layout.addWidget(hint)
        overlay = QLabel("Overlay hint example", secondary_panel)
        overlay.setProperty("role", "overlayHint")
        overlay.setAlignment(Qt.AlignCenter)
        secondary_layout.addWidget(overlay, 0, Qt.AlignLeft)
        compact_group = QFrame(secondary_panel)
        compact_group.setProperty("role", "compactControlGroup")
        compact_group.setAttribute(Qt.WA_StyledBackground, True)
        compact_layout = QHBoxLayout(compact_group)
        compact_layout.setContentsMargins(10, 8, 10, 8)
        compact_layout.setSpacing(8)
        compact_layout.addWidget(QLabel("Compact group preview", compact_group))
        compact_chip = QLabel("Badge", compact_group)
        compact_chip.setProperty("role", "overlayHint")
        compact_layout.addWidget(compact_chip, 0, Qt.AlignLeft)
        compact_layout.addStretch(1)
        secondary_layout.addWidget(compact_group)
        layout.addWidget(secondary_panel)
        layout.addStretch(1)
        return page

    def _build_theme_preview_buttons_page(self) -> QWidget:
        page, preview_root, layout = self._create_theme_preview_page("themePreviewButtonsRoot")

        button_box = QGroupBox("Button States", preview_root)
        button_layout = QVBoxLayout(button_box)
        button_layout.setContentsMargins(14, 18, 14, 14)
        button_layout.setSpacing(10)
        top_row = QWidget(button_box)
        top_row_layout = QHBoxLayout(top_row)
        top_row_layout.setContentsMargins(0, 0, 0, 0)
        top_row_layout.setSpacing(10)
        normal_btn = QPushButton("Primary Action", top_row)
        checked_btn = QToolButton(top_row)
        checked_btn.setText("Checked")
        checked_btn.setCheckable(True)
        checked_btn.setChecked(True)
        disabled_btn = QPushButton("Disabled", top_row)
        disabled_btn.setEnabled(False)
        top_row_layout.addWidget(normal_btn)
        top_row_layout.addWidget(checked_btn)
        top_row_layout.addWidget(disabled_btn)
        top_row_layout.addStretch(1)
        button_layout.addWidget(top_row)

        help_row = QWidget(button_box)
        help_row_layout = QHBoxLayout(help_row)
        help_row_layout.setContentsMargins(0, 0, 0, 0)
        help_row_layout.setSpacing(10)
        help_btn = _create_round_help_button(self, "theme-settings")
        help_btn.setParent(help_row)
        help_btn.setToolTip("Round help button preview")
        help_disabled = _create_round_help_button(self, "settings")
        help_disabled.setParent(help_row)
        help_disabled.setEnabled(False)
        help_row_layout.addWidget(QLabel("Round Help Buttons", help_row))
        help_row_layout.addWidget(help_btn)
        help_row_layout.addWidget(help_disabled)
        help_row_layout.addStretch(1)
        button_layout.addWidget(help_row)
        layout.addWidget(button_box)
        layout.addStretch(1)
        return page

    def _build_theme_preview_inputs_page(self) -> QWidget:
        page, preview_root, layout = self._create_theme_preview_page("themePreviewInputsRoot")

        editor_box = QGroupBox("Editors", preview_root)
        editor_grid = QGridLayout(editor_box)
        self._configure_grid(editor_grid)
        preview_line_edit = QLineEdit("Focused line edit", editor_box)
        preview_line_edit.setPlaceholderText("Placeholder preview")
        preview_combo = FocusWheelComboBox(editor_box)
        preview_combo.addItems(["Global", "Europe", "United States"])
        preview_combo.setCurrentIndex(1)
        preview_spin = FocusWheelSpinBox(editor_box)
        preview_spin.setRange(0, 100)
        preview_spin.setValue(42)
        disabled_edit = QLineEdit("Disabled", editor_box)
        disabled_edit.setEnabled(False)
        editor_grid.addWidget(self._make_label("Line Edit"), 0, 0)
        editor_grid.addWidget(preview_line_edit, 0, 1)
        editor_grid.addWidget(
            self._make_hint("Use this field to test focus, placeholder, and border styling."),
            0,
            2,
        )
        editor_grid.addWidget(self._make_label("Combo Box"), 1, 0)
        editor_grid.addWidget(preview_combo, 1, 1)
        editor_grid.addWidget(
            self._make_hint("Dropdowns inherit the same input palette and focus rules."), 1, 2
        )
        editor_grid.addWidget(self._make_label("Spin Box"), 2, 0)
        editor_grid.addWidget(preview_spin, 2, 1)
        editor_grid.addWidget(
            self._make_hint(
                "Numeric editors preview the same QAbstractSpinBox chrome used elsewhere."
            ),
            2,
            2,
        )
        editor_grid.addWidget(self._make_label("Disabled"), 3, 0)
        editor_grid.addWidget(disabled_edit, 3, 1)
        editor_grid.addWidget(
            self._make_hint(
                "Disabled fields preview their own background, text, and border settings."
            ),
            3,
            2,
        )
        layout.addWidget(editor_box)

        indicator_box = QGroupBox("Indicators", preview_root)
        indicator_layout = QHBoxLayout(indicator_box)
        indicator_layout.setContentsMargins(14, 18, 14, 14)
        indicator_layout.setSpacing(12)
        preview_check = QCheckBox("Checked checkbox", indicator_box)
        preview_check.setChecked(True)
        preview_radio = QRadioButton("Radio option", indicator_box)
        preview_radio.setChecked(True)
        indicator_disabled = QCheckBox("Disabled", indicator_box)
        indicator_disabled.setEnabled(False)
        indicator_layout.addWidget(preview_check)
        indicator_layout.addWidget(preview_radio)
        indicator_layout.addWidget(indicator_disabled)
        indicator_layout.addStretch(1)
        layout.addWidget(indicator_box)

        slider_box = QGroupBox("Sliders", preview_root)
        slider_layout = QGridLayout(slider_box)
        self._configure_grid(slider_layout)
        preview_slider = FocusWheelSlider(Qt.Horizontal, slider_box)
        preview_slider.setRange(0, 100)
        preview_slider.setValue(62)
        preview_slider.setTickInterval(25)
        preview_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        preview_vertical_slider = FocusWheelSlider(Qt.Vertical, slider_box)
        preview_vertical_slider.setRange(0, 100)
        preview_vertical_slider.setValue(38)
        preview_vertical_slider.setTickInterval(25)
        preview_vertical_slider.setTickPosition(QSlider.TickPosition.TicksBothSides)
        preview_vertical_slider.setMinimumHeight(112)
        disabled_slider = FocusWheelSlider(Qt.Horizontal, slider_box)
        disabled_slider.setRange(0, 100)
        disabled_slider.setValue(42)
        disabled_slider.setEnabled(False)
        slider_layout.addWidget(self._make_label("Horizontal"), 0, 0)
        slider_layout.addWidget(preview_slider, 0, 1)
        slider_layout.addWidget(
            self._make_hint("Preview slider track, fill, handle, hover, and sizing."),
            0,
            2,
        )
        slider_layout.addWidget(self._make_label("Vertical"), 1, 0)
        slider_layout.addWidget(preview_vertical_slider, 1, 1)
        slider_layout.addWidget(
            self._make_hint(
                "Vertical sliders use the same token set with orientation-aware sizing."
            ),
            1,
            2,
        )
        slider_layout.addWidget(self._make_label("Disabled"), 2, 0)
        slider_layout.addWidget(disabled_slider, 2, 1)
        slider_layout.addWidget(
            self._make_hint(
                "Disabled sliders preview their separate track, handle, and border colors."
            ),
            2,
            2,
        )
        layout.addWidget(slider_box)
        layout.addStretch(1)
        preview_line_edit.setFocus(Qt.OtherFocusReason)
        return page

    def _build_theme_preview_data_views_page(self) -> QWidget:
        page, preview_root, layout = self._create_theme_preview_page("themePreviewDataViewsRoot")

        data_box = QGroupBox("Tables, Lists & Progress", preview_root)
        data_layout = QVBoxLayout(data_box)
        data_layout.setContentsMargins(14, 18, 14, 14)
        data_layout.setSpacing(10)
        preview_table = QTableWidget(3, 3, data_box)
        preview_table.setAlternatingRowColors(True)
        preview_table.setHorizontalHeaderLabels(["ID", "Title", "Status"])
        preview_table.verticalHeader().setVisible(False)
        preview_table.setItem(0, 0, QTableWidgetItem("1"))
        preview_table.setItem(0, 1, QTableWidgetItem("Orbit"))
        preview_table.setItem(0, 2, QTableWidgetItem("Active"))
        preview_table.setItem(1, 0, QTableWidgetItem("2"))
        preview_table.setItem(1, 1, QTableWidgetItem("Subconscious"))
        preview_table.setItem(1, 2, QTableWidgetItem("Pending"))
        preview_table.setItem(2, 0, QTableWidgetItem("3"))
        preview_table.setItem(2, 1, QTableWidgetItem("Guided Drift"))
        preview_table.setItem(2, 2, QTableWidgetItem("Archived"))
        preview_table.selectRow(1)
        preview_table.setMinimumHeight(170)
        data_layout.addWidget(preview_table)
        list_row = QWidget(data_box)
        list_row_layout = QHBoxLayout(list_row)
        list_row_layout.setContentsMargins(0, 0, 0, 0)
        list_row_layout.setSpacing(10)
        preview_list = QListWidget(list_row)
        preview_list.addItems(["Saved Theme", "Catalog Search", "History Snapshot"])
        preview_list.setCurrentRow(0)
        preview_list.setMinimumHeight(120)
        browser = QTextBrowser(list_row)
        browser.setPlainText(
            "Text browsers and previews inherit the table/list palette and selection styling."
        )
        browser.setMinimumHeight(120)
        list_row_layout.addWidget(preview_list, 1)
        list_row_layout.addWidget(browser, 1)
        data_layout.addWidget(list_row)
        progress = QProgressBar(data_box)
        progress.setRange(0, 100)
        progress.setValue(68)
        progress.setFormat("Indexing %p%")
        data_layout.addWidget(progress)
        layout.addWidget(data_box)
        layout.addStretch(1)
        return page

    def _build_theme_preview_navigation_page(self) -> QWidget:
        page, preview_root, layout = self._create_theme_preview_page("themePreviewNavigationRoot")

        menu_box = QGroupBox("Menus & Tabs", preview_root)
        menu_layout = QVBoxLayout(menu_box)
        menu_layout.setContentsMargins(14, 18, 14, 14)
        menu_layout.setSpacing(8)
        preview_menu_bar = QMenuBar(menu_box)
        preview_file_menu = preview_menu_bar.addMenu("File")
        preview_file_menu.addAction("New")
        preview_file_menu.addAction("Open")
        preview_view_menu = preview_menu_bar.addMenu("View")
        preview_view_menu.addAction("Theme")
        menu_layout.addWidget(preview_menu_bar)
        preview_tabs = QTabWidget(menu_box)
        preview_tabs.setDocumentMode(True)
        preview_tabs.addTab(QLabel("Selected tab content", preview_tabs), "Selected")
        preview_tabs.addTab(QLabel("Inactive tab content", preview_tabs), "Other Tab")
        menu_layout.addWidget(preview_tabs)
        preview_toolbar = QToolBar("Preview Toolbar", menu_box)
        preview_toolbar.setObjectName("themePreviewToolbar")
        preview_toolbar.addAction("Refresh")
        preview_toolbar.addAction("Export")
        preview_toolbar.addSeparator()
        toolbar_label = QLabel("Toolbar label", preview_toolbar)
        preview_toolbar.addWidget(toolbar_label)
        menu_layout.addWidget(preview_toolbar)
        preview_status = QStatusBar(menu_box)
        preview_status.setObjectName("themePreviewStatusBar")
        preview_status.showMessage("Status preview: 3 ready, 1 warning")
        preview_status.addPermanentWidget(QLabel("Profile: Demo", preview_status))
        menu_layout.addWidget(preview_status)
        layout.addWidget(menu_box)

        header_box = QGroupBox("Headers", preview_root)
        header_layout = QVBoxLayout(header_box)
        header_layout.setContentsMargins(14, 18, 14, 14)
        header_layout.setSpacing(8)
        header_table = QTableWidget(2, 2, header_box)
        header_table.setHorizontalHeaderLabels(["Column", "Value"])
        header_table.verticalHeader().setVisible(False)
        header_table.setItem(0, 0, QTableWidgetItem("Status"))
        header_table.setItem(0, 1, QTableWidgetItem("Active"))
        header_table.setItem(1, 0, QTableWidgetItem("Owner"))
        header_table.setItem(1, 1, QTableWidgetItem("Cosmowyn Records"))
        header_layout.addWidget(header_table)
        layout.addWidget(header_box)
        layout.addStretch(1)
        return page

    def _build_theme_preview_action_ribbon_page(self) -> QWidget:
        page, preview_root, layout = self._create_theme_preview_page("themePreviewActionRibbonRoot")

        ribbon_box = QGroupBox("Ribbon Over Workspace Tabs", preview_root)
        ribbon_layout = QVBoxLayout(ribbon_box)
        ribbon_layout.setContentsMargins(14, 18, 14, 14)
        ribbon_layout.setSpacing(8)
        intro = QLabel(
            "This preview keeps the action ribbon directly above tab chrome so you can judge separation and color contrast. Ribbon buttons still use the shared Buttons styling in this pass.",
            ribbon_box,
        )
        intro.setWordWrap(True)
        intro.setProperty("role", "secondary")
        ribbon_layout.addWidget(intro)

        preview_toolbar = QToolBar("Preview Action Ribbon", ribbon_box)
        preview_toolbar.setObjectName("actionRibbonToolbar")
        preview_toolbar.setProperty("role", "actionRibbonToolbar")
        preview_toolbar.setToolButtonStyle(Qt.ToolButtonTextOnly)
        for label, checked in (("Catalog", True), ("Search", False), ("Releases", False)):
            button = QToolButton(preview_toolbar)
            button.setText(label)
            button.setCheckable(True)
            button.setChecked(checked)
            button.setProperty("role", "actionRibbonButton")
            preview_toolbar.addWidget(button)
        preview_toolbar.addSeparator()
        pinned_button = QToolButton(preview_toolbar)
        pinned_button.setText("Pinned")
        pinned_button.setCheckable(True)
        pinned_button.setProperty("role", "actionRibbonButton")
        preview_toolbar.addWidget(pinned_button)
        ribbon_layout.addWidget(preview_toolbar)

        workspace_tabs = QTabWidget(ribbon_box)
        workspace_tabs.setDocumentMode(True)
        first_page = QWidget(workspace_tabs)
        first_page.setProperty("role", "workspaceCanvas")
        first_layout = QVBoxLayout(first_page)
        first_layout.setContentsMargins(14, 14, 14, 14)
        first_layout.setSpacing(8)
        first_layout.addWidget(QLabel("Workspace tab content preview", first_page))
        first_note = QLabel(
            "Use the separate Action Ribbon tab to differentiate ribbon chrome from the dock and tab chrome below it.",
            first_page,
        )
        first_note.setWordWrap(True)
        first_note.setProperty("role", "secondary")
        first_layout.addWidget(first_note)
        first_layout.addStretch(1)
        second_page = QWidget(workspace_tabs)
        second_page.setProperty("role", "workspaceCanvas")
        second_layout = QVBoxLayout(second_page)
        second_layout.setContentsMargins(14, 14, 14, 14)
        second_layout.setSpacing(8)
        second_layout.addWidget(QLabel("Inactive workspace tab", second_page))
        second_layout.addStretch(1)
        workspace_tabs.addTab(first_page, "Catalog Cleanup")
        workspace_tabs.addTab(second_page, "Release Browser")
        ribbon_layout.addWidget(workspace_tabs)

        layout.addWidget(ribbon_box)
        layout.addStretch(1)
        return page

    def _build_theme_preview_blob_icons_page(self) -> QWidget:
        page, preview_root, layout = self._create_theme_preview_page("themePreviewBlobIconsRoot")

        preview_box = QGroupBox("Blob Badge Preview", preview_root)
        preview_layout = QGridLayout(preview_box)
        self._configure_grid(preview_layout)

        def _add_preview_row(
            row_index: int,
            *,
            kind: str,
            label_text: str,
            size_text: str,
            help_text: str,
        ) -> None:
            icon_label = QLabel(preview_box)
            icon_label.setFixedSize(34, 34)
            icon_label.setAlignment(Qt.AlignCenter)
            icon_label.setStyleSheet(
                "border: 1px solid palette(mid); border-radius: 6px; background: palette(base);"
            )
            sample_text = QLabel(size_text, preview_box)
            sample_text.setProperty("role", "secondary")
            sample_row = QWidget(preview_box)
            sample_layout = QHBoxLayout(sample_row)
            sample_layout.setContentsMargins(0, 0, 0, 0)
            sample_layout.setSpacing(10)
            sample_layout.addWidget(icon_label)
            sample_layout.addWidget(sample_text)
            sample_layout.addStretch(1)
            self._blob_icon_preview_labels[kind] = icon_label
            self._add_row(
                preview_layout,
                row_index,
                label_text,
                sample_row,
                help_text,
            )

        preview_specs = (
            (
                "audio_managed",
                "Managed Audio Column",
                "71.3 MB",
                "Preview for primary audio badges when the source is stored as a managed file.",
            ),
            (
                "audio_database",
                "Database Audio Column",
                "71.3 MB",
                "Preview for primary audio badges when the source is stored directly inside the database.",
            ),
            (
                "audio_lossy_managed",
                "Managed Lossy Audio Column",
                "9.8 MB",
                "Preview for lossy primary audio badges stored as a managed file.",
            ),
            (
                "audio_lossy_database",
                "Database Lossy Audio Column",
                "9.8 MB",
                "Preview for lossy primary audio badges stored directly inside the database.",
            ),
            (
                "image_managed",
                "Managed Image Column",
                "2.4 MB",
                "Preview for Album Art and inherited image BLOB fields stored as managed files.",
            ),
            (
                "image_database",
                "Database Image Column",
                "2.4 MB",
                "Preview for Album Art and inherited image BLOB fields stored directly inside the database.",
            ),
        )
        for row_index, (kind, label_text, size_text, help_text) in enumerate(preview_specs):
            _add_preview_row(
                row_index,
                kind=kind,
                label_text=label_text,
                size_text=size_text,
                help_text=help_text,
            )

        custom_hint_box = QGroupBox("Custom Column Override", preview_root)
        custom_hint_layout = QVBoxLayout(custom_hint_box)
        custom_hint_layout.setContentsMargins(14, 18, 14, 14)
        custom_hint_layout.setSpacing(8)
        hint = QLabel(
            "Each custom BLOB column can stay on the global storage-aware icon or store its own override with the same system-icon, emoji, and custom-image options.",
            custom_hint_box,
        )
        hint.setWordWrap(True)
        hint.setProperty("role", "secondary")
        custom_hint_layout.addWidget(hint)
        layout.addWidget(preview_box)
        layout.addWidget(custom_hint_box)
        layout.addStretch(1)
        return page

    def _build_theme_preview_advanced_page(self) -> QWidget:
        page, preview_root, layout = self._create_theme_preview_page("themePreviewAdvancedRoot")

        advanced_box = QGroupBox("Selector Playground", preview_root)
        advanced_layout = QVBoxLayout(advanced_box)
        advanced_layout.setContentsMargins(14, 18, 14, 14)
        advanced_layout.setSpacing(8)
        intro = QLabel(
            "Use this compact playground while writing Advanced QSS. The preview follows the advanced tab so you can test selectors without the other theme categories crowding the pane.",
            advanced_box,
        )
        intro.setProperty("role", "secondary")
        intro.setWordWrap(True)
        advanced_layout.addWidget(intro)
        playground_row = QWidget(advanced_box)
        playground_row.setObjectName("themePreviewPlayground")
        playground_layout = QHBoxLayout(playground_row)
        playground_layout.setContentsMargins(0, 0, 0, 0)
        playground_layout.setSpacing(10)
        advanced_button = QPushButton("Preview Button", playground_row)
        advanced_button.setObjectName("themePreviewButton")
        advanced_input = QLineEdit("Preview Field", playground_row)
        advanced_input.setObjectName("themePreviewField")
        advanced_help = _create_round_help_button(self, "theme-settings")
        advanced_help.setParent(playground_row)
        advanced_help.setObjectName("themePreviewHelpButton")
        playground_layout.addWidget(advanced_button)
        playground_layout.addWidget(advanced_input, 1)
        playground_layout.addWidget(advanced_help)
        advanced_layout.addWidget(playground_row)
        selector_hint = QLabel(
            'Example object names: `#themePreviewButton`, `#themePreviewField`, `#themePreviewHelpButton`, `#themePreviewPlayground QPushButton`, and `QToolButton[role="actionRibbonButton"]`.',
            advanced_box,
        )
        selector_hint.setProperty("role", "hint")
        selector_hint.setWordWrap(True)
        advanced_layout.addWidget(selector_hint)
        layout.addWidget(advanced_box)
        layout.addStretch(1)
        return page

    def _sync_theme_preview_to_builder_tab(self, index: int) -> None:
        if not hasattr(self, "_theme_builder_page_keys") or not self._theme_builder_page_keys:
            return
        if index < 0 or index >= len(self._theme_builder_page_keys):
            index = 0
        page_key = self._theme_builder_page_keys[index]
        preview_index = self._theme_preview_tab_indices.get(page_key, 0)
        self.theme_preview_tabs.setCurrentIndex(preview_index)
        self._queue_theme_preview_update()

    def _queue_theme_preview_update(self, *_args) -> None:
        if not self._theme_change_tracking_enabled:
            return
        self._theme_preview_timer.start()

    def _refresh_theme_previews(self) -> None:
        try:
            theme_values = self._theme_value_payload()
        except Exception:
            return
        qss_issues = self._theme_qss_validation_issues(theme_values.get("custom_qss"))
        preview_values = dict(theme_values)
        if qss_issues:
            preview_values["custom_qss"] = str(self._theme_last_valid_custom_qss_preview or "")
        else:
            self._theme_last_valid_custom_qss_preview = str(theme_values.get("custom_qss") or "")
        stylesheet = build_app_theme_stylesheet(preview_values)
        for widget in getattr(self, "_theme_preview_roots", []):
            widget.setStyleSheet(stylesheet)
            _repolish_qss_widget_tree(widget)
        self._refresh_blob_icon_previews()
        self._update_theme_qss_status(qss_issues)
        current_preview_name = self.theme_preview_tabs.tabText(
            self.theme_preview_tabs.currentIndex()
        )
        if self._theme_builder_page_keys[self.theme_builder_tabs.currentIndex()] == "blob_icons":
            self.theme_preview_status_label.setText(
                "Showing the media icon preview for the current profile draft. Managed-file and database-backed audio and image badges can each use platform icons, emojis, or compressed custom images stored inside the database."
            )
        else:
            self.theme_preview_status_label.setText(
                "Showing the "
                + current_preview_name.lower()
                + " preview for "
                + (
                    f"saved theme '{self._current_theme_preset_name()}'"
                    if self._current_theme_preset_name()
                    else "the current custom draft"
                )
                + f". {len(self._theme_color_edits)} color slots and {len(self._theme_metric_spins)} geometry/typography controls are available in the builder."
            )
        if qss_issues:
            self.theme_preview_status_label.setText(
                self.theme_preview_status_label.text()
                + " Advanced QSS preview is holding the last valid stylesheet until the current editor syntax issue is fixed."
            )
        if self.theme_live_preview_check.isChecked():
            self._apply_live_theme_preview(preview_values)
        elif (
            hasattr(self, "theme_preview_status_label")
            and self._theme_builder_page_keys[self.theme_builder_tabs.currentIndex()]
            != "blob_icons"
        ):
            self.theme_preview_status_label.setText(
                self.theme_preview_status_label.text()
                + " Turn on Live Preview to apply the draft to the whole running app while you edit."
            )

    @staticmethod
    def _theme_qss_validation_issues(custom_qss: object) -> list:
        return validate_qss_document(str(custom_qss or ""))

    def _update_theme_qss_status(self, issues: list) -> None:
        status_label = getattr(self, "theme_custom_qss_status_label", None)
        if status_label is None:
            return
        if not issues:
            status_label.setProperty("role", "secondary")
            status_label.setText(
                "Advanced QSS is syntactically ready. Autocomplete and Insert Full Template both generate valid starter rules you can trim down, and you can still edit the raw QSS directly."
            )
            return
        first_issue = issues[0]
        status_label.setProperty("role", "hint")
        status_label.setText(
            f"Advanced QSS syntax issue at line {first_issue.line}, column {first_issue.column}: {first_issue.message} "
            "Live preview is keeping the last valid advanced QSS until this is fixed."
        )

    def _refresh_blob_icon_previews(self) -> None:
        specs = self._blob_icon_value_payload()
        style = self.style() if hasattr(self, "style") else None
        for kind, label in self._blob_icon_preview_labels.items():
            icon = icon_from_blob_icon_spec(
                specs.get(kind),
                kind=kind,
                style=style,
                fallback_spec=self._blob_icon_original_values.get(kind),
                size=22,
            )
            label.setPixmap(icon.pixmap(24, 24))

    def _apply_live_theme_preview(self, values: dict[str, object]) -> None:
        owner = self.parent()
        if owner is not None and callable(getattr(owner, "_apply_theme", None)):
            owner._apply_theme(values)

    def _restore_original_application_theme(self) -> None:
        owner = self.parent()
        if owner is not None and callable(getattr(owner, "_apply_theme", None)):
            owner._apply_theme(self._theme_original_values)

    def _handle_theme_live_preview_toggled(self, checked: bool) -> None:
        if checked:
            self._refresh_theme_previews()
        else:
            self._restore_original_application_theme()

    def _set_theme_preview_pane_visible(self, visible: bool) -> None:
        visible = bool(visible)
        if hasattr(self, "theme_preview_host"):
            self.theme_preview_host.setVisible(visible)
        if hasattr(self, "theme_splitter"):
            if visible:
                self.theme_splitter.setSizes([720, 420])
            else:
                self.theme_splitter.setSizes([1, 0])

    def _set_theme_builder_hints_visible(self, visible: bool) -> None:
        visible = bool(visible)
        theme_page = getattr(self, "theme_page", None)
        if theme_page is None:
            return
        for label in theme_page.findChildren(QLabel):
            if label.property("role") == "hint":
                label.setVisible(visible)

    def _handle_theme_dialog_finished(self, result: int) -> None:
        self._theme_preview_timer.stop()
        if result != QDialog.Accepted:
            self._restore_original_application_theme()

    def _bind_theme_field_change_tracking(self) -> None:
        self.theme_font_family_combo.currentFontChanged.connect(self._mark_theme_selection_custom)
        self.theme_auto_contrast_check.toggled.connect(self._mark_theme_selection_custom)
        self.theme_live_preview_check.toggled.connect(self._handle_theme_live_preview_toggled)
        self.theme_show_hints_check.toggled.connect(self._set_theme_builder_hints_visible)
        self.theme_show_preview_check.toggled.connect(self._set_theme_preview_pane_visible)
        self.theme_custom_qss_edit.textChanged.connect(self._mark_theme_selection_custom)
        for edit in self._theme_color_edits.values():
            edit.textChanged.connect(self._mark_theme_selection_custom)
            edit.textChanged.connect(self._queue_theme_preview_update)
        for spin in self._theme_metric_spins.values():
            spin.valueChanged.connect(self._mark_theme_selection_custom)
            spin.valueChanged.connect(self._queue_theme_preview_update)
        self.theme_font_family_combo.currentFontChanged.connect(self._queue_theme_preview_update)
        self.theme_auto_contrast_check.toggled.connect(self._queue_theme_preview_update)
        self.theme_custom_qss_edit.textChanged.connect(self._queue_theme_preview_update)
        for editor in self._blob_icon_editors.values():
            editor.specChanged.connect(self._queue_theme_preview_update)
        self.theme_preset_combo.currentIndexChanged.connect(self._update_theme_preset_actions)
        self.theme_load_button.clicked.connect(self._load_selected_theme_preset)
        self.theme_save_button.clicked.connect(self._save_current_theme_preset)
        self.theme_delete_button.clicked.connect(self._delete_selected_theme_preset)
        self.theme_import_button.clicked.connect(self._import_theme_from_file)
        self.theme_export_button.clicked.connect(self._export_theme_to_file)
        self.theme_reset_button.clicked.connect(self._reset_theme_to_defaults)

    def _collect_qss_reference_entries(self) -> list[QssReferenceEntry]:
        app = QApplication.instance()
        widgets: list[QWidget] = []
        if app is not None:
            widgets = [widget for widget in app.topLevelWidgets() if isinstance(widget, QWidget)]
        if self not in widgets:
            widgets.append(self)
        for widget in widgets:
            _ensure_qss_widget_object_names(widget)
        return collect_qss_reference_entries(widgets)

    def _refresh_qss_selector_reference(self) -> None:
        self._qss_reference_entries = self._collect_qss_reference_entries()
        self.theme_custom_qss_edit.set_reference_entries(self._qss_reference_entries)
        self._apply_qss_reference_filter()

    def _apply_qss_reference_filter(self) -> None:
        filter_text = str(self.qss_reference_filter_edit.text() or "").strip().lower()
        if not filter_text:
            visible_entries = list(self._qss_reference_entries)
        else:
            visible_entries = [
                entry
                for entry in self._qss_reference_entries
                if filter_text in entry.category.lower()
                or filter_text in entry.selector.lower()
                or filter_text in entry.details.lower()
            ]
        self._qss_filtered_reference_entries = visible_entries
        self.qss_reference_table.setRowCount(0)
        for entry in visible_entries:
            row = self.qss_reference_table.rowCount()
            self.qss_reference_table.insertRow(row)
            self.qss_reference_table.setItem(row, 0, QTableWidgetItem(entry.category))
            self.qss_reference_table.setItem(row, 1, QTableWidgetItem(entry.selector))
            self.qss_reference_table.setItem(row, 2, QTableWidgetItem(entry.details))
        total = len(self._qss_reference_entries)
        shown = len(visible_entries)
        if total == 0:
            self.qss_reference_status_label.setText(
                "No selectors discovered yet. Open another window or dialog and refresh the catalog."
            )
        elif shown == total:
            self.qss_reference_status_label.setText(
                f"{total} selectors available for autocomplete and copy/insert."
            )
        else:
            self.qss_reference_status_label.setText(
                f"Showing {shown} of {total} selectors after filtering."
            )
        self._update_qss_reference_actions()

    def _selected_qss_selector(self) -> str:
        rows = self.qss_reference_table.selectionModel().selectedRows()
        if not rows:
            return ""
        item = self.qss_reference_table.item(rows[0].row(), 1)
        return item.text().strip() if item is not None else ""

    def _selected_qss_reference_entry(self) -> QssReferenceEntry | None:
        rows = self.qss_reference_table.selectionModel().selectedRows()
        if not rows:
            return None
        row = rows[0].row()
        if row < 0 or row >= len(self._qss_filtered_reference_entries):
            return None
        return self._qss_filtered_reference_entries[row]

    def _update_qss_reference_actions(self) -> None:
        has_selection = bool(self._selected_qss_selector())
        self.qss_reference_copy_button.setEnabled(has_selection)
        self.qss_reference_insert_button.setEnabled(has_selection)
        self.qss_reference_insert_template_button.setEnabled(has_selection)

    def _copy_selected_qss_selector(self) -> None:
        selector = self._selected_qss_selector()
        if not selector:
            return
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(selector)

    def _insert_selected_qss_selector(self) -> None:
        selector = self._selected_qss_selector()
        if not selector:
            return
        self.theme_qss_tabs.setCurrentIndex(0)
        cursor = self.theme_custom_qss_edit.textCursor()
        cursor.insertText(selector)
        self.theme_custom_qss_edit.setTextCursor(cursor)
        self.theme_custom_qss_edit.setFocus()

    def _insert_selected_qss_template(self) -> None:
        entry = self._selected_qss_reference_entry()
        if entry is None:
            return
        self.theme_qss_tabs.setCurrentIndex(0)
        self.theme_custom_qss_edit.insert_template_for_reference_entry(entry)
        self.theme_custom_qss_edit.setFocus()

    def _theme_value_payload(self) -> dict[str, object]:
        values = {
            "font_family": self.theme_font_family_combo.currentFont().family().strip(),
            "auto_contrast_enabled": self.theme_auto_contrast_check.isChecked(),
            "custom_qss": self.theme_custom_qss_edit.toPlainText(),
            "selected_name": self._current_theme_preset_name(),
        }
        for key in self._theme_color_edits:
            values[key] = self._theme_color_edits[key].text().strip()
        for key, spin in self._theme_metric_spins.items():
            values[key] = int(spin.value())
        return values

    def _blob_icon_value_payload(self) -> dict[str, dict[str, object]]:
        values = dict(self._blob_icon_settings or {})
        for kind, editor in self._blob_icon_editors.items():
            values[kind] = editor.current_spec()
        return normalize_blob_icon_settings(values)

    def _theme_preview_value_payload(self) -> dict[str, object]:
        values = dict(self._theme_settings or {})
        values["selected_name"] = self._current_theme_preset_name()

        font_combo = getattr(self, "theme_font_family_combo", None)
        if font_combo is not None:
            values["font_family"] = font_combo.currentFont().family().strip()

        auto_contrast_check = getattr(self, "theme_auto_contrast_check", None)
        if auto_contrast_check is not None:
            values["auto_contrast_enabled"] = auto_contrast_check.isChecked()

        custom_qss_edit = getattr(self, "theme_custom_qss_edit", None)
        if custom_qss_edit is not None:
            values["custom_qss"] = custom_qss_edit.toPlainText()

        for theme_key, theme_edit in self._theme_color_edits.items():
            values[theme_key] = theme_edit.text().strip()
        for metric_key, spin in self._theme_metric_spins.items():
            values[metric_key] = int(spin.value())
        return values

    def _apply_theme_values_to_fields(
        self, theme_values: dict[str, object], *, selected_name: str = ""
    ) -> None:
        self._theme_change_tracking_enabled = False
        try:
            font_family = str(theme_values.get("font_family") or "").strip()
            if font_family:
                self.theme_font_family_combo.setCurrentFont(QFont(font_family))
            self.theme_auto_contrast_check.setChecked(
                bool(theme_values.get("auto_contrast_enabled", True))
            )
            self.theme_custom_qss_edit.setPlainText(str(theme_values.get("custom_qss") or ""))
            for key, edit in self._theme_color_edits.items():
                edit.setText(str(theme_values.get(key) or "").strip())
            for key, spin in self._theme_metric_spins.items():
                try:
                    value = int(theme_values.get(key) or spin.value())
                except Exception:
                    value = spin.value()
                spin.setValue(max(spin.minimum(), min(spin.maximum(), value)))
            self._set_theme_preset_selection(selected_name)
        finally:
            self._theme_change_tracking_enabled = True
        self._update_theme_preset_actions()
        self._refresh_theme_previews()

    def _refresh_theme_preset_combo(self) -> None:
        current_name = self._current_theme_preset_name()
        self.theme_preset_combo.blockSignals(True)
        self.theme_preset_combo.clear()
        self.theme_preset_combo.addItem(self.CUSTOM_THEME_LABEL, "")
        for name in self._bundled_theme_order:
            if name not in self._stored_themes:
                continue
            self.theme_preset_combo.addItem(name, name)
            self.theme_preset_combo.setItemData(
                self.theme_preset_combo.count() - 1,
                f"Starter theme: {self._bundled_theme_descriptions.get(name, '')}".strip(),
                Qt.ToolTipRole,
            )
        for name in sorted(
            theme_name
            for theme_name in self._stored_themes
            if theme_name not in self._bundled_theme_names
        ):
            self.theme_preset_combo.addItem(name, name)
            self.theme_preset_combo.setItemData(
                self.theme_preset_combo.count() - 1,
                "Saved custom theme preset.",
                Qt.ToolTipRole,
            )
        self.theme_preset_combo.blockSignals(False)
        self._set_theme_preset_selection(current_name)

    def _set_theme_preset_selection(self, theme_name: str) -> None:
        clean_name = str(theme_name or "").strip()
        index = self.theme_preset_combo.findData(clean_name)
        if index < 0:
            index = 0
        self.theme_preset_combo.blockSignals(True)
        self.theme_preset_combo.setCurrentIndex(index)
        self.theme_preset_combo.blockSignals(False)
        self._update_theme_preset_actions()

    def _current_theme_preset_name(self) -> str:
        return str(self.theme_preset_combo.currentData() or "").strip()

    def _update_theme_preset_actions(self, *_args) -> None:
        selected_name = self._current_theme_preset_name()
        has_named_theme = bool(selected_name)
        is_bundled_theme = selected_name in self._bundled_theme_names
        self.theme_load_button.setEnabled(has_named_theme)
        self.theme_delete_button.setEnabled(has_named_theme and not is_bundled_theme)
        if is_bundled_theme:
            self.theme_delete_button.setToolTip(
                "Starter themes are packaged with the app and cannot be deleted."
            )
        else:
            self.theme_delete_button.setToolTip("Delete the selected saved theme.")

    def _mark_theme_selection_custom(self, *_args) -> None:
        if not self._theme_change_tracking_enabled:
            return
        if self._current_theme_preset_name():
            self._set_theme_preset_selection("")

    def _load_selected_theme_preset(self) -> None:
        selected_name = self._current_theme_preset_name()
        if not selected_name:
            return
        theme_values = self._stored_themes.get(selected_name)
        if not theme_values:
            QMessageBox.warning(
                self, "Theme Not Found", "The selected theme preset is no longer available."
            )
            self._set_theme_preset_selection("")
            return
        self._apply_theme_values_to_fields(theme_values, selected_name=selected_name)

    def _save_current_theme_preset(self) -> None:
        suggested_name = self._current_theme_preset_name() or "My Theme"
        if suggested_name in self._bundled_theme_names:
            suggested_name = f"{suggested_name} Copy"
        custom_theme_names = sorted(
            theme_name
            for theme_name in self._stored_themes
            if theme_name not in self._bundled_theme_names
        )
        name, ok = _get_name_from_editable_choice_dialog(
            self,
            title="Save Theme",
            label="Theme name:",
            choices=custom_theme_names,
            suggested_name=suggested_name,
            placeholder="Enter a new theme name",
        )
        if not ok:
            return
        clean_name = str(name or "").strip()
        if not clean_name:
            QMessageBox.warning(
                self, "Theme Name Required", "Please enter a name for the saved theme."
            )
            return
        if clean_name in self._bundled_theme_names:
            QMessageBox.information(
                self,
                "Starter Theme Protected",
                "Bundled starter themes cannot be overwritten. Save this draft under a new name instead.",
            )
            return
        if clean_name in self._stored_themes:
            answer = QMessageBox.question(
                self,
                "Overwrite Theme",
                f"A saved theme named '{clean_name}' already exists.\n\nOverwrite it?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
        theme_values = dict(self._theme_value_payload())
        theme_values["selected_name"] = ""
        self._stored_themes[clean_name] = theme_values
        self._refresh_theme_preset_combo()
        self._set_theme_preset_selection(clean_name)

    def _delete_selected_theme_preset(self) -> None:
        selected_name = self._current_theme_preset_name()
        if not selected_name:
            return
        if selected_name in self._bundled_theme_names:
            QMessageBox.information(
                self,
                "Starter Theme Protected",
                "Bundled starter themes are packaged with the app and cannot be deleted.",
            )
            return
        answer = QMessageBox.question(
            self,
            "Delete Theme",
            f"Remove the saved theme '{selected_name}'?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self._stored_themes.pop(selected_name, None)
        self._refresh_theme_preset_combo()
        self._set_theme_preset_selection("")

    def _import_theme_from_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import Theme",
            str(Path.home()),
            "Theme JSON (*.json)",
        )
        if not path:
            return
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception as exc:
            QMessageBox.warning(self, "Import Theme", f"Could not read theme file:\n{exc}")
            return

        theme_values = payload.get("theme") if isinstance(payload, dict) else None
        if not isinstance(theme_values, dict):
            theme_values = payload if isinstance(payload, dict) else None
        if not isinstance(theme_values, dict):
            QMessageBox.warning(
                self,
                "Import Theme",
                "The selected file does not contain a valid theme payload.",
            )
            return
        imported_name = ""
        if isinstance(payload, dict):
            imported_name = str(payload.get("name") or "").strip()
        self._apply_theme_values_to_fields(theme_values, selected_name="")
        self._set_theme_preset_selection("")
        if imported_name:
            self.theme_preview_status_label.setText(
                f"Imported theme draft '{imported_name}'. Save it to the library if you want to keep it as a preset."
            )

    def _export_theme_to_file(self) -> None:
        suggested_name = self._current_theme_preset_name() or "custom-theme"
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", suggested_name.strip()) or "custom-theme"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Theme",
            str(Path.home() / f"{safe_name}.json"),
            "Theme JSON (*.json)",
        )
        if not path:
            return
        payload = {
            "schema": "isrc-manager-theme",
            "version": 2,
            "name": self._current_theme_preset_name() or "Custom Theme",
            "theme": {
                **normalize_app_theme_settings(self._theme_value_payload()),
                "selected_name": "",
            },
        }
        try:
            Path(path).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        except Exception as exc:
            QMessageBox.warning(self, "Export Theme", f"Could not save theme file:\n{exc}")
            return
        QMessageBox.information(self, "Export Theme", f"Saved theme to:\n{path}")

    def _reset_theme_to_defaults(self) -> None:
        answer = QMessageBox.question(
            self,
            "Reset Theme",
            "Reset the current theme draft back to the built-in defaults?\n\nThis does not remove any saved presets.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        defaults = default_theme_settings()
        defaults["selected_name"] = ""
        self._apply_theme_values_to_fields(defaults, selected_name="")
        self._set_theme_preset_selection("")

    def _sync_color_swatch(self, key: str) -> None:
        edit = self._theme_color_edits[key]
        swatch = self._theme_color_swatches[key]
        color_text = edit.text().strip()

        def apply_swatch(fill_color: QColor, text_color: QColor) -> None:
            border_color = (
                fill_color.darker(140)
                if fill_color.lightnessF() >= 0.58
                else fill_color.lighter(165)
            )
            swatch.setStyleSheet(
                "; ".join(
                    (
                        f"background-color: {fill_color.name().upper()}",
                        f"color: {text_color.name().upper()}",
                        f"border: 1px solid {border_color.name().upper()}",
                        "border-radius: 5px",
                    )
                )
            )

        if not color_text:
            effective_value = str(
                build_effective_theme_settings(self._theme_preview_value_payload()).get(key) or ""
            )
            effective_color = QColor(effective_value)
            if effective_color.isValid():
                fill_color = effective_color
            else:
                fill_color = QColor("#D1D5DB")
            text_color = QColor("#111827") if fill_color.lightnessF() >= 0.55 else QColor("#F9FAFB")
            swatch.setText("A")
            swatch.setToolTip(
                "Using the automatic derived/default color for this slot."
                + (
                    f"\nResolved preview: {fill_color.name().upper()}"
                    if fill_color.isValid()
                    else ""
                )
            )
            apply_swatch(fill_color, text_color)
        else:
            color = QColor(color_text)
            if color.isValid():
                text_color = QColor("#111827") if color.lightnessF() >= 0.55 else QColor("#F9FAFB")
                swatch.setText("")
                swatch.setToolTip(color.name().upper())
                apply_swatch(color, text_color)
            else:
                fill_color = QColor("#F87171")
                text_color = QColor("#111827")
                swatch.setText("!")
                swatch.setToolTip(
                    "Invalid color. Use values like #112233, #abc, or named Qt colors."
                )
                apply_swatch(fill_color, text_color)

    def _pick_theme_color(self, key: str) -> None:
        current_text = self._theme_color_edits[key].text().strip()
        initial = QColor(current_text) if current_text else QColor("#ffffff")
        color = QColorDialog.getColor(initial, self, f"Choose {key.replace('_', ' ').title()}")
        if color.isValid():
            self._theme_color_edits[key].setText(color.name().upper())

    def _browse_icon(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose Icon",
            "",
            "Images (*.ico *.png *.jpg *.jpeg *.bmp)",
        )
        if path:
            self.icon_path_edit.setText(path)


__all__ = ["ApplicationSettingsThemeMixin"]

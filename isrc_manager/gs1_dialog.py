"""PySide6 dialog for editing and exporting GS1 metadata from the catalog."""

from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .services import (
    GS1BatchValidationError,
    GS1DependencyError,
    GS1ExportPlan,
    GS1MetadataGroup,
    GS1MetadataRecord,
    GS1TemplateVerificationError,
    GS1ValidationError,
)
from .services.gs1_mapping import (
    COMMON_CLASSIFICATION_CHOICES,
    COMMON_LANGUAGE_CHOICES,
    COMMON_MARKET_CHOICES,
    COMMON_PACKAGING_CHOICES,
    COMMON_STATUS_CHOICES,
    COMMON_UNIT_CHOICES,
)


def _safe_filename(text: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(text or "").strip())
    cleaned = cleaned.strip("._")
    return cleaned or "gs1_export"


class GS1MetadataEditorPage(QWidget):
    """Reusable GS1 metadata form used for a single export product group."""

    changed = Signal()

    ELEMENT_MARGIN = 2
    LABEL_MIN_WIDTH = 220
    FIELD_HEIGHT = 48
    CHECKBOX_ROW_HEIGHT = 48
    COMPACT_FIELD_MIN_WIDTH = 180
    STANDARD_FIELD_MIN_WIDTH = 380
    WIDE_FIELD_MIN_WIDTH = 520
    NOTES_MIN_HEIGHT = 176

    def __init__(self, group: GS1MetadataGroup, parent=None):
        super().__init__(parent)
        self.group = group
        self._saved_record = group.record.copy()
        self._default_record = group.default_record.copy()
        self._loading_form = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        self.group_summary_label = QLabel(self._group_summary_text())
        self.group_summary_label.setWordWrap(True)
        self.group_summary_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(self.group_summary_label)

        form_layout = QVBoxLayout()
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_layout.setSpacing(2)

        self.status_combo = self._combo(COMMON_STATUS_CHOICES)
        self.classification_combo = self._combo(COMMON_CLASSIFICATION_CHOICES)
        self.consumer_unit_check = QCheckBox("This item is sold to the consumer", self)
        self.consumer_unit_row = self._checkbox_row(self.consumer_unit_check)
        self.packaging_combo = self._combo(COMMON_PACKAGING_CHOICES)
        self.market_combo = self._combo(COMMON_MARKET_CHOICES)
        self.language_combo = self._combo(COMMON_LANGUAGE_CHOICES)
        self.description_edit = QLineEdit(self)
        self.description_edit.setMaxLength(300)
        self.brand_edit = QLineEdit(self)
        self.brand_edit.setMaxLength(70)
        self.subbrand_edit = QLineEdit(self)
        self.subbrand_edit.setMaxLength(70)
        self.quantity_edit = QLineEdit(self)
        self.unit_combo = self._combo(COMMON_UNIT_CHOICES)
        self.image_url_edit = QLineEdit(self)
        self.image_url_edit.setMaxLength(500)
        self.export_enabled_check = QCheckBox("Allow this record to be included in GS1 exports", self)
        self.export_enabled_row = self._checkbox_row(self.export_enabled_check)
        self.notes_edit = QPlainTextEdit(self)
        self.notes_edit.setPlaceholderText("Internal notes for this GS1 record.")
        self.notes_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._apply_form_metrics()

        form_layout.addWidget(self._build_form_row("Status", self.status_combo))
        form_layout.addWidget(self._build_form_row("Product Classification", self.classification_combo))
        form_layout.addWidget(self._build_form_row("Consumer Unit", self.consumer_unit_row))
        form_layout.addWidget(self._build_form_row("Packaging Type", self.packaging_combo))
        form_layout.addWidget(self._build_form_row("Target Market", self.market_combo))
        form_layout.addWidget(self._build_form_row("Language", self.language_combo))
        form_layout.addWidget(self._build_form_row("Product Description", self.description_edit))
        form_layout.addWidget(self._build_form_row("Brand", self.brand_edit))
        form_layout.addWidget(self._build_form_row("Subbrand", self.subbrand_edit))
        form_layout.addWidget(self._build_form_row("Quantity", self.quantity_edit))
        form_layout.addWidget(self._build_form_row("Unit", self.unit_combo))
        form_layout.addWidget(self._build_form_row("Image URL", self.image_url_edit))
        form_layout.addWidget(self._build_form_row("Export Enabled", self.export_enabled_row))
        form_layout.addWidget(self._build_form_row("Notes", self.notes_edit, top_aligned=True))
        root.addLayout(form_layout)
        root.addStretch(1)

        self._connect_form_signals()
        self.apply_record_to_form(self._saved_record)

    @property
    def is_loading(self) -> bool:
        return self._loading_form

    @staticmethod
    def _combo(items) -> QComboBox:
        combo = QComboBox()
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.NoInsert)
        combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        for item in items:
            combo.addItem(str(item))
        return combo

    @classmethod
    def _form_label(cls, text: str) -> QLabel:
        label = QLabel(text)
        label.setMinimumWidth(cls.LABEL_MIN_WIDTH)
        label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        return label

    def _build_form_row(self, label_text: str, widget: QWidget, *, top_aligned: bool = False) -> QWidget:
        row = QWidget(self)
        row.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed if not top_aligned else QSizePolicy.MinimumExpanding)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(
            self.ELEMENT_MARGIN,
            self.ELEMENT_MARGIN,
            self.ELEMENT_MARGIN,
            self.ELEMENT_MARGIN,
        )
        row_layout.setSpacing(14)
        label = self._form_label(label_text)
        label.setAlignment(Qt.AlignRight | (Qt.AlignTop if top_aligned else Qt.AlignVCenter))
        if widget.sizePolicy().horizontalPolicy() == QSizePolicy.Preferred:
            widget.setSizePolicy(QSizePolicy.Expanding, widget.sizePolicy().verticalPolicy())
        row_layout.addWidget(label, 0, Qt.AlignTop if top_aligned else Qt.AlignVCenter)
        row_layout.addWidget(widget, 1, Qt.AlignTop if top_aligned else Qt.AlignVCenter)
        row.setMinimumHeight(max(widget.minimumHeight(), widget.sizeHint().height()) + (self.ELEMENT_MARGIN * 2))
        return row

    def _checkbox_row(self, checkbox: QCheckBox) -> QWidget:
        checkbox.setMinimumHeight(self.CHECKBOX_ROW_HEIGHT)
        row = QWidget(self)
        row.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        row.setMinimumHeight(self.CHECKBOX_ROW_HEIGHT)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(
            self.ELEMENT_MARGIN,
            self.ELEMENT_MARGIN,
            self.ELEMENT_MARGIN,
            self.ELEMENT_MARGIN,
        )
        layout.setSpacing(8)
        layout.addWidget(checkbox, 0, Qt.AlignLeft | Qt.AlignVCenter)
        layout.addStretch(1)
        return row

    def _apply_line_edit_metrics(
        self,
        widget: QLineEdit,
        *,
        min_width: int,
        max_width: int | None = None,
    ) -> None:
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        widget.setFixedHeight(self.FIELD_HEIGHT)
        widget.setMinimumWidth(min_width)
        widget.setTextMargins(8, 4, 8, 4)
        if max_width is not None:
            widget.setMaximumWidth(max_width)

    def _apply_combo_metrics(
        self,
        widget: QComboBox,
        *,
        min_width: int,
        max_width: int | None = None,
    ) -> None:
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        widget.setFixedHeight(self.FIELD_HEIGHT)
        widget.setMinimumWidth(min_width)
        if max_width is not None:
            widget.setMaximumWidth(max_width)
        line_edit = widget.lineEdit()
        if line_edit is not None:
            line_edit.setFixedHeight(max(36, self.FIELD_HEIGHT - 8))
            line_edit.setTextMargins(8, 4, 8, 4)

    def _apply_form_metrics(self) -> None:
        self._apply_combo_metrics(self.status_combo, min_width=240, max_width=300)
        self._apply_combo_metrics(self.classification_combo, min_width=self.WIDE_FIELD_MIN_WIDTH)
        self._apply_combo_metrics(self.packaging_combo, min_width=self.STANDARD_FIELD_MIN_WIDTH)
        self._apply_combo_metrics(self.market_combo, min_width=self.STANDARD_FIELD_MIN_WIDTH)
        self._apply_combo_metrics(self.language_combo, min_width=240, max_width=320)
        self._apply_combo_metrics(self.unit_combo, min_width=200, max_width=240)
        self._apply_line_edit_metrics(self.description_edit, min_width=self.WIDE_FIELD_MIN_WIDTH)
        self._apply_line_edit_metrics(self.brand_edit, min_width=self.STANDARD_FIELD_MIN_WIDTH)
        self._apply_line_edit_metrics(self.subbrand_edit, min_width=self.STANDARD_FIELD_MIN_WIDTH)
        self._apply_line_edit_metrics(self.quantity_edit, min_width=self.COMPACT_FIELD_MIN_WIDTH, max_width=220)
        self._apply_line_edit_metrics(self.image_url_edit, min_width=self.WIDE_FIELD_MIN_WIDTH)
        self.notes_edit.setMinimumWidth(self.WIDE_FIELD_MIN_WIDTH)
        self.notes_edit.setMinimumHeight(self.NOTES_MIN_HEIGHT)

    def _connect_form_signals(self) -> None:
        for edit in (
            self.description_edit,
            self.brand_edit,
            self.subbrand_edit,
            self.quantity_edit,
            self.image_url_edit,
        ):
            edit.textChanged.connect(lambda *_args: self.changed.emit())
        for combo in (
            self.status_combo,
            self.classification_combo,
            self.packaging_combo,
            self.market_combo,
            self.language_combo,
            self.unit_combo,
        ):
            combo.currentTextChanged.connect(lambda *_args: self.changed.emit())
            combo.editTextChanged.connect(lambda *_args: self.changed.emit())
        self.consumer_unit_check.toggled.connect(lambda *_args: self.changed.emit())
        self.export_enabled_check.toggled.connect(lambda *_args: self.changed.emit())
        self.notes_edit.textChanged.connect(lambda: self.changed.emit())

    def _group_summary_text(self) -> str:
        unique_upcs = [str(context.upc or "").strip() for context in self.group.contexts if str(context.upc or "").strip()]
        unique_upcs = list(dict.fromkeys(unique_upcs))
        source_tracks = ", ".join(
            str(context.track_title or f"Track {context.track_id}").strip()
            for context in self.group.contexts
        )
        parts = [
            f"<b>Product:</b> {self.group.display_title}",
            f"<b>Type:</b> {'Album product' if self.group.is_album_group else 'Single'}",
            f"<b>Tracks in group:</b> {len(self.group.track_ids)}",
            f"<b>Source tracks:</b> {source_tracks}",
        ]
        if self.group.is_album_group and self.group.representative_context.album_title:
            parts.append(f"<b>Album:</b> {self.group.representative_context.album_title}")
        if unique_upcs:
            parts.append(f"<b>Existing UPC/EAN:</b> {', '.join(unique_upcs)}")
        parts.append(
            "<b>Save behavior:</b> "
            + (
                "Saving this tab applies the same GS1 metadata to every selected track in this album group."
                if self.group.is_album_group and len(self.group.track_ids) > 1
                else "Saving this tab stores metadata for this track."
            )
        )
        parts.append(
            "<b>Product naming:</b> "
            + (
                "Album groups export with the album title as the product name."
                if self.group.is_album_group
                else "Singles export with the track title plus ' - Single' as the product name."
            )
        )
        return "<br/>".join(parts)

    def apply_record_to_form(self, record: GS1MetadataRecord) -> None:
        self._loading_form = True
        try:
            self.status_combo.setCurrentText(record.status)
            self.classification_combo.setCurrentText(record.product_classification)
            self.consumer_unit_check.setChecked(bool(record.consumer_unit_flag))
            self.packaging_combo.setCurrentText(record.packaging_type)
            self.market_combo.setCurrentText(record.target_market)
            self.language_combo.setCurrentText(record.language)
            self.description_edit.setText(record.product_description)
            self.brand_edit.setText(record.brand)
            self.subbrand_edit.setText(record.subbrand)
            self.quantity_edit.setText(record.quantity)
            self.unit_combo.setCurrentText(record.unit)
            self.image_url_edit.setText(record.image_url)
            self.export_enabled_check.setChecked(bool(record.export_enabled))
            self.notes_edit.setPlainText(record.notes)
        finally:
            self._loading_form = False

    def record_from_form(self) -> GS1MetadataRecord:
        base = self._saved_record.copy()
        base.track_id = self.group.representative_context.track_id
        base.status = self.status_combo.currentText().strip()
        base.product_classification = self.classification_combo.currentText().strip()
        base.consumer_unit_flag = self.consumer_unit_check.isChecked()
        base.packaging_type = self.packaging_combo.currentText().strip()
        base.target_market = self.market_combo.currentText().strip()
        base.language = self.language_combo.currentText().strip()
        base.product_description = self.description_edit.text().strip()
        base.brand = self.brand_edit.text().strip()
        base.subbrand = self.subbrand_edit.text().strip()
        base.quantity = self.quantity_edit.text().strip()
        base.unit = self.unit_combo.currentText().strip()
        base.image_url = self.image_url_edit.text().strip()
        base.export_enabled = self.export_enabled_check.isChecked()
        base.notes = self.notes_edit.toPlainText().strip()
        return base

    def set_saved_record(self, record: GS1MetadataRecord) -> None:
        self._saved_record = record.copy()
        self.apply_record_to_form(self._saved_record)

    def set_default_record(self, record: GS1MetadataRecord) -> None:
        self._default_record = record.copy()

    def reset_to_defaults(self) -> None:
        self.apply_record_to_form(self._default_record)

    def revert_form(self) -> None:
        self.apply_record_to_form(self._saved_record)


class GS1ExportPreviewDialog(QDialog):
    """Shows the exact worksheet data that will be written before export continues."""

    def __init__(self, plan: GS1ExportPlan, parent=None):
        super().__init__(parent)
        self.plan = plan
        self.setWindowTitle("GS1 Export Preview")
        self.setModal(True)
        self.resize(1080, 680)
        self.setMinimumSize(960, 560)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        summary_box = QGroupBox("Export Summary", self)
        summary_layout = QVBoxLayout(summary_box)
        summary_layout.setContentsMargins(14, 14, 14, 14)
        summary_layout.setSpacing(8)
        summary_label = QLabel("\n".join(plan.summary_lines))
        summary_label.setWordWrap(True)
        summary_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        summary_layout.addWidget(summary_label)
        root.addWidget(summary_box)

        if plan.warnings:
            warning_box = QGroupBox("Warnings", self)
            warning_layout = QVBoxLayout(warning_box)
            warning_layout.setContentsMargins(14, 14, 14, 14)
            warning_layout.setSpacing(8)
            warning_label = QLabel("\n".join(f"- {line}" for line in plan.warnings))
            warning_label.setWordWrap(True)
            warning_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            warning_layout.addWidget(warning_label)
            root.addWidget(warning_box)

        preview_box = QGroupBox("Workbook Rows", self)
        preview_layout = QVBoxLayout(preview_box)
        preview_layout.setContentsMargins(14, 14, 14, 14)
        preview_layout.setSpacing(8)
        preview_help = QLabel(
            f"Detected sheet: {plan.template_profile.sheet_name}. The table below shows the final values that will be written into the workbook."
        )
        preview_help.setWordWrap(True)
        preview_layout.addWidget(preview_help)

        table = QTableWidget(len(plan.preview.rows), len(plan.preview.headers), self)
        table.setHorizontalHeaderLabels(list(plan.preview.headers))
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.NoSelection)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.setWordWrap(False)
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setStretchLastSection(True)
        for row_index, row_values in enumerate(plan.preview.rows):
            for column_index, value in enumerate(row_values):
                item = QTableWidgetItem(str(value))
                table.setItem(row_index, column_index, item)
        table.resizeColumnsToContents()
        preview_layout.addWidget(table, 1)
        root.addWidget(preview_box, 1)

        button_box = QDialogButtonBox(QDialogButtonBox.Cancel | QDialogButtonBox.Ok, parent=self)
        ok_button = button_box.button(QDialogButtonBox.Ok)
        if ok_button is not None:
            ok_button.setText("Continue Export")
            ok_button.setDefault(True)
        cancel_button = button_box.button(QDialogButtonBox.Cancel)
        if cancel_button is not None:
            cancel_button.setAutoDefault(False)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        root.addWidget(button_box)


class GS1MetadataDialog(QDialog):
    """Edits GS1 metadata for one or more grouped products from the catalog selection."""

    WINDOW_TITLE = "GS1 Metadata"
    ELEMENT_MARGIN = 2

    def __init__(self, *, app, track_id: int, batch_track_ids: list[int] | None = None, parent=None):
        super().__init__(parent or app)
        self.app = app
        self.track_id = int(track_id)
        self.batch_track_ids = self._normalize_track_ids(batch_track_ids or [self.track_id])
        self.gs1_service = getattr(app, "gs1_integration_service", None)
        if self.gs1_service is None:
            raise RuntimeError("GS1 integration service is not available")

        self._template_path_override = ""
        self._template_profile = None
        self._group_tabs: QTabWidget | None = None
        self._groups = self.gs1_service.build_metadata_groups(
            self.batch_track_ids,
            current_profile_path=self._current_profile_path(),
            window_title=self._window_title(),
        )
        if not self._groups:
            raise ValueError("Could not determine the selected track.")
        self._editor_pages: list[GS1MetadataEditorPage] = []

        self.setWindowTitle(self.WINDOW_TITLE)
        self.setModal(True)
        self.resize(1120, 860)
        self.setMinimumSize(1020, 780)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        scroll_area = QScrollArea(self)
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_content = QWidget(scroll_area)
        scroll_content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        content_layout = QVBoxLayout(scroll_content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(12)
        scroll_area.setWidget(scroll_content)
        root.addWidget(scroll_area, 1)

        summary_box = QGroupBox("Release / Product Context", self)
        summary_layout = QVBoxLayout(summary_box)
        summary_layout.setContentsMargins(14, 14, 14, 14)
        summary_layout.setSpacing(6)
        self.summary_label = QLabel(self._selection_summary_text())
        self.summary_label.setWordWrap(True)
        self.summary_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        summary_layout.addWidget(self.summary_label)
        content_layout.addWidget(summary_box)

        template_box = QGroupBox("Official GS1 Workbook", self)
        template_layout = QVBoxLayout(template_box)
        template_layout.setContentsMargins(14, 14, 14, 14)
        template_layout.setSpacing(8)
        self.template_help_label = QLabel(
            "GS1 export uses the official workbook from your GS1 portal or regional GS1 environment. "
            "The app validates the workbook before writing any rows."
        )
        self.template_help_label.setWordWrap(True)
        template_layout.addWidget(self.template_help_label)
        self.template_status_label = QLabel("")
        self.template_status_label.setWordWrap(True)
        self.template_status_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        template_layout.addWidget(self.template_status_label)
        template_button_row = QHBoxLayout()
        template_button_row.setContentsMargins(self.ELEMENT_MARGIN, self.ELEMENT_MARGIN, self.ELEMENT_MARGIN, self.ELEMENT_MARGIN)
        template_button_row.setSpacing(8)
        self.choose_template_button = QPushButton("Choose Workbook…", self)
        self.choose_template_button.setAutoDefault(False)
        self.choose_template_button.clicked.connect(lambda: self._choose_template_path(prompt_message=None))
        self.reverify_template_button = QPushButton("Re-verify", self)
        self.reverify_template_button.setAutoDefault(False)
        self.reverify_template_button.clicked.connect(lambda: self._refresh_template_status(prompt_if_missing=False))
        self.settings_button = QPushButton("Open Settings…", self)
        self.settings_button.setAutoDefault(False)
        self.settings_button.clicked.connect(lambda: self.app.open_settings_dialog(initial_focus="gs1_template_path"))
        template_button_row.addWidget(self.choose_template_button)
        template_button_row.addWidget(self.reverify_template_button)
        template_button_row.addWidget(self.settings_button)
        template_button_row.addStretch(1)
        template_layout.addLayout(template_button_row)
        content_layout.addWidget(template_box)

        editor_box = QGroupBox("GS1 Metadata", self)
        editor_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        editor_layout = QVBoxLayout(editor_box)
        editor_layout.setContentsMargins(16, 14, 16, 14)
        editor_layout.setSpacing(10)
        if len(self._groups) > 1:
            tabs_help = QLabel(
                "Each tab represents one final GS1 product row. Album tabs apply the same GS1 metadata to every selected track in that album group when you save."
            )
            tabs_help.setWordWrap(True)
            editor_layout.addWidget(tabs_help)
            self._group_tabs = QTabWidget(self)
            self._group_tabs.currentChanged.connect(lambda *_args: self._update_readiness())
            editor_layout.addWidget(self._group_tabs, 1)
        for group in self._groups:
            page = GS1MetadataEditorPage(group, self)
            page.changed.connect(self._update_readiness)
            self._editor_pages.append(page)
            if self._group_tabs is not None:
                self._group_tabs.addTab(page, group.tab_title)
            else:
                editor_layout.addWidget(page)
        content_layout.addWidget(editor_box)

        info_box = QGroupBox("Export Readiness", self)
        info_layout = QVBoxLayout(info_box)
        info_layout.setContentsMargins(14, 14, 14, 14)
        info_layout.setSpacing(8)
        self.readiness_label = QLabel("")
        self.readiness_label.setWordWrap(True)
        info_layout.addWidget(self.readiness_label)
        self.batch_note_label = QLabel(
            "Exports always produce a single workbook. Tracks with the same album title become one product row per album title, while singles export as separate rows."
        )
        self.batch_note_label.setWordWrap(True)
        info_layout.addWidget(self.batch_note_label)
        content_layout.addWidget(info_box)
        content_layout.addStretch(1)

        button_row = QHBoxLayout()
        button_row.setContentsMargins(self.ELEMENT_MARGIN, self.ELEMENT_MARGIN, self.ELEMENT_MARGIN, self.ELEMENT_MARGIN)
        button_row.setSpacing(8)
        self.revert_button = QPushButton("Revert", self)
        self.revert_button.setAutoDefault(False)
        self.revert_button.clicked.connect(self._revert_form)
        self.reset_defaults_button = QPushButton("Reset to Defaults", self)
        self.reset_defaults_button.setAutoDefault(False)
        self.reset_defaults_button.clicked.connect(self._reset_to_defaults)
        button_row.addWidget(self.revert_button)
        button_row.addWidget(self.reset_defaults_button)
        button_row.addStretch(1)

        self.save_button = QPushButton("Save", self)
        self.save_button.setDefault(True)
        self.save_button.clicked.connect(lambda: self._save_groups(self._groups, show_confirmation=True))
        self.export_current_button = QPushButton("Export Current…", self)
        self.export_current_button.clicked.connect(self._export_current)
        self.export_batch_button = QPushButton(self._batch_button_text(), self)
        self.export_batch_button.clicked.connect(self._export_batch)
        self.export_batch_button.setEnabled(len(self._groups) > 1 or len(self.batch_track_ids) > 1)
        self.close_button = QPushButton("Close", self)
        self.close_button.setAutoDefault(False)
        self.close_button.clicked.connect(self.accept)
        button_row.addWidget(self.save_button)
        button_row.addWidget(self.export_current_button)
        button_row.addWidget(self.export_batch_button)
        button_row.addWidget(self.close_button)
        root.addLayout(button_row)

        self._refresh_template_status(prompt_if_missing=True)
        self._update_readiness()

    def _normalize_track_ids(self, track_ids: list[int]) -> list[int]:
        normalized: list[int] = []
        seen: set[int] = set()
        for track_id in track_ids:
            try:
                clean_id = int(track_id)
            except (TypeError, ValueError):
                continue
            if clean_id <= 0 or clean_id in seen:
                continue
            normalized.append(clean_id)
            seen.add(clean_id)
        if self.track_id in seen:
            normalized = [self.track_id] + [value for value in normalized if value != self.track_id]
        else:
            normalized.insert(0, self.track_id)
        return normalized

    def _current_profile_path(self) -> str:
        return str(getattr(self.app, "current_db_path", "") or "")

    def _window_title(self) -> str:
        identity = getattr(self.app, "identity", {}) or {}
        return str(identity.get("window_title") or "")

    def _selection_summary_text(self) -> str:
        lines = [
            f"<b>Selected tracks:</b> {len(self.batch_track_ids)}",
            f"<b>Export product groups:</b> {len(self._groups)}",
        ]
        if len(self._groups) > 1:
            lines.append("<b>Editing mode:</b> One tab per final GS1 export product group.")
        group_lines = []
        for group in self._groups:
            kind = "Album" if group.is_album_group else "Single"
            group_lines.append(f"{kind}: {group.display_title} ({len(group.track_ids)} track{'s' if len(group.track_ids) != 1 else ''})")
        if group_lines:
            lines.append("<b>Groups:</b> " + " | ".join(group_lines))
        return "<br/>".join(lines)

    def _current_group(self) -> GS1MetadataGroup:
        if self._group_tabs is None:
            return self._groups[0]
        return self._groups[self._group_tabs.currentIndex()]

    def _current_page(self) -> GS1MetadataEditorPage:
        if self._group_tabs is None:
            return self._editor_pages[0]
        return self._editor_pages[self._group_tabs.currentIndex()]

    def _page_for_group(self, group: GS1MetadataGroup) -> GS1MetadataEditorPage:
        index = self._groups.index(group)
        return self._editor_pages[index]

    def _focus_group(self, group: GS1MetadataGroup) -> None:
        if self._group_tabs is None:
            return
        self._group_tabs.setCurrentIndex(self._groups.index(group))

    def _refresh_template_status(self, *, prompt_if_missing: bool) -> bool:
        template_path = self._template_path_override or self.app.gs1_settings_service.load_template_path()
        if not template_path:
            self._template_profile = None
            self.template_status_label.setText(
                "No official GS1 workbook is configured yet. Choose the Excel upload template from your GS1 portal or environment."
            )
            self._update_readiness()
            if prompt_if_missing:
                return self._choose_template_path(
                    prompt_message=(
                        "GS1 export requires the official Excel upload template from your GS1 portal or regional GS1 environment.\n\n"
                        "Choose that workbook now so the app can validate it and use the correct upload sheet."
                    )
                )
            return False

        try:
            self._template_profile = self.gs1_service.load_template_profile(template_path)
        except (GS1DependencyError, GS1TemplateVerificationError) as exc:
            self._template_profile = None
            self.template_status_label.setText(str(exc))
            self._update_readiness()
            if prompt_if_missing:
                return self._choose_template_path(prompt_message=str(exc))
            return False

        self._template_path_override = str(template_path)
        self.template_status_label.setText(
            "Verified workbook:\n"
            f"{self._template_path_override}\n"
            f"Detected sheet: {self._template_profile.sheet_name} (header row {self._template_profile.header_row})"
        )
        self._update_readiness()
        return True

    def _choose_template_path(self, *, prompt_message: str | None) -> bool:
        if prompt_message:
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("Official GS1 Workbook Required")
            msg_box.setIcon(QMessageBox.Information)
            msg_box.setText(prompt_message)
            msg_box.setInformativeText(
                "Download the official workbook from your GS1 environment, then choose it here. "
                "The app validates headers and sheet structure before export."
            )
            msg_box.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
            if msg_box.exec() != QMessageBox.Ok:
                return False

        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose Official GS1 Workbook",
            self._template_path_override or str(Path.home()),
            "Excel Workbook (*.xlsx *.xlsm *.xltx *.xltm)",
        )
        if not path:
            return False

        try:
            profile = self.gs1_service.load_template_profile(path)
        except (GS1DependencyError, GS1TemplateVerificationError) as exc:
            self._template_profile = None
            self.template_status_label.setText(str(exc))
            self._update_readiness()
            QMessageBox.warning(self, "GS1 Workbook", str(exc))
            return False

        self._template_path_override = str(path)
        self._template_profile = profile
        self.template_status_label.setText(
            "Verified workbook:\n"
            f"{self._template_path_override}\n"
            f"Detected sheet: {profile.sheet_name} (header row {profile.header_row})"
        )
        if QMessageBox.question(
            self,
            "Save as Default?",
            "Save this workbook path as the default GS1 template for future exports?",
            QMessageBox.Yes | QMessageBox.No,
        ) == QMessageBox.Yes:
            self.gs1_service.save_template_path(str(path))
        self._update_readiness()
        return True

    def _update_readiness(self) -> None:
        if any(page.is_loading for page in self._editor_pages):
            return
        lines: list[str] = []
        issues: list[str] = []
        for group, page in zip(self._groups, self._editor_pages):
            validation = self.gs1_service.validate_group_metadata(group, page.record_from_form(), for_export=False)
            if validation.is_valid:
                continue
            issues.append(f"{group.tab_title}: " + "; ".join(validation.messages()))
        if issues:
            lines.append("Metadata needs attention:")
            lines.extend(f"- {message}" for message in issues)
        else:
            lines.append(f"Metadata is complete for {len(self._groups)} product group(s).")

        if self._template_profile is None:
            lines.append("Export is blocked until a verified official GS1 workbook is selected.")
        elif issues:
            lines.append("Export validation still has blocking issues.")
        else:
            lines.append(f"Ready to export into '{self._template_profile.sheet_name}'.")
        self.readiness_label.setText("\n".join(lines))

    def _save_groups(self, groups: list[GS1MetadataGroup], *, show_confirmation: bool) -> bool:
        saved_track_count = 0
        for group in groups:
            page = self._page_for_group(group)
            try:
                saved_records = self.gs1_service.save_metadata_group(group, page.record_from_form())
            except GS1ValidationError as exc:
                self._focus_group(group)
                self.readiness_label.setText("Metadata needs attention:\n" + "\n".join(f"- {message}" for message in exc.result.messages()))
                QMessageBox.warning(self, "GS1 Metadata", str(exc))
                self._update_readiness()
                return False
            representative = saved_records[0]
            group.record = representative.copy()
            page.group.record = representative.copy()
            page.set_saved_record(representative)
            saved_track_count += len(saved_records)
        self._update_readiness()
        if show_confirmation:
            QMessageBox.information(
                self,
                "GS1 Metadata",
                f"Saved GS1 metadata for {saved_track_count} track(s) across {len(groups)} product group(s).",
            )
        return True

    def _reset_to_defaults(self) -> None:
        group = self._current_group()
        default_group = self.gs1_service.build_metadata_groups(
            list(group.track_ids),
            current_profile_path=self._current_profile_path(),
            window_title=self._window_title(),
        )[0]
        group.default_record = default_group.default_record.copy()
        page = self._current_page()
        page.set_default_record(default_group.default_record)
        page.reset_to_defaults()
        self._update_readiness()

    def _revert_form(self) -> None:
        self._current_page().revert_form()
        self._update_readiness()

    def _batch_button_text(self) -> str:
        if len(self._groups) <= 1 and len(self.batch_track_ids) <= 1:
            return "Export Selection…"
        return f"Export Selection ({len(self._groups)})…"

    def _suggest_output_path(self, *, batch: bool) -> str:
        base_name = self._current_group().display_title if not batch else f"selection_{len(self._groups)}"
        suffix = Path(self._template_path_override or self.app.gs1_settings_service.load_template_path() or "template.xlsx").suffix
        if suffix.lower() not in {".xlsx", ".xlsm", ".xltx", ".xltm"}:
            suffix = ".xlsx"
        filename = f"gs1_{_safe_filename(base_name)}{suffix}" if not batch else f"gs1_selection_{_safe_filename(base_name)}{suffix}"
        return str(self.app.exports_dir / filename)

    def _confirm_output_path(self, output_path: str) -> bool:
        if not output_path:
            return False
        selected_path = Path(output_path)
        template_path_text = str(self._template_path_override or self.app.gs1_settings_service.load_template_path() or "").strip()
        if template_path_text and selected_path.resolve() == Path(template_path_text).resolve():
            return (
                QMessageBox.question(
                    self,
                    "Overwrite Template?",
                    "The selected output path is the same as the configured GS1 template. Overwrite it?",
                    QMessageBox.Yes | QMessageBox.No,
                )
                == QMessageBox.Yes
            )
        if selected_path.exists():
            return (
                QMessageBox.question(
                    self,
                    "Overwrite File?",
                    f"The file already exists:\n{selected_path}\n\nOverwrite it?",
                    QMessageBox.Yes | QMessageBox.No,
                )
                == QMessageBox.Yes
            )
        return True

    def _build_export_plan(self, track_ids: list[int]) -> GS1ExportPlan | None:
        try:
            plan = self.gs1_service.prepare_export_plan(
                track_ids,
                template_path=self._template_path_override,
                current_profile_path=self._current_profile_path(),
                window_title=self._window_title(),
            )
        except (GS1BatchValidationError, GS1DependencyError, GS1TemplateVerificationError) as exc:
            QMessageBox.warning(self, "GS1 Export", str(exc))
            return None
        return plan

    def _confirm_export_preview(self, plan: GS1ExportPlan) -> bool:
        return GS1ExportPreviewDialog(plan, self).exec() == QDialog.Accepted

    def _export_current(self) -> None:
        current_group = self._current_group()
        if not self._save_groups([current_group], show_confirmation=False):
            return
        if self._template_profile is None and not self._refresh_template_status(prompt_if_missing=True):
            self._update_readiness()
            return
        plan = self._build_export_plan(list(current_group.track_ids))
        if plan is None:
            return
        self._template_profile = plan.template_profile
        if not self._confirm_export_preview(plan):
            return
        output_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export GS1 Workbook",
            self._suggest_output_path(batch=False),
            "Excel Workbook (*.xlsx *.xlsm *.xltx *.xltm)",
        )
        if not output_path or not self._confirm_output_path(output_path):
            return
        try:
            result = self.app._run_file_history_action(
                action_label=lambda export_result: f"Export GS1: {export_result.exported_count} record",
                action_type="file.export_gs1_single",
                target_path=output_path,
                mutation=lambda: self.gs1_service.export_plan(plan, output_path=output_path),
                entity_type="Export",
                entity_id=output_path,
                payload=lambda export_result: {
                    "path": output_path,
                    "count": export_result.exported_count,
                    "track_ids": list(current_group.track_ids),
                    "sheet_name": export_result.sheet_name,
                },
            )
        except (GS1BatchValidationError, GS1DependencyError, GS1TemplateVerificationError) as exc:
            QMessageBox.warning(self, "GS1 Export", str(exc))
            return
        except Exception as exc:
            QMessageBox.critical(self, "GS1 Export", f"Failed to export the workbook:\n{exc}")
            return
        QMessageBox.information(
            self,
            "GS1 Export",
            f"Saved GS1 workbook:\n{result.output_path}\n\nSheet: {result.sheet_name}\nRows: {', '.join(map(str, result.row_numbers))}",
        )

    def _export_batch(self) -> None:
        if len(self.batch_track_ids) <= 1 and len(self._groups) <= 1:
            QMessageBox.information(self, "GS1 Export", "Select more than one catalog row to export a grouped workbook.")
            return
        if not self._save_groups(self._groups, show_confirmation=False):
            return
        if self._template_profile is None and not self._refresh_template_status(prompt_if_missing=True):
            self._update_readiness()
            return
        plan = self._build_export_plan(self.batch_track_ids)
        if plan is None:
            return
        self._template_profile = plan.template_profile
        if not self._confirm_export_preview(plan):
            return
        output_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export GS1 Selection Workbook",
            self._suggest_output_path(batch=True),
            "Excel Workbook (*.xlsx *.xlsm *.xltx *.xltm)",
        )
        if not output_path or not self._confirm_output_path(output_path):
            return
        try:
            result = self.app._run_file_history_action(
                action_label=lambda export_result: f"Export GS1 Selection: {export_result.exported_count} records",
                action_type="file.export_gs1_batch",
                target_path=output_path,
                mutation=lambda: self.gs1_service.export_plan(plan, output_path=output_path),
                entity_type="Export",
                entity_id=output_path,
                payload=lambda export_result: {
                    "path": output_path,
                    "count": export_result.exported_count,
                    "track_ids": list(self.batch_track_ids),
                    "sheet_name": export_result.sheet_name,
                },
            )
        except (GS1BatchValidationError, GS1DependencyError, GS1TemplateVerificationError) as exc:
            QMessageBox.warning(self, "GS1 Export", str(exc))
            return
        except Exception as exc:
            QMessageBox.critical(self, "GS1 Export", f"Failed to export the workbook:\n{exc}")
            return
        QMessageBox.information(
            self,
            "GS1 Export",
            f"Saved GS1 workbook:\n{result.output_path}\n\nSheet: {result.sheet_name}\nRows: {', '.join(map(str, result.row_numbers))}",
        )

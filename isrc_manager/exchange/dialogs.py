"""Dialogs for CSV/XLSX/JSON exchange workflows."""

from __future__ import annotations

import json

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from .models import ExchangeImportOptions, ExchangeInspection


class ExchangeImportDialog(QDialog):
    """Preview source columns, map them, and choose import mode/options."""

    def __init__(
        self,
        *,
        inspection: ExchangeInspection,
        supported_headers: list[str],
        settings,
        initial_mode: str = "dry_run",
        parent=None,
    ):
        super().__init__(parent)
        self.inspection = inspection
        self.supported_headers = supported_headers
        self.settings = settings
        self.initial_mode = str(initial_mode or "dry_run")

        self.setWindowTitle(f"Import {inspection.format_name.upper()}")
        self.resize(1100, 760)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        intro = QLabel(
            "Review the detected columns, adjust the mapping where needed, and choose how the import should match existing rows."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        meta_row = QHBoxLayout()
        meta_row.setContentsMargins(0, 0, 0, 0)
        meta_row.setSpacing(8)
        meta_row.addWidget(QLabel(f"Source: {inspection.file_path}"))
        meta_row.addStretch(1)
        if inspection.warnings:
            warning_label = QLabel("Warnings: " + " | ".join(inspection.warnings))
            warning_label.setWordWrap(True)
            meta_row.addWidget(warning_label)
        root.addLayout(meta_row)

        preset_row = QHBoxLayout()
        preset_row.setContentsMargins(0, 0, 0, 0)
        preset_row.setSpacing(8)
        preset_row.addWidget(QLabel("Mapping preset"))
        self.preset_combo = QComboBox()
        preset_row.addWidget(self.preset_combo, 1)
        load_preset_button = QPushButton("Load Preset")
        load_preset_button.clicked.connect(self._load_preset)
        preset_row.addWidget(load_preset_button)
        self.preset_name_edit = QLineEdit()
        self.preset_name_edit.setPlaceholderText("Preset name")
        preset_row.addWidget(self.preset_name_edit)
        save_preset_button = QPushButton("Save Preset")
        save_preset_button.clicked.connect(self._save_preset)
        preset_row.addWidget(save_preset_button)
        root.addLayout(preset_row)

        option_row = QHBoxLayout()
        option_row.setContentsMargins(0, 0, 0, 0)
        option_row.setSpacing(8)
        option_row.addWidget(QLabel("Mode"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Dry run validation", "dry_run")
        self.mode_combo.addItem("Create new tracks only", "create")
        self.mode_combo.addItem("Update existing matches", "update")
        self.mode_combo.addItem("Merge into existing rows", "merge")
        self.mode_combo.addItem("Insert new when duplicate exists", "insert_new")
        option_row.addWidget(self.mode_combo)
        self.match_internal_checkbox = QCheckBox("Match by internal ID")
        self.match_internal_checkbox.setChecked(True)
        option_row.addWidget(self.match_internal_checkbox)
        self.match_isrc_checkbox = QCheckBox("Match by ISRC")
        self.match_isrc_checkbox.setChecked(True)
        option_row.addWidget(self.match_isrc_checkbox)
        self.match_upc_title_checkbox = QCheckBox("Match by UPC + title")
        self.match_upc_title_checkbox.setChecked(True)
        option_row.addWidget(self.match_upc_title_checkbox)
        self.heuristic_checkbox = QCheckBox("Enable title/artist heuristics")
        option_row.addWidget(self.heuristic_checkbox)
        self.create_custom_checkbox = QCheckBox("Create missing text custom fields")
        self.create_custom_checkbox.setChecked(True)
        option_row.addWidget(self.create_custom_checkbox)
        root.addLayout(option_row)

        self.mode_hint_label = QLabel()
        self.mode_hint_label.setWordWrap(True)
        root.addWidget(self.mode_hint_label)

        mapping_label = QLabel("Column Mapping")
        root.addWidget(mapping_label)

        self.mapping_table = QTableWidget(0, 2, self)
        self.mapping_table.setHorizontalHeaderLabels(["Source Column", "Map To"])
        self.mapping_table.verticalHeader().setVisible(False)
        self.mapping_table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.mapping_table, 1)

        preview_label = QLabel("Source Preview")
        root.addWidget(preview_label)
        self.preview_table = QTableWidget(0, len(inspection.headers), self)
        self.preview_table.setHorizontalHeaderLabels(inspection.headers)
        self.preview_table.verticalHeader().setVisible(False)
        self.preview_table.horizontalHeader().setStretchLastSection(True)
        self.preview_table.setEditTriggers(QTableWidget.NoEditTriggers)
        root.addWidget(self.preview_table, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.import_button = QPushButton("Run Import")
        self.import_button.setDefault(True)
        self.import_button.clicked.connect(self.accept)
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        buttons.addWidget(self.import_button)
        buttons.addWidget(cancel_button)
        root.addLayout(buttons)

        self._reload_presets()
        self._populate_mapping_table()
        self._populate_preview_table()
        self._apply_initial_mode()
        self.mode_combo.currentIndexChanged.connect(self._update_mode_affordances)
        self._update_mode_affordances()

    def _settings_key(self) -> str:
        return f"exchange/mapping_presets/{self.inspection.format_name}"

    def _read_presets(self) -> dict[str, dict[str, str]]:
        raw = self.settings.value(self._settings_key(), "{}", str)
        try:
            payload = json.loads(str(raw or "{}"))
        except Exception:
            payload = {}
        return payload if isinstance(payload, dict) else {}

    def _write_presets(self, payload: dict[str, dict[str, str]]) -> None:
        self.settings.setValue(self._settings_key(), json.dumps(payload, ensure_ascii=False))
        self.settings.sync()

    def _reload_presets(self) -> None:
        self.preset_combo.clear()
        self.preset_combo.addItem("")
        for name in sorted(self._read_presets()):
            self.preset_combo.addItem(name)

    def _populate_mapping_table(self) -> None:
        headers = self.inspection.headers
        self.mapping_table.setRowCount(len(headers))
        choices = [""] + self.supported_headers
        for row, header in enumerate(headers):
            self.mapping_table.setItem(row, 0, QTableWidgetItem(header))
            combo = QComboBox(self.mapping_table)
            combo.addItems(choices)
            suggested = self.inspection.suggested_mapping.get(header, "")
            index = combo.findText(suggested)
            combo.setCurrentIndex(index if index >= 0 else 0)
            self.mapping_table.setCellWidget(row, 1, combo)

    def _populate_preview_table(self) -> None:
        rows = self.inspection.preview_rows
        self.preview_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for column, header in enumerate(self.inspection.headers):
                self.preview_table.setItem(
                    row_index,
                    column,
                    QTableWidgetItem("" if row.get(header) is None else str(row.get(header))),
                )

    def _apply_initial_mode(self) -> None:
        index = self.mode_combo.findData(self.initial_mode)
        if index < 0:
            index = self.mode_combo.findData("dry_run")
        self.mode_combo.setCurrentIndex(max(0, index))

    def _update_mode_affordances(self) -> None:
        mode = str(self.mode_combo.currentData() or "dry_run")
        if mode == "dry_run":
            self.import_button.setText("Run Validation")
            self.mode_hint_label.setText(
                "Dry run checks the source data and mappings only. No rows will be written to the database."
            )
        else:
            self.import_button.setText("Import Data")
            self.mode_hint_label.setText(
                "This mode writes rows into the current profile using the matching rules selected below."
            )

    def _save_preset(self) -> None:
        name = self.preset_name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Mapping Preset", "Enter a preset name first.")
            return
        presets = self._read_presets()
        presets[name] = self.mapping()
        self._write_presets(presets)
        self._reload_presets()
        index = self.preset_combo.findText(name)
        self.preset_combo.setCurrentIndex(index if index >= 0 else 0)

    def _load_preset(self) -> None:
        name = self.preset_combo.currentText().strip()
        if not name:
            return
        preset = self._read_presets().get(name)
        if not isinstance(preset, dict):
            return
        for row in range(self.mapping_table.rowCount()):
            header_item = self.mapping_table.item(row, 0)
            combo = self.mapping_table.cellWidget(row, 1)
            if header_item is None or combo is None:
                continue
            value = str(preset.get(header_item.text(), ""))
            index = combo.findText(value)
            combo.setCurrentIndex(index if index >= 0 else 0)

    def mapping(self) -> dict[str, str]:
        mapped: dict[str, str] = {}
        for row in range(self.mapping_table.rowCount()):
            header_item = self.mapping_table.item(row, 0)
            combo = self.mapping_table.cellWidget(row, 1)
            if header_item is None or combo is None:
                continue
            source = header_item.text()
            target = combo.currentText().strip()
            if target:
                mapped[source] = target
        return mapped

    def import_options(self) -> ExchangeImportOptions:
        return ExchangeImportOptions(
            mode=str(self.mode_combo.currentData() or "dry_run"),
            match_by_internal_id=self.match_internal_checkbox.isChecked(),
            match_by_isrc=self.match_isrc_checkbox.isChecked(),
            match_by_upc_title=self.match_upc_title_checkbox.isChecked(),
            heuristic_match=self.heuristic_checkbox.isChecked(),
            create_missing_custom_fields=self.create_custom_checkbox.isChecked(),
        )

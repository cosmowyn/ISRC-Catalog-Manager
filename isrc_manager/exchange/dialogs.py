"""Dialogs for CSV/XLSX/JSON exchange workflows."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

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
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from isrc_manager.ui_common import (
    _add_standard_dialog_header,
    _apply_compact_dialog_control_heights,
    _apply_standard_dialog_chrome,
)

from .models import ExchangeImportOptions, ExchangeInspection


def _keep_signal_wrapper_alive(owner: object, wrapper: Callable[..., object]) -> None:
    wrappers = getattr(owner, "_isrc_signal_wrappers", None)
    if wrappers is None:
        wrappers = []
        setattr(owner, "_isrc_signal_wrappers", wrappers)
    wrappers.append(wrapper)


def _connect_noarg_signal(signal: Any, owner: object, slot: Callable[[], object]) -> None:
    def _wrapper(_checked: bool = False, _slot: Callable[[], object] = slot) -> None:
        _slot()

    _keep_signal_wrapper_alive(owner, _wrapper)
    signal.connect(_wrapper)


class ExchangeImportDialog(QDialog):
    """Preview source columns, map them, and choose import mode/options."""

    SKIP_MAPPING_TARGET = "__skip_field__"
    IDENTIFIER_CATEGORY_OPTIONS = (
        ("Catalog Number", "catalog_number"),
        ("Contract Number", "contract_number"),
        ("License Number", "license_number"),
        ("Registry SHA-256 Key", "registry_sha256_key"),
    )
    IDENTIFIER_REVIEW_TARGETS = frozenset(
        {"contract_number", "license_number", "registry_sha256_key"}
    )

    def __init__(
        self,
        *,
        inspection: ExchangeInspection,
        supported_headers: list[str],
        settings,
        initial_mode: str = "dry_run",
        csv_reinspect_callback: Callable[[str | None], ExchangeInspection] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.inspection = inspection
        self.supported_headers = supported_headers
        self.settings = settings
        self.initial_mode = str(initial_mode or "dry_run")
        self.csv_reinspect_callback = csv_reinspect_callback
        self._csv_delimiter_error: str | None = None
        self.identifier_review_table: QTableWidget | None = None
        self._identifier_review_reason_by_key = {
            str(row.review_key or "").strip(): str(row.reason or "").strip()
            for row in inspection.identifier_review_rows
            if str(row.review_key or "").strip()
        }

        self.setWindowTitle(f"Import {inspection.format_name.upper()}")
        self.resize(1100, 760)
        _apply_standard_dialog_chrome(self, "exchangeImportDialog")

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)
        _add_standard_dialog_header(
            root,
            self,
            title=self.windowTitle(),
            subtitle=(
                "Review the detected columns, adjust the mapping where needed, and choose how the import should match existing rows."
            ),
        )

        self.content_tabs = QTabWidget(self)
        self.content_tabs.setObjectName("exchangeImportTabs")
        self.content_tabs.setDocumentMode(True)
        root.addWidget(self.content_tabs, 1)

        setup_page = QWidget(self.content_tabs)
        setup_page.setProperty("role", "workspaceCanvas")
        setup_layout = QVBoxLayout(setup_page)
        setup_layout.setContentsMargins(0, 0, 0, 0)
        setup_layout.setSpacing(12)
        self.content_tabs.addTab(setup_page, "Setup & Mapping")

        preview_page = QWidget(self.content_tabs)
        preview_page.setProperty("role", "workspaceCanvas")
        preview_layout = QVBoxLayout(preview_page)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(12)
        self.content_tabs.addTab(preview_page, "Source Preview")

        review_layout: QVBoxLayout | None = None
        if any(
            str(name or "").strip() in self.IDENTIFIER_REVIEW_TARGETS
            for name in self.supported_headers
        ):
            review_page = QWidget(self.content_tabs)
            review_page.setProperty("role", "workspaceCanvas")
            review_layout = QVBoxLayout(review_page)
            review_layout.setContentsMargins(0, 0, 0, 0)
            review_layout.setSpacing(12)
            self.content_tabs.addTab(review_page, "Identifier Review")

        meta_row = QHBoxLayout()
        meta_row.setContentsMargins(0, 0, 0, 0)
        meta_row.setSpacing(8)
        self.source_label = QLabel(f"Source: {inspection.file_path}")
        meta_row.addWidget(self.source_label)
        meta_row.addStretch(1)
        self.warning_label = QLabel()
        self.warning_label.setWordWrap(True)
        meta_row.addWidget(self.warning_label)
        setup_layout.addLayout(meta_row)
        self._update_warning_label()

        self.delimiter_combo: QComboBox | None = None
        self.custom_delimiter_edit: QLineEdit | None = None
        self.delimiter_error_label: QLabel | None = None
        if self.inspection.format_name == "csv":
            delimiter_row = QHBoxLayout()
            delimiter_row.setContentsMargins(0, 0, 0, 0)
            delimiter_row.setSpacing(8)
            delimiter_row.addWidget(QLabel("Delimiter"))
            self.delimiter_combo = QComboBox(self)
            self.delimiter_combo.setObjectName("csvDelimiterCombo")
            self.delimiter_combo.addItem("Auto detect", "auto")
            self.delimiter_combo.addItem("Comma (,)", ",")
            self.delimiter_combo.addItem("Semicolon (;)", ";")
            self.delimiter_combo.addItem("Tab", "\t")
            self.delimiter_combo.addItem("Pipe (|)", "|")
            self.delimiter_combo.addItem("Custom delimiter", "custom")
            delimiter_row.addWidget(self.delimiter_combo)
            self.custom_delimiter_edit = QLineEdit(self)
            self.custom_delimiter_edit.setObjectName("csvCustomDelimiterEdit")
            self.custom_delimiter_edit.setPlaceholderText("One character")
            delimiter_row.addWidget(self.custom_delimiter_edit)
            delimiter_row.addStretch(1)
            setup_layout.addLayout(delimiter_row)

            self.delimiter_error_label = QLabel(self)
            self.delimiter_error_label.setObjectName("csvDelimiterErrorLabel")
            self.delimiter_error_label.setWordWrap(True)
            setup_layout.addWidget(self.delimiter_error_label)

        preset_row = QHBoxLayout()
        preset_row.setContentsMargins(0, 0, 0, 0)
        preset_row.setSpacing(8)
        preset_row.addWidget(QLabel("Mapping preset"))
        self.preset_combo = QComboBox()
        preset_row.addWidget(self.preset_combo, 1)
        load_preset_button = QPushButton("Load Preset")
        _connect_noarg_signal(load_preset_button.clicked, load_preset_button, self._load_preset)
        preset_row.addWidget(load_preset_button)
        self.preset_name_edit = QLineEdit()
        self.preset_name_edit.setPlaceholderText("Preset name")
        preset_row.addWidget(self.preset_name_edit)
        save_preset_button = QPushButton("Save Preset")
        _connect_noarg_signal(save_preset_button.clicked, save_preset_button, self._save_preset)
        preset_row.addWidget(save_preset_button)
        setup_layout.addLayout(preset_row)

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
        create_custom_label = "Create missing text custom fields"
        if self.inspection.format_name == "xml":
            create_custom_label = "Create missing custom fields"
        self.create_custom_checkbox = QCheckBox(create_custom_label)
        self.create_custom_checkbox.setChecked(True)
        option_row.addWidget(self.create_custom_checkbox)
        setup_layout.addLayout(option_row)

        self.remember_choices_checkbox = QCheckBox(
            f"Remember these {inspection.format_name.upper()} import choices"
        )
        self.remember_choices_checkbox.setObjectName("rememberImportChoicesCheckbox")
        setup_layout.addWidget(self.remember_choices_checkbox)

        self.mode_hint_label = QLabel()
        self.mode_hint_label.setWordWrap(True)
        setup_layout.addWidget(self.mode_hint_label)

        mapping_label = QLabel("Column Mapping")
        setup_layout.addWidget(mapping_label)

        self.mapping_table = QTableWidget(0, 2, self)
        self.mapping_table.setHorizontalHeaderLabels(["Source Column", "Map To"])
        self.mapping_table.verticalHeader().setVisible(False)
        self.mapping_table.horizontalHeader().setStretchLastSection(True)
        setup_layout.addWidget(self.mapping_table, 1)

        preview_label = QLabel("Source Preview")
        preview_layout.addWidget(preview_label)
        self.preview_table = QTableWidget(0, len(inspection.headers), self)
        self.preview_table.setHorizontalHeaderLabels(inspection.headers)
        self.preview_table.verticalHeader().setVisible(False)
        self.preview_table.horizontalHeader().setStretchLastSection(True)
        self.preview_table.setEditTriggers(QTableWidget.NoEditTriggers)
        preview_layout.addWidget(self.preview_table, 1)

        if review_layout is not None:
            review_label = QLabel(
                "Choose how staged external identifier values should be stored in Codespace when you apply the import."
            )
            review_label.setWordWrap(True)
            review_layout.addWidget(review_label)
            self.identifier_review_table = QTableWidget(0, 5, self)
            self.identifier_review_table.setHorizontalHeaderLabels(
                ["Row", "Source Column", "Store As", "Value", "Reason"]
            )
            self.identifier_review_table.verticalHeader().setVisible(False)
            self.identifier_review_table.horizontalHeader().setStretchLastSection(True)
            review_layout.addWidget(self.identifier_review_table, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.import_button = QPushButton("Run Import")
        self.import_button.setDefault(True)
        _connect_noarg_signal(self.import_button.clicked, self.import_button, self.accept)
        cancel_button = QPushButton("Cancel")
        _connect_noarg_signal(cancel_button.clicked, cancel_button, self.reject)
        buttons.addWidget(self.import_button)
        buttons.addWidget(cancel_button)
        root.addLayout(buttons)

        self._reload_presets()
        self._populate_mapping_table()
        self._populate_preview_table()
        self._populate_identifier_review_table()
        self._apply_initial_mode()
        _connect_noarg_signal(
            self.mode_combo.currentIndexChanged,
            self.mode_combo,
            self._update_mode_affordances,
        )
        if self.delimiter_combo is not None and self.custom_delimiter_edit is not None:
            _connect_noarg_signal(
                self.delimiter_combo.currentIndexChanged,
                self.delimiter_combo,
                self._on_csv_delimiter_changed,
            )
            _connect_noarg_signal(
                self.custom_delimiter_edit.textChanged,
                self.custom_delimiter_edit,
                self._on_csv_delimiter_changed,
            )
            self._update_csv_delimiter_widgets()
            self._set_csv_delimiter_error(None)
        self._load_saved_import_preferences()
        self._update_mode_affordances()
        _apply_compact_dialog_control_heights(self)

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

    def _import_preferences_key(self) -> str:
        return f"exchange/import_preferences/{self.inspection.format_name}"

    def _read_import_preferences(self) -> dict[str, object]:
        raw = self.settings.value(self._import_preferences_key(), "{}", str)
        try:
            payload = json.loads(str(raw or "{}"))
        except Exception:
            payload = {}
        return payload if isinstance(payload, dict) else {}

    def _write_import_preferences(self, payload: dict[str, object]) -> None:
        self.settings.setValue(
            self._import_preferences_key(),
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
        )
        self.settings.sync()

    def _load_saved_import_preferences(self) -> None:
        payload = self._read_import_preferences()
        if not payload:
            return
        mode = str(payload.get("mode") or "").strip()
        if mode:
            index = self.mode_combo.findData(mode)
            if index >= 0:
                self.mode_combo.setCurrentIndex(index)
        self.match_internal_checkbox.setChecked(
            bool(payload.get("match_by_internal_id", self.match_internal_checkbox.isChecked()))
        )
        self.match_isrc_checkbox.setChecked(
            bool(payload.get("match_by_isrc", self.match_isrc_checkbox.isChecked()))
        )
        self.match_upc_title_checkbox.setChecked(
            bool(payload.get("match_by_upc_title", self.match_upc_title_checkbox.isChecked()))
        )
        self.heuristic_checkbox.setChecked(
            bool(payload.get("heuristic_match", self.heuristic_checkbox.isChecked()))
        )
        self.create_custom_checkbox.setChecked(
            bool(
                payload.get(
                    "create_missing_custom_fields",
                    self.create_custom_checkbox.isChecked(),
                )
            )
        )
        if self.delimiter_combo is None:
            return
        delimiter_mode = str(payload.get("csv_delimiter_mode") or "").strip()
        custom_delimiter = str(payload.get("csv_custom_delimiter") or "")
        if delimiter_mode:
            index = self.delimiter_combo.findData(delimiter_mode)
            if index >= 0:
                self.delimiter_combo.setCurrentIndex(index)
        if self.custom_delimiter_edit is not None and custom_delimiter:
            self.custom_delimiter_edit.setText(custom_delimiter)

    def _current_import_preference_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "mode": str(self.mode_combo.currentData() or "dry_run"),
            "match_by_internal_id": self.match_internal_checkbox.isChecked(),
            "match_by_isrc": self.match_isrc_checkbox.isChecked(),
            "match_by_upc_title": self.match_upc_title_checkbox.isChecked(),
            "heuristic_match": self.heuristic_checkbox.isChecked(),
            "create_missing_custom_fields": self.create_custom_checkbox.isChecked(),
        }
        if self.delimiter_combo is not None:
            payload["csv_delimiter_mode"] = str(self.delimiter_combo.currentData() or "auto")
            if self.custom_delimiter_edit is not None:
                payload["csv_custom_delimiter"] = self.custom_delimiter_edit.text()
        return payload

    def _update_warning_label(self) -> None:
        warnings = self.inspection.warnings
        if warnings:
            self.warning_label.setText("Warnings: " + " | ".join(warnings))
            self.warning_label.show()
            return
        self.warning_label.clear()
        self.warning_label.hide()

    def _populate_mapping_table(self, preferred_mapping: dict[str, str] | None = None) -> None:
        headers = self.inspection.headers
        self.mapping_table.setRowCount(len(headers))
        for row, header in enumerate(headers):
            self.mapping_table.setItem(row, 0, QTableWidgetItem(header))
            combo = QComboBox(self.mapping_table)
            combo.addItem("", "")
            combo.addItem("Skip this field", self.SKIP_MAPPING_TARGET)
            for target_name in self.supported_headers:
                combo.addItem(target_name, target_name)
            suggested = (
                preferred_mapping.get(header, "")
                if preferred_mapping is not None
                else self.inspection.suggested_mapping.get(header, "")
            )
            if not suggested:
                suggested = self.inspection.suggested_mapping.get(header, "")
            index = combo.findData(suggested)
            combo.setCurrentIndex(index if index >= 0 else 0)
            _connect_noarg_signal(combo.currentIndexChanged, combo, self._on_mapping_changed)
            self.mapping_table.setCellWidget(row, 1, combo)

    def _populate_preview_table(self) -> None:
        rows = self.inspection.preview_rows
        self.preview_table.clearContents()
        self.preview_table.setColumnCount(len(self.inspection.headers))
        self.preview_table.setHorizontalHeaderLabels(self.inspection.headers)
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
        self._apply_dialog_validation()

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
            index = combo.findData(value)
            combo.setCurrentIndex(index if index >= 0 else 0)

    def mapping(self) -> dict[str, str]:
        mapped: dict[str, str] = {}
        for row in range(self.mapping_table.rowCount()):
            header_item = self.mapping_table.item(row, 0)
            combo = self.mapping_table.cellWidget(row, 1)
            if header_item is None or combo is None:
                continue
            source = header_item.text()
            target = str(combo.currentData() or "").strip()
            if target and target != self.SKIP_MAPPING_TARGET:
                mapped[source] = target
        return mapped

    def skipped_source_headers(self) -> list[str]:
        skipped: list[str] = []
        for row in range(self.mapping_table.rowCount()):
            header_item = self.mapping_table.item(row, 0)
            combo = self.mapping_table.cellWidget(row, 1)
            if header_item is None or combo is None:
                continue
            if str(combo.currentData() or "") == self.SKIP_MAPPING_TARGET:
                skipped.append(header_item.text())
        return skipped

    def import_options(self) -> ExchangeImportOptions:
        return ExchangeImportOptions(
            mode=str(self.mode_combo.currentData() or "dry_run"),
            match_by_internal_id=self.match_internal_checkbox.isChecked(),
            match_by_isrc=self.match_isrc_checkbox.isChecked(),
            match_by_upc_title=self.match_upc_title_checkbox.isChecked(),
            heuristic_match=self.heuristic_checkbox.isChecked(),
            create_missing_custom_fields=self.create_custom_checkbox.isChecked(),
            skip_targets=self.skipped_source_headers(),
            identifier_overrides=self._identifier_overrides(),
        )

    def resolved_csv_delimiter(self) -> str | None:
        if self.delimiter_combo is None:
            return None
        current = str(self.delimiter_combo.currentData() or "auto")
        if current == "auto":
            return self.inspection.resolved_delimiter
        if current == "custom":
            delimiter, _error = self._validate_custom_delimiter()
            return delimiter
        return current

    def _apply_inspection(
        self,
        inspection: ExchangeInspection,
        *,
        preferred_mapping: dict[str, str] | None = None,
    ) -> None:
        self.inspection = inspection
        self._identifier_review_reason_by_key = {
            str(row.review_key or "").strip(): str(row.reason or "").strip()
            for row in inspection.identifier_review_rows
            if str(row.review_key or "").strip()
        }
        self.source_label.setText(f"Source: {inspection.file_path}")
        self._update_warning_label()
        self._populate_mapping_table(preferred_mapping=preferred_mapping)
        self._populate_preview_table()
        self._populate_identifier_review_table()

    def _apply_dialog_validation(self) -> None:
        self.import_button.setEnabled(not bool(self._csv_delimiter_error))

    def _set_csv_delimiter_error(self, message: str | None) -> None:
        self._csv_delimiter_error = str(message).strip() if message is not None else None
        if self._csv_delimiter_error == "":
            self._csv_delimiter_error = None
        if self.delimiter_error_label is None:
            return
        if self._csv_delimiter_error:
            self.delimiter_error_label.setText(self._csv_delimiter_error)
            self.delimiter_error_label.show()
        else:
            self.delimiter_error_label.clear()
            self.delimiter_error_label.hide()
        self._apply_dialog_validation()

    def _update_csv_delimiter_widgets(self) -> None:
        if self.delimiter_combo is None or self.custom_delimiter_edit is None:
            return
        is_custom = str(self.delimiter_combo.currentData() or "auto") == "custom"
        self.custom_delimiter_edit.setVisible(is_custom)

    def _validate_custom_delimiter(self) -> tuple[str | None, str | None]:
        if self.delimiter_combo is None or self.custom_delimiter_edit is None:
            return None, None
        if str(self.delimiter_combo.currentData() or "auto") != "custom":
            return None, None
        delimiter = self.custom_delimiter_edit.text()
        if not delimiter:
            return None, "Enter a custom delimiter."
        if len(delimiter) != 1 or delimiter in {"\r", "\n"}:
            return None, "Custom delimiter must be exactly one non-newline character."
        if delimiter == "\t":
            return None, "Use the Tab option for tab-delimited files."
        return delimiter, None

    def _requested_csv_delimiter(self) -> tuple[str | None, str | None]:
        if self.delimiter_combo is None:
            return None, None
        current = str(self.delimiter_combo.currentData() or "auto")
        if current == "auto":
            return None, None
        if current == "custom":
            return self._validate_custom_delimiter()
        return current, None

    def _on_csv_delimiter_changed(self) -> None:
        self._update_csv_delimiter_widgets()
        requested_delimiter, error = self._requested_csv_delimiter()
        if error:
            self._set_csv_delimiter_error(error)
            return
        if self.csv_reinspect_callback is None:
            self._set_csv_delimiter_error(None)
            return
        preferred_mapping = self.mapping()
        try:
            inspection = self.csv_reinspect_callback(requested_delimiter)
        except Exception as exc:
            self._set_csv_delimiter_error(str(exc))
            return
        self._set_csv_delimiter_error(None)
        self._apply_inspection(inspection, preferred_mapping=preferred_mapping)

    @staticmethod
    def _identifier_review_key(
        *,
        row_index: int,
        source_header: str,
        target_field_name: str,
        value: str,
    ) -> str:
        return "|".join(
            (
                str(int(row_index)),
                str(source_header or "").strip(),
                str(target_field_name or "").strip(),
                str(value or "").strip(),
            )
        )

    def _identifier_review_rows(self) -> list[tuple[str, int, str, str, str, str]]:
        rows: list[tuple[str, int, str, str, str, str]] = []
        mapping = self.mapping()
        for row_index, preview_row in enumerate(self.inspection.preview_rows, start=1):
            for source_header, target_field_name in mapping.items():
                clean_target = str(target_field_name or "").strip()
                if clean_target not in self.IDENTIFIER_REVIEW_TARGETS:
                    continue
                clean_value = str(preview_row.get(source_header) or "").strip()
                if not clean_value:
                    continue
                review_key = self._identifier_review_key(
                    row_index=row_index,
                    source_header=source_header,
                    target_field_name=clean_target,
                    value=clean_value,
                )
                rows.append(
                    (
                        review_key,
                        int(row_index),
                        str(source_header),
                        clean_target,
                        clean_value,
                        self._identifier_review_reason_by_key.get(review_key)
                        or (
                            "Staged only until apply. The selected type controls which "
                            "External Identifier bucket receives this value."
                        ),
                    )
                )
        return rows

    def _populate_identifier_review_table(self) -> None:
        if self.identifier_review_table is None:
            return
        existing_overrides = self._identifier_overrides()
        rows = self._identifier_review_rows()
        self.identifier_review_table.clearContents()
        self.identifier_review_table.setRowCount(len(rows))
        for row_index, (
            review_key,
            source_row,
            source_header,
            target_name,
            value,
            reason,
        ) in enumerate(rows):
            row_item = QTableWidgetItem(str(source_row))
            row_item.setData(0x0100, review_key)
            self.identifier_review_table.setItem(row_index, 0, row_item)
            self.identifier_review_table.setItem(row_index, 1, QTableWidgetItem(source_header))
            combo = QComboBox(self.identifier_review_table)
            for label, system_key in self.IDENTIFIER_CATEGORY_OPTIONS:
                combo.addItem(label, system_key)
            combo_index = combo.findData(existing_overrides.get(review_key) or target_name)
            combo.setCurrentIndex(combo_index if combo_index >= 0 else 0)
            self.identifier_review_table.setCellWidget(row_index, 2, combo)
            self.identifier_review_table.setItem(row_index, 3, QTableWidgetItem(value))
            self.identifier_review_table.setItem(row_index, 4, QTableWidgetItem(reason))

    def _identifier_overrides(self) -> dict[str, str]:
        if self.identifier_review_table is None:
            return {}
        overrides: dict[str, str] = {}
        for row in range(self.identifier_review_table.rowCount()):
            key_item = self.identifier_review_table.item(row, 0)
            combo = self.identifier_review_table.cellWidget(row, 2)
            if key_item is None or combo is None:
                continue
            review_key = str(key_item.data(0x0100) or "").strip()
            selected = str(combo.currentData() or "").strip()
            if review_key and selected:
                overrides[review_key] = selected
        return overrides

    def _on_mapping_changed(self) -> None:
        self._populate_identifier_review_table()

    def accept(self) -> None:
        if self.remember_choices_checkbox.isChecked():
            self._write_import_preferences(self._current_import_preference_payload())
        super().accept()

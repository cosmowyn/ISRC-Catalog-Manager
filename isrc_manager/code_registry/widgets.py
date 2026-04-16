"""Reusable Qt widgets for code-registry-backed editing flows."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QCompleter,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .models import (
    BUILTIN_CATEGORY_CATALOG_NUMBER,
    BUILTIN_CATEGORY_CONTRACT_NUMBER,
    BUILTIN_CATEGORY_LICENSE_NUMBER,
    BUILTIN_CATEGORY_REGISTRY_SHA256_KEY,
    CATALOG_MODE_EMPTY,
    CATALOG_MODE_EXTERNAL,
    CATALOG_MODE_INTERNAL,
    CLASSIFICATION_CANONICAL_CANDIDATE,
    CLASSIFICATION_EXTERNAL,
    CLASSIFICATION_INTERNAL,
    CLASSIFICATION_MISMATCH,
)
from .service import CodeRegistryService

_DEFAULT_GENERATE_LABELS = {
    BUILTIN_CATEGORY_CATALOG_NUMBER: "Generate",
    BUILTIN_CATEGORY_CONTRACT_NUMBER: "Generate",
    BUILTIN_CATEGORY_LICENSE_NUMBER: "Generate",
    BUILTIN_CATEGORY_REGISTRY_SHA256_KEY: "Generate Key",
}


class CodeIdentifierSelector(QWidget):
    """Editor control for internal-vs-external code identifier values."""

    valueChanged = Signal()

    def __init__(
        self,
        *,
        service_provider: Callable[[], CodeRegistryService | None],
        system_key: str = BUILTIN_CATEGORY_CATALOG_NUMBER,
        allow_generate: bool = True,
        created_via: str,
        external_mode_label: str = "External Identifiers",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.service_provider = service_provider
        self.system_key = str(system_key or BUILTIN_CATEGORY_CATALOG_NUMBER).strip()
        self.allow_generate = bool(allow_generate)
        self.created_via = str(created_via or "ui.identifier")
        self.external_mode_label = str(external_mode_label or "External Identifiers")
        self._registry_entry_id: int | None = None
        self._external_identifier_id: int | None = None
        self._loaded_external_value: str | None = None
        self._internal_value_to_entry_id: dict[str, int] = {}
        self._build_ui()
        self.refresh_choices()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        row = QWidget(self)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)

        self.mode_combo = QComboBox(row)
        self.mode_combo.addItem("Internal Registry", CATALOG_MODE_INTERNAL)
        self.mode_combo.addItem(self.external_mode_label, CATALOG_MODE_EXTERNAL)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        row_layout.addWidget(self.mode_combo)

        self.value_combo = QComboBox(row)
        self.value_combo.setEditable(True)
        self.value_combo.setInsertPolicy(QComboBox.NoInsert)
        self.value_combo.currentIndexChanged.connect(self._on_value_changed)
        line_edit = self.value_combo.lineEdit()
        if line_edit is not None:
            line_edit.textEdited.connect(self._on_text_edited)
        row_layout.addWidget(self.value_combo, 1)
        self.combo = self.value_combo

        self.generate_button = QPushButton(
            _DEFAULT_GENERATE_LABELS.get(self.system_key, "Generate"),
            row,
        )
        self.generate_button.clicked.connect(self.generate_value)
        row_layout.addWidget(self.generate_button)

        layout.addWidget(row)

        self.status_label = QLabel("", self)
        self.status_label.setWordWrap(True)
        self.status_label.setProperty("role", "supportingText")
        layout.addWidget(self.status_label)

    def _service(self) -> CodeRegistryService | None:
        try:
            return self.service_provider()
        except Exception:
            return None

    def _category(self):
        service = self._service()
        if service is None:
            return None
        return service.fetch_category_by_system_key(self.system_key)

    def _current_mode(self) -> str:
        data = self.mode_combo.currentData()
        clean_mode = str(data or CATALOG_MODE_EXTERNAL).strip().lower()
        if clean_mode not in {CATALOG_MODE_INTERNAL, CATALOG_MODE_EXTERNAL, CATALOG_MODE_EMPTY}:
            return CATALOG_MODE_EXTERNAL
        return clean_mode

    def _generation_unavailable_reason(self) -> str | None:
        if not self.allow_generate or self._current_mode() != CATALOG_MODE_INTERNAL:
            return None
        service = self._service()
        if service is None:
            return "Open a profile to use internal registry generation."
        return service.generation_unavailable_reason(system_key=self.system_key)

    def refresh_choices(self) -> None:
        service = self._service()
        current_text = self.value_combo.currentText().strip()
        category = self._category()
        if service is None or category is None:
            self._internal_value_to_entry_id = {}
            values: list[str] = []
        elif self._current_mode() == CATALOG_MODE_INTERNAL:
            entries = service.list_entries(category_id=category.id)
            self._internal_value_to_entry_id = {
                str(entry.value): int(entry.id) for entry in entries
            }
            values = sorted(self._internal_value_to_entry_id)
        else:
            self._internal_value_to_entry_id = {}
            values = service.external_identifier_suggestions(system_key=self.system_key)
        previous = self.value_combo.blockSignals(True)
        try:
            self.value_combo.clear()
            self.value_combo.addItem("")
            self.value_combo.addItems(values)
            completer = QCompleter(values, self.value_combo)
            completer.setCaseSensitivity(Qt.CaseInsensitive)
            self.value_combo.setCompleter(completer)
            if current_text:
                index = self.value_combo.findText(current_text)
                if index >= 0:
                    self.value_combo.setCurrentIndex(index)
                else:
                    self.value_combo.setCurrentIndex(-1)
                    self.value_combo.setEditText(current_text)
            else:
                self.value_combo.setCurrentIndex(0)
        finally:
            self.value_combo.blockSignals(previous)
        generation_reason = self._generation_unavailable_reason()
        internal_generation_mode = (
            self.allow_generate and self._current_mode() == CATALOG_MODE_INTERNAL
        )
        self.generate_button.setVisible(internal_generation_mode)
        self.generate_button.setEnabled(internal_generation_mode and generation_reason is None)
        self.generate_button.setToolTip(generation_reason or "")
        self._sync_ids_from_text()
        self._refresh_status()

    def refresh(self) -> None:
        self.refresh_choices()

    def _sync_ids_from_text(self) -> None:
        current_text = self.value_combo.currentText().strip()
        if self._current_mode() == CATALOG_MODE_INTERNAL:
            self._registry_entry_id = self._internal_value_to_entry_id.get(current_text)
            self._external_identifier_id = None
            return
        if current_text != str(self._loaded_external_value or "").strip():
            self._external_identifier_id = None
        self._registry_entry_id = None

    def _on_mode_changed(self, _index: int) -> None:
        if self._current_mode() == CATALOG_MODE_INTERNAL:
            self._external_identifier_id = None
        else:
            self._registry_entry_id = None
        self.refresh_choices()
        self.valueChanged.emit()

    def _on_value_changed(self, _index: int) -> None:
        self._sync_ids_from_text()
        self._refresh_status()
        self.valueChanged.emit()

    def _on_text_edited(self, _text: str) -> None:
        if self._current_mode() == CATALOG_MODE_INTERNAL:
            self._registry_entry_id = None
        else:
            self._external_identifier_id = None
        self._refresh_status()
        self.valueChanged.emit()

    def _blank_status_message(self) -> str:
        category = self._category()
        label = category.display_name if category is not None else "identifier"
        return f"No {label.lower()} selected."

    def _refresh_status(self) -> None:
        clean_value = self.value_combo.currentText().strip()
        generation_reason = self._generation_unavailable_reason()
        if not clean_value:
            self.status_label.setText(generation_reason or self._blank_status_message())
            return
        service = self._service()
        category = self._category()
        if service is None or category is None:
            self.status_label.setText("")
            return
        classification = service.classify_identifier_value(
            system_key=self.system_key,
            value=clean_value,
            allow_existing_internal_match=(self.system_key == BUILTIN_CATEGORY_REGISTRY_SHA256_KEY),
        )
        if self._current_mode() == CATALOG_MODE_INTERNAL:
            if self._registry_entry_id is not None:
                self.status_label.setText("Selected existing immutable registry value.")
            elif generation_reason:
                self.status_label.setText(generation_reason)
            elif classification.classification == CLASSIFICATION_INTERNAL:
                self.status_label.setText(
                    f"Matches the canonical internal format and will be captured as an immutable {category.display_name.lower()} on save."
                )
            else:
                self.status_label.setText(
                    classification.reason
                    or f"This value does not match the configured internal rules for {category.display_name.lower()}."
                )
            return
        if classification.classification == CLASSIFICATION_MISMATCH:
            self.status_label.setText(
                f"{self.external_mode_label}. Known internal family, but non-canonical format: "
                + str(classification.reason or "")
            )
        elif classification.classification == CLASSIFICATION_CANONICAL_CANDIDATE:
            self.status_label.setText(
                f"{self.external_mode_label} for now. This looks canonical, but no active internal prefix is configured."
            )
        elif classification.classification == CLASSIFICATION_EXTERNAL:
            self.status_label.setText(f"{self.external_mode_label} value.")
        else:
            self.status_label.setText(
                f"{self.external_mode_label} mode is active. Switch to Internal Registry if this should be app-managed."
            )

    def set_value(
        self,
        *,
        value: str | None = None,
        catalog_number: str | None = None,
        registry_entry_id: int | None = None,
        catalog_registry_entry_id: int | None = None,
        external_identifier_id: int | None = None,
        external_catalog_identifier_id: int | None = None,
        mode: str | None = None,
    ) -> None:
        clean_value = str(value if value is not None else catalog_number or "").strip()
        resolved_registry_entry_id = (
            int(registry_entry_id)
            if registry_entry_id is not None
            else (int(catalog_registry_entry_id) if catalog_registry_entry_id is not None else None)
        )
        resolved_external_identifier_id = (
            int(external_identifier_id)
            if external_identifier_id is not None
            else (
                int(external_catalog_identifier_id)
                if external_catalog_identifier_id is not None
                else None
            )
        )
        resolved_mode = str(mode or "").strip().lower()
        if resolved_mode not in {CATALOG_MODE_INTERNAL, CATALOG_MODE_EXTERNAL, CATALOG_MODE_EMPTY}:
            if resolved_registry_entry_id is not None:
                resolved_mode = CATALOG_MODE_INTERNAL
            elif resolved_external_identifier_id is not None or clean_value:
                resolved_mode = CATALOG_MODE_EXTERNAL
            else:
                resolved_mode = CATALOG_MODE_EMPTY
        self.mode_combo.setCurrentIndex(self.mode_combo.findData(resolved_mode))
        self.refresh_choices()
        previous = self.value_combo.blockSignals(True)
        try:
            if clean_value:
                index = self.value_combo.findText(clean_value)
                if index >= 0:
                    self.value_combo.setCurrentIndex(index)
                else:
                    self.value_combo.setCurrentIndex(-1)
                    self.value_combo.setEditText(clean_value)
            else:
                self.value_combo.setCurrentIndex(0)
        finally:
            self.value_combo.blockSignals(previous)
        self._registry_entry_id = resolved_registry_entry_id
        self._external_identifier_id = resolved_external_identifier_id
        self._loaded_external_value = clean_value or None
        if resolved_registry_entry_id is None and resolved_external_identifier_id is None:
            self._sync_ids_from_text()
        self._refresh_status()

    def identifier_value(self) -> str | None:
        clean_value = self.value_combo.currentText().strip()
        return clean_value or None

    def identifier_mode(self) -> str:
        return self._current_mode()

    def registry_entry_id(self) -> int | None:
        self._sync_ids_from_text()
        return self._registry_entry_id if self._current_mode() == CATALOG_MODE_INTERNAL else None

    @property
    def entry_id(self) -> int | None:
        return self.registry_entry_id()

    def external_code_identifier_id(self) -> int | None:
        self._sync_ids_from_text()
        return (
            self._external_identifier_id if self._current_mode() == CATALOG_MODE_EXTERNAL else None
        )

    def catalog_number(self) -> str | None:
        return self.identifier_value()

    def mode(self) -> str:
        return self.identifier_mode()

    def currentText(self) -> str:
        return self.value_combo.currentText()

    def setCurrentText(self, value: str | None) -> None:
        clean_value = str(value or "").strip()
        if not clean_value:
            self.set_value()
            return
        self.set_value(value=clean_value)

    def lineEdit(self):
        return self.value_combo.lineEdit()

    def set_assignment(
        self,
        *,
        value: str | None,
        registry_entry_id: int | None,
        external_identifier_id: int | None = None,
        external_catalog_identifier_id: int | None = None,
        mode: str | None = None,
    ) -> None:
        self.set_value(
            value=value,
            registry_entry_id=registry_entry_id,
            external_identifier_id=external_identifier_id,
            external_catalog_identifier_id=external_catalog_identifier_id,
            mode=mode,
        )

    def catalog_registry_entry_id(self) -> int | None:
        return self.registry_entry_id()

    def external_catalog_identifier_id(self) -> int | None:
        return self.external_code_identifier_id()

    def value(self) -> str | None:
        return self.identifier_value()

    def generate_value(self) -> None:
        service = self._service()
        if service is None:
            return
        generation_reason = self._generation_unavailable_reason()
        if generation_reason:
            self.status_label.setText(generation_reason)
            return
        result = (
            service.generate_sha256_key(
                system_key=self.system_key,
                created_via=f"{self.created_via}.generate",
            )
            if self.system_key == BUILTIN_CATEGORY_REGISTRY_SHA256_KEY
            else service.generate_next_code(
                system_key=self.system_key,
                created_via=f"{self.created_via}.generate",
            )
        )
        self.mode_combo.setCurrentIndex(self.mode_combo.findData(CATALOG_MODE_INTERNAL))
        self.refresh_choices()
        self.value_combo.setCurrentText(result.entry.value)
        self._registry_entry_id = int(result.entry.id)
        self._external_identifier_id = None
        self._refresh_status()
        self.valueChanged.emit()


CatalogIdentifierSelector = CodeIdentifierSelector
CatalogIdentifierField = CodeIdentifierSelector

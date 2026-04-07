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
    CATALOG_MODE_EMPTY,
    CATALOG_MODE_EXTERNAL,
    CATALOG_MODE_INTERNAL,
    CLASSIFICATION_CANONICAL_CANDIDATE,
    CLASSIFICATION_EXTERNAL,
    CLASSIFICATION_INTERNAL,
    CLASSIFICATION_MISMATCH,
    SUBJECT_KIND_CATALOG,
)
from .service import CodeRegistryService


class CatalogIdentifierSelector(QWidget):
    """Editor control for internal-vs-external catalog identifiers."""

    valueChanged = Signal()

    def __init__(
        self,
        *,
        service_provider: Callable[[], CodeRegistryService | None],
        allow_generate: bool = True,
        created_via: str,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.service_provider = service_provider
        self.allow_generate = bool(allow_generate)
        self.created_via = str(created_via or "ui.catalog")
        self._catalog_registry_entry_id: int | None = None
        self._external_catalog_identifier_id: int | None = None
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
        self.mode_combo.addItem("External Catalog", CATALOG_MODE_EXTERNAL)
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

        self.generate_button = QPushButton("Generate", row)
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

    def _current_mode(self) -> str:
        data = self.mode_combo.currentData()
        clean_mode = str(data or CATALOG_MODE_EXTERNAL).strip().lower()
        if clean_mode not in {CATALOG_MODE_INTERNAL, CATALOG_MODE_EXTERNAL, CATALOG_MODE_EMPTY}:
            return CATALOG_MODE_EXTERNAL
        return clean_mode

    def refresh_choices(self) -> None:
        service = self._service()
        current_text = self.value_combo.currentText().strip()
        if service is None:
            return
        self._internal_value_to_entry_id = {
            str(choice.value): int(choice.entry_id)
            for choice in service.list_choices_for_subject(subject_kind=SUBJECT_KIND_CATALOG)
        }
        if self._current_mode() == CATALOG_MODE_INTERNAL:
            values = sorted(self._internal_value_to_entry_id)
        else:
            values = service.external_catalog_suggestions()
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
        self.generate_button.setVisible(
            self.allow_generate and self._current_mode() == CATALOG_MODE_INTERNAL
        )
        self._sync_ids_from_text()
        self._refresh_status()

    def refresh(self) -> None:
        self.refresh_choices()

    def _sync_ids_from_text(self) -> None:
        current_text = self.value_combo.currentText().strip()
        if self._current_mode() == CATALOG_MODE_INTERNAL:
            self._catalog_registry_entry_id = self._internal_value_to_entry_id.get(current_text)
            self._external_catalog_identifier_id = None
            return
        if current_text != str(self._loaded_external_value or "").strip():
            self._external_catalog_identifier_id = None
        self._catalog_registry_entry_id = None

    def _on_mode_changed(self, _index: int) -> None:
        if self._current_mode() == CATALOG_MODE_INTERNAL:
            self._external_catalog_identifier_id = None
        else:
            self._catalog_registry_entry_id = None
        self.refresh_choices()
        self.valueChanged.emit()

    def _on_value_changed(self, _index: int) -> None:
        self._sync_ids_from_text()
        self._refresh_status()
        self.valueChanged.emit()

    def _on_text_edited(self, _text: str) -> None:
        if self._current_mode() == CATALOG_MODE_INTERNAL:
            self._catalog_registry_entry_id = None
        else:
            self._external_catalog_identifier_id = None
        self._refresh_status()
        self.valueChanged.emit()

    def _refresh_status(self) -> None:
        clean_value = self.value_combo.currentText().strip()
        if not clean_value:
            self.status_label.setText("No catalog identifier selected.")
            return
        service = self._service()
        if service is None:
            self.status_label.setText("")
            return
        if self._current_mode() == CATALOG_MODE_INTERNAL:
            classification = service.classify_catalog_identifier(clean_value)
            if self._catalog_registry_entry_id is not None:
                self.status_label.setText("Internal Registry value.")
            elif classification.classification == CLASSIFICATION_INTERNAL:
                self.status_label.setText(
                    "Matches the canonical internal format and will be captured as an immutable registry value on save."
                )
            else:
                self.status_label.setText(
                    classification.reason
                    or "This value does not match the configured internal catalog rules."
                )
            return
        classification = service.classify_catalog_identifier(clean_value)
        if classification.classification == CLASSIFICATION_MISMATCH:
            self.status_label.setText(
                "External Catalog. Known internal prefix, but non-canonical format: "
                + str(classification.reason or "")
            )
        elif classification.classification == CLASSIFICATION_CANONICAL_CANDIDATE:
            self.status_label.setText(
                "External Catalog for now. This looks canonical but no matching internal prefix is configured."
            )
        elif classification.classification == CLASSIFICATION_EXTERNAL:
            self.status_label.setText("External Catalog value.")
        else:
            self.status_label.setText(
                "External Catalog mode is active. Switch to Internal Registry if this should be app-managed."
            )

    def set_value(
        self,
        *,
        catalog_number: str | None,
        catalog_registry_entry_id: int | None,
        external_catalog_identifier_id: int | None,
    ) -> None:
        clean_value = str(catalog_number or "").strip()
        if catalog_registry_entry_id is not None:
            self.mode_combo.setCurrentIndex(self.mode_combo.findData(CATALOG_MODE_INTERNAL))
            self.refresh_choices()
            index = self.value_combo.findData(int(catalog_registry_entry_id))
            if index >= 0:
                self.value_combo.setCurrentIndex(index)
            elif clean_value:
                self.value_combo.setCurrentIndex(-1)
                self.value_combo.setEditText(clean_value)
            self._catalog_registry_entry_id = int(catalog_registry_entry_id)
            self._external_catalog_identifier_id = None
            self._loaded_external_value = None
        else:
            self.mode_combo.setCurrentIndex(self.mode_combo.findData(CATALOG_MODE_EXTERNAL))
            self.refresh_choices()
            if clean_value:
                index = self.value_combo.findText(clean_value)
                if index >= 0:
                    self.value_combo.setCurrentIndex(index)
                else:
                    self.value_combo.setCurrentIndex(-1)
                    self.value_combo.setEditText(clean_value)
            else:
                self.value_combo.setCurrentIndex(0)
            self._catalog_registry_entry_id = None
            self._external_catalog_identifier_id = (
                int(external_catalog_identifier_id)
                if external_catalog_identifier_id is not None
                else None
            )
            self._loaded_external_value = clean_value or None
        self._refresh_status()

    def catalog_number(self) -> str | None:
        clean_value = self.value_combo.currentText().strip()
        return clean_value or None

    def currentText(self) -> str:
        return self.value_combo.currentText()

    def setCurrentText(self, value: str | None) -> None:
        clean_value = str(value or "").strip()
        if not clean_value:
            self.set_value(
                catalog_number=None,
                catalog_registry_entry_id=None,
                external_catalog_identifier_id=None,
            )
            return
        service = self._service()
        classification = (
            service.classify_catalog_identifier(clean_value) if service is not None else None
        )
        if classification is not None and classification.classification == CLASSIFICATION_INTERNAL:
            self.set_value(
                catalog_number=clean_value,
                catalog_registry_entry_id=self._internal_value_to_entry_id.get(clean_value),
                external_catalog_identifier_id=None,
            )
            return
        self.set_value(
            catalog_number=clean_value,
            catalog_registry_entry_id=None,
            external_catalog_identifier_id=None,
        )

    def lineEdit(self):
        return self.value_combo.lineEdit()

    def set_assignment(
        self,
        *,
        value: str | None,
        registry_entry_id: int | None,
        external_catalog_identifier_id: int | None,
    ) -> None:
        self.set_value(
            catalog_number=value,
            catalog_registry_entry_id=registry_entry_id,
            external_catalog_identifier_id=external_catalog_identifier_id,
        )

    def catalog_registry_entry_id(self) -> int | None:
        self._sync_ids_from_text()
        return (
            self._catalog_registry_entry_id
            if self._current_mode() == CATALOG_MODE_INTERNAL
            else None
        )

    def external_catalog_identifier_id(self) -> int | None:
        self._sync_ids_from_text()
        return (
            self._external_catalog_identifier_id
            if self._current_mode() == CATALOG_MODE_EXTERNAL
            else None
        )

    def generate_value(self) -> None:
        service = self._service()
        if service is None:
            return
        result = service.generate_next_code(
            system_key=BUILTIN_CATEGORY_CATALOG_NUMBER,
            created_via=f"{self.created_via}.generate",
        )
        self.mode_combo.setCurrentIndex(self.mode_combo.findData(CATALOG_MODE_INTERNAL))
        self.refresh_choices()
        self.value_combo.setCurrentText(result.entry.value)
        self._catalog_registry_entry_id = int(result.entry.id)
        self._external_catalog_identifier_id = None
        self._refresh_status()
        self.valueChanged.emit()


CatalogIdentifierField = CatalogIdentifierSelector

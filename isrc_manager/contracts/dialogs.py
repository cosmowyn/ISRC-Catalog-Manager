"""Contract manager dialogs."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
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
from isrc_manager.ui_common import (
    FocusWheelComboBox,
    _add_standard_dialog_header,
    _apply_compact_dialog_control_heights,
    _apply_standard_dialog_chrome,
    _apply_standard_widget_chrome,
    _configure_standard_form_layout,
    _confirm_destructive_action,
    _create_action_button_cluster,
    _create_scrollable_dialog_content,
    _create_standard_section,
)

from .models import (
    CONTRACT_STATUS_CHOICES,
    DOCUMENT_TYPE_CHOICES,
    OBLIGATION_TYPE_CHOICES,
    ContractDocumentPayload,
    ContractDocumentRecord,
    ContractObligationPayload,
    ContractPartyPayload,
    ContractPayload,
)
from .service import ContractService


def _parse_bool_token(value: str) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def _parse_int_list(text: str) -> list[int]:
    values: list[int] = []
    for part in str(text or "").replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        values.append(int(part))
    return values


def _parse_optional_int(text: str) -> int | None:
    clean = str(text or "").strip()
    if not clean:
        return None
    return int(clean)


@dataclass(slots=True)
class _ReferenceChoice:
    reference_id: int
    label: str
    unresolved: bool = False


def _normalize_reference_text(value: str | None) -> str:
    return " ".join(str(value or "").split()).casefold()


def _unknown_reference_choice(reference_id: int) -> _ReferenceChoice:
    return _ReferenceChoice(int(reference_id), f"Unknown #{int(reference_id)}", unresolved=True)


def _reference_choice_display_text(choice: _ReferenceChoice) -> str:
    if choice.unresolved:
        return choice.label
    label = str(choice.label or "").strip() or f"Record #{choice.reference_id}"
    return f"{choice.reference_id} - {label}"


def _extract_reference_id(text: str | None) -> int | None:
    clean = str(text or "").strip()
    if not clean:
        return None
    if clean.isdigit():
        return int(clean)
    if clean.startswith("#") and clean[1:].isdigit():
        return int(clean[1:])
    prefix, separator, _ = clean.partition(" - ")
    if separator and prefix.strip().isdigit():
        return int(prefix.strip())
    lowered = clean.lower()
    if lowered.startswith("unknown #"):
        candidate = clean.split("#", 1)[1].split(" ", 1)[0].strip()
        if candidate.isdigit():
            return int(candidate)
    return None


def _build_reference_completer(combo: QComboBox, values: list[str]) -> None:
    completer = QCompleter(values, combo)
    completer.setCaseSensitivity(Qt.CaseInsensitive)
    combo.setCompleter(completer)


def _build_text_completer(line_edit: QLineEdit, values: list[str]) -> None:
    completer = QCompleter(values, line_edit)
    completer.setCaseSensitivity(Qt.CaseInsensitive)
    line_edit.setCompleter(completer)


_CONTRACT_PARTY_ROLE_PRESETS = (
    "counterparty",
    "licensor",
    "licensee",
    "label",
    "publisher",
    "distributor",
    "manager",
    "producer",
    "rights holder",
    "administrator",
)


def _primary_reference_label(label: str | None) -> str:
    clean = str(label or "").strip()
    primary, _separator, _remainder = clean.partition(" / ")
    return primary or clean


def _reference_choice_variants(choice: _ReferenceChoice) -> list[str]:
    label = str(choice.label or "").strip()
    variants: list[str] = []
    seen: set[str] = set()
    for candidate in [label, *[part.strip() for part in label.split(" / ") if part.strip()]]:
        normalized = _normalize_reference_text(candidate)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        variants.append(candidate)
    if not variants:
        variants.append(f"Record #{choice.reference_id}")
    return variants


def _normalized_tokens(value: str | None) -> set[str]:
    clean = _normalize_reference_text(value).replace("/", " ").replace("-", " ")
    return {token for token in clean.split() if token}


def _reference_choice_similarity(search_text: str | None, choice: _ReferenceChoice) -> float:
    normalized_search = _normalize_reference_text(search_text)
    if len(normalized_search) < 4:
        return 0.0
    search_tokens = _normalized_tokens(search_text)
    best_score = 0.0
    for variant in _reference_choice_variants(choice):
        normalized_variant = _normalize_reference_text(variant)
        if not normalized_variant:
            continue
        if normalized_search == normalized_variant:
            return 1.0
        score = SequenceMatcher(None, normalized_search, normalized_variant).ratio()
        if normalized_search in normalized_variant or normalized_variant in normalized_search:
            score = max(score, 0.92)
        variant_tokens = _normalized_tokens(variant)
        if search_tokens and variant_tokens:
            shared_tokens = search_tokens & variant_tokens
            if shared_tokens:
                score = max(score, len(shared_tokens) / max(1, len(search_tokens | variant_tokens)))
                if len(shared_tokens) >= min(len(search_tokens), len(variant_tokens), 2):
                    score = max(score, 0.88)
        best_score = max(best_score, score)
    return best_score


def _iter_reference_choice_matches(
    choices: list[_ReferenceChoice], normalized_text: str
) -> _ReferenceChoice | None:
    for choice in choices:
        display_text = _reference_choice_display_text(choice)
        if normalized_text in {
            _normalize_reference_text(choice.label),
            _normalize_reference_text(display_text),
        }:
            return choice
    return None


class _OptionalReferenceSelector(QWidget):
    valueChanged = Signal()

    def __init__(self, *, placeholder: str, clear_button_text: str = "Clear", parent=None):
        super().__init__(parent)
        self._choices: list[_ReferenceChoice] = []
        self._choices_by_id: dict[int, _ReferenceChoice] = {}
        self._suspend_signals = False

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        self.combo = FocusWheelComboBox(self)
        self.combo.setEditable(True)
        self.combo.setInsertPolicy(QComboBox.NoInsert)
        self.combo.addItem("", None)
        self.combo.setCurrentIndex(0)
        self.combo.setMinimumWidth(220)
        self.combo.setPlaceholderText(placeholder)
        self.combo.currentIndexChanged.connect(self._emit_value_changed)
        self.combo.currentTextChanged.connect(self._emit_value_changed)
        root.addWidget(self.combo, 1)

        self.clear_button = QPushButton(clear_button_text, self)
        self.clear_button.clicked.connect(self.clear)
        root.addWidget(self.clear_button)

    def set_choices(self, choices: list[_ReferenceChoice]) -> None:
        current_value = self.value_id()
        self._choices = list(choices)
        self._choices_by_id = {choice.reference_id: choice for choice in self._choices}
        self._rebuild_combo(current_value)

    def set_value_id(self, reference_id: int | None) -> None:
        self._rebuild_combo(int(reference_id) if reference_id is not None else None)

    def value_id(self) -> int | None:
        current_index = self.combo.currentIndex()
        data = self.combo.currentData()
        if current_index > 0 and data not in (None, ""):
            if _normalize_reference_text(self.combo.currentText()) == _normalize_reference_text(
                self.combo.itemText(current_index)
            ):
                return int(data)
        resolved = self._resolve_choice(self.combo.currentText())
        return resolved.reference_id if resolved is not None else None

    def clear(self) -> None:
        self._suspend_signals = True
        try:
            self.combo.setCurrentIndex(0)
            self.combo.setEditText("")
        finally:
            self._suspend_signals = False
        self.valueChanged.emit()

    def _resolve_choice(self, text: str | None) -> _ReferenceChoice | None:
        clean = str(text or "").strip()
        if not clean:
            return None
        extracted_id = _extract_reference_id(clean)
        if extracted_id is not None:
            return self._choices_by_id.get(extracted_id) or _unknown_reference_choice(extracted_id)
        normalized_text = _normalize_reference_text(clean)
        return _iter_reference_choice_matches(self._choices, normalized_text)

    def _rebuild_combo(self, selected_id: int | None) -> None:
        selected_choice = None
        if selected_id is not None:
            selected_choice = self._choices_by_id.get(selected_id) or _unknown_reference_choice(
                selected_id
            )
        self._suspend_signals = True
        try:
            self.combo.clear()
            self.combo.addItem("", None)
            display_values: list[str] = []
            for choice in self._choices:
                display_text = _reference_choice_display_text(choice)
                self.combo.addItem(display_text, choice.reference_id)
                display_values.append(display_text)
            if (
                selected_choice is not None
                and selected_choice.reference_id not in self._choices_by_id
            ):
                display_text = _reference_choice_display_text(selected_choice)
                self.combo.addItem(display_text, selected_choice.reference_id)
                display_values.append(display_text)
            _build_reference_completer(self.combo, display_values)
            if selected_choice is None:
                self.combo.setCurrentIndex(0)
                self.combo.setEditText("")
                return
            for index in range(self.combo.count()):
                if self.combo.itemData(index) == selected_choice.reference_id:
                    self.combo.setCurrentIndex(index)
                    return
            self.combo.setCurrentIndex(0)
            self.combo.setEditText(_reference_choice_display_text(selected_choice))
        finally:
            self._suspend_signals = False

    def _emit_value_changed(self, *_args) -> None:
        if self._suspend_signals:
            return
        self.valueChanged.emit()


class _ReferenceListEditor(QWidget):
    valueChanged = Signal()

    def __init__(self, *, placeholder: str, parent=None):
        super().__init__(parent)
        self._choices: list[_ReferenceChoice] = []
        self._choices_by_id: dict[int, _ReferenceChoice] = {}
        self._entries: list[_ReferenceChoice] = []
        self._suspend_signals = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(8)
        self.combo = FocusWheelComboBox(self)
        self.combo.setEditable(True)
        self.combo.setInsertPolicy(QComboBox.NoInsert)
        self.combo.addItem("", None)
        self.combo.setMinimumWidth(240)
        self.combo.setPlaceholderText(placeholder)
        self.combo.activated.connect(lambda *_args: self.add_current_reference())
        controls.addWidget(self.combo, 1)

        self.add_button = QPushButton("Add", self)
        self.add_button.clicked.connect(self.add_current_reference)
        controls.addWidget(self.add_button)
        root.addLayout(controls)

        table_actions = QHBoxLayout()
        table_actions.setContentsMargins(0, 0, 0, 0)
        table_actions.setSpacing(8)
        table_actions.addStretch(1)
        self.remove_button = QPushButton("Remove Highlighted", self)
        self.remove_button.clicked.connect(self.remove_selected_references)
        table_actions.addWidget(self.remove_button)
        root.addLayout(table_actions)

        self.table = QTableWidget(0, 2, self)
        self.table.setHorizontalHeaderLabels(["ID", "Reference"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setMinimumHeight(104)
        root.addWidget(self.table, 1)

    def set_choices(self, choices: list[_ReferenceChoice]) -> None:
        self._choices = list(choices)
        self._choices_by_id = {choice.reference_id: choice for choice in self._choices}
        self._entries = [
            self._choices_by_id.get(entry.reference_id) or entry for entry in self._entries
        ]
        self._refresh_combo()
        self._refresh_table()

    def set_value_ids(self, reference_ids: list[int]) -> None:
        seen: set[int] = set()
        entries: list[_ReferenceChoice] = []
        for raw_id in reference_ids:
            try:
                reference_id = int(raw_id)
            except Exception:
                continue
            if reference_id <= 0 or reference_id in seen:
                continue
            seen.add(reference_id)
            entries.append(
                self._choices_by_id.get(reference_id) or _unknown_reference_choice(reference_id)
            )
        self._suspend_signals = True
        try:
            self._entries = entries
            self._refresh_table()
        finally:
            self._suspend_signals = False

    def value_ids(self) -> list[int]:
        return [int(entry.reference_id) for entry in self._entries]

    def add_current_reference(self) -> None:
        choice = self._resolve_choice(self.combo.currentText())
        if choice is None:
            return
        if any(entry.reference_id == choice.reference_id for entry in self._entries):
            return
        self._entries.append(choice)
        self._refresh_table()
        self.combo.setCurrentIndex(0)
        self.combo.setEditText("")
        self.valueChanged.emit()

    def remove_selected_references(self) -> None:
        rows = sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True)
        if not rows:
            return
        for row in rows:
            if 0 <= row < len(self._entries):
                del self._entries[row]
        self._refresh_table()
        self.valueChanged.emit()

    def _resolve_choice(self, text: str | None) -> _ReferenceChoice | None:
        clean = str(text or "").strip()
        if not clean:
            return None
        current_index = self.combo.currentIndex()
        if current_index > 0 and _normalize_reference_text(clean) == _normalize_reference_text(
            self.combo.itemText(current_index)
        ):
            data = self.combo.currentData()
            if data not in (None, ""):
                return self._choices_by_id.get(int(data))
        extracted_id = _extract_reference_id(clean)
        if extracted_id is not None:
            return self._choices_by_id.get(extracted_id) or _unknown_reference_choice(extracted_id)
        normalized_text = _normalize_reference_text(clean)
        return _iter_reference_choice_matches(self._choices, normalized_text)

    def _refresh_combo(self) -> None:
        self.combo.clear()
        self.combo.addItem("", None)
        display_values: list[str] = []
        for choice in self._choices:
            display_text = _reference_choice_display_text(choice)
            self.combo.addItem(display_text, choice.reference_id)
            display_values.append(display_text)
        _build_reference_completer(self.combo, display_values)

    def _refresh_table(self) -> None:
        self.table.setRowCount(len(self._entries))
        for row, choice in enumerate(self._entries):
            id_item = QTableWidgetItem(str(choice.reference_id))
            id_item.setTextAlignment(Qt.AlignCenter)
            label_item = QTableWidgetItem(choice.label or f"Record #{choice.reference_id}")
            self.table.setItem(row, 0, id_item)
            self.table.setItem(row, 1, label_item)


class _ContractPartyEditor(QWidget):
    valueChanged = Signal()

    def __init__(self, *, placeholder: str, parent=None):
        super().__init__(parent)
        self._choices: list[_ReferenceChoice] = []
        self._choices_by_id: dict[int, _ReferenceChoice] = {}
        self._entries: list[ContractPartyPayload] = []
        self._suspend_updates = False
        self._auto_revealed_row: int | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(8)
        self.party_combo = FocusWheelComboBox(self)
        self.party_combo.setEditable(True)
        self.party_combo.setInsertPolicy(QComboBox.NoInsert)
        self.party_combo.addItem("", None)
        self.party_combo.setMinimumWidth(220)
        self.party_combo.setPlaceholderText(placeholder)
        top_row.addWidget(self.party_combo, 1)

        self.role_edit = QLineEdit(self)
        self.role_edit.setPlaceholderText("Role (e.g. licensee, label)")
        self.role_edit.setMinimumWidth(140)
        _build_text_completer(self.role_edit, list(_CONTRACT_PARTY_ROLE_PRESETS))
        top_row.addWidget(self.role_edit)

        self.primary_checkbox = QCheckBox("Primary", self)
        top_row.addWidget(self.primary_checkbox)

        self.add_button = QPushButton("Add Party", self)
        self.add_button.clicked.connect(self.add_current_party)
        top_row.addWidget(self.add_button)
        root.addLayout(top_row)

        bottom_row = QHBoxLayout()
        bottom_row.setContentsMargins(0, 0, 0, 0)
        bottom_row.setSpacing(8)
        self.notes_edit = QLineEdit(self)
        self.notes_edit.setPlaceholderText("Notes (optional)")
        bottom_row.addWidget(self.notes_edit, 1)

        self.remove_button = QPushButton("Remove Highlighted", self)
        self.remove_button.clicked.connect(self.remove_selected_parties)
        bottom_row.addWidget(self.remove_button)
        root.addLayout(bottom_row)

        self.editor_hint_label = QLabel(self)
        self.editor_hint_label.setProperty("role", "supportingText")
        self.editor_hint_label.setWordWrap(True)
        root.addWidget(self.editor_hint_label)

        self.table = QTableWidget(0, 5, self)
        self.table.setHorizontalHeaderLabels(["ID", "Party", "Role", "Primary", "Notes"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.setMinimumHeight(140)
        self.table.itemSelectionChanged.connect(self._load_selected_party_into_controls)
        root.addWidget(self.table, 1)

        self.party_combo.currentTextChanged.connect(self._refresh_editor_state)
        self.role_edit.textChanged.connect(self._refresh_editor_state)
        self.primary_checkbox.stateChanged.connect(self._refresh_editor_state)
        self.notes_edit.textChanged.connect(self._refresh_editor_state)
        self._refresh_editor_state()

    def set_choices(self, choices: list[_ReferenceChoice]) -> None:
        self._choices = list(choices)
        self._choices_by_id = {choice.reference_id: choice for choice in self._choices}
        self._refresh_combo()
        self._refresh_table()
        self._refresh_editor_state()

    def set_value(self, parties: list[object]) -> None:
        entries: list[ContractPartyPayload] = []
        for item in parties:
            party_id = getattr(item, "party_id", None)
            name = getattr(item, "name", None)
            if not name:
                name = getattr(item, "party_name", None)
            entries.append(
                ContractPartyPayload(
                    party_id=int(party_id) if party_id not in (None, "") else None,
                    name=str(name or "").strip() or None,
                    role_label=str(getattr(item, "role_label", "") or "").strip() or "counterparty",
                    is_primary=bool(getattr(item, "is_primary", False)),
                    notes=str(getattr(item, "notes", "") or "").strip() or None,
                )
            )
        self._entries = entries
        self._refresh_table()
        self._refresh_editor_state()

    def value(self) -> list[ContractPartyPayload]:
        return [
            ContractPartyPayload(
                party_id=entry.party_id,
                name=entry.name,
                role_label=entry.role_label,
                is_primary=entry.is_primary,
                notes=entry.notes,
            )
            for entry in self._entries
        ]

    def setPlainText(self, text: str) -> None:
        entries: list[ContractPartyPayload] = []
        for line in str(text or "").splitlines():
            parts = [part.strip() for part in line.split("|")]
            if not parts or not parts[0]:
                continue
            party_id = int(parts[0]) if parts[0].isdigit() else None
            entries.append(
                ContractPartyPayload(
                    party_id=party_id,
                    name=None if party_id is not None else parts[0],
                    role_label=parts[1] if len(parts) > 1 and parts[1] else "counterparty",
                    is_primary=_parse_bool_token(parts[2]) if len(parts) > 2 else False,
                    notes=parts[3] if len(parts) > 3 and parts[3] else None,
                )
            )
        self._entries = entries
        self._refresh_table()
        self._refresh_editor_state()

    def toPlainText(self) -> str:
        lines: list[str] = []
        for entry in self._entries:
            identity = str(entry.party_id) if entry.party_id is not None else str(entry.name or "")
            if not identity.strip():
                continue
            parts = [
                identity,
                str(entry.role_label or "counterparty"),
                "1" if entry.is_primary else "0",
            ]
            if entry.notes:
                parts.append(str(entry.notes))
            lines.append("|".join(parts))
        return "\n".join(lines)

    def add_current_party(self) -> None:
        entry = self._draft_entry()
        if entry is None:
            return
        replace_index = self._matching_entry_index(entry)
        if replace_index is None:
            self._entries.append(entry)
        else:
            self._entries[replace_index] = entry
        self._refresh_table()
        self.table.clearSelection()
        self._clear_editor_controls()
        self.valueChanged.emit()

    def remove_selected_parties(self) -> None:
        rows = sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True)
        if not rows:
            return
        for row in rows:
            if 0 <= row < len(self._entries):
                del self._entries[row]
        self._refresh_table()
        self._clear_editor_controls()
        self.valueChanged.emit()

    def _matching_entry_index(self, entry: ContractPartyPayload) -> int | None:
        for index, current in enumerate(self._entries):
            if entry.party_id is not None and current.party_id == entry.party_id:
                return index
            if entry.party_id is None and current.party_id is None:
                if _normalize_reference_text(current.name) == _normalize_reference_text(entry.name):
                    return index
        return None

    def _refresh_combo(self) -> None:
        self.party_combo.clear()
        self.party_combo.addItem("", None)
        display_values: list[str] = []
        for choice in self._choices:
            display_text = _reference_choice_display_text(choice)
            self.party_combo.addItem(display_text, choice.reference_id)
            display_values.append(display_text)
        _build_reference_completer(self.party_combo, display_values)

    def _display_label(self, entry: ContractPartyPayload) -> str:
        if entry.party_id is not None:
            choice = self._choices_by_id.get(int(entry.party_id))
            if choice is not None:
                label = str(choice.label or "").strip()
                primary_label = _primary_reference_label(label)
                return primary_label or label or f"Party #{int(entry.party_id)}"
            if entry.name:
                return entry.name
            return f"Unknown #{int(entry.party_id)}"
        return str(entry.name or "").strip()

    def _refresh_table(self) -> None:
        self.table.setRowCount(len(self._entries))
        for row, entry in enumerate(self._entries):
            id_item = QTableWidgetItem(str(entry.party_id or ""))
            id_item.setTextAlignment(Qt.AlignCenter)
            party_item = QTableWidgetItem(self._display_label(entry))
            role_item = QTableWidgetItem(str(entry.role_label or "counterparty"))
            primary_item = QTableWidgetItem("Yes" if entry.is_primary else "No")
            notes_item = QTableWidgetItem(str(entry.notes or ""))
            self.table.setItem(row, 0, id_item)
            self.table.setItem(row, 1, party_item)
            self.table.setItem(row, 2, role_item)
            self.table.setItem(row, 3, primary_item)
            self.table.setItem(row, 4, notes_item)

    def _resolve_party_selection(self) -> tuple[int | None, str | None] | None:
        clean = str(self.party_combo.currentText() or "").strip()
        if not clean:
            return None
        current_index = self.party_combo.currentIndex()
        if current_index > 0 and _normalize_reference_text(clean) == _normalize_reference_text(
            self.party_combo.itemText(current_index)
        ):
            data = self.party_combo.currentData()
            if data not in (None, ""):
                return int(data), None
        extracted_id = _extract_reference_id(clean)
        if extracted_id is not None:
            choice = self._choices_by_id.get(extracted_id)
            return extracted_id, None if choice is not None else None
        normalized_text = _normalize_reference_text(clean)
        for choice in self._choices:
            if normalized_text in {
                _normalize_reference_text(variant) for variant in _reference_choice_variants(choice)
            }:
                return choice.reference_id, None
        matched = _iter_reference_choice_matches(self._choices, normalized_text)
        if matched is not None:
            return matched.reference_id, None
        return None, clean

    def _near_duplicate_choices(
        self, text: str | None, *, limit: int = 2
    ) -> list[_ReferenceChoice]:
        normalized_text = _normalize_reference_text(text)
        if len(normalized_text) < 4:
            return []
        matches: list[tuple[float, _ReferenceChoice]] = []
        for choice in self._choices:
            score = _reference_choice_similarity(text, choice)
            if score < 0.74:
                continue
            matches.append((score, choice))
        matches.sort(
            key=lambda item: (
                -item[0],
                _normalize_reference_text(_primary_reference_label(item[1].label)),
            )
        )
        return [choice for _score, choice in matches[: max(1, int(limit or 1))]]

    def _linked_entry_for_party_id(self, party_id: int | None) -> ContractPartyPayload | None:
        if party_id is None:
            return None
        for entry in self._entries:
            if entry.party_id == int(party_id):
                return entry
        return None

    def _linked_entry_row(self, party_id: int | None) -> int | None:
        if party_id is None:
            return None
        for index, entry in enumerate(self._entries):
            if entry.party_id == int(party_id):
                return index
        return None

    def _suggestion_label(self, choice: _ReferenceChoice) -> str:
        label = _primary_reference_label(choice.label) or f"Party #{choice.reference_id}"
        linked_entry = self._linked_entry_for_party_id(choice.reference_id)
        if linked_entry is None:
            return label
        role_label = str(linked_entry.role_label or "").strip()
        if role_label:
            return f"{label} (already linked as {role_label})"
        return f"{label} (already linked)"

    def _reveal_row(self, row: int | None) -> None:
        selection_model = self.table.selectionModel()
        target_row = int(row) if row is not None else None
        if target_row is None or target_row < 0 or target_row >= self.table.rowCount():
            if (
                self._auto_revealed_row is not None
                and selection_model is not None
                and selection_model.hasSelection()
            ):
                selected_rows = selection_model.selectedRows()
                if len(selected_rows) == 1 and selected_rows[0].row() == self._auto_revealed_row:
                    self._suspend_updates = True
                    try:
                        self.table.clearSelection()
                    finally:
                        self._suspend_updates = False
            self._auto_revealed_row = None
            return
        if (
            selection_model is not None
            and selection_model.hasSelection()
            and len(selection_model.selectedRows()) == 1
            and selection_model.selectedRows()[0].row() == target_row
        ):
            self._auto_revealed_row = target_row
            item = self.table.item(target_row, 0) or self.table.item(target_row, 1)
            if item is not None:
                self.table.scrollToItem(item, QAbstractItemView.PositionAtCenter)
            return
        self._suspend_updates = True
        try:
            self.table.selectRow(target_row)
            item = self.table.item(target_row, 0) or self.table.item(target_row, 1)
            if item is not None:
                self.table.scrollToItem(item, QAbstractItemView.PositionAtCenter)
        finally:
            self._suspend_updates = False
        self._auto_revealed_row = target_row

    def _draft_entry(self) -> ContractPartyPayload | None:
        resolved = self._resolve_party_selection()
        if resolved is None:
            return None
        party_id, party_name = resolved
        return ContractPartyPayload(
            party_id=party_id,
            name=party_name,
            role_label=self.role_edit.text().strip() or "counterparty",
            is_primary=self.primary_checkbox.isChecked(),
            notes=self.notes_edit.text().strip() or None,
        )

    def _clear_editor_controls(self) -> None:
        self.party_combo.setCurrentIndex(0)
        self.party_combo.setEditText("")
        self.role_edit.clear()
        self.primary_checkbox.setChecked(False)
        self.notes_edit.clear()
        self._refresh_editor_state()

    def _entries_match(self, left: ContractPartyPayload, right: ContractPartyPayload) -> bool:
        return (
            left.party_id == right.party_id
            and _normalize_reference_text(left.name) == _normalize_reference_text(right.name)
            and _normalize_reference_text(left.role_label)
            == _normalize_reference_text(right.role_label)
            and bool(left.is_primary) == bool(right.is_primary)
            and _normalize_reference_text(left.notes) == _normalize_reference_text(right.notes)
        )

    def _refresh_editor_state(self) -> None:
        if self._suspend_updates:
            return
        draft = self._draft_entry()
        if draft is None:
            self._reveal_row(None)
            self.add_button.setEnabled(False)
            self.add_button.setText("Add Party")
            self.add_button.setToolTip("Choose an existing party or type a new party name.")
            self.editor_hint_label.setText(
                "Choose an existing party or type a new counterparty name."
            )
            return
        match_index = self._matching_entry_index(draft)
        if match_index is None:
            self.add_button.setEnabled(True)
            self.add_button.setText("Add Party")
            self.add_button.setToolTip("Add this party to the linked parties table.")
            if draft.party_id is None and draft.name:
                suggestions = self._near_duplicate_choices(draft.name)
                if suggestions:
                    linked_suggestion = next(
                        (
                            choice
                            for choice in suggestions
                            if self._linked_entry_for_party_id(choice.reference_id) is not None
                        ),
                        None,
                    )
                    self._reveal_row(
                        None
                        if linked_suggestion is None
                        else self._linked_entry_row(linked_suggestion.reference_id)
                    )
                    suggestion_labels = ", ".join(
                        self._suggestion_label(choice) for choice in suggestions
                    )
                    hint_suffix = (
                        "Select an existing record first if this is the same counterparty."
                    )
                    if linked_suggestion is not None:
                        hint_suffix = "The linked row is highlighted below so you can update it instead of adding a shadow entry."
                    self.editor_hint_label.setText(
                        f"Possible existing part{'y' if len(suggestions) == 1 else 'ies'}: {suggestion_labels}. {hint_suffix}"
                    )
                    if linked_suggestion is not None:
                        self.add_button.setToolTip(
                            "Add a new party entry, or select the already linked suggested record if you meant to update the current contract row."
                        )
                    else:
                        self.add_button.setToolTip(
                            "Add a new party entry, or select the suggested existing record if it is the same counterparty."
                        )
                else:
                    self._reveal_row(None)
                    self.editor_hint_label.setText(
                        "This typed party name will be created when the contract is saved."
                    )
            else:
                self._reveal_row(None)
                self.editor_hint_label.setText(
                    "This party will be added to the linked parties table."
                )
            return
        current = self._entries[match_index]
        self._reveal_row(match_index)
        self.add_button.setEnabled(True)
        self.add_button.setText("Update Existing")
        self.add_button.setToolTip("Update the existing linked party entry.")
        if self._entries_match(current, draft):
            self.editor_hint_label.setText(
                f"{self._display_label(current)} is already linked with the same values. The linked row is highlighted below."
            )
        else:
            self.editor_hint_label.setText(
                f"{self._display_label(current)} is already linked. The linked row is highlighted below, and Add / Update will refresh its role, primary flag, or notes."
            )

    def _load_selected_party_into_controls(self) -> None:
        if self._suspend_updates:
            return
        selection_model = self.table.selectionModel()
        if selection_model is None:
            return
        rows = selection_model.selectedRows()
        if len(rows) != 1:
            return
        row = rows[0].row()
        if row < 0 or row >= len(self._entries):
            return
        entry = self._entries[row]
        self._suspend_updates = True
        try:
            if entry.party_id is not None and entry.party_id in self._choices_by_id:
                for index in range(self.party_combo.count()):
                    if self.party_combo.itemData(index) == entry.party_id:
                        self.party_combo.setCurrentIndex(index)
                        break
            else:
                self.party_combo.setCurrentIndex(0)
                self.party_combo.setEditText(
                    str(entry.name or (entry.party_id if entry.party_id is not None else ""))
                )
            self.role_edit.setText(str(entry.role_label or "counterparty"))
            self.primary_checkbox.setChecked(bool(entry.is_primary))
            self.notes_edit.setText(str(entry.notes or ""))
        finally:
            self._suspend_updates = False
        self._refresh_editor_state()


class ContractDocumentEditor(QWidget):
    """Structured editor for contract documents and storage metadata."""

    def __init__(self, *, contract_service: ContractService, parent=None):
        super().__init__(parent)
        self.contract_service = contract_service
        self._documents: list[ContractDocumentPayload] = []
        self._current_row: int = -1
        self._suspend_updates = False
        self._preview_dir = tempfile.TemporaryDirectory(prefix="isrc_contract_documents_")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        self.add_file_button = QPushButton("Add File…")
        self.add_file_button.clicked.connect(self._append_document_file)
        self.open_button = QPushButton("Open Selected")
        self.open_button.clicked.connect(self.open_selected_document)
        self.export_button = QPushButton("Export Selected…")
        self.export_button.clicked.connect(self._export_selected_document)
        self.database_button = QPushButton("Store as Database")
        self.database_button.clicked.connect(
            lambda: self._set_selected_storage_mode(STORAGE_MODE_DATABASE)
        )
        self.managed_button = QPushButton("Store as Managed File")
        self.managed_button.clicked.connect(
            lambda: self._set_selected_storage_mode(STORAGE_MODE_MANAGED_FILE)
        )
        self.remove_button = QPushButton("Remove Selected")
        self.remove_button.clicked.connect(self._remove_selected_document)
        self.actions_cluster = _create_action_button_cluster(
            self,
            [
                self.add_file_button,
                self.open_button,
                self.export_button,
                self.database_button,
                self.managed_button,
                self.remove_button,
            ],
            columns=2,
            min_button_width=170,
        )
        self.actions_cluster.setObjectName("contractDocumentActionsCluster")
        root.addWidget(self.actions_cluster)

        splitter = QSplitter(Qt.Horizontal, self)
        splitter.setObjectName("contractDocumentEditorSplitter")
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, 1)

        table_box = QGroupBox("Documents", self)
        table_layout = QVBoxLayout(table_box)
        table_layout.setContentsMargins(12, 16, 12, 12)
        table_layout.setSpacing(8)
        self.documents_table = QTableWidget(0, 9, table_box)
        self.documents_table.setHorizontalHeaderLabels(
            [
                "ID",
                "Title",
                "Type",
                "Version",
                "Storage",
                "Active",
                "Signed",
                "Filename",
                "Checksum",
            ]
        )
        self.documents_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.documents_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.documents_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.documents_table.verticalHeader().setVisible(False)
        header = self.documents_table.horizontalHeader()
        header.setMinimumSectionSize(36)
        for column, width in (
            (0, 68),
            (2, 112),
            (3, 88),
            (4, 94),
            (5, 68),
            (6, 68),
        ):
            header.setSectionResizeMode(column, QHeaderView.Interactive)
            header.resizeSection(column, width)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(7, QHeaderView.Stretch)
        header.setSectionResizeMode(8, QHeaderView.Stretch)
        self.documents_table.itemSelectionChanged.connect(self._on_selection_changed)
        table_layout.addWidget(self.documents_table, 1)
        splitter.addWidget(table_box)

        detail_panel = QWidget(splitter)
        detail_panel.setMinimumWidth(340)
        detail_panel_layout = QVBoxLayout(detail_panel)
        detail_panel_layout.setContentsMargins(0, 0, 0, 0)
        detail_panel_layout.setSpacing(0)
        self.detail_scroll_area, _, detail_content_layout = _create_scrollable_dialog_content(
            detail_panel
        )
        self.detail_scroll_area.setObjectName("contractDocumentDetailScrollArea")
        detail_panel_layout.addWidget(self.detail_scroll_area, 1)
        detail_content_layout.setSpacing(10)

        detail_intro = QLabel(
            "Edit the selected document metadata here without losing its storage or integrity history."
        )
        detail_intro.setWordWrap(True)
        detail_content_layout.addWidget(detail_intro)

        identity_box, identity_layout = _create_standard_section(
            self,
            "Document Identity",
            "Core metadata for the selected contract file.",
        )
        identity_form = QFormLayout()
        _configure_standard_form_layout(identity_form)
        self.document_id_label = QLabel("")
        self.filename_label = QLabel("")
        self.filename_label.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard
        )
        self.checksum_label = QLabel("")
        self.checksum_label.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard
        )
        self.source_path_label = QLabel("")
        self.source_path_label.setWordWrap(True)
        self.source_path_label.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard
        )

        self.title_edit = QLineEdit()
        self.document_type_combo = QComboBox()
        self.document_type_combo.addItems(
            [value.replace("_", " ").title() for value in DOCUMENT_TYPE_CHOICES]
        )
        self.version_edit = QLineEdit()
        self.created_edit = QLineEdit()
        self.received_edit = QLineEdit()
        self.signed_status_edit = QLineEdit()

        for widget in (self.created_edit, self.received_edit):
            widget.setPlaceholderText("YYYY-MM-DD")

        identity_form.addRow("Document ID", self.document_id_label)
        identity_form.addRow("Title", self.title_edit)
        identity_form.addRow("Document Type", self.document_type_combo)
        identity_form.addRow("Version Label", self.version_edit)
        identity_form.addRow("Created Date", self.created_edit)
        identity_form.addRow("Received Date", self.received_edit)
        identity_form.addRow("Signed Status", self.signed_status_edit)
        identity_layout.addLayout(identity_form)
        detail_content_layout.addWidget(identity_box)

        lifecycle_box, lifecycle_layout = _create_standard_section(
            self,
            "Status and Relationships",
            "Track signature state, active status, and linked version history.",
        )
        lifecycle_form = QFormLayout()
        _configure_standard_form_layout(lifecycle_form)
        self.signed_all_checkbox = QCheckBox("Signed by all parties")
        self.active_checkbox = QCheckBox("Active")
        self.supersedes_edit = _OptionalReferenceSelector(
            placeholder="Select a saved document or type an ID",
            parent=self,
        )
        self.superseded_by_edit = _OptionalReferenceSelector(
            placeholder="Select a saved document or type an ID",
            parent=self,
        )
        lifecycle_form.addRow("Signed By All", self.signed_all_checkbox)
        lifecycle_form.addRow("Active", self.active_checkbox)
        lifecycle_form.addRow("Supersedes Document", self.supersedes_edit)
        lifecycle_form.addRow("Superseded By Document", self.superseded_by_edit)
        lifecycle_layout.addLayout(lifecycle_form)
        detail_content_layout.addWidget(lifecycle_box)

        storage_box, storage_layout = _create_standard_section(
            self,
            "Storage and Integrity",
            "Switch storage modes without losing the known filename, path, or checksum.",
        )
        storage_form = QFormLayout()
        _configure_standard_form_layout(storage_form)
        self.storage_mode_combo = QComboBox()
        self.storage_mode_combo.addItem("Managed File", STORAGE_MODE_MANAGED_FILE)
        self.storage_mode_combo.addItem("Stored in Database", STORAGE_MODE_DATABASE)
        storage_form.addRow("Storage Mode", self.storage_mode_combo)
        storage_form.addRow("Filename", self.filename_label)
        storage_form.addRow("Stored Path / Blob", self.source_path_label)
        storage_form.addRow("Checksum", self.checksum_label)
        storage_layout.addLayout(storage_form)

        detail_actions = QHBoxLayout()
        detail_actions.setContentsMargins(0, 0, 0, 0)
        detail_actions.setSpacing(8)
        self.switch_mode_button = QPushButton("Switch Storage Mode")
        self.switch_mode_button.clicked.connect(self._toggle_selected_storage_mode)
        detail_actions.addWidget(self.switch_mode_button)
        storage_layout.addLayout(detail_actions)
        detail_content_layout.addWidget(storage_box)

        notes_box, notes_layout = _create_standard_section(
            self,
            "Notes",
            "Capture signing context, delivery notes, or other version-specific detail.",
        )
        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setMinimumHeight(72)
        notes_layout.addWidget(self.notes_edit)
        detail_content_layout.addWidget(notes_box)
        detail_content_layout.addStretch(1)

        splitter.addWidget(detail_panel)
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 4)
        splitter.setSizes([520, 470])

        for widget in (
            self.title_edit,
            self.document_type_combo,
            self.version_edit,
            self.created_edit,
            self.received_edit,
            self.signed_status_edit,
            self.signed_all_checkbox,
            self.active_checkbox,
            self.supersedes_edit,
            self.superseded_by_edit,
            self.storage_mode_combo,
            self.notes_edit,
        ):
            self._connect_document_widget(widget)

        self._refresh_action_state()

    def closeEvent(self, event) -> None:  # pragma: no cover - Qt lifecycle hook
        self.cleanup()
        super().closeEvent(event)

    def cleanup(self) -> None:
        preview_dir = getattr(self, "_preview_dir", None)
        if preview_dir is None:
            return
        try:
            preview_dir.cleanup()
        except Exception:
            pass
        self._preview_dir = None

    def _connect_document_widget(self, widget) -> None:
        if isinstance(widget, QLineEdit):
            widget.textChanged.connect(self._sync_current_document_from_form)
        elif isinstance(widget, QPlainTextEdit):
            widget.textChanged.connect(self._sync_current_document_from_form)
        elif isinstance(widget, QComboBox):
            widget.currentTextChanged.connect(self._sync_current_document_from_form)
        elif isinstance(widget, QCheckBox):
            widget.stateChanged.connect(self._sync_current_document_from_form)
        elif hasattr(widget, "valueChanged"):
            widget.valueChanged.connect(self._sync_current_document_from_form)

    def _payload_from_record(self, record: ContractDocumentRecord) -> ContractDocumentPayload:
        return ContractDocumentPayload(
            document_id=record.id,
            title=record.title,
            document_type=record.document_type,
            version_label=record.version_label,
            created_date=record.created_date,
            received_date=record.received_date,
            signed_status=record.signed_status,
            signed_by_all_parties=record.signed_by_all_parties,
            active_flag=record.active_flag,
            supersedes_document_id=record.supersedes_document_id,
            superseded_by_document_id=record.superseded_by_document_id,
            stored_path=record.file_path,
            storage_mode=record.storage_mode,
            filename=record.filename,
            checksum_sha256=record.checksum_sha256,
            notes=record.notes,
        )

    def load_documents(self, documents: list[ContractDocumentRecord]) -> None:
        self._suspend_updates = True
        try:
            self._documents = [self._payload_from_record(document) for document in documents]
            self.documents_table.blockSignals(True)
            try:
                self.documents_table.setRowCount(0)
                for row, document in enumerate(self._documents):
                    self._insert_document_row(row, document)
            finally:
                self.documents_table.blockSignals(False)
            if self._documents:
                self.documents_table.selectRow(0)
                self._load_document_into_form(0)
            else:
                self._current_row = -1
                self._clear_form()
        finally:
            self._suspend_updates = False
        self._refresh_action_state()

    def documents(self) -> list[ContractDocumentPayload]:
        self._sync_current_document_from_form()
        return [
            ContractDocumentPayload(
                document_id=item.document_id,
                title=item.title,
                document_type=item.document_type,
                version_label=item.version_label,
                created_date=item.created_date,
                received_date=item.received_date,
                signed_status=item.signed_status,
                signed_by_all_parties=item.signed_by_all_parties,
                active_flag=item.active_flag,
                supersedes_document_id=item.supersedes_document_id,
                superseded_by_document_id=item.superseded_by_document_id,
                source_path=item.source_path,
                stored_path=item.stored_path,
                storage_mode=item.storage_mode,
                filename=item.filename,
                checksum_sha256=item.checksum_sha256,
                notes=item.notes,
            )
            for item in self._documents
        ]

    def _current_document(self) -> tuple[int, ContractDocumentPayload] | None:
        row = self._current_row
        if row < 0 or row >= len(self._documents):
            return None
        return row, self._documents[row]

    def _refresh_action_state(self) -> None:
        has_selection = self._current_document() is not None
        for button in (
            self.open_button,
            self.export_button,
            self.database_button,
            self.managed_button,
            self.remove_button,
            self.switch_mode_button,
        ):
            button.setEnabled(has_selection)
        if has_selection:
            _, document = self._current_document()
            assert document is not None
            current_mode = normalize_storage_mode(document.storage_mode, default=None)
            self.database_button.setEnabled(current_mode != STORAGE_MODE_DATABASE)
            self.managed_button.setEnabled(current_mode != STORAGE_MODE_MANAGED_FILE)
            self.switch_mode_button.setText(
                "Switch to Managed File"
                if current_mode == STORAGE_MODE_DATABASE
                else "Switch to Database"
            )
        else:
            self.switch_mode_button.setText("Switch Storage Mode")

    def _clear_form(self) -> None:
        self.document_id_label.setText("")
        self.title_edit.clear()
        self.document_type_combo.setCurrentIndex(0)
        self.version_edit.clear()
        self.created_edit.clear()
        self.received_edit.clear()
        self.signed_status_edit.clear()
        self.signed_all_checkbox.setChecked(False)
        self.active_checkbox.setChecked(False)
        self.supersedes_edit.clear()
        self.superseded_by_edit.clear()
        self.storage_mode_combo.setCurrentIndex(0)
        self.filename_label.setText("")
        self.source_path_label.setText("")
        self.checksum_label.setText("")
        self.notes_edit.clear()
        self._refresh_document_reference_selectors()

    def _insert_document_row(self, row: int, document: ContractDocumentPayload) -> None:
        if row >= self.documents_table.rowCount():
            self.documents_table.insertRow(row)
        values = [
            str(document.document_id or ""),
            document.title,
            (document.document_type or "other").replace("_", " ").title(),
            document.version_label or "",
            (
                normalize_storage_mode(document.storage_mode, default=None)
                or STORAGE_MODE_MANAGED_FILE
            )
            .replace("_", " ")
            .title(),
            "Yes" if document.active_flag else "No",
            "Yes" if document.signed_by_all_parties else "No",
            document.filename or "",
            document.checksum_sha256 or "",
        ]
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            if column == 0:
                item.setTextAlignment(Qt.AlignCenter)
            self.documents_table.setItem(row, column, item)

    def _update_document_row(self, row: int) -> None:
        if row < 0 or row >= len(self._documents):
            return
        document = self._documents[row]
        values = [
            str(document.document_id or ""),
            document.title,
            (document.document_type or "other").replace("_", " ").title(),
            document.version_label or "",
            (
                normalize_storage_mode(document.storage_mode, default=None)
                or STORAGE_MODE_MANAGED_FILE
            )
            .replace("_", " ")
            .title(),
            "Yes" if document.active_flag else "No",
            "Yes" if document.signed_by_all_parties else "No",
            document.filename or "",
            document.checksum_sha256 or "",
        ]
        for column, value in enumerate(values):
            item = self.documents_table.item(row, column)
            if item is None:
                item = QTableWidgetItem()
                self.documents_table.setItem(row, column, item)
            item.setText(value)

    def _load_document_into_form(self, row: int) -> None:
        if row < 0 or row >= len(self._documents):
            self._current_row = -1
            self._clear_form()
            self._refresh_action_state()
            return
        document = self._documents[row]
        self._current_row = row
        self._suspend_updates = True
        try:
            self.document_id_label.setText(str(document.document_id or ""))
            self.title_edit.setText(document.title or "")
            self.document_type_combo.setCurrentText(
                (document.document_type or "other").replace("_", " ").title()
            )
            self.version_edit.setText(document.version_label or "")
            self.created_edit.setText(document.created_date or "")
            self.received_edit.setText(document.received_date or "")
            self.signed_status_edit.setText(document.signed_status or "")
            self.signed_all_checkbox.setChecked(bool(document.signed_by_all_parties))
            self.active_checkbox.setChecked(bool(document.active_flag))
            self._refresh_document_reference_selectors()
            self.supersedes_edit.set_value_id(document.supersedes_document_id)
            self.superseded_by_edit.set_value_id(document.superseded_by_document_id)
            self.storage_mode_combo.setCurrentIndex(
                self.storage_mode_combo.findData(
                    normalize_storage_mode(document.storage_mode, default=STORAGE_MODE_MANAGED_FILE)
                )
            )
            self.filename_label.setText(document.filename or "")
            storage_mode = normalize_storage_mode(
                document.storage_mode, default=STORAGE_MODE_MANAGED_FILE
            )
            self.source_path_label.setText(
                document.stored_path
                or document.source_path
                or ("Stored in database" if storage_mode == STORAGE_MODE_DATABASE else "")
            )
            self.checksum_label.setText(document.checksum_sha256 or "")
            self.notes_edit.setPlainText(document.notes or "")
        finally:
            self._suspend_updates = False
        self._refresh_action_state()

    def _on_selection_changed(self) -> None:
        if self._suspend_updates:
            return
        self._sync_current_document_from_form()
        self._load_document_into_form(self.documents_table.currentRow())

    def _sync_current_document_from_form(self) -> None:
        if self._suspend_updates:
            return
        current = self._current_document()
        if current is None:
            return
        row, document = current
        document.title = self.title_edit.text().strip()
        document.document_type = (
            self.document_type_combo.currentText().strip().lower().replace(" ", "_") or "other"
        )
        document.version_label = self.version_edit.text().strip() or None
        document.created_date = self.created_edit.text().strip() or None
        document.received_date = self.received_edit.text().strip() or None
        document.signed_status = self.signed_status_edit.text().strip() or None
        document.signed_by_all_parties = self.signed_all_checkbox.isChecked()
        document.active_flag = self.active_checkbox.isChecked()
        document.supersedes_document_id = self.supersedes_edit.value_id()
        document.superseded_by_document_id = self.superseded_by_edit.value_id()
        document.storage_mode = normalize_storage_mode(
            self.storage_mode_combo.currentData(), default=STORAGE_MODE_MANAGED_FILE
        )
        document.notes = self.notes_edit.toPlainText().strip() or None
        self._documents[row] = document
        self._update_document_row(row)

    def _append_document_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select Contract Document", "")
        if not path:
            return
        resolved = Path(path)
        title = resolved.name
        payload = ContractDocumentPayload(
            title=title,
            document_type="signed_agreement",
            source_path=str(resolved),
            storage_mode=STORAGE_MODE_MANAGED_FILE,
            filename=resolved.name,
        )
        self._documents.append(payload)
        row = len(self._documents) - 1
        self._insert_document_row(row, payload)
        self.documents_table.selectRow(row)
        self._load_document_into_form(row)

    def _remove_selected_document(self) -> None:
        current = self._current_document()
        if current is None:
            return
        row, _ = current
        self.documents_table.removeRow(row)
        del self._documents[row]
        if self._documents:
            next_row = min(row, len(self._documents) - 1)
            self.documents_table.selectRow(next_row)
            self._load_document_into_form(next_row)
        else:
            self._current_row = -1
            self._clear_form()
        self._refresh_action_state()

    def _document_reference_choices(
        self, *, exclude_row: int | None = None
    ) -> list[_ReferenceChoice]:
        choices: list[_ReferenceChoice] = []
        for row, document in enumerate(self._documents):
            if exclude_row is not None and row == exclude_row:
                continue
            if document.document_id is None:
                continue
            label_parts = [str(document.title or "").strip()]
            if document.version_label:
                label_parts.append(f"Version: {document.version_label}")
            if document.filename:
                label_parts.append(document.filename)
            label = (
                " / ".join(part for part in label_parts if part)
                or f"Document #{document.document_id}"
            )
            choices.append(_ReferenceChoice(int(document.document_id), label))
        return choices

    def _refresh_document_reference_selectors(self) -> None:
        current_row = self._current_row if self._current_row >= 0 else None
        choices = self._document_reference_choices(exclude_row=current_row)
        selected_supersedes = None
        selected_superseded_by = None
        if current_row is not None and current_row < len(self._documents):
            current = self._documents[current_row]
            selected_supersedes = current.supersedes_document_id
            selected_superseded_by = current.superseded_by_document_id
        self.supersedes_edit.set_choices(choices)
        self.superseded_by_edit.set_choices(choices)
        if current_row is None:
            return
        self.supersedes_edit.set_value_id(selected_supersedes)
        self.superseded_by_edit.set_value_id(selected_superseded_by)

    def _document_bytes(self, document: ContractDocumentPayload) -> tuple[bytes, str]:
        if document.document_id is not None:
            data, mime_type = self.contract_service.fetch_document_bytes(int(document.document_id))
            filename = document.filename or ""
            if not filename:
                filename = Path(
                    document.stored_path or document.source_path or "contract-document"
                ).name
            return data, filename
        source_path = str(document.source_path or "").strip()
        if source_path:
            path = Path(source_path)
            if not path.exists():
                raise FileNotFoundError(source_path)
            return path.read_bytes(), path.name
        stored_path = str(document.stored_path or "").strip()
        if stored_path:
            resolved = self.contract_service.resolve_document_path(stored_path)
            if resolved is None or not resolved.exists():
                raise FileNotFoundError(stored_path)
            return resolved.read_bytes(), resolved.name
        raise FileNotFoundError("No document source is available.")

    def _materialize_document(self, document: ContractDocumentPayload) -> Path:
        data, filename = self._document_bytes(document)
        suffix = Path(filename).suffix or ".bin"
        preview_dir = Path(self._preview_dir.name)
        preview_dir.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            delete=False,
            dir=preview_dir,
            prefix="document_",
            suffix=suffix,
        )
        with handle:
            handle.write(data)
        return Path(handle.name)

    def open_selected_document(self) -> Path | None:
        current = self._current_document()
        if current is None:
            QMessageBox.information(self, "Open Document", "Select a document first.")
            return None
        _, document = current
        try:
            preview_path = self._materialize_document(document)
        except Exception as exc:
            QMessageBox.critical(self, "Open Document", str(exc))
            return None
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(preview_path)))
        return preview_path

    def _export_selected_document(self, path: str | Path | None = None) -> Path | None:
        if isinstance(path, bool):
            path = None
        current = self._current_document()
        if current is None:
            QMessageBox.information(self, "Export Document", "Select a document first.")
            return None
        _, document = current
        if path is None:
            suggested = (
                document.filename
                or Path(document.stored_path or document.source_path or "contract-document").name
            )
            chosen, _ = QFileDialog.getSaveFileName(self, "Export Contract Document", suggested)
            if not chosen:
                return None
            output = Path(chosen)
        else:
            output = Path(path)
        try:
            data, _ = self._document_bytes(document)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(data)
        except Exception as exc:
            QMessageBox.critical(self, "Export Document", str(exc))
            return None
        return output

    def _set_selected_storage_mode(self, target_mode: str) -> None:
        current = self._current_document()
        if current is None:
            return
        row, document = current
        document.storage_mode = normalize_storage_mode(
            target_mode, default=STORAGE_MODE_MANAGED_FILE
        )
        self._documents[row] = document
        self._load_document_into_form(row)

    def _toggle_selected_storage_mode(self) -> None:
        current = self._current_document()
        if current is None:
            return
        _, document = current
        current_mode = normalize_storage_mode(
            document.storage_mode, default=STORAGE_MODE_MANAGED_FILE
        )
        target_mode = (
            STORAGE_MODE_DATABASE
            if current_mode == STORAGE_MODE_MANAGED_FILE
            else STORAGE_MODE_MANAGED_FILE
        )
        self._set_selected_storage_mode(target_mode)


class ContractObligationEditor(QWidget):
    """Structured editor for contract obligations and follow-up dates."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._obligations: list[ContractObligationPayload] = []
        self._current_row: int = -1
        self._suspend_updates = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        self.add_button = QPushButton("Add Obligation")
        self.add_button.clicked.connect(self._append_obligation)
        self.complete_button = QPushButton("Mark Completed")
        self.complete_button.clicked.connect(lambda: self._set_selected_completed(True))
        self.reopen_button = QPushButton("Mark Open")
        self.reopen_button.clicked.connect(lambda: self._set_selected_completed(False))
        self.remove_button = QPushButton("Remove Selected")
        self.remove_button.clicked.connect(self._remove_selected_obligation)
        root.addWidget(
            _create_action_button_cluster(
                self,
                [
                    self.add_button,
                    self.complete_button,
                    self.reopen_button,
                    self.remove_button,
                ],
                columns=2,
                min_button_width=150,
            )
        )

        splitter = QSplitter(Qt.Horizontal, self)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, 1)

        table_box = QGroupBox("Obligations", self)
        table_layout = QVBoxLayout(table_box)
        table_layout.setContentsMargins(14, 18, 14, 14)
        table_layout.setSpacing(10)
        self.obligations_table = QTableWidget(0, 6, table_box)
        self.obligations_table.setHorizontalHeaderLabels(
            ["Type", "Title", "Due", "Follow-Up", "Reminder", "Completed"]
        )
        self.obligations_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.obligations_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.obligations_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.obligations_table.verticalHeader().setVisible(False)
        header = self.obligations_table.horizontalHeader()
        header.setMinimumSectionSize(36)
        header.setSectionResizeMode(0, QHeaderView.Interactive)
        header.resizeSection(0, 116)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        for column, width in ((2, 96), (3, 96), (4, 96), (5, 82)):
            header.setSectionResizeMode(column, QHeaderView.Interactive)
            header.resizeSection(column, width)
        self.obligations_table.itemSelectionChanged.connect(self._on_selection_changed)
        table_layout.addWidget(self.obligations_table, 1)
        splitter.addWidget(table_box)

        detail_panel = QWidget(splitter)
        detail_panel.setMinimumWidth(340)
        detail_layout = QVBoxLayout(detail_panel)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.setSpacing(0)
        detail_scroll_area, _, detail_content_layout = _create_scrollable_dialog_content(
            detail_panel
        )
        detail_layout.addWidget(detail_scroll_area, 1)

        detail_intro = QLabel(
            "Track each obligation as structured metadata so due dates, reminders, completion state, and notes stay readable."
        )
        detail_intro.setWordWrap(True)
        detail_content_layout.addWidget(detail_intro)

        summary_box, summary_layout = _create_standard_section(
            self,
            "Obligation Summary",
            "Choose the obligation type and define the task title users will actually recognize later.",
        )
        summary_form = QFormLayout()
        _configure_standard_form_layout(summary_form)
        self.obligation_id_label = QLabel("")
        self.obligation_type_combo = QComboBox(self)
        for value in OBLIGATION_TYPE_CHOICES:
            self.obligation_type_combo.addItem(value.replace("_", " ").title(), value)
        self.obligation_title_edit = QLineEdit(self)
        summary_form.addRow("Obligation ID", self.obligation_id_label)
        summary_form.addRow("Obligation Type", self.obligation_type_combo)
        summary_form.addRow("Title", self.obligation_title_edit)
        summary_layout.addLayout(summary_form)
        detail_content_layout.addWidget(summary_box)

        dates_box, dates_layout = _create_standard_section(
            self,
            "Timeline",
            "Use ISO dates so the timeline stays consistent with the rest of the contract workflow.",
        )
        dates_form = QFormLayout()
        _configure_standard_form_layout(dates_form)
        self.due_date_edit = QLineEdit(self)
        self.follow_up_date_edit = QLineEdit(self)
        self.reminder_date_edit = QLineEdit(self)
        self.completed_at_edit = QLineEdit(self)
        for widget in (
            self.due_date_edit,
            self.follow_up_date_edit,
            self.reminder_date_edit,
            self.completed_at_edit,
        ):
            widget.setPlaceholderText("YYYY-MM-DD")
        dates_form.addRow("Due Date", self.due_date_edit)
        dates_form.addRow("Follow-Up Date", self.follow_up_date_edit)
        dates_form.addRow("Reminder Date", self.reminder_date_edit)
        dates_form.addRow("Completed At", self.completed_at_edit)
        dates_layout.addLayout(dates_form)
        detail_content_layout.addWidget(dates_box)

        status_box, status_layout = _create_standard_section(
            self,
            "Status and Notes",
            "Keep completion state and context together instead of encoding them into a keyword string.",
        )
        status_form = QFormLayout()
        _configure_standard_form_layout(status_form)
        self.completed_checkbox = QCheckBox("Completed", self)
        status_form.addRow("Status", self.completed_checkbox)
        status_layout.addLayout(status_form)
        self.obligation_notes_edit = QPlainTextEdit(self)
        self.obligation_notes_edit.setMinimumHeight(96)
        status_layout.addWidget(self.obligation_notes_edit)
        detail_content_layout.addWidget(status_box)
        detail_content_layout.addStretch(1)

        splitter.addWidget(detail_panel)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 5)
        splitter.setSizes([420, 520])

        for widget in (
            self.obligation_type_combo,
            self.obligation_title_edit,
            self.due_date_edit,
            self.follow_up_date_edit,
            self.reminder_date_edit,
            self.completed_checkbox,
            self.completed_at_edit,
            self.obligation_notes_edit,
        ):
            self._connect_obligation_widget(widget)

        self._refresh_action_state()

    @staticmethod
    def _payload_from_record(record) -> ContractObligationPayload:
        return ContractObligationPayload(
            obligation_id=getattr(record, "obligation_id", getattr(record, "id", None)),
            obligation_type=getattr(record, "obligation_type", "other") or "other",
            title=getattr(record, "title", "") or "",
            due_date=getattr(record, "due_date", None),
            follow_up_date=getattr(record, "follow_up_date", None),
            reminder_date=getattr(record, "reminder_date", None),
            completed=bool(getattr(record, "completed", False)),
            completed_at=getattr(record, "completed_at", None),
            notes=getattr(record, "notes", None),
        )

    def load_obligations(self, obligations) -> None:
        self._suspend_updates = True
        try:
            self._obligations = [self._payload_from_record(item) for item in obligations]
            self.obligations_table.blockSignals(True)
            try:
                self.obligations_table.setRowCount(0)
                for row, obligation in enumerate(self._obligations):
                    self._insert_obligation_row(row, obligation)
            finally:
                self.obligations_table.blockSignals(False)
            if self._obligations:
                self.obligations_table.selectRow(0)
                self._load_obligation_into_form(0)
            else:
                self._current_row = -1
                self._clear_form()
        finally:
            self._suspend_updates = False
        self._refresh_action_state()

    def obligations(self) -> list[ContractObligationPayload]:
        self._sync_current_obligation_from_form()
        return [
            ContractObligationPayload(
                obligation_id=item.obligation_id,
                obligation_type=item.obligation_type,
                title=item.title,
                due_date=item.due_date,
                follow_up_date=item.follow_up_date,
                reminder_date=item.reminder_date,
                completed=item.completed,
                completed_at=item.completed_at,
                notes=item.notes,
            )
            for item in self._obligations
            if str(item.title or "").strip()
        ]

    def _connect_obligation_widget(self, widget) -> None:
        if isinstance(widget, QLineEdit):
            widget.textChanged.connect(self._sync_current_obligation_from_form)
        elif isinstance(widget, QPlainTextEdit):
            widget.textChanged.connect(self._sync_current_obligation_from_form)
        elif isinstance(widget, QComboBox):
            widget.currentIndexChanged.connect(self._sync_current_obligation_from_form)
        elif isinstance(widget, QCheckBox):
            widget.stateChanged.connect(self._sync_current_obligation_from_form)

    def _current_obligation(self) -> tuple[int, ContractObligationPayload] | None:
        row = self._current_row
        if row < 0 or row >= len(self._obligations):
            return None
        return row, self._obligations[row]

    def _refresh_action_state(self) -> None:
        current = self._current_obligation()
        has_selection = current is not None
        self.remove_button.setEnabled(has_selection)
        self.complete_button.setEnabled(has_selection)
        self.reopen_button.setEnabled(has_selection)
        if current is not None:
            _, obligation = current
            self.complete_button.setEnabled(not obligation.completed)
            self.reopen_button.setEnabled(obligation.completed)

    def _clear_form(self) -> None:
        self.obligation_id_label.setText("")
        self._set_type_value("other")
        self.obligation_title_edit.clear()
        self.due_date_edit.clear()
        self.follow_up_date_edit.clear()
        self.reminder_date_edit.clear()
        self.completed_checkbox.setChecked(False)
        self.completed_at_edit.clear()
        self.obligation_notes_edit.clear()

    def _set_type_value(self, obligation_type: str | None) -> None:
        normalized = str(obligation_type or "other").strip().lower().replace(" ", "_") or "other"
        index = self.obligation_type_combo.findData(normalized)
        if index < 0:
            self.obligation_type_combo.addItem(normalized.replace("_", " ").title(), normalized)
            index = self.obligation_type_combo.count() - 1
        self.obligation_type_combo.setCurrentIndex(index)

    def _insert_obligation_row(self, row: int, obligation: ContractObligationPayload) -> None:
        if row >= self.obligations_table.rowCount():
            self.obligations_table.insertRow(row)
        values = [
            (obligation.obligation_type or "other").replace("_", " ").title(),
            obligation.title or "",
            obligation.due_date or "",
            obligation.follow_up_date or "",
            obligation.reminder_date or "",
            "Yes" if obligation.completed else "No",
        ]
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            if column in {2, 3, 4, 5}:
                item.setTextAlignment(Qt.AlignCenter)
            self.obligations_table.setItem(row, column, item)

    def _update_obligation_row(self, row: int) -> None:
        if row < 0 or row >= len(self._obligations):
            return
        obligation = self._obligations[row]
        values = [
            (obligation.obligation_type or "other").replace("_", " ").title(),
            obligation.title or "",
            obligation.due_date or "",
            obligation.follow_up_date or "",
            obligation.reminder_date or "",
            "Yes" if obligation.completed else "No",
        ]
        for column, value in enumerate(values):
            item = self.obligations_table.item(row, column)
            if item is None:
                item = QTableWidgetItem()
                self.obligations_table.setItem(row, column, item)
            item.setText(value)

    def _load_obligation_into_form(self, row: int) -> None:
        if row < 0 or row >= len(self._obligations):
            self._current_row = -1
            self._clear_form()
            self._refresh_action_state()
            return
        obligation = self._obligations[row]
        self._current_row = row
        self._suspend_updates = True
        try:
            self.obligation_id_label.setText(str(obligation.obligation_id or ""))
            self._set_type_value(obligation.obligation_type)
            self.obligation_title_edit.setText(obligation.title or "")
            self.due_date_edit.setText(obligation.due_date or "")
            self.follow_up_date_edit.setText(obligation.follow_up_date or "")
            self.reminder_date_edit.setText(obligation.reminder_date or "")
            self.completed_checkbox.setChecked(bool(obligation.completed))
            self.completed_at_edit.setText(obligation.completed_at or "")
            self.obligation_notes_edit.setPlainText(obligation.notes or "")
        finally:
            self._suspend_updates = False
        self._refresh_action_state()

    def _on_selection_changed(self) -> None:
        if self._suspend_updates:
            return
        self._sync_current_obligation_from_form()
        self._load_obligation_into_form(self.obligations_table.currentRow())

    def _sync_current_obligation_from_form(self) -> None:
        if self._suspend_updates:
            return
        current = self._current_obligation()
        if current is None:
            return
        row, obligation = current
        obligation.obligation_type = (
            str(self.obligation_type_combo.currentData() or "other")
            .strip()
            .lower()
            .replace(" ", "_")
            or "other"
        )
        obligation.title = self.obligation_title_edit.text().strip()
        obligation.due_date = self.due_date_edit.text().strip() or None
        obligation.follow_up_date = self.follow_up_date_edit.text().strip() or None
        obligation.reminder_date = self.reminder_date_edit.text().strip() or None
        obligation.completed = self.completed_checkbox.isChecked()
        obligation.completed_at = self.completed_at_edit.text().strip() or None
        obligation.notes = self.obligation_notes_edit.toPlainText().strip() or None
        self._obligations[row] = obligation
        self._update_obligation_row(row)
        self._refresh_action_state()

    def _append_obligation(self) -> None:
        self._sync_current_obligation_from_form()
        obligation = ContractObligationPayload(obligation_type="other", title="")
        row = len(self._obligations)
        self._obligations.append(obligation)
        self._insert_obligation_row(row, obligation)
        self.obligations_table.selectRow(row)
        self._load_obligation_into_form(row)

    def _remove_selected_obligation(self) -> None:
        current = self._current_obligation()
        if current is None:
            return
        row, _obligation = current
        del self._obligations[row]
        self.obligations_table.removeRow(row)
        if self._obligations:
            next_row = min(row, len(self._obligations) - 1)
            self.obligations_table.selectRow(next_row)
            self._load_obligation_into_form(next_row)
        else:
            self._current_row = -1
            self._clear_form()
            self._refresh_action_state()

    def _set_selected_completed(self, completed: bool) -> None:
        current = self._current_obligation()
        if current is None:
            return
        self.completed_checkbox.setChecked(bool(completed))
        if not completed:
            self.completed_at_edit.clear()
        self._sync_current_obligation_from_form()


class ContractEditorDialog(QDialog):
    """Create or edit a contract lifecycle record."""

    def __init__(self, *, contract_service: ContractService, detail=None, parent=None):
        super().__init__(parent)
        self.contract_service = contract_service
        self.detail = detail
        self.setWindowTitle("Edit Contract" if detail is not None else "Create Contract")
        self.resize(980, 780)
        self.setMinimumSize(900, 700)
        _apply_standard_dialog_chrome(self, "contractEditorDialog")

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)
        _add_standard_dialog_header(
            root,
            self,
            title=self.windowTitle(),
            subtitle=(
                "Track lifecycle dates, linked parties, obligations, and document versions "
                "for one contract without losing the connection between them."
            ),
        )
        tabs = QTabWidget(self)
        root.addWidget(tabs, 1)

        overview_scroll, _, overview_layout = _create_scrollable_dialog_content(self)
        core_box, core_layout = _create_standard_section(
            self,
            "Contract Overview",
            "Core identification fields for the agreement, plus high-level summary and notes.",
        )
        core_form = QFormLayout()
        _configure_standard_form_layout(core_form)

        self.title_edit = QLineEdit()
        core_form.addRow("Title", self.title_edit)

        self.type_edit = QLineEdit()
        core_form.addRow("Contract Type", self.type_edit)

        self.status_combo = QComboBox()
        self.status_combo.addItems(
            [value.replace("_", " ").title() for value in CONTRACT_STATUS_CHOICES]
        )
        core_form.addRow("Status", self.status_combo)

        self.summary_edit = QPlainTextEdit()
        self.summary_edit.setMinimumHeight(88)
        core_form.addRow("Summary", self.summary_edit)

        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setMinimumHeight(96)
        core_form.addRow("Notes", self.notes_edit)
        core_layout.addLayout(core_form)
        overview_layout.addWidget(core_box)

        lifecycle_box, lifecycle_layout = _create_standard_section(
            self,
            "Lifecycle Dates",
            "Keep the contract timeline in one place so notice windows, renewals, and reversion points stay visible.",
        )
        self.draft_edit = QLineEdit()
        self.signature_edit = QLineEdit()
        self.effective_edit = QLineEdit()
        self.start_edit = QLineEdit()
        self.end_edit = QLineEdit()
        self.renewal_edit = QLineEdit()
        self.notice_edit = QLineEdit()
        self.reversion_edit = QLineEdit()
        self.termination_edit = QLineEdit()
        self.option_periods_edit = QLineEdit()

        for widget in (
            self.draft_edit,
            self.signature_edit,
            self.effective_edit,
            self.start_edit,
            self.end_edit,
            self.renewal_edit,
            self.notice_edit,
            self.reversion_edit,
            self.termination_edit,
        ):
            widget.setPlaceholderText("YYYY-MM-DD")

        def _add_lifecycle_group(title: str, rows: list[tuple[str, QWidget]]) -> None:
            group = QGroupBox(title, self)
            group_layout = QVBoxLayout(group)
            group_layout.setContentsMargins(12, 14, 12, 12)
            group_layout.setSpacing(8)
            form = QFormLayout()
            _configure_standard_form_layout(form)
            for label_text, widget in rows:
                form.addRow(label_text, widget)
            group_layout.addLayout(form)
            lifecycle_layout.addWidget(group)

        _add_lifecycle_group(
            "Execution",
            [
                ("Draft Date", self.draft_edit),
                ("Signature Date", self.signature_edit),
                ("Effective Date", self.effective_edit),
            ],
        )
        _add_lifecycle_group(
            "Term and Renewal",
            [
                ("Start Date", self.start_edit),
                ("End Date", self.end_edit),
                ("Renewal Date", self.renewal_edit),
                ("Option Periods", self.option_periods_edit),
            ],
        )
        _add_lifecycle_group(
            "Notice and Exit",
            [
                ("Notice Deadline", self.notice_edit),
                ("Reversion Date", self.reversion_edit),
                ("Termination Date", self.termination_edit),
            ],
        )
        overview_layout.addWidget(lifecycle_box)
        overview_layout.addStretch(1)
        tabs.addTab(overview_scroll, "Overview")

        links_page = QWidget(self)
        links_page.setProperty("role", "workspaceCanvas")
        links_layout = QVBoxLayout(links_page)
        links_layout.setContentsMargins(0, 0, 0, 0)
        links_layout.setSpacing(0)
        links_splitter = QSplitter(Qt.Horizontal, links_page)
        links_splitter.setObjectName("contractLinksPartiesSplitter")
        links_splitter.setChildrenCollapsible(False)
        links_layout.addWidget(links_splitter, 1)

        repertoire_panel = QWidget(links_splitter)
        repertoire_panel_layout = QVBoxLayout(repertoire_panel)
        repertoire_panel_layout.setContentsMargins(0, 0, 0, 0)
        repertoire_panel_layout.setSpacing(0)
        repertoire_box, repertoire_layout = _create_standard_section(
            self,
            "Linked Repertoire",
            "Reference the related works, tracks, and releases connected to this agreement.",
        )

        self.work_ids_edit = _ReferenceListEditor(
            placeholder="Select a linked work or type an ID",
            parent=self,
        )
        self.work_ids_edit.setObjectName("contractWorkReferenceEditor")

        self.track_ids_edit = _ReferenceListEditor(
            placeholder="Select a linked track or type an ID",
            parent=self,
        )
        self.track_ids_edit.setObjectName("contractTrackReferenceEditor")

        self.release_ids_edit = _ReferenceListEditor(
            placeholder="Select a linked release or type an ID",
            parent=self,
        )
        self.release_ids_edit.setObjectName("contractReleaseReferenceEditor")
        for title, editor in (
            ("Linked Works", self.work_ids_edit),
            ("Linked Tracks", self.track_ids_edit),
            ("Linked Releases", self.release_ids_edit),
        ):
            label = QLabel(title, repertoire_box)
            label.setProperty("role", "supportingText")
            repertoire_layout.addWidget(label)
            repertoire_layout.addWidget(editor)
        repertoire_panel_layout.addWidget(repertoire_box, 1)
        links_splitter.addWidget(repertoire_panel)

        parties_panel = QWidget(links_splitter)
        parties_panel_layout = QVBoxLayout(parties_panel)
        parties_panel_layout.setContentsMargins(0, 0, 0, 0)
        parties_panel_layout.setSpacing(0)
        parties_box, parties_layout = _create_standard_section(
            self,
            "Linked Parties",
            "Keep parties structured with role, primary status, and notes while still allowing typed names for new counterparties.",
        )
        self.parties_edit = _ContractPartyEditor(
            placeholder="Search known party or type a new party name",
            parent=self,
        )
        parties_layout.addWidget(self.parties_edit)
        parties_panel_layout.addWidget(parties_box, 1)
        links_splitter.addWidget(parties_panel)
        links_splitter.setStretchFactor(0, 5)
        links_splitter.setStretchFactor(1, 4)
        links_splitter.setSizes([560, 420])
        tabs.addTab(links_page, "Links and Parties")

        obligations_scroll, _, obligations_layout = _create_scrollable_dialog_content(self)
        obligations_box, obligations_box_layout = _create_standard_section(
            self,
            "Obligations",
            "Track deadlines, reminders, completion state, and notes with dedicated fields instead of encoding them into a keyword string.",
        )
        self.obligations_editor = ContractObligationEditor(self)
        obligations_box_layout.addWidget(self.obligations_editor)
        obligations_layout.addWidget(obligations_box)
        obligations_layout.addStretch(1)
        tabs.addTab(obligations_scroll, "Obligations")

        documents_page = QWidget(self)
        documents_page.setProperty("role", "workspaceCanvas")
        documents_layout = QVBoxLayout(documents_page)
        documents_layout.setContentsMargins(0, 0, 0, 0)
        documents_layout.setSpacing(0)
        self.documents_editor = ContractDocumentEditor(
            contract_service=self.contract_service,
            parent=self,
        )
        documents_layout.addWidget(self.documents_editor, 1)
        tabs.addTab(documents_page, "Documents")

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        save_button = buttons.button(QDialogButtonBox.Save)
        if save_button is not None:
            save_button.setText("Save Contract")
            save_button.setDefault(True)
        root.addWidget(buttons)
        _apply_compact_dialog_control_heights(self)
        self._populate_reference_editors()

        if detail is not None:
            contract = detail.contract
            self.title_edit.setText(contract.title)
            self.type_edit.setText(contract.contract_type or "")
            self.status_combo.setCurrentText(contract.status.replace("_", " ").title())
            self.draft_edit.setText(contract.draft_date or "")
            self.signature_edit.setText(contract.signature_date or "")
            self.effective_edit.setText(contract.effective_date or "")
            self.start_edit.setText(contract.start_date or "")
            self.end_edit.setText(contract.end_date or "")
            self.renewal_edit.setText(contract.renewal_date or "")
            self.notice_edit.setText(contract.notice_deadline or "")
            self.option_periods_edit.setText(contract.option_periods or "")
            self.reversion_edit.setText(contract.reversion_date or "")
            self.termination_edit.setText(contract.termination_date or "")
            self.summary_edit.setPlainText(contract.summary or "")
            self.notes_edit.setPlainText(contract.notes or "")
            self.work_ids_edit.set_value_ids(detail.work_ids)
            self.track_ids_edit.set_value_ids(detail.track_ids)
            self.release_ids_edit.set_value_ids(detail.release_ids)
            self.parties_edit.set_value(detail.parties)
            self.obligations_editor.load_obligations(detail.obligations)
            self.documents_editor.load_documents(detail.documents)
        else:
            self.obligations_editor.load_obligations([])
            self.documents_editor.load_documents([])

    def _reference_choices_from_query(self, query: str, formatter) -> list[_ReferenceChoice]:
        conn = getattr(self.contract_service, "conn", None)
        if conn is None:
            return []
        choices: list[_ReferenceChoice] = []
        for row in conn.execute(query).fetchall():
            try:
                reference_id = int(row[0])
            except Exception:
                continue
            choices.append(_ReferenceChoice(reference_id, formatter(row)))
        return choices

    def _populate_reference_editors(self) -> None:
        self.work_ids_edit.set_choices(
            self._reference_choices_from_query(
                """
                SELECT id, title, COALESCE(iswc, '')
                FROM Works
                ORDER BY title, id
                """,
                lambda row: " / ".join(
                    part for part in (str(row[1] or "").strip(), str(row[2] or "").strip()) if part
                )
                or f"Work #{int(row[0])}",
            )
        )
        self.track_ids_edit.set_choices(
            self._reference_choices_from_query(
                """
                SELECT
                    t.id,
                    t.track_title,
                    COALESCE(a.name, '')
                FROM Tracks t
                LEFT JOIN Artists a ON a.id = t.main_artist_id
                ORDER BY t.track_title, t.id
                """,
                lambda row: " / ".join(
                    part for part in (str(row[1] or "").strip(), str(row[2] or "").strip()) if part
                )
                or f"Track #{int(row[0])}",
            )
        )
        self.release_ids_edit.set_choices(
            self._reference_choices_from_query(
                """
                SELECT id, title, COALESCE(primary_artist, '')
                FROM Releases
                ORDER BY title, id
                """,
                lambda row: " / ".join(
                    part for part in (str(row[1] or "").strip(), str(row[2] or "").strip()) if part
                )
                or f"Release #{int(row[0])}",
            )
        )
        self.parties_edit.set_choices(
            self._reference_choices_from_query(
                """
                SELECT
                    id,
                    legal_name,
                    COALESCE(display_name, ''),
                    COALESCE(email, '')
                FROM Parties
                ORDER BY COALESCE(display_name, legal_name), legal_name, id
                """,
                lambda row: " / ".join(
                    part
                    for part in (
                        str(row[2] or "").strip(),
                        str(row[1] or "").strip(),
                        str(row[3] or "").strip(),
                    )
                    if part
                )
                or f"Party #{int(row[0])}",
            )
        )

    def payload(self) -> ContractPayload:
        return ContractPayload(
            title=self.title_edit.text().strip(),
            contract_type=self.type_edit.text().strip() or None,
            draft_date=self.draft_edit.text().strip() or None,
            signature_date=self.signature_edit.text().strip() or None,
            effective_date=self.effective_edit.text().strip() or None,
            start_date=self.start_edit.text().strip() or None,
            end_date=self.end_edit.text().strip() or None,
            renewal_date=self.renewal_edit.text().strip() or None,
            notice_deadline=self.notice_edit.text().strip() or None,
            option_periods=self.option_periods_edit.text().strip() or None,
            reversion_date=self.reversion_edit.text().strip() or None,
            termination_date=self.termination_edit.text().strip() or None,
            status=self.status_combo.currentText().strip().lower().replace(" ", "_"),
            summary=self.summary_edit.toPlainText().strip() or None,
            notes=self.notes_edit.toPlainText().strip() or None,
            parties=self.parties_edit.value(),
            obligations=self.obligations_editor.obligations(),
            documents=self.documents_editor.documents(),
            work_ids=self.work_ids_edit.value_ids(),
            track_ids=self.track_ids_edit.value_ids(),
            release_ids=self.release_ids_edit.value_ids(),
        )

    def closeEvent(self, event) -> None:  # pragma: no cover - Qt lifecycle hook
        documents_editor = getattr(self, "documents_editor", None)
        cleanup = getattr(documents_editor, "cleanup", None)
        if callable(cleanup):
            cleanup()
        super().closeEvent(event)


class ContractBrowserPanel(QWidget):
    """Browse and edit contract lifecycle records inside a workspace panel."""

    def __init__(self, *, contract_service_provider, parent=None):
        super().__init__(parent)
        self.contract_service_provider = contract_service_provider
        self.setObjectName("contractBrowserPanel")
        _apply_standard_widget_chrome(self, "contractBrowserPanel")

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(14)
        _add_standard_dialog_header(
            root,
            self,
            title="Contract Manager",
            subtitle=(
                "See which contracts are draft, active, expiring, or blocked by missing "
                "signatures and document versions."
            ),
        )

        controls_box, controls_layout = _create_standard_section(
            self,
            "Find and Manage",
            "Search by title, contract type, linked party, or summary, then act on the selected agreement.",
        )
        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(10)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search contracts by title, type, party, or summary...")
        self.search_edit.textChanged.connect(self.refresh)
        controls.addWidget(self.search_edit, 1)
        controls_layout.addLayout(controls)
        action_buttons: list[QPushButton] = []
        for label, handler in (
            ("Add", self.create_contract),
            ("Edit", self.edit_selected),
            ("Delete", self.delete_selected),
            ("Export Deadlines…", self.export_deadlines),
            ("Refresh", self.refresh),
        ):
            button = QPushButton(label)
            button.clicked.connect(handler)
            action_buttons.append(button)
        controls_layout.addWidget(
            _create_action_button_cluster(
                self,
                action_buttons,
                columns=3,
                min_button_width=140,
            )
        )
        root.addWidget(controls_box)

        table_box, table_layout = _create_standard_section(
            self,
            "Contracts",
            "Double-click a row to open the editor for the selected contract.",
        )
        self.table = QTableWidget(0, 7, table_box)
        self.table.setHorizontalHeaderLabels(
            ["ID", "Title", "Type", "Status", "Notice", "Obligations", "Documents"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.table.doubleClicked.connect(lambda _index: self.edit_selected())
        table_layout.addWidget(self.table, 1)
        root.addWidget(table_box, 1)

        _apply_compact_dialog_control_heights(self)

        self.refresh()

    def _contract_service(self) -> ContractService | None:
        return self.contract_service_provider()

    def _restore_selection(self, contract_id: int | None) -> None:
        if not contract_id:
            return
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is None:
                continue
            try:
                current_contract_id = int(item.text())
            except Exception:
                continue
            if current_contract_id != int(contract_id):
                continue
            self.table.selectRow(row)
            return

    def focus_contract(self, contract_id: int | None) -> None:
        self.table.clearSelection()
        self._restore_selection(contract_id)

    def _selected_contract_id(self) -> int | None:
        selection_model = self.table.selectionModel()
        if selection_model is None:
            return None
        rows = selection_model.selectedRows()
        if not rows:
            return None
        item = self.table.item(rows[0].row(), 0)
        return int(item.text()) if item is not None else None

    def refresh(self) -> None:
        selected_contract_id = self._selected_contract_id()
        service = self._contract_service()
        if service is None:
            self.table.setRowCount(0)
            return
        rows = service.list_contracts(search_text=self.search_edit.text())
        self.table.setRowCount(0)
        for record in rows:
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = [
                str(record.id),
                record.title,
                record.contract_type or "",
                record.status.replace("_", " ").title(),
                record.notice_deadline or "",
                str(record.obligation_count),
                str(record.document_count),
            ]
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))
        self.table.resizeColumnsToContents()
        self._restore_selection(selected_contract_id)

    def create_contract(self) -> None:
        service = self._contract_service()
        if service is None:
            QMessageBox.warning(self, "Contract Manager", "Open a profile first.")
            return
        dialog = ContractEditorDialog(contract_service=service, parent=self)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            contract_id = service.create_contract(dialog.payload())
        except Exception as exc:
            QMessageBox.critical(self, "Contract Manager", str(exc))
            return
        self.refresh()
        self.focus_contract(contract_id)

    def edit_selected(self) -> None:
        service = self._contract_service()
        if service is None:
            QMessageBox.warning(self, "Contract Manager", "Open a profile first.")
            return
        contract_id = self._selected_contract_id()
        if not contract_id:
            QMessageBox.information(self, "Contract Manager", "Select a contract first.")
            return
        detail = service.fetch_contract_detail(contract_id)
        if detail is None:
            self.refresh()
            return
        dialog = ContractEditorDialog(contract_service=service, detail=detail, parent=self)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            service.update_contract(contract_id, dialog.payload())
        except Exception as exc:
            QMessageBox.critical(self, "Contract Manager", str(exc))
            return
        self.refresh()
        self.focus_contract(contract_id)

    def delete_selected(self) -> None:
        service = self._contract_service()
        if service is None:
            QMessageBox.warning(self, "Contract Manager", "Open a profile first.")
            return
        contract_id = self._selected_contract_id()
        if not contract_id:
            QMessageBox.information(self, "Contract Manager", "Select a contract first.")
            return
        if not _confirm_destructive_action(
            self,
            title="Delete Contract",
            prompt="Delete the selected contract?",
        ):
            return
        service.delete_contract(contract_id)
        self.refresh()

    def export_deadlines(self) -> None:
        service = self._contract_service()
        if service is None:
            QMessageBox.warning(self, "Contract Manager", "Open a profile first.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Upcoming Deadlines", "", "CSV Files (*.csv)"
        )
        if not path:
            return
        try:
            service.export_deadlines_csv(path)
        except Exception as exc:
            QMessageBox.critical(self, "Contract Manager", str(exc))


class ContractBrowserDialog(QDialog):
    """Compatibility dialog wrapper around the reusable contract manager panel."""

    def __init__(self, *, contract_service: ContractService, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Contract Manager")
        self.resize(1060, 700)
        self.setMinimumSize(940, 620)
        _apply_standard_dialog_chrome(self, "contractBrowserDialog")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.panel = ContractBrowserPanel(
            contract_service_provider=lambda: contract_service,
            parent=self,
        )
        root.addWidget(self.panel)

    def __getattr__(self, name: str):
        panel = self.__dict__.get("panel")
        if panel is not None and hasattr(panel, name):
            return getattr(panel, name)
        raise AttributeError(name)

"""Dialogs for audio tag preview and conflict resolution."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QCompleter,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from isrc_manager.file_storage import (
    STORAGE_MODE_DATABASE,
    STORAGE_MODE_MANAGED_FILE,
    normalize_storage_mode,
)
from isrc_manager.parties import PartyService, artist_primary_label, party_authority_notifier
from isrc_manager.ui_common import (
    _add_standard_dialog_header,
    _apply_compact_dialog_control_heights,
    _apply_standard_dialog_chrome,
)

TAG_POLICY_CHOICES = (
    ("merge_blanks", "Merge blanks only"),
    ("prefer_file_tags", "Prefer file tags"),
    ("prefer_database", "Prefer database values"),
)


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


def _connect_args_signal(signal: Any, owner: object, slot: Callable[..., object]) -> None:
    def _wrapper(*args: object, _slot: Callable[..., object] = slot) -> None:
        try:
            _slot(*args)
        except RuntimeError as exc:
            if "Internal C++ object" not in str(exc):
                raise

    _keep_signal_wrapper_alive(owner, _wrapper)
    signal.connect(_wrapper)


class TagPreviewDialog(QDialog):
    """Preview tag mapping conflicts before import or export."""

    def __init__(
        self,
        *,
        title: str,
        intro: str,
        rows: list[dict[str, object]],
        initial_policy: str = "merge_blanks",
        allow_policy_change: bool = True,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(980, 640)
        self._rows = rows
        _apply_standard_dialog_chrome(self, "tagPreviewDialog")

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)
        _add_standard_dialog_header(
            root,
            self,
            title=title,
            subtitle=intro,
        )

        policy_row = QHBoxLayout()
        policy_row.setContentsMargins(0, 0, 0, 0)
        policy_row.setSpacing(8)
        policy_label = QLabel("Conflict policy")
        policy_label.setProperty("role", "secondary")
        policy_row.addWidget(policy_label)
        self.policy_combo = QComboBox()
        for key, label in TAG_POLICY_CHOICES:
            self.policy_combo.addItem(label, key)
        index = self.policy_combo.findData(initial_policy)
        self.policy_combo.setCurrentIndex(index if index >= 0 else 0)
        self.policy_combo.setEnabled(allow_policy_change)
        policy_row.addWidget(self.policy_combo)
        policy_row.addStretch(1)
        root.addLayout(policy_row)

        self.table = QTableWidget(0, 6, self)
        self.table.setHorizontalHeaderLabels(
            ["Track", "Field", "Database", "File Tags", "Chosen", "Source File"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        root.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        confirm = QPushButton("Continue")
        confirm.setDefault(True)
        _connect_noarg_signal(confirm.clicked, confirm, self.accept)
        cancel = QPushButton("Cancel")
        _connect_noarg_signal(cancel.clicked, cancel, self.reject)
        buttons.addWidget(confirm)
        buttons.addWidget(cancel)
        root.addLayout(buttons)

        self.populate_rows(rows)
        _apply_compact_dialog_control_heights(self)

    def populate_rows(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows
        self.table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = [
                str(row.get("track") or ""),
                str(row.get("field") or ""),
                str(row.get("database") or ""),
                str(row.get("file") or ""),
                str(row.get("chosen") or ""),
                str(row.get("source") or ""),
            ]
            for column, value in enumerate(values):
                self.table.setItem(row_index, column, QTableWidgetItem(value))

    def selected_policy(self) -> str:
        return str(self.policy_combo.currentData() or "merge_blanks")


class BulkAudioAttachDialog(QDialog):
    """Review catalog media matches before attachment writes are applied."""

    def __init__(
        self,
        *,
        title: str,
        intro: str,
        items: list[dict[str, object]],
        track_choices: list[tuple[int, str, str | None]],
        media_label: str = "audio file",
        suggested_artist: str | None = None,
        party_service: PartyService | None = None,
        default_storage_mode: str | None = STORAGE_MODE_MANAGED_FILE,
        attach_button_text: str = "Attach Files",
        create_track_button_text: str = "Open Add Track Instead…",
        allow_artist_name_update: bool = True,
        allow_create_track: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(1080, 720)
        self._items = list(items)
        self._media_label = str(media_label or "media file")
        self._allow_artist_name_update = bool(allow_artist_name_update)
        self._allow_create_track = bool(allow_create_track)
        self._create_track_requested = False
        self.party_service = party_service
        self._track_choices = list(track_choices)
        self._track_choice_map = {
            int(track_id): {"label": label, "artist": artist}
            for track_id, label, artist in self._track_choices
        }
        self._match_combos: list[QComboBox] = []
        _apply_standard_dialog_chrome(self, "bulkAudioAttachDialog")

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)
        _add_standard_dialog_header(
            root,
            self,
            title=title,
            subtitle=intro,
        )

        storage_row = QHBoxLayout()
        storage_row.setContentsMargins(0, 0, 0, 0)
        storage_row.setSpacing(8)
        storage_label = QLabel("Storage mode")
        storage_label.setProperty("role", "secondary")
        storage_row.addWidget(storage_label)
        self.storage_combo = QComboBox(self)
        self.storage_combo.addItem("Managed local files", STORAGE_MODE_MANAGED_FILE)
        self.storage_combo.addItem("Internal database storage", STORAGE_MODE_DATABASE)
        normalized_default_mode = normalize_storage_mode(default_storage_mode, default=None)
        index = self.storage_combo.findData(normalized_default_mode)
        self.storage_combo.setCurrentIndex(index if index >= 0 else 0)
        storage_row.addWidget(self.storage_combo)
        storage_row.addStretch(1)
        root.addLayout(storage_row)

        self.apply_artist_checkbox = QCheckBox("Apply artist to matched tracks")
        self.apply_artist_checkbox.setChecked(
            bool(suggested_artist) and self._allow_artist_name_update
        )
        self.artist_edit = QComboBox(self)
        self.artist_edit.setEditable(True)
        self.artist_edit.setInsertPolicy(QComboBox.NoInsert)
        self.artist_edit.setPlaceholderText("Optional artist name for all matched tracks")
        self._refresh_artist_choice_combo(str(suggested_artist or ""))
        self.artist_edit.setEnabled(self.apply_artist_checkbox.isChecked())
        self.apply_artist_checkbox.toggled.connect(self.artist_edit.setEnabled)
        if self._allow_artist_name_update:
            artist_row = QHBoxLayout()
            artist_row.setContentsMargins(0, 0, 0, 0)
            artist_row.setSpacing(8)
            artist_row.addWidget(self.apply_artist_checkbox)
            artist_row.addWidget(self.artist_edit, 1)
            root.addLayout(artist_row)
        else:
            self.apply_artist_checkbox.setVisible(False)
            self.artist_edit.setVisible(False)

        self.summary_label = QLabel("")
        self.summary_label.setProperty("role", "secondary")
        root.addWidget(self.summary_label)

        self.table = QTableWidget(0, 6, self)
        self.table.setHorizontalHeaderLabels(
            [
                "Attach To Track",
                "Match Basis",
                "Detected",
                "Selected Target",
                "Warning",
                "Source File",
            ]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        root.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        if self._allow_create_track and len(self._items) == 1:
            create_track = QPushButton(create_track_button_text)
            _connect_noarg_signal(create_track.clicked, create_track, self._request_create_track)
            buttons.addWidget(create_track)
        buttons.addStretch(1)
        confirm = QPushButton(attach_button_text)
        confirm.setDefault(True)
        _connect_noarg_signal(confirm.clicked, confirm, self.accept)
        cancel = QPushButton("Cancel")
        _connect_noarg_signal(cancel.clicked, cancel, self.reject)
        buttons.addWidget(confirm)
        buttons.addWidget(cancel)
        root.addLayout(buttons)

        self.populate_rows(self._items)
        _apply_compact_dialog_control_heights(self)
        if self.party_service is not None:
            notifier = party_authority_notifier()
            _connect_args_signal(notifier.changed, self, self._refresh_artist_choice_combo)

    @staticmethod
    def _display_text_for_choice(track_id: int, label: str) -> str:
        clean_label = str(label or "").strip()
        if clean_label and clean_label.startswith(f"{int(track_id)} - "):
            return clean_label
        if clean_label:
            return f"{int(track_id)} - {clean_label}"
        return f"{int(track_id)}"

    @staticmethod
    def _extract_track_id(text: str | None) -> int | None:
        match = re.match(r"^\s*(\d+)\b", str(text or ""))
        if match is None:
            return None
        try:
            return int(match.group(1))
        except (TypeError, ValueError):
            return None

    def _resolve_track_id(self, combo: QComboBox) -> int | None:
        current_index = combo.currentIndex()
        data = combo.currentData()
        if current_index > 0 and data not in (None, ""):
            if (
                str(combo.currentText() or "").strip()
                == str(combo.itemText(current_index) or "").strip()
            ):
                try:
                    return int(data)
                except (TypeError, ValueError):
                    return None
        extracted = self._extract_track_id(combo.currentText())
        if extracted in self._track_choice_map:
            return int(extracted)
        return None

    def _combo_for_row(self, row_index: int) -> QComboBox:
        return self._match_combos[row_index]

    def _candidate_hint_text(self, item: dict[str, object]) -> str:
        candidate_ids = []
        for value in item.get("candidate_track_ids") or []:
            try:
                candidate_ids.append(int(value))
            except (TypeError, ValueError):
                continue
        if not candidate_ids:
            return ""
        labels: list[str] = []
        for track_id in candidate_ids[:5]:
            label = str(self._track_choice_map.get(track_id, {}).get("label") or f"{track_id}")
            labels.append(label)
        if len(candidate_ids) > 5:
            labels.append(f"+{len(candidate_ids) - 5} more")
        return "Possible matches: " + "; ".join(labels)

    def populate_rows(self, items: list[dict[str, object]]) -> None:
        self._items = list(items)
        self._match_combos = []
        self.table.setRowCount(len(items))
        for row_index, item in enumerate(items):
            combo = QComboBox(self.table)
            combo.setEditable(True)
            combo.setInsertPolicy(QComboBox.NoInsert)
            combo.addItem("(Skip this file)", None)
            for track_id, label, _artist in self._track_choices:
                combo.addItem(self._display_text_for_choice(track_id, label), int(track_id))
            completer = combo.completer()
            if completer is not None:
                completer.setCompletionMode(QCompleter.PopupCompletion)
                completer.setFilterMode(Qt.MatchContains)
            matched_track_id = item.get("matched_track_id")
            index = combo.findData(int(matched_track_id)) if matched_track_id else 0
            combo.setCurrentIndex(index if index >= 0 else 0)
            combo.currentIndexChanged.connect(
                lambda _index, row=row_index, source_combo=combo: self._update_row_target(
                    row, source_combo
                )
            )
            combo.currentTextChanged.connect(
                lambda _text, row=row_index, source_combo=combo: self._update_row_target(
                    row, source_combo
                )
            )
            self._match_combos.append(combo)
            self.table.setCellWidget(row_index, 0, combo)
            self.table.setItem(
                row_index,
                1,
                QTableWidgetItem(str(item.get("match_basis") or item.get("status") or "")),
            )
            detected_parts = [
                str(item.get("detected_title") or "").strip(),
                str(item.get("detected_artist") or "").strip(),
                str(item.get("detected_album") or "").strip(),
            ]
            detected_text = " / ".join(part for part in detected_parts if part)
            if not detected_text:
                detected_text = str(item.get("detected_display") or "").strip()
            self.table.setItem(
                row_index,
                2,
                QTableWidgetItem(detected_text),
            )
            self.table.setItem(row_index, 3, QTableWidgetItem(""))
            warning_text = str(item.get("warning") or "").strip()
            candidate_hint = self._candidate_hint_text(item)
            if candidate_hint:
                warning_text = (
                    f"{warning_text}\n{candidate_hint}" if warning_text else candidate_hint
                )
            warning_item = QTableWidgetItem(warning_text)
            if warning_text:
                warning_item.setToolTip(warning_text)
            self.table.setItem(row_index, 4, warning_item)
            self.table.setItem(
                row_index,
                5,
                QTableWidgetItem(str(item.get("source_name") or "")),
            )
            self._update_row_target(row_index, combo)
        self._refresh_summary()

    def _update_row_target(self, row: int, combo: QComboBox) -> None:
        track_id = self._resolve_track_id(combo)
        target_item = self.table.item(row, 3)
        if target_item is None:
            target_item = QTableWidgetItem("")
            self.table.setItem(row, 3, target_item)
        if track_id is None:
            original_track_id = self._items[row].get("matched_track_id")
            if original_track_id not in (None, ""):
                try:
                    track_id = int(original_track_id)
                except (TypeError, ValueError):
                    track_id = None
        if track_id is None:
            target_item.setText("")
        else:
            target_item.setText(
                str(self._track_choice_map.get(int(track_id), {}).get("label") or "")
            )
        if len(self._match_combos) == len(self._items):
            self._refresh_summary()

    def _refresh_summary(self) -> None:
        if len(self._match_combos) < len(self._items):
            return
        matched = len(self.selected_matches())
        total = len(self._items)
        unresolved_count = sum(
            1
            for row_index in range(total)
            if self._resolve_track_id(self._combo_for_row(row_index)) is None
        )
        summary = f"{matched} of {total} {self._media_label}(s) are queued for attachment."
        if unresolved_count:
            summary += (
                " 1 row still needs a target."
                if unresolved_count == 1
                else f" {unresolved_count} rows still need a target."
            )
        self.summary_label.setText(summary)

    def _artist_choice_values(self) -> list[str]:
        values: list[str] = []
        seen: set[str] = set()
        if self.party_service is None:
            return values
        for record in self.party_service.list_artist_parties():
            primary = artist_primary_label(record)
            for candidate in (primary, *list(getattr(record, "artist_aliases", ()) or ())):
                clean_value = str(candidate or "").strip()
                if not clean_value or clean_value in seen:
                    continue
                seen.add(clean_value)
                values.append(clean_value)
        return values

    def _refresh_artist_choice_combo(self, current_text: str | None = None) -> None:
        if not isinstance(self.artist_edit, QComboBox):
            return
        desired_text = str(
            current_text if current_text is not None else self.artist_edit.currentText()
        ).strip()
        if desired_text and self.party_service is not None:
            party_id = self.party_service.find_artist_party_id_by_name(desired_text)
            if party_id is not None:
                record = self.party_service.fetch_party(int(party_id))
                if record is not None:
                    desired_text = artist_primary_label(record)
        values = self._artist_choice_values()
        previous_state = self.artist_edit.blockSignals(True)
        try:
            self.artist_edit.clear()
            self.artist_edit.addItems(values)
            completer = QCompleter(values, self.artist_edit)
            completer.setCaseSensitivity(Qt.CaseInsensitive)
            completer.setCompletionMode(QCompleter.PopupCompletion)
            completer.setFilterMode(Qt.MatchContains)
            self.artist_edit.setCompleter(completer)
            if desired_text:
                self.artist_edit.setCurrentIndex(-1)
                self.artist_edit.setEditText(desired_text)
        finally:
            self.artist_edit.blockSignals(previous_state)

    def selected_matches(self) -> list[dict[str, object]]:
        matches: list[dict[str, object]] = []
        for row_index, item in enumerate(self._items):
            combo = self._match_combos[row_index]
            track_id = self._resolve_track_id(combo)
            if track_id is None:
                continue
            matches.append(
                {
                    "source_path": str(item.get("source_path") or ""),
                    "source_name": str(item.get("source_name") or ""),
                    "track_id": int(track_id),
                    "detected_artist": str(item.get("detected_artist") or ""),
                    "detected_album": str(item.get("detected_album") or ""),
                }
            )
        return matches

    def selected_artist_name(self) -> str | None:
        if not self._allow_artist_name_update or not self.apply_artist_checkbox.isChecked():
            return None
        text = self.artist_edit.currentText().strip()
        return text or None

    def selected_storage_mode(self) -> str:
        return str(self.storage_combo.currentData() or STORAGE_MODE_MANAGED_FILE)

    def create_track_requested(self) -> bool:
        return bool(self._create_track_requested)

    def _request_create_track(self) -> None:
        self._create_track_requested = True
        self.accept()

    def accept(self) -> None:
        matches = self.selected_matches()
        if not matches and not self._create_track_requested:
            QMessageBox.warning(
                self, self.windowTitle(), "Choose at least one file-to-track match."
            )
            return
        seen: set[int] = set()
        duplicates: list[str] = []
        for match in matches:
            track_id = int(match["track_id"])
            if track_id in seen:
                duplicates.append(str(track_id))
            seen.add(track_id)
        if duplicates:
            QMessageBox.warning(
                self,
                self.windowTitle(),
                "Each track can receive only one attached audio file per batch.\n\n"
                f"Duplicate track IDs: {', '.join(duplicates)}",
            )
            return
        super().accept()

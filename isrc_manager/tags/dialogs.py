"""Dialogs for audio tag preview and conflict resolution."""

from __future__ import annotations

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
        confirm.clicked.connect(self.accept)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
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
    """Review and adjust batch audio-to-track matches before attachment."""

    def __init__(
        self,
        *,
        title: str,
        intro: str,
        items: list[dict[str, object]],
        track_choices: list[tuple[int, str, str | None]],
        suggested_artist: str | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(1080, 720)
        self._items = list(items)
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

        artist_row = QHBoxLayout()
        artist_row.setContentsMargins(0, 0, 0, 0)
        artist_row.setSpacing(8)
        self.apply_artist_checkbox = QCheckBox("Apply artist to matched tracks")
        self.apply_artist_checkbox.setChecked(bool(suggested_artist))
        artist_row.addWidget(self.apply_artist_checkbox)
        self.artist_edit = QLineEdit()
        self.artist_edit.setPlaceholderText("Optional artist name for all matched tracks")
        self.artist_edit.setText(str(suggested_artist or ""))
        self.artist_edit.setEnabled(self.apply_artist_checkbox.isChecked())
        self.apply_artist_checkbox.toggled.connect(self.artist_edit.setEnabled)
        artist_row.addWidget(self.artist_edit, 1)
        root.addLayout(artist_row)

        self.summary_label = QLabel("")
        self.summary_label.setProperty("role", "secondary")
        root.addWidget(self.summary_label)

        self.table = QTableWidget(0, 6, self)
        self.table.setHorizontalHeaderLabels(
            [
                "Attach To Track",
                "Match Basis",
                "Detected Artist",
                "Current Artist",
                "Detected Title",
                "Source File",
            ]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        root.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        confirm = QPushButton("Attach Files")
        confirm.setDefault(True)
        confirm.clicked.connect(self.accept)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(confirm)
        buttons.addWidget(cancel)
        root.addLayout(buttons)

        self.populate_rows(self._items)
        _apply_compact_dialog_control_heights(self)

    def populate_rows(self, items: list[dict[str, object]]) -> None:
        self._items = list(items)
        self._match_combos = []
        self.table.setRowCount(len(items))
        for row_index, item in enumerate(items):
            combo = QComboBox(self.table)
            combo.addItem("(Skip this file)", None)
            for track_id, label, _artist in self._track_choices:
                combo.addItem(label, int(track_id))
            matched_track_id = item.get("matched_track_id")
            index = combo.findData(int(matched_track_id)) if matched_track_id else 0
            combo.setCurrentIndex(index if index >= 0 else 0)
            combo.currentIndexChanged.connect(
                lambda _index, row=row_index, source_combo=combo: self._update_row_artist(
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
            self.table.setItem(
                row_index,
                2,
                QTableWidgetItem(str(item.get("detected_artist") or "")),
            )
            self.table.setItem(
                row_index,
                3,
                QTableWidgetItem(str(item.get("matched_track_artist") or "")),
            )
            self.table.setItem(
                row_index,
                4,
                QTableWidgetItem(str(item.get("detected_title") or "")),
            )
            self.table.setItem(
                row_index,
                5,
                QTableWidgetItem(str(item.get("source_name") or "")),
            )
            self._update_row_artist(row_index, combo)
        self._refresh_summary()

    def _update_row_artist(self, row: int, combo: QComboBox) -> None:
        track_id = combo.currentData()
        artist_item = self.table.item(row, 3)
        if artist_item is None:
            artist_item = QTableWidgetItem("")
            self.table.setItem(row, 3, artist_item)
        if track_id in (None, ""):
            original_artist = self._items[row].get("matched_track_artist") or ""
            artist_item.setText(str(original_artist))
        else:
            artist_item.setText(
                str(self._track_choice_map.get(int(track_id), {}).get("artist") or "")
            )
        if len(self._match_combos) == len(self._items):
            self._refresh_summary()

    def _refresh_summary(self) -> None:
        if len(self._match_combos) < len(self._items):
            return
        matched = len(self.selected_matches())
        total = len(self._items)
        self.summary_label.setText(f"{matched} of {total} audio file(s) are queued for attachment.")

    def selected_matches(self) -> list[dict[str, object]]:
        matches: list[dict[str, object]] = []
        for row_index, item in enumerate(self._items):
            combo = self._match_combos[row_index]
            track_id = combo.currentData()
            if track_id in (None, ""):
                continue
            matches.append(
                {
                    "source_path": str(item.get("source_path") or ""),
                    "source_name": str(item.get("source_name") or ""),
                    "track_id": int(track_id),
                    "detected_artist": str(item.get("detected_artist") or ""),
                }
            )
        return matches

    def selected_artist_name(self) -> str | None:
        if not self.apply_artist_checkbox.isChecked():
            return None
        text = self.artist_edit.text().strip()
        return text or None

    def accept(self) -> None:
        matches = self.selected_matches()
        if not matches:
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

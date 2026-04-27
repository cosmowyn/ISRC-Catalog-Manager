from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QKeySequence, QShortcut, QTextCursor, QTextDocument
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from isrc_manager.blob_icons import BlobIconDialog, describe_blob_icon_spec
from isrc_manager.constants import DEFAULT_WINDOW_TITLE, FIELD_TYPE_CHOICES
from isrc_manager.external_launch import open_external_url
from isrc_manager.help_content import HELP_CHAPTERS_BY_ID, iter_help_sections
from isrc_manager.storage_sizes import format_storage_bytes
from isrc_manager.ui_common import (
    FocusWheelComboBox,
    _add_standard_dialog_header,
    _apply_compact_dialog_control_heights,
    _apply_standard_dialog_chrome,
    _compose_widget_stylesheet,
    _create_round_help_button,
    _create_scrollable_dialog_content,
    _create_standard_section,
)


class CustomColumnsDialog(QDialog):
    """
    Manage custom field definitions:
    - Add (name, type: text/dropdown/checkbox; options for dropdown)
    - Rename
    - Change type
    - Edit options (dropdown)
    - Remove
    """

    def __init__(self, fields, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Manage Custom Columns")
        self.setModal(True)
        self.resize(760, 560)
        self.setMinimumSize(680, 500)
        _apply_standard_dialog_chrome(self, "customColumnsDialog")

        # fields: [{"id": int|None, "name": str, "field_type": "...", "options": str|None,
        #           "blob_icon_payload": dict|None}]
        self.fields = [dict(f) for f in fields]

        self.listw = QListWidget()
        self.listw.setAlternatingRowColors(True)
        self.listw.setMinimumHeight(280)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)
        _add_standard_dialog_header(
            layout,
            self,
            title="Manage Custom Columns",
            subtitle="Create, rename, remove, and configure custom metadata fields used across the catalog.",
            help_topic_id="custom-columns",
        )

        list_box, list_layout = _create_standard_section(
            self,
            "Defined Columns",
            "Each custom column stores one metadata field for every track. Dropdown fields can keep a reusable list of choices.",
        )
        list_layout.addWidget(self.listw, 1)

        row1 = QHBoxLayout()
        row1.setSpacing(8)
        self.btn_add = QPushButton("Add…")
        self.btn_remove = QPushButton("Remove")
        self.btn_rename = QPushButton("Rename…")
        self.btn_type = QPushButton("Change Type…")
        self.btn_opts = QPushButton("Edit Options…")
        self.btn_blob_icon = QPushButton("Set BLOB Icon…")
        row1.addWidget(self.btn_add)
        row1.addWidget(self.btn_remove)
        row1.addWidget(self.btn_rename)
        row1.addWidget(self.btn_type)
        row1.addWidget(self.btn_opts)
        row1.addWidget(self.btn_blob_icon)
        row1.addStretch(1)
        list_layout.addLayout(row1)
        layout.addWidget(list_box, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, Qt.Horizontal, self
        )
        ok = buttons.button(QDialogButtonBox.Ok)
        cancel = buttons.button(QDialogButtonBox.Cancel)
        if ok is not None:
            ok.setDefault(True)
        if cancel is not None:
            cancel.setAutoDefault(False)
        layout.addWidget(buttons)

        self.btn_add.clicked.connect(self._add)
        self.btn_remove.clicked.connect(self._remove)
        self.btn_rename.clicked.connect(self._rename)
        self.btn_type.clicked.connect(self._change_type)
        self.btn_opts.clicked.connect(self._edit_options)
        self.btn_blob_icon.clicked.connect(self._edit_blob_icon)
        self.listw.currentRowChanged.connect(self._update_button_states)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        self._refresh_list()
        self._update_button_states()

    def _refresh_list(self):
        self.listw.clear()
        for index, field in enumerate(self.fields):
            label = f"{field['name']}  ·  {field.get('field_type', 'text')}"
            if field.get("field_type") in {"blob_audio", "blob_image"}:
                label += "  ·  " + describe_blob_icon_spec(
                    field.get("blob_icon_payload"),
                    kind="audio" if field.get("field_type") == "blob_audio" else "image",
                    allow_inherit=True,
                )
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, index)
            self.listw.addItem(item)
        self._update_button_states()

    def _current_index(self):
        item = self.listw.currentItem()
        return item.data(Qt.UserRole) if item else None

    def _current_field(self):
        index = self._current_index()
        return (self.fields[index] if index is not None else None), index

    def _update_button_states(self, *_args) -> None:
        current_field, _index = self._current_field()
        is_dropdown = current_field is not None and current_field.get("field_type") == "dropdown"
        is_blob = current_field is not None and current_field.get("field_type") in {
            "blob_audio",
            "blob_image",
        }
        self.btn_remove.setEnabled(current_field is not None)
        self.btn_rename.setEnabled(current_field is not None)
        self.btn_type.setEnabled(current_field is not None)
        self.btn_opts.setEnabled(is_dropdown)
        self.btn_blob_icon.setEnabled(is_blob)

    def _add(self):
        name, ok = QInputDialog.getText(self, "Add Column", "Column name:")
        name = (name or "").strip()
        if not (ok and name):
            return
        if any(field["name"] == name for field in self.fields):
            QMessageBox.warning(self, "Exists", f"Column '{name}' already exists.")
            return

        field_type, ok = QInputDialog.getItem(
            self, "Field Type", "Choose type:", FIELD_TYPE_CHOICES, 0, False
        )
        if not ok:
            return

        new_field = {
            "id": None,
            "name": name,
            "field_type": field_type,
            "options": None,
            "blob_icon_payload": None,
        }

        if field_type == "dropdown":
            options_text, options_ok = QInputDialog.getMultiLineText(
                self, "Dropdown Options", "Enter options (one per line):"
            )
            if options_ok:
                options = [
                    option.strip() for option in (options_text or "").splitlines() if option.strip()
                ]
                new_field["options"] = json.dumps(options) if options else json.dumps([])
        elif field_type in {"blob_audio", "blob_image"}:
            icon_dialog = BlobIconDialog(
                kind="audio" if field_type == "blob_audio" else "image",
                title=f"Default Icon for {name}",
                spec={"mode": "inherit"},
                allow_inherit=True,
                parent=self,
            )
            if icon_dialog.exec() == QDialog.Accepted:
                new_field["blob_icon_payload"] = icon_dialog.current_spec()

        self.fields.append(new_field)
        self._refresh_list()
        self.listw.setCurrentRow(self.listw.count() - 1)

    def _remove(self):
        index = self._current_index()
        if index is None:
            return

        current_field = self.fields[index]
        if (
            QMessageBox.question(
                self,
                "Remove Column",
                f"Are you sure you want to remove '{current_field['name']}'?",
                QMessageBox.Yes | QMessageBox.No,
            )
            != QMessageBox.Yes
        ):
            return

        del self.fields[index]
        self._refresh_list()
        if self.listw.count():
            self.listw.setCurrentRow(min(index, self.listw.count() - 1))

    def _rename(self):
        current_field, index = self._current_field()
        if current_field is None:
            return

        new_name, ok = QInputDialog.getText(
            self, "Rename Column", "New name:", text=current_field["name"]
        )
        new_name = (new_name or "").strip()
        if not (ok and new_name):
            return

        if any(
            position != index and field["name"] == new_name
            for position, field in enumerate(self.fields)
        ):
            QMessageBox.warning(self, "Exists", f"Column '{new_name}' already exists.")
            return

        self.fields[index]["name"] = new_name
        self._refresh_list()
        self.listw.setCurrentRow(index)

    def _change_type(self):
        current_field, index = self._current_field()
        if current_field is None:
            return

        current_choice = (
            FIELD_TYPE_CHOICES.index(current_field.get("field_type", "text"))
            if current_field.get("field_type", "text") in FIELD_TYPE_CHOICES
            else 0
        )
        field_type, ok = QInputDialog.getItem(
            self, "Change Field Type", "Choose type:", FIELD_TYPE_CHOICES, current_choice, False
        )
        if not ok:
            return

        self.fields[index]["field_type"] = field_type

        if field_type != "dropdown":
            self.fields[index]["options"] = None
        elif not self.fields[index].get("options"):
            options_text, options_ok = QInputDialog.getMultiLineText(
                self, "Dropdown Options", "Enter options (one per line):"
            )
            if options_ok:
                options = [
                    option.strip() for option in (options_text or "").splitlines() if option.strip()
                ]
                self.fields[index]["options"] = json.dumps(options) if options else json.dumps([])
        if field_type not in {"blob_audio", "blob_image"}:
            self.fields[index]["blob_icon_payload"] = None
        elif self.fields[index].get("blob_icon_payload") is None:
            self.fields[index]["blob_icon_payload"] = {"mode": "inherit"}

        self._refresh_list()
        self.listw.setCurrentRow(index)

    def _edit_options(self):
        current_field, index = self._current_field()
        if current_field is None or current_field.get("field_type") != "dropdown":
            return

        existing = json.loads(current_field.get("options") or "[]")
        default_lines = "\n".join(existing)

        options_text, ok = QInputDialog.getMultiLineText(
            self, "Dropdown Options", "Enter options (one per line):", text=default_lines
        )
        if not ok:
            return

        options = [option.strip() for option in (options_text or "").splitlines() if option.strip()]
        self.fields[index]["options"] = json.dumps(options)
        self._refresh_list()
        self.listw.setCurrentRow(index)

    def _edit_blob_icon(self):
        current_field, index = self._current_field()
        if current_field is None:
            return
        field_type = str(current_field.get("field_type") or "").strip().lower()
        if field_type not in {"blob_audio", "blob_image"}:
            return
        dialog = BlobIconDialog(
            kind="audio" if field_type == "blob_audio" else "image",
            title=f"Icon for {current_field['name']}",
            spec=current_field.get("blob_icon_payload") or {"mode": "inherit"},
            allow_inherit=True,
            parent=self,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        self.fields[index]["blob_icon_payload"] = dialog.current_spec()
        self._refresh_list()
        self.listw.setCurrentRow(index)

    def get_fields(self):
        return self.fields


class ActionRibbonDialog(QDialog):
    """Pick which existing app actions appear in the top quick-action ribbon."""

    def __init__(
        self,
        available_actions: list[dict],
        selected_action_ids: list[str],
        *,
        ribbon_visible: bool,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Customize Action Ribbon")
        self.setModal(True)
        self.resize(980, 620)
        self.setMinimumSize(860, 560)
        _apply_standard_dialog_chrome(self, "actionRibbonDialog")

        self.available_actions = [dict(spec) for spec in available_actions]
        self.available_by_id = {str(spec["id"]): spec for spec in self.available_actions}
        self.default_action_ids = [
            str(spec["id"]) for spec in self.available_actions if spec.get("default")
        ]

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)
        _add_standard_dialog_header(
            layout,
            self,
            title="Customize Action Ribbon",
            subtitle=(
                "Choose which existing menu actions appear in the top quick-action ribbon, "
                "then reorder them to match your workflow."
            ),
            help_topic_id="main-window",
        )

        visibility_box, visibility_layout = _create_standard_section(
            self,
            "Ribbon Visibility",
            "Hide the ribbon completely or keep it visible with your chosen quick actions.",
        )
        self.show_ribbon_checkbox = QCheckBox("Show action ribbon")
        self.show_ribbon_checkbox.setChecked(bool(ribbon_visible))
        visibility_layout.addWidget(self.show_ribbon_checkbox)
        layout.addWidget(visibility_box)

        content_row = QHBoxLayout()
        content_row.setSpacing(14)

        available_box, available_layout = _create_standard_section(
            self,
            "Available Actions",
            "Pick from the app's existing menu and quick actions. Double-click an action to add it.",
        )
        self.available_list = QListWidget()
        self.available_list.setAlternatingRowColors(True)
        self.available_list.setMinimumWidth(360)
        available_layout.addWidget(self.available_list, 1)
        content_row.addWidget(available_box, 1)

        middle_col = QVBoxLayout()
        middle_col.setSpacing(8)
        middle_col.addStretch(1)
        self.btn_add = QPushButton("Add ->")
        self.btn_remove = QPushButton("<- Remove")
        self.btn_up = QPushButton("Move Up")
        self.btn_down = QPushButton("Move Down")
        self.btn_reset = QPushButton("Reset Defaults")
        middle_col.addWidget(self.btn_add)
        middle_col.addWidget(self.btn_remove)
        middle_col.addSpacing(8)
        middle_col.addWidget(self.btn_up)
        middle_col.addWidget(self.btn_down)
        middle_col.addSpacing(8)
        middle_col.addWidget(self.btn_reset)
        middle_col.addStretch(1)
        content_row.addLayout(middle_col)

        selected_box, selected_layout = _create_standard_section(
            self,
            "Ribbon Order",
            "These actions appear left to right in the ribbon. Drag to reorder or use the move buttons.",
        )
        self.selected_list = QListWidget()
        self.selected_list.setAlternatingRowColors(True)
        self.selected_list.setDragDropMode(QAbstractItemView.InternalMove)
        self.selected_list.setDefaultDropAction(Qt.MoveAction)
        self.selected_list.setSelectionMode(QAbstractItemView.SingleSelection)
        selected_layout.addWidget(self.selected_list, 1)
        content_row.addWidget(selected_box, 1)

        layout.addLayout(content_row, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, Qt.Horizontal, self
        )
        ok = buttons.button(QDialogButtonBox.Ok)
        cancel = buttons.button(QDialogButtonBox.Cancel)
        if ok is not None:
            ok.setDefault(True)
        if cancel is not None:
            cancel.setAutoDefault(False)
        layout.addWidget(buttons)

        self.btn_add.clicked.connect(self._add_current_available_action)
        self.btn_remove.clicked.connect(self._remove_current_selected_action)
        self.btn_up.clicked.connect(lambda: self._move_selected_action(-1))
        self.btn_down.clicked.connect(lambda: self._move_selected_action(1))
        self.btn_reset.clicked.connect(self._reset_defaults)
        self.available_list.itemDoubleClicked.connect(
            lambda *_args: self._add_current_available_action()
        )
        self.selected_list.itemDoubleClicked.connect(
            lambda *_args: self._remove_current_selected_action()
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        self._populate_selected_list(selected_action_ids)
        self._refresh_available_list()
        _apply_compact_dialog_control_heights(self)

    def _selected_action_ids(self) -> list[str]:
        return [
            str(self.selected_list.item(row).data(Qt.UserRole))
            for row in range(self.selected_list.count())
            if self.selected_list.item(row) is not None
            and self.selected_list.item(row).data(Qt.UserRole)
        ]

    def _populate_selected_list(self, action_ids: list[str]) -> None:
        self.selected_list.clear()
        seen: set[str] = set()
        for action_id in action_ids:
            clean_id = str(action_id)
            if clean_id in seen or clean_id not in self.available_by_id:
                continue
            seen.add(clean_id)
            spec = self.available_by_id[clean_id]
            item = QListWidgetItem(str(spec["label"]))
            item.setData(Qt.UserRole, clean_id)
            item.setToolTip(self._tooltip_for_spec(spec))
            self.selected_list.addItem(item)

    def _tooltip_for_spec(self, spec: dict) -> str:
        shortcut_text = str(spec.get("shortcut") or "").strip()
        description = str(spec.get("description") or "").strip()
        parts = [str(spec.get("category") or "Action"), description]
        if shortcut_text:
            parts.append(f"Shortcut: {shortcut_text}")
        return "\n".join(part for part in parts if part)

    def _refresh_available_list(self) -> None:
        current_action_id = None
        current_item = self.available_list.currentItem()
        if current_item is not None and current_item.data(Qt.UserRole):
            current_action_id = str(current_item.data(Qt.UserRole))

        selected_ids = set(self._selected_action_ids())
        self.available_list.clear()
        for spec in self.available_actions:
            action_id = str(spec["id"])
            label = f"{spec['category']} / {spec['label']}"
            shortcut_text = str(spec.get("shortcut") or "").strip()
            if shortcut_text:
                label += f"  [{shortcut_text}]"
            if action_id in selected_ids:
                label += "  (Added)"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, action_id)
            item.setToolTip(self._tooltip_for_spec(spec))
            self.available_list.addItem(item)
            if action_id == current_action_id:
                self.available_list.setCurrentItem(item)

    def _add_current_available_action(self) -> None:
        current_item = self.available_list.currentItem()
        if current_item is None:
            return
        action_id = str(current_item.data(Qt.UserRole) or "")
        if not action_id or action_id in set(self._selected_action_ids()):
            return
        spec = self.available_by_id.get(action_id)
        if spec is None:
            return
        item = QListWidgetItem(str(spec["label"]))
        item.setData(Qt.UserRole, action_id)
        item.setToolTip(self._tooltip_for_spec(spec))
        self.selected_list.addItem(item)
        self.selected_list.setCurrentItem(item)
        self._refresh_available_list()

    def _remove_current_selected_action(self) -> None:
        current_row = self.selected_list.currentRow()
        if current_row < 0:
            return
        removed_item = self.selected_list.takeItem(current_row)
        removed_action_id = (
            str(removed_item.data(Qt.UserRole) or "") if removed_item is not None else ""
        )
        del removed_item
        if self.selected_list.count():
            self.selected_list.setCurrentRow(min(current_row, self.selected_list.count() - 1))
        self._refresh_available_list()
        if removed_action_id:
            for row in range(self.available_list.count()):
                item = self.available_list.item(row)
                if item is not None and str(item.data(Qt.UserRole) or "") == removed_action_id:
                    self.available_list.setCurrentRow(row)
                    break

    def _move_selected_action(self, delta: int) -> None:
        current_row = self.selected_list.currentRow()
        if current_row < 0:
            return
        target_row = current_row + int(delta)
        if target_row < 0 or target_row >= self.selected_list.count():
            return
        item = self.selected_list.takeItem(current_row)
        self.selected_list.insertItem(target_row, item)
        self.selected_list.setCurrentRow(target_row)

    def _reset_defaults(self) -> None:
        self._populate_selected_list(self.default_action_ids)
        if self.selected_list.count():
            self.selected_list.setCurrentRow(0)
        self._refresh_available_list()

    def selected_action_ids(self) -> list[str]:
        return self._selected_action_ids()

    def ribbon_visible(self) -> bool:
        return self.show_ribbon_checkbox.isChecked()


class MasterTransferExportDialog(QDialog):
    """Review exportable master transfer sections before writing the ZIP package."""

    def __init__(self, sections, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Export Master Catalog Transfer")
        self.setModal(True)
        self.resize(980, 680)
        self.setMinimumSize(860, 560)
        _apply_standard_dialog_chrome(self, "masterTransferExportDialog")

        self._table_updating = False
        self.sections = [self._normalize_section(section) for section in list(sections or [])]
        self._sections_by_id = {
            str(section["section_id"]): section
            for section in self.sections
            if section["section_id"]
        }
        self._requested_selected = {
            str(section["section_id"]): bool(section.get("default_selected", True))
            for section in self.sections
            if section["section_id"]
        }

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)
        _add_standard_dialog_header(
            layout,
            self,
            title="Export Master Catalog Transfer",
            subtitle=(
                "Review the logical sections that will be packaged into the transfer ZIP. "
                "Everything starts selected, and dependent sections stay linked to the "
                "sections they require."
            ),
        )

        selection_box, selection_layout = _create_standard_section(
            self,
            "Section Selection",
            "Uncheck any section you do not want to include. If a section depends on another "
            "section, it is disabled automatically until the required section is selected again.",
        )
        self.section_table = QTableWidget(len(self.sections), 4, self)
        self.section_table.setHorizontalHeaderLabels(
            ["Include", "Section", "Contents", "Requirements"]
        )
        self.section_table.verticalHeader().setVisible(False)
        self.section_table.setAlternatingRowColors(True)
        self.section_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.section_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.section_table.horizontalHeader().setStretchLastSection(True)
        self.section_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.section_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.section_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.section_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        selection_layout.addWidget(self.section_table, 1)
        layout.addWidget(selection_box, 1)

        self.selection_status_label = QLabel(self)
        self.selection_status_label.setWordWrap(True)
        self.selection_status_label.setProperty("role", "secondary")
        layout.addWidget(self.selection_status_label)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self.export_button = QPushButton("Export ZIP", self)
        self.export_button.setDefault(True)
        self.export_button.clicked.connect(self.accept)
        cancel_button = QPushButton("Cancel", self)
        cancel_button.clicked.connect(self.reject)
        button_row.addWidget(self.export_button)
        button_row.addWidget(cancel_button)
        layout.addLayout(button_row)

        self._populate_section_table()
        self.section_table.itemChanged.connect(self._on_item_changed)
        self._refresh_dependency_states()
        _apply_compact_dialog_control_heights(self)

    @staticmethod
    def _normalize_section(section) -> dict[str, object]:
        if isinstance(section, dict):
            payload = dict(section)
        else:
            payload = {
                "section_id": getattr(section, "section_id", ""),
                "label": getattr(section, "label", ""),
                "description": getattr(section, "description", ""),
                "dependency_note": getattr(section, "dependency_note", ""),
                "depends_on": list(getattr(section, "depends_on", []) or []),
                "entity_counts": dict(getattr(section, "entity_counts", {}) or {}),
                "default_selected": bool(getattr(section, "default_selected", True)),
            }
        return {
            "section_id": str(payload.get("section_id") or "").strip(),
            "label": str(payload.get("label") or "").strip() or "Unnamed Section",
            "description": str(payload.get("description") or "").strip(),
            "dependency_note": str(payload.get("dependency_note") or "").strip(),
            "depends_on": [
                str(value or "").strip() for value in list(payload.get("depends_on") or [])
            ],
            "entity_counts": {
                str(key): int(value or 0)
                for key, value in dict(payload.get("entity_counts") or {}).items()
            },
            "default_selected": bool(payload.get("default_selected", True)),
        }

    @staticmethod
    def _counts_text(counts: dict[str, int]) -> str:
        visible_counts = [
            f"{str(key).replace('_', ' ')}={int(value or 0)}"
            for key, value in counts.items()
            if int(value or 0) > 0
        ]
        return ", ".join(visible_counts) if visible_counts else "No rows found"

    def _effective_selected(self, section_id: str, *, memo: dict[str, bool] | None = None) -> bool:
        if memo is None:
            memo = {}
        clean_id = str(section_id or "").strip()
        if clean_id in memo:
            return memo[clean_id]
        if not self._requested_selected.get(clean_id, False):
            memo[clean_id] = False
            return False
        section = self._sections_by_id.get(clean_id)
        if section is None:
            memo[clean_id] = False
            return False
        for dependency_id in section.get("depends_on") or []:
            if not self._effective_selected(str(dependency_id), memo=memo):
                memo[clean_id] = False
                return False
        memo[clean_id] = True
        return True

    def _populate_section_table(self) -> None:
        self._table_updating = True
        try:
            for row_index, section in enumerate(self.sections):
                include_item = QTableWidgetItem()
                include_item.setData(Qt.UserRole, str(section["section_id"]))
                include_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
                include_item.setCheckState(
                    Qt.Checked if bool(section.get("default_selected", True)) else Qt.Unchecked
                )
                self.section_table.setItem(row_index, 0, include_item)

                section_item = QTableWidgetItem(str(section["label"]))
                section_item.setToolTip(str(section.get("description") or ""))
                self.section_table.setItem(row_index, 1, section_item)

                contents_item = QTableWidgetItem(
                    self._counts_text(dict(section.get("entity_counts") or {}))
                )
                contents_item.setToolTip(contents_item.text())
                self.section_table.setItem(row_index, 2, contents_item)

                requirements_item = QTableWidgetItem()
                self.section_table.setItem(row_index, 3, requirements_item)
        finally:
            self._table_updating = False

    def _on_item_changed(self, item: QTableWidgetItem | None) -> None:
        if item is None or self._table_updating or item.column() != 0:
            return
        section_id = str(item.data(Qt.UserRole) or "").strip()
        if not section_id:
            return
        self._requested_selected[section_id] = item.checkState() == Qt.Checked
        self._refresh_dependency_states()

    def _refresh_dependency_states(self) -> None:
        memo: dict[str, bool] = {}
        effective_selection = {
            str(section["section_id"]): self._effective_selected(
                str(section["section_id"]),
                memo=memo,
            )
            for section in self.sections
        }
        self._table_updating = True
        try:
            for row_index, section in enumerate(self.sections):
                section_id = str(section["section_id"])
                include_item = self.section_table.item(row_index, 0)
                requirements_item = self.section_table.item(row_index, 3)
                if include_item is None or requirements_item is None:
                    continue

                blocked_dependencies = [
                    str(self._sections_by_id.get(dep, {}).get("label") or dep)
                    for dep in list(section.get("depends_on") or [])
                    if not effective_selection.get(str(dep), False)
                ]
                flags = Qt.ItemIsEnabled
                if not blocked_dependencies:
                    flags |= Qt.ItemIsUserCheckable
                include_item.setFlags(flags)
                include_item.setCheckState(
                    Qt.Checked if effective_selection.get(section_id, False) else Qt.Unchecked
                )

                if blocked_dependencies:
                    requirements_item.setText("Requires: " + ", ".join(blocked_dependencies))
                elif section.get("depends_on"):
                    requirements_item.setText(
                        "Requires: "
                        + ", ".join(
                            str(self._sections_by_id.get(dep, {}).get("label") or dep)
                            for dep in list(section.get("depends_on") or [])
                        )
                    )
                else:
                    requirements_item.setText("No prerequisites")
                tooltip_lines = [
                    str(section.get("description") or "").strip(),
                    str(section.get("dependency_note") or "").strip(),
                    requirements_item.text(),
                ]
                requirements_item.setToolTip("\n".join(line for line in tooltip_lines if line))
        finally:
            self._table_updating = False

        selected_labels = [
            str(section.get("label") or "")
            for section in self.sections
            if effective_selection.get(str(section["section_id"]), False)
        ]
        self.export_button.setEnabled(bool(selected_labels))
        if selected_labels:
            self.selection_status_label.setText("Selected sections: " + ", ".join(selected_labels))
        else:
            self.selection_status_label.setText(
                "Select at least one section to create a master transfer package."
            )

    def selected_section_ids(self) -> list[str]:
        memo: dict[str, bool] = {}
        return [
            str(section["section_id"])
            for section in self.sections
            if self._effective_selected(str(section["section_id"]), memo=memo)
        ]


class ApplicationLogDialog(QDialog):
    def __init__(self, app, parent=None):
        super().__init__(parent or app)
        self.app = app
        self.setObjectName("applicationLogDialog")
        self.setProperty("role", "panel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setWindowTitle("Application Log")
        self.resize(860, 700)
        self.setMinimumSize(720, 560)
        _apply_standard_dialog_chrome(self, "applicationLogDialog")
        self.setStyleSheet(
            _compose_widget_stylesheet(
                self,
                """
                QDialog#applicationLogDialog QLabel#logTitle {
                    font-size: 28px;
                    font-weight: 700;
                }
                QDialog#applicationLogDialog QLabel#logSubtitle {
                    font-size: 15px;
                }
                QDialog#applicationLogDialog QGroupBox {
                    font-size: 16px;
                    font-weight: 600;
                    margin-top: 8px;
                }
                QDialog#applicationLogDialog QGroupBox::title {
                    left: 10px;
                    padding: 0 6px;
                }
                QDialog#applicationLogDialog QLabel[role="meta"] {
                }
                """,
            )
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        help_row = QHBoxLayout()
        help_row.addStretch(1)
        help_row.addWidget(_create_round_help_button(self, "application-log"))
        root.addLayout(help_row)

        title = QLabel("Application Log")
        title.setObjectName("logTitle")
        title.setProperty("role", "dialogTitle")
        subtitle = QLabel(
            "Review the live application logs, open archived log files, and jump straight to the log folder."
        )
        subtitle.setObjectName("logSubtitle")
        subtitle.setProperty("role", "dialogSubtitle")
        subtitle.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(subtitle)

        source_group = QGroupBox("Application Log")
        source_layout = QFormLayout(source_group)
        source_layout.setContentsMargins(14, 18, 14, 14)
        source_layout.setHorizontalSpacing(14)
        source_layout.setVerticalSpacing(10)
        source_layout.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.log_combo = FocusWheelComboBox()
        self.log_combo.setMinimumContentsLength(28)
        self.log_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        source_layout.addRow("Log file", self.log_combo)

        self.log_path_label = QLabel()
        self.log_path_label.setProperty("role", "meta")
        self.log_path_label.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard
        )
        self.log_path_label.setWordWrap(True)
        source_layout.addRow("Path", self.log_path_label)
        root.addWidget(source_group)

        contents_group = QGroupBox("Log Contents")
        contents_layout = QVBoxLayout(contents_group)
        contents_layout.setContentsMargins(14, 18, 14, 14)
        contents_layout.setSpacing(12)

        button_row = QHBoxLayout()
        button_row.setSpacing(10)
        self.refresh_button = QPushButton("Refresh")
        self.open_file_button = QPushButton("Open File")
        self.open_folder_button = QPushButton("Open Log Folder")
        for button in (self.refresh_button, self.open_file_button, self.open_folder_button):
            button.setMinimumWidth(134)
            button_row.addWidget(button)
        button_row.addStretch(1)
        contents_layout.addLayout(button_row)

        self.contents_edit = QPlainTextEdit(self)
        self.contents_edit.setReadOnly(True)
        self.contents_edit.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.contents_edit.setMinimumHeight(360)
        contents_layout.addWidget(self.contents_edit, 1)
        root.addWidget(contents_group, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close, Qt.Horizontal, self)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.log_combo.currentIndexChanged.connect(self._load_selected_log)
        self.refresh_button.clicked.connect(self.refresh)
        self.open_file_button.clicked.connect(self._open_selected_log)
        self.open_folder_button.clicked.connect(
            lambda: self.app._open_local_path(self.app.logs_dir, "Open Log Folder")
        )

        self.refresh()
        _apply_compact_dialog_control_heights(self)

    def refresh(self):
        current_path = self.log_combo.currentData()
        log_files = self.app._available_log_files()

        self.log_combo.blockSignals(True)
        self.log_combo.clear()
        for path in log_files:
            stamp = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            kind = "Trace log" if ".jsonl" in path.name else "Application log"
            self.log_combo.addItem(f"{kind}: {path.name}    {stamp}", str(path))
        self.log_combo.blockSignals(False)

        if not log_files:
            self.log_path_label.setText("No log files found in the application log folder.")
            self.contents_edit.setPlainText("No log files are available yet.")
            self.open_file_button.setEnabled(False)
            return

        target_index = 0
        if current_path:
            for index in range(self.log_combo.count()):
                if self.log_combo.itemData(index) == current_path:
                    target_index = index
                    break

        self.open_file_button.setEnabled(True)
        self.log_combo.setCurrentIndex(target_index)
        self._load_selected_log()

    def _selected_log_path(self) -> Path | None:
        data = self.log_combo.currentData()
        return Path(data) if data else None

    def _load_selected_log(self):
        path = self._selected_log_path()
        if path is None:
            self.log_path_label.setText("No log file selected.")
            self.contents_edit.setPlainText("")
            self.open_file_button.setEnabled(False)
            return

        self.log_path_label.setText(str(path))
        self.open_file_button.setEnabled(path.exists())
        text = self.app._read_log_for_viewer(path)
        self.contents_edit.setPlainText(text)
        self.contents_edit.verticalScrollBar().setValue(0)

    def _open_selected_log(self):
        path = self._selected_log_path()
        if path is not None:
            self.app._open_local_path(path, "Open Log File")


class DiagnosticsDialog(QDialog):
    def __init__(self, app, parent=None):
        super().__init__(parent or app)
        self.app = app
        self._checks = []
        self._busy = False
        self.setObjectName("diagnosticsDialog")
        self.setProperty("role", "panel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setWindowTitle("Diagnostics")
        self.resize(1080, 780)
        self.setMinimumSize(980, 680)
        _apply_standard_dialog_chrome(self, "diagnosticsDialog")
        self.setStyleSheet(
            _compose_widget_stylesheet(
                self,
                """
                QDialog#diagnosticsDialog QLabel#diagnosticsTitle {
                    font-size: 28px;
                    font-weight: 700;
                }
                QDialog#diagnosticsDialog QLabel#diagnosticsSubtitle {
                    font-size: 15px;
                }
                QDialog#diagnosticsDialog QGroupBox {
                    font-size: 16px;
                    font-weight: 600;
                    margin-top: 8px;
                }
                QDialog#diagnosticsDialog QGroupBox::title {
                    left: 10px;
                    padding: 0 6px;
                }
                """,
            )
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        help_row = QHBoxLayout()
        help_row.addStretch(1)
        help_row.addWidget(_create_round_help_button(self, "diagnostics"))
        root.addLayout(help_row)

        title = QLabel("Diagnostics")
        title.setObjectName("diagnosticsTitle")
        title.setProperty("role", "dialogTitle")
        subtitle = QLabel(
            "Inspect the current profile, schema, and managed files to quickly spot anything that needs attention."
        )
        subtitle.setObjectName("diagnosticsSubtitle")
        subtitle.setProperty("role", "dialogSubtitle")
        subtitle.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(subtitle)

        self.loading_panel = QWidget(self)
        loading_row = QHBoxLayout(self.loading_panel)
        loading_row.setContentsMargins(0, 0, 0, 0)
        loading_row.setSpacing(10)
        self.loading_bar = QProgressBar(self)
        self.loading_bar.setRange(0, 100)
        self.loading_bar.setValue(0)
        self.loading_bar.setTextVisible(True)
        self.loading_bar.setFormat("%p%")
        self.loading_bar.setMinimumWidth(220)
        self.loading_status_label = QLabel("Loading diagnostics...")
        self.loading_status_label.setWordWrap(True)
        self._loading_progress_value = 0
        self._loading_progress_maximum = 100
        self._loading_status_message = "Loading diagnostics..."
        loading_row.addWidget(self.loading_bar)
        loading_row.addWidget(self.loading_status_label, 1)
        self.loading_panel.hide()
        root.addWidget(self.loading_panel)

        self.surface_tabs = QTabWidget(self)
        self.surface_tabs.setDocumentMode(True)
        root.addWidget(self.surface_tabs, 1)

        self.body_scroll, _, body_layout = _create_scrollable_dialog_content(self)
        self.surface_tabs.addTab(self.body_scroll, "Health")

        self.catalog_cleanup_panel = None
        build_cleanup_panel = getattr(self.app, "_create_diagnostics_catalog_cleanup_panel", None)
        if callable(build_cleanup_panel):
            try:
                cleanup_panel = build_cleanup_panel(self)
            except Exception:
                cleanup_panel = None
            if isinstance(cleanup_panel, QWidget):
                self.catalog_cleanup_panel = cleanup_panel
                self.surface_tabs.addTab(cleanup_panel, "Catalog Cleanup")

        self.history_storage_group = QGroupBox("History Storage")
        storage_layout = QVBoxLayout(self.history_storage_group)
        storage_layout.setContentsMargins(14, 18, 14, 14)
        storage_layout.setSpacing(12)
        self.history_storage_summary_label = QLabel(self.history_storage_group)
        self.history_storage_summary_label.setWordWrap(True)
        self.history_storage_summary_label.setProperty("role", "supportingText")
        storage_layout.addWidget(self.history_storage_summary_label)

        metrics_layout = QGridLayout()
        metrics_layout.setHorizontalSpacing(18)
        metrics_layout.setVerticalSpacing(8)
        self.history_storage_metric_labels = {}
        for row, (metric_key, title_text) in enumerate(
            (
                ("usage", "Current usage"),
                ("budget", "Budget"),
                ("over_budget", "Over budget"),
                ("reclaimable", "Safe reclaimable"),
                ("retention", "Retention level"),
                ("auto_cleanup", "Automatic cleanup"),
            )
        ):
            title_label = QLabel(title_text, self.history_storage_group)
            title_label.setAlignment(Qt.AlignRight | Qt.AlignTop)
            value_label = QLabel("Not available", self.history_storage_group)
            value_label.setTextInteractionFlags(
                Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard
            )
            value_label.setWordWrap(True)
            metrics_layout.addWidget(title_label, row, 0, alignment=Qt.AlignRight | Qt.AlignTop)
            metrics_layout.addWidget(value_label, row, 1)
            self.history_storage_metric_labels[metric_key] = value_label
        metrics_layout.setColumnStretch(1, 1)
        storage_layout.addLayout(metrics_layout)

        storage_actions = QHBoxLayout()
        storage_actions.setContentsMargins(0, 0, 0, 0)
        storage_actions.setSpacing(10)
        self.open_cleanup_button = QPushButton("Open History Cleanup…", self.history_storage_group)
        self.open_cleanup_button.clicked.connect(self._open_history_cleanup)
        storage_actions.addWidget(self.open_cleanup_button)
        storage_actions.addStretch(1)
        storage_layout.addLayout(storage_actions)
        body_layout.addWidget(self.history_storage_group)

        self.application_storage_group = QGroupBox("Application Storage")
        app_storage_layout = QVBoxLayout(self.application_storage_group)
        app_storage_layout.setContentsMargins(14, 18, 14, 14)
        app_storage_layout.setSpacing(12)
        self.application_storage_summary_label = QLabel(self.application_storage_group)
        self.application_storage_summary_label.setWordWrap(True)
        self.application_storage_summary_label.setProperty("role", "supportingText")
        app_storage_layout.addWidget(self.application_storage_summary_label)

        app_metrics_layout = QGridLayout()
        app_metrics_layout.setHorizontalSpacing(18)
        app_metrics_layout.setVerticalSpacing(8)
        self.application_storage_metric_labels = {}
        for row, (metric_key, title_text) in enumerate(
            (
                ("total", "Total app usage"),
                ("current_profile", "Current profile attributed"),
                ("reclaimable", "Reclaimable now"),
                ("deleted_profiles", "Deleted-profile residue"),
                ("orphaned", "Orphaned / unreferenced"),
                ("warnings", "Warning / protected"),
            )
        ):
            title_label = QLabel(title_text, self.application_storage_group)
            title_label.setAlignment(Qt.AlignRight | Qt.AlignTop)
            value_label = QLabel("Not available", self.application_storage_group)
            value_label.setTextInteractionFlags(
                Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard
            )
            value_label.setWordWrap(True)
            app_metrics_layout.addWidget(title_label, row, 0, alignment=Qt.AlignRight | Qt.AlignTop)
            app_metrics_layout.addWidget(value_label, row, 1)
            self.application_storage_metric_labels[metric_key] = value_label
        app_metrics_layout.setColumnStretch(1, 1)
        app_storage_layout.addLayout(app_metrics_layout)

        app_storage_actions = QHBoxLayout()
        app_storage_actions.setContentsMargins(0, 0, 0, 0)
        app_storage_actions.setSpacing(10)
        self.open_storage_admin_button = QPushButton(
            "Open Application Storage Admin…",
            self.application_storage_group,
        )
        self.open_storage_admin_button.clicked.connect(self._open_application_storage_admin)
        app_storage_actions.addWidget(self.open_storage_admin_button)
        app_storage_actions.addStretch(1)
        app_storage_layout.addLayout(app_storage_actions)
        body_layout.addWidget(self.application_storage_group)

        self.environment_group = QGroupBox("Environment")
        env_layout = QGridLayout(self.environment_group)
        env_layout.setContentsMargins(14, 18, 14, 14)
        env_layout.setHorizontalSpacing(18)
        env_layout.setVerticalSpacing(10)
        env_layout.setColumnMinimumWidth(0, 190)
        self.environment_labels = {}
        self.environment_name_labels = {}
        for row, key in enumerate(
            (
                "App version",
                "Schema version",
                "Current profile",
                "Database path",
                "Data folder",
                "Log folder",
                "Restore points",
                "Platform",
                "Python",
            )
        ):
            name_label = QLabel(key)
            name_label.setAlignment(Qt.AlignRight | Qt.AlignTop)
            name_label.setMinimumWidth(190)
            name_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.MinimumExpanding)
            label = QLabel()
            label.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
            label.setWordWrap(True)
            label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
            label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.MinimumExpanding)
            env_layout.addWidget(name_label, row, 0, alignment=Qt.AlignRight | Qt.AlignTop)
            env_layout.addWidget(label, row, 1)
            self.environment_name_labels[key] = name_label
            self.environment_labels[key] = label
        env_layout.setColumnStretch(1, 1)
        body_layout.addWidget(self.environment_group)

        checks_group = QGroupBox("Checks")
        checks_layout = QVBoxLayout(checks_group)
        checks_layout.setContentsMargins(14, 18, 14, 14)
        checks_layout.setSpacing(12)
        self.checks_list = QListWidget(self)
        self.checks_list.setMinimumHeight(180)
        checks_layout.addWidget(self.checks_list, 1)
        body_layout.addWidget(checks_group)

        details_group = QGroupBox("Details")
        details_layout = QVBoxLayout(details_group)
        details_layout.setContentsMargins(14, 18, 14, 14)
        self.details_edit = QPlainTextEdit(self)
        self.details_edit.setReadOnly(True)
        self.details_edit.setMinimumHeight(160)
        details_layout.addWidget(self.details_edit)
        body_layout.addWidget(details_group)
        body_layout.addStretch(1)

        button_row = QHBoxLayout()
        button_row.setSpacing(10)
        self.refresh_button = QPushButton("Refresh")
        self.preview_repair_button = QPushButton("Preview Repair")
        self.repair_button = QPushButton("Repair Issue")
        self.open_logs_button = QPushButton("Open Log Folder")
        self.open_data_button = QPushButton("Open Data Folder")
        self.close_button = QPushButton("Close")
        for button in (
            self.refresh_button,
            self.preview_repair_button,
            self.repair_button,
            self.open_logs_button,
            self.open_data_button,
            self.close_button,
        ):
            button.setMinimumWidth(140)
        button_row.addWidget(self.refresh_button)
        button_row.addWidget(self.preview_repair_button)
        button_row.addWidget(self.repair_button)
        button_row.addWidget(self.open_logs_button)
        button_row.addWidget(self.open_data_button)
        button_row.addStretch(1)
        button_row.addWidget(self.close_button)
        root.addLayout(button_row)

        self.refresh_button.clicked.connect(self.refresh)
        self.preview_repair_button.clicked.connect(self._preview_selected_repair)
        self.repair_button.clicked.connect(self._run_selected_repair)
        self.open_logs_button.clicked.connect(
            lambda: self.app._open_local_path(self.app.logs_dir, "Open Log Folder")
        )
        self.open_data_button.clicked.connect(
            lambda: self.app._open_local_path(self.app.data_root, "Open Data Folder")
        )
        self.close_button.clicked.connect(self.accept)
        self.checks_list.currentRowChanged.connect(self._show_selected_check)

        self.refresh()
        _apply_compact_dialog_control_heights(self)
        self._sync_loading_panel_metrics()

    def refresh(self):
        if self._busy:
            return
        if hasattr(self.app, "_load_diagnostics_report_async"):
            self._set_busy(True, "Loading diagnostics...")
            self.app._load_diagnostics_report_async(
                owner=self,
                on_success=self._populate_loaded_report,
                on_error=lambda failure: self._handle_background_error(
                    "Diagnostics",
                    failure,
                    "Could not load diagnostics.",
                ),
                on_cancelled=self._handle_background_cancelled,
                on_finished=self._finish_loaded_report,
                on_progress=self._apply_busy_progress,
                on_status=self._set_busy_message,
            )
            return
        report = self.app._build_diagnostics_report()
        self._apply_loaded_report(report)

    def _apply_loaded_report(self, report: dict):
        self._populate_loaded_report(report)
        self._finish_loaded_report()

    def _populate_loaded_report(self, report: dict):
        for key, value in report["environment"].items():
            label = self.environment_labels.get(key)
            if label is not None:
                label.setText(value)
        self._apply_history_storage_budget(report.get("history_storage_budget") or {})
        self._apply_application_storage_summary(report.get("application_storage") or {})
        self._sync_environment_label_metrics()

        self._checks = list(report["checks"])
        self.checks_list.blockSignals(True)
        self.checks_list.clear()
        for check in self._checks:
            status = check["status"].upper()
            self.checks_list.addItem(f"[{status}] {check['title']}: {check['summary']}")
        self.checks_list.blockSignals(False)

        if self._checks:
            self.checks_list.setCurrentRow(0)
            self._show_selected_check(0)
        else:
            self.details_edit.setPlainText("No diagnostics are available for the current profile.")
            self._update_repair_buttons(None)
        refresh_cleanup = getattr(self.catalog_cleanup_panel, "refresh", None)
        if callable(refresh_cleanup):
            refresh_cleanup()

    def _finish_loaded_report(self) -> None:
        if self._busy:
            self._set_busy(False)

    def focus_cleanup_tab(self, tab_name: str = "artists") -> None:
        if self.catalog_cleanup_panel is None:
            return
        cleanup_index = self.surface_tabs.indexOf(self.catalog_cleanup_panel)
        if cleanup_index >= 0:
            self.surface_tabs.setCurrentIndex(cleanup_index)
        focus_tab = getattr(self.catalog_cleanup_panel, "focus_tab", None)
        if callable(focus_tab):
            focus_tab(tab_name)

    def _apply_history_storage_budget(self, payload: dict[str, object]) -> None:
        available = bool(payload.get("available"))
        summary = str(payload.get("summary") or "").strip()
        self.history_storage_summary_label.setText(
            summary
            or (
                "History storage information is not available for the current profile."
                if not available
                else ""
            )
        )
        mapping = {
            "usage": str(payload.get("usage_text") or "Not available"),
            "budget": str(payload.get("budget_text") or "Not available"),
            "over_budget": str(payload.get("over_budget_text") or "Not available"),
            "reclaimable": str(payload.get("reclaimable_text") or "Not available"),
            "retention": str(payload.get("retention_mode_label") or "Not available"),
            "auto_cleanup": str(payload.get("auto_cleanup_text") or "Not available"),
        }
        for key, label in self.history_storage_metric_labels.items():
            label.setText(mapping.get(key, "Not available"))
        self.open_cleanup_button.setEnabled(
            callable(getattr(self.app, "open_history_cleanup_dialog", None))
        )

    def _set_busy(self, busy: bool, message: str | None = None) -> None:
        self._busy = bool(busy)
        if self._busy:
            self._loading_progress_value = 0
            self._loading_progress_maximum = 100
            self._loading_status_message = str(message or "Working...")
            self.loading_panel.show()
            self.loading_bar.setRange(0, self._loading_progress_maximum)
            self.loading_bar.setValue(0)
            self.loading_bar.setFormat("%p%")
            self._set_busy_message(self._loading_status_message)
        else:
            self.loading_panel.hide()
            self.loading_bar.setRange(0, 100)
            self.loading_bar.setValue(0)
            self.loading_bar.setFormat("%p%")
            self._loading_progress_value = 0
            self._loading_progress_maximum = 100
            self._loading_status_message = ""
            self.loading_status_label.setText("")
        for widget in (
            self.refresh_button,
            self.preview_repair_button,
            self.repair_button,
            self.open_logs_button,
            self.open_data_button,
            self.close_button,
            self.checks_list,
            self.open_cleanup_button,
            self.open_storage_admin_button,
        ):
            widget.setEnabled(not self._busy)
        if not self._busy:
            self.open_cleanup_button.setEnabled(
                callable(getattr(self.app, "open_history_cleanup_dialog", None))
            )
            self.open_storage_admin_button.setEnabled(
                callable(getattr(self.app, "open_application_storage_admin_dialog", None))
            )
        self._sync_loading_panel_metrics()
        self._update_repair_buttons(self._selected_check())

    def _set_busy_message(self, message: str) -> None:
        self._loading_status_message = str(message or "Working...")
        self.loading_status_label.setText(self._loading_status_message)

    def _apply_busy_progress(self, update: object) -> None:
        value = getattr(update, "value", None)
        maximum = getattr(update, "maximum", None)
        message = getattr(update, "message", None)
        if maximum not in (None, 0):
            self._loading_progress_maximum = max(1, int(maximum))
        if value is not None:
            self._loading_progress_value = max(
                0,
                min(self._loading_progress_maximum, int(value)),
            )
        self.loading_bar.setRange(0, self._loading_progress_maximum)
        self.loading_bar.setValue(self._loading_progress_value)
        self.loading_bar.setFormat("%p%")
        self._set_busy_message(str(message or self._loading_status_message or "Working..."))

    def _handle_background_cancelled(self) -> None:
        self._set_busy(False)
        self.details_edit.setPlainText("The diagnostics task was cancelled.")

    def _handle_background_error(self, title: str, failure, user_message: str) -> None:
        self._set_busy(False)
        if hasattr(self.app, "_show_background_task_error"):
            self.app._show_background_task_error(title, failure, user_message=user_message)
            return
        message = str(getattr(failure, "message", failure) or "Unknown error.")
        QMessageBox.critical(self, title, f"{user_message}\n{message}")

    def _show_selected_check(self, row: int):
        if row < 0 or row >= len(self._checks):
            self.details_edit.setPlainText("")
            self._update_repair_buttons(None)
            return
        check = self._checks[row]
        text = f"{check['title']}\nStatus: {check['status']}\n\n{check['details']}"
        self.details_edit.setPlainText(text)
        self._update_repair_buttons(check)

    def _sync_environment_label_metrics(self):
        viewport = self.body_scroll.viewport()
        viewport_width = (
            viewport.width() if viewport is not None else self.environment_group.width()
        )
        available_width = max(420, viewport_width - 320)
        for key, label in self.environment_labels.items():
            label.setFixedWidth(available_width)
            label.adjustSize()
            label.setMinimumHeight(max(label.sizeHint().height(), label.fontMetrics().height() + 8))
            name_label = self.environment_name_labels.get(key)
            if name_label is not None:
                name_label.setMinimumHeight(label.minimumHeight())

    def _sync_loading_panel_metrics(self):
        available_width = max(560, self.width() - 72)
        bar_width = max(220, min(320, int(available_width * 0.24)))
        self.loading_bar.setFixedWidth(bar_width)
        self.loading_status_label.setMinimumWidth(max(260, available_width - bar_width - 32))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_loading_panel_metrics()
        self._sync_environment_label_metrics()

    def _open_history_cleanup(self) -> None:
        opener = getattr(self.app, "open_history_cleanup_dialog", None)
        if callable(opener):
            opener()

    def _apply_application_storage_summary(self, payload: dict[str, object]) -> None:
        available = bool(payload.get("available"))
        summary = str(payload.get("summary") or "").strip()
        if not summary and not available:
            summary = "Application-wide storage information is not available."
        self.application_storage_summary_label.setText(summary)
        mapping = {
            "total": str(payload.get("total_text") or "Not available"),
            "current_profile": str(payload.get("current_profile_text") or "Not available"),
            "reclaimable": str(payload.get("reclaimable_text") or "Not available"),
            "deleted_profiles": str(payload.get("deleted_profile_text") or "Not available"),
            "orphaned": str(payload.get("orphaned_text") or "Not available"),
            "warnings": str(payload.get("warning_text") or "Not available"),
        }
        for key, label in self.application_storage_metric_labels.items():
            label.setText(mapping.get(key, "Not available"))
        self.open_storage_admin_button.setEnabled(
            callable(getattr(self.app, "open_application_storage_admin_dialog", None))
        )

    def _open_application_storage_admin(self) -> None:
        opener = getattr(self.app, "open_application_storage_admin_dialog", None)
        if callable(opener):
            opener()

    def _update_repair_buttons(self, check: dict | None):
        repairable = bool(check and check.get("repair_key")) and not self._busy
        self.preview_repair_button.setEnabled(repairable)
        self.repair_button.setEnabled(repairable)
        label = "Repair Issue"
        if check is not None:
            label = check.get("repair_label") or "Repair Issue"
        self.repair_button.setText(label)

    def _selected_check(self) -> dict | None:
        row = self.checks_list.currentRow()
        if row < 0 or row >= len(self._checks):
            return None
        return self._checks[row]

    def _preview_selected_repair(self):
        if self._busy:
            return
        check = self._selected_check()
        if not check or not check.get("repair_key"):
            return
        preview_text = self.app._preview_diagnostics_repair(check["repair_key"], check)
        base = self.details_edit.toPlainText().rstrip()
        self.details_edit.setPlainText(f"{base}\n\nRepair Preview\n\n{preview_text}")

    def _run_selected_repair(self):
        if self._busy:
            return
        check = self._selected_check()
        if not check or not check.get("repair_key"):
            return
        label = check.get("repair_label") or "Repair Issue"
        preview_text = self.app._preview_diagnostics_repair(check["repair_key"], check)
        if (
            QMessageBox.question(
                self,
                label,
                f"{preview_text}\n\nContinue?",
                QMessageBox.Yes | QMessageBox.No,
            )
            != QMessageBox.Yes
        ):
            return
        if check["repair_key"] != "storage_layout_migrate" and hasattr(
            self.app, "_run_diagnostics_repair_async"
        ):
            self._set_busy(True, label)
            self.app._run_diagnostics_repair_async(
                check["repair_key"],
                check,
                owner=self,
                on_success=self._handle_repair_success,
                on_error=lambda failure: self._handle_background_error(
                    "Repair Failed",
                    failure,
                    "Could not apply the selected diagnostics repair.",
                ),
                on_cancelled=self._handle_background_cancelled,
                on_status=self._set_busy_message,
            )
            return
        try:
            result_text = self.app._run_diagnostics_repair(check["repair_key"], check)
        except Exception as exc:
            QMessageBox.critical(self, "Repair Failed", str(exc))
            return
        QMessageBox.information(self, "Repair Complete", result_text)
        self.refresh()

    def _handle_repair_success(self, result_text: str) -> None:
        self._set_busy(False)
        QMessageBox.information(self, "Repair Complete", str(result_text or "Repair complete."))
        self.refresh()


class ApplicationStorageAdminDialog(QDialog):
    def __init__(self, app, parent=None):
        super().__init__(parent or app)
        self.app = app
        self._busy = False
        self._items_by_key: dict[str, dict[str, object]] = {}
        self.setObjectName("applicationStorageAdminDialog")
        self.setProperty("role", "panel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setWindowTitle("Application Storage Admin")
        self.resize(1220, 860)
        self.setMinimumSize(1080, 760)
        _apply_standard_dialog_chrome(self, "applicationStorageAdminDialog")
        self.setStyleSheet(
            _compose_widget_stylesheet(
                self,
                """
                QDialog#applicationStorageAdminDialog QLabel#storageAdminTitle {
                    font-size: 28px;
                    font-weight: 700;
                }
                QDialog#applicationStorageAdminDialog QLabel#storageAdminSubtitle {
                    font-size: 15px;
                }
                QDialog#applicationStorageAdminDialog QGroupBox {
                    font-size: 16px;
                    font-weight: 600;
                    margin-top: 8px;
                }
                QDialog#applicationStorageAdminDialog QGroupBox::title {
                    left: 10px;
                    padding: 0 6px;
                }
                """,
            )
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        help_row = QHBoxLayout()
        help_row.addStretch(1)
        help_row.addWidget(_create_round_help_button(self, "diagnostics"))
        root.addLayout(help_row)

        title = QLabel("Application Storage Admin")
        title.setObjectName("storageAdminTitle")
        title.setProperty("role", "dialogTitle")
        subtitle = QLabel(
            "Inspect application-wide files across active profiles, history, backups, and generated artifacts, then permanently clean up retained data without dropping into the OS shell."
        )
        subtitle.setObjectName("storageAdminSubtitle")
        subtitle.setProperty("role", "dialogSubtitle")
        subtitle.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(subtitle)

        self.loading_panel = QWidget(self)
        loading_row = QHBoxLayout(self.loading_panel)
        loading_row.setContentsMargins(0, 0, 0, 0)
        loading_row.setSpacing(10)
        self.loading_bar = QProgressBar(self)
        self.loading_bar.setRange(0, 0)
        self.loading_bar.setTextVisible(False)
        self.loading_bar.setMinimumWidth(220)
        self.loading_status_label = QLabel("Inspecting application-wide storage...")
        self.loading_status_label.setWordWrap(True)
        loading_row.addWidget(self.loading_bar)
        loading_row.addWidget(self.loading_status_label, 1)
        self.loading_panel.hide()
        root.addWidget(self.loading_panel)

        summary_group = QGroupBox("Storage Summary")
        summary_layout = QVBoxLayout(summary_group)
        summary_layout.setContentsMargins(14, 18, 14, 14)
        summary_layout.setSpacing(12)
        self.summary_label = QLabel(summary_group)
        self.summary_label.setWordWrap(True)
        self.summary_label.setProperty("role", "supportingText")
        summary_layout.addWidget(self.summary_label)

        metrics_layout = QGridLayout()
        metrics_layout.setHorizontalSpacing(18)
        metrics_layout.setVerticalSpacing(8)
        self.summary_metric_labels = {}
        for row, (metric_key, title_text) in enumerate(
            (
                ("total", "Total app usage"),
                ("current_profile", "Current profile attributed"),
                ("reclaimable", "Reclaimable now"),
                ("deleted_profiles", "Deleted-profile residue"),
                ("orphaned", "Orphaned / unreferenced"),
                ("warnings", "Warning / protected"),
            )
        ):
            title_label = QLabel(title_text, summary_group)
            title_label.setAlignment(Qt.AlignRight | Qt.AlignTop)
            value_label = QLabel("Not available", summary_group)
            value_label.setTextInteractionFlags(
                Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard
            )
            value_label.setWordWrap(True)
            metrics_layout.addWidget(title_label, row, 0, alignment=Qt.AlignRight | Qt.AlignTop)
            metrics_layout.addWidget(value_label, row, 1)
            self.summary_metric_labels[metric_key] = value_label
        metrics_layout.setColumnStretch(1, 1)
        summary_layout.addLayout(metrics_layout)

        warning_label = QLabel(
            "Final cleanup is permanent. These actions do not create new snapshots, undo records, or secondary safety copies."
        )
        warning_label.setWordWrap(True)
        warning_label.setProperty("role", "supportingText")
        summary_layout.addWidget(warning_label)
        root.addWidget(summary_group)

        self.surface_tabs = QTabWidget(self)
        self.surface_tabs.setDocumentMode(True)
        root.addWidget(self.surface_tabs, 1)

        self.cleanup_table = self._build_items_table()
        self.warning_table = self._build_items_table()
        self.update_backup_table = self._build_items_table(owner_header="Version")
        self.surface_tabs.addTab(self.cleanup_table, "Cleanup Candidates")
        self.surface_tabs.addTab(self.warning_table, "Warnings & In Use")
        self.surface_tabs.addTab(self.update_backup_table, "Update Backups")

        details_group = QGroupBox("Details")
        details_layout = QVBoxLayout(details_group)
        details_layout.setContentsMargins(14, 18, 14, 14)
        self.details_edit = QPlainTextEdit(self)
        self.details_edit.setReadOnly(True)
        self.details_edit.setMinimumHeight(180)
        details_layout.addWidget(self.details_edit)
        root.addWidget(details_group)

        button_row = QHBoxLayout()
        button_row.setSpacing(10)
        self.refresh_button = QPushButton("Refresh")
        self.delete_button = QPushButton("Delete Selected…")
        self.open_data_button = QPushButton("Open Data Folder")
        self.close_button = QPushButton("Close")
        for button in (
            self.refresh_button,
            self.delete_button,
            self.open_data_button,
            self.close_button,
        ):
            button.setMinimumWidth(150)
        button_row.addWidget(self.refresh_button)
        button_row.addWidget(self.delete_button)
        button_row.addWidget(self.open_data_button)
        button_row.addStretch(1)
        button_row.addWidget(self.close_button)
        root.addLayout(button_row)

        self.refresh_button.clicked.connect(self.refresh)
        self.delete_button.clicked.connect(self._delete_selected)
        self.open_data_button.clicked.connect(
            lambda: self.app._open_local_path(self.app.data_root, "Open Data Folder")
        )
        self.close_button.clicked.connect(self.accept)
        self.surface_tabs.currentChanged.connect(lambda _index: self._sync_selection_details())
        self.cleanup_table.itemSelectionChanged.connect(self._sync_selection_details)
        self.warning_table.itemSelectionChanged.connect(self._sync_selection_details)
        self.update_backup_table.itemSelectionChanged.connect(self._sync_selection_details)

        self.refresh()
        _apply_compact_dialog_control_heights(self)
        self._sync_loading_panel_metrics()

    def _build_items_table(self, *, owner_header: str = "Profile") -> QTableWidget:
        table = QTableWidget(0, 6, self)
        table.setHorizontalHeaderLabels(
            ["Status", "Category", "Item", "Size", owner_header, "Path"]
        )
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.setSortingEnabled(False)
        table.verticalHeader().setVisible(False)
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.Stretch)
        return table

    def refresh(self) -> None:
        if self._busy:
            return
        loader = getattr(self.app, "_load_application_storage_audit_async", None)
        if not callable(loader):
            self._apply_audit_payload({"summary": {}, "items": []})
            return
        self._set_busy(True, "Inspecting application-wide storage...")
        loader(
            owner=self,
            on_success=self._apply_audit_payload,
            on_error=lambda failure: self._handle_background_error(
                "Application Storage Admin",
                failure,
                "Could not inspect application-wide storage.",
            ),
            on_cancelled=self._handle_background_cancelled,
            on_status=self._set_busy_message,
        )

    def _apply_audit_payload(self, payload: dict[str, object]) -> None:
        self._set_busy(False)
        summary = payload.get("summary") or {}
        self.summary_label.setText(
            str(summary.get("summary") or "Application-wide storage information is not available.")
        )
        mapping = {
            "total": str(summary.get("total_text") or "Not available"),
            "current_profile": str(summary.get("current_profile_text") or "Not available"),
            "reclaimable": str(summary.get("reclaimable_text") or "Not available"),
            "deleted_profiles": str(summary.get("deleted_profile_text") or "Not available"),
            "orphaned": str(summary.get("orphaned_text") or "Not available"),
            "warnings": str(summary.get("warning_text") or "Not available"),
        }
        for key, label in self.summary_metric_labels.items():
            label.setText(mapping.get(key, "Not available"))

        raw_items = list(payload.get("items") or [])
        self._items_by_key = {
            str(item.get("item_key") or ""): dict(item)
            for item in raw_items
            if str(item.get("item_key") or "").strip()
        }
        update_items = [item for item in raw_items if self._is_update_backup_item(item)]
        non_update_items = [item for item in raw_items if not self._is_update_backup_item(item)]
        cleanup_items = [
            item for item in non_update_items if not bool(item.get("warning_required"))
        ]
        warning_items = [item for item in non_update_items if bool(item.get("warning_required"))]
        self._populate_items_table(self.cleanup_table, cleanup_items)
        self._populate_items_table(self.warning_table, warning_items)
        self._populate_items_table(self.update_backup_table, update_items)
        self.details_edit.setPlainText("")
        self._sync_selection_details()

    def _populate_items_table(self, table: QTableWidget, items: list[dict[str, object]]) -> None:
        table.setRowCount(0)
        for row_index, item in enumerate(items):
            table.insertRow(row_index)
            row_values = (
                str(item.get("status_label") or ""),
                str(item.get("category_label") or ""),
                str(item.get("label") or ""),
                str(item.get("size_text") or ""),
                str(item.get("profile_name") or ""),
                str(item.get("path") or ""),
            )
            item_key = str(item.get("item_key") or "")
            for column, text in enumerate(row_values):
                table_item = QTableWidgetItem(text)
                table_item.setData(Qt.UserRole, item_key)
                if column == 5:
                    table_item.setToolTip(text)
                table.setItem(row_index, column, table_item)
        if table.rowCount() > 0:
            table.selectRow(0)

    def _selected_items(self) -> list[dict[str, object]]:
        table = self.surface_tabs.currentWidget()
        if not isinstance(table, QTableWidget):
            return []
        items: list[dict[str, object]] = []
        seen_keys: set[str] = set()
        for row in sorted({index.row() for index in table.selectionModel().selectedRows()}):
            row_item = table.item(row, 0)
            if row_item is None:
                continue
            item_key = str(row_item.data(Qt.UserRole) or "").strip()
            if not item_key or item_key in seen_keys:
                continue
            payload = self._items_by_key.get(item_key)
            if payload is None:
                continue
            seen_keys.add(item_key)
            items.append(payload)
        return items

    def _sync_selection_details(self) -> None:
        selected = self._selected_items()
        if not selected:
            self.details_edit.setPlainText("Select a storage item to inspect its cleanup impact.")
            self.delete_button.setEnabled(False)
            return
        primary = selected[0]
        lines = [
            str(primary.get("label") or ""),
            f"Status: {primary.get('status_label') or ''}",
            f"Category: {primary.get('category_label') or ''}",
            f"Path: {primary.get('path') or ''}",
            f"Size: {primary.get('size_text') or ''}",
        ]
        profile_name = str(primary.get("profile_name") or "").strip()
        if profile_name:
            if self._is_update_backup_item(primary):
                lines.append(f"Version: {profile_name}")
            else:
                lines.append(f"Profile: {profile_name}")
        reason = str(primary.get("reason") or "").strip()
        if reason:
            lines.extend(["", reason])
        warning = str(primary.get("warning") or "").strip()
        if warning:
            lines.extend(["", "Warning", "", warning])
        references_text = str(primary.get("references_text") or "").strip()
        if references_text:
            lines.extend(["", "Live references", "", references_text])
        if len(selected) > 1:
            lines.extend(["", f"{len(selected)} item(s) are currently selected."])
        self.details_edit.setPlainText("\n".join(lines))
        self.delete_button.setEnabled(not self._busy)

    def _delete_selected(self) -> None:
        if self._busy:
            return
        selected = self._selected_items()
        if not selected:
            return
        total_bytes = sum(int(item.get("bytes_on_disk") or 0) for item in selected)
        warning_items = [item for item in selected if bool(item.get("warning_required"))]
        if (
            QMessageBox.question(
                self,
                "Delete Selected Files",
                (
                    f"Permanently delete {len(selected)} selected storage item(s)\n"
                    f"Estimated reclaimed space: {self._display_bytes(total_bytes)}\n\n"
                    "This cleanup does not create undo, redo, or snapshot history. Continue?"
                ),
                QMessageBox.Yes | QMessageBox.No,
            )
            != QMessageBox.Yes
        ):
            return
        allow_warning_deletes = False
        if warning_items:
            warning_names = "\n".join(str(item.get("label") or "") for item in warning_items[:6])
            typed_text, accepted = QInputDialog.getText(
                self,
                "Confirm Protected Cleanup",
                (
                    "Some selected items are still in use or still back live recovery state.\n\n"
                    f"{warning_names}\n\n"
                    "Type DELETE to confirm permanent cleanup."
                ),
            )
            if not accepted or str(typed_text).strip() != "DELETE":
                return
            allow_warning_deletes = True

        runner = getattr(self.app, "_run_application_storage_cleanup_async", None)
        if not callable(runner):
            QMessageBox.warning(
                self,
                "Application Storage Admin",
                "Application-wide cleanup is not available in this build.",
            )
            return
        self._set_busy(True, "Deleting selected storage items...")
        runner(
            [str(item.get("item_key") or "") for item in selected],
            allow_warning_deletes=allow_warning_deletes,
            owner=self,
            on_success=self._handle_cleanup_success,
            on_error=lambda failure: self._handle_background_error(
                "Application Storage Cleanup",
                failure,
                "Could not complete the selected final cleanup.",
            ),
            on_cancelled=self._handle_background_cancelled,
            on_status=self._set_busy_message,
        )

    def _handle_cleanup_success(self, payload: dict[str, object]) -> None:
        self._set_busy(False)
        removed_count = int(payload.get("removed_count") or 0)
        removed_text = str(payload.get("removed_text") or self._display_bytes(0))
        history_count = int(payload.get("removed_history_entry_count") or 0)
        session_count = int(payload.get("removed_session_entry_count") or 0)
        skipped_count = int(payload.get("skipped_count") or 0)
        parts = [
            f"Removed {removed_count} storage item(s) and reclaimed {removed_text}.",
        ]
        if history_count:
            parts.append(
                f"Quarantined {history_count} dependent history entr{'y' if history_count == 1 else 'ies'}."
            )
        if session_count:
            parts.append(
                f"Removed {session_count} dependent session-history entr{'y' if session_count == 1 else 'ies'}."
            )
        if skipped_count:
            parts.append(f"Skipped {skipped_count} item(s).")
        QMessageBox.information(self, "Cleanup Complete", "\n".join(parts))
        refresh_history_actions = getattr(self.app, "_refresh_history_actions", None)
        if callable(refresh_history_actions):
            refresh_history_actions()
        self.refresh()

    def _set_busy(self, busy: bool, message: str | None = None) -> None:
        self._busy = bool(busy)
        if self._busy:
            self.loading_panel.show()
            self._set_busy_message(message or "Working...")
        else:
            self.loading_panel.hide()
            self.loading_status_label.setText("")
        for widget in (
            self.refresh_button,
            self.delete_button,
            self.open_data_button,
            self.close_button,
            self.cleanup_table,
            self.warning_table,
            self.update_backup_table,
        ):
            widget.setEnabled(not self._busy)
        if not self._busy:
            self._sync_selection_details()
        self._sync_loading_panel_metrics()

    def _set_busy_message(self, message: str) -> None:
        self.loading_status_label.setText(str(message or "Working..."))

    def _handle_background_cancelled(self) -> None:
        self._set_busy(False)
        self.details_edit.setPlainText("The application-wide storage task was cancelled.")

    def _handle_background_error(self, title: str, failure, user_message: str) -> None:
        self._set_busy(False)
        if hasattr(self.app, "_show_background_task_error"):
            self.app._show_background_task_error(title, failure, user_message=user_message)
            return
        message = str(getattr(failure, "message", failure) or "Unknown error.")
        QMessageBox.critical(self, title, f"{user_message}\n{message}")

    def _sync_loading_panel_metrics(self):
        available_width = max(560, self.width() - 72)
        bar_width = max(220, min(320, int(available_width * 0.24)))
        self.loading_bar.setFixedWidth(bar_width)
        self.loading_status_label.setMinimumWidth(max(260, available_width - bar_width - 32))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_loading_panel_metrics()

    @staticmethod
    def _display_bytes(value: int) -> str:
        return format_storage_bytes(value, max_decimals=1)

    @staticmethod
    def _is_update_backup_item(item: dict[str, object]) -> bool:
        category_key = str(item.get("category_key") or "")
        item_key = str(item.get("item_key") or "")
        return category_key.startswith("update_") or item_key.startswith("update-")


class AboutDialog(QDialog):
    def __init__(self, app, parent=None):
        super().__init__(parent or app)
        self.app = app
        self.setObjectName("aboutDialog")
        self.setProperty("role", "panel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setWindowTitle("About ISRC Catalog Manager")
        self.resize(680, 420)
        self.setMinimumSize(620, 380)
        _apply_standard_dialog_chrome(self, "aboutDialog")
        self.setStyleSheet(
            _compose_widget_stylesheet(
                self,
                """
                QDialog#aboutDialog QLabel#aboutTitle {
                    font-size: 30px;
                    font-weight: 700;
                }
                QDialog#aboutDialog QLabel#aboutBody {
                    font-size: 15px;
                }
                QDialog#aboutDialog QGroupBox {
                    font-size: 16px;
                    font-weight: 600;
                    margin-top: 8px;
                }
                QDialog#aboutDialog QGroupBox::title {
                    left: 10px;
                    padding: 0 6px;
                }
                """,
            )
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        help_row = QHBoxLayout()
        help_row.addStretch(1)
        help_row.addWidget(_create_round_help_button(self, "about"))
        root.addLayout(help_row)

        top_row = QHBoxLayout()
        top_row.setSpacing(16)

        icon_label = QLabel()
        icon_label.setFixedSize(96, 96)
        pixmap = app.windowIcon().pixmap(96, 96)
        if not pixmap.isNull():
            icon_label.setPixmap(pixmap)
        top_row.addWidget(icon_label, 0, Qt.AlignTop)

        intro_layout = QVBoxLayout()
        intro_layout.setSpacing(8)
        title = QLabel("ISRC Catalog Manager")
        title.setObjectName("aboutTitle")
        title.setProperty("role", "dialogTitle")
        intro_layout.addWidget(title)

        version_label = QLabel(f"Version {app._app_version_text()}")
        version_label.setProperty("role", "secondary")
        intro_layout.addWidget(version_label)

        body = QLabel(
            "Local-first desktop catalog management for tracks, licensing, custom metadata, snapshots, and export workflows."
        )
        body.setObjectName("aboutBody")
        body.setProperty("role", "dialogSubtitle")
        body.setWordWrap(True)
        intro_layout.addWidget(body)

        body2 = QLabel(
            "Everything stays on your machine: profile databases, managed media, logs, backups, and history."
        )
        body2.setObjectName("aboutBody")
        body2.setProperty("role", "dialogSubtitle")
        body2.setWordWrap(True)
        intro_layout.addWidget(body2)
        intro_layout.addStretch(1)
        top_row.addLayout(intro_layout, 1)
        root.addLayout(top_row)

        details_group = QGroupBox("Current Workspace")
        details_layout = QFormLayout(details_group)
        details_layout.setContentsMargins(14, 18, 14, 14)
        details_layout.setHorizontalSpacing(18)
        details_layout.setVerticalSpacing(10)
        details_layout.setLabelAlignment(Qt.AlignRight | Qt.AlignTop)

        details = {
            "Window title": app.windowTitle() or DEFAULT_WINDOW_TITLE,
            "Current profile": (
                Path(app.current_db_path).name if getattr(app, "current_db_path", "") else "(none)"
            ),
            "Database path": (
                str(app.current_db_path) if getattr(app, "current_db_path", "") else "(none)"
            ),
            "Data folder": str(app.data_root),
            "Log folder": str(app.logs_dir),
            "Schema version": str(app._get_db_version()),
        }
        for key, value in details.items():
            label = QLabel(value)
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
            details_layout.addRow(key, label)
        root.addWidget(details_group)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok, Qt.Horizontal, self)
        buttons.accepted.connect(self.accept)
        root.addWidget(buttons)


class ReleaseNotesDialog(QDialog):
    def __init__(
        self,
        *,
        version: str,
        released_at: str,
        summary: str,
        release_notes_markdown: str,
        release_notes_url: str = "",
        allow_update_install: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self._install_requested = False
        self.update_button = None
        self.setWindowTitle(f"Release Notes - {version}")
        self.resize(900, 680)
        self.setMinimumSize(760, 520)
        _apply_standard_dialog_chrome(self, "releaseNotesDialog")

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        subtitle_parts = [f"Version {version}"]
        if released_at:
            subtitle_parts.append(str(released_at))
        _add_standard_dialog_header(
            root,
            self,
            title="Release Notes",
            subtitle=" - ".join(subtitle_parts),
        )

        summary_box, summary_layout = _create_standard_section(
            self,
            "Update Summary",
            "A quick summary from the update manifest.",
        )
        summary_label = QLabel(str(summary or "").strip() or "No summary was provided.")
        summary_label.setWordWrap(True)
        summary_label.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard
        )
        summary_layout.addWidget(summary_label)
        root.addWidget(summary_box)

        notes_box, notes_layout = _create_standard_section(
            self,
            "Release Notes",
            "Release notes are loaded and shown inside the application.",
        )
        self.browser = QTextBrowser(self)
        self.browser.setOpenExternalLinks(False)
        self.browser.setOpenLinks(False)
        self.browser.setMinimumHeight(320)
        self.browser.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard | Qt.LinksAccessibleByKeyboard
        )
        self._set_notes_markdown(
            release_notes_markdown=release_notes_markdown,
            version=version,
            summary=summary,
            release_notes_url=release_notes_url,
        )
        notes_layout.addWidget(self.browser, 1)
        root.addWidget(notes_box, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close, Qt.Horizontal, self)
        buttons.rejected.connect(self.reject)
        if allow_update_install:
            self.update_button = buttons.addButton(
                "Download and Install",
                QDialogButtonBox.ActionRole,
            )
            self.update_button.clicked.connect(self._request_update_install)
        close_button = buttons.button(QDialogButtonBox.Close)
        if close_button is not None:
            close_button.setDefault(True)
        root.addWidget(buttons)

    def install_requested(self) -> bool:
        return bool(self._install_requested)

    def _request_update_install(self) -> None:
        self._install_requested = True
        self.accept()

    def _set_notes_markdown(
        self,
        *,
        release_notes_markdown: str,
        version: str,
        summary: str,
        release_notes_url: str,
    ) -> None:
        markdown = str(release_notes_markdown or "").strip()
        if not markdown:
            fallback_lines = [
                f"# ISRC Catalog Manager {version}",
                "",
                str(summary or "").strip() or "No release-note details were provided.",
                "",
                "The full release notes could not be loaded inside the app right now.",
            ]
            if release_notes_url:
                fallback_lines.extend(
                    [
                        "",
                        "Source:",
                        str(release_notes_url).strip(),
                    ]
                )
            markdown = "\n".join(fallback_lines)
        if hasattr(self.browser, "setMarkdown"):
            self.browser.setMarkdown(markdown)
        else:
            self.browser.setPlainText(markdown)


class HelpContentsDialog(QDialog):
    def __init__(self, app, parent=None):
        super().__init__(parent or app)
        self.app = app
        self.setWindowTitle("Help Contents")
        self.resize(1180, 820)
        self.setMinimumSize(980, 680)
        self._current_topic_id = "overview"
        self._help_html = ""

        _apply_standard_dialog_chrome(
            self,
            "helpContentsDialog",
            extra_qss="""
            QDialog#helpContentsDialog QListWidget#helpChapterList {
                min-width: 280px;
            }
            """,
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        _add_standard_dialog_header(
            root,
            self,
            title="Help Contents",
            subtitle="Browse quick-start chapters, drill into deeper reference topics, and jump directly to the section that matches the current window.",
        )

        self.search_field = QLineEdit(self)
        self.search_field.setPlaceholderText("Search help...")
        self.search_field.setClearButtonEnabled(True)
        self.search_field.setMinimumWidth(320)
        self.search_prev_button = QPushButton("Previous Match")
        self.search_next_button = QPushButton("Next Match")
        self.open_file_button = QPushButton("Open Help File")
        self.close_button = QPushButton("Close")
        search_box, search_layout = _create_standard_section(
            self,
            "Find & Navigate",
            "Filter the chapter index or search inside the loaded help page. Use the navigation buttons to jump between matches.",
        )
        search_row = QHBoxLayout()
        search_row.setSpacing(8)
        search_row.addWidget(self.search_field, 1)
        search_row.addWidget(self.search_prev_button)
        search_row.addWidget(self.search_next_button)
        search_row.addStretch(1)
        search_row.addWidget(self.open_file_button)
        search_row.addWidget(self.close_button)
        search_layout.addLayout(search_row)
        root.addWidget(search_box)

        splitter = QSplitter(Qt.Horizontal, self)

        self.chapter_list = QListWidget(self)
        self.chapter_list.setObjectName("helpChapterList")
        splitter.addWidget(self.chapter_list)

        self.browser = QTextBrowser(self)
        self.browser.setOpenExternalLinks(False)
        self.browser.setOpenLinks(False)
        splitter.addWidget(self.browser)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        content_box, content_layout = _create_standard_section(
            self,
            "Help Manual",
            "Browse the indexed chapters on the left and read the selected help article on the right.",
        )
        content_layout.addWidget(splitter, 1)
        root.addWidget(content_box, 1)

        self.match_status_label = QLabel("Type to search or select a chapter from the index.")
        self.match_status_label.setProperty("role", "secondary")
        self.match_status_label.setWordWrap(True)
        root.addWidget(self.match_status_label)

        self.search_field.textChanged.connect(self._filter_chapters)
        self.search_field.returnPressed.connect(self.find_next)
        self.search_prev_button.clicked.connect(self.find_previous)
        self.search_next_button.clicked.connect(self.find_next)
        self.open_file_button.clicked.connect(self._open_help_file)
        self.close_button.clicked.connect(self.close)
        self.chapter_list.currentItemChanged.connect(self._on_chapter_selection_changed)
        self.browser.anchorClicked.connect(self._on_anchor_clicked)
        self.find_shortcut = QShortcut(QKeySequence.Find, self)
        self.find_shortcut.activated.connect(
            lambda: (
                self.search_field.setFocus(Qt.ShortcutFocusReason),
                self.search_field.selectAll(),
            )
        )

        self.refresh_help_source()

    def refresh_help_source(self) -> None:
        help_path = self.app._ensure_help_file()
        try:
            self._help_html = help_path.read_text(encoding="utf-8")
        except Exception:
            self._help_html = self.app._help_html()
        self.browser.setHtml(self._help_html)
        self._rebuild_chapter_index()
        self.open_topic(self._current_topic_id or "overview", focus_search=False)

    def _rebuild_chapter_index(self, query: str = "") -> None:
        needle = (query or "").strip().lower()
        self.chapter_list.blockSignals(True)
        self.chapter_list.clear()
        visible_sections = []
        for section_title, section_chapters in iter_help_sections():
            matched_chapters = []
            for chapter in section_chapters:
                haystack = " ".join(
                    (chapter.title, chapter.summary, " ".join(chapter.keywords))
                ).lower()
                if needle and needle not in haystack:
                    continue
                matched_chapters.append(chapter)
            if matched_chapters:
                visible_sections.append((section_title, matched_chapters))

        for section_title, section_chapters in visible_sections:
            heading = QListWidgetItem(section_title)
            heading.setData(Qt.UserRole + 1, "sectionHeader")
            heading.setFlags(Qt.ItemFlag.NoItemFlags)
            heading.setToolTip(f"{section_title} chapters")
            self.chapter_list.addItem(heading)
            for chapter in section_chapters:
                item = QListWidgetItem(chapter.title)
                item.setData(Qt.UserRole, chapter.chapter_id)
                item.setToolTip(f"{chapter.summary}\n\nKeywords: {', '.join(chapter.keywords)}")
                self.chapter_list.addItem(item)
        self.chapter_list.blockSignals(False)

        if self.chapter_list.count():
            for index in range(self.chapter_list.count()):
                item = self.chapter_list.item(index)
                if item.data(Qt.UserRole) == self._current_topic_id:
                    self.chapter_list.setCurrentRow(index)
                    break
            else:
                self.chapter_list.setCurrentRow(0)

    def _on_chapter_selection_changed(self, current, _previous) -> None:
        if current is None:
            return
        topic_id = str(current.data(Qt.UserRole) or "")
        if topic_id:
            self.open_topic(topic_id, focus_search=False)

    def _on_anchor_clicked(self, url: QUrl) -> None:
        fragment = (url.fragment() or "").strip()
        if fragment:
            self.open_topic(fragment, focus_search=False)
            return
        open_external_url(
            url,
            source="HelpContentsDialog.anchorClicked",
            metadata={"topic_id": self._current_topic_id or ""},
        )

    def _move_search_to_start(self) -> None:
        cursor = self.browser.textCursor()
        cursor.movePosition(QTextCursor.Start)
        self.browser.setTextCursor(cursor)

    def _move_search_to_end(self) -> None:
        cursor = self.browser.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.browser.setTextCursor(cursor)

    def _search_document(self, *, backward: bool) -> bool:
        text = self.search_field.text().strip()
        if not text:
            self.match_status_label.setText(
                "Type text into the search field to search within the help file."
            )
            return False
        flags = QTextDocument.FindBackward if backward else None
        found = self.browser.find(text, flags) if flags is not None else self.browser.find(text)
        if not found:
            if backward:
                self._move_search_to_end()
            else:
                self._move_search_to_start()
            found = self.browser.find(text, flags) if flags is not None else self.browser.find(text)
        self.match_status_label.setText(
            f"Searching for: {text}" if found else f"No matches found for: {text}"
        )
        return found

    def find_next(self) -> None:
        self._search_document(backward=False)

    def find_previous(self) -> None:
        self._search_document(backward=True)

    def _filter_chapters(self, text: str) -> None:
        self._rebuild_chapter_index(text)
        if text.strip():
            self.find_next()
        else:
            self.match_status_label.setText("Type to search or select a chapter from the index.")

    def open_topic(self, topic_id: str, *, focus_search: bool = False) -> None:
        chapter_id = topic_id if topic_id in HELP_CHAPTERS_BY_ID else "overview"
        self._current_topic_id = chapter_id
        for index in range(self.chapter_list.count()):
            item = self.chapter_list.item(index)
            if item.data(Qt.UserRole) == chapter_id:
                self.chapter_list.blockSignals(True)
                self.chapter_list.setCurrentRow(index)
                self.chapter_list.blockSignals(False)
                break
        self.browser.scrollToAnchor(chapter_id)
        self.match_status_label.setText(HELP_CHAPTERS_BY_ID[chapter_id].summary)
        if focus_search:
            self.search_field.setFocus(Qt.OtherFocusReason)
            self.search_field.selectAll()

    def _open_help_file(self) -> None:
        self.app._open_local_path(self.app._ensure_help_file(), "Open Help File")

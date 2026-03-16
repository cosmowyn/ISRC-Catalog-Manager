from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QTextCursor, QTextDocument
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
)

from isrc_manager.constants import DEFAULT_WINDOW_TITLE, FIELD_TYPE_CHOICES
from isrc_manager.help_content import HELP_CHAPTERS, HELP_CHAPTERS_BY_ID
from isrc_manager.paths import DATA_DIR
from isrc_manager.ui_common import (
    FocusWheelComboBox,
    _add_standard_dialog_header,
    _apply_standard_dialog_chrome,
    _compose_widget_stylesheet,
    _create_round_help_button,
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

        # fields: [{"id": int|None, "name": str, "field_type": "text|dropdown|checkbox|date", "options": str|None}]
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
        row1.addWidget(self.btn_add)
        row1.addWidget(self.btn_remove)
        row1.addWidget(self.btn_rename)
        row1.addWidget(self.btn_type)
        row1.addWidget(self.btn_opts)
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
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        self._refresh_list()

    def _refresh_list(self):
        self.listw.clear()
        for index, field in enumerate(self.fields):
            label = f"{field['name']}  ·  {field.get('field_type', 'text')}"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, index)
            self.listw.addItem(item)

    def _current_index(self):
        item = self.listw.currentItem()
        return item.data(Qt.UserRole) if item else None

    def _current_field(self):
        index = self._current_index()
        return (self.fields[index] if index is not None else None), index

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

        new_field = {"id": None, "name": name, "field_type": field_type, "options": None}

        if field_type == "dropdown":
            options_text, options_ok = QInputDialog.getMultiLineText(
                self, "Dropdown Options", "Enter options (one per line):"
            )
            if options_ok:
                options = [
                    option.strip() for option in (options_text or "").splitlines() if option.strip()
                ]
                new_field["options"] = json.dumps(options) if options else json.dumps([])

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


class ApplicationLogDialog(QDialog):
    def __init__(self, app, parent=None):
        super().__init__(parent or app)
        self.app = app
        self.setObjectName("applicationLogDialog")
        self.setWindowTitle("Application Log")
        self.resize(860, 700)
        self.setMinimumSize(720, 560)
        self.setStyleSheet(
            _compose_widget_stylesheet(
                self,
                """
                QDialog#applicationLogDialog QLabel#logTitle {
                    font-size: 28px;
                    font-weight: 700;
                }
                QDialog#applicationLogDialog QLabel#logSubtitle {
                    color: #64748b;
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
                    color: #475569;
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
        subtitle = QLabel(
            "Review the live application logs, open archived log files, and jump straight to the log folder."
        )
        subtitle.setObjectName("logSubtitle")
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
        self.setObjectName("diagnosticsDialog")
        self.setWindowTitle("Diagnostics")
        self.resize(1080, 780)
        self.setMinimumSize(980, 680)
        self.setStyleSheet(
            _compose_widget_stylesheet(
                self,
                """
                QDialog#diagnosticsDialog QLabel#diagnosticsTitle {
                    font-size: 28px;
                    font-weight: 700;
                }
                QDialog#diagnosticsDialog QLabel#diagnosticsSubtitle {
                    color: #64748b;
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
        subtitle = QLabel(
            "Inspect the current profile, schema, and managed files to quickly spot anything that needs attention."
        )
        subtitle.setObjectName("diagnosticsSubtitle")
        subtitle.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(subtitle)

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
        root.addWidget(self.environment_group)

        checks_group = QGroupBox("Checks")
        checks_layout = QVBoxLayout(checks_group)
        checks_layout.setContentsMargins(14, 18, 14, 14)
        checks_layout.setSpacing(12)
        self.checks_list = QListWidget(self)
        self.checks_list.setMinimumHeight(220)
        checks_layout.addWidget(self.checks_list, 1)
        root.addWidget(checks_group, 1)

        details_group = QGroupBox("Details")
        details_layout = QVBoxLayout(details_group)
        details_layout.setContentsMargins(14, 18, 14, 14)
        self.details_edit = QPlainTextEdit(self)
        self.details_edit.setReadOnly(True)
        self.details_edit.setMinimumHeight(190)
        details_layout.addWidget(self.details_edit)
        root.addWidget(details_group)

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
            lambda: self.app._open_local_path(DATA_DIR(), "Open Data Folder")
        )
        self.close_button.clicked.connect(self.accept)
        self.checks_list.currentRowChanged.connect(self._show_selected_check)

        self.refresh()

    def refresh(self):
        report = self.app._build_diagnostics_report()
        for key, value in report["environment"].items():
            label = self.environment_labels.get(key)
            if label is not None:
                label.setText(value)
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
        available_width = max(460, self.environment_group.width() - 280)
        for key, label in self.environment_labels.items():
            label.setFixedWidth(available_width)
            label.adjustSize()
            label.setMinimumHeight(max(label.sizeHint().height(), label.fontMetrics().height() + 8))
            name_label = self.environment_name_labels.get(key)
            if name_label is not None:
                name_label.setMinimumHeight(label.minimumHeight())

    def _update_repair_buttons(self, check: dict | None):
        repairable = bool(check and check.get("repair_key"))
        self.preview_repair_button.setEnabled(repairable)
        self.repair_button.setEnabled(repairable)

    def _selected_check(self) -> dict | None:
        row = self.checks_list.currentRow()
        if row < 0 or row >= len(self._checks):
            return None
        return self._checks[row]

    def _preview_selected_repair(self):
        check = self._selected_check()
        if not check or not check.get("repair_key"):
            return
        preview_text = self.app._preview_diagnostics_repair(check["repair_key"], check)
        base = self.details_edit.toPlainText().rstrip()
        self.details_edit.setPlainText(f"{base}\n\nRepair Preview\n\n{preview_text}")

    def _run_selected_repair(self):
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
        try:
            result_text = self.app._run_diagnostics_repair(check["repair_key"], check)
        except Exception as exc:
            QMessageBox.critical(self, "Repair Failed", str(exc))
            return
        QMessageBox.information(self, "Repair Complete", result_text)
        self.refresh()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_environment_label_metrics()


class AboutDialog(QDialog):
    def __init__(self, app, parent=None):
        super().__init__(parent or app)
        self.app = app
        self.setObjectName("aboutDialog")
        self.setWindowTitle("About ISRC Catalog Manager")
        self.resize(680, 420)
        self.setMinimumSize(620, 380)
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
        intro_layout.addWidget(title)

        version_label = QLabel(f"Version {app._app_version_text()}")
        version_label.setProperty("role", "secondary")
        intro_layout.addWidget(version_label)

        body = QLabel(
            "Local-first desktop catalog management for tracks, licensing, custom metadata, snapshots, and export workflows."
        )
        body.setObjectName("aboutBody")
        body.setWordWrap(True)
        intro_layout.addWidget(body)

        body2 = QLabel(
            "Everything stays on your machine: profile databases, managed media, logs, backups, and history."
        )
        body2.setObjectName("aboutBody")
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
            "Data folder": str(DATA_DIR()),
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
            subtitle="Search the local help manual, browse indexed chapters, and jump directly to the section that matches the current window.",
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
        self.browser.setOpenExternalLinks(True)
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
        for chapter in HELP_CHAPTERS:
            haystack = " ".join(
                (chapter.title, chapter.summary, " ".join(chapter.keywords))
            ).lower()
            if needle and needle not in haystack:
                continue
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

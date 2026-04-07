"""Workspace panel for the central code registry."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
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

from isrc_manager.ui_common import (
    _add_standard_dialog_header,
    _apply_compact_dialog_control_heights,
    _apply_standard_widget_chrome,
    _configure_standard_form_layout,
    _create_standard_section,
)

from .models import (
    BUILTIN_CATEGORY_CATALOG_NUMBER,
    BUILTIN_CATEGORY_REGISTRY_SHA256_KEY,
    GENERATION_STRATEGY_MANUAL,
    GENERATION_STRATEGY_SEQUENTIAL,
    GENERATION_STRATEGY_SHA256,
    SUBJECT_KIND_CATALOG,
    SUBJECT_KIND_CONTRACT,
    SUBJECT_KIND_GENERIC,
    SUBJECT_KIND_KEY,
    SUBJECT_KIND_LICENSE,
    CodeRegistryCategoryPayload,
)
from .service import CodeRegistryService


class _RegistryOwnerAssignmentDialog(QDialog):
    """Allows assigning an existing internal registry value to a track, release, or contract."""

    _OWNER_KIND_LABELS = {
        "track": "Track",
        "release": "Release",
        "contract": "Contract",
    }

    def __init__(
        self,
        *,
        service_provider: Callable[[], CodeRegistryService | None],
        entry_id: int,
        entry_value: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service_provider = service_provider
        self.entry_id = int(entry_id)
        self.entry_value = str(entry_value or "").strip()
        self._target_rows: list[tuple[str, int]] = []
        self.setWindowTitle("Link Registry Value")
        self.resize(760, 520)
        self._build_ui()
        self._refresh_targets()

    def _service(self) -> CodeRegistryService | None:
        try:
            return self.service_provider()
        except Exception:
            return None

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        intro = QLabel(
            f"Link internal registry value '{self.entry_value}' to an existing owner.",
            self,
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(8)
        self.owner_kind_combo = QComboBox(self)
        controls.addWidget(self.owner_kind_combo)
        self.search_edit = QLineEdit(self)
        self.search_edit.setPlaceholderText("Search by ID, title, artist, or code...")
        controls.addWidget(self.search_edit, 1)
        layout.addLayout(controls)

        self.target_table = QTableWidget(0, 4, self)
        self.target_table.setHorizontalHeaderLabels(["Type", "ID", "Label", "Detail"])
        self.target_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.target_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.target_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.target_table.verticalHeader().setVisible(False)
        self.target_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.target_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.target_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.target_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        layout.addWidget(self.target_table, 1)

        self.empty_label = QLabel("", self)
        self.empty_label.setWordWrap(True)
        self.empty_label.setProperty("role", "supportingText")
        layout.addWidget(self.empty_label)

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel,
            Qt.Horizontal,
            self,
        )
        ok_button = self.button_box.button(QDialogButtonBox.Ok)
        if ok_button is not None:
            ok_button.setText("Link Value")
            ok_button.setEnabled(False)
        self.button_box.accepted.connect(self._accept_selection)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

        service = self._service()
        owner_kinds = (
            service.assignment_owner_kinds_for_entry(self.entry_id) if service is not None else []
        )
        for owner_kind in owner_kinds:
            self.owner_kind_combo.addItem(
                self._OWNER_KIND_LABELS.get(owner_kind, owner_kind.title()),
                owner_kind,
            )
        self.owner_kind_combo.currentIndexChanged.connect(self._refresh_targets)
        self.search_edit.textChanged.connect(self._refresh_targets)
        self.target_table.itemSelectionChanged.connect(self._sync_accept_enabled)

    def _selected_target(self) -> tuple[str, int] | None:
        row = self.target_table.currentRow()
        if row < 0 or row >= len(self._target_rows):
            return None
        return self._target_rows[row]

    def assignment(self) -> tuple[str, int] | None:
        return self._selected_target()

    def _sync_accept_enabled(self) -> None:
        ok_button = self.button_box.button(QDialogButtonBox.Ok)
        if ok_button is not None:
            ok_button.setEnabled(self._selected_target() is not None)

    def _refresh_targets(self) -> None:
        service = self._service()
        self.target_table.setRowCount(0)
        self._target_rows = []
        if service is None:
            self.empty_label.setText("Code registry service is unavailable.")
            self._sync_accept_enabled()
            return
        current_owner_kind = self.owner_kind_combo.currentData()
        if current_owner_kind is None:
            self.empty_label.setText("This registry value does not support workspace assignment.")
            self._sync_accept_enabled()
            return
        targets = service.list_assignment_targets_for_entry(
            self.entry_id,
            owner_kind=str(current_owner_kind),
            search_text=self.search_edit.text().strip() or None,
        )
        for target in targets:
            row = self.target_table.rowCount()
            self.target_table.insertRow(row)
            self._target_rows.append((target.owner_kind, int(target.owner_id)))
            values = [
                self._OWNER_KIND_LABELS.get(target.owner_kind, target.owner_kind.title()),
                str(target.owner_id),
                target.label,
                target.detail or "",
            ]
            for column, value in enumerate(values):
                self.target_table.setItem(row, column, QTableWidgetItem(value))
        self.target_table.resizeColumnsToContents()
        self.empty_label.setText(
            ""
            if targets
            else "No matching owners were found. Adjust the search or choose another owner type."
        )
        if targets:
            self.target_table.selectRow(0)
        self._sync_accept_enabled()

    def _accept_selection(self) -> None:
        if self._selected_target() is None:
            QMessageBox.warning(self, "Link Registry Value", "Select an owner to continue.")
            return
        self.accept()


class CodeRegistryWorkspacePanel(QWidget):
    """Integrated management surface for internal codes, external catalogs, and categories."""

    close_requested = Signal()

    _SUBJECT_KIND_CHOICES = (
        ("Catalog", SUBJECT_KIND_CATALOG),
        ("Contract", SUBJECT_KIND_CONTRACT),
        ("License", SUBJECT_KIND_LICENSE),
        ("Registry Key", SUBJECT_KIND_KEY),
        ("Generic", SUBJECT_KIND_GENERIC),
    )
    _GENERATION_CHOICES = (
        ("Sequential", GENERATION_STRATEGY_SEQUENTIAL),
        ("SHA-256", GENERATION_STRATEGY_SHA256),
        ("Manual", GENERATION_STRATEGY_MANUAL),
    )

    def __init__(
        self,
        *,
        service_provider: Callable[[], CodeRegistryService | None],
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.service_provider = service_provider
        self._category_row_ids: list[int] = []
        self._entry_row_ids: list[int] = []
        self._external_row_ids: list[int] = []
        self._suspend_category_form = False
        self._selected_entry_id: int | None = None
        _apply_standard_widget_chrome(self, "codeRegistryWorkspacePanel")
        self.setProperty("role", "workspaceCanvas")
        self._build_ui()
        self.refresh()

    def _service(self) -> CodeRegistryService | None:
        try:
            return self.service_provider()
        except Exception:
            return None

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)
        _add_standard_dialog_header(
            root,
            self,
            title="Code Registry",
            subtitle=(
                "Manage authoritative internal business codes and the separate Registry SHA-256 Key, "
                "while keeping foreign catalog identifiers safely distinct."
            ),
        )
        self.status_label = QLabel("", self)
        self.status_label.setWordWrap(True)
        self.status_label.setProperty("role", "supportingText")
        root.addWidget(self.status_label)

        self.tabs = QTabWidget(self)
        self.tabs.setDocumentMode(True)
        root.addWidget(self.tabs, 1)

        self._build_entries_tab()
        self._build_external_tab()
        self._build_categories_tab()
        _apply_compact_dialog_control_heights(self)

    def _build_entries_tab(self) -> None:
        page = QWidget(self)
        page.setProperty("role", "workspaceCanvas")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(8)
        self.entry_search_edit = QLineEdit(page)
        self.entry_search_edit.setPlaceholderText("Search internal registry values...")
        self.entry_search_edit.textChanged.connect(self.refresh_entries)
        toolbar.addWidget(self.entry_search_edit, 1)
        self.entry_category_filter = QComboBox(page)
        self.entry_category_filter.currentIndexChanged.connect(self.refresh_entries)
        toolbar.addWidget(self.entry_category_filter)
        self.include_unused_checkbox = QCheckBox("Include Unlinked", page)
        self.include_unused_checkbox.setChecked(True)
        self.include_unused_checkbox.toggled.connect(self.refresh_entries)
        toolbar.addWidget(self.include_unused_checkbox)
        generate_code_button = QPushButton("Generate Code", page)
        generate_code_button.clicked.connect(self._generate_catalog_code)
        toolbar.addWidget(generate_code_button)
        generate_hash_button = QPushButton("Generate Registry SHA-256 Key", page)
        generate_hash_button.clicked.connect(self._generate_registry_hash)
        toolbar.addWidget(generate_hash_button)
        refresh_button = QPushButton("Refresh", page)
        refresh_button.clicked.connect(self.refresh)
        toolbar.addWidget(refresh_button)
        layout.addLayout(toolbar)

        splitter = QSplitter(Qt.Horizontal, page)
        splitter.setChildrenCollapsible(False)

        table_box, table_layout = _create_standard_section(
            page,
            "Internal Registry",
            "Every row here is immutable once created. Generation and manual capture both land in this authoritative registry.",
        )
        self.entry_table = QTableWidget(0, 7, table_box)
        self.entry_table.setHorizontalHeaderLabels(
            ["ID", "Category", "Value", "Kind", "Usage", "Created Via", "Created At"]
        )
        self.entry_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.entry_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.entry_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.entry_table.verticalHeader().setVisible(False)
        self.entry_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.entry_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.entry_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.entry_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.entry_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.entry_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.entry_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.entry_table.itemSelectionChanged.connect(self._load_entry_details)
        table_layout.addWidget(self.entry_table, 1)

        details_box, details_layout = _create_standard_section(
            page,
            "Usage and Details",
            "Inspect current links and creation metadata without editing immutable values in place.",
        )
        details_form = QFormLayout()
        _configure_standard_form_layout(details_form)
        self.entry_value_label = QLabel("No internal entry selected.", details_box)
        self.entry_value_label.setWordWrap(True)
        self.entry_category_label = QLabel("", details_box)
        self.entry_kind_label = QLabel("", details_box)
        self.entry_usage_label = QLabel("", details_box)
        self.entry_created_label = QLabel("", details_box)
        details_form.addRow("Value", self.entry_value_label)
        details_form.addRow("Category", self.entry_category_label)
        details_form.addRow("Kind", self.entry_kind_label)
        details_form.addRow("Usage", self.entry_usage_label)
        details_form.addRow("Created", self.entry_created_label)
        details_layout.addLayout(details_form)
        self.entry_usage_text = QPlainTextEdit(details_box)
        self.entry_usage_text.setReadOnly(True)
        self.entry_usage_text.setPlaceholderText(
            "Linked tracks, releases, and contracts appear here."
        )
        details_layout.addWidget(self.entry_usage_text, 1)
        self.assign_entry_button = QPushButton("Link Selected Value", details_box)
        self.assign_entry_button.clicked.connect(self._assign_selected_entry)
        self.assign_entry_button.setEnabled(False)
        details_layout.addWidget(self.assign_entry_button)
        self.delete_entry_button = QPushButton("Delete Selected Value", details_box)
        self.delete_entry_button.clicked.connect(self._delete_selected_entry)
        self.delete_entry_button.setEnabled(False)
        details_layout.addWidget(self.delete_entry_button)

        splitter.addWidget(table_box)
        splitter.addWidget(details_box)
        splitter.setSizes([760, 420])
        layout.addWidget(splitter, 1)
        self.tabs.addTab(page, "Internal Registry")

    def _build_external_tab(self) -> None:
        page = QWidget(self)
        page.setProperty("role", "workspaceCanvas")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(8)
        self.external_search_edit = QLineEdit(page)
        self.external_search_edit.setPlaceholderText("Search external catalog identifiers...")
        self.external_search_edit.textChanged.connect(self.refresh_external)
        toolbar.addWidget(self.external_search_edit, 1)
        promote_button = QPushButton("Promote External", page)
        promote_button.clicked.connect(self._promote_external)
        toolbar.addWidget(promote_button)
        reclassify_button = QPushButton("Reclassify Canonical Candidates", page)
        reclassify_button.clicked.connect(self._reclassify_external)
        toolbar.addWidget(reclassify_button)
        external_refresh_button = QPushButton("Refresh", page)
        external_refresh_button.clicked.connect(self.refresh)
        toolbar.addWidget(external_refresh_button)
        layout.addLayout(toolbar)

        splitter = QSplitter(Qt.Horizontal, page)
        splitter.setChildrenCollapsible(False)

        table_box, table_layout = _create_standard_section(
            page,
            "External Catalogs",
            "Foreign or non-conforming catalog identifiers stay here as shared values. Each row tracks total usage across linked tracks and releases.",
        )
        self.external_table = QTableWidget(0, 7, table_box)
        self.external_table.setHorizontalHeaderLabels(
            ["ID", "Value", "Usage", "Status", "Provenance", "Source", "Updated"]
        )
        self.external_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.external_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.external_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.external_table.verticalHeader().setVisible(False)
        self.external_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.external_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.external_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.external_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.external_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.external_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.external_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.external_table.itemSelectionChanged.connect(self._load_external_details)
        table_layout.addWidget(self.external_table, 1)

        details_box, details_layout = _create_standard_section(
            page,
            "Usage and Details",
            "Review classification notes and owner links before promoting anything into the internal registry.",
        )
        details_form = QFormLayout()
        _configure_standard_form_layout(details_form)
        self.external_value_label = QLabel("No external identifier selected.", details_box)
        self.external_value_label.setWordWrap(True)
        self.external_status_label = QLabel("", details_box)
        self.external_usage_label = QLabel("", details_box)
        self.external_anchor_label = QLabel("", details_box)
        self.external_source_label = QLabel("", details_box)
        self.external_reason_label = QLabel("", details_box)
        self.external_reason_label.setWordWrap(True)
        details_form.addRow("Value", self.external_value_label)
        details_form.addRow("Status", self.external_status_label)
        details_form.addRow("Usage", self.external_usage_label)
        details_form.addRow("First Seen", self.external_anchor_label)
        details_form.addRow("Source", self.external_source_label)
        details_form.addRow("Reason", self.external_reason_label)
        details_layout.addLayout(details_form)
        self.external_usage_text = QPlainTextEdit(details_box)
        self.external_usage_text.setReadOnly(True)
        self.external_usage_text.setPlaceholderText("Current owner links appear here.")
        details_layout.addWidget(self.external_usage_text, 1)

        splitter.addWidget(table_box)
        splitter.addWidget(details_box)
        splitter.setSizes([760, 420])
        layout.addWidget(splitter, 1)
        self.tabs.addTab(page, "External Catalogs")

    def _build_categories_tab(self) -> None:
        page = QWidget(self)
        page.setProperty("role", "workspaceCanvas")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        splitter = QSplitter(Qt.Horizontal, page)
        splitter.setChildrenCollapsible(False)

        table_box, table_layout = _create_standard_section(
            page,
            "Categories",
            "Built-in categories stay authoritative, while custom categories can be added for future internal code expansion.",
        )
        self.category_table = QTableWidget(0, 7, table_box)
        self.category_table.setHorizontalHeaderLabels(
            ["ID", "Name", "System Key", "Subject", "Generation", "Prefix", "Active"]
        )
        self.category_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.category_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.category_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.category_table.verticalHeader().setVisible(False)
        self.category_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.category_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.category_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.category_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.category_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.category_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.category_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.category_table.itemSelectionChanged.connect(self._load_category_form)
        table_layout.addWidget(self.category_table, 1)

        editor_box, editor_layout = _create_standard_section(
            page,
            "Category Editor",
            "Built-in categories allow prefix and active-state management. New categories can be created here without leaving the workspace.",
        )
        form = QFormLayout()
        _configure_standard_form_layout(form)
        self.category_name_edit = QLineEdit(page)
        self.category_prefix_edit = QLineEdit(page)
        self.category_system_key_label = QLabel("", page)
        self.category_subject_combo = QComboBox(page)
        for label, value in self._SUBJECT_KIND_CHOICES:
            self.category_subject_combo.addItem(label, value)
        self.category_generation_combo = QComboBox(page)
        for label, value in self._GENERATION_CHOICES:
            self.category_generation_combo.addItem(label, value)
        self.category_active_checkbox = QCheckBox("Category is active", page)
        form.addRow("Display Name", self.category_name_edit)
        form.addRow("System Key", self.category_system_key_label)
        form.addRow("Subject", self.category_subject_combo)
        form.addRow("Generation", self.category_generation_combo)
        form.addRow("Prefix", self.category_prefix_edit)
        form.addRow("", self.category_active_checkbox)
        editor_layout.addLayout(form)
        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(8)
        create_button = QPushButton("Create Category", page)
        create_button.clicked.connect(self._create_category)
        buttons.addWidget(create_button)
        save_button = QPushButton("Save Category Changes", page)
        save_button.clicked.connect(self._save_category)
        buttons.addWidget(save_button)
        self.delete_category_button = QPushButton("Delete Category", page)
        self.delete_category_button.clicked.connect(self._delete_category)
        self.delete_category_button.setEnabled(False)
        buttons.addWidget(self.delete_category_button)
        buttons.addStretch(1)
        editor_layout.addLayout(buttons)

        splitter.addWidget(table_box)
        splitter.addWidget(editor_box)
        splitter.setSizes([760, 360])
        layout.addWidget(splitter, 1)
        self.tabs.addTab(page, "Categories")

    def refresh(self) -> None:
        self.refresh_categories()
        self.refresh_entries()
        self.refresh_external()
        self._set_status("Code Registry refreshed.")

    def refresh_categories(self) -> None:
        service = self._service()
        self.category_table.setRowCount(0)
        self._category_row_ids = []
        self.entry_category_filter.blockSignals(True)
        self.entry_category_filter.clear()
        self.entry_category_filter.addItem("All Categories", None)
        self.entry_category_filter.blockSignals(False)
        if service is None:
            return
        for category in service.list_categories():
            row = self.category_table.rowCount()
            self.category_table.insertRow(row)
            self._category_row_ids.append(int(category.id))
            values = [
                str(category.id),
                category.display_name,
                category.system_key or "",
                category.subject_kind,
                category.generation_strategy,
                category.prefix or "",
                "Yes" if category.active_flag else "No",
            ]
            for column, value in enumerate(values):
                self.category_table.setItem(row, column, QTableWidgetItem(value))
            self.entry_category_filter.addItem(category.display_name, int(category.id))
        self.category_table.resizeColumnsToContents()

    def refresh_entries(self) -> None:
        service = self._service()
        self.entry_table.setRowCount(0)
        self._entry_row_ids = []
        if service is None:
            return
        entries = service.list_entries(
            category_id=self.entry_category_filter.currentData(),
            search_text=self.entry_search_edit.text().strip() or None,
            include_unused=self.include_unused_checkbox.isChecked(),
        )
        for entry in entries:
            row = self.entry_table.rowCount()
            self.entry_table.insertRow(row)
            self._entry_row_ids.append(int(entry.id))
            values = [
                str(entry.id),
                entry.category_display_name,
                entry.value,
                entry.entry_kind,
                str(entry.usage_count),
                entry.created_via or "",
                entry.created_at or "",
            ]
            for column, value in enumerate(values):
                self.entry_table.setItem(row, column, QTableWidgetItem(value))
        self.entry_table.resizeColumnsToContents()
        self._load_entry_details()

    def refresh_external(self) -> None:
        service = self._service()
        self.external_table.setRowCount(0)
        self._external_row_ids = []
        if service is None:
            return
        records = service.list_external_catalog_identifiers(
            search_text=self.external_search_edit.text().strip() or None
        )
        for record in records:
            row = self.external_table.rowCount()
            self.external_table.insertRow(row)
            self._external_row_ids.append(int(record.id))
            values = [
                str(record.id),
                record.value,
                str(record.usage_count),
                record.classification_status,
                record.provenance_kind,
                record.source_label or "",
                record.updated_at or "",
            ]
            for column, value in enumerate(values):
                self.external_table.setItem(row, column, QTableWidgetItem(value))
        self.external_table.resizeColumnsToContents()
        self._load_external_details()

    def _selected_row_id(self, table: QTableWidget, row_ids: list[int]) -> int | None:
        row = table.currentRow()
        if row < 0 or row >= len(row_ids):
            return None
        return int(row_ids[row])

    def _load_entry_details(self) -> None:
        service = self._service()
        entry_id = self._selected_row_id(self.entry_table, self._entry_row_ids)
        if service is None or entry_id is None:
            self._selected_entry_id = None
            self.entry_value_label.setText("No internal entry selected.")
            self.entry_category_label.setText("")
            self.entry_kind_label.setText("")
            self.entry_usage_label.setText("")
            self.entry_created_label.setText("")
            self.entry_usage_text.clear()
            self.assign_entry_button.setEnabled(False)
            self.delete_entry_button.setEnabled(False)
            return
        entry = service.fetch_entry(entry_id)
        usage = service.usage_for_entry(entry_id)
        if entry is None:
            return
        self._selected_entry_id = int(entry.id)
        self.entry_value_label.setText(entry.value)
        self.entry_category_label.setText(entry.category_display_name)
        self.entry_kind_label.setText(entry.entry_kind)
        self.entry_usage_label.setText(str(len(usage)))
        created_bits = [bit for bit in [entry.created_at, entry.created_via] if bit]
        self.entry_created_label.setText(" / ".join(created_bits))
        self.entry_usage_text.setPlainText(self._usage_text(usage))
        self.assign_entry_button.setEnabled(True)
        self.delete_entry_button.setEnabled(
            entry.category_system_key == BUILTIN_CATEGORY_REGISTRY_SHA256_KEY and not usage
        )

    def _load_external_details(self) -> None:
        service = self._service()
        external_id = self._selected_row_id(self.external_table, self._external_row_ids)
        if service is None or external_id is None:
            self.external_value_label.setText("No external identifier selected.")
            self.external_status_label.setText("")
            self.external_usage_label.setText("")
            self.external_anchor_label.setText("")
            self.external_source_label.setText("")
            self.external_reason_label.setText("")
            self.external_usage_text.clear()
            return
        record = service.fetch_external_catalog_identifier(external_id)
        usage = service.usage_for_external_identifier(external_id)
        if record is None:
            return
        self.external_value_label.setText(record.value)
        self.external_status_label.setText(record.classification_status)
        self.external_usage_label.setText(str(record.usage_count))
        self.external_anchor_label.setText(
            (
                f"{record.subject_kind} #{record.subject_id}"
                if record.subject_kind and int(record.subject_id or 0) > 0
                else "Shared external registry value"
            )
        )
        self.external_source_label.setText(record.source_label or record.provenance_kind)
        self.external_reason_label.setText(record.classification_reason or "")
        self.external_usage_text.setPlainText(self._usage_text(usage))

    @staticmethod
    def _usage_text(usage) -> str:
        if not usage:
            return "No current owner links."
        return "\n".join(
            f"{item.subject_kind.title()} #{item.subject_id} / {item.field_name}: {item.label}"
            for item in usage
        )

    def _load_category_form(self) -> None:
        service = self._service()
        category_id = self._selected_row_id(self.category_table, self._category_row_ids)
        self._suspend_category_form = True
        try:
            if service is None or category_id is None:
                self._reset_category_form()
                return
            category = service.fetch_category(category_id)
            if category is None:
                return
            self.category_name_edit.setText(category.display_name)
            self.category_system_key_label.setText(category.system_key or "Custom")
            self.category_prefix_edit.setText(category.prefix or "")
            self.category_active_checkbox.setChecked(bool(category.active_flag))
            self._select_combo_data(self.category_subject_combo, category.subject_kind)
            self._select_combo_data(self.category_generation_combo, category.generation_strategy)
            self.category_name_edit.setReadOnly(bool(category.is_system))
            self.category_subject_combo.setEnabled(not bool(category.is_system))
            self.category_generation_combo.setEnabled(not bool(category.is_system))
            self.delete_category_button.setEnabled(not bool(category.is_system))
        finally:
            self._suspend_category_form = False

    def _reset_category_form(self) -> None:
        self.category_name_edit.clear()
        self.category_name_edit.setReadOnly(False)
        self.category_system_key_label.setText("")
        self.category_prefix_edit.clear()
        self.category_active_checkbox.setChecked(True)
        self.category_subject_combo.setEnabled(True)
        self.category_generation_combo.setEnabled(True)
        self.category_subject_combo.setCurrentIndex(0)
        self.category_generation_combo.setCurrentIndex(0)
        self.delete_category_button.setEnabled(False)

    @staticmethod
    def _select_combo_data(combo: QComboBox, value: object | None) -> None:
        index = combo.findData(value)
        combo.setCurrentIndex(index if index >= 0 else 0)

    def _create_category(self) -> None:
        service = self._service()
        if service is None:
            return
        try:
            category_id = service.create_category(
                CodeRegistryCategoryPayload(
                    display_name=self.category_name_edit.text().strip(),
                    subject_kind=str(
                        self.category_subject_combo.currentData() or SUBJECT_KIND_GENERIC
                    ),
                    generation_strategy=str(
                        self.category_generation_combo.currentData() or GENERATION_STRATEGY_MANUAL
                    ),
                    prefix=self.category_prefix_edit.text().strip() or None,
                    active_flag=self.category_active_checkbox.isChecked(),
                )
            )
        except Exception as exc:
            QMessageBox.critical(self, "Code Registry", str(exc))
            return
        self.refresh_categories()
        self._focus_category(category_id)
        self._set_status("Created a new code-registry category.")

    def _save_category(self) -> None:
        service = self._service()
        category_id = self._selected_row_id(self.category_table, self._category_row_ids)
        if service is None or category_id is None:
            return
        category = service.fetch_category(category_id)
        if category is None:
            return
        try:
            service.update_category(
                category_id,
                display_name=(
                    self.category_name_edit.text().strip() or None
                    if not bool(category.is_system)
                    else None
                ),
                prefix=self.category_prefix_edit.text().strip() or None,
                active_flag=self.category_active_checkbox.isChecked(),
            )
        except Exception as exc:
            QMessageBox.critical(self, "Code Registry", str(exc))
            return
        self.refresh()
        self._focus_category(category_id)
        self._set_status("Saved category changes.")

    def _focus_category(self, category_id: int) -> None:
        for row, current_id in enumerate(self._category_row_ids):
            if int(current_id) != int(category_id):
                continue
            self.category_table.selectRow(row)
            return

    def _focus_entry(self, entry_id: int) -> None:
        for row, current_id in enumerate(self._entry_row_ids):
            if int(current_id) != int(entry_id):
                continue
            self.entry_table.selectRow(row)
            return

    def _generate_catalog_code(self) -> None:
        service = self._service()
        if service is None:
            return
        try:
            result = service.generate_next_code(
                system_key=BUILTIN_CATEGORY_CATALOG_NUMBER,
                created_via="workspace.generate",
            )
        except Exception as exc:
            QMessageBox.critical(self, "Code Registry", str(exc))
            return
        self.refresh()
        self._focus_entry(result.entry.id)
        self._set_status(f"Generated internal catalog code {result.entry.value}.")

    def _generate_registry_hash(self) -> None:
        service = self._service()
        if service is None:
            return
        try:
            result = service.generate_sha256_key(
                system_key=BUILTIN_CATEGORY_REGISTRY_SHA256_KEY,
                created_via="workspace.generate",
            )
        except Exception as exc:
            QMessageBox.critical(self, "Code Registry", str(exc))
            return
        self.refresh()
        self._focus_entry(result.entry.id)
        self._set_status("Generated a new Registry SHA-256 Key.")

    def _promote_external(self) -> None:
        service = self._service()
        external_id = self._selected_row_id(self.external_table, self._external_row_ids)
        if service is None or external_id is None:
            return
        try:
            entry = service.promote_external_catalog_identifier(
                external_id,
                created_via="workspace.promote",
            )
        except Exception as exc:
            QMessageBox.critical(self, "Code Registry", str(exc))
            return
        self.refresh()
        self._set_status(
            f"Promoted external catalog value into internal registry entry {entry.value}."
        )

    def _reclassify_external(self) -> None:
        service = self._service()
        if service is None:
            return
        try:
            result = service.reclassify_external_catalog_identifiers()
        except Exception as exc:
            QMessageBox.critical(self, "Code Registry", str(exc))
            return
        self.refresh()
        self._set_status(
            "Reclassified external identifiers. "
            + ", ".join(f"{key}={int(value)}" for key, value in sorted(result.items()))
        )

    def _delete_category(self) -> None:
        service = self._service()
        category_id = self._selected_row_id(self.category_table, self._category_row_ids)
        if service is None or category_id is None:
            return
        category = service.fetch_category(category_id)
        if category is None:
            return
        confirm = QMessageBox.question(
            self,
            "Delete Category",
            (
                f"Delete custom category '{category.display_name}'?\n\n"
                "This removes the category definition itself. Issued internal registry entries "
                "must remain immutable, so categories with existing entries cannot be deleted."
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            service.delete_category(category_id)
        except Exception as exc:
            QMessageBox.critical(self, "Code Registry", str(exc))
            return
        self.refresh()
        self.category_table.clearSelection()
        self._load_category_form()
        self._set_status(f"Deleted custom category '{category.display_name}'.")

    def _assign_selected_entry(self) -> None:
        service = self._service()
        entry_id = self._selected_entry_id
        if service is None or entry_id is None:
            return
        entry = service.fetch_entry(int(entry_id))
        if entry is None:
            return
        dialog = _RegistryOwnerAssignmentDialog(
            service_provider=self.service_provider,
            entry_id=entry.id,
            entry_value=entry.value,
            parent=self,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        assignment = dialog.assignment()
        if assignment is None:
            return
        owner_kind, owner_id = assignment
        try:
            service.assign_entry_to_owner(
                entry.id,
                owner_kind=str(owner_kind),
                owner_id=int(owner_id),
            )
        except Exception as exc:
            QMessageBox.critical(self, "Code Registry", str(exc))
            return
        self.refresh()
        self._focus_entry(entry.id)
        self._set_status(
            f"Linked internal registry value {entry.value} to {str(owner_kind).title()} #{int(owner_id)}."
        )

    def _delete_selected_entry(self) -> None:
        service = self._service()
        entry_id = self._selected_entry_id
        if service is None or entry_id is None:
            return
        entry = service.fetch_entry(int(entry_id))
        if entry is None:
            return
        confirm = QMessageBox.question(
            self,
            "Delete Registry Value",
            (
                f"Delete unused Registry SHA-256 Key '{entry.value}'?\n\n"
                "This is only allowed while the key is not linked to any contract."
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            service.delete_entry(entry.id)
        except Exception as exc:
            QMessageBox.critical(self, "Code Registry", str(exc))
            return
        self.refresh()
        self.entry_table.clearSelection()
        self._load_entry_details()
        self._set_status(f"Deleted unused Registry SHA-256 Key {entry.value}.")

    def _set_status(self, text: str) -> None:
        self.status_label.setText(str(text or "").strip())

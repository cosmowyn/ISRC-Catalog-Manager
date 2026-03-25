"""Workspace panels for contract template placeholder tools."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
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
    _create_action_button_cluster,
    _create_standard_section,
)

from .models import ContractTemplateCatalogEntry


class ContractTemplateWorkspacePanel(QWidget):
    """Docked workspace for symbol generation and placeholder dictionary browsing."""

    TAB_ORDER = ("symbols",)

    def __init__(self, *, catalog_service_provider, parent=None):
        super().__init__(parent)
        self.catalog_service_provider = catalog_service_provider
        self._visible_entries: list[ContractTemplateCatalogEntry] = []
        self.setObjectName("contractTemplateWorkspacePanel")
        _apply_standard_widget_chrome(self, "contractTemplateWorkspacePanel")

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(14)
        _add_standard_dialog_header(
            root,
            self,
            title="Contract Templates",
            subtitle=(
                "Generate copy-ready placeholder symbols from authoritative app data, "
                "then use the manual helper when a template needs user-supplied fields."
            ),
        )

        self.workspace_tabs = QTabWidget(self)
        self.workspace_tabs.setObjectName("contractTemplateWorkspaceTabs")
        self.workspace_tabs.setDocumentMode(True)
        root.addWidget(self.workspace_tabs, 1)

        self.symbol_generator_tab = QWidget(self.workspace_tabs)
        self.symbol_generator_tab.setObjectName("contractTemplateSymbolGeneratorTab")
        self.workspace_tabs.addTab(self.symbol_generator_tab, "Symbol Generator")

        tab_layout = QVBoxLayout(self.symbol_generator_tab)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        tab_layout.setSpacing(14)

        splitter = QSplitter(Qt.Horizontal, self.symbol_generator_tab)
        splitter.setChildrenCollapsible(False)
        tab_layout.addWidget(splitter, 1)

        left_container = QWidget(splitter)
        left_layout = QVBoxLayout(left_container)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(14)

        controls_box, controls_layout = _create_standard_section(
            self.symbol_generator_tab,
            "Symbol Generator",
            "Filter the known database symbol catalog and copy canonical placeholders "
            "into your external document template.",
        )
        search_row = QHBoxLayout()
        search_row.setContentsMargins(0, 0, 0, 0)
        search_row.setSpacing(8)
        self.search_edit = QLineEdit(controls_box)
        self.search_edit.setObjectName("contractTemplateCatalogSearchEdit")
        self.search_edit.setPlaceholderText(
            "Search labels, namespaces, symbols, or descriptions..."
        )
        self.search_edit.textChanged.connect(self.refresh)
        search_row.addWidget(self.search_edit, 1)
        self.namespace_combo = QComboBox(controls_box)
        self.namespace_combo.setObjectName("contractTemplateNamespaceCombo")
        self.namespace_combo.currentIndexChanged.connect(self.refresh)
        search_row.addWidget(self.namespace_combo)
        controls_layout.addLayout(search_row)

        refresh_button = QPushButton("Refresh", controls_box)
        refresh_button.clicked.connect(self.refresh)
        copy_selected_button = QPushButton("Copy Selected Symbol", controls_box)
        copy_selected_button.setObjectName("contractTemplateCopySelectedButton")
        copy_selected_button.clicked.connect(self.copy_selected_symbol)
        copy_visible_button = QPushButton("Copy Visible Symbols", controls_box)
        copy_visible_button.setObjectName("contractTemplateCopyVisibleButton")
        copy_visible_button.clicked.connect(self.copy_visible_symbols)
        self.symbol_actions_cluster = _create_action_button_cluster(
            controls_box,
            [refresh_button, copy_selected_button, copy_visible_button],
            columns=2,
            min_button_width=170,
            span_last_row=True,
        )
        self.symbol_actions_cluster.setObjectName("contractTemplateSymbolActionsCluster")
        controls_layout.addWidget(self.symbol_actions_cluster)
        self.status_label = QLabel(
            "Open a profile to browse the contract template symbol catalog."
        )
        self.status_label.setWordWrap(True)
        self.status_label.setProperty("role", "secondary")
        controls_layout.addWidget(self.status_label)
        left_layout.addWidget(controls_box)

        table_box, table_layout = _create_standard_section(
            self.symbol_generator_tab,
            "Known Database Symbols",
            "Each symbol is canonical, copy-ready, and tied to a real field or "
            "custom-field definition already present in the app.",
        )
        self.table = QTableWidget(0, 5, table_box)
        self.table.setObjectName("contractTemplateCatalogTable")
        self.table.setHorizontalHeaderLabels(
            ["Namespace", "Field", "Type", "Scope", "Symbol"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self._update_selected_details)
        self.table.doubleClicked.connect(lambda _index: self.copy_selected_symbol())
        table_layout.addWidget(self.table, 1)
        left_layout.addWidget(table_box, 1)
        splitter.addWidget(left_container)

        right_container = QWidget(splitter)
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(14)

        selected_box, selected_layout = _create_standard_section(
            self.symbol_generator_tab,
            "Selected Symbol",
            "Review the selected symbol's type, scope, source, and canonical text "
            "before copying it into your template.",
        )
        selected_form = QFormLayout()
        selected_form.setLabelAlignment(Qt.AlignLeft | Qt.AlignTop)
        selected_form.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
        selected_form.setHorizontalSpacing(12)
        selected_form.setVerticalSpacing(10)
        self.selected_label_value = QLabel("No symbol selected.", selected_box)
        self.selected_label_value.setWordWrap(True)
        self.selected_namespace_value = QLabel("-", selected_box)
        self.selected_type_value = QLabel("-", selected_box)
        self.selected_scope_value = QLabel("-", selected_box)
        self.selected_source_value = QLabel("-", selected_box)
        self.selected_symbol_edit = QLineEdit(selected_box)
        self.selected_symbol_edit.setObjectName("contractTemplateSelectedSymbolEdit")
        self.selected_symbol_edit.setReadOnly(True)
        selected_form.addRow("Label", self.selected_label_value)
        selected_form.addRow("Namespace", self.selected_namespace_value)
        selected_form.addRow("Field Type", self.selected_type_value)
        selected_form.addRow("Scope", self.selected_scope_value)
        selected_form.addRow("Source", self.selected_source_value)
        selected_form.addRow("Canonical Symbol", self.selected_symbol_edit)
        selected_layout.addLayout(selected_form)
        self.detail_resolver_label = QLabel("Resolver Target: -", selected_box)
        self.detail_resolver_label.setWordWrap(True)
        self.detail_source_label = QLabel("Source Kind: -", selected_box)
        self.detail_source_label.setWordWrap(True)
        self.detail_source_label.setProperty("role", "secondary")
        selected_layout.addWidget(self.detail_resolver_label)
        selected_layout.addWidget(self.detail_source_label)
        self.selected_description_value = QLabel(
            "Choose a symbol to see more detail.", selected_box
        )
        self.selected_description_value.setWordWrap(True)
        self.selected_description_value.setProperty("role", "secondary")
        selected_layout.addWidget(self.selected_description_value)
        right_layout.addWidget(selected_box)

        manual_box, manual_layout = _create_standard_section(
            self.symbol_generator_tab,
            "Manual Symbol Helper",
            "Use this when a value is intentionally not pulled from the current "
            "database. The helper keeps the token parser-safe and copy-ready.",
        )
        manual_form = QFormLayout()
        manual_form.setLabelAlignment(Qt.AlignLeft | Qt.AlignTop)
        manual_form.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
        manual_form.setHorizontalSpacing(12)
        manual_form.setVerticalSpacing(10)
        self.manual_key_edit = QLineEdit(manual_box)
        self.manual_key_edit.setObjectName("contractTemplateManualKeyEdit")
        self.manual_key_edit.setPlaceholderText("Example: License Date")
        self.manual_key_edit.textChanged.connect(self._refresh_manual_symbol_preview)
        self.manual_symbol_edit = QLineEdit(manual_box)
        self.manual_symbol_edit.setObjectName("contractTemplateManualSymbolEdit")
        self.manual_symbol_edit.setReadOnly(True)
        manual_form.addRow("Human Label", self.manual_key_edit)
        manual_form.addRow("Generated Symbol", self.manual_symbol_edit)
        manual_layout.addLayout(manual_form)
        self.manual_feedback_label = QLabel(
            "Generated manual symbols use the canonical Phase 1 grammar: "
            "{{manual.your_field_name}}.",
            manual_box,
        )
        self.manual_feedback_label.setWordWrap(True)
        self.manual_feedback_label.setProperty("role", "secondary")
        manual_layout.addWidget(self.manual_feedback_label)
        copy_manual_button = QPushButton("Copy Manual Symbol", manual_box)
        copy_manual_button.setObjectName("contractTemplateCopyManualButton")
        copy_manual_button.clicked.connect(self.copy_manual_symbol)
        manual_layout.addWidget(copy_manual_button)
        right_layout.addWidget(manual_box)

        guidance_box, guidance_layout = _create_standard_section(
            self.symbol_generator_tab,
            "Generator Notes",
            "These symbols are for template authoring only. Layout still lives in "
            "Word or Pages, while later phases will handle fill forms, drafts, and export.",
        )
        guidance = QLabel(
            "Use db symbols for authoritative catalog values. Use manual symbols only "
            "when a template needs a user-supplied value that does not already live in "
            "the database.",
            guidance_box,
        )
        guidance.setWordWrap(True)
        guidance.setProperty("role", "secondary")
        guidance_layout.addWidget(guidance)
        right_layout.addWidget(guidance_box)
        right_layout.addStretch(1)
        splitter.addWidget(right_container)

        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 4)

        _apply_compact_dialog_control_heights(self)
        self._populate_namespace_combo(())
        self._refresh_manual_symbol_preview()
        self.refresh()
        self.focus_tab("symbols")

    def _catalog_service(self):
        return self.catalog_service_provider()

    def focus_tab(self, tab_name: str = "symbols") -> None:
        del tab_name
        self.workspace_tabs.setCurrentWidget(self.symbol_generator_tab)

    def focus_namespace(self, namespace: str | None = None) -> None:
        clean_namespace = str(namespace or "").strip().lower() or None
        target_index = 0
        for index in range(self.namespace_combo.count()):
            if self.namespace_combo.itemData(index) == clean_namespace:
                target_index = index
                break
        self.namespace_combo.setCurrentIndex(target_index)
        self.refresh()

    def refresh(self) -> None:
        selected_symbol = self._selected_symbol()
        service = self._catalog_service()
        if service is None:
            self._visible_entries = []
            self._populate_namespace_combo(())
            self.table.setRowCount(0)
            self.status_label.setText(
                "Open a profile to browse the contract template symbol catalog."
            )
            self._update_selected_details()
            return

        current_namespace = self.namespace_combo.currentData()
        namespaces = service.list_namespaces()
        self._populate_namespace_combo(namespaces, selected_namespace=current_namespace)
        self._visible_entries = service.list_known_symbols(
            search_text=self.search_edit.text(),
            namespace=self.namespace_combo.currentData(),
        )
        self.table.setRowCount(0)
        for entry in self._visible_entries:
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = [
                str(entry.namespace or ""),
                entry.display_label,
                entry.field_type.replace("_", " "),
                self._scope_label(entry),
                entry.canonical_symbol,
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 4:
                    item.setData(Qt.UserRole, entry.canonical_symbol)
                self.table.setItem(row, column, item)
        self.table.resizeColumnsToContents()
        count = len(self._visible_entries)
        self.status_label.setText(
            f"Showing {count} known symbol{'s' if count != 1 else ''}."
            if count
            else "No known symbols match the current filters."
        )
        self._restore_selection(selected_symbol)
        self._update_selected_details()

    def copy_selected_symbol(self) -> None:
        entry = self._selected_entry()
        if entry is None:
            return
        self._copy_to_clipboard(entry.canonical_symbol)

    def copy_visible_symbols(self) -> None:
        if not self._visible_entries:
            return
        self._copy_to_clipboard(
            "\n".join(item.canonical_symbol for item in self._visible_entries)
        )

    def copy_manual_symbol(self) -> None:
        text = self.manual_symbol_edit.text().strip()
        if not text:
            return
        self._copy_to_clipboard(text)

    def _populate_namespace_combo(
        self,
        namespaces: tuple[str, ...],
        *,
        selected_namespace: str | None = None,
    ) -> None:
        current = str(selected_namespace or "").strip().lower() or None
        self.namespace_combo.blockSignals(True)
        self.namespace_combo.clear()
        self.namespace_combo.addItem("All Namespaces", None)
        selected_index = 0
        for index, namespace in enumerate(namespaces, start=1):
            label = namespace.replace("_", " ").title()
            self.namespace_combo.addItem(label, namespace)
            if current == namespace:
                selected_index = index
        self.namespace_combo.setCurrentIndex(selected_index)
        self.namespace_combo.blockSignals(False)

    def _selected_symbol(self) -> str | None:
        selection_model = self.table.selectionModel()
        if selection_model is None:
            return None
        rows = selection_model.selectedRows()
        if not rows:
            return None
        item = self.table.item(rows[0].row(), 4)
        if item is None:
            return None
        return str(item.data(Qt.UserRole) or item.text() or "").strip() or None

    def _restore_selection(self, canonical_symbol: str | None) -> None:
        if canonical_symbol:
            for row in range(self.table.rowCount()):
                item = self.table.item(row, 4)
                if item is None:
                    continue
                candidate = str(item.data(Qt.UserRole) or item.text() or "").strip()
                if candidate == canonical_symbol:
                    self.table.selectRow(row)
                    return
        if self.table.rowCount() > 0:
            self.table.selectRow(0)
        else:
            self.table.clearSelection()

    def _selected_entry(self) -> ContractTemplateCatalogEntry | None:
        canonical_symbol = self._selected_symbol()
        if not canonical_symbol:
            return None
        for entry in self._visible_entries:
            if entry.canonical_symbol == canonical_symbol:
                return entry
        return None

    def _update_selected_details(self) -> None:
        entry = self._selected_entry()
        if entry is None:
            self.selected_label_value.setText("No symbol selected.")
            self.selected_namespace_value.setText("-")
            self.selected_type_value.setText("-")
            self.selected_scope_value.setText("-")
            self.selected_source_value.setText("-")
            self.selected_symbol_edit.clear()
            self.detail_resolver_label.setText("Resolver Target: -")
            self.detail_source_label.setText("Source Kind: -")
            self.selected_description_value.setText("Choose a symbol to see more detail.")
            return

        self.selected_label_value.setText(entry.display_label)
        self.selected_namespace_value.setText(str(entry.namespace or "-"))
        self.selected_type_value.setText(entry.field_type.replace("_", " "))
        self.selected_scope_value.setText(self._scope_label(entry))
        source_parts = [part for part in (entry.source_table, entry.source_column) if part]
        self.selected_source_value.setText(".".join(source_parts) if source_parts else "-")
        self.selected_symbol_edit.setText(entry.canonical_symbol)
        resolver_parts = []
        if entry.scope_entity_type:
            resolver_parts.append(
                str(entry.scope_entity_type).replace("_", " ").title()
            )
        if entry.scope_policy:
            resolver_parts.append(self._scope_label(entry))
        resolver_text = " | ".join(resolver_parts) if resolver_parts else "-"
        self.detail_resolver_label.setText(f"Resolver Target: {resolver_text}")
        self.detail_source_label.setText(f"Source Kind: {entry.source_kind}")
        description = str(entry.description or "").strip()
        if entry.custom_field_id is not None:
            custom_field_note = f"Custom Field ID: {entry.custom_field_id}"
            description = (
                f"{description}\n{custom_field_note}" if description else custom_field_note
            )
        if entry.options:
            option_text = ", ".join(entry.options)
            description = (
                f"{description}\nOptions: {option_text}"
                if description
                else f"Options: {option_text}"
            )
        self.selected_description_value.setText(
            description or "No additional guidance recorded."
        )

    def _refresh_manual_symbol_preview(self) -> None:
        service = self._catalog_service()
        raw_value = self.manual_key_edit.text()
        if service is None:
            self.manual_symbol_edit.clear()
            self.manual_feedback_label.setText(
                "Open a profile to use the manual placeholder helper."
            )
            return
        if not raw_value.strip():
            self.manual_symbol_edit.clear()
            self.manual_feedback_label.setText(
                "Generated manual symbols use the canonical Phase 1 grammar: "
                "{{manual.your_field_name}}."
            )
            return
        try:
            symbol = service.build_manual_symbol(raw_value)
        except ValueError as exc:
            self.manual_symbol_edit.clear()
            self.manual_feedback_label.setText(str(exc))
            return
        self.manual_symbol_edit.setText(symbol)
        self.manual_feedback_label.setText(
            "Manual symbols are parser-safe and remain outside the authoritative "
            "DB-backed catalog."
        )

    @staticmethod
    def _scope_label(entry: ContractTemplateCatalogEntry) -> str:
        mapping = {
            "track_context": "Track context",
            "release_selection_required": "Needs release selection",
            "work_selection_required": "Needs work selection",
            "contract_selection_required": "Needs contract selection",
            "party_selection_required": "Needs party selection",
            "right_selection_required": "Needs right selection",
            "asset_selection_required": "Needs asset selection",
        }
        return mapping.get(str(entry.scope_policy or ""), str(entry.scope_policy or "-"))

    def _copy_to_clipboard(self, text: str) -> None:
        app = QApplication.instance()
        if app is None:
            return
        clipboard = app.clipboard()
        if clipboard is None:
            return
        clipboard.setText(str(text or ""))

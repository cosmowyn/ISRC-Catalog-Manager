"""Workspace panels for contract template placeholder tools."""

from __future__ import annotations

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from isrc_manager.file_storage import STORAGE_MODE_DATABASE, STORAGE_MODE_MANAGED_FILE
from isrc_manager.ui_common import (
    _add_standard_dialog_header,
    _apply_compact_dialog_control_heights,
    _apply_standard_widget_chrome,
    _configure_standard_form_layout,
    _create_action_button_cluster,
    _create_scrollable_dialog_content,
    _create_standard_section,
)

from .models import (
    ContractTemplateCatalogEntry,
    ContractTemplateDraftPayload,
    ContractTemplateDraftRecord,
    ContractTemplateFormDefinition,
    ContractTemplateFormManualField,
    ContractTemplateFormSelectorField,
)


def _clean_text(value: object | None) -> str | None:
    clean = str(value or "").strip()
    return clean or None


class ContractTemplateWorkspacePanel(QWidget):
    """Docked workspace for placeholder generation and dynamic fill forms."""

    TAB_ORDER = ("symbols", "fill")

    def __init__(
        self,
        *,
        catalog_service_provider,
        template_service_provider=None,
        form_service_provider=None,
        parent=None,
    ):
        super().__init__(parent)
        self.catalog_service_provider = catalog_service_provider
        self.template_service_provider = template_service_provider or (lambda: None)
        self.form_service_provider = form_service_provider or (lambda: None)
        self._visible_entries: list[ContractTemplateCatalogEntry] = []
        self._visible_drafts: list[ContractTemplateDraftRecord] = []
        self._fill_definition: ContractTemplateFormDefinition | None = None
        self._loaded_draft_id: int | None = None
        self._fill_dirty = False
        self._suspend_fill_updates = False
        self._fill_type_overrides: dict[str, str] = {}
        self._fill_payload_extras: dict[str, object] = {}
        self.selector_widgets: dict[str, QWidget] = {}
        self.manual_widgets: dict[str, QWidget] = {}
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
                "import scanned template revisions, fill detected placeholders, and "
                "resume editable drafts through one coherent workspace."
            ),
        )

        self.workspace_tabs = QTabWidget(self)
        self.workspace_tabs.setObjectName("contractTemplateWorkspaceTabs")
        self.workspace_tabs.setDocumentMode(True)
        root.addWidget(self.workspace_tabs, 1)

        self._build_symbol_generator_tab()
        self._build_fill_form_tab()

        _apply_compact_dialog_control_heights(self)
        self._populate_namespace_combo(())
        self._refresh_manual_symbol_preview()
        self.refresh()
        self.focus_tab("symbols")

    def _build_symbol_generator_tab(self) -> None:
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
        _configure_standard_form_layout(selected_form)
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
        _configure_standard_form_layout(manual_form)
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
            "Word or Pages, while this workspace now also builds fill controls from "
            "scanned placeholder inventories.",
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

    def _build_fill_form_tab(self) -> None:
        self.fill_form_tab = QWidget(self.workspace_tabs)
        self.fill_form_tab.setObjectName("contractTemplateFillFormTab")
        self.workspace_tabs.addTab(self.fill_form_tab, "Fill Form")

        scroll_area, _scroll_content, scroll_layout = _create_scrollable_dialog_content(
            self.fill_form_tab,
            page=self.fill_form_tab,
        )
        scroll_area.setObjectName("contractTemplateFillFormScrollArea")

        selection_box, selection_layout = _create_standard_section(
            self.fill_form_tab,
            "Template Revision",
            "Choose a scanned template revision, then let the app synthesize one "
            "editable control per detected placeholder.",
        )
        selection_form = QFormLayout()
        _configure_standard_form_layout(selection_form)
        self.fill_template_combo = QComboBox(selection_box)
        self.fill_template_combo.setObjectName("contractTemplateFillTemplateCombo")
        self.fill_template_combo.currentIndexChanged.connect(self._on_fill_template_changed)
        self.fill_revision_combo = QComboBox(selection_box)
        self.fill_revision_combo.setObjectName("contractTemplateFillRevisionCombo")
        self.fill_revision_combo.currentIndexChanged.connect(self._on_fill_revision_changed)
        selection_form.addRow("Template", self.fill_template_combo)
        selection_form.addRow("Revision", self.fill_revision_combo)
        selection_layout.addLayout(selection_form)

        refresh_fill_button = QPushButton("Refresh Fill Form", selection_box)
        refresh_fill_button.setObjectName("contractTemplateFillRefreshButton")
        refresh_fill_button.clicked.connect(self.refresh_fill_form)
        selection_layout.addWidget(refresh_fill_button)

        self.fill_status_label = QLabel(
            "Open a profile to browse imported template revisions."
        )
        self.fill_status_label.setWordWrap(True)
        self.fill_status_label.setObjectName("contractTemplateFillStatusLabel")
        self.fill_warning_label = QLabel("")
        self.fill_warning_label.setWordWrap(True)
        self.fill_warning_label.setProperty("role", "secondary")
        self.fill_warning_label.setObjectName("contractTemplateFillWarningLabel")
        selection_layout.addWidget(self.fill_status_label)
        selection_layout.addWidget(self.fill_warning_label)
        scroll_layout.addWidget(selection_box)

        draft_box, draft_layout = _create_standard_section(
            self.fill_form_tab,
            "Draft Workspace",
            "Save the current editable state for this revision, reopen it later, and "
            "choose whether the draft payload stays embedded in the database or lives "
            "as a managed file.",
        )
        draft_form = QFormLayout()
        _configure_standard_form_layout(draft_form)
        self.fill_draft_name_edit = QLineEdit(draft_box)
        self.fill_draft_name_edit.setObjectName("contractTemplateDraftNameEdit")
        self.fill_draft_name_edit.setPlaceholderText("Draft name")
        self.fill_draft_storage_combo = QComboBox(draft_box)
        self.fill_draft_storage_combo.setObjectName("contractTemplateDraftStorageCombo")
        self.fill_draft_storage_combo.addItem("Database Embedded", STORAGE_MODE_DATABASE)
        self.fill_draft_storage_combo.addItem("Managed File", STORAGE_MODE_MANAGED_FILE)
        self.fill_draft_combo = QComboBox(draft_box)
        self.fill_draft_combo.setObjectName("contractTemplateDraftCombo")
        self.fill_draft_combo.currentIndexChanged.connect(self._on_fill_draft_changed)
        draft_form.addRow("Draft Name", self.fill_draft_name_edit)
        draft_form.addRow("Storage Mode", self.fill_draft_storage_combo)
        draft_form.addRow("Saved Drafts", self.fill_draft_combo)
        draft_layout.addLayout(draft_form)

        refresh_drafts_button = QPushButton("Refresh Drafts", draft_box)
        refresh_drafts_button.setObjectName("contractTemplateRefreshDraftsButton")
        refresh_drafts_button.clicked.connect(self.refresh_fill_drafts)
        save_new_draft_button = QPushButton("Save New Draft", draft_box)
        save_new_draft_button.setObjectName("contractTemplateSaveNewDraftButton")
        save_new_draft_button.clicked.connect(self.save_new_draft)
        save_selected_draft_button = QPushButton("Save Draft Changes", draft_box)
        save_selected_draft_button.setObjectName("contractTemplateSaveDraftChangesButton")
        save_selected_draft_button.clicked.connect(self.save_selected_draft)
        load_selected_draft_button = QPushButton("Load Selected Draft", draft_box)
        load_selected_draft_button.setObjectName("contractTemplateLoadDraftButton")
        load_selected_draft_button.clicked.connect(self.load_selected_draft)
        reset_fill_form_button = QPushButton("Reset Form", draft_box)
        reset_fill_form_button.setObjectName("contractTemplateResetFillFormButton")
        reset_fill_form_button.clicked.connect(self.reset_fill_form)
        self.fill_draft_actions_cluster = _create_action_button_cluster(
            draft_box,
            [
                refresh_drafts_button,
                save_new_draft_button,
                save_selected_draft_button,
                load_selected_draft_button,
                reset_fill_form_button,
            ],
            columns=2,
            min_button_width=170,
            span_last_row=True,
        )
        self.fill_draft_actions_cluster.setObjectName("contractTemplateDraftActionsCluster")
        draft_layout.addWidget(self.fill_draft_actions_cluster)

        self.fill_draft_status_label = QLabel(
            "Drafts are revision-specific and restore the last editable state."
        )
        self.fill_draft_status_label.setObjectName("contractTemplateDraftStatusLabel")
        self.fill_draft_status_label.setWordWrap(True)
        self.fill_draft_status_label.setProperty("role", "secondary")
        draft_layout.addWidget(self.fill_draft_status_label)
        scroll_layout.addWidget(draft_box)

        selector_box, selector_layout = _create_standard_section(
            self.fill_form_tab,
            "Database-Linked Fields",
            "Known placeholders become selector-driven controls so users choose "
            "authoritative records instead of typing catalog data by hand.",
        )
        self.fill_selector_empty_label = QLabel(
            "No database-linked placeholders are available for this revision.",
            selector_box,
        )
        self.fill_selector_empty_label.setWordWrap(True)
        self.fill_selector_empty_label.setProperty("role", "secondary")
        selector_layout.addWidget(self.fill_selector_empty_label)
        self.fill_selector_form = QFormLayout()
        _configure_standard_form_layout(self.fill_selector_form)
        selector_layout.addLayout(self.fill_selector_form)
        scroll_layout.addWidget(selector_box)

        manual_box, manual_layout = _create_standard_section(
            self.fill_form_tab,
            "Manual Fields",
            "Unknown or intentionally manual placeholders become typed inputs such "
            "as text, date, number, boolean, or option lists.",
        )
        self.fill_manual_empty_label = QLabel(
            "No manual placeholders are available for this revision.",
            manual_box,
        )
        self.fill_manual_empty_label.setWordWrap(True)
        self.fill_manual_empty_label.setProperty("role", "secondary")
        manual_layout.addWidget(self.fill_manual_empty_label)
        self.fill_manual_form = QFormLayout()
        _configure_standard_form_layout(self.fill_manual_form)
        manual_layout.addLayout(self.fill_manual_form)
        scroll_layout.addWidget(manual_box)

        guidance_box, guidance_layout = _create_standard_section(
            self.fill_form_tab,
            "Draft Notes",
            "Draft resume now restores the last editable payload for this revision. "
            "Resolved export and PDF generation still remain deferred to later phases.",
        )
        self.fill_guidance_label = QLabel(
            "Repeated placeholders are deduplicated into one control per canonical "
            "symbol. Selector values stay tied to authoritative records, and manual "
            "entries stay isolated from database-backed fields.",
            guidance_box,
        )
        self.fill_guidance_label.setWordWrap(True)
        self.fill_guidance_label.setProperty("role", "secondary")
        guidance_layout.addWidget(self.fill_guidance_label)
        scroll_layout.addWidget(guidance_box)
        scroll_layout.addStretch(1)

    def _catalog_service(self):
        return self.catalog_service_provider()

    def _template_service(self):
        return self.template_service_provider()

    def _form_service(self):
        return self.form_service_provider()

    def focus_tab(self, tab_name: str = "symbols") -> None:
        clean_name = str(tab_name or "symbols").strip().lower()
        if clean_name == "fill":
            self.workspace_tabs.setCurrentWidget(self.fill_form_tab)
            self.refresh_fill_form()
            return
        self.workspace_tabs.setCurrentWidget(self.symbol_generator_tab)

    def focus_namespace(self, namespace: str | None = None) -> None:
        clean_namespace = str(namespace or "").strip().lower() or None
        target_index = 0
        for index in range(self.namespace_combo.count()):
            if self.namespace_combo.itemData(index) == clean_namespace:
                target_index = index
                break
        self.namespace_combo.setCurrentIndex(target_index)
        self.refresh_symbol_generator()

    def refresh(self) -> None:
        self.refresh_symbol_generator()
        self.refresh_fill_form()

    def refresh_symbol_generator(self) -> None:
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

    def refresh_fill_form(self) -> None:
        template_service = self._template_service()
        form_service = self._form_service()
        selected_template_id = self._selected_fill_template_id()
        selected_revision_id = self._selected_fill_revision_id()
        selected_draft_id = self._selected_fill_draft_id()

        if template_service is None or form_service is None:
            self._fill_definition = None
            self._populate_fill_template_combo(())
            self._populate_fill_revision_combo(())
            self._clear_fill_fields()
            self._clear_fill_drafts(
                "Open a profile to browse and resume contract template drafts."
            )
            self.fill_status_label.setText(
                "Open a profile to browse imported template revisions."
            )
            self.fill_warning_label.setText("")
            return

        templates = tuple(template_service.list_templates())
        self._populate_fill_template_combo(templates, selected_template_id=selected_template_id)
        template_id = self._selected_fill_template_id()
        if template_id is None:
            self._fill_definition = None
            self._populate_fill_revision_combo(())
            self._clear_fill_fields()
            self._clear_fill_drafts(
                "Choose a template revision before saving or loading drafts."
            )
            self.fill_status_label.setText(
                "No contract template records exist yet. Import a scanned revision in "
                "Phase 2 tooling or seed one through the service layer."
            )
            self.fill_warning_label.setText("")
            return

        active_revision_id = None
        template_record = template_service.fetch_template(template_id)
        if template_record is not None:
            active_revision_id = template_record.active_revision_id
        revisions = tuple(template_service.list_revisions(template_id))
        self._populate_fill_revision_combo(
            revisions,
            selected_revision_id=selected_revision_id,
            active_revision_id=active_revision_id,
        )
        revision_id = self._selected_fill_revision_id()
        if revision_id is None:
            self._fill_definition = None
            self._clear_fill_fields()
            self._clear_fill_drafts(
                "The selected template does not have any drafts because it has no active revision context yet."
            )
            self.fill_status_label.setText(
                "The selected template does not have any stored revisions yet."
            )
            self.fill_warning_label.setText("")
            return

        preserved_state = None
        if self._fill_definition is not None and self._fill_definition.revision_id == revision_id:
            preserved_state = self.current_fill_state()

        try:
            form_definition = form_service.build_form_definition(revision_id)
        except Exception as exc:
            self._fill_definition = None
            self._clear_fill_fields()
            self._clear_fill_drafts(
                f"Unable to load drafts because revision #{int(revision_id)} could not build a fill form."
            )
            self.fill_status_label.setText(
                f"Unable to build a fill form for revision #{int(revision_id)}."
            )
            self.fill_warning_label.setText(str(exc))
            return

        self._fill_definition = form_definition
        self._rebuild_fill_fields(form_definition)
        if preserved_state is not None and int(preserved_state.get("revision_id") or 0) == int(
            revision_id
        ):
            self.apply_editable_payload(preserved_state)
        else:
            self._fill_dirty = False
        self.refresh_fill_drafts(selected_draft_id=selected_draft_id)
        status_bits = [
            f"{len(form_definition.selector_fields)} selector"
            f"{'s' if len(form_definition.selector_fields) != 1 else ''}",
            f"{len(form_definition.manual_fields)} manual field"
            f"{'s' if len(form_definition.manual_fields) != 1 else ''}",
        ]
        revision_label = _clean_text(form_definition.revision_label) or f"Revision #{revision_id}"
        self.fill_status_label.setText(
            f"{form_definition.template_name} / {revision_label} is {form_definition.scan_status}. "
            f"Generated {', '.join(status_bits)}."
        )
        warning_lines = list(form_definition.warnings)
        if form_definition.unresolved_placeholders:
            warning_lines.append(
                "Unresolved placeholders: "
                + ", ".join(form_definition.unresolved_placeholders)
            )
        if form_definition.scan_status != "scan_ready":
            warning_lines.insert(
                0,
                "This revision is not fully scan-ready, so the editable form may be incomplete.",
            )
        self.fill_warning_label.setText("\n".join(line for line in warning_lines if line))

    def current_fill_state(self) -> dict[str, object]:
        revision_id = self._selected_fill_revision_id()
        form_service = self._form_service()
        if revision_id is None or form_service is None:
            return {
                "revision_id": None,
                "db_selections": {},
                "manual_values": {},
                "type_overrides": {},
            }
        db_selections = {
            key: value
            for key, widget in self.selector_widgets.items()
            for value in [self._read_widget_value(widget)]
            if value is not None
        }
        manual_values = {
            key: value
            for key, widget in self.manual_widgets.items()
            for value in [self._read_widget_value(widget)]
            if value is not None
        }
        payload = form_service.build_editable_payload(
            revision_id,
            db_selections=db_selections,
            manual_values=manual_values,
            type_overrides=self._fill_type_overrides,
        )
        payload.update(self._fill_payload_extras)
        return payload

    def refresh_fill_drafts(self, *, selected_draft_id: int | None = None) -> None:
        template_service = self._template_service()
        revision_id = self._selected_fill_revision_id()
        if template_service is None or revision_id is None:
            self._clear_fill_drafts("Choose a revision before saving or loading drafts.")
            return
        draft_records = tuple(template_service.list_drafts(revision_id=revision_id))
        self._visible_drafts = list(draft_records)
        visible_ids = {int(record.draft_id) for record in draft_records}
        target_id = selected_draft_id or self._loaded_draft_id
        if target_id is not None and int(target_id) not in visible_ids:
            self._loaded_draft_id = None
            self._fill_type_overrides = {}
            self._fill_payload_extras = {}
            target_id = None
        self._populate_fill_draft_combo(draft_records, selected_draft_id=target_id)
        selected = self._selected_fill_draft_record()
        if selected is None:
            self._sync_draft_controls_from_selection(None)
            if not draft_records:
                self.fill_draft_status_label.setText(
                    "No saved drafts exist for this revision yet."
                )
            return
        self._sync_draft_controls_from_selection(selected)

    def save_new_draft(self) -> None:
        self._save_draft(save_as_new=True)

    def save_selected_draft(self) -> None:
        self._save_draft(save_as_new=False)

    def _save_draft(self, *, save_as_new: bool) -> bool:
        template_service = self._template_service()
        revision_id = self._selected_fill_revision_id()
        if template_service is None or revision_id is None:
            self.fill_draft_status_label.setText(
                "Choose a revision before saving a draft."
            )
            return False
        draft_payload = self._draft_payload_for_revision(revision_id)
        selected = self._selected_fill_draft_record()
        target = None if save_as_new else (selected or self._loaded_draft_record())
        try:
            saved = (
                template_service.create_draft(draft_payload)
                if target is None
                else template_service.update_draft(target.draft_id, draft_payload)
            )
        except Exception as exc:
            self.fill_draft_status_label.setText(f"Unable to save draft: {exc}")
            QMessageBox.warning(self, "Draft Workspace", str(exc))
            return False
        self._loaded_draft_id = saved.draft_id
        self._fill_dirty = False
        self.refresh_fill_drafts(selected_draft_id=saved.draft_id)
        self.fill_draft_status_label.setText(
            f"Saved draft #{saved.draft_id} using {self._storage_label(saved.storage_mode)} storage."
        )
        return True

    def load_selected_draft(self) -> None:
        template_service = self._template_service()
        draft = self._selected_fill_draft_record()
        if template_service is None or draft is None:
            self.fill_draft_status_label.setText(
                "Select a draft to restore the last editable state."
            )
            return
        try:
            revision = template_service.fetch_revision(draft.revision_id)
            payload = template_service.fetch_draft_payload(draft.draft_id) or {}
            if revision is None:
                raise ValueError(f"Revision {draft.revision_id} not found")
        except Exception as exc:
            self.fill_draft_status_label.setText(f"Unable to load draft: {exc}")
            QMessageBox.warning(self, "Draft Workspace", str(exc))
            return
        self._select_revision_context(revision.template_id, draft.revision_id)
        self.apply_editable_payload(payload)
        self.fill_draft_name_edit.setText(draft.name)
        self._set_storage_mode_value(draft.storage_mode or STORAGE_MODE_DATABASE)
        self._loaded_draft_id = draft.draft_id
        self._fill_dirty = False
        self.refresh_fill_drafts(selected_draft_id=draft.draft_id)
        self.fill_draft_status_label.setText(
            f"Loaded draft #{draft.draft_id} and restored its editable state."
        )

    def reset_fill_form(self) -> None:
        self._clear_fill_input_values()
        self._loaded_draft_id = None
        self._fill_dirty = False
        self._fill_type_overrides = {}
        self._fill_payload_extras = {}
        self.fill_draft_name_edit.setText(self._draft_name_value())
        self._set_storage_mode_value(STORAGE_MODE_DATABASE)
        self._select_combo_data(self.fill_draft_combo, None)
        self.fill_draft_status_label.setText(
            "Cleared the current fill form. Saved drafts remain available to load."
        )

    def apply_editable_payload(self, payload: object | None) -> None:
        payload_map = dict(payload or {})
        self._fill_type_overrides = {
            str(key): str(value)
            for key, value in dict(payload_map.get("type_overrides") or {}).items()
        }
        self._fill_payload_extras = {
            key: value
            for key, value in payload_map.items()
            if key not in {"revision_id", "db_selections", "manual_values", "type_overrides"}
        }
        self._clear_fill_input_values()
        db_values = dict(payload_map.get("db_selections") or {})
        manual_values = dict(payload_map.get("manual_values") or {})
        previous_suspend = self._suspend_fill_updates
        self._suspend_fill_updates = True
        try:
            for key, value in db_values.items():
                widget = self.selector_widgets.get(str(key))
                if widget is not None:
                    self._write_widget_value(widget, value, explicit=True)
            for key, value in manual_values.items():
                widget = self.manual_widgets.get(str(key))
                if widget is not None:
                    self._write_widget_value(widget, value, explicit=True)
        finally:
            self._suspend_fill_updates = previous_suspend
        self._fill_dirty = False

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

    def _populate_fill_template_combo(
        self,
        templates: tuple[object, ...],
        *,
        selected_template_id: int | None = None,
    ) -> None:
        self.fill_template_combo.blockSignals(True)
        self.fill_template_combo.clear()
        self.fill_template_combo.addItem("Choose Template", None)
        selected_index = 0
        for index, template in enumerate(templates, start=1):
            label = str(getattr(template, "name", "") or f"Template #{index}")
            if getattr(template, "active_revision_id", None) is not None:
                label = f"{label} (active revision)"
            self.fill_template_combo.addItem(label, int(template.template_id))
            if selected_template_id is not None and int(template.template_id) == int(
                selected_template_id
            ):
                selected_index = index
        if selected_index == 0 and len(templates) == 1:
            selected_index = 1
        self.fill_template_combo.setCurrentIndex(selected_index)
        self.fill_template_combo.blockSignals(False)

    def _populate_fill_revision_combo(
        self,
        revisions: tuple[object, ...],
        *,
        selected_revision_id: int | None = None,
        active_revision_id: int | None = None,
    ) -> None:
        self.fill_revision_combo.blockSignals(True)
        self.fill_revision_combo.clear()
        self.fill_revision_combo.addItem("Choose Revision", None)
        selected_index = 0
        for index, revision in enumerate(revisions, start=1):
            label_bits = [
                _clean_text(getattr(revision, "revision_label", None))
                or str(getattr(revision, "source_filename", "") or f"Revision #{index}"),
                str(getattr(revision, "scan_status", "") or "scan_pending"),
            ]
            if active_revision_id is not None and int(revision.revision_id) == int(
                active_revision_id
            ):
                label_bits.append("active")
            label = " | ".join(bit for bit in label_bits if bit)
            self.fill_revision_combo.addItem(label, int(revision.revision_id))
            if selected_revision_id is not None and int(revision.revision_id) == int(
                selected_revision_id
            ):
                selected_index = index
            elif selected_index == 0 and active_revision_id is not None and int(
                revision.revision_id
            ) == int(active_revision_id):
                selected_index = index
        if selected_index == 0 and len(revisions) == 1:
            selected_index = 1
        self.fill_revision_combo.setCurrentIndex(selected_index)
        self.fill_revision_combo.blockSignals(False)

    def _populate_fill_draft_combo(
        self,
        drafts: tuple[ContractTemplateDraftRecord, ...],
        *,
        selected_draft_id: int | None = None,
    ) -> None:
        self.fill_draft_combo.blockSignals(True)
        self.fill_draft_combo.clear()
        self.fill_draft_combo.addItem("Choose Saved Draft", None)
        selected_index = 0
        for index, draft in enumerate(drafts, start=1):
            label = (
                f"{draft.name} | {self._storage_label(draft.storage_mode)}"
                f" | {draft.updated_at or draft.created_at or 'recent'}"
            )
            self.fill_draft_combo.addItem(label, int(draft.draft_id))
            if selected_draft_id is not None and int(draft.draft_id) == int(selected_draft_id):
                selected_index = index
        if selected_index == 0 and len(drafts) == 1:
            selected_index = 1
        self.fill_draft_combo.setCurrentIndex(selected_index)
        self.fill_draft_combo.blockSignals(False)

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

    def _selected_fill_template_id(self) -> int | None:
        value = self.fill_template_combo.currentData()
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def _selected_fill_revision_id(self) -> int | None:
        value = self.fill_revision_combo.currentData()
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def _selected_fill_draft_id(self) -> int | None:
        value = self.fill_draft_combo.currentData()
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def _selected_fill_draft_record(self) -> ContractTemplateDraftRecord | None:
        draft_id = self._selected_fill_draft_id()
        if draft_id is None:
            return None
        for record in self._visible_drafts:
            if int(record.draft_id) == int(draft_id):
                return record
        return None

    def _loaded_draft_record(self) -> ContractTemplateDraftRecord | None:
        if self._loaded_draft_id is None:
            return None
        for record in self._visible_drafts:
            if int(record.draft_id) == int(self._loaded_draft_id):
                return record
        return None

    def _draft_payload_for_revision(self, revision_id: int) -> ContractTemplateDraftPayload:
        current_record = self._selected_fill_draft_record() or self._loaded_draft_record()
        return ContractTemplateDraftPayload(
            revision_id=int(revision_id),
            name=self._draft_name_value(),
            editable_payload=self.current_fill_state(),
            status=(current_record.status if current_record is not None else "draft"),
            scope_entity_type=(
                current_record.scope_entity_type if current_record is not None else None
            ),
            scope_entity_id=(current_record.scope_entity_id if current_record is not None else None),
            storage_mode=self._selected_storage_mode_value(),
            filename=(current_record.filename if current_record is not None else None),
            mime_type=(
                current_record.mime_type if current_record is not None else "application/json"
            ),
            last_resolved_snapshot_id=(
                current_record.last_resolved_snapshot_id if current_record is not None else None
            ),
        )

    def _draft_name_value(self) -> str:
        clean_name = _clean_text(self.fill_draft_name_edit.text())
        if clean_name:
            return clean_name
        if self._fill_definition is None:
            return "Contract Template Draft"
        revision_label = _clean_text(self._fill_definition.revision_label) or (
            f"Revision {self._fill_definition.revision_id}"
        )
        return f"{self._fill_definition.template_name} - {revision_label} Draft"

    def _selected_storage_mode_value(self) -> str:
        clean_mode = _clean_text(self.fill_draft_storage_combo.currentData())
        if clean_mode in {STORAGE_MODE_DATABASE, STORAGE_MODE_MANAGED_FILE}:
            return str(clean_mode)
        return STORAGE_MODE_DATABASE

    def _set_storage_mode_value(self, storage_mode: str) -> None:
        self._select_combo_data(self.fill_draft_storage_combo, storage_mode)

    @staticmethod
    def _storage_label(storage_mode: str | None) -> str:
        return (
            "managed file"
            if _clean_text(storage_mode) == STORAGE_MODE_MANAGED_FILE
            else "database embedded"
        )

    def _clear_fill_drafts(self, status_text: str) -> None:
        self._visible_drafts = []
        self._loaded_draft_id = None
        self._fill_type_overrides = {}
        self._fill_payload_extras = {}
        self._populate_fill_draft_combo(())
        self.fill_draft_name_edit.setText(self._draft_name_value())
        self._set_storage_mode_value(STORAGE_MODE_DATABASE)
        self.fill_draft_status_label.setText(status_text)

    def _sync_draft_controls_from_selection(
        self, record: ContractTemplateDraftRecord | None
    ) -> None:
        if record is None:
            self.fill_draft_name_edit.setText(self._draft_name_value())
            return
        self.fill_draft_name_edit.setText(record.name)
        self._set_storage_mode_value(record.storage_mode or STORAGE_MODE_DATABASE)
        self.fill_draft_status_label.setText(
            f"Selected draft #{record.draft_id} is {self._storage_label(record.storage_mode)} "
            f"and was last updated {record.updated_at or record.created_at or 'recently'}."
        )

    def _clear_fill_input_values(self) -> None:
        previous_suspend = self._suspend_fill_updates
        self._suspend_fill_updates = True
        try:
            for widget in self.selector_widgets.values():
                self._write_widget_value(widget, None, explicit=False)
            for widget in self.manual_widgets.values():
                self._write_widget_value(widget, None, explicit=False)
        finally:
            self._suspend_fill_updates = previous_suspend
        self._fill_dirty = False

    def _write_widget_value(
        self,
        widget: QWidget,
        value: object | None,
        *,
        explicit: bool,
    ) -> None:
        if isinstance(widget, QComboBox):
            if not explicit or value is None:
                widget.setCurrentIndex(0)
                return
            index = widget.findData(value)
            if index < 0:
                index = widget.findData(str(value))
            if index < 0:
                index = widget.findText(str(value))
            widget.setCurrentIndex(index if index >= 0 else 0)
            return
        if isinstance(widget, QCheckBox):
            widget.setChecked(bool(value) if explicit else False)
            widget.setProperty("has_user_value", bool(explicit))
            return
        if isinstance(widget, QDoubleSpinBox):
            widget.setValue(float(value) if explicit and value is not None else 0.0)
            widget.setProperty("has_user_value", bool(explicit))
            return
        if isinstance(widget, QDateEdit):
            if explicit and value is not None:
                date_value = QDate.fromString(str(value), Qt.ISODate)
                if not date_value.isValid():
                    date_value = QDate.fromString(str(value), "yyyy-MM-dd")
                widget.setDate(date_value if date_value.isValid() else QDate.currentDate())
                widget.setProperty("has_user_value", bool(date_value.isValid()))
            else:
                widget.setDate(QDate.currentDate())
                widget.setProperty("has_user_value", False)
            return
        if isinstance(widget, QLineEdit):
            widget.setText(str(value) if explicit and value is not None else "")

    @staticmethod
    def _read_widget_value(widget: QWidget) -> object | None:
        if isinstance(widget, QComboBox):
            value = widget.currentData()
            return value if value is not None else None
        if isinstance(widget, QCheckBox):
            if not bool(widget.property("has_user_value")):
                return None
            return bool(widget.isChecked())
        if isinstance(widget, QDoubleSpinBox):
            if not bool(widget.property("has_user_value")):
                return None
            value = float(widget.value())
            return int(value) if value.is_integer() else value
        if isinstance(widget, QDateEdit):
            if not bool(widget.property("has_user_value")):
                return None
            return widget.date().toString("yyyy-MM-dd")
        if isinstance(widget, QLineEdit):
            return _clean_text(widget.text())
        return None

    def _mark_fill_dirty(self) -> None:
        if self._suspend_fill_updates:
            return
        self._fill_dirty = True
        if self._loaded_draft_id is not None:
            self.fill_draft_status_label.setText(
                f"Draft #{self._loaded_draft_id} has unsaved changes."
            )
        else:
            self.fill_draft_status_label.setText(
                "Current fill form has unsaved changes."
            )

    def _select_combo_data(self, combo: QComboBox, data_value: object | None) -> None:
        for index in range(combo.count()):
            if combo.itemData(index) == data_value:
                combo.setCurrentIndex(index)
                return
        combo.setCurrentIndex(0)

    def _select_revision_context(self, template_id: int, revision_id: int) -> None:
        previous_suspend = self._suspend_fill_updates
        self._suspend_fill_updates = True
        try:
            self._select_combo_data(self.fill_template_combo, int(template_id))
        finally:
            self._suspend_fill_updates = previous_suspend
        self.refresh_fill_form()
        previous_suspend = self._suspend_fill_updates
        self._suspend_fill_updates = True
        try:
            self._select_combo_data(self.fill_revision_combo, int(revision_id))
        finally:
            self._suspend_fill_updates = previous_suspend
        self.refresh_fill_form()

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

    def _on_fill_template_changed(self) -> None:
        if self._suspend_fill_updates:
            return
        self._loaded_draft_id = None
        self._fill_type_overrides = {}
        self._fill_payload_extras = {}
        self._fill_dirty = False
        self.refresh_fill_form()

    def _on_fill_revision_changed(self) -> None:
        if self._suspend_fill_updates:
            return
        self._loaded_draft_id = None
        self._fill_type_overrides = {}
        self._fill_payload_extras = {}
        self._fill_dirty = False
        self.refresh_fill_form()

    def _on_fill_draft_changed(self) -> None:
        if self._suspend_fill_updates:
            return
        self._sync_draft_controls_from_selection(self._selected_fill_draft_record())

    def _rebuild_fill_fields(self, form_definition: ContractTemplateFormDefinition) -> None:
        self._clear_fill_fields()
        for field in form_definition.selector_fields:
            widget = self._build_selector_widget(field)
            self.selector_widgets[field.selector_key] = widget
            self.fill_selector_form.addRow(field.display_label, widget)
        for field in form_definition.manual_fields:
            widget = self._build_manual_widget(field)
            self.manual_widgets[field.canonical_symbol] = widget
            self.fill_manual_form.addRow(field.display_label, widget)
        self.fill_selector_empty_label.setVisible(not bool(form_definition.selector_fields))
        self.fill_manual_empty_label.setVisible(not bool(form_definition.manual_fields))

    def _clear_fill_fields(self) -> None:
        self._clear_form_layout(self.fill_selector_form)
        self._clear_form_layout(self.fill_manual_form)
        self.selector_widgets = {}
        self.manual_widgets = {}
        self.fill_selector_empty_label.setVisible(True)
        self.fill_manual_empty_label.setVisible(True)

    def _clear_form_layout(self, layout: QFormLayout) -> None:
        while layout.rowCount() > 0:
            layout.removeRow(0)

    def _build_selector_widget(self, field: ContractTemplateFormSelectorField) -> QComboBox:
        combo = QComboBox(self.fill_form_tab)
        combo.setObjectName("contractTemplateSelectorWidget")
        combo.setProperty("selector_key", field.selector_key)
        combo.setProperty("scope_entity_type", field.scope_entity_type)
        combo.setProperty("scope_policy", field.scope_policy)
        combo.setProperty("widget_kind", field.widget_kind)
        combo.addItem(f"Choose {field.display_label}", None)
        for choice in field.choices:
            combo.addItem(choice.label, choice.value)
            if choice.description:
                combo.setItemData(combo.count() - 1, choice.description, Qt.ToolTipRole)
        combo.currentIndexChanged.connect(self._mark_fill_dirty)
        return combo

    def _build_manual_widget(self, field: ContractTemplateFormManualField) -> QWidget:
        if field.field_type == "boolean":
            checkbox = QCheckBox("Yes", self.fill_form_tab)
            checkbox.setObjectName("contractTemplateManualBooleanWidget")
            checkbox.setProperty("canonical_symbol", field.canonical_symbol)
            checkbox.setProperty("field_type", field.field_type)
            checkbox.setProperty("widget_kind", field.widget_kind)
            checkbox.setProperty("has_user_value", False)

            def _handle_boolean_toggle(_checked: bool, *, widget=checkbox) -> None:
                widget.setProperty("has_user_value", True)
                self._mark_fill_dirty()

            checkbox.toggled.connect(_handle_boolean_toggle)
            return checkbox

        if field.options:
            combo = QComboBox(self.fill_form_tab)
            combo.setObjectName("contractTemplateManualOptionsWidget")
            combo.setProperty("canonical_symbol", field.canonical_symbol)
            combo.setProperty("field_type", field.field_type)
            combo.setProperty("widget_kind", field.widget_kind)
            combo.addItem(f"Choose {field.display_label}", None)
            for option in field.options:
                combo.addItem(option, option)
            combo.currentIndexChanged.connect(self._mark_fill_dirty)
            return combo

        if field.field_type == "number":
            spin = QDoubleSpinBox(self.fill_form_tab)
            spin.setObjectName("contractTemplateManualNumberWidget")
            spin.setProperty("canonical_symbol", field.canonical_symbol)
            spin.setProperty("field_type", field.field_type)
            spin.setProperty("widget_kind", field.widget_kind)
            spin.setProperty("has_user_value", False)
            spin.setRange(-999999999.0, 999999999.0)
            spin.setDecimals(6)

            def _handle_number_change(_value: float, *, widget=spin) -> None:
                widget.setProperty("has_user_value", True)
                self._mark_fill_dirty()

            spin.valueChanged.connect(_handle_number_change)
            return spin

        if field.field_type == "date":
            edit = QDateEdit(self.fill_form_tab)
            edit.setObjectName("contractTemplateManualDateWidget")
            edit.setProperty("canonical_symbol", field.canonical_symbol)
            edit.setProperty("field_type", field.field_type)
            edit.setProperty("widget_kind", field.widget_kind)
            edit.setProperty("has_user_value", False)
            edit.setCalendarPopup(True)
            edit.setDisplayFormat("yyyy-MM-dd")
            edit.setDate(QDate.currentDate())

            def _handle_date_change(_date: QDate, *, widget=edit) -> None:
                widget.setProperty("has_user_value", True)
                self._mark_fill_dirty()

            edit.dateChanged.connect(_handle_date_change)
            return edit

        line_edit = QLineEdit(self.fill_form_tab)
        line_edit.setObjectName("contractTemplateManualTextWidget")
        line_edit.setProperty("canonical_symbol", field.canonical_symbol)
        line_edit.setProperty("field_type", field.field_type)
        line_edit.setProperty("widget_kind", field.widget_kind)
        if field.field_type == "date":
            line_edit.setPlaceholderText("YYYY-MM-DD")
        elif field.field_type == "number":
            line_edit.setPlaceholderText("Enter a numeric value")
        else:
            line_edit.setPlaceholderText(f"Enter {field.display_label}")
        line_edit.textChanged.connect(self._mark_fill_dirty)
        return line_edit

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
            "manual_entry": "Manual entry",
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

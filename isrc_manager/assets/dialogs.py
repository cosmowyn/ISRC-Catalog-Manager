"""Deliverable and asset registry dialogs."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
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

from isrc_manager.file_storage import (
    STORAGE_MODE_DATABASE,
    STORAGE_MODE_MANAGED_FILE,
    normalize_storage_mode,
)
from isrc_manager.media.derivatives import DerivativeLedgerRecord, DerivativeLedgerService
from isrc_manager.ui_common import (
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

from .models import ASSET_TYPE_CHOICES, AssetVersionPayload, AssetVersionRecord
from .service import AssetService


class AssetEditorDialog(QDialog):
    """Create or edit an asset/deliverable registry record."""

    def __init__(
        self, *, asset_service: AssetService, asset: AssetVersionRecord | None = None, parent=None
    ):
        super().__init__(parent)
        self.asset_service = asset_service
        self.asset = asset
        self.setWindowTitle("Edit Asset Version" if asset is not None else "Register Asset Version")
        self.resize(760, 600)
        self.setMinimumSize(700, 540)
        _apply_standard_dialog_chrome(self, "assetEditorDialog")

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)
        _add_standard_dialog_header(
            root,
            self,
            title=self.windowTitle(),
            subtitle=(
                "Register a managed master, derivative, or artwork variant and keep its "
                "approval state tied to the right track or release."
            ),
        )

        self.tabs = QTabWidget(self)
        self.tabs.setObjectName("assetEditorTabs")
        self.tabs.setDocumentMode(True)
        root.addWidget(self.tabs, 1)

        def create_tab(title: str) -> QVBoxLayout:
            page = QWidget(self.tabs)
            page.setProperty("role", "workspaceCanvas")
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(0, 0, 0, 0)
            page_layout.setSpacing(0)
            scroll_area, _, content_layout = _create_scrollable_dialog_content(page)
            page_layout.addWidget(scroll_area, 1)
            self.tabs.addTab(page, title)
            return content_layout

        self.track_id_edit = QComboBox()
        self.track_id_edit.setEditable(True)
        self.track_id_edit.addItem("", None)
        self.release_id_edit = QComboBox()
        self.release_id_edit.setEditable(True)
        self.release_id_edit.addItem("", None)
        self._populate_reference_combos()

        target_box, target_layout = _create_standard_section(
            self,
            "Target Record",
            "Link the asset to a track or release, then describe the type and status of the version.",
        )
        target_form = QFormLayout()
        _configure_standard_form_layout(target_form)
        target_form.addRow("Track ID", self.track_id_edit)
        target_form.addRow("Release ID", self.release_id_edit)

        self.asset_type_combo = QComboBox()
        self.asset_type_combo.addItems(
            [item.replace("_", " ").title() for item in ASSET_TYPE_CHOICES]
        )
        target_form.addRow("Asset Type", self.asset_type_combo)

        self.status_edit = QLineEdit()
        target_form.addRow("Version Status", self.status_edit)

        self.format_edit = QLineEdit()
        target_form.addRow("Format", self.format_edit)

        self.storage_mode_combo = QComboBox()
        self.storage_mode_combo.addItem("Stored in Database", STORAGE_MODE_DATABASE)
        self.storage_mode_combo.addItem("Managed File", STORAGE_MODE_MANAGED_FILE)
        target_form.addRow("Storage Mode", self.storage_mode_combo)

        flags_widget = QWidget(self)
        flags_row = QHBoxLayout(flags_widget)
        flags_row.setContentsMargins(0, 0, 0, 0)
        flags_row.setSpacing(10)
        self.approved_checkbox = QCheckBox("Approved for use")
        self.primary_checkbox = QCheckBox("Primary asset")
        flags_row.addWidget(self.approved_checkbox)
        flags_row.addWidget(self.primary_checkbox)
        flags_row.addStretch(1)
        target_form.addRow("Flags", flags_widget)
        target_layout.addLayout(target_form)
        target_page_layout = create_tab("Target")
        target_page_layout.addWidget(target_box)
        target_page_layout.addStretch(1)

        source_box, source_layout = _create_standard_section(
            self,
            "Source File",
            "Choose the file to register. The app will manage the stored copy inside the catalog workspace.",
        )
        source_form = QFormLayout()
        _configure_standard_form_layout(source_form)
        self.file_edit = QLineEdit()
        self.file_edit.setReadOnly(True)
        file_row = QWidget(self)
        file_layout = QHBoxLayout(file_row)
        file_layout.setContentsMargins(0, 0, 0, 0)
        file_layout.setSpacing(8)
        file_layout.addWidget(self.file_edit, 1)
        browse_button = QPushButton("Browse…")
        browse_button.clicked.connect(self._pick_file)
        file_layout.addWidget(browse_button)
        source_form.addRow("Source File", file_row)
        source_layout.addLayout(source_form)
        source_page_layout = create_tab("Source")
        source_page_layout.addWidget(source_box)
        source_page_layout.addStretch(1)

        notes_box, notes_layout = _create_standard_section(
            self,
            "Notes",
            "Capture approval comments, delivery instructions, or any context that distinguishes this version from others.",
        )
        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setMinimumHeight(180)
        notes_layout.addWidget(self.notes_edit)
        notes_page_layout = create_tab("Notes")
        notes_page_layout.addWidget(notes_box)
        notes_page_layout.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        save_button = buttons.button(QDialogButtonBox.Save)
        if save_button is not None:
            save_button.setText("Save Asset")
            save_button.setDefault(True)
        root.addWidget(buttons)
        _apply_compact_dialog_control_heights(self)

        if asset is not None:
            self._set_combo_id(self.track_id_edit, asset.track_id)
            self._set_combo_id(self.release_id_edit, asset.release_id)
            self.asset_type_combo.setCurrentText(asset.asset_type.replace("_", " ").title())
            resolved = self.asset_service.resolve_asset_path(asset.stored_path)
            self.file_edit.setText(str(resolved) if resolved is not None else "")
            self.status_edit.setText(asset.version_status or "")
            self.format_edit.setText(asset.format or "")
            self.storage_mode_combo.setCurrentIndex(
                0
                if normalize_storage_mode(asset.storage_mode, default=STORAGE_MODE_MANAGED_FILE)
                == STORAGE_MODE_DATABASE
                else 1
            )
            self.approved_checkbox.setChecked(asset.approved_for_use)
            self.primary_checkbox.setChecked(asset.primary_flag)
            self.notes_edit.setPlainText(asset.notes or "")
        else:
            self.storage_mode_combo.setCurrentIndex(1)

    def _populate_reference_combos(self) -> None:
        conn = getattr(self.asset_service, "conn", None)
        if conn is None:
            return
        for track_id, track_title, artist_name in conn.execute(
            """
            SELECT
                t.id,
                t.track_title,
                COALESCE(a.name, '')
            FROM Tracks t
            LEFT JOIN Artists a ON a.id = t.main_artist_id
            ORDER BY t.track_title, t.id
            """
        ).fetchall():
            label = " / ".join(
                part for part in (str(track_title or ""), str(artist_name or "")) if part
            )
            if not label:
                label = f"Track {track_id}"
            self.track_id_edit.addItem(f"{track_id} - {label}", int(track_id))
        for release_id, title, primary_artist in conn.execute(
            """
            SELECT id, title, COALESCE(primary_artist, '')
            FROM Releases
            ORDER BY title, id
            """
        ).fetchall():
            label = " / ".join(
                part for part in (str(title or ""), str(primary_artist or "")) if part
            )
            if not label:
                label = f"Release {release_id}"
            self.release_id_edit.addItem(f"{release_id} - {label}", int(release_id))
        for combo in (self.track_id_edit, self.release_id_edit):
            labels = [
                combo.itemText(index) for index in range(combo.count()) if combo.itemText(index)
            ]
            completer = QCompleter(labels, combo)
            completer.setCaseSensitivity(Qt.CaseInsensitive)
            combo.setCompleter(completer)

    @staticmethod
    def _set_combo_id(combo: QComboBox, value: int | None) -> None:
        for index in range(combo.count()):
            if combo.itemData(index) == value:
                combo.setCurrentIndex(index)
                return

    @staticmethod
    def _combo_optional_int(combo: QComboBox) -> int | None:
        data = combo.currentData()
        if data not in (None, ""):
            try:
                return int(data)
            except (TypeError, ValueError):
                return None
        text = combo.currentText().strip()
        if not text:
            return None
        try:
            return int(text.split(" - ", 1)[0].strip())
        except (TypeError, ValueError):
            return None

    def _pick_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select Asset File", "")
        if path:
            self.file_edit.setText(path)

    def payload(self) -> AssetVersionPayload:
        return AssetVersionPayload(
            asset_type=self.asset_type_combo.currentText().strip().lower().replace(" ", "_"),
            source_path=self.file_edit.text().strip() or None,
            storage_mode=self.storage_mode_combo.currentData(),
            format=self.format_edit.text().strip() or None,
            approved_for_use=self.approved_checkbox.isChecked(),
            primary_flag=self.primary_checkbox.isChecked(),
            version_status=self.status_edit.text().strip() or None,
            notes=self.notes_edit.toPlainText().strip() or None,
            track_id=self._combo_optional_int(self.track_id_edit),
            release_id=self._combo_optional_int(self.release_id_edit),
        )


class _DerivativeLedgerPane(QWidget):
    """Browse managed derivative export batches with layered detail and admin tools."""

    def __init__(self, *, ledger_service_provider, drill_in_host_provider=None, parent=None):
        super().__init__(parent)
        self.ledger_service_provider = ledger_service_provider
        self.drill_in_host_provider = drill_in_host_provider
        self.setObjectName("derivativeLedgerPane")
        self._batches = []
        self._derivatives = []
        self._detail_labels: list[QLabel] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        controls_box, controls_layout = _create_standard_section(
            self,
            "Find Batches",
            "Search batches by batch ID, track, output file, format, or hash.",
        )
        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(10)
        self.search_edit = QLineEdit(self)
        self.search_edit.setPlaceholderText(
            "Search by batch ID, track title, output file, format, or hash..."
        )
        self.search_edit.textChanged.connect(self.refresh)
        controls.addWidget(self.search_edit, 1)
        self.format_filter_combo = QComboBox(self)
        self.format_filter_combo.setObjectName("derivativeLedgerFormatFilter")
        self.format_filter_combo.currentIndexChanged.connect(self.refresh)
        controls.addWidget(self.format_filter_combo)
        self.kind_filter_combo = QComboBox(self)
        self.kind_filter_combo.setObjectName("derivativeLedgerKindFilter")
        self.kind_filter_combo.currentIndexChanged.connect(self.refresh)
        controls.addWidget(self.kind_filter_combo)
        self.status_filter_combo = QComboBox(self)
        self.status_filter_combo.setObjectName("derivativeLedgerStatusFilter")
        self.status_filter_combo.currentIndexChanged.connect(self.refresh)
        controls.addWidget(self.status_filter_combo)
        self.refresh_button = QPushButton("Refresh", self)
        self.refresh_button.clicked.connect(self.refresh)
        controls.addWidget(self.refresh_button)
        controls_layout.addLayout(controls)
        self.summary_label = QLabel(self)
        self.summary_label.setProperty("role", "supportingText")
        self.summary_label.setWordWrap(True)
        controls_layout.addWidget(self.summary_label)
        root.addWidget(controls_box)

        self.workspace_splitter = QSplitter(Qt.Horizontal, self)
        self.workspace_splitter.setObjectName("derivativeLedgerWorkspaceSplitter")
        self.workspace_splitter.setChildrenCollapsible(False)
        root.addWidget(self.workspace_splitter, 1)

        batch_box, batch_layout = _create_standard_section(
            self,
            "Export Batches",
            "Keep the batch list visible while reviewing derivatives, details, lineage, and cleanup tools.",
        )
        batch_box.setMinimumWidth(320)
        self.batch_table = QTableWidget(0, 7, batch_box)
        self.batch_table.setHorizontalHeaderLabels(
            ["Batch ID", "Created", "Format", "Kind", "Exported", "Package", "Status"]
        )
        self.batch_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.batch_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.batch_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.batch_table.verticalHeader().setVisible(False)
        self.batch_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.batch_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.batch_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.batch_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.batch_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.batch_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.batch_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.Stretch)
        self.batch_table.itemSelectionChanged.connect(self._load_selected_batch)
        batch_layout.addWidget(self.batch_table, 1)
        self.workspace_splitter.addWidget(batch_box)

        selected_box, selected_layout = _create_standard_section(
            self,
            "Selected Batch Workspace",
            "Keep derivatives visible for daily review, with deeper details, lineage, and admin tools layered into tabs.",
        )
        selected_box.setMinimumWidth(420)
        self.selected_batch_heading = QLabel(self)
        self.selected_batch_heading.setProperty("role", "secondary")
        self.selected_batch_heading.setWordWrap(True)
        selected_layout.addWidget(self.selected_batch_heading)
        self.selection_label = QLabel(self)
        self.selection_label.setProperty("role", "supportingText")
        self.selection_label.setWordWrap(True)
        selected_layout.addWidget(self.selection_label)

        self.batch_workspace_tabs = QTabWidget(selected_box)
        self.batch_workspace_tabs.setObjectName("derivativeLedgerDetailTabs")
        self.batch_workspace_tabs.setDocumentMode(True)
        selected_layout.addWidget(self.batch_workspace_tabs, 1)
        self.workspace_splitter.addWidget(selected_box)
        self.workspace_splitter.setStretchFactor(0, 3)
        self.workspace_splitter.setStretchFactor(1, 5)
        self.workspace_splitter.setSizes([460, 760])

        derivatives_tab = QWidget(self.batch_workspace_tabs)
        derivatives_layout = QVBoxLayout(derivatives_tab)
        derivatives_layout.setContentsMargins(0, 0, 0, 0)
        derivatives_layout.setSpacing(10)
        self.derivative_summary_label = QLabel(derivatives_tab)
        self.derivative_summary_label.setProperty("role", "supportingText")
        self.derivative_summary_label.setWordWrap(True)
        derivatives_layout.addWidget(self.derivative_summary_label)
        self.derivative_table = QTableWidget(0, 7, derivatives_tab)
        self.derivative_table.setHorizontalHeaderLabels(
            ["Track", "Output File", "Format", "Kind", "Watermarked", "Size", "Status"]
        )
        self.derivative_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.derivative_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.derivative_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.derivative_table.verticalHeader().setVisible(False)
        self.derivative_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeToContents
        )
        self.derivative_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.derivative_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeToContents
        )
        self.derivative_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeToContents
        )
        self.derivative_table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeToContents
        )
        self.derivative_table.horizontalHeader().setSectionResizeMode(
            5, QHeaderView.ResizeToContents
        )
        self.derivative_table.horizontalHeader().setSectionResizeMode(
            6, QHeaderView.ResizeToContents
        )
        self.derivative_table.itemSelectionChanged.connect(self._show_selected_derivative)
        derivatives_layout.addWidget(self.derivative_table, 1)
        self.open_track_button = QPushButton("Open Track…", derivatives_tab)
        self.open_track_button.clicked.connect(self._open_selected_track)
        self.open_release_button = QPushButton("Open Release…", derivatives_tab)
        self.open_release_button.clicked.connect(self._open_selected_release)
        self.verify_authenticity_button = QPushButton("Verify Authenticity…", derivatives_tab)
        self.verify_authenticity_button.clicked.connect(self._verify_selected_derivative)
        self.derivative_actions_cluster = _create_action_button_cluster(
            derivatives_tab,
            [
                self.open_track_button,
                self.open_release_button,
                self.verify_authenticity_button,
            ],
            columns=2,
            min_button_width=180,
            span_last_row=True,
        )
        self.derivative_actions_cluster.setObjectName("derivativeLedgerActionsCluster")
        derivatives_layout.addWidget(self.derivative_actions_cluster)
        self.batch_workspace_tabs.addTab(derivatives_tab, "Derivatives")

        details_tab = QWidget(self.batch_workspace_tabs)
        details_tab_layout = QVBoxLayout(details_tab)
        details_tab_layout.setContentsMargins(0, 0, 0, 0)
        details_tab_layout.setSpacing(0)
        self.details_scroll_area, _, details_content_layout = _create_scrollable_dialog_content(
            details_tab
        )
        self.details_scroll_area.setObjectName("derivativeLedgerDetailsScrollArea")
        details_tab_layout.addWidget(self.details_scroll_area, 1)
        details_content_layout.setSpacing(12)
        batch_details_box, batch_details_layout = _create_standard_section(
            self,
            "Batch Summary",
            "Review the selected export job without expanding the entire workspace.",
        )
        batch_details_form = QFormLayout()
        _configure_standard_form_layout(batch_details_form)
        self.batch_id_value = self._create_detail_label()
        self.batch_created_value = self._create_detail_label()
        self.batch_completed_value = self._create_detail_label()
        self.batch_workflow_value = self._create_detail_label()
        self.batch_totals_value = self._create_detail_label()
        self.batch_status_value = self._create_detail_label()
        self.batch_package_mode_value = self._create_detail_label()
        self.batch_profile_value = self._create_detail_label()
        batch_details_form.addRow("Batch ID", self.batch_id_value)
        batch_details_form.addRow("Created", self.batch_created_value)
        batch_details_form.addRow("Completed", self.batch_completed_value)
        batch_details_form.addRow("Workflow", self.batch_workflow_value)
        batch_details_form.addRow("Export Totals", self.batch_totals_value)
        batch_details_form.addRow("Status", self.batch_status_value)
        batch_details_form.addRow("Package Mode", self.batch_package_mode_value)
        batch_details_form.addRow("Profile", self.batch_profile_value)
        batch_details_layout.addLayout(batch_details_form)
        details_content_layout.addWidget(batch_details_box)

        output_box, output_layout = _create_standard_section(
            self,
            "Selected Output",
            "The currently highlighted derivative stays readable without collapsing the batch list above.",
        )
        output_form = QFormLayout()
        _configure_standard_form_layout(output_form)
        self.output_track_value = self._create_detail_label()
        self.output_filename_value = self._create_detail_label()
        self.output_format_value = self._create_detail_label()
        self.output_kind_value = self._create_detail_label()
        self.output_authenticity_value = self._create_detail_label()
        self.output_watermark_value = self._create_detail_label()
        self.output_metadata_value = self._create_detail_label()
        self.output_size_value = self._create_detail_label()
        self.output_status_value = self._create_detail_label()
        output_form.addRow("Track", self.output_track_value)
        output_form.addRow("Output File", self.output_filename_value)
        output_form.addRow("Format", self.output_format_value)
        output_form.addRow("Derivative Kind", self.output_kind_value)
        output_form.addRow("Authenticity Basis", self.output_authenticity_value)
        output_form.addRow("Watermark Applied", self.output_watermark_value)
        output_form.addRow("Metadata Embedded", self.output_metadata_value)
        output_form.addRow("Output Size", self.output_size_value)
        output_form.addRow("Status", self.output_status_value)
        output_layout.addLayout(output_form)
        details_content_layout.addWidget(output_box)
        details_content_layout.addStretch(1)
        self.batch_workspace_tabs.addTab(details_tab, "Details")

        lineage_tab = QWidget(self.batch_workspace_tabs)
        lineage_tab_layout = QVBoxLayout(lineage_tab)
        lineage_tab_layout.setContentsMargins(0, 0, 0, 0)
        lineage_tab_layout.setSpacing(0)
        self.lineage_scroll_area, _, lineage_content_layout = _create_scrollable_dialog_content(
            lineage_tab
        )
        self.lineage_scroll_area.setObjectName("derivativeLedgerLineageScrollArea")
        lineage_tab_layout.addWidget(self.lineage_scroll_area, 1)
        lineage_content_layout.setSpacing(12)
        integrity_box, integrity_layout = _create_standard_section(
            self,
            "Integrity and Lineage",
            "Hashes, manifests, and source lineage stay available without overwhelming the main review tab.",
        )
        integrity_form = QFormLayout()
        _configure_standard_form_layout(integrity_form)
        self.export_id_value = self._create_detail_label()
        self.output_sha_value = self._create_detail_label()
        self.source_storage_value = self._create_detail_label()
        self.source_lineage_value = self._create_detail_label()
        self.manifest_id_value = self._create_detail_label()
        integrity_form.addRow("Export ID", self.export_id_value)
        integrity_form.addRow("Output SHA-256", self.output_sha_value)
        integrity_form.addRow("Source Storage", self.source_storage_value)
        integrity_form.addRow("Source Lineage", self.source_lineage_value)
        integrity_form.addRow("Manifest ID", self.manifest_id_value)
        integrity_layout.addLayout(integrity_form)
        lineage_content_layout.addWidget(integrity_box)

        packaging_box, packaging_layout = _create_standard_section(
            self,
            "Packaging and Storage",
            "Retained paths remain visible in their own scrollable inspector.",
        )
        packaging_form = QFormLayout()
        _configure_standard_form_layout(packaging_form)
        self.zip_filename_value = self._create_detail_label()
        self.managed_file_path_value = self._create_detail_label()
        self.sidecar_path_value = self._create_detail_label()
        self.package_member_value = self._create_detail_label()
        packaging_form.addRow("ZIP Package", self.zip_filename_value)
        packaging_form.addRow("Exported File Path", self.managed_file_path_value)
        packaging_form.addRow("Sidecar Path", self.sidecar_path_value)
        packaging_form.addRow("ZIP Member", self.package_member_value)
        packaging_layout.addLayout(packaging_form)
        lineage_content_layout.addWidget(packaging_box)
        lineage_content_layout.addStretch(1)
        self.batch_workspace_tabs.addTab(lineage_tab, "Lineage")

        admin_tab = QWidget(self.batch_workspace_tabs)
        admin_tab_layout = QVBoxLayout(admin_tab)
        admin_tab_layout.setContentsMargins(0, 0, 0, 0)
        admin_tab_layout.setSpacing(10)
        admin_box, admin_box_layout = _create_standard_section(
            self,
            "Ledger Admin",
            "Use cleanup actions for stale or test records without removing the exported files on disk.",
        )
        self.admin_summary_label = QLabel(admin_tab)
        self.admin_summary_label.setProperty("role", "supportingText")
        self.admin_summary_label.setWordWrap(True)
        admin_box_layout.addWidget(self.admin_summary_label)
        self.delete_derivative_button = QPushButton("Delete Selected Derivative…", admin_tab)
        self.delete_derivative_button.clicked.connect(self._delete_selected_derivative)
        self.delete_batch_button = QPushButton("Delete Selected Batch…", admin_tab)
        self.delete_batch_button.clicked.connect(self._delete_selected_batch)
        self.delete_output_files_button = QPushButton("Delete Retained Output Files…", admin_tab)
        self.delete_output_files_button.clicked.connect(self._delete_selected_output_files)
        self.refresh_admin_button = QPushButton("Refresh View", admin_tab)
        self.refresh_admin_button.clicked.connect(self.refresh)
        self.admin_actions_cluster = _create_action_button_cluster(
            admin_box,
            [
                self.delete_derivative_button,
                self.delete_batch_button,
                self.delete_output_files_button,
                self.refresh_admin_button,
            ],
            columns=1,
            min_button_width=220,
        )
        self.admin_actions_cluster.setObjectName("derivativeLedgerAdminActionsCluster")
        admin_box_layout.addWidget(self.admin_actions_cluster)
        admin_semantics_label = QLabel(
            "Deleting ledger records removes database references only. Exported files, ZIP packages, and sidecars remain on disk unless you delete them separately."
        )
        admin_semantics_label.setProperty("role", "supportingText")
        admin_semantics_label.setWordWrap(True)
        admin_box_layout.addWidget(admin_semantics_label)
        admin_tab_layout.addWidget(admin_box)
        admin_tab_layout.addStretch(1)
        self.batch_workspace_tabs.addTab(admin_tab, "Admin")

        self.details_edit = QPlainTextEdit(self)
        self.details_edit.setReadOnly(True)
        self.details_edit.hide()

        _apply_compact_dialog_control_heights(self)

        self._populate_filter_combo(self.format_filter_combo, [], "All Formats")
        self._populate_filter_combo(self.kind_filter_combo, [], "All Kinds")
        self._populate_filter_combo(self.status_filter_combo, [], "All Statuses")
        self.refresh()

    def _create_detail_label(self) -> QLabel:
        label = QLabel(self)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        label.setProperty("role", "supportingText")
        self._detail_labels.append(label)
        return label

    @staticmethod
    def _set_detail_label(label: QLabel, value: str | None, *, empty: str = "—") -> None:
        clean = str(value or "").strip()
        label.setText(clean or empty)

    def _populate_filter_combo(
        self,
        combo: QComboBox,
        values: list[str],
        all_label: str,
        *,
        formatter=None,
    ) -> None:
        current_value = str(combo.currentData() or "").strip().lower()
        display = formatter or (lambda value: value)
        combo.blockSignals(True)
        try:
            combo.clear()
            combo.addItem(all_label, "")
            normalized_values: list[str] = []
            for value in values:
                clean_value = str(value or "").strip().lower()
                if not clean_value or clean_value in normalized_values:
                    continue
                normalized_values.append(clean_value)
                combo.addItem(display(clean_value), clean_value)
            target_index = 0
            if current_value:
                for index in range(combo.count()):
                    if str(combo.itemData(index) or "").strip().lower() == current_value:
                        target_index = index
                        break
            combo.setCurrentIndex(target_index)
        finally:
            combo.blockSignals(False)

    def _filter_value(self, combo: QComboBox) -> str | None:
        clean_value = str(combo.currentData() or "").strip().lower()
        return clean_value or None

    def _clear_detail_fields(self) -> None:
        for label in self._detail_labels:
            label.setText("—")

    def _ledger_service(self) -> DerivativeLedgerService | None:
        return self.ledger_service_provider()

    def _drill_in_host(self):
        provider = self.drill_in_host_provider
        return provider() if callable(provider) else None

    @staticmethod
    def _human_size(size_bytes: int) -> str:
        value = float(max(0, int(size_bytes or 0)))
        units = ("B", "KB", "MB", "GB", "TB")
        for unit in units:
            if value < 1024 or unit == units[-1]:
                if unit == "B":
                    return f"{int(value)} {unit}"
                return f"{value:.1f} {unit}"
            value /= 1024.0
        return "0 B"

    @staticmethod
    def _workflow_label(derivative_kind: str, authenticity_basis: str) -> str:
        kind_text = str(derivative_kind or "").replace("_", " ").strip().title()
        basis_text = str(authenticity_basis or "").replace("_", " ").strip().title()
        return f"{kind_text} / {basis_text}" if basis_text else kind_text

    def _selected_batch_id(self) -> str | None:
        selection_model = self.batch_table.selectionModel()
        if selection_model is None:
            return None
        rows = selection_model.selectedRows()
        if not rows:
            return None
        item = self.batch_table.item(rows[0].row(), 0)
        return str(item.data(Qt.UserRole) or "").strip() if item is not None else None

    def _selected_batch_record(self):
        batch_id = self._selected_batch_id()
        if not batch_id:
            return None
        return next(
            (candidate for candidate in self._batches if candidate.batch_id == batch_id), None
        )

    def _selected_derivative(self) -> DerivativeLedgerRecord | None:
        selection_model = self.derivative_table.selectionModel()
        if selection_model is None:
            return None
        rows = selection_model.selectedRows()
        if not rows:
            return None
        row = rows[0].row()
        if row < 0 or row >= len(self._derivatives):
            return None
        return self._derivatives[row]

    def _resolve_primary_release(self, derivative: DerivativeLedgerRecord | None):
        host = self._drill_in_host()
        release_service = getattr(host, "release_service", None) if host is not None else None
        if release_service is None or derivative is None or derivative.track_id is None:
            return None
        try:
            return release_service.find_primary_release_for_track(int(derivative.track_id))
        except Exception:
            return None

    def _verify_target_path(self, derivative: DerivativeLedgerRecord | None) -> Path | None:
        if derivative is None:
            return None
        candidate = str(derivative.managed_file_path or "").strip()
        if not candidate:
            return None
        path = Path(candidate)
        return path if path.exists() else None

    def _batch_lines(self, batch) -> list[str]:
        return [
            f"Batch ID: {batch.batch_id}",
            f"Created: {batch.created_at}",
            f"Completed: {batch.completed_at or '(pending)'}",
            f"Workflow: {self._workflow_label(batch.derivative_kind, batch.authenticity_basis)}",
            f"Format: {batch.output_format.upper()}",
            f"Exported: {batch.exported_count} of {batch.requested_count}",
            f"Skipped: {batch.skipped_count}",
            f"Package mode: {(batch.package_mode or 'directory').replace('_', ' ')}",
            (
                f"ZIP package: {batch.zip_filename}"
                if batch.zip_filename
                else "ZIP package: not used"
            ),
            f"Status: {batch.status}",
            f"Profile: {batch.profile_name or '(not recorded)'}",
        ]

    def _derivative_lines(self, derivative: DerivativeLedgerRecord) -> list[str]:
        return [
            f"Export ID: {derivative.export_id}",
            f"Batch ID: {derivative.batch_id}",
            f"Track: {derivative.track_title or '(unknown)'}"
            + (f" (#{derivative.track_id})" if derivative.track_id is not None else ""),
            f"Output file: {derivative.output_filename}",
            f"Output format: {derivative.output_format.upper()}",
            f"Derivative kind: {derivative.derivative_kind.replace('_', ' ')}",
            f"Authenticity basis: {derivative.authenticity_basis.replace('_', ' ')}",
            f"Watermark applied: {'Yes' if derivative.watermark_applied else 'No'}",
            f"Catalog metadata embedded: {'Yes' if derivative.metadata_embedded else 'No'}",
            f"Output size: {self._human_size(derivative.output_size_bytes)}",
            f"Output SHA-256: {derivative.output_sha256}",
            f"Source storage: {derivative.source_storage_mode or '(not recorded)'}",
            f"Source lineage: {derivative.source_lineage_ref}",
            (
                f"Manifest ID: {derivative.derivative_manifest_id}"
                if derivative.derivative_manifest_id
                else "Manifest ID: none"
            ),
            f"Batch created: {derivative.batch_created_at}",
            f"Batch completed: {derivative.batch_completed_at or '(pending)'}",
            f"Package mode: {(derivative.package_mode or 'directory').replace('_', ' ')}",
            (
                f"ZIP package: {derivative.zip_filename}"
                if derivative.zip_filename
                else "ZIP package: not used"
            ),
            (
                f"Exported file path: {derivative.managed_file_path}"
                if derivative.managed_file_path
                else "Exported file path: not retained"
            ),
            (
                f"Sidecar path: {derivative.sidecar_path}"
                if derivative.sidecar_path
                else "Sidecar path: none"
            ),
            (
                f"ZIP member: {derivative.package_member_path}"
                if derivative.package_member_path
                else "ZIP member: not packaged"
            ),
            f"Status: {derivative.status}",
        ]

    def _apply_batch_details(self, batch) -> None:
        self._clear_detail_fields()
        self.selected_batch_heading.setText(f"Selected Batch: {batch.batch_id}")
        self._set_detail_label(self.batch_id_value, batch.batch_id)
        self._set_detail_label(self.batch_created_value, batch.created_at)
        self._set_detail_label(self.batch_completed_value, batch.completed_at, empty="(pending)")
        self._set_detail_label(
            self.batch_workflow_value,
            self._workflow_label(batch.derivative_kind, batch.authenticity_basis),
        )
        self._set_detail_label(
            self.batch_totals_value,
            f"{batch.exported_count} exported / {batch.requested_count} requested / {batch.skipped_count} skipped",
        )
        self._set_detail_label(self.batch_status_value, batch.status.title())
        self._set_detail_label(
            self.batch_package_mode_value,
            (batch.package_mode or "directory").replace("_", " ").title(),
        )
        self._set_detail_label(self.batch_profile_value, batch.profile_name, empty="(not recorded)")
        self._set_detail_label(self.zip_filename_value, batch.zip_filename, empty="not used")
        self.selection_label.setText(
            f"Batch {batch.batch_id} selected. Use the tabs to review outputs, details, lineage, and cleanup actions."
        )
        self.admin_summary_label.setText(
            f"Selected batch: {batch.batch_id}. Deleting it removes the batch record and its derivative ledger rows from the catalog database only."
        )
        self.details_edit.setPlainText("\n".join(self._batch_lines(batch)))

    def _apply_derivative_details(self, derivative: DerivativeLedgerRecord) -> None:
        track_label = derivative.track_title or "(unknown)"
        if derivative.track_id is not None:
            track_label = f"{track_label} (#{derivative.track_id})"
        self.selected_batch_heading.setText(f"Selected Batch: {derivative.batch_id}")
        self._set_detail_label(self.output_track_value, track_label)
        self._set_detail_label(self.output_filename_value, derivative.output_filename)
        self._set_detail_label(self.output_format_value, derivative.output_format.upper())
        self._set_detail_label(
            self.output_kind_value, derivative.derivative_kind.replace("_", " ").title()
        )
        self._set_detail_label(
            self.output_authenticity_value,
            derivative.authenticity_basis.replace("_", " ").title(),
        )
        self._set_detail_label(
            self.output_watermark_value, "Yes" if derivative.watermark_applied else "No"
        )
        self._set_detail_label(
            self.output_metadata_value, "Yes" if derivative.metadata_embedded else "No"
        )
        self._set_detail_label(
            self.output_size_value, self._human_size(derivative.output_size_bytes)
        )
        self._set_detail_label(self.output_status_value, derivative.status.title())
        self._set_detail_label(self.export_id_value, derivative.export_id)
        self._set_detail_label(self.output_sha_value, derivative.output_sha256)
        self._set_detail_label(
            self.source_storage_value, derivative.source_storage_mode, empty="(not recorded)"
        )
        self._set_detail_label(self.source_lineage_value, derivative.source_lineage_ref)
        self._set_detail_label(
            self.manifest_id_value, derivative.derivative_manifest_id, empty="none"
        )
        self._set_detail_label(self.zip_filename_value, derivative.zip_filename, empty="not used")
        self._set_detail_label(
            self.managed_file_path_value, derivative.managed_file_path, empty="not retained"
        )
        self._set_detail_label(self.sidecar_path_value, derivative.sidecar_path, empty="none")
        self._set_detail_label(
            self.package_member_value, derivative.package_member_path, empty="not packaged"
        )
        self.selection_label.setText(
            f"Batch {derivative.batch_id} selected. Current output: {derivative.output_filename}."
        )
        self.admin_summary_label.setText(
            f"Selected output: {derivative.output_filename}. Deleting the derivative removes only its database row and leaves files on disk untouched."
        )
        self.details_edit.setPlainText("\n".join(self._derivative_lines(derivative)))

    def _update_summary_label(self) -> None:
        summary = f"{len(self._batches)} batch(es) shown."
        batch = self._selected_batch_record()
        if batch is not None:
            summary = (
                f"{summary} {len(self._derivatives)} derivative row(s) shown for {batch.batch_id}."
            )
        self.summary_label.setText(summary)

    @staticmethod
    def _existing_output_paths(derivative: DerivativeLedgerRecord | None) -> list[tuple[str, Path]]:
        if derivative is None:
            return []
        output_paths: list[tuple[str, Path]] = []
        for label, raw_value in (
            ("Exported output file", derivative.managed_file_path),
            ("Sidecar file", derivative.sidecar_path),
        ):
            clean_value = str(raw_value or "").strip()
            if not clean_value:
                continue
            path = Path(clean_value)
            if path.exists():
                output_paths.append((label, path))
        return output_paths

    def _update_drill_in_actions(self) -> None:
        derivative = self._selected_derivative()
        host = self._drill_in_host()
        can_open_track = bool(
            derivative is not None
            and derivative.track_id is not None
            and callable(getattr(host, "open_selected_editor", None))
        )
        self.open_track_button.setEnabled(can_open_track)
        self.open_track_button.setToolTip(
            "Open the related track in the main editor."
            if can_open_track
            else "Select a derivative row with a related track to open the track editor."
        )

        release = self._resolve_primary_release(derivative)
        can_open_release = bool(
            release is not None and callable(getattr(host, "open_release_editor", None))
        )
        self.open_release_button.setEnabled(can_open_release)
        self.open_release_button.setToolTip(
            f"Open the primary release '{release.title}'."
            if can_open_release
            else "The selected derivative's track is not linked to a release yet."
        )

        verification_path = self._verify_target_path(derivative)
        can_verify = bool(
            verification_path is not None
            and callable(getattr(host, "verify_audio_authenticity", None))
        )
        self.verify_authenticity_button.setEnabled(can_verify)
        self.verify_authenticity_button.setToolTip(
            f"Verify authenticity for {verification_path.name}."
            if can_verify
            else "Authenticity verification is available when the exported output file is still present on disk."
        )

        service = self._ledger_service()
        self.delete_derivative_button.setEnabled(service is not None and derivative is not None)
        self.delete_batch_button.setEnabled(
            service is not None and self._selected_batch_record() is not None
        )
        self.delete_output_files_button.setEnabled(
            service is not None and bool(self._existing_output_paths(derivative))
        )
        self.refresh_admin_button.setEnabled(service is not None)

    def focus_derivative(self, export_id: str | None) -> None:
        clean_export_id = str(export_id or "").strip()
        if not clean_export_id:
            return
        for row in range(self.derivative_table.rowCount()):
            item = self.derivative_table.item(row, 0)
            if item is None:
                continue
            if str(item.data(Qt.UserRole) or "").strip() != clean_export_id:
                continue
            self.derivative_table.selectRow(row)
            self._show_selected_derivative()
            return

    def _open_selected_track(self) -> None:
        derivative = self._selected_derivative()
        host = self._drill_in_host()
        opener = getattr(host, "open_selected_editor", None) if host is not None else None
        if derivative is None or derivative.track_id is None or not callable(opener):
            return
        opener(int(derivative.track_id))

    def _open_selected_release(self) -> None:
        derivative = self._selected_derivative()
        host = self._drill_in_host()
        opener = getattr(host, "open_release_editor", None) if host is not None else None
        release = self._resolve_primary_release(derivative)
        if release is None or not callable(opener):
            return
        opener(int(release.id))

    def _verify_selected_derivative(self) -> None:
        derivative = self._selected_derivative()
        host = self._drill_in_host()
        opener = getattr(host, "verify_audio_authenticity", None) if host is not None else None
        verification_path = self._verify_target_path(derivative)
        if verification_path is None or not callable(opener):
            return
        opener(str(verification_path))

    def _delete_selected_derivative(self) -> None:
        service = self._ledger_service()
        if service is None:
            QMessageBox.warning(self, "Derivative Ledger", "Open a profile first.")
            return
        derivative = self._selected_derivative()
        batch = self._selected_batch_record()
        if derivative is None or batch is None:
            QMessageBox.information(self, "Derivative Ledger", "Select a derivative row first.")
            return
        if not _confirm_destructive_action(
            self,
            title="Delete Derivative Ledger Entry",
            prompt=(
                f"Delete the selected derivative ledger entry for '{derivative.output_filename}'?"
            ),
            consequences=[
                (
                    "This removes the database record only. Exported files on disk are not "
                    "deleted, and the batch keeps its historical export totals."
                )
            ],
        ):
            return
        service.delete_derivative(derivative.export_id)
        self.refresh()
        self.focus_batch(batch.batch_id)

    def _delete_selected_output_files(self) -> None:
        service = self._ledger_service()
        if service is None:
            QMessageBox.warning(self, "Derivative Ledger", "Open a profile first.")
            return
        derivative = self._selected_derivative()
        batch = self._selected_batch_record()
        if derivative is None or batch is None:
            QMessageBox.information(self, "Derivative Ledger", "Select a derivative row first.")
            return
        output_paths = self._existing_output_paths(derivative)
        if not output_paths:
            QMessageBox.information(
                self,
                "Derivative Ledger",
                "No retained output or sidecar files are currently available to delete for the selected derivative.",
            )
            return
        listed_paths = "\n".join(f"- {label}: {path}" for label, path in output_paths)
        if not _confirm_destructive_action(
            self,
            title="Delete Retained Output Files",
            prompt=f"Delete the retained files for '{derivative.output_filename}'?",
            consequences=[
                listed_paths,
                "This deletes only the files listed above. The ledger entry remains in the database.",
            ],
        ):
            return
        delete_output = any(label == "Exported output file" for label, _path in output_paths)
        delete_sidecar = any(label == "Sidecar file" for label, _path in output_paths)
        try:
            for _label, path in output_paths:
                path.unlink(missing_ok=True)
            service.update_derivative_artifacts(
                derivative.export_id,
                managed_file_path=None if delete_output else derivative.managed_file_path,
                sidecar_path=None if delete_sidecar else derivative.sidecar_path,
                package_member_path=derivative.package_member_path,
            )
        except Exception as exc:
            QMessageBox.critical(self, "Derivative Ledger", str(exc))
            return
        self.refresh()
        self.focus_batch(batch.batch_id)
        self.focus_derivative(derivative.export_id)

    def _delete_selected_batch(self) -> None:
        service = self._ledger_service()
        if service is None:
            QMessageBox.warning(self, "Derivative Ledger", "Open a profile first.")
            return
        batch = self._selected_batch_record()
        if batch is None:
            QMessageBox.information(self, "Derivative Ledger", "Select a batch first.")
            return
        derivative_count = len(self._derivatives)
        if not _confirm_destructive_action(
            self,
            title="Delete Export Batch",
            prompt=(
                f"Delete batch '{batch.batch_id}' and its {derivative_count} registered "
                f"derivative ledger entr{'y' if derivative_count == 1 else 'ies'}?"
            ),
            consequences=[
                "This removes database records only. Exported files on disk are not deleted."
            ],
        ):
            return
        service.delete_batch(batch.batch_id)
        self.refresh()

    def refresh(self) -> None:
        selected_batch_id = self._selected_batch_id()
        service = self._ledger_service()
        self._batches = []
        self._derivatives = []
        self.batch_table.setRowCount(0)
        self.derivative_table.setRowCount(0)
        if service is None:
            self.summary_label.setText(
                "Open a profile first to inspect managed derivative exports."
            )
            self.selected_batch_heading.setText("Selected Batch")
            self.selection_label.setText(
                "No derivative ledger is available without an open profile."
            )
            self.derivative_summary_label.setText(
                "Open a profile first to browse export batches and registered outputs."
            )
            self.admin_summary_label.setText(
                "Cleanup tools become available when a profile is open."
            )
            self._clear_detail_fields()
            self.details_edit.setPlainText(
                "No derivative ledger is available without an open profile."
            )
            self._update_drill_in_actions()
            return
        unfiltered_batches = service.list_batches(
            search_text=self.search_edit.text(),
            limit=1000,
        )
        self._populate_filter_combo(
            self.format_filter_combo,
            [batch.output_format for batch in unfiltered_batches],
            "All Formats",
            formatter=lambda value: value.upper(),
        )
        self._populate_filter_combo(
            self.kind_filter_combo,
            [batch.derivative_kind for batch in unfiltered_batches],
            "All Kinds",
            formatter=lambda value: value.replace("_", " ").title(),
        )
        self._populate_filter_combo(
            self.status_filter_combo,
            [batch.status for batch in unfiltered_batches],
            "All Statuses",
            formatter=lambda value: value.title(),
        )
        self._batches = service.list_batches(
            search_text=self.search_edit.text(),
            output_format=self._filter_value(self.format_filter_combo),
            derivative_kind=self._filter_value(self.kind_filter_combo),
            status=self._filter_value(self.status_filter_combo),
        )
        self.batch_table.setRowCount(len(self._batches))
        for row, batch in enumerate(self._batches):
            values = [
                batch.batch_id,
                batch.created_at,
                batch.output_format.upper(),
                self._workflow_label(batch.derivative_kind, batch.authenticity_basis),
                f"{batch.exported_count}/{batch.requested_count}",
                (batch.package_mode or "directory").replace("_", " ").title(),
                batch.status.title(),
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value or ""))
                if col == 0:
                    item.setData(Qt.UserRole, batch.batch_id)
                self.batch_table.setItem(row, col, item)
        self.batch_table.resizeRowsToContents()
        if self._batches:
            target_batch_id = selected_batch_id
            if not any(batch.batch_id == target_batch_id for batch in self._batches):
                target_batch_id = self._batches[0].batch_id
            self.focus_batch(target_batch_id)
        else:
            self._clear_detail_fields()
            self.selected_batch_heading.setText("Selected Batch")
            self.selection_label.setText("No export batch matches the current search.")
            self.derivative_summary_label.setText(
                "Adjust the search to review registered derivative outputs."
            )
            self.admin_summary_label.setText(
                "Cleanup tools become available when a batch is selected."
            )
            self.details_edit.setPlainText("No derivative exports match the current search.")
            self._update_summary_label()
            self._update_drill_in_actions()

    def focus_batch(self, batch_id: str | None) -> None:
        clean_batch_id = str(batch_id or "").strip()
        if not clean_batch_id:
            return
        for row in range(self.batch_table.rowCount()):
            item = self.batch_table.item(row, 0)
            if item is None:
                continue
            if str(item.data(Qt.UserRole) or "") != clean_batch_id:
                continue
            self.batch_table.selectRow(row)
            self._load_selected_batch()
            return

    def _load_selected_batch(self) -> None:
        batch_id = self._selected_batch_id()
        service = self._ledger_service()
        self._derivatives = []
        self.derivative_table.setRowCount(0)
        if service is None or not batch_id:
            self._clear_detail_fields()
            self.selected_batch_heading.setText("Selected Batch")
            self.selection_label.setText("Select a batch to review its derivatives and details.")
            self.derivative_summary_label.setText("No batch selected.")
            self.admin_summary_label.setText(
                "Cleanup tools become available when a batch is selected."
            )
            self.details_edit.setPlainText("")
            self._update_summary_label()
            self._update_drill_in_actions()
            return
        self._derivatives = service.list_derivatives(
            batch_id=batch_id,
            search_text=self.search_edit.text(),
            output_format=self._filter_value(self.format_filter_combo),
            derivative_kind=self._filter_value(self.kind_filter_combo),
            status=self._filter_value(self.status_filter_combo),
        )
        self.derivative_table.setRowCount(len(self._derivatives))
        for row, derivative in enumerate(self._derivatives):
            values = [
                derivative.track_title
                or (f"Track #{derivative.track_id}" if derivative.track_id else ""),
                derivative.output_filename,
                derivative.output_format.upper(),
                derivative.derivative_kind.replace("_", " ").title(),
                "Yes" if derivative.watermark_applied else "No",
                self._human_size(derivative.output_size_bytes),
                derivative.status.title(),
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value or ""))
                if col == 0:
                    item.setData(Qt.UserRole, derivative.export_id)
                self.derivative_table.setItem(row, col, item)
        self.derivative_table.resizeRowsToContents()
        batch = self._selected_batch_record()
        self._update_summary_label()
        if batch is None:
            self.selected_batch_heading.setText("Selected Batch")
            self.selection_label.setText(
                "No derivative details are available for the selected batch."
            )
            self.derivative_summary_label.setText("No batch selected.")
            self.admin_summary_label.setText(
                "Cleanup tools become available when a batch is selected."
            )
            self.details_edit.setPlainText(
                "No derivative details are available for the selected batch."
            )
            self._update_drill_in_actions()
            return
        self._apply_batch_details(batch)
        if self._derivatives:
            self.derivative_summary_label.setText(
                f"{len(self._derivatives)} derivative row(s) shown for batch {batch.batch_id}."
            )
            self.derivative_table.selectRow(0)
            self._show_selected_derivative()
            return
        self.derivative_summary_label.setText(
            "No registered derivatives match the current search for this batch."
        )
        self._update_drill_in_actions()

    def _show_selected_derivative(self) -> None:
        derivative = self._selected_derivative()
        batch = self._selected_batch_record()
        if batch is None:
            self._clear_detail_fields()
            self.selected_batch_heading.setText("Selected Batch")
            self.details_edit.setPlainText("")
            self._update_summary_label()
            self._update_drill_in_actions()
            return
        self._apply_batch_details(batch)
        if derivative is None:
            self._update_summary_label()
            self._update_drill_in_actions()
            return
        self._apply_derivative_details(derivative)
        self.derivative_summary_label.setText(
            f"{len(self._derivatives)} derivative row(s) shown for batch {batch.batch_id}."
        )
        self._update_summary_label()
        self._update_drill_in_actions()


class AssetBrowserPanel(QWidget):
    """Browse registered master and deliverable variants inside a workspace panel."""

    def __init__(self, *, asset_service_provider, drill_in_host_provider=None, parent=None):
        super().__init__(parent)
        self.asset_service_provider = asset_service_provider
        self.drill_in_host_provider = drill_in_host_provider
        self.setObjectName("assetBrowserPanel")
        _apply_standard_widget_chrome(self, "assetBrowserPanel")

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(14)
        _add_standard_dialog_header(
            root,
            self,
            title="Deliverables and Asset Versions",
            subtitle=(
                "Maintain master, derivative, and artwork versions alongside the managed derivative export ledger."
            ),
        )
        self.workspace_tabs = QTabWidget(self)
        self.workspace_tabs.setObjectName("assetBrowserTabs")
        self.workspace_tabs.setDocumentMode(True)
        root.addWidget(self.workspace_tabs, 1)

        self.asset_registry_tab = QWidget(self.workspace_tabs)
        asset_tab_layout = QVBoxLayout(self.asset_registry_tab)
        asset_tab_layout.setContentsMargins(0, 0, 0, 0)
        asset_tab_layout.setSpacing(14)

        controls_box, controls_layout = _create_standard_section(
            self.asset_registry_tab,
            "Find and Manage",
            "Search by filename, asset type, or version status, then maintain the selected asset record.",
        )
        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(10)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search by filename, type, or version status...")
        self.search_edit.textChanged.connect(self.refresh)
        controls.addWidget(self.search_edit, 1)
        controls_layout.addLayout(controls)
        action_buttons: list[QPushButton] = []
        for label, handler in (
            ("Add", self.create_asset),
            ("Edit", self.edit_selected),
            ("Mark Primary", self.mark_primary),
            ("Delete", self.delete_selected),
            ("Refresh", self.refresh),
        ):
            button = QPushButton(label)
            button.clicked.connect(handler)
            action_buttons.append(button)
        self.asset_actions_cluster = _create_action_button_cluster(
            self.asset_registry_tab,
            action_buttons,
            columns=2,
            min_button_width=160,
            span_last_row=True,
        )
        self.asset_actions_cluster.setObjectName("assetRegistryActionsCluster")
        controls_layout.addWidget(self.asset_actions_cluster)
        asset_tab_layout.addWidget(controls_box)

        table_box, table_layout = _create_standard_section(
            self.asset_registry_tab,
            "Asset Registry",
            "Double-click a row to edit a registered asset version.",
        )
        self.table = QTableWidget(0, 8, table_box)
        self.table.setHorizontalHeaderLabels(
            ["ID", "Filename", "Type", "Track", "Release", "Approved", "Primary", "Status"]
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
        self.table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeToContents)
        self.table.doubleClicked.connect(lambda _index: self.edit_selected())
        table_layout.addWidget(self.table, 1)
        asset_tab_layout.addWidget(table_box, 1)

        self.derivative_ledger_tab = _DerivativeLedgerPane(
            ledger_service_provider=self._derivative_ledger_service,
            drill_in_host_provider=self.drill_in_host_provider,
            parent=self.workspace_tabs,
        )

        self.workspace_tabs.addTab(self.asset_registry_tab, "Asset Registry")
        self.workspace_tabs.addTab(self.derivative_ledger_tab, "Derivative Ledger")

        _apply_compact_dialog_control_heights(self)

        self.refresh()

    def _asset_service(self) -> AssetService | None:
        return self.asset_service_provider()

    def _derivative_ledger_service(self) -> DerivativeLedgerService | None:
        service = self._asset_service()
        conn = getattr(service, "conn", None) if service is not None else None
        if conn is None:
            return None
        return DerivativeLedgerService(conn)

    def focus_tab(self, tab_name: str = "assets") -> None:
        normalized = str(tab_name or "").strip().lower()
        if normalized in {"derivatives", "derivative_ledger", "ledger"}:
            self.workspace_tabs.setCurrentWidget(self.derivative_ledger_tab)
            return
        self.workspace_tabs.setCurrentWidget(self.asset_registry_tab)

    def _restore_selection(self, asset_id: int | None) -> None:
        if not asset_id:
            return
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is None:
                continue
            try:
                current_asset_id = int(item.text())
            except Exception:
                continue
            if current_asset_id != int(asset_id):
                continue
            self.table.selectRow(row)
            return

    def focus_asset(self, asset_id: int | None) -> None:
        self.focus_tab("assets")
        self.table.clearSelection()
        self._restore_selection(asset_id)

    def focus_derivative_batch(self, batch_id: str | None) -> None:
        self.focus_tab("derivatives")
        self.derivative_ledger_tab.focus_batch(batch_id)

    def _selected_asset_id(self) -> int | None:
        selection_model = self.table.selectionModel()
        if selection_model is None:
            return None
        rows = selection_model.selectedRows()
        if not rows:
            return None
        item = self.table.item(rows[0].row(), 0)
        return int(item.text()) if item is not None else None

    def refresh(self) -> None:
        selected_asset_id = self._selected_asset_id()
        service = self._asset_service()
        if service is None:
            self.table.setRowCount(0)
            self.derivative_ledger_tab.refresh()
            return
        assets = service.list_assets(search_text=self.search_edit.text())
        self.table.setRowCount(0)
        for asset in assets:
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = [
                str(asset.id),
                asset.filename,
                asset.asset_type.replace("_", " ").title(),
                str(asset.track_id or ""),
                str(asset.release_id or ""),
                "Yes" if asset.approved_for_use else "No",
                "Yes" if asset.primary_flag else "No",
                asset.version_status or "",
            ]
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))
        self.table.resizeColumnsToContents()
        self._restore_selection(selected_asset_id)
        self.derivative_ledger_tab.refresh()

    def create_asset(self) -> None:
        service = self._asset_service()
        if service is None:
            QMessageBox.warning(self, "Asset Registry", "Open a profile first.")
            return
        dialog = AssetEditorDialog(asset_service=service, parent=self)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            asset_id = service.create_asset(dialog.payload())
        except Exception as exc:
            QMessageBox.critical(self, "Asset Registry", str(exc))
            return
        self.refresh()
        self.focus_asset(asset_id)

    def edit_selected(self) -> None:
        service = self._asset_service()
        if service is None:
            QMessageBox.warning(self, "Asset Registry", "Open a profile first.")
            return
        asset_id = self._selected_asset_id()
        if not asset_id:
            QMessageBox.information(self, "Asset Registry", "Select an asset first.")
            return
        asset = service.fetch_asset(asset_id)
        if asset is None:
            self.refresh()
            return
        dialog = AssetEditorDialog(asset_service=service, asset=asset, parent=self)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            service.update_asset(asset_id, dialog.payload())
        except Exception as exc:
            QMessageBox.critical(self, "Asset Registry", str(exc))
            return
        self.refresh()
        self.focus_asset(asset_id)

    def delete_selected(self) -> None:
        service = self._asset_service()
        if service is None:
            QMessageBox.warning(self, "Asset Registry", "Open a profile first.")
            return
        asset_id = self._selected_asset_id()
        if not asset_id:
            QMessageBox.information(self, "Asset Registry", "Select an asset first.")
            return
        if not _confirm_destructive_action(
            self,
            title="Delete Asset",
            prompt="Delete the selected asset record?",
        ):
            return
        service.delete_asset(asset_id)
        self.refresh()

    def mark_primary(self) -> None:
        service = self._asset_service()
        if service is None:
            QMessageBox.warning(self, "Asset Registry", "Open a profile first.")
            return
        asset_id = self._selected_asset_id()
        if not asset_id:
            QMessageBox.information(self, "Asset Registry", "Select an asset first.")
            return
        service.mark_primary(asset_id)
        self.refresh()
        self.focus_asset(asset_id)


class AssetBrowserDialog(QDialog):
    """Compatibility dialog wrapper around the reusable asset registry panel."""

    def __init__(self, *, asset_service: AssetService, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Deliverables and Asset Versions")
        self.resize(1060, 700)
        self.setMinimumSize(940, 620)
        _apply_standard_dialog_chrome(self, "assetBrowserDialog")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.panel = AssetBrowserPanel(
            asset_service_provider=lambda: asset_service,
            drill_in_host_provider=(lambda: parent),
            parent=self,
        )
        root.addWidget(self.panel)

    def __getattr__(self, name: str):
        panel = self.__dict__.get("panel")
        if panel is not None and hasattr(panel, name):
            return getattr(panel, name)
        raise AttributeError(name)

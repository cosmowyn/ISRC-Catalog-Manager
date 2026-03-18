"""Deliverable and asset registry dialogs."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
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
    _add_standard_dialog_header,
    _apply_compact_dialog_control_heights,
    _apply_standard_dialog_chrome,
    _apply_standard_widget_chrome,
    _configure_standard_form_layout,
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
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(0, 0, 0, 0)
            page_layout.setSpacing(0)
            scroll_area, _, content_layout = _create_scrollable_dialog_content(page)
            page_layout.addWidget(scroll_area, 1)
            self.tabs.addTab(page, title)
            return content_layout

        target_box, target_layout = _create_standard_section(
            self,
            "Target Record",
            "Link the asset to a track or release, then describe the type and status of the version.",
        )
        target_form = QFormLayout()
        _configure_standard_form_layout(target_form)

        self.track_id_edit = QLineEdit()
        target_form.addRow("Track ID", self.track_id_edit)

        self.release_id_edit = QLineEdit()
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
        self.storage_mode_combo.addItem("Database (BLOB)", STORAGE_MODE_DATABASE)
        self.storage_mode_combo.addItem("Managed file", STORAGE_MODE_MANAGED_FILE)
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
            self.track_id_edit.setText(str(asset.track_id or ""))
            self.release_id_edit.setText(str(asset.release_id or ""))
            self.asset_type_combo.setCurrentText(asset.asset_type.replace("_", " ").title())
            resolved = self.asset_service.resolve_asset_path(asset.stored_path)
            self.file_edit.setText(str(resolved) if resolved is not None else "")
            self.status_edit.setText(asset.version_status or "")
            self.format_edit.setText(asset.format or "")
            self.storage_mode_combo.setCurrentIndex(
                0
                if normalize_storage_mode(
                    asset.storage_mode, default=STORAGE_MODE_MANAGED_FILE
                )
                == STORAGE_MODE_DATABASE
                else 1
            )
            self.approved_checkbox.setChecked(asset.approved_for_use)
            self.primary_checkbox.setChecked(asset.primary_flag)
            self.notes_edit.setPlainText(asset.notes or "")
        else:
            self.storage_mode_combo.setCurrentIndex(1)

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
            track_id=int(self.track_id_edit.text()) if self.track_id_edit.text().strip() else None,
            release_id=(
                int(self.release_id_edit.text()) if self.release_id_edit.text().strip() else None
            ),
        )


class AssetBrowserPanel(QWidget):
    """Browse registered master and deliverable variants inside a workspace panel."""

    def __init__(self, *, asset_service_provider, parent=None):
        super().__init__(parent)
        self.asset_service_provider = asset_service_provider
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
                "Track alternate masters, derivatives, and artwork variants so one "
                "repertoire item can safely have multiple usable files."
            ),
        )

        controls_box, controls_layout = _create_standard_section(
            self,
            "Find and Manage",
            "Search by filename, asset type, or version status, then maintain the selected managed asset record.",
        )
        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(8)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search by filename, type, or version status...")
        self.search_edit.textChanged.connect(self.refresh)
        controls.addWidget(self.search_edit, 1)
        for label, handler in (
            ("Add", self.create_asset),
            ("Edit", self.edit_selected),
            ("Delete", self.delete_selected),
            ("Mark Primary", self.mark_primary),
            ("Refresh", self.refresh),
        ):
            button = QPushButton(label)
            button.clicked.connect(handler)
            controls.addWidget(button)
        controls_layout.addLayout(controls)
        root.addWidget(controls_box)

        table_box, table_layout = _create_standard_section(
            self,
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
        root.addWidget(table_box, 1)

        _apply_compact_dialog_control_heights(self)

        self.refresh()

    def _asset_service(self) -> AssetService | None:
        return self.asset_service_provider()

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
        self.table.clearSelection()
        self._restore_selection(asset_id)

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
        if (
            QMessageBox.question(self, "Delete Asset", "Delete the selected asset record?")
            != QMessageBox.Yes
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
            parent=self,
        )
        root.addWidget(self.panel)

    def __getattr__(self, name: str):
        panel = self.__dict__.get("panel")
        if panel is not None and hasattr(panel, name):
            return getattr(panel, name)
        raise AttributeError(name)

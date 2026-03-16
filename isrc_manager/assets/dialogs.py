"""Deliverable and asset registry dialogs."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
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
        self.resize(620, 520)

        root = QVBoxLayout(self)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignTop)

        self.track_id_edit = QLineEdit()
        form.addRow("Track ID", self.track_id_edit)

        self.release_id_edit = QLineEdit()
        form.addRow("Release ID", self.release_id_edit)

        self.asset_type_combo = QComboBox()
        self.asset_type_combo.addItems(
            [item.replace("_", " ").title() for item in ASSET_TYPE_CHOICES]
        )
        form.addRow("Asset Type", self.asset_type_combo)

        self.file_edit = QLineEdit()
        self.file_edit.setReadOnly(True)
        file_row = QHBoxLayout()
        file_row.addWidget(self.file_edit, 1)
        browse_button = QPushButton("Browse…")
        browse_button.clicked.connect(self._pick_file)
        file_row.addWidget(browse_button)
        form.addRow("Source File", file_row)

        self.status_edit = QLineEdit()
        form.addRow("Version Status", self.status_edit)

        self.format_edit = QLineEdit()
        form.addRow("Format", self.format_edit)

        self.approved_checkbox = QCheckBox("Approved for use")
        self.primary_checkbox = QCheckBox("Primary asset")
        flags_row = QHBoxLayout()
        flags_row.addWidget(self.approved_checkbox)
        flags_row.addWidget(self.primary_checkbox)
        flags_row.addStretch(1)
        form.addRow("Flags", flags_row)

        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setMinimumHeight(100)
        form.addRow("Notes", self.notes_edit)
        root.addLayout(form)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        save_button = QPushButton("Save")
        save_button.clicked.connect(self.accept)
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        buttons.addWidget(save_button)
        buttons.addWidget(cancel_button)
        root.addLayout(buttons)

        if asset is not None:
            self.track_id_edit.setText(str(asset.track_id or ""))
            self.release_id_edit.setText(str(asset.release_id or ""))
            self.asset_type_combo.setCurrentText(asset.asset_type.replace("_", " ").title())
            resolved = self.asset_service.resolve_asset_path(asset.stored_path)
            self.file_edit.setText(str(resolved) if resolved is not None else "")
            self.status_edit.setText(asset.version_status or "")
            self.format_edit.setText(asset.format or "")
            self.approved_checkbox.setChecked(asset.approved_for_use)
            self.primary_checkbox.setChecked(asset.primary_flag)
            self.notes_edit.setPlainText(asset.notes or "")

    def _pick_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select Asset File", "")
        if path:
            self.file_edit.setText(path)

    def payload(self) -> AssetVersionPayload:
        return AssetVersionPayload(
            asset_type=self.asset_type_combo.currentText().strip().lower().replace(" ", "_"),
            source_path=self.file_edit.text().strip() or None,
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


class AssetBrowserDialog(QDialog):
    """Browse registered master and deliverable variants."""

    def __init__(self, *, asset_service: AssetService, parent=None):
        super().__init__(parent)
        self.asset_service = asset_service
        self.setWindowTitle("Deliverables and Asset Versions")
        self.resize(1000, 620)

        root = QVBoxLayout(self)
        intro = QLabel(
            "Track alternate masters, derivatives, and artwork variants here so one repertoire item can safely have multiple usable files."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        controls = QHBoxLayout()
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
        root.addLayout(controls)

        self.table = QTableWidget(0, 8, self)
        self.table.setHorizontalHeaderLabels(
            ["ID", "Filename", "Type", "Track", "Release", "Approved", "Primary", "Status"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.doubleClicked.connect(lambda _index: self.edit_selected())
        root.addWidget(self.table, 1)

        self.refresh()

    def _selected_asset_id(self) -> int | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        item = self.table.item(rows[0].row(), 0)
        return int(item.text()) if item is not None else None

    def refresh(self) -> None:
        assets = self.asset_service.list_assets(search_text=self.search_edit.text())
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

    def create_asset(self) -> None:
        dialog = AssetEditorDialog(asset_service=self.asset_service, parent=self)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            self.asset_service.create_asset(dialog.payload())
        except Exception as exc:
            QMessageBox.critical(self, "Asset Registry", str(exc))
            return
        self.refresh()

    def edit_selected(self) -> None:
        asset_id = self._selected_asset_id()
        if not asset_id:
            QMessageBox.information(self, "Asset Registry", "Select an asset first.")
            return
        asset = self.asset_service.fetch_asset(asset_id)
        if asset is None:
            self.refresh()
            return
        dialog = AssetEditorDialog(asset_service=self.asset_service, asset=asset, parent=self)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            self.asset_service.update_asset(asset_id, dialog.payload())
        except Exception as exc:
            QMessageBox.critical(self, "Asset Registry", str(exc))
            return
        self.refresh()

    def delete_selected(self) -> None:
        asset_id = self._selected_asset_id()
        if not asset_id:
            QMessageBox.information(self, "Asset Registry", "Select an asset first.")
            return
        if (
            QMessageBox.question(self, "Delete Asset", "Delete the selected asset record?")
            != QMessageBox.Yes
        ):
            return
        self.asset_service.delete_asset(asset_id)
        self.refresh()

    def mark_primary(self) -> None:
        asset_id = self._selected_asset_id()
        if not asset_id:
            QMessageBox.information(self, "Asset Registry", "Select an asset first.")
            return
        self.asset_service.mark_primary(asset_id)
        self.refresh()

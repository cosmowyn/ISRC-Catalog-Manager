"""Application settings dialog."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QCompleter,
    QFileDialog,
    QMessageBox,
)

from isrc_manager.file_storage import (
    STORAGE_MODE_DATABASE,
    normalize_storage_mode,
)
from isrc_manager.services import (
    GS1ContractImportError,
)
from isrc_manager.services.gs1_mapping import (
    COMMON_CLASSIFICATION_CHOICES,
    COMMON_LANGUAGE_CHOICES,
    COMMON_MARKET_CHOICES,
    COMMON_PACKAGING_CHOICES,
)
from isrc_manager.ui_common import (
    FocusWheelComboBox,
)


class ApplicationSettingsGs1Mixin:
    def _create_gs1_default_combo(self, *, initial_text: str, placeholder: str) -> QComboBox:
        combo = FocusWheelComboBox(self)
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.NoInsert)
        combo.setMinimumWidth(320)
        combo.setMaximumWidth(520)
        combo.setCurrentText(str(initial_text or "").strip())
        line_edit = combo.lineEdit()
        if line_edit is not None:
            line_edit.setClearButtonEnabled(True)
            line_edit.setPlaceholderText(placeholder)
        return combo

    def _create_gs1_contract_combo(self, *, initial_text: str) -> QComboBox:
        combo = FocusWheelComboBox(self)
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.NoInsert)
        combo.setMinimumWidth(320)
        combo.setMaximumWidth(520)
        combo.setCurrentText(str(initial_text or "").strip())
        line_edit = combo.lineEdit()
        if line_edit is not None:
            line_edit.setClearButtonEnabled(True)
            line_edit.setPlaceholderText("Choose or type a contract number")
        return combo

    def _configure_gs1_default_option_combos(self) -> None:
        self._gs1_default_option_combos = {
            "target_market": self.gs1_target_market_edit,
            "language": self.gs1_language_edit,
            "brand": self.gs1_brand_edit,
            "subbrand": self.gs1_subbrand_edit,
            "packaging_type": self.gs1_packaging_type_edit,
            "product_classification": self.gs1_product_classification_edit,
        }

    def _configure_gs1_contract_combo(self) -> None:
        entries = tuple(self._gs1_contract_entries or ())
        current_text = self.gs1_active_contract_edit.currentText().strip()
        self.gs1_active_contract_edit.blockSignals(True)
        self.gs1_active_contract_edit.clear()
        self.gs1_active_contract_edit.addItem("")
        for entry in entries:
            self.gs1_active_contract_edit.addItem(entry.contract_number)
            index = self.gs1_active_contract_edit.count() - 1
            details = " | ".join(
                part
                for part in (
                    entry.product,
                    f"Status: {entry.status}" if entry.status else "",
                    (
                        f"Range: {entry.start_number}-{entry.end_number}"
                        if entry.start_number and entry.end_number
                        else ""
                    ),
                )
                if part
            )
            if details:
                self.gs1_active_contract_edit.setItemData(index, details, Qt.ToolTipRole)
        if (
            current_text
            and self.gs1_active_contract_edit.findText(current_text, Qt.MatchFixedString) < 0
        ):
            self.gs1_active_contract_edit.addItem(current_text)
        self.gs1_active_contract_edit.setCurrentText(current_text)
        self.gs1_active_contract_edit.blockSignals(False)
        self._refresh_gs1_contract_status()

    def _refresh_gs1_contract_status(self) -> None:
        entries = tuple(self._gs1_contract_entries or ())
        if not entries:
            self.gs1_contracts_status_label.setText(
                "No GTIN contract list has been imported yet. Import the CSV export from your GS1 portal to populate contract choices."
            )
            return
        previews = []
        for entry in entries[:6]:
            parts = [entry.contract_number]
            if entry.product:
                parts.append(entry.product)
            if entry.status:
                parts.append(entry.status)
            previews.append(" - ".join(parts))
        suffix = "" if len(entries) <= 6 else f"\n…and {len(entries) - 6} more."
        self.gs1_contracts_status_label.setText(
            f"Loaded {len(entries)} GTIN contract(s) from:\n{self.gs1_contracts_csv_edit.text().strip() or '(path not saved)'}\n\n"
            + "\n".join(previews)
            + suffix
        )

    def _refresh_gs1_template_status(self) -> None:
        asset = self._gs1_template_asset
        pending_path = self._pending_gs1_template_path.strip()
        if pending_path:
            self.gs1_template_path_edit.setText(pending_path)
            self.gs1_template_store_btn.setText("Replace…")
            self.gs1_template_export_btn.setEnabled(bool(asset is not None))
            summary = self._gs1_template_profile_summary()
            if summary:
                self.gs1_template_status_label.setText(
                    "Selected replacement workbook. Save settings to store it using the chosen storage mode.\n\n"
                    + summary
                )
            else:
                self.gs1_template_status_label.setText(
                    "Selected replacement workbook. Save settings to store it using the chosen storage mode."
                )
            return

        if asset is None:
            self.gs1_template_path_edit.clear()
            self.gs1_template_store_btn.setText("Upload…")
            self.gs1_template_export_btn.setEnabled(False)
            self.gs1_template_storage_combo.setCurrentIndex(
                max(0, self.gs1_template_storage_combo.findData(STORAGE_MODE_DATABASE))
            )
            self.gs1_template_status_label.setText(
                "No official GS1 workbook is stored in this profile yet."
            )
            return

        self.gs1_template_path_edit.setText(asset.label)
        self.gs1_template_store_btn.setText("Replace…")
        self.gs1_template_export_btn.setEnabled(True)
        storage_index = self.gs1_template_storage_combo.findData(
            normalize_storage_mode(asset.storage_mode, default=STORAGE_MODE_DATABASE)
        )
        self.gs1_template_storage_combo.setCurrentIndex(max(0, storage_index))
        lines = []
        if asset.stored_in_database:
            lines.append("Workbook is stored inside the current profile database.")
        else:
            lines.append("Workbook is stored as a managed local file inside the app workspace.")
        if asset.filename:
            lines.append(f"Filename: {asset.filename}")
        if asset.size_bytes:
            lines.append(f"Size: {asset.size_bytes} bytes")
        if asset.updated_at:
            lines.append(f"Updated: {asset.updated_at}")
        summary = self._gs1_template_profile_summary()
        if summary:
            lines.append("")
            lines.append(summary)
        self.gs1_template_status_label.setText("\n".join(lines))

    def _gs1_template_profile_summary(self) -> str:
        profile = self._gs1_template_profile
        if profile is None:
            return ""
        available_sheets = list(profile.available_sheet_names)
        if len(available_sheets) == 1:
            return (
                f"Verified workbook sheet: {available_sheets[0]} "
                f"(header row {profile.header_row})"
            )
        if available_sheets:
            return (
                "Verified workbook sheets: "
                + ", ".join(available_sheets)
                + f"\nDefault matched sheet: {profile.sheet_name} (header row {profile.header_row})"
            )
        return ""

    @staticmethod
    def _set_combo_items(combo: QComboBox, values, *, preserve_text: str = "") -> None:
        clean_values: list[str] = []
        for value in values:
            text = str(value or "").strip()
            if text and text not in clean_values:
                clean_values.append(text)
        current_text = str(preserve_text or combo.currentText() or "").strip()
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("")
        combo.addItems(clean_values)
        if current_text and combo.findText(current_text, Qt.MatchFixedString) < 0:
            combo.addItem(current_text)
        combo.setCurrentText(current_text)
        completer = QCompleter(clean_values)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        combo.setCompleter(completer)
        combo.blockSignals(False)

    def _refresh_gs1_template_options(self, *, show_errors: bool) -> None:
        self._gs1_template_profile = None
        options_by_field: dict[str, tuple[str, ...]] = {}
        template_path = self._pending_gs1_template_path.strip()
        if self.gs1_integration_service is not None:
            try:
                if template_path:
                    self._gs1_template_profile = self.gs1_integration_service.load_template_profile(
                        template_path
                    )
                elif self._gs1_template_asset is not None:
                    self._gs1_template_profile = (
                        self.gs1_integration_service.load_template_profile()
                    )
                options_by_field = dict(self._gs1_template_profile.field_options)
            except Exception as exc:
                if show_errors:
                    QMessageBox.warning(self, "GS1 Workbook", str(exc))
        self._refresh_gs1_template_status()
        builtin_options = {
            "target_market": COMMON_MARKET_CHOICES,
            "language": COMMON_LANGUAGE_CHOICES,
            "packaging_type": COMMON_PACKAGING_CHOICES,
            "product_classification": COMMON_CLASSIFICATION_CHOICES,
        }
        for field_name, combo in self._gs1_default_option_combos.items():
            merged_values: list[str] = []
            if field_name == "target_market":
                for value in builtin_options.get(field_name, ()):
                    text = str(value or "").strip()
                    if text and text not in merged_values:
                        merged_values.append(text)
            for value in options_by_field.get(field_name, ()):
                text = str(value or "").strip()
                if text and text not in merged_values:
                    merged_values.append(text)
            if field_name != "target_market":
                for value in builtin_options.get(field_name, ()):
                    text = str(value or "").strip()
                    if text and text not in merged_values:
                        merged_values.append(text)
            self._set_combo_items(combo, merged_values, preserve_text=combo.currentText())

    def _browse_gs1_template(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose Official GS1 Workbook",
            self._pending_gs1_template_path
            or self.gs1_template_path_edit.text().strip()
            or str(Path.home()),
            "Excel Workbook (*.xlsx *.xlsm *.xltx *.xltm)",
        )
        if path:
            if self.gs1_integration_service is not None:
                try:
                    self.gs1_integration_service.load_template_profile(path)
                except Exception as exc:
                    QMessageBox.warning(self, "GS1 Workbook", str(exc))
                    return
            self._pending_gs1_template_path = str(path)
            self._refresh_gs1_template_options(show_errors=False)

    def _export_gs1_template(self):
        if self.gs1_integration_service is None:
            return
        asset = self._gs1_template_asset
        if asset is None:
            QMessageBox.information(
                self,
                "GS1 Workbook",
                "No GS1 workbook is stored in this profile yet.",
            )
            return
        suggested_path = str(Path.home() / (asset.filename or "gs1-template.xlsx"))
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Stored GS1 Workbook",
            suggested_path,
            "Excel Workbook (*.xlsx *.xlsm *.xltx *.xltm)",
        )
        if not path:
            return
        destination = Path(path)
        if not destination.suffix:
            destination = destination.with_suffix(asset.suffix)
        if destination.exists():
            overwrite = QMessageBox.question(
                self,
                "Overwrite File?",
                f"The file already exists:\n{destination}\n\nOverwrite it?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if overwrite != QMessageBox.Yes:
                return
        try:
            saved_path = self.gs1_integration_service.export_template_workbook(destination)
        except Exception as exc:
            QMessageBox.warning(self, "GS1 Workbook", str(exc))
            return
        QMessageBox.information(
            self,
            "GS1 Workbook",
            f"Saved the stored GS1 workbook to:\n{saved_path}",
        )

    def _browse_gs1_contracts_csv(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import GS1 Contracts CSV",
            self.gs1_contracts_csv_edit.text().strip() or "",
            "CSV File (*.csv)",
        )
        if path:
            self._import_gs1_contracts_csv(path, show_errors=True)

    def _export_gs1_contracts_csv(self):
        if self.gs1_integration_service is None:
            return
        suggested_filename = (
            self._pending_gs1_contracts_csv_filename
            or Path(self.gs1_contracts_csv_edit.text().strip() or "").name
            or self.gs1_integration_service.settings_service.load_stored_contracts_filename()
            or "gs1-contracts.csv"
        )
        suggested_path = str(Path.home() / suggested_filename)
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Stored GS1 Contracts CSV",
            suggested_path,
            "CSV File (*.csv)",
        )
        if not path:
            return
        destination = Path(path)
        if destination.suffix.lower() != ".csv":
            destination = destination.with_suffix(".csv")
        if destination.exists():
            overwrite = QMessageBox.question(
                self,
                "Overwrite File?",
                f"The file already exists:\n{destination}\n\nOverwrite it?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if overwrite != QMessageBox.Yes:
                return
        try:
            saved_path = self.gs1_integration_service.export_contracts_csv(
                destination,
                contracts=tuple(self._gs1_contract_entries),
                source_path=self.gs1_contracts_csv_edit.text().strip(),
                source_bytes=self._pending_gs1_contracts_csv_bytes,
            )
        except Exception as exc:
            QMessageBox.warning(self, "GS1 Contracts", str(exc))
            return
        QMessageBox.information(
            self,
            "GS1 Contracts",
            f"Saved the GTIN contracts CSV to:\n{saved_path}",
        )

    def _reload_gs1_contracts_csv(self):
        path = self.gs1_contracts_csv_edit.text().strip()
        if not path:
            QMessageBox.information(self, "GS1 Contracts", "Choose a GS1 contracts CSV first.")
            return
        self._import_gs1_contracts_csv(path, show_errors=True)

    def _import_gs1_contracts_csv(self, path: str, *, show_errors: bool) -> bool:
        if self.gs1_integration_service is None:
            return False
        try:
            entries = self.gs1_integration_service.contract_import_service.load_contracts(path)
        except GS1ContractImportError as exc:
            if show_errors:
                QMessageBox.warning(self, "GS1 Contracts", str(exc))
            return False
        self._gs1_contract_entries = tuple(entries)
        self._gs1_contracts_csv_path = str(path)
        self.gs1_contracts_csv_edit.setText(str(path))
        try:
            self._pending_gs1_contracts_csv_bytes = Path(path).read_bytes()
        except OSError:
            self._pending_gs1_contracts_csv_bytes = None
        self._pending_gs1_contracts_csv_filename = Path(path).name
        current_contract = self.gs1_active_contract_edit.currentText().strip()
        if not current_contract:
            active_entry = next(
                (entry for entry in self._gs1_contract_entries if entry.is_active), None
            )
            if active_entry is not None:
                self.gs1_active_contract_edit.setCurrentText(active_entry.contract_number)
        self._configure_gs1_contract_combo()
        return True

    def _clear_gs1_contracts(self):
        self._gs1_contract_entries = ()
        self._gs1_contracts_csv_path = ""
        self._pending_gs1_contracts_csv_bytes = None
        self._pending_gs1_contracts_csv_filename = ""
        self.gs1_contracts_csv_edit.clear()
        self.gs1_active_contract_edit.setCurrentText("")
        self._configure_gs1_contract_combo()

__all__ = ["ApplicationSettingsGs1Mixin"]

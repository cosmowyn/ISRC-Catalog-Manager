from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox

from isrc_manager import application_settings_gs1 as gs1_module
from isrc_manager.application_settings_gs1 import ApplicationSettingsGs1Mixin
from isrc_manager.file_storage import STORAGE_MODE_DATABASE, STORAGE_MODE_MANAGED_FILE
from isrc_manager.services import GS1ContractEntry, GS1ContractImportError, GS1TemplateAsset
from tests.qt_test_helpers import require_qapplication


class _TextWidget:
    def __init__(self, text: str = ""):
        self._text = text

    def setText(self, text: str) -> None:
        self._text = str(text)

    def text(self) -> str:
        return self._text

    def clear(self) -> None:
        self._text = ""


class _ButtonWidget:
    def __init__(self):
        self._text = ""
        self._enabled = True

    def setText(self, text: str) -> None:
        self._text = str(text)

    def text(self) -> str:
        return self._text

    def setEnabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)

    def isEnabled(self) -> bool:
        return self._enabled


class _Gs1Harness(ApplicationSettingsGs1Mixin):
    pass


def _editable_combo(text: str = "") -> QComboBox:
    combo = QComboBox()
    combo.setEditable(True)
    combo.setCurrentText(text)
    return combo


def _make_harness() -> _Gs1Harness:
    require_qapplication()
    harness = _Gs1Harness()
    harness._gs1_template_profile = None
    harness._gs1_template_asset = None
    harness._pending_gs1_template_path = ""
    harness._gs1_contract_entries = ()
    harness._gs1_contracts_csv_path = ""
    harness._pending_gs1_contracts_csv_bytes = None
    harness._pending_gs1_contracts_csv_filename = ""
    harness.gs1_integration_service = None

    harness.gs1_template_path_edit = _TextWidget()
    harness.gs1_template_store_btn = _ButtonWidget()
    harness.gs1_template_export_btn = _ButtonWidget()
    harness.gs1_template_status_label = _TextWidget()
    harness.gs1_template_storage_combo = QComboBox()
    harness.gs1_template_storage_combo.addItem("Database", STORAGE_MODE_DATABASE)
    harness.gs1_template_storage_combo.addItem("Managed file", STORAGE_MODE_MANAGED_FILE)

    harness.gs1_contracts_status_label = _TextWidget()
    harness.gs1_contracts_csv_edit = _TextWidget()
    harness.gs1_active_contract_edit = _editable_combo()

    harness.gs1_target_market_edit = _editable_combo()
    harness.gs1_language_edit = _editable_combo()
    harness.gs1_brand_edit = _editable_combo("Existing Brand")
    harness.gs1_subbrand_edit = _editable_combo()
    harness.gs1_packaging_type_edit = _editable_combo()
    harness.gs1_product_classification_edit = _editable_combo()
    harness._configure_gs1_default_option_combos()
    return harness


def _combo_texts(combo: QComboBox) -> list[str]:
    return [combo.itemText(index) for index in range(combo.count())]


def test_set_combo_items_deduplicates_values_and_preserves_custom_text():
    require_qapplication()
    combo = _editable_combo("Custom Brand")

    ApplicationSettingsGs1Mixin._set_combo_items(
        combo,
        [" Alpha ", "", "Beta", "Alpha", None],
    )

    assert _combo_texts(combo) == ["", "Alpha", "Beta", "Custom Brand"]
    assert combo.currentText() == "Custom Brand"
    assert combo.completer().caseSensitivity() == Qt.CaseInsensitive


def test_template_status_covers_pending_empty_and_stored_asset():
    harness = _make_harness()
    harness._gs1_template_profile = SimpleNamespace(
        available_sheet_names=["Input", "Instructions"],
        sheet_name="Input",
        header_row=3,
    )
    harness._gs1_template_asset = object()
    harness._pending_gs1_template_path = "/tmp/replacement.xlsx"

    harness._refresh_gs1_template_status()

    assert harness.gs1_template_path_edit.text() == "/tmp/replacement.xlsx"
    assert harness.gs1_template_store_btn.text() == "Replace…"
    assert harness.gs1_template_export_btn.isEnabled() is True
    assert "Selected replacement workbook" in harness.gs1_template_status_label.text()
    assert "Default matched sheet: Input" in harness.gs1_template_status_label.text()

    harness._pending_gs1_template_path = ""
    harness._gs1_template_asset = None
    harness._refresh_gs1_template_status()

    assert harness.gs1_template_path_edit.text() == ""
    assert harness.gs1_template_store_btn.text() == "Upload…"
    assert harness.gs1_template_export_btn.isEnabled() is False
    assert harness.gs1_template_storage_combo.currentData() == STORAGE_MODE_DATABASE
    assert "No official GS1 workbook" in harness.gs1_template_status_label.text()

    harness._gs1_template_profile = SimpleNamespace(
        available_sheet_names=["Metadata"],
        sheet_name="Metadata",
        header_row=5,
    )
    harness._gs1_template_asset = GS1TemplateAsset(
        filename="template.xlsx",
        managed_file_path="/workspace/template.xlsx",
        storage_mode=STORAGE_MODE_MANAGED_FILE,
        size_bytes=1234,
        updated_at="2026-05-25",
        stored_in_database=False,
    )
    harness._refresh_gs1_template_status()

    status = harness.gs1_template_status_label.text()
    assert harness.gs1_template_store_btn.text() == "Replace…"
    assert harness.gs1_template_export_btn.isEnabled() is True
    assert harness.gs1_template_storage_combo.currentData() == STORAGE_MODE_MANAGED_FILE
    assert "managed local file" in status
    assert "Filename: template.xlsx" in status
    assert "Size: 1234 bytes" in status
    assert "Verified workbook sheet: Metadata" in status


def test_refresh_template_options_merges_service_and_builtin_values(monkeypatch):
    harness = _make_harness()
    profile = SimpleNamespace(
        available_sheet_names=["Metadata"],
        sheet_name="Metadata",
        header_row=2,
        field_options={
            "brand": ("Moon Records", "Existing Brand"),
            "target_market": ("Atlantis",),
            "language": ("Klingon",),
        },
    )
    service = SimpleNamespace(load_template_profile=mock.Mock(return_value=profile))
    harness.gs1_integration_service = service
    harness._pending_gs1_template_path = "/tmp/template.xlsx"

    harness._refresh_gs1_template_options(show_errors=False)

    service.load_template_profile.assert_called_once_with("/tmp/template.xlsx")
    assert harness._gs1_template_profile is profile
    assert "Moon Records" in _combo_texts(harness.gs1_brand_edit)
    assert harness.gs1_brand_edit.currentText() == "Existing Brand"
    assert "Atlantis" in _combo_texts(harness.gs1_target_market_edit)
    assert "Klingon" in _combo_texts(harness.gs1_language_edit)

    warnings = []
    harness.gs1_integration_service = SimpleNamespace(
        load_template_profile=mock.Mock(side_effect=RuntimeError("bad workbook"))
    )
    monkeypatch.setattr(
        gs1_module.QMessageBox,
        "warning",
        lambda *args: warnings.append(args),
    )

    harness._refresh_gs1_template_options(show_errors=True)

    assert warnings
    assert "bad workbook" in str(warnings[0])


def test_import_gs1_contracts_csv_loads_entries_and_clear_resets_state(tmp_path):
    harness = _make_harness()
    csv_path = tmp_path / "contracts.csv"
    csv_path.write_text("contract_number,status\n1001,Inactive\n1002,Active\n", encoding="utf-8")
    entries = (
        GS1ContractEntry(contract_number="1001", product="Small Pack", status="Inactive"),
        GS1ContractEntry(
            contract_number="1002",
            product="Large Pack",
            start_number="8721000000000",
            end_number="8721000000999",
            status="Active",
        ),
    )
    harness.gs1_integration_service = SimpleNamespace(
        contract_import_service=SimpleNamespace(load_contracts=mock.Mock(return_value=entries))
    )

    assert harness._import_gs1_contracts_csv(str(csv_path), show_errors=True) is True

    assert harness._gs1_contract_entries == entries
    assert harness._gs1_contracts_csv_path == str(csv_path)
    assert harness._pending_gs1_contracts_csv_bytes == csv_path.read_bytes()
    assert harness._pending_gs1_contracts_csv_filename == "contracts.csv"
    assert harness.gs1_contracts_csv_edit.text() == str(csv_path)
    assert harness.gs1_active_contract_edit.currentText() == "1002"
    assert harness.gs1_active_contract_edit.itemData(2, Qt.ToolTipRole)
    assert "Loaded 2 GTIN contract(s)" in harness.gs1_contracts_status_label.text()

    harness._clear_gs1_contracts()

    assert harness._gs1_contract_entries == ()
    assert harness._gs1_contracts_csv_path == ""
    assert harness._pending_gs1_contracts_csv_bytes is None
    assert harness._pending_gs1_contracts_csv_filename == ""
    assert harness.gs1_contracts_csv_edit.text() == ""
    assert harness.gs1_active_contract_edit.currentText() == ""


def test_import_gs1_contracts_csv_handles_missing_service_and_import_errors(monkeypatch):
    harness = _make_harness()

    assert harness._import_gs1_contracts_csv("/missing.csv", show_errors=True) is False

    warnings = []
    harness.gs1_integration_service = SimpleNamespace(
        contract_import_service=SimpleNamespace(
            load_contracts=mock.Mock(side_effect=GS1ContractImportError("no header"))
        )
    )
    monkeypatch.setattr(
        gs1_module.QMessageBox,
        "warning",
        lambda *args: warnings.append(args),
    )

    assert harness._import_gs1_contracts_csv("/bad.csv", show_errors=True) is False
    assert warnings
    assert "no header" in str(warnings[0])


def test_export_template_and_contract_csv_apply_suffixes_and_report_success(monkeypatch, tmp_path):
    harness = _make_harness()
    template_target = tmp_path / "template-copy"
    contracts_target = tmp_path / "contracts-copy"
    information_messages = []

    service = mock.Mock()
    service.export_template_workbook.return_value = template_target.with_suffix(".xlsx")
    service.export_contracts_csv.return_value = contracts_target.with_suffix(".csv")
    service.settings_service.load_stored_contracts_filename.return_value = "stored-contracts.csv"
    harness.gs1_integration_service = service
    harness._gs1_template_asset = GS1TemplateAsset(filename="template.xlsx")
    harness._gs1_contract_entries = (
        GS1ContractEntry(contract_number="1002", product="Large Pack", status="Active"),
    )
    harness.gs1_contracts_csv_edit.setText("/imports/contracts.csv")
    harness._pending_gs1_contracts_csv_bytes = b"contract_number\n1002\n"

    save_paths = iter(
        [
            (str(template_target), ""),
            (str(contracts_target), ""),
        ]
    )
    monkeypatch.setattr(
        gs1_module.QFileDialog,
        "getSaveFileName",
        lambda *args: next(save_paths),
    )
    monkeypatch.setattr(
        gs1_module.QMessageBox,
        "information",
        lambda *args: information_messages.append(args),
    )

    harness._export_gs1_template()
    harness._export_gs1_contracts_csv()

    service.export_template_workbook.assert_called_once_with(template_target.with_suffix(".xlsx"))
    service.export_contracts_csv.assert_called_once_with(
        contracts_target.with_suffix(".csv"),
        contracts=harness._gs1_contract_entries,
        source_path="/imports/contracts.csv",
        source_bytes=b"contract_number\n1002\n",
    )
    assert len(information_messages) == 2

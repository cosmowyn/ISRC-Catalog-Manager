from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QMessageBox

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


def test_create_gs1_combos_tolerate_missing_line_edit(monkeypatch):
    class _NoLineEditCombo:
        def __init__(self, parent):
            self.parent = parent
            self.current_text = ""
            self.editable = False
            self.insert_policy = None
            self.minimum_width = 0
            self.maximum_width = 0

        def setEditable(self, editable):
            self.editable = bool(editable)

        def setInsertPolicy(self, policy):
            self.insert_policy = policy

        def setMinimumWidth(self, width):
            self.minimum_width = width

        def setMaximumWidth(self, width):
            self.maximum_width = width

        def setCurrentText(self, text):
            self.current_text = str(text)

        def lineEdit(self):
            return None

    monkeypatch.setattr(gs1_module, "FocusWheelComboBox", _NoLineEditCombo)
    harness = _Gs1Harness()

    default_combo = harness._create_gs1_default_combo(
        initial_text="  Existing Market  ",
        placeholder="Target market",
    )
    contract_combo = harness._create_gs1_contract_combo(initial_text="  1002  ")

    assert default_combo.parent is harness
    assert default_combo.editable is True
    assert default_combo.insert_policy == QComboBox.NoInsert
    assert default_combo.minimum_width == 320
    assert default_combo.maximum_width == 520
    assert default_combo.current_text == "Existing Market"
    assert contract_combo.current_text == "1002"


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


def test_contract_combo_preserves_custom_text_and_summarizes_sparse_overflow_entries():
    harness = _make_harness()
    harness.gs1_active_contract_edit.setCurrentText("manual-contract")
    harness._gs1_contract_entries = (
        GS1ContractEntry(contract_number="1000"),
        GS1ContractEntry(contract_number="1001", product="Starter Pack"),
        GS1ContractEntry(contract_number="1002", status="Active"),
        GS1ContractEntry(contract_number="1003", product="Archive", status="Inactive"),
        GS1ContractEntry(contract_number="1004"),
        GS1ContractEntry(contract_number="1005"),
        GS1ContractEntry(contract_number="1006"),
    )

    harness._configure_gs1_contract_combo()

    assert "manual-contract" in _combo_texts(harness.gs1_active_contract_edit)
    assert harness.gs1_active_contract_edit.currentText() == "manual-contract"
    status = harness.gs1_contracts_status_label.text()
    assert "Loaded 7 GTIN contract(s)" in status
    assert "(path not saved)" in status
    assert "1000" in status
    assert "1001 - Starter Pack" in status
    assert "1002 - Active" in status
    assert "and 1 more" in status


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


def test_template_status_reports_database_asset_without_optional_metadata():
    harness = _make_harness()
    harness._gs1_template_profile = SimpleNamespace(
        available_sheet_names=(),
        sheet_name="",
        header_row=1,
    )
    harness._gs1_template_asset = GS1TemplateAsset(
        storage_mode=STORAGE_MODE_DATABASE,
        stored_in_database=True,
    )

    assert harness._gs1_template_profile_summary() == ""

    harness._refresh_gs1_template_status()

    status = harness.gs1_template_status_label.text()
    assert harness.gs1_template_path_edit.text() == "Official GS1 workbook"
    assert harness.gs1_template_export_btn.isEnabled() is True
    assert "inside the current profile database" in status
    assert "Filename:" not in status
    assert "Size:" not in status
    assert "Updated:" not in status
    assert "Verified workbook" not in status


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


def test_refresh_template_options_loads_stored_asset_and_keeps_builtins_after_template_options():
    harness = _make_harness()
    profile = SimpleNamespace(
        available_sheet_names=["Metadata"],
        sheet_name="Metadata",
        header_row=4,
        field_options={
            "target_market": ("Worldwide", "Mars"),
            "language": ("Klingon", "English"),
            "brand": ("Existing Brand", "Lunar Works"),
            "packaging_type": ("Download", "Cassette"),
            "product_classification": ("Music", "Archive"),
        },
    )
    service = SimpleNamespace(load_template_profile=mock.Mock(return_value=profile))
    harness.gs1_integration_service = service
    harness._gs1_template_asset = GS1TemplateAsset(filename="stored-template.xlsx")

    harness._refresh_gs1_template_options(show_errors=False)

    service.load_template_profile.assert_called_once_with()
    assert harness._gs1_template_profile is profile
    target_values = _combo_texts(harness.gs1_target_market_edit)
    assert target_values.index("Worldwide") < target_values.index("Mars")
    language_values = _combo_texts(harness.gs1_language_edit)
    assert language_values.index("Klingon") < language_values.index("Dutch")
    assert "Lunar Works" in _combo_texts(harness.gs1_brand_edit)
    assert "Cassette" in _combo_texts(harness.gs1_packaging_type_edit)
    assert "Archive" in _combo_texts(harness.gs1_product_classification_edit)


def test_browse_gs1_template_handles_cancel_validation_failure_and_pending_selection(
    monkeypatch, tmp_path
):
    harness = _make_harness()
    refresh = mock.Mock()
    harness._refresh_gs1_template_options = refresh
    warnings = []
    monkeypatch.setattr(
        gs1_module.QMessageBox,
        "warning",
        lambda *args: warnings.append(args),
    )

    selections = iter(
        [
            ("", ""),
            (str(tmp_path / "bad-template.xlsx"), ""),
            (str(tmp_path / "accepted-template.xlsx"), ""),
        ]
    )
    monkeypatch.setattr(
        gs1_module.QFileDialog,
        "getOpenFileName",
        lambda *args: next(selections),
    )
    harness.gs1_integration_service = SimpleNamespace(
        load_template_profile=mock.Mock(side_effect=RuntimeError("not a GS1 workbook"))
    )

    harness._browse_gs1_template()
    assert refresh.call_count == 0
    assert harness._pending_gs1_template_path == ""

    harness._browse_gs1_template()
    assert warnings
    assert "not a GS1 workbook" in str(warnings[0])
    assert refresh.call_count == 0
    assert harness._pending_gs1_template_path == ""

    harness.gs1_integration_service = None
    harness._browse_gs1_template()
    assert harness._pending_gs1_template_path == str(tmp_path / "accepted-template.xlsx")
    refresh.assert_called_once_with(show_errors=False)


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

    warnings.clear()
    assert harness._import_gs1_contracts_csv("/bad.csv", show_errors=False) is False
    assert warnings == []


def test_import_gs1_contracts_csv_handles_unreadable_source_and_autoselect_edges():
    harness = _make_harness()
    entries = (GS1ContractEntry(contract_number="1001", status="Inactive"),)
    contract_service = SimpleNamespace(load_contracts=mock.Mock(return_value=entries))
    harness.gs1_integration_service = SimpleNamespace(contract_import_service=contract_service)
    harness.gs1_active_contract_edit.setCurrentText("manual-contract")

    assert harness._import_gs1_contracts_csv("/missing/contracts.csv", show_errors=True) is True

    assert harness._pending_gs1_contracts_csv_bytes is None
    assert harness._pending_gs1_contracts_csv_filename == "contracts.csv"
    assert harness.gs1_active_contract_edit.currentText() == "manual-contract"

    harness.gs1_active_contract_edit.setCurrentText("")
    contract_service.load_contracts.return_value = entries

    assert harness._import_gs1_contracts_csv("/missing/other.csv", show_errors=True) is True
    assert harness.gs1_active_contract_edit.currentText() == ""


def test_browse_reload_and_export_gs1_contracts_csv_guardrails(monkeypatch, tmp_path):
    harness = _make_harness()
    information_messages = []
    warnings = []
    imports = []
    monkeypatch.setattr(
        gs1_module.QMessageBox,
        "information",
        lambda *args: information_messages.append(args),
    )
    monkeypatch.setattr(
        gs1_module.QMessageBox,
        "warning",
        lambda *args: warnings.append(args),
    )

    browse_paths = iter([("", ""), (str(tmp_path / "contracts.csv"), "")])
    monkeypatch.setattr(
        gs1_module.QFileDialog,
        "getOpenFileName",
        lambda *args: next(browse_paths),
    )
    harness._import_gs1_contracts_csv = lambda path, *, show_errors: imports.append(
        (path, show_errors)
    )

    harness._browse_gs1_contracts_csv()
    assert imports == []

    harness._browse_gs1_contracts_csv()
    assert imports == [(str(tmp_path / "contracts.csv"), True)]

    harness.gs1_contracts_csv_edit.setText("")
    harness._reload_gs1_contracts_csv()
    assert "Choose a GS1 contracts CSV first." in str(information_messages[-1])

    harness.gs1_contracts_csv_edit.setText(str(tmp_path / "contracts.csv"))
    harness._reload_gs1_contracts_csv()
    assert imports[-1] == (str(tmp_path / "contracts.csv"), True)

    harness.gs1_integration_service = None
    harness._export_gs1_contracts_csv()

    existing = tmp_path / "existing.csv"
    existing.write_text("contract_number\n1001\n", encoding="utf-8")
    export_target = tmp_path / "export.csv"
    service = mock.Mock()
    service.settings_service.load_stored_contracts_filename.return_value = "stored.csv"
    service.export_contracts_csv.side_effect = RuntimeError("cannot write contracts")
    harness.gs1_integration_service = service
    harness.gs1_contracts_csv_edit.setText("")
    save_paths = iter([("", ""), (str(existing), ""), (str(export_target), "")])
    monkeypatch.setattr(
        gs1_module.QFileDialog,
        "getSaveFileName",
        lambda *args: next(save_paths),
    )
    monkeypatch.setattr(gs1_module.QMessageBox, "question", lambda *args: QMessageBox.No)

    harness._export_gs1_contracts_csv()
    service.settings_service.load_stored_contracts_filename.assert_called_once_with()
    service.export_contracts_csv.assert_not_called()

    harness._export_gs1_contracts_csv()
    service.export_contracts_csv.assert_not_called()

    harness._export_gs1_contracts_csv()
    service.export_contracts_csv.assert_called_once_with(
        export_target,
        contracts=(),
        source_path="",
        source_bytes=None,
    )
    assert warnings
    assert "cannot write contracts" in str(warnings[-1])


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


def test_export_gs1_template_guardrails(monkeypatch, tmp_path):
    harness = _make_harness()
    information_messages = []
    warnings = []
    monkeypatch.setattr(
        gs1_module.QMessageBox,
        "information",
        lambda *args: information_messages.append(args),
    )
    monkeypatch.setattr(
        gs1_module.QMessageBox,
        "warning",
        lambda *args: warnings.append(args),
    )

    harness._export_gs1_template()

    service = mock.Mock()
    harness.gs1_integration_service = service
    harness._export_gs1_template()
    assert "No GS1 workbook is stored" in str(information_messages[-1])
    service.export_template_workbook.assert_not_called()

    harness._gs1_template_asset = GS1TemplateAsset(filename="template.xlsx")
    existing = tmp_path / "existing.xlsx"
    existing.write_text("old workbook", encoding="utf-8")
    failed_export = tmp_path / "failed.xlsx"
    save_paths = iter([("", ""), (str(existing), ""), (str(failed_export), "")])
    monkeypatch.setattr(
        gs1_module.QFileDialog,
        "getSaveFileName",
        lambda *args: next(save_paths),
    )
    monkeypatch.setattr(gs1_module.QMessageBox, "question", lambda *args: QMessageBox.No)
    service.export_template_workbook.side_effect = RuntimeError("cannot write workbook")

    harness._export_gs1_template()
    service.export_template_workbook.assert_not_called()

    harness._export_gs1_template()
    service.export_template_workbook.assert_not_called()

    harness._export_gs1_template()
    service.export_template_workbook.assert_called_once_with(failed_export)
    assert warnings
    assert "cannot write workbook" in str(warnings[-1])

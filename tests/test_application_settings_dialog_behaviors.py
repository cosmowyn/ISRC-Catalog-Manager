from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
        QGridLayout,
        QLabel,
        QLineEdit,
        QMessageBox,
        QTableWidget,
        QWidget,
    )
except ImportError as exc:  # pragma: no cover - environment-specific fallback
    QApplication = None
    QCheckBox = None
    QComboBox = None
    QGridLayout = None
    QLabel = None
    QLineEdit = None
    QMessageBox = None
    QTableWidget = None
    QWidget = None
    Qt = None
    QT_IMPORT_ERROR = exc
else:
    QT_IMPORT_ERROR = None

from isrc_manager import application_settings_theme as theme_module
from isrc_manager.application_settings_dialog import ApplicationSettingsDialog
from isrc_manager.application_settings_theme import ApplicationSettingsThemeMixin
from isrc_manager.constants import (
    DEFAULT_HISTORY_RETENTION_MODE,
    HISTORY_RETENTION_MODE_BALANCED,
    HISTORY_RETENTION_MODE_CUSTOM,
    MIN_HISTORY_STORAGE_BUDGET_MB,
)
from isrc_manager.qss_reference import QssReferenceEntry
from isrc_manager.services.settings_reads import OwnerPartySettings


def _dialog() -> ApplicationSettingsDialog:
    return ApplicationSettingsDialog.__new__(ApplicationSettingsDialog)


def _ensure_qapp() -> QApplication:
    if QApplication is None:
        pytest.skip(f"PySide6 QtWidgets unavailable: {QT_IMPORT_ERROR}")
    return QApplication.instance() or QApplication([])


class _FakeButton:
    def __init__(self):
        self.enabled = False
        self.tooltip = ""

    def setEnabled(self, value):
        self.enabled = bool(value)

    def setToolTip(self, value):
        self.tooltip = str(value)


class _FakeCheck:
    def __init__(self, checked=False):
        self.checked = bool(checked)

    def isChecked(self):
        return self.checked

    def setChecked(self, value):
        self.checked = bool(value)


class _FakeFontCombo:
    def __init__(self, family="Inter"):
        self.family = family

    def currentFont(self):
        return SimpleNamespace(family=lambda: self.family)

    def setCurrentFont(self, font):
        self.family = font.family() if hasattr(font, "family") else str(font)


class _FakePlainTextEdit:
    def __init__(self, text=""):
        self.text = text
        self.focused = False
        self.templates: list[QssReferenceEntry] = []
        self.reference_entries: list[QssReferenceEntry] = []

    def toPlainText(self):
        return self.text

    def setPlainText(self, text):
        self.text = str(text)

    def textCursor(self):
        edit = self

        class Cursor:
            def insertText(self, text):
                edit.text += str(text)

        return Cursor()

    def setTextCursor(self, _cursor):
        return None

    def setFocus(self):
        self.focused = True

    def insert_template_for_reference_entry(self, entry):
        self.templates.append(entry)

    def set_reference_entries(self, entries):
        self.reference_entries = list(entries)


class _FakeLineEdit:
    def __init__(self, text=""):
        self._text = str(text)

    def text(self):
        return self._text

    def setText(self, text):
        self._text = str(text)


class _FakeSpin:
    def __init__(self, value=0, minimum=0, maximum=999):
        self._value = int(value)
        self._minimum = int(minimum)
        self._maximum = int(maximum)

    def value(self):
        return self._value

    def setValue(self, value):
        self._value = int(value)

    def minimum(self):
        return self._minimum

    def maximum(self):
        return self._maximum


class _FakeThemeHarness(ApplicationSettingsThemeMixin):
    CUSTOM_THEME_LABEL = "Custom Theme"

    def __init__(self):
        self._theme_settings = {"window_bg": "#101010", "font_size": 13}
        self._stored_themes = {
            "Starter": {"window_bg": "#202020", "selected_name": ""},
            "User Theme": {"window_bg": "#303030", "selected_name": ""},
        }
        self._bundled_theme_order = ["Starter", "Missing"]
        self._bundled_theme_names = {"Starter"}
        self._bundled_theme_descriptions = {"Starter": "bundled"}
        self._theme_color_edits = {"window_bg": _FakeLineEdit("#111111")}
        self._theme_color_swatches = {"window_bg": QLabel()}
        self._theme_metric_spins = {"font_size": _FakeSpin(13, 8, 36)}
        self._blob_icon_settings = {"audio": {"mode": "emoji", "emoji": "A"}}
        self._blob_icon_editors = {
            "audio": SimpleNamespace(current_spec=lambda: {"mode": "emoji", "emoji": "B"})
        }
        self._blob_icon_original_values = {"audio": {"mode": "emoji", "emoji": "C"}}
        self._blob_icon_preview_labels = {"audio": QLabel()}
        self._theme_change_tracking_enabled = True
        self._theme_last_valid_custom_qss_preview = ""
        self.theme_font_family_combo = _FakeFontCombo()
        self.theme_auto_contrast_check = _FakeCheck(True)
        self.theme_custom_qss_edit = _FakePlainTextEdit("QWidget { color: #fff; }")
        self.theme_preset_combo = QComboBox()
        self.theme_load_button = _FakeButton()
        self.theme_delete_button = _FakeButton()
        self.theme_preview_status_label = QLabel()
        self.theme_custom_qss_status_label = QLabel()
        self.theme_qss_tabs = QComboBox()
        self.qss_reference_filter_edit = _FakeLineEdit()
        self.qss_reference_table = QTableWidget(0, 3)
        self.qss_reference_status_label = QLabel()
        self.qss_reference_copy_button = _FakeButton()
        self.qss_reference_insert_button = _FakeButton()
        self.qss_reference_insert_template_button = _FakeButton()
        self._qss_reference_entries: list[QssReferenceEntry] = []
        self._qss_filtered_reference_entries: list[QssReferenceEntry] = []
        self.applied_theme_payloads: list[dict[str, object]] = []
        self.refreshed = 0
        self._refresh_theme_preset_combo()

    def _refresh_theme_previews(self):
        self.refreshed += 1

    def _apply_theme_values_to_fields(self, theme_values, *, selected_name=""):
        self.applied_theme_payloads.append(dict(theme_values))
        self._set_theme_preset_selection(selected_name)


def _party_record(**overrides):
    values = {
        "id": 7,
        "legal_name": None,
        "display_name": None,
        "artist_name": None,
        "company_name": None,
        "first_name": None,
        "middle_name": None,
        "last_name": None,
        "contact_person": None,
        "email": None,
        "alternative_email": None,
        "phone": None,
        "website": None,
        "street_name": None,
        "street_number": None,
        "address_line1": None,
        "address_line2": None,
        "city": None,
        "region": None,
        "postal_code": None,
        "country": None,
        "bank_account_number": None,
        "chamber_of_commerce_number": None,
        "tax_id": None,
        "vat_number": None,
        "pro_affiliation": None,
        "pro_number": None,
        "ipi_cae": None,
        "notes": None,
        "label": "Party Label",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_smart_history_budget_math_rounds_clamps_and_counts_expected_copies() -> None:
    assert ApplicationSettingsDialog._ceil_div(5, 2) == 3
    assert ApplicationSettingsDialog._ceil_div(-10, 0) == 0
    assert ApplicationSettingsDialog._smart_history_budget_copy_count(0) == 3
    assert ApplicationSettingsDialog._smart_history_budget_copy_count(4) == 6

    assert (
        ApplicationSettingsDialog._smart_history_budget_mb_from_profile_footprint(1, 1)
        == MIN_HISTORY_STORAGE_BUDGET_MB
    )
    assert (
        ApplicationSettingsDialog._smart_history_budget_mb_from_database_size(
            1024 * 1024 * 1024,
            2,
        )
        == 5120
    )
    assert (
        ApplicationSettingsDialog._history_retention_mode_description(
            HISTORY_RETENTION_MODE_BALANCED
        )
        != ""
    )
    assert ApplicationSettingsDialog._history_retention_mode_description("missing") == ""
    assert ApplicationSettingsDialog._history_retention_preset(HISTORY_RETENTION_MODE_CUSTOM) == {}


def test_profile_database_discovery_deduplicates_sources_and_sizes_sidecars(tmp_path: Path) -> None:
    current = tmp_path / "current.db"
    current.write_bytes(b"db")
    sibling = tmp_path / "sibling.db"
    sibling.write_bytes(b"other")
    database_dir = tmp_path / "profiles"
    database_dir.mkdir()
    directory_profile = database_dir / "directory.db"
    directory_profile.write_bytes(b"directory")

    class ProfileStore:
        def list_profiles(self):
            return [current, str(current), tmp_path / "missing.db"]

    owner = SimpleNamespace(profile_store=ProfileStore(), database_dir=database_dir)
    dialog = _dialog()
    dialog._current_profile_path = current
    discovered = dialog._discover_profile_database_paths(owner)
    assert discovered[0] == current
    assert current in discovered
    assert sibling in discovered
    assert directory_profile in discovered
    assert discovered.count(current) == 1

    bad_candidates = ApplicationSettingsDialog._deduplicate_profile_database_paths(
        [current, str(current), None]
    )
    assert bad_candidates == [current]

    for suffix, data in {
        ".wal": b"wal",
        "-shm": b"shm!",
        "-journal": b"journal",
    }.items():
        Path(str(current) + suffix).write_bytes(data)
    assert ApplicationSettingsDialog._profile_database_bundle_size_bytes(current) == (
        len(b"db") + len(b"wal") + len(b"shm!") + len(b"journal")
    )


def test_smart_history_budget_source_prefers_app_storage_then_current_then_collection(
    tmp_path: Path,
) -> None:
    current = tmp_path / "current.db"
    current.write_bytes(b"current")
    other = tmp_path / "other.db"
    other.write_bytes(b"other")

    class StorageService:
        def inspect(self, current_db_path):
            assert current_db_path == current
            return SimpleNamespace(summary=SimpleNamespace(total_app_bytes=1234))

    owner = SimpleNamespace(_application_storage_admin_service=lambda: StorageService())
    dialog = _dialog()
    dialog._current_profile_path = current
    dialog._smart_history_budget_owner = owner
    dialog._profile_database_paths = [current, other]
    dialog._smart_history_budget_source_cache = None
    assert dialog._smart_history_budget_source() == (
        1234,
        "application-wide tracked storage",
    )
    assert dialog._smart_history_budget_source() == (
        1234,
        "application-wide tracked storage",
    )

    failing_owner = SimpleNamespace(
        _application_storage_admin_service=lambda: (_ for _ in ()).throw(RuntimeError("no audit"))
    )
    dialog._smart_history_budget_source_cache = None
    dialog._smart_history_budget_owner = failing_owner
    assert dialog._smart_history_budget_source() == (
        current.stat().st_size,
        "current profile database files",
    )

    dialog._smart_history_budget_source_cache = None
    dialog._current_profile_path = None
    assert dialog._smart_history_budget_source() == (
        current.stat().st_size + other.stat().st_size,
        "profile database files",
    )


def test_party_resolution_creates_fetches_and_deduplicates_artist_names() -> None:
    dialog = _dialog()
    dialog._artist_party_primary_label = lambda record: record.label

    assert dialog._resolve_party_backed_artist_name("  ") == ("", None)
    dialog.party_service = None
    assert dialog._resolve_party_backed_artist_name("  Raw Artist  ") == ("Raw Artist", None)

    class PartyService:
        def __init__(self) -> None:
            self.ensured: list[str] = []

        def find_artist_party_id_by_name(self, name, *, cursor=None):
            if name.casefold() == "known":
                return 21
            return None

        def ensure_artist_party_by_name(self, name, *, cursor=None):
            self.ensured.append(name)
            return 22

        def fetch_party(self, party_id: int):
            if party_id == 99:
                return None
            return _party_record(id=party_id, label=f"Party {party_id}")

    service = PartyService()
    dialog.party_service = service
    assert dialog._resolve_party_backed_artist_name("Known") == ("Party 21", 21)
    assert dialog._resolve_party_backed_artist_name("New Artist") == ("Party 22", 22)
    assert service.ensured == ["New Artist"]
    assert dialog._resolve_party_backed_artist_name("Missing", selected_party_id=99) == (
        "Missing",
        99,
    )
    assert dialog._resolve_party_backed_additional_artist_names(
        ["Known", "known", "", "New Artist"]
    ) == ["Party 21", "Party 22"]


def test_owner_party_payload_prefers_live_party_then_sanitized_snapshot() -> None:
    record = _party_record(
        id=12,
        legal_name="  Legal Co  ",
        display_name=" Display ",
        artist_name=" Artist ",
        company_name=" Company ",
        email=" owner@example.test ",
        vat_number=" VAT ",
    )
    payload = ApplicationSettingsDialog._owner_party_settings_from_record(record)
    assert payload.party_id == 12
    assert payload.legal_name == "Legal Co"
    assert payload.display_name == "Display"
    assert payload.artist_name == "Artist"
    assert payload.company_name == "Company"
    assert payload.email == "owner@example.test"
    assert payload.vat_number == "VAT"

    class PartyService:
        def fetch_party(self, party_id: int):
            if party_id == 12:
                return record
            return None

    dialog = _dialog()
    dialog.party_service = PartyService()
    dialog._owner_selected_party_id = None
    dialog._owner_party_settings = OwnerPartySettings()
    assert dialog._owner_party_settings_payload() == OwnerPartySettings()

    dialog._owner_selected_party_id = 12
    assert dialog._owner_party_settings_payload().legal_name == "Legal Co"

    dialog.party_service = None
    dialog._owner_selected_party_id = 15
    dialog._owner_party_settings = OwnerPartySettings(
        party_id=15,
        legal_name="  Legacy Legal  ",
        company_name="  Legacy Co  ",
        notes="  Keep this note  ",
    )
    legacy = dialog._owner_party_settings_payload()
    assert legacy.party_id == 15
    assert legacy.legal_name == "Legacy Legal"
    assert legacy.company_name == "Legacy Co"
    assert legacy.notes == "Keep this note"

    dialog._owner_selected_party_id = 99
    unresolved = dialog._owner_party_settings_payload()
    assert unresolved.party_id == 99
    assert unresolved.legal_name == ""


def test_work_payload_and_history_mode_detection_use_profile_and_presets() -> None:
    dialog = _dialog()
    dialog._current_profile_name = lambda: "Profile A"
    payload = dialog._work_payload_from_track_seed(
        track_title="  Song  ",
        iswc=" T123 ",
        registration_number=" REG ",
    )
    assert payload.title == "Song"
    assert payload.iswc == "T123"
    assert payload.registration_number == "REG"
    assert payload.profile_name == "Profile A"

    preset = ApplicationSettingsDialog._history_retention_preset(DEFAULT_HISTORY_RETENTION_MODE)
    dialog._history_retention_control_payload = lambda: dict(preset)
    assert (
        dialog._detect_history_retention_mode(preferred_mode=DEFAULT_HISTORY_RETENTION_MODE)
        == DEFAULT_HISTORY_RETENTION_MODE
    )
    dialog._history_retention_control_payload = lambda: {"unexpected": True}
    assert dialog._detect_history_retention_mode() == HISTORY_RETENTION_MODE_CUSTOM


class _ValidationDialog:
    def __init__(self, **overrides):
        values = {
            "isrc_prefix": "NLABC",
            "artist_code": "42",
            "gs1_template_import_path": "",
            "gs1_contracts_csv_path": "",
            "blob_icon_settings": {},
            "custom_qss": "",
        }
        values.update(overrides)
        self._values = values
        self.focused_fields: list[str] = []
        self.accepted = False
        self.gs1_integration_service = None
        self._gs1_contracts_csv_path = ""
        self._gs1_contract_entries = ()
        self._theme_color_edits = {}
        self._theme_tab_index = 3
        self.tabs = SimpleNamespace(
            indexes=[], setCurrentIndex=lambda index: self.tabs.indexes.append(index)
        )
        self.theme_qss_tabs = SimpleNamespace(
            indexes=[], setCurrentIndex=lambda index: self.theme_qss_tabs.indexes.append(index)
        )
        self.theme_custom_qss_edit = SimpleNamespace(focused=False)

    def values(self):
        return dict(self._values)

    def focus_field(self, name):
        self.focused_fields.append(name)

    def _import_gs1_contracts_csv(self, _path, *, show_errors):
        assert show_errors is True
        return False

    def _theme_qss_validation_issues(self, _qss):
        return []

    def accept(self):
        self.accepted = True


def test_settings_validation_rejects_invalid_registration_and_gs1_inputs(tmp_path: Path) -> None:
    cases = [
        (_ValidationDialog(isrc_prefix="bad"), "Invalid Prefix", "isrc_prefix"),
        (_ValidationDialog(artist_code="7"), "Invalid Artist Code", "artist_code"),
        (
            _ValidationDialog(gs1_contracts_csv_path=str(tmp_path / "contracts.xlsx")),
            "Invalid GS1 Contracts File",
            "gs1_contracts_csv_path",
        ),
        (
            _ValidationDialog(gs1_contracts_csv_path=str(tmp_path / "contracts.csv")),
            None,
            "gs1_contracts_csv_path",
        ),
    ]

    for fake_dialog, warning_title, focused_field in cases:
        with mock.patch(
            "isrc_manager.application_settings_dialog.QMessageBox.warning",
            return_value=None,
        ) as warning:
            ApplicationSettingsDialog._accept_if_valid(fake_dialog)
        assert not fake_dialog.accepted
        assert fake_dialog.focused_fields == [focused_field]
        if warning_title is not None:
            assert warning.call_args.args[1] == warning_title

    fake_dialog = _ValidationDialog(gs1_template_import_path=str(tmp_path / "template.xlsx"))
    fake_dialog.gs1_integration_service = SimpleNamespace(
        load_template_profile=mock.Mock(side_effect=ValueError("template parse failed"))
    )
    with mock.patch(
        "isrc_manager.application_settings_dialog.QMessageBox.warning",
        return_value=None,
    ) as warning:
        ApplicationSettingsDialog._accept_if_valid(fake_dialog)
    fake_dialog.gs1_integration_service.load_template_profile.assert_called_once()
    assert warning.call_args.args[1] == "GS1 Workbook"
    assert "template parse failed" in warning.call_args.args[2]
    assert fake_dialog.focused_fields == ["gs1_template_path"]


def test_settings_validation_rejects_blob_icon_theme_color_and_qss_errors() -> None:
    blob_cases = [
        (
            {"audio": {"mode": "emoji", "emoji": ""}},
            "Choose or type an emoji for the audio blob icon.",
        ),
        (
            {"image": {"mode": "image", "image_path": "", "image_png_base64": ""}},
            "Choose a custom image for the image blob icon.",
        ),
    ]
    for blob_icon_settings, expected_message in blob_cases:
        fake_dialog = _ValidationDialog(blob_icon_settings=blob_icon_settings)
        with (
            mock.patch(
                "isrc_manager.application_settings_dialog.normalize_blob_icon_settings",
                return_value=blob_icon_settings,
            ),
            mock.patch(
                "isrc_manager.application_settings_dialog.QMessageBox.warning",
                return_value=None,
            ) as warning,
        ):
            ApplicationSettingsDialog._accept_if_valid(fake_dialog)
        assert not fake_dialog.accepted
        assert fake_dialog.tabs.indexes == [3]
        assert expected_message in warning.call_args.args[2]

    edit = SimpleNamespace(
        text=lambda: "not-a-color",
        focused=False,
        selected=False,
        setFocus=lambda reason: setattr(edit, "focused", reason),
        selectAll=lambda: setattr(edit, "selected", True),
    )
    fake_dialog = _ValidationDialog()
    fake_dialog._theme_color_edits = {"accent_color": edit}
    with mock.patch(
        "isrc_manager.application_settings_dialog.QMessageBox.warning",
        return_value=None,
    ) as warning:
        ApplicationSettingsDialog._accept_if_valid(fake_dialog)
    assert not fake_dialog.accepted
    assert fake_dialog.tabs.indexes == [3]
    assert edit.focused == Qt.OtherFocusReason
    assert edit.selected is True
    assert warning.call_args.args[1] == "Invalid Theme Color"

    qss_edit = SimpleNamespace(
        focus_reason=None, setFocus=lambda reason: setattr(qss_edit, "focus_reason", reason)
    )
    fake_dialog = _ValidationDialog(custom_qss="QWidget { color: ; }")
    fake_dialog.theme_custom_qss_edit = qss_edit
    fake_dialog._theme_qss_validation_issues = lambda _qss: [
        SimpleNamespace(line=4, column=8, message="Expected color")
    ]
    with mock.patch(
        "isrc_manager.application_settings_dialog.QMessageBox.warning",
        return_value=None,
    ) as warning:
        ApplicationSettingsDialog._accept_if_valid(fake_dialog)
    assert not fake_dialog.accepted
    assert fake_dialog.tabs.indexes == [3]
    assert fake_dialog.theme_qss_tabs.indexes == [0]
    assert qss_edit.focus_reason == Qt.OtherFocusReason
    assert "Line 4, column 8: Expected color" in warning.call_args.args[2]

    valid_dialog = _ValidationDialog()
    ApplicationSettingsDialog._accept_if_valid(valid_dialog)
    assert valid_dialog.accepted is True


def test_unencrypted_profile_warning_suppression_requires_confirmation() -> None:
    _ensure_qapp()
    dialog = _dialog()
    dialog._suppress_unencrypted_profile_warning_notice_shown = False
    dialog.suppress_unencrypted_profile_warnings_check = QCheckBox()
    dialog.suppress_unencrypted_profile_warnings_check.setChecked(True)

    with mock.patch(
        "isrc_manager.application_settings_dialog.QMessageBox.warning",
        return_value=QMessageBox.Cancel,
    ):
        ApplicationSettingsDialog._confirm_unencrypted_profile_warning_suppression(dialog, True)

    assert dialog.suppress_unencrypted_profile_warnings_check.isChecked() is False

    dialog.suppress_unencrypted_profile_warnings_check.setChecked(True)
    with mock.patch(
        "isrc_manager.application_settings_dialog.QMessageBox.warning",
        return_value=QMessageBox.Ok,
    ):
        ApplicationSettingsDialog._confirm_unencrypted_profile_warning_suppression(dialog, True)

    assert dialog.suppress_unencrypted_profile_warnings_check.isChecked() is True
    assert dialog._suppress_unencrypted_profile_warning_notice_shown is True


def test_settings_focus_wrapping_rows_and_artist_party_combo_behaviour() -> None:
    _ensure_qapp()
    dialog = _dialog()
    dialog.tabs = SimpleNamespace(
        indexes=[], setCurrentIndex=lambda index: dialog.tabs.indexes.append(index)
    )
    line_edit = QLineEdit()
    combo = QComboBox()
    combo.setEditable(True)
    combo.addItem("Artist Label", 12)
    combo.setItemData(0, "Primary Artist", Qt.UserRole + 1)
    dialog._focus_map = {"line": (1, line_edit), "combo": (2, combo)}

    dialog.focus_field("missing")
    dialog.focus_field("line")
    dialog.focus_field("combo")

    assert dialog.tabs.indexes == [1, 2]
    assert line_edit.selectedText() == ""
    assert combo.lineEdit() is not None

    content = QWidget()
    scroll = ApplicationSettingsDialog._wrap_tab_page(content)
    assert content.property("role") == "workspaceCanvas"
    assert scroll.property("role") == "workspaceCanvas"

    grid_host = QWidget()
    grid = QGridLayout(grid_host)
    row_owner = QWidget()
    row_owner._make_label = lambda text: QLineEdit(text)
    row_owner._make_hint = lambda text: QLineEdit(text)
    ApplicationSettingsDialog._add_row(row_owner, grid, 0, "Label", QLineEdit(), "Hint")
    ApplicationSettingsDialog._add_row(row_owner, grid, 1, "Plain", QLineEdit())
    assert grid.itemAtPosition(0, 1) is not None
    assert grid.itemAtPosition(1, 1) is not None

    records = [
        _party_record(
            id=21,
            display_name="Display Artist",
            legal_name="Legal Artist",
            artist_aliases=("Alias One", ""),
            label="Primary Display",
        )
    ]

    class PartyService:
        def __init__(self, *, fail: bool = False):
            self.fail = fail

        def list_artist_parties(self):
            if self.fail:
                raise RuntimeError("party lookup failed")
            return records

    dialog.party_service = None
    assert dialog._artist_party_records() == []
    dialog.party_service = PartyService(fail=True)
    assert dialog._artist_party_records() == []

    dialog.party_service = PartyService()
    artist_combo = QComboBox()
    dialog._configure_artist_party_combo(
        artist_combo,
        allow_empty=True,
        selected_party_id=99,
        current_text="Missing Artist",
    )
    assert artist_combo.itemData(0) is None
    assert artist_combo.findData(21) >= 0
    assert artist_combo.findData(99) >= 0
    assert artist_combo.completer() is not None

    artist_combo.setCurrentIndex(artist_combo.findData(21))
    assert dialog._resolve_artist_party_choice(artist_combo) == ("Display Artist", 21)
    artist_combo.setCurrentIndex(-1)
    artist_combo.setEditText("Missing Artist")
    assert dialog._resolve_artist_party_choice(artist_combo) == ("Missing Artist", 99)
    artist_combo.setEditText("Fresh Typing")
    assert dialog._resolve_artist_party_choice(artist_combo) == ("Fresh Typing", None)
    artist_combo.setEditText("")
    assert dialog._resolve_artist_party_choice(artist_combo) == ("", None)

    dialog.artist_field = artist_combo
    dialog.additional_artist_field = object()
    dialog._refresh_add_track_artist_party_choices()


def test_theme_reference_filter_actions_and_payload_helpers() -> None:
    _ensure_qapp()
    harness = _FakeThemeHarness()
    harness._qss_reference_entries = [
        QssReferenceEntry("Widget", "QPushButton", "Button selector"),
        QssReferenceEntry("Panel", "#workspacePanel", "Workspace panel"),
    ]

    harness._apply_qss_reference_filter()
    assert harness.qss_reference_table.rowCount() == 2
    assert "2 selectors available" in harness.qss_reference_status_label.text()

    harness.qss_reference_filter_edit.setText("workspace")
    harness._apply_qss_reference_filter()
    assert harness.qss_reference_table.rowCount() == 1
    assert "Showing 1 of 2" in harness.qss_reference_status_label.text()

    harness.qss_reference_table.selectRow(0)
    assert harness._selected_qss_selector() == "#workspacePanel"
    harness._update_qss_reference_actions()
    assert harness.qss_reference_copy_button.enabled

    harness._insert_selected_qss_selector()
    assert "#workspacePanel" in harness.theme_custom_qss_edit.toPlainText()
    harness._insert_selected_qss_template()
    assert harness.theme_custom_qss_edit.templates == [harness._qss_filtered_reference_entries[0]]

    payload = harness._theme_value_payload()
    assert payload["font_family"] == "Inter"
    assert payload["window_bg"] == "#111111"
    assert payload["font_size"] == 13
    assert isinstance(harness._blob_icon_value_payload(), dict)


def test_theme_preset_save_delete_import_export_reset_and_swatches(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _ensure_qapp()
    harness = _FakeThemeHarness()
    messages: list[tuple[str, str]] = []

    class FakeMessageBox:
        Yes = 1
        No = 2
        answers = [No, Yes, Yes, Yes]

        @classmethod
        def warning(cls, _parent, title, message):
            messages.append((title, message))

        @classmethod
        def information(cls, _parent, title, message):
            messages.append((title, message))

        @classmethod
        def question(cls, *_args):
            return cls.answers.pop(0)

    class FakeFileDialog:
        open_paths: list[str] = []
        save_paths: list[str] = []

        @classmethod
        def getOpenFileName(cls, *_args):
            return (cls.open_paths.pop(0), "Theme JSON")

        @classmethod
        def getSaveFileName(cls, *_args):
            return (cls.save_paths.pop(0), "Theme JSON")

    choices = iter(
        [
            ("", True),
            ("Starter", True),
            ("User Theme", True),
            ("User Theme", True),
        ]
    )
    monkeypatch.setattr(theme_module, "QMessageBox", FakeMessageBox)
    monkeypatch.setattr(theme_module, "QFileDialog", FakeFileDialog)
    monkeypatch.setattr(
        theme_module,
        "_get_name_from_editable_choice_dialog",
        lambda *_args, **_kwargs: next(choices),
    )

    harness._save_current_theme_preset()
    assert messages[-1][0] == "Theme Name Required"

    harness._save_current_theme_preset()
    assert messages[-1][0] == "Starter Theme Protected"

    harness._save_current_theme_preset()
    assert harness._current_theme_preset_name() == ""

    harness._save_current_theme_preset()
    assert "User Theme" in harness._stored_themes
    assert harness._current_theme_preset_name() == "User Theme"

    harness._set_theme_preset_selection("User Theme")
    harness._delete_selected_theme_preset()
    assert "User Theme" not in harness._stored_themes
    assert harness._current_theme_preset_name() == ""

    missing_theme = tmp_path / "missing-theme.json"
    bad_theme = tmp_path / "bad-theme.json"
    bad_theme.write_text("[]", encoding="utf-8")
    imported_theme = tmp_path / "theme.json"
    imported_theme.write_text(
        '{"name": "Imported", "theme": {"window_bg": "#abcdef"}}',
        encoding="utf-8",
    )
    FakeFileDialog.open_paths = [str(missing_theme), str(bad_theme), str(imported_theme)]
    harness._import_theme_from_file()
    assert messages[-1][0] == "Import Theme"
    harness._import_theme_from_file()
    assert "valid theme payload" in messages[-1][1]
    harness._import_theme_from_file()
    assert harness.applied_theme_payloads[-1]["window_bg"] == "#abcdef"
    assert "Imported theme draft" in harness.theme_preview_status_label.text()

    export_path = tmp_path / "exported theme.json"
    FakeFileDialog.save_paths = [str(export_path)]
    harness._export_theme_to_file()
    exported = export_path.read_text(encoding="utf-8")
    assert '"schema": "isrc-manager-theme"' in exported
    assert messages[-1][0] == "Export Theme"

    harness._reset_theme_to_defaults()
    assert harness.applied_theme_payloads[-1]["selected_name"] == ""

    harness._theme_color_edits["window_bg"].setText("")
    harness._sync_color_swatch("window_bg")
    assert harness._theme_color_swatches["window_bg"].text() == "A"
    harness._theme_color_edits["window_bg"].setText("#000000")
    harness._sync_color_swatch("window_bg")
    assert harness._theme_color_swatches["window_bg"].toolTip() == "#000000"
    harness._theme_color_edits["window_bg"].setText("not-a-color")
    harness._sync_color_swatch("window_bg")
    assert harness._theme_color_swatches["window_bg"].text() == "!"


def test_theme_preview_status_and_live_preview_controls() -> None:
    _ensure_qapp()
    owner = SimpleNamespace(applied=[])
    owner._apply_theme = lambda payload: owner.applied.append(dict(payload))

    class PreviewHarness(_FakeThemeHarness):
        def parent(self):
            return owner

    harness = PreviewHarness()
    harness._theme_preview_roots = [QWidget()]

    class FakeTabs:
        def __init__(self, labels):
            self.labels = list(labels)
            self.index = 0

        def addItem(self, label):
            self.labels.append(label)

        def currentIndex(self):
            return self.index

        def setCurrentIndex(self, index):
            self.index = int(index)

        def tabText(self, index):
            return self.labels[int(index)]

    harness.theme_preview_tabs = FakeTabs(["Buttons"])
    harness.theme_builder_tabs = FakeTabs(["Typography"])
    harness._theme_builder_page_keys = ["typography", "blob_icons"]
    harness._theme_preview_tab_indices = {"typography": 0, "blob_icons": 0}
    harness.theme_live_preview_check = _FakeCheck(True)
    harness._theme_original_values = {"window_bg": "#010101"}
    harness._refresh_theme_previews = ApplicationSettingsThemeMixin._refresh_theme_previews.__get__(
        harness,
        PreviewHarness,
    )

    harness._refresh_theme_previews()
    assert owner.applied
    assert "Showing the buttons preview" in harness.theme_preview_status_label.text()

    harness.theme_live_preview_check.setChecked(False)
    harness._handle_theme_live_preview_toggled(False)
    assert owner.applied[-1] == {"window_bg": "#010101"}

    harness._theme_change_tracking_enabled = False
    harness._queue_theme_preview_update()

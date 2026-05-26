from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from isrc_manager.application_settings_dialog import ApplicationSettingsDialog
from isrc_manager.constants import (
    DEFAULT_HISTORY_RETENTION_MODE,
    HISTORY_RETENTION_MODE_BALANCED,
    HISTORY_RETENTION_MODE_CUSTOM,
    MIN_HISTORY_STORAGE_BUDGET_MB,
)
from isrc_manager.services.settings_reads import OwnerPartySettings


def _dialog() -> ApplicationSettingsDialog:
    return ApplicationSettingsDialog.__new__(ApplicationSettingsDialog)


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

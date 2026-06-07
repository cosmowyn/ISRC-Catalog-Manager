import sqlite3

from isrc_manager.code_registry.models import (
    BUILTIN_CATEGORY_CATALOG_NUMBER,
    BUILTIN_CATEGORY_REGISTRY_SHA256_KEY,
    CATALOG_MODE_EXTERNAL,
    CATALOG_MODE_INTERNAL,
    CLASSIFICATION_CANONICAL_CANDIDATE,
    CLASSIFICATION_EXTERNAL,
    CLASSIFICATION_INTERNAL,
    CLASSIFICATION_MISMATCH,
    CodeIdentifierClassification,
    CodeRegistryCategoryRecord,
    CodeRegistryEntryGenerationResult,
    CodeRegistryEntryRecord,
)
from isrc_manager.code_registry.widgets import CatalogIdentifierField
from tests.qt_test_helpers import require_qapplication


def _category(
    *,
    category_id: int = 1,
    system_key: str = BUILTIN_CATEGORY_CATALOG_NUMBER,
    display_name: str = "Catalog Number",
) -> CodeRegistryCategoryRecord:
    return CodeRegistryCategoryRecord(
        id=category_id,
        system_key=system_key,
        display_name=display_name,
        subject_kind="catalog",
        generation_strategy="sequential",
        prefix="CAT",
        normalized_prefix="cat",
        active_flag=True,
        sort_order=1,
        is_system=True,
        created_at="created",
        updated_at="updated",
    )


def _entry(
    value: str,
    *,
    entry_id: int = 1,
    category_id: int = 1,
    system_key: str = BUILTIN_CATEGORY_CATALOG_NUMBER,
) -> CodeRegistryEntryRecord:
    return CodeRegistryEntryRecord(
        id=entry_id,
        category_id=category_id,
        category_system_key=system_key,
        category_display_name="Catalog Number",
        subject_kind="catalog",
        generation_strategy="sequential",
        value=value,
        normalized_value=value.casefold(),
        entry_kind="generated",
        prefix_snapshot="CAT",
        sequence_year=2026,
        sequence_number=entry_id,
        immutable_flag=True,
        created_at="created",
        created_via="test",
        notes=None,
    )


def _classification(
    value: str,
    classification: str,
    *,
    reason: str = "",
) -> CodeIdentifierClassification:
    return CodeIdentifierClassification(
        input_value=value,
        normalized_value=value.casefold(),
        classification=classification,
        category_id=1,
        category_system_key=BUILTIN_CATEGORY_CATALOG_NUMBER,
        category_display_name="Catalog Number",
        canonical_value=value,
        reason=reason,
    )


class RecordingCodeRegistryService:
    def __init__(self):
        self.category = _category()
        self.entries = [_entry("CAT-001", entry_id=1)]
        self.suggestions = ["EXT-001", "EXT-002"]
        self.unavailable_reason = None
        self.raise_list_entries = False
        self.raise_suggestions = False
        self.classifications = {
            "CAT-001": _classification("CAT-001", CLASSIFICATION_INTERNAL),
            "CAT-002": _classification("CAT-002", CLASSIFICATION_INTERNAL),
            "EXT-MISMATCH": _classification(
                "EXT-MISMATCH",
                CLASSIFICATION_MISMATCH,
                reason="wrong prefix",
            ),
            "EXT-CANONICAL": _classification(
                "EXT-CANONICAL",
                CLASSIFICATION_CANONICAL_CANDIDATE,
            ),
            "EXT-001": _classification("EXT-001", CLASSIFICATION_EXTERNAL),
            "UNKNOWN": _classification("UNKNOWN", "unknown"),
        }
        self.generated_entries = [_entry("CAT-002", entry_id=2)]
        self.generated_sha_entries = [
            _entry(
                "sha256:abc",
                entry_id=5,
                system_key=BUILTIN_CATEGORY_REGISTRY_SHA256_KEY,
            )
        ]

    def fetch_category_by_system_key(self, system_key):
        if system_key == BUILTIN_CATEGORY_REGISTRY_SHA256_KEY:
            return _category(
                category_id=5,
                system_key=BUILTIN_CATEGORY_REGISTRY_SHA256_KEY,
                display_name="Registry SHA-256 Key",
            )
        return self.category

    def generation_unavailable_reason(self, *, system_key):
        del system_key
        return self.unavailable_reason

    def list_entries(self, *, category_id):
        del category_id
        if self.raise_list_entries:
            raise sqlite3.DatabaseError("entries unavailable")
        return list(self.entries)

    def external_identifier_suggestions(self, *, system_key):
        del system_key
        if self.raise_suggestions:
            raise sqlite3.DatabaseError("suggestions unavailable")
        return list(self.suggestions)

    def classify_identifier_value(self, *, value, **_kwargs):
        if value == "BROKEN":
            raise sqlite3.DatabaseError("classification unavailable")
        return self.classifications.get(
            value,
            _classification(value, CLASSIFICATION_EXTERNAL),
        )

    def generate_next_code(self, *, system_key, created_via):
        del system_key, created_via
        entry = self.generated_entries.pop(0)
        self.entries.append(entry)
        return CodeRegistryEntryGenerationResult(entry=entry, category=self.category)

    def generate_sha256_key(self, *, system_key, created_via):
        del system_key, created_via
        entry = self.generated_sha_entries.pop(0)
        category = _category(
            category_id=5,
            system_key=BUILTIN_CATEGORY_REGISTRY_SHA256_KEY,
            display_name="Registry SHA-256 Key",
        )
        self.entries.append(entry)
        return CodeRegistryEntryGenerationResult(entry=entry, category=category)


class FailingCodeRegistryService:
    def fetch_category_by_system_key(self, _system_key):
        raise sqlite3.DatabaseError("database disk image is malformed")

    def generation_unavailable_reason(self, *, system_key):
        del system_key
        raise sqlite3.DatabaseError("database disk image is malformed")

    def list_entries(self, *, category_id):
        del category_id
        raise sqlite3.DatabaseError("database disk image is malformed")

    def external_identifier_suggestions(self, *, system_key):
        del system_key
        raise sqlite3.DatabaseError("database disk image is malformed")

    def classify_identifier_value(self, **_kwargs):
        raise sqlite3.DatabaseError("database disk image is malformed")


def test_catalog_identifier_field_tolerates_registry_refresh_database_errors():
    require_qapplication()
    field = CatalogIdentifierField(
        service_provider=lambda: FailingCodeRegistryService(),
        created_via="test.catalog.identifier",
    )
    try:
        field.refresh_choices()
        field.setCurrentText("CAT-001")
        field._refresh_status()

        assert field.combo.count() == 1
        assert field.identifier_value() == "CAT-001"
    finally:
        field.deleteLater()


def test_catalog_identifier_field_internal_modes_statuses_and_generation():
    require_qapplication()
    service = RecordingCodeRegistryService()
    field = CatalogIdentifierField(
        service_provider=lambda: service,
        created_via="test.catalog.identifier",
    )
    try:
        assert field.identifier_mode() == CATALOG_MODE_INTERNAL
        assert field.generate_button.isHidden() is False
        assert field.generate_button.isEnabled() is True
        assert field.combo.findText("CAT-001") >= 0

        field.set_value(value="CAT-001", registry_entry_id=1, mode=CATALOG_MODE_INTERNAL)
        assert field.registry_entry_id() == 1
        assert field.entry_id == 1
        assert "existing immutable registry value" in field.status_label.text()

        field.set_value(value="CAT-002", mode=CATALOG_MODE_INTERNAL)
        assert field.registry_entry_id() is None
        assert "canonical internal format" in field.status_label.text()

        service.unavailable_reason = "Configure an active prefix first."
        field.refresh_choices()
        field.set_value(value="CAT-002", mode=CATALOG_MODE_INTERNAL)
        assert field.generate_button.isEnabled() is False
        assert field.generate_button.toolTip() == "Configure an active prefix first."
        assert field.status_label.text() == "Configure an active prefix first."

        service.unavailable_reason = None
        service.classifications["BAD"] = _classification(
            "BAD",
            CLASSIFICATION_EXTERNAL,
            reason="not a catalog number",
        )
        field.set_value(value="BAD", mode=CATALOG_MODE_INTERNAL)
        assert field.status_label.text() == "not a catalog number"

        field.generate_value()
        assert field.identifier_value() == "CAT-002"
        assert field.registry_entry_id() == 2
    finally:
        field.deleteLater()


def test_catalog_identifier_field_external_statuses_and_identifier_ids():
    require_qapplication()
    service = RecordingCodeRegistryService()
    field = CatalogIdentifierField(
        service_provider=lambda: service,
        created_via="test.catalog.identifier",
        external_mode_label="Partner Codes",
    )
    try:
        field.set_value(
            value="EXT-001",
            external_identifier_id=7,
            mode=CATALOG_MODE_EXTERNAL,
        )
        assert field.identifier_mode() == CATALOG_MODE_EXTERNAL
        assert field.external_code_identifier_id() == 7
        assert field.external_catalog_identifier_id() == 7
        assert field.catalog_number() == "EXT-001"
        assert field.mode() == CATALOG_MODE_EXTERNAL
        assert field.value() == "EXT-001"
        assert field.status_label.text() == "Partner Codes value."

        field.set_value(value="EXT-MISMATCH", mode=CATALOG_MODE_EXTERNAL)
        assert "Known internal family" in field.status_label.text()
        assert "wrong prefix" in field.status_label.text()

        field.set_value(value="EXT-CANONICAL", mode=CATALOG_MODE_EXTERNAL)
        assert "looks canonical" in field.status_label.text()

        field.set_value(value="UNKNOWN", mode=CATALOG_MODE_EXTERNAL)
        assert "Switch to Internal Registry" in field.status_label.text()

        field.set_value(
            value="EXT-001",
            external_catalog_identifier_id=8,
            mode=CATALOG_MODE_EXTERNAL,
        )
        assert field.external_catalog_identifier_id() == 8
        field.value_combo.setEditText("EXT-CHANGED")
        field._on_text_edited("EXT-CHANGED")
        assert field.external_code_identifier_id() is None
    finally:
        field.deleteLater()


def test_catalog_identifier_field_handles_service_edges_and_invalid_modes():
    require_qapplication()
    service = RecordingCodeRegistryService()
    field = CatalogIdentifierField(
        service_provider=lambda: service,
        created_via="test.catalog.identifier",
        allow_generate=False,
    )
    try:
        field.mode_combo.setItemData(0, "bad-mode")
        field.mode_combo.setCurrentIndex(0)
        assert field.identifier_mode() == CATALOG_MODE_EXTERNAL

        service.raise_suggestions = True
        field.refresh_choices()
        assert field.combo.count() == 1
        assert field.generate_button.isVisible() is False

        field.mode_combo.setItemData(0, CATALOG_MODE_INTERNAL)
        field.set_value(value="CAT-NEW", mode=CATALOG_MODE_INTERNAL)
        service.raise_list_entries = True
        field.refresh_choices()
        assert field.combo.count() == 1

        field.set_value(value="BROKEN", mode=CATALOG_MODE_EXTERNAL)
        assert field.status_label.text() == "Registry status is temporarily unavailable."

        field.set_value()
        assert field.identifier_value() is None
        assert field.mode_combo.currentIndex() < 0
        assert field.identifier_mode() == CATALOG_MODE_EXTERNAL
        assert "No catalog number selected" in field.status_label.text()

        field.setCurrentText("")
        assert field.identifier_value() is None

        field.set_assignment(
            value="EXT-001",
            registry_entry_id=None,
            external_catalog_identifier_id=11,
            mode=None,
        )
        assert field.external_catalog_identifier_id() == 11
    finally:
        field.deleteLater()

    broken_provider_field = CatalogIdentifierField(
        service_provider=lambda: (_ for _ in ()).throw(RuntimeError("profile closed")),
        created_via="test.catalog.identifier",
    )
    try:
        broken_provider_field.setCurrentText("CAT-001")
        broken_provider_field.generate_value()
        assert broken_provider_field.registry_entry_id() is None
        assert broken_provider_field.status_label.text() == ""
    finally:
        broken_provider_field.deleteLater()


def test_catalog_identifier_field_generate_value_guard_and_sha_route():
    require_qapplication()
    service = RecordingCodeRegistryService()
    field = CatalogIdentifierField(
        service_provider=lambda: service,
        created_via="test.catalog.identifier",
    )
    try:
        service.unavailable_reason = "Generation disabled."
        field.generate_value()
        assert field.status_label.text() == "Generation disabled."
    finally:
        field.deleteLater()

    sha_field = CatalogIdentifierField(
        service_provider=lambda: service,
        system_key=BUILTIN_CATEGORY_REGISTRY_SHA256_KEY,
        created_via="test.registry.key",
    )
    try:
        service.unavailable_reason = None
        sha_field.generate_value()
        assert sha_field.identifier_value() == "sha256:abc"
        assert sha_field.registry_entry_id() == 5
    finally:
        sha_field.deleteLater()

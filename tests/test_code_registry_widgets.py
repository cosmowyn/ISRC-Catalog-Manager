import sqlite3

from isrc_manager.code_registry.widgets import CatalogIdentifierField
from tests.qt_test_helpers import require_qapplication


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

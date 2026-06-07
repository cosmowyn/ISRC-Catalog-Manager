from types import SimpleNamespace

import pytest

from isrc_manager.conversion.adapters.database import (
    _OWNER_SOURCE_FIELDS,
    DatabaseTrackSourceAdapter,
)


class _ExchangeService:
    def __init__(self, *, headers=(), rows=()):
        self.headers = tuple(headers)
        self.rows = tuple(rows)
        self.export_calls = []

    def export_rows(self, track_ids):
        self.export_calls.append(track_ids)
        return self.headers, self.rows


def test_database_source_adapter_requires_open_profile():
    adapter = DatabaseTrackSourceAdapter(exchange_service=None)

    with pytest.raises(ValueError, match="open profile"):
        adapter.inspect_source([1])


def test_database_source_adapter_handles_missing_settings_service_and_scope_selection():
    exchange = _ExchangeService(headers=("title",), rows=())
    adapter = DatabaseTrackSourceAdapter(exchange)

    profile = adapter.inspect_source([0, -1, 7])

    assert exchange.export_calls == [[7]]
    assert profile.headers == ("title",)
    assert profile.rows == ()
    assert profile.warnings == ()
    assert adapter._owner_backed_source_values() == {}
    assert adapter.select_scope(profile, "ignored") is profile


def test_database_source_adapter_falls_back_when_settings_reads_fail():
    class _FailingSettings:
        def load_sena_number(self):
            raise RuntimeError("settings unavailable")

        def load_owner_party_settings(self):
            raise RuntimeError("owner unavailable")

    adapter = DatabaseTrackSourceAdapter(
        _ExchangeService(),
        settings_read_service=_FailingSettings(),
    )

    values = adapter._settings_backed_source_values()

    assert values["pro_number"] == ""
    for header_name, _field_name in _OWNER_SOURCE_FIELDS:
        assert values[header_name] == ""


def test_database_source_adapter_enriches_rows_with_owner_settings_without_duplicate_headers():
    owner = SimpleNamespace(
        party_id="42",
        legal_name=" Label BV ",
        display_name="Label",
        artist_name="",
        company_name="Company",
        first_name="",
        middle_name=None,
        last_name="Owner",
        contact_person="Contact",
        email="owner@example.com",
        alternative_email="",
        phone="",
        website="https://example.com",
        street_name="Main",
        street_number="1",
        address_line1="Main 1",
        address_line2="",
        city="Amsterdam",
        region="NH",
        postal_code="1000 AA",
        country="NL",
        bank_account_number="NL00BANK",
        chamber_of_commerce_number="12345678",
        tax_id="",
        vat_number="NL123",
        pro_affiliation="SENA",
        pro_number="external",
    )

    class _Settings:
        def load_sena_number(self):
            return " SENA-42 "

        def load_owner_party_settings(self):
            return owner

    exchange = _ExchangeService(
        headers=("title", "pro_number", "owner_legal_name"),
        rows=({"title": "Song", "pro_number": "row value"},),
    )
    adapter = DatabaseTrackSourceAdapter(exchange, settings_read_service=_Settings())

    profile = adapter.inspect_source([1, 2])

    assert exchange.export_calls == [[1, 2]]
    assert profile.headers[:3] == ("title", "pro_number", "owner_legal_name")
    assert profile.headers.count("pro_number") == 1
    assert profile.headers.count("owner_legal_name") == 1
    assert profile.rows[0]["title"] == "Song"
    assert profile.rows[0]["pro_number"] == "SENA-42"
    assert profile.rows[0]["owner_party_id"] == "42"
    assert profile.rows[0]["owner_legal_name"] == "Label BV"
    assert profile.preview_rows == profile.rows
    assert "Release-aware export rows" in profile.warnings[0]


def test_database_source_adapter_blanks_invalid_owner_party_ids():
    class _Settings:
        def load_sena_number(self):
            return ""

        def load_owner_party_settings(self):
            return SimpleNamespace(party_id="not-a-number")

    adapter = DatabaseTrackSourceAdapter(
        _ExchangeService(),
        settings_read_service=_Settings(),
    )

    assert adapter._owner_backed_source_values()["owner_party_id"] == ""

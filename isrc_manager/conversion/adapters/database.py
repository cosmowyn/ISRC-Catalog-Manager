"""Database-backed track source adapter for conversion."""

from __future__ import annotations

from ..models import SOURCE_MODE_DATABASE_TRACKS, ConversionSourceProfile
from .base import SourceAdapter

_OWNER_SOURCE_FIELDS: tuple[tuple[str, str], ...] = (
    ("owner_party_id", "party_id"),
    ("owner_legal_name", "legal_name"),
    ("owner_display_name", "display_name"),
    ("owner_artist_name", "artist_name"),
    ("owner_company_name", "company_name"),
    ("owner_first_name", "first_name"),
    ("owner_middle_name", "middle_name"),
    ("owner_last_name", "last_name"),
    ("owner_contact_person", "contact_person"),
    ("owner_email", "email"),
    ("owner_alternative_email", "alternative_email"),
    ("owner_phone", "phone"),
    ("owner_website", "website"),
    ("owner_street_name", "street_name"),
    ("owner_street_number", "street_number"),
    ("owner_address_line1", "address_line1"),
    ("owner_address_line2", "address_line2"),
    ("owner_city", "city"),
    ("owner_region", "region"),
    ("owner_postal_code", "postal_code"),
    ("owner_country", "country"),
    ("owner_bank_account_number", "bank_account_number"),
    ("owner_chamber_of_commerce_number", "chamber_of_commerce_number"),
    ("owner_tax_id", "tax_id"),
    ("owner_vat_number", "vat_number"),
    ("owner_pro_affiliation", "pro_affiliation"),
    ("owner_pro_number", "pro_number"),
    ("owner_ipi_cae", "ipi_cae"),
)


class DatabaseTrackSourceAdapter(SourceAdapter):
    format_name = SOURCE_MODE_DATABASE_TRACKS

    def __init__(self, exchange_service, settings_read_service=None):
        self.exchange_service = exchange_service
        self.settings_read_service = settings_read_service

    def _settings_backed_source_values(self) -> dict[str, object]:
        if self.settings_read_service is None:
            return {}
        try:
            sena_number = str(self.settings_read_service.load_sena_number() or "").strip()
        except Exception:
            sena_number = ""
        owner_values = self._owner_backed_source_values()
        # Conversion templates often ask for this application setting as "PRO Number",
        # even though the authoritative settings field is stored as the SENA number.
        return {"pro_number": sena_number, **owner_values}

    def _owner_backed_source_values(self) -> dict[str, object]:
        if self.settings_read_service is None:
            return {}
        try:
            owner_settings = self.settings_read_service.load_owner_party_settings()
        except Exception:
            owner_settings = None
        if owner_settings is None:
            return {header_name: "" for header_name, _field_name in _OWNER_SOURCE_FIELDS}
        values: dict[str, object] = {}
        for header_name, field_name in _OWNER_SOURCE_FIELDS:
            raw_value = getattr(owner_settings, field_name, "")
            if field_name == "party_id":
                try:
                    values[header_name] = str(int(raw_value)) if int(raw_value) > 0 else ""
                except Exception:
                    values[header_name] = ""
                continue
            values[header_name] = str(raw_value or "").strip()
        return values

    def inspect_source(
        self,
        source,
        *,
        preferred_csv_delimiter: str | None = None,
    ) -> ConversionSourceProfile:
        del preferred_csv_delimiter
        track_ids = [int(track_id) for track_id in list(source or []) if int(track_id) > 0]
        if self.exchange_service is None:
            raise ValueError("Database-backed conversion requires an open profile.")
        headers, rows = self.exchange_service.export_rows(track_ids or None)
        settings_values = self._settings_backed_source_values()
        effective_headers = list(headers)
        for field_name in settings_values:
            if field_name not in effective_headers:
                effective_headers.append(field_name)
        row_dicts = []
        for row in rows:
            payload = dict(row)
            payload.update(settings_values)
            row_dicts.append(payload)
        return ConversionSourceProfile(
            source_mode=SOURCE_MODE_DATABASE_TRACKS,
            format_name=self.format_name,
            source_label="Current profile tracks",
            source_path="",
            headers=tuple(effective_headers),
            rows=tuple(row_dicts),
            preview_rows=tuple(row_dicts[:10]),
            warnings=tuple(
                [
                    "Release-aware export rows may expand one selected track into multiple conversion rows."
                ]
                if row_dicts
                else []
            ),
        )

    def select_scope(
        self,
        profile: ConversionSourceProfile,
        scope_key: str,
    ) -> ConversionSourceProfile:
        del scope_key
        return profile

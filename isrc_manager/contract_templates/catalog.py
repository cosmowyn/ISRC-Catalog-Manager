"""Catalog-backed placeholder symbol registry for contract template workflows."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING

from isrc_manager.assets import ASSET_TYPE_CHOICES
from isrc_manager.code_registry import (
    BUILTIN_CATEGORY_CATALOG_NUMBER,
    BUILTIN_CATEGORY_CONTRACT_NUMBER,
    BUILTIN_CATEGORY_LICENSE_NUMBER,
    BUILTIN_CATEGORY_REGISTRY_SHA256_KEY,
)
from isrc_manager.contracts import CONTRACT_STATUS_CHOICES
from isrc_manager.domain.standard_fields import STANDARD_FIELD_SPECS
from isrc_manager.parties import PARTY_TYPE_CHOICES
from isrc_manager.releases import RELEASE_TYPE_CHOICES
from isrc_manager.rights import RIGHT_TYPE_CHOICES
from isrc_manager.works import WORK_STATUS_CHOICES

from .models import ContractTemplateCatalogEntry
from .parser import parse_placeholder

if TYPE_CHECKING:
    from isrc_manager.services.custom_fields import CustomFieldDefinitionService

_CUSTOM_FIELD_EXCLUDED_TYPES = frozenset({"blob_audio", "blob_image"})
_NORMALIZE_KEY_RE = re.compile(r"[^A-Za-z0-9_-]+")
_NAMESPACE_ORDER = (
    "track",
    "release",
    "work",
    "contract",
    "owner",
    "party",
    "right",
    "asset",
    "custom",
)
_TRACK_SOURCE_OVERRIDES = {
    "album_title": ("TrackSnapshot", "album_title"),
    "artist_name": ("TrackSnapshot", "artist_name"),
    "additional_artists": ("TrackSnapshot", "additional_artists"),
}
_SCOPE_POLICY_BY_NAMESPACE = {
    "track": "track_context",
    "release": "release_selection_required",
    "work": "work_selection_required",
    "contract": "contract_selection_required",
    "owner": "owner_settings_context",
    "party": "party_selection_required",
    "right": "right_selection_required",
    "asset": "asset_selection_required",
    "custom": "track_context",
}
_SCOPE_ENTITY_BY_NAMESPACE = {
    "track": "track",
    "release": "release",
    "work": "work",
    "contract": "contract",
    "owner": "owner",
    "party": "party",
    "right": "right",
    "asset": "asset",
    "custom": "track",
}

_REGISTRY_BINDINGS = {
    ("track", "catalog_number"): (BUILTIN_CATEGORY_CATALOG_NUMBER, "track"),
    ("release", "catalog_number"): (BUILTIN_CATEGORY_CATALOG_NUMBER, "release"),
    ("contract", "contract_number"): (BUILTIN_CATEGORY_CONTRACT_NUMBER, "contract"),
    ("contract", "license_number"): (BUILTIN_CATEGORY_LICENSE_NUMBER, "contract"),
    ("contract", "registry_sha256_key"): (BUILTIN_CATEGORY_REGISTRY_SHA256_KEY, "contract"),
}


@dataclass(frozen=True, slots=True)
class _CatalogSeed:
    namespace: str
    key: str
    label: str
    field_type: str
    source_table: str
    source_column: str | None = None
    description: str | None = None
    options: tuple[str, ...] = ()
    is_settings_field: bool = False


@dataclass(slots=True)
class ContractTemplateCatalogSection:
    namespace: str
    label: str
    entries: tuple[ContractTemplateCatalogEntry, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "namespace": self.namespace,
            "label": self.label,
            "entries": [item.to_dict() for item in self.entries],
        }


@dataclass(frozen=True, slots=True)
class ContractTemplateRegistryBinding:
    system_key: str
    owner_kind: str


def _track_seeds() -> tuple[_CatalogSeed, ...]:
    seeds: list[_CatalogSeed] = []
    for spec in STANDARD_FIELD_SPECS:
        if spec.key in {"id", "audio_file", "album_art"}:
            continue
        if spec.field_type in {"blob_audio", "blob_image"}:
            continue
        source_table, source_column = _TRACK_SOURCE_OVERRIDES.get(
            spec.key,
            ("Tracks", spec.value_column or spec.key),
        )
        seeds.append(
            _CatalogSeed(
                namespace="track",
                key=spec.key,
                label=spec.label,
                field_type=spec.field_type,
                source_table=source_table,
                source_column=source_column,
            )
        )
    seeds.extend(
        (
            _CatalogSeed("track", "composer", "Composer", "text", "Tracks", "composer"),
            _CatalogSeed("track", "publisher", "Publisher", "text", "Tracks", "publisher"),
            _CatalogSeed("track", "comments", "Comments", "text", "Tracks", "comments"),
            _CatalogSeed("track", "lyrics", "Lyrics", "text", "Tracks", "lyrics"),
        )
    )
    return tuple(seeds)


def registry_binding_for_catalog_entry(
    namespace: str | None,
    key: str | None,
) -> ContractTemplateRegistryBinding | None:
    binding = _REGISTRY_BINDINGS.get((str(namespace or "").strip().lower(), str(key or "").strip()))
    if binding is None:
        return None
    system_key, owner_kind = binding
    return ContractTemplateRegistryBinding(system_key=system_key, owner_kind=owner_kind)


def registry_binding_for_symbol(
    canonical_symbol: str | None,
) -> ContractTemplateRegistryBinding | None:
    token = parse_placeholder(str(canonical_symbol or ""))
    if token.binding_kind != "db":
        return None
    return registry_binding_for_catalog_entry(token.namespace, token.key)


_STATIC_SEEDS: tuple[_CatalogSeed, ...] = _track_seeds() + (
    _CatalogSeed("release", "title", "Release Title", "text", "Releases", "title"),
    _CatalogSeed(
        "release", "version_subtitle", "Version Subtitle", "text", "Releases", "version_subtitle"
    ),
    _CatalogSeed(
        "release", "primary_artist", "Primary Artist", "text", "Releases", "primary_artist"
    ),
    _CatalogSeed("release", "album_artist", "Album Artist", "text", "Releases", "album_artist"),
    _CatalogSeed(
        "release",
        "release_type",
        "Release Type",
        "dropdown",
        "Releases",
        "release_type",
        options=tuple(RELEASE_TYPE_CHOICES),
    ),
    _CatalogSeed("release", "release_date", "Release Date", "date", "Releases", "release_date"),
    _CatalogSeed(
        "release",
        "original_release_date",
        "Original Release Date",
        "date",
        "Releases",
        "original_release_date",
    ),
    _CatalogSeed("release", "label", "Label", "text", "Releases", "label"),
    _CatalogSeed("release", "sublabel", "Sublabel", "text", "Releases", "sublabel"),
    _CatalogSeed(
        "release", "catalog_number", "Catalog Number", "text", "Releases", "catalog_number"
    ),
    _CatalogSeed("release", "upc", "UPC", "text", "Releases", "upc"),
    _CatalogSeed(
        "release",
        "barcode_validation_status",
        "Barcode Validation Status",
        "text",
        "Releases",
        "barcode_validation_status",
    ),
    _CatalogSeed("release", "territory", "Territory", "text", "Releases", "territory"),
    _CatalogSeed(
        "release", "explicit_flag", "Explicit Release", "checkbox", "Releases", "explicit_flag"
    ),
    _CatalogSeed(
        "release", "repertoire_status", "Repertoire Status", "text", "Releases", "repertoire_status"
    ),
    _CatalogSeed(
        "release",
        "metadata_complete",
        "Metadata Complete",
        "checkbox",
        "Releases",
        "metadata_complete",
    ),
    _CatalogSeed(
        "release", "contract_signed", "Contract Signed", "checkbox", "Releases", "contract_signed"
    ),
    _CatalogSeed(
        "release", "rights_verified", "Rights Verified", "checkbox", "Releases", "rights_verified"
    ),
    _CatalogSeed("release", "notes", "Release Notes", "text", "Releases", "release_notes"),
    _CatalogSeed("work", "title", "Work Title", "text", "Works", "title"),
    _CatalogSeed(
        "work", "version_subtitle", "Version Subtitle", "text", "Works", "version_subtitle"
    ),
    _CatalogSeed("work", "language", "Language", "text", "Works", "language"),
    _CatalogSeed("work", "genre_notes", "Genre Notes", "text", "Works", "genre_notes"),
    _CatalogSeed("work", "iswc", "ISWC", "text", "Works", "iswc"),
    _CatalogSeed(
        "work", "registration_number", "Registration Number", "text", "Works", "registration_number"
    ),
    _CatalogSeed(
        "work",
        "work_status",
        "Work Status",
        "dropdown",
        "Works",
        "work_status",
        options=tuple(WORK_STATUS_CHOICES),
    ),
    _CatalogSeed("work", "lyrics_flag", "Lyrics Based", "checkbox", "Works", "lyrics_flag"),
    _CatalogSeed(
        "work", "instrumental_flag", "Instrumental", "checkbox", "Works", "instrumental_flag"
    ),
    _CatalogSeed(
        "work", "metadata_complete", "Metadata Complete", "checkbox", "Works", "metadata_complete"
    ),
    _CatalogSeed(
        "work", "contract_signed", "Contract Signed", "checkbox", "Works", "contract_signed"
    ),
    _CatalogSeed(
        "work", "rights_verified", "Rights Verified", "checkbox", "Works", "rights_verified"
    ),
    _CatalogSeed("work", "notes", "Work Notes", "text", "Works", "notes"),
    _CatalogSeed("contract", "title", "Contract Title", "text", "Contracts", "title"),
    _CatalogSeed(
        "contract", "contract_type", "Contract Type", "text", "Contracts", "contract_type"
    ),
    _CatalogSeed(
        "contract", "contract_number", "Contract Number", "text", "Contracts", "contract_number"
    ),
    _CatalogSeed(
        "contract", "license_number", "License Number", "text", "Contracts", "license_number"
    ),
    _CatalogSeed(
        "contract",
        "registry_sha256_key",
        "Registry SHA-256 Key",
        "text",
        "Contracts",
        "registry_sha256_key",
    ),
    _CatalogSeed("contract", "draft_date", "Draft Date", "date", "Contracts", "draft_date"),
    _CatalogSeed(
        "contract", "signature_date", "Signature Date", "date", "Contracts", "signature_date"
    ),
    _CatalogSeed(
        "contract", "effective_date", "Effective Date", "date", "Contracts", "effective_date"
    ),
    _CatalogSeed("contract", "start_date", "Start Date", "date", "Contracts", "start_date"),
    _CatalogSeed("contract", "end_date", "End Date", "date", "Contracts", "end_date"),
    _CatalogSeed("contract", "renewal_date", "Renewal Date", "date", "Contracts", "renewal_date"),
    _CatalogSeed(
        "contract", "notice_deadline", "Notice Deadline", "date", "Contracts", "notice_deadline"
    ),
    _CatalogSeed(
        "contract", "option_periods", "Option Periods", "text", "Contracts", "option_periods"
    ),
    _CatalogSeed(
        "contract", "reversion_date", "Reversion Date", "date", "Contracts", "reversion_date"
    ),
    _CatalogSeed(
        "contract", "termination_date", "Termination Date", "date", "Contracts", "termination_date"
    ),
    _CatalogSeed(
        "contract",
        "status",
        "Contract Status",
        "dropdown",
        "Contracts",
        "status",
        options=tuple(CONTRACT_STATUS_CHOICES),
    ),
    _CatalogSeed("contract", "summary", "Summary", "text", "Contracts", "summary"),
    _CatalogSeed("contract", "notes", "Contract Notes", "text", "Contracts", "notes"),
    _CatalogSeed(
        "owner",
        "legal_name",
        "Owner Legal Name",
        "text",
        "OwnerParty",
        "legal_name",
        is_settings_field=True,
    ),
    _CatalogSeed(
        "owner",
        "display_name",
        "Owner Display Name",
        "text",
        "OwnerParty",
        "display_name",
        is_settings_field=True,
    ),
    _CatalogSeed(
        "owner",
        "artist_name",
        "Owner Artist Name",
        "text",
        "OwnerParty",
        "artist_name",
        is_settings_field=True,
    ),
    _CatalogSeed(
        "owner",
        "company_name",
        "Owner Company Name",
        "text",
        "OwnerParty",
        "company_name",
        is_settings_field=True,
    ),
    _CatalogSeed(
        "owner",
        "first_name",
        "Owner First Name",
        "text",
        "OwnerParty",
        "first_name",
        is_settings_field=True,
    ),
    _CatalogSeed(
        "owner",
        "middle_name",
        "Owner Middle Name",
        "text",
        "OwnerParty",
        "middle_name",
        is_settings_field=True,
    ),
    _CatalogSeed(
        "owner",
        "last_name",
        "Owner Last Name",
        "text",
        "OwnerParty",
        "last_name",
        is_settings_field=True,
    ),
    _CatalogSeed(
        "owner",
        "contact_person",
        "Owner Contact Person",
        "text",
        "OwnerParty",
        "contact_person",
        is_settings_field=True,
    ),
    _CatalogSeed(
        "owner",
        "email",
        "Owner Email",
        "text",
        "OwnerParty",
        "email",
        is_settings_field=True,
    ),
    _CatalogSeed(
        "owner",
        "alternative_email",
        "Owner Alternative Email",
        "text",
        "OwnerParty",
        "alternative_email",
        is_settings_field=True,
    ),
    _CatalogSeed(
        "owner",
        "phone",
        "Owner Phone",
        "text",
        "OwnerParty",
        "phone",
        is_settings_field=True,
    ),
    _CatalogSeed(
        "owner",
        "website",
        "Owner Website",
        "text",
        "OwnerParty",
        "website",
        is_settings_field=True,
    ),
    _CatalogSeed(
        "owner",
        "street_name",
        "Owner Street Name",
        "text",
        "OwnerParty",
        "street_name",
        is_settings_field=True,
    ),
    _CatalogSeed(
        "owner",
        "street_number",
        "Owner Street Number",
        "text",
        "OwnerParty",
        "street_number",
        is_settings_field=True,
    ),
    _CatalogSeed(
        "owner",
        "address_line1",
        "Owner Address Line 1",
        "text",
        "OwnerParty",
        "address_line1",
        is_settings_field=True,
    ),
    _CatalogSeed(
        "owner",
        "address_line2",
        "Owner Address Line 2",
        "text",
        "OwnerParty",
        "address_line2",
        is_settings_field=True,
    ),
    _CatalogSeed(
        "owner",
        "city",
        "Owner City",
        "text",
        "OwnerParty",
        "city",
        is_settings_field=True,
    ),
    _CatalogSeed(
        "owner",
        "region",
        "Owner Region",
        "text",
        "OwnerParty",
        "region",
        is_settings_field=True,
    ),
    _CatalogSeed(
        "owner",
        "postal_code",
        "Owner Postal Code",
        "text",
        "OwnerParty",
        "postal_code",
        is_settings_field=True,
    ),
    _CatalogSeed(
        "owner",
        "country",
        "Owner Country",
        "text",
        "OwnerParty",
        "country",
        is_settings_field=True,
    ),
    _CatalogSeed(
        "owner",
        "bank_account_number",
        "Owner Bank Account Number",
        "text",
        "OwnerParty",
        "bank_account_number",
        is_settings_field=True,
    ),
    _CatalogSeed(
        "owner",
        "chamber_of_commerce_number",
        "Owner Chamber Of Commerce Number",
        "text",
        "OwnerParty",
        "chamber_of_commerce_number",
        is_settings_field=True,
    ),
    _CatalogSeed(
        "owner",
        "tax_id",
        "Owner Tax ID",
        "text",
        "OwnerParty",
        "tax_id",
        is_settings_field=True,
    ),
    _CatalogSeed(
        "owner",
        "vat_number",
        "Owner VAT Number",
        "text",
        "OwnerParty",
        "vat_number",
        is_settings_field=True,
    ),
    _CatalogSeed(
        "owner",
        "pro_affiliation",
        "Owner PRO Affiliation",
        "text",
        "OwnerParty",
        "pro_affiliation",
        is_settings_field=True,
    ),
    _CatalogSeed(
        "owner",
        "pro_number",
        "Owner PRO Number",
        "text",
        "OwnerParty",
        "pro_number",
        is_settings_field=True,
    ),
    _CatalogSeed(
        "owner",
        "ipi_cae",
        "Owner IPI/CAE",
        "text",
        "OwnerParty",
        "ipi_cae",
        is_settings_field=True,
    ),
    _CatalogSeed("party", "legal_name", "Legal Name", "text", "Parties", "legal_name"),
    _CatalogSeed("party", "display_name", "Display Name", "text", "Parties", "display_name"),
    _CatalogSeed("party", "artist_name", "Artist Name", "text", "Parties", "artist_name"),
    _CatalogSeed(
        "party", "artist_aliases", "Artist Aliases", "text", "PartyArtistAliases", "alias_name"
    ),
    _CatalogSeed("party", "company_name", "Company Name", "text", "Parties", "company_name"),
    _CatalogSeed("party", "first_name", "First Name", "text", "Parties", "first_name"),
    _CatalogSeed("party", "middle_name", "Middle Name", "text", "Parties", "middle_name"),
    _CatalogSeed("party", "last_name", "Last Name", "text", "Parties", "last_name"),
    _CatalogSeed(
        "party",
        "party_type",
        "Party Type",
        "dropdown",
        "Parties",
        "party_type",
        options=tuple(PARTY_TYPE_CHOICES),
    ),
    _CatalogSeed("party", "contact_person", "Contact Person", "text", "Parties", "contact_person"),
    _CatalogSeed("party", "email", "Email", "text", "Parties", "email"),
    _CatalogSeed(
        "party", "alternative_email", "Alternative Email", "text", "Parties", "alternative_email"
    ),
    _CatalogSeed("party", "phone", "Phone", "text", "Parties", "phone"),
    _CatalogSeed("party", "website", "Website", "text", "Parties", "website"),
    _CatalogSeed("party", "street_name", "Street Name", "text", "Parties", "street_name"),
    _CatalogSeed("party", "street_number", "Street Number", "text", "Parties", "street_number"),
    _CatalogSeed("party", "address_line1", "Address Line 1", "text", "Parties", "address_line1"),
    _CatalogSeed("party", "address_line2", "Address Line 2", "text", "Parties", "address_line2"),
    _CatalogSeed("party", "city", "City", "text", "Parties", "city"),
    _CatalogSeed("party", "region", "Region", "text", "Parties", "region"),
    _CatalogSeed("party", "postal_code", "Postal Code", "text", "Parties", "postal_code"),
    _CatalogSeed("party", "country", "Country", "text", "Parties", "country"),
    _CatalogSeed(
        "party",
        "bank_account_number",
        "Bank Account Number",
        "text",
        "Parties",
        "bank_account_number",
    ),
    _CatalogSeed(
        "party",
        "chamber_of_commerce_number",
        "Chamber Of Commerce Number",
        "text",
        "Parties",
        "chamber_of_commerce_number",
    ),
    _CatalogSeed("party", "tax_id", "Tax ID", "text", "Parties", "tax_id"),
    _CatalogSeed("party", "vat_number", "VAT Number", "text", "Parties", "vat_number"),
    _CatalogSeed(
        "party", "pro_affiliation", "PRO Affiliation", "text", "Parties", "pro_affiliation"
    ),
    _CatalogSeed("party", "pro_number", "PRO Number", "text", "Parties", "pro_number"),
    _CatalogSeed("party", "ipi_cae", "IPI/CAE", "text", "Parties", "ipi_cae"),
    _CatalogSeed("party", "notes", "Party Notes", "text", "Parties", "notes"),
    _CatalogSeed("right", "title", "Right Title", "text", "Rights", "title"),
    _CatalogSeed(
        "right",
        "right_type",
        "Right Type",
        "dropdown",
        "Rights",
        "right_type",
        options=tuple(RIGHT_TYPE_CHOICES),
    ),
    _CatalogSeed("right", "exclusive_flag", "Exclusive", "checkbox", "Rights", "exclusive_flag"),
    _CatalogSeed("right", "territory", "Territory", "text", "Rights", "territory"),
    _CatalogSeed("right", "media_use_type", "Media Use Type", "text", "Rights", "media_use_type"),
    _CatalogSeed("right", "start_date", "Start Date", "date", "Rights", "start_date"),
    _CatalogSeed("right", "end_date", "End Date", "date", "Rights", "end_date"),
    _CatalogSeed("right", "perpetual_flag", "Perpetual", "checkbox", "Rights", "perpetual_flag"),
    _CatalogSeed("right", "granted_by_name", "Granted By Party", "text", "Parties", "legal_name"),
    _CatalogSeed("right", "granted_to_name", "Granted To Party", "text", "Parties", "legal_name"),
    _CatalogSeed("right", "retained_by_name", "Retained By Party", "text", "Parties", "legal_name"),
    _CatalogSeed(
        "right", "source_contract_title", "Source Contract Title", "text", "Contracts", "title"
    ),
    _CatalogSeed("right", "notes", "Right Notes", "text", "Rights", "notes"),
    _CatalogSeed(
        "asset",
        "asset_type",
        "Asset Type",
        "dropdown",
        "AssetVersions",
        "asset_type",
        options=tuple(ASSET_TYPE_CHOICES),
    ),
    _CatalogSeed("asset", "filename", "Filename", "text", "AssetVersions", "filename"),
    _CatalogSeed("asset", "checksum_sha256", "SHA-256", "text", "AssetVersions", "checksum_sha256"),
    _CatalogSeed("asset", "duration_sec", "Duration (sec)", "int", "AssetVersions", "duration_sec"),
    _CatalogSeed("asset", "sample_rate", "Sample Rate", "int", "AssetVersions", "sample_rate"),
    _CatalogSeed("asset", "bit_depth", "Bit Depth", "int", "AssetVersions", "bit_depth"),
    _CatalogSeed("asset", "format", "Format", "text", "AssetVersions", "format"),
    _CatalogSeed(
        "asset",
        "approved_for_use",
        "Approved For Use",
        "checkbox",
        "AssetVersions",
        "approved_for_use",
    ),
    _CatalogSeed(
        "asset", "primary_flag", "Primary Asset", "checkbox", "AssetVersions", "primary_flag"
    ),
    _CatalogSeed(
        "asset", "version_status", "Version Status", "text", "AssetVersions", "version_status"
    ),
    _CatalogSeed("asset", "notes", "Asset Notes", "text", "AssetVersions", "notes"),
)


class ContractTemplateCatalogService:
    """Exposes copy-ready canonical placeholders from authoritative app data fields."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        custom_field_definition_service: "CustomFieldDefinitionService | None" = None,
    ):
        self.conn = conn
        if custom_field_definition_service is None:
            from isrc_manager.services.custom_fields import CustomFieldDefinitionService

        self.custom_field_definition_service = (
            custom_field_definition_service
            if custom_field_definition_service is not None
            else CustomFieldDefinitionService(conn)
        )

    def list_known_symbols(
        self,
        *,
        search_text: str = "",
        namespace: str | None = None,
    ) -> list[ContractTemplateCatalogEntry]:
        entries = list(self._static_entries()) + list(self._custom_field_entries())
        clean_namespace = str(namespace or "").strip().lower()
        if clean_namespace and clean_namespace != "all":
            entries = [item for item in entries if item.namespace == clean_namespace]
        query = str(search_text or "").strip().casefold()
        if query:
            entries = [
                item
                for item in entries
                if query in item.display_label.casefold()
                or query in item.canonical_symbol.casefold()
                or query in item.key.casefold()
                or query in str(item.namespace or "").casefold()
                or query in str(item.description or "").casefold()
            ]
        return sorted(
            entries,
            key=lambda item: (
                (
                    _NAMESPACE_ORDER.index(item.namespace)
                    if item.namespace in _NAMESPACE_ORDER
                    else 999
                ),
                item.is_custom_field,
                item.display_label.casefold(),
                item.canonical_symbol,
            ),
        )

    def list_namespaces(self) -> tuple[str, ...]:
        seen: set[str] = set()
        ordered: list[str] = []
        for entry in self.list_known_symbols():
            namespace = str(entry.namespace or "").strip()
            if not namespace or namespace in seen:
                continue
            seen.add(namespace)
            ordered.append(namespace)
        return tuple(ordered)

    def list_sections(self) -> tuple[ContractTemplateCatalogSection, ...]:
        grouped: list[ContractTemplateCatalogSection] = []
        for namespace in self.list_namespaces():
            entries = tuple(self.list_known_symbols(namespace=namespace))
            grouped.append(
                ContractTemplateCatalogSection(
                    namespace=namespace,
                    label=namespace.replace("_", " ").title(),
                    entries=entries,
                )
            )
        return tuple(grouped)

    def list_catalog_entries(
        self,
        *,
        search_text: str = "",
        namespace: str | None = None,
    ) -> list[ContractTemplateCatalogEntry]:
        return self.list_known_symbols(search_text=search_text, namespace=namespace)

    def list_entries(
        self,
        *,
        search_text: str = "",
        namespace: str | None = None,
    ) -> list[ContractTemplateCatalogEntry]:
        return self.list_known_symbols(search_text=search_text, namespace=namespace)

    def build_manual_symbol(self, value: str) -> str:
        normalized = _NORMALIZE_KEY_RE.sub("_", str(value or "").strip())
        normalized = normalized.lower().replace("-", "_")
        normalized = re.sub(r"_+", "_", normalized).strip("_")
        if not normalized:
            raise ValueError("Manual placeholder label must contain at least one letter or number.")
        return parse_placeholder(f"{{{{manual.{normalized}}}}}").canonical_symbol

    def _static_entries(self) -> tuple[ContractTemplateCatalogEntry, ...]:
        return tuple(self._entry_from_seed(seed) for seed in _STATIC_SEEDS)

    def _custom_field_entries(self) -> tuple[ContractTemplateCatalogEntry, ...]:
        fields = self.custom_field_definition_service.list_active_fields()
        entries: list[ContractTemplateCatalogEntry] = []
        for field in fields:
            field_type = str(field.get("field_type") or "text").strip().lower()
            if field_type in _CUSTOM_FIELD_EXCLUDED_TYPES:
                continue
            field_id = int(field["id"])
            key = f"cf_{field_id}"
            token = parse_placeholder(f"{{{{db.custom.{key}}}}}")
            entries.append(
                ContractTemplateCatalogEntry(
                    binding_kind="db",
                    namespace="custom",
                    key=key,
                    canonical_symbol=token.canonical_symbol,
                    display_label=str(field.get("name") or f"Custom Field {field_id}"),
                    field_type=field_type,
                    description=(f"Track custom field '{str(field.get('name') or field_id)}'."),
                    scope_entity_type="track",
                    scope_policy=_SCOPE_POLICY_BY_NAMESPACE["custom"],
                    source_table="CustomFieldValues",
                    source_column=None,
                    options=self._parse_custom_options(field.get("options")),
                    custom_field_id=field_id,
                    is_custom_field=True,
                    is_settings_field=False,
                )
            )
        return tuple(entries)

    def _entry_from_seed(self, seed: _CatalogSeed) -> ContractTemplateCatalogEntry:
        token = parse_placeholder(f"{{{{db.{seed.namespace}.{seed.key}}}}}")
        return ContractTemplateCatalogEntry(
            binding_kind="db",
            namespace=seed.namespace,
            key=seed.key,
            canonical_symbol=token.canonical_symbol,
            display_label=seed.label,
            field_type=seed.field_type,
            description=seed.description or self._default_description(seed.namespace, seed.label),
            scope_entity_type=_SCOPE_ENTITY_BY_NAMESPACE.get(seed.namespace),
            scope_policy=_SCOPE_POLICY_BY_NAMESPACE.get(seed.namespace),
            source_table=seed.source_table,
            source_column=seed.source_column,
            options=seed.options,
            is_settings_field=seed.is_settings_field,
        )

    @staticmethod
    def _default_description(namespace: str, label: str) -> str:
        scope_label = {
            "track": "selected track context",
            "release": "explicit release scope",
            "work": "explicit work scope",
            "contract": "explicit contract scope",
            "owner": "application owner settings",
            "party": "explicit party scope",
            "right": "explicit right scope",
            "asset": "explicit asset scope",
            "custom": "selected track context",
        }.get(namespace, "current fill scope")
        return f"{label} from the {scope_label}."

    @staticmethod
    def _parse_custom_options(raw_options: object | None) -> tuple[str, ...]:
        text = str(raw_options or "").strip()
        if not text:
            return ()
        try:
            loaded = json.loads(text)
        except Exception:
            loaded = None
        if isinstance(loaded, list):
            return tuple(str(item).strip() for item in loaded if str(item).strip())
        return tuple(part.strip() for part in re.split(r"[\r\n|]+", text) if part.strip())

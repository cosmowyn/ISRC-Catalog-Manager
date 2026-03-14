"""Canonical GS1 models shared across the UI, persistence, and export layers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


CANONICAL_GS1_EXPORT_FIELDS = (
    "gtin_request_number",
    "status",
    "product_classification",
    "consumer_unit_flag",
    "packaging_type",
    "target_market",
    "product_description",
    "language",
    "brand",
    "subbrand",
    "quantity",
    "unit",
    "image_url",
)

CORE_GS1_TEMPLATE_FIELDS = (
    "gtin_request_number",
    "status",
    "product_classification",
    "consumer_unit_flag",
    "packaging_type",
    "target_market",
    "product_description",
    "language",
    "brand",
    "quantity",
    "unit",
)

REQUIRED_GS1_METADATA_FIELDS = (
    "status",
    "product_classification",
    "packaging_type",
    "target_market",
    "product_description",
    "language",
    "brand",
    "quantity",
    "unit",
)


@dataclass(slots=True)
class GS1ProfileDefaults:
    contract_number: str = ""
    target_market: str = ""
    language: str = ""
    brand: str = ""
    subbrand: str = ""
    packaging_type: str = ""
    product_classification: str = ""


@dataclass(slots=True)
class GS1RecordContext:
    track_id: int
    track_title: str = ""
    album_title: str = ""
    artist_name: str = ""
    upc: str = ""
    release_date: str = ""
    catalog_number: str = ""
    profile_label: str = ""

    @property
    def release_title(self) -> str:
        return (self.album_title or self.track_title or "").strip()

    @property
    def display_title(self) -> str:
        title = self.release_title
        if title:
            return title
        return f"Track {self.track_id}"


@dataclass(slots=True)
class GS1MetadataRecord:
    track_id: int
    id: int | None = None
    contract_number: str = ""
    status: str = "Concept"
    product_classification: str = ""
    consumer_unit_flag: bool = True
    packaging_type: str = ""
    target_market: str = ""
    language: str = ""
    product_description: str = ""
    brand: str = ""
    subbrand: str = ""
    quantity: str = "1"
    unit: str = ""
    image_url: str = ""
    notes: str = ""
    export_enabled: bool = True
    created_at: str | None = None
    updated_at: str | None = None

    def copy(self) -> "GS1MetadataRecord":
        return GS1MetadataRecord(
            id=self.id,
            track_id=self.track_id,
            contract_number=self.contract_number,
            status=self.status,
            product_classification=self.product_classification,
            consumer_unit_flag=bool(self.consumer_unit_flag),
            packaging_type=self.packaging_type,
            target_market=self.target_market,
            language=self.language,
            product_description=self.product_description,
            brand=self.brand,
            subbrand=self.subbrand,
            quantity=self.quantity,
            unit=self.unit,
            image_url=self.image_url,
            notes=self.notes,
            export_enabled=bool(self.export_enabled),
            created_at=self.created_at,
            updated_at=self.updated_at,
        )


@dataclass(slots=True)
class GS1ValidationIssue:
    field_name: str
    message: str


@dataclass(slots=True)
class GS1ValidationResult:
    issues: list[GS1ValidationIssue]

    @property
    def is_valid(self) -> bool:
        return not self.issues

    def messages(self) -> list[str]:
        return [issue.message for issue in self.issues]


@dataclass(slots=True)
class GS1TemplateCandidate:
    sheet_name: str
    header_row: int
    column_map: dict[str, int]
    matched_headers: dict[str, str]
    score: float
    workbook_markers: list[str]


@dataclass(slots=True)
class GS1TemplateSheetProfile:
    sheet_name: str
    header_row: int
    column_map: dict[str, int]
    matched_headers: dict[str, str]
    score: float
    missing_optional_fields: tuple[str, ...] = ()
    field_options: dict[str, tuple[str, ...]] = field(default_factory=dict)


@dataclass(slots=True)
class GS1TemplateProfile:
    workbook_path: Path
    sheet_name: str
    header_row: int
    column_map: dict[str, int]
    matched_headers: dict[str, str]
    score: float
    workbook_markers: list[str]
    locale_hint: str = "default"
    missing_optional_fields: tuple[str, ...] = ()
    field_options: dict[str, tuple[str, ...]] = field(default_factory=dict)
    sheet_profiles: dict[str, GS1TemplateSheetProfile] = field(default_factory=dict)

    @property
    def available_sheet_names(self) -> tuple[str, ...]:
        if self.sheet_profiles:
            return tuple(self.sheet_profiles.keys())
        if self.sheet_name:
            return (self.sheet_name,)
        return ()

    def sheet_profile(self, sheet_name: str) -> GS1TemplateSheetProfile:
        clean_name = str(sheet_name or "").strip()
        profile = self.sheet_profiles.get(clean_name)
        if profile is not None:
            return profile
        if clean_name == self.sheet_name:
            return GS1TemplateSheetProfile(
                sheet_name=self.sheet_name,
                header_row=self.header_row,
                column_map=dict(self.column_map),
                matched_headers=dict(self.matched_headers),
                score=self.score,
                missing_optional_fields=tuple(self.missing_optional_fields),
                field_options=dict(self.field_options),
            )
        raise KeyError(clean_name)

    def resolve_sheet_name(self, contract_number: str) -> str:
        clean_contract = str(contract_number or "").strip()
        if clean_contract:
            if clean_contract in self.available_sheet_names:
                return clean_contract
            raise GS1TemplateVerificationError(
                "The selected GS1 contract number does not match any writable sheet in the configured workbook:\n"
                f"{clean_contract}\n\n"
                "Choose a contract number that exists in the workbook or select the correct official workbook."
            )
        if len(self.available_sheet_names) == 1:
            return self.available_sheet_names[0]
        raise GS1TemplateVerificationError(
            "This workbook contains multiple GS1 contract sheets. Choose an active contract number in Settings "
            "or on the GS1 record before exporting."
        )


@dataclass(slots=True)
class GS1PreparedRecord:
    metadata: GS1MetadataRecord
    context: GS1RecordContext
    source_track_ids: tuple[int, ...] = ()
    source_track_labels: tuple[str, ...] = ()
    source_upc_values: tuple[str, ...] = ()


@dataclass(slots=True)
class GS1MetadataGroup:
    group_id: str
    tab_title: str
    display_title: str
    mode: str
    track_ids: tuple[int, ...]
    contexts: tuple[GS1RecordContext, ...]
    record: GS1MetadataRecord
    default_record: GS1MetadataRecord

    @property
    def representative_context(self) -> GS1RecordContext:
        return self.contexts[0]

    @property
    def is_album_group(self) -> bool:
        return self.mode == "album"


@dataclass(slots=True)
class GS1ExportPreview:
    headers: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    row_sheet_names: tuple[str, ...] = ()


@dataclass(slots=True)
class GS1ExportPlan:
    template_profile: GS1TemplateProfile
    prepared_records: tuple[GS1PreparedRecord, ...]
    preview: GS1ExportPreview
    warnings: tuple[str, ...] = ()
    summary_lines: tuple[str, ...] = ()
    mode: str = "single"


@dataclass(slots=True)
class GS1BatchValidationIssue:
    track_id: int
    track_label: str
    messages: list[str]


@dataclass(slots=True)
class GS1ExportResult:
    output_path: Path
    exported_count: int
    sheet_name: str
    row_numbers: list[int]
    sheet_row_numbers: dict[str, tuple[int, ...]] = field(default_factory=dict)


@dataclass(slots=True)
class GS1ContractEntry:
    contract_number: str
    product: str = ""
    company_number: str = ""
    start_number: str = ""
    end_number: str = ""
    renewal_date: str = ""
    end_date: str = ""
    status: str = ""
    tier: str = ""

    @property
    def is_active(self) -> bool:
        normalized = str(self.status or "").strip().casefold()
        return normalized in {"active", "actief"}


class GS1Error(Exception):
    """Base class for GS1 workflow failures."""


class GS1DependencyError(GS1Error):
    """Raised when the optional Excel dependency is unavailable."""


class GS1ContractImportError(GS1Error):
    """Raised when an imported GS1 contracts CSV cannot be parsed or yields no usable contracts."""


class GS1TemplateVerificationError(GS1Error):
    """Raised when a workbook is missing, unreadable, or not recognized."""


class GS1ValidationError(GS1Error):
    """Raised when one record fails GS1 validation."""

    def __init__(self, result: GS1ValidationResult):
        self.result = result
        super().__init__("\n".join(result.messages()) or "GS1 metadata is invalid.")


class GS1BatchValidationError(GS1Error):
    """Raised when one or more records cannot be exported."""

    def __init__(self, issues: list[GS1BatchValidationIssue]):
        self.issues = issues
        lines = []
        for issue in issues:
            title = issue.track_label or f"Track {issue.track_id}"
            lines.append(f"{title}: " + "; ".join(issue.messages))
        super().__init__("\n".join(lines) or "One or more GS1 records are invalid.")

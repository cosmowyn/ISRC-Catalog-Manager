"""Core models for template-driven conversion workflows."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

REQUIRED_STATUS_REQUIRED = "required"
REQUIRED_STATUS_OPTIONAL = "optional"
REQUIRED_STATUS_UNKNOWN = "unknown"

MAPPING_KIND_SOURCE = "source_field"
MAPPING_KIND_CONSTANT = "constant_value"
MAPPING_KIND_UNMAPPED = "unmapped"
MAPPING_KIND_SKIP = "skip_field"

TRANSFORM_IDENTITY = "identity"
TRANSFORM_DURATION_SECONDS_TO_HMS = "duration_seconds_to_hms"
TRANSFORM_DATE_TO_YEAR = "date_to_year"
TRANSFORM_BOOL_TO_YES_NO = "bool_to_yes_no"
TRANSFORM_COMMA_JOIN = "comma_join"

SOURCE_MODE_FILE = "file"
SOURCE_MODE_DATABASE_TRACKS = "database_tracks"


@dataclass(slots=True)
class ConversionTargetField:
    field_key: str
    display_name: str
    location: str
    required_status: str
    kind: str = "field"
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class ConversionTemplateProfile:
    template_path: Path
    format_name: str
    output_suffix: str
    structure_label: str
    target_fields: tuple[ConversionTargetField, ...]
    template_signature: str
    template_bytes: bytes | None = None
    available_scopes: tuple[tuple[str, str], ...] = ()
    chosen_scope: str = ""
    warnings: tuple[str, ...] = ()
    adapter_state: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class ConversionSourceProfile:
    source_mode: str
    format_name: str
    source_label: str
    headers: tuple[str, ...]
    rows: tuple[dict[str, object], ...]
    preview_rows: tuple[dict[str, object], ...]
    source_path: str = ""
    available_scopes: tuple[tuple[str, str], ...] = ()
    chosen_scope: str = ""
    warnings: tuple[str, ...] = ()
    adapter_state: dict[str, object] = field(default_factory=dict)
    resolved_delimiter: str = ""


@dataclass(slots=True)
class ConversionMappingEntry:
    target_field_key: str
    target_display_name: str
    mapping_kind: str = MAPPING_KIND_UNMAPPED
    source_field: str = ""
    constant_value: str = ""
    transform_name: str = TRANSFORM_IDENTITY
    status: str = "unmapped"
    origin: str = "manual"
    sample_value: str = ""
    message: str = ""


@dataclass(slots=True)
class ConversionSession:
    template_profile: ConversionTemplateProfile
    source_profile: ConversionSourceProfile
    mapping_entries: tuple[ConversionMappingEntry, ...]
    included_row_indices: tuple[int, ...]
    warnings: tuple[str, ...] = ()


@dataclass(slots=True)
class ConversionPreview:
    template_profile: ConversionTemplateProfile
    source_profile: ConversionSourceProfile
    mapping_entries: tuple[ConversionMappingEntry, ...]
    included_row_indices: tuple[int, ...]
    rendered_headers: tuple[str, ...] = ()
    rendered_rows: tuple[tuple[str, ...], ...] = ()
    rendered_field_rows: tuple[dict[str, object], ...] = ()
    rendered_xml_text: str = ""
    warnings: tuple[str, ...] = ()
    blocking_issues: tuple[str, ...] = ()
    adapter_state: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class ConversionExportResult:
    output_path: Path
    target_format: str
    exported_row_count: int
    summary_lines: tuple[str, ...] = ()


@dataclass(slots=True)
class SavedConversionTemplateRecord:
    id: int
    name: str
    filename: str
    format_name: str
    source_path: str = ""
    chosen_scope: str = ""
    source_mode: str = ""
    mapping_payload: str = ""
    size_bytes: int = 0
    created_at: str | None = None
    updated_at: str | None = None
    template_bytes: bytes | None = None

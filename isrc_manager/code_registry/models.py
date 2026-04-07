"""Authoritative internal code-registry data models."""

from __future__ import annotations

from dataclasses import asdict, dataclass

SUBJECT_KIND_CATALOG = "catalog"
SUBJECT_KIND_CONTRACT = "contract"
SUBJECT_KIND_LICENSE = "license"
SUBJECT_KIND_KEY = "key"
SUBJECT_KIND_GENERIC = "generic"

GENERATION_STRATEGY_SEQUENTIAL = "sequential"
GENERATION_STRATEGY_SHA256 = "sha256"
GENERATION_STRATEGY_MANUAL = "manual"

ENTRY_KIND_GENERATED = "generated"
ENTRY_KIND_IMPORTED = "imported"
ENTRY_KIND_MANUAL_CAPTURE = "manual_capture"
ENTRY_KIND_SHA256_GENERATED = "sha256_generated"

CATALOG_MODE_INTERNAL = "internal"
CATALOG_MODE_EXTERNAL = "external"
CATALOG_MODE_EMPTY = "empty"

CLASSIFICATION_INTERNAL = "internal"
CLASSIFICATION_EXTERNAL = "external"
CLASSIFICATION_MISMATCH = "mismatch"
CLASSIFICATION_CANONICAL_CANDIDATE = "canonical_candidate"

BUILTIN_CATEGORY_CATALOG_NUMBER = "catalog_number"
BUILTIN_CATEGORY_CONTRACT_NUMBER = "contract_number"
BUILTIN_CATEGORY_LICENSE_NUMBER = "license_number"
BUILTIN_CATEGORY_REGISTRY_SHA256_KEY = "registry_sha256_key"


@dataclass(slots=True)
class CodeRegistryCategoryRecord:
    id: int
    system_key: str | None
    display_name: str
    subject_kind: str
    generation_strategy: str
    prefix: str | None
    normalized_prefix: str | None
    active_flag: bool
    sort_order: int
    is_system: bool
    created_at: str | None
    updated_at: str | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class CodeRegistryEntryRecord:
    id: int
    category_id: int
    category_system_key: str | None
    category_display_name: str
    subject_kind: str
    generation_strategy: str
    value: str
    normalized_value: str
    entry_kind: str
    prefix_snapshot: str | None
    sequence_year: int | None
    sequence_number: int | None
    immutable_flag: bool
    created_at: str | None
    created_via: str | None
    notes: str | None
    usage_count: int = 0

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class ExternalCatalogIdentifierRecord:
    id: int
    subject_kind: str
    subject_id: int
    value: str
    normalized_value: str
    provenance_kind: str
    classification_status: str
    classification_reason: str | None
    source_label: str | None
    created_at: str | None
    updated_at: str | None
    usage_count: int = 0
    linked_flag: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class CodeRegistryUsageLink:
    subject_kind: str
    subject_id: int
    label: str
    field_name: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class CodeRegistryAssignmentTarget:
    owner_kind: str
    owner_id: int
    label: str
    detail: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class CodeRegistryChoice:
    entry_id: int
    category_id: int
    category_label: str
    value: str
    label: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class CatalogIdentifierResolution:
    mode: str
    value: str | None = None
    registry_entry_id: int | None = None
    category_id: int | None = None
    external_value: str | None = None
    classification_status: str | None = None
    classification_reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class CatalogIdentifierClassification:
    input_value: str
    normalized_value: str
    classification: str
    category_id: int | None = None
    category_system_key: str | None = None
    category_display_name: str | None = None
    canonical_value: str | None = None
    matched_prefix: str | None = None
    sequence_year: int | None = None
    sequence_number: int | None = None
    existing_entry_id: int | None = None
    reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class CodeRegistryCategoryPayload:
    display_name: str
    subject_kind: str
    generation_strategy: str
    prefix: str | None = None
    active_flag: bool = True
    sort_order: int = 0


@dataclass(slots=True)
class CodeRegistryEntryGenerationResult:
    entry: CodeRegistryEntryRecord
    category: CodeRegistryCategoryRecord

    def to_dict(self) -> dict[str, object]:
        return {
            "entry": self.entry.to_dict(),
            "category": self.category.to_dict(),
        }

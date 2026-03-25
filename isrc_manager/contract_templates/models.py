"""Dataclasses for contract template placeholder workflow storage."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(slots=True)
class ContractTemplatePayload:
    name: str
    description: str | None = None
    template_family: str = "contract"
    source_format: str | None = None


@dataclass(slots=True)
class ContractTemplateRecord:
    template_id: int
    name: str
    description: str | None
    template_family: str
    source_format: str | None
    active_revision_id: int | None
    archived: bool
    created_at: str | None
    updated_at: str | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class ContractTemplateRevisionPayload:
    revision_label: str | None = None
    source_filename: str | None = None
    source_mime_type: str | None = None
    source_format: str = "docx"
    source_path: str | None = None
    storage_mode: str | None = None
    scan_status: str = "scan_pending"
    scan_error: str | None = None


@dataclass(slots=True)
class ContractTemplateRevisionRecord:
    revision_id: int
    template_id: int
    revision_label: str | None
    source_filename: str
    source_mime_type: str | None
    source_format: str
    source_path: str | None
    managed_file_path: str | None
    storage_mode: str | None
    source_checksum_sha256: str | None
    size_bytes: int
    scan_status: str
    scan_error: str | None
    placeholder_inventory_hash: str | None
    placeholder_count: int
    created_at: str | None
    updated_at: str | None
    stored_in_database: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class ContractTemplatePlaceholderPayload:
    canonical_symbol: str
    display_label: str | None = None
    inferred_field_type: str | None = None
    required: bool = True
    source_occurrence_count: int = 1
    metadata: object | None = None


@dataclass(slots=True)
class ContractTemplatePlaceholderRecord:
    placeholder_id: int
    revision_id: int
    canonical_symbol: str
    binding_kind: str
    namespace: str | None
    placeholder_key: str
    display_label: str | None
    inferred_field_type: str | None
    required: bool
    source_occurrence_count: int
    metadata: object | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class ContractTemplatePlaceholderBindingPayload:
    canonical_symbol: str
    resolver_kind: str | None = None
    resolver_target: str | None = None
    scope_entity_type: str | None = None
    scope_policy: str | None = None
    widget_hint: str | None = None
    validation: object | None = None
    metadata: object | None = None


@dataclass(slots=True)
class ContractTemplatePlaceholderBindingRecord:
    binding_id: int
    revision_id: int
    placeholder_id: int
    canonical_symbol: str
    resolver_kind: str
    resolver_target: str | None
    scope_entity_type: str | None
    scope_policy: str | None
    widget_hint: str | None
    validation: object | None
    metadata: object | None
    created_at: str | None
    updated_at: str | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class ContractTemplateDraftPayload:
    revision_id: int
    name: str
    editable_payload: object | None = None
    status: str = "draft"
    scope_entity_type: str | None = None
    scope_entity_id: str | None = None
    storage_mode: str | None = None
    filename: str | None = None
    mime_type: str = "application/json"
    last_resolved_snapshot_id: int | None = None


@dataclass(slots=True)
class ContractTemplateDraftRecord:
    draft_id: int
    revision_id: int
    name: str
    status: str
    scope_entity_type: str | None
    scope_entity_id: str | None
    managed_file_path: str | None
    storage_mode: str | None
    filename: str | None
    mime_type: str | None
    size_bytes: int
    last_resolved_snapshot_id: int | None
    created_at: str | None
    updated_at: str | None
    stored_in_database: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class ContractTemplateResolvedSnapshotPayload:
    draft_id: int
    revision_id: int
    resolved_values: object
    resolution_warnings: object | None = None
    preview_payload: object | None = None
    scope_entity_type: str | None = None
    scope_entity_id: str | None = None
    resolved_checksum_sha256: str | None = None


@dataclass(slots=True)
class ContractTemplateResolvedSnapshotRecord:
    snapshot_id: int
    draft_id: int
    revision_id: int
    scope_entity_type: str | None
    scope_entity_id: str | None
    resolved_values: object
    resolution_warnings: object | None
    preview_payload: object | None
    resolved_checksum_sha256: str | None
    created_at: str | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class ContractTemplateOutputArtifactPayload:
    snapshot_id: int
    artifact_type: str
    output_path: str
    output_filename: str | None = None
    mime_type: str | None = None
    size_bytes: int = 0
    checksum_sha256: str | None = None
    retained: bool = True
    status: str = "generated"


@dataclass(slots=True)
class ContractTemplateOutputArtifactRecord:
    artifact_id: int
    snapshot_id: int
    artifact_type: str
    status: str
    output_path: str
    output_filename: str
    mime_type: str | None
    size_bytes: int
    checksum_sha256: str | None
    retained: bool
    created_at: str | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

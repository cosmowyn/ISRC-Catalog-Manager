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
    source_root_path: str | None = None
    source_tree_mode: str | None = None
    storage_mode: str | None = None
    scan_status: str = "scan_pending"
    scan_error: str | None = None
    scan_adapter: str | None = None
    scan_diagnostics: object | None = None


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
    scan_adapter: str | None
    scan_diagnostics: object | None
    placeholder_inventory_hash: str | None
    placeholder_count: int
    created_at: str | None
    updated_at: str | None
    stored_in_database: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class ContractTemplateRevisionAssetPayload:
    package_rel_path: str
    managed_file_path: str
    source_filename: str | None = None
    mime_type: str | None = None
    size_bytes: int = 0
    checksum_sha256: str | None = None
    asset_role: str = "asset"


@dataclass(slots=True)
class ContractTemplateRevisionAssetRecord:
    asset_id: int
    revision_id: int
    package_rel_path: str
    managed_file_path: str
    source_filename: str
    mime_type: str | None
    size_bytes: int
    checksum_sha256: str | None
    asset_role: str
    created_at: str | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class ContractTemplateScanDiagnostic:
    severity: str
    code: str
    message: str
    source_part: str | None = None
    location_hint: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class ContractTemplateScanOccurrence:
    source_part: str
    container_kind: str
    container_index: int
    start_index: int
    end_index: int
    raw_text: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class ContractTemplateScanEntry:
    canonical_symbol: str
    binding_kind: str
    namespace: str | None
    key: str
    occurrence_count: int
    occurrences: tuple[ContractTemplateScanOccurrence, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "canonical_symbol": self.canonical_symbol,
            "binding_kind": self.binding_kind,
            "namespace": self.namespace,
            "key": self.key,
            "occurrence_count": self.occurrence_count,
            "occurrences": [item.to_dict() for item in self.occurrences],
        }


@dataclass(slots=True)
class ContractTemplateScanResult:
    source_format: str
    scan_format: str
    scan_status: str
    scan_adapter: str | None
    placeholders: tuple[ContractTemplateScanEntry, ...]
    diagnostics: tuple[ContractTemplateScanDiagnostic, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "source_format": self.source_format,
            "scan_format": self.scan_format,
            "scan_status": self.scan_status,
            "scan_adapter": self.scan_adapter,
            "placeholders": [item.to_dict() for item in self.placeholders],
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }


@dataclass(slots=True)
class ContractTemplateImportResult:
    revision: ContractTemplateRevisionRecord
    scan_result: ContractTemplateScanResult

    def to_dict(self) -> dict[str, object]:
        return {
            "revision": self.revision.to_dict(),
            "scan_result": self.scan_result.to_dict(),
        }


def _clean_scope_value(value: str | None) -> str | None:
    clean = str(value or "").strip().lower()
    return clean or None


def build_contract_template_selector_scope_key(
    scope_entity_type: str | None,
    scope_policy: str | None,
) -> str | None:
    clean_entity_type = _clean_scope_value(scope_entity_type)
    if clean_entity_type is None:
        return None
    clean_scope_policy = _clean_scope_value(scope_policy) or "selection_required"
    return f"db_scope.{clean_entity_type}.{clean_scope_policy}"


@dataclass(slots=True)
class ContractTemplateCatalogEntry:
    binding_kind: str
    namespace: str | None
    key: str
    canonical_symbol: str
    display_label: str
    field_type: str
    description: str | None
    scope_entity_type: str | None
    scope_policy: str | None
    source_table: str | None
    source_column: str | None
    options: tuple[str, ...] = ()
    custom_field_id: int | None = None
    is_custom_field: bool = False
    is_settings_field: bool = False

    @property
    def label(self) -> str:
        return self.display_label

    @property
    def source_kind(self) -> str:
        if self.is_custom_field:
            return "Custom Field"
        if self.is_settings_field:
            if str(self.namespace or "").strip().lower() == "owner":
                return "Owner Party"
            return "Application Settings"
        return "Database Field"

    def to_dict(self) -> dict[str, object]:
        return {
            "binding_kind": self.binding_kind,
            "namespace": self.namespace,
            "key": self.key,
            "canonical_symbol": self.canonical_symbol,
            "display_label": self.display_label,
            "field_type": self.field_type,
            "description": self.description,
            "scope_entity_type": self.scope_entity_type,
            "scope_policy": self.scope_policy,
            "source_table": self.source_table,
            "source_column": self.source_column,
            "options": list(self.options),
            "custom_field_id": self.custom_field_id,
            "is_custom_field": self.is_custom_field,
            "is_settings_field": self.is_settings_field,
        }


@dataclass(slots=True)
class ContractTemplateFormChoice:
    value: str
    label: str
    description: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class ContractTemplateFormSelectorField:
    selector_key: str
    display_label: str
    scope_entity_type: str
    scope_policy: str | None
    widget_kind: str
    required: bool
    placeholder_symbols: tuple[str, ...]
    choices: tuple[ContractTemplateFormChoice, ...] = ()
    description: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "selector_key": self.selector_key,
            "display_label": self.display_label,
            "scope_entity_type": self.scope_entity_type,
            "scope_policy": self.scope_policy,
            "widget_kind": self.widget_kind,
            "required": self.required,
            "placeholder_symbols": list(self.placeholder_symbols),
            "choices": [item.to_dict() for item in self.choices],
            "description": self.description,
        }


@dataclass(slots=True)
class ContractTemplateFormAutoField:
    canonical_symbol: str
    display_label: str
    source_label: str
    required: bool
    placeholder_count: int
    description: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "canonical_symbol": self.canonical_symbol,
            "display_label": self.display_label,
            "source_label": self.source_label,
            "required": self.required,
            "placeholder_count": self.placeholder_count,
            "description": self.description,
        }


@dataclass(slots=True)
class ContractTemplateFormManualField:
    canonical_symbol: str
    display_label: str
    field_type: str
    widget_kind: str
    required: bool
    placeholder_count: int
    description: str | None = None
    options: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "canonical_symbol": self.canonical_symbol,
            "display_label": self.display_label,
            "field_type": self.field_type,
            "widget_kind": self.widget_kind,
            "required": self.required,
            "placeholder_count": self.placeholder_count,
            "description": self.description,
            "options": list(self.options),
        }


@dataclass(slots=True)
class ContractTemplateFormDefinition:
    template_id: int
    revision_id: int
    template_name: str
    revision_label: str | None
    scan_status: str
    auto_fields: tuple[ContractTemplateFormAutoField, ...]
    selector_fields: tuple[ContractTemplateFormSelectorField, ...]
    manual_fields: tuple[ContractTemplateFormManualField, ...]
    unresolved_placeholders: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "template_id": self.template_id,
            "revision_id": self.revision_id,
            "template_name": self.template_name,
            "revision_label": self.revision_label,
            "scan_status": self.scan_status,
            "auto_fields": [item.to_dict() for item in self.auto_fields],
            "selector_fields": [item.to_dict() for item in self.selector_fields],
            "manual_fields": [item.to_dict() for item in self.manual_fields],
            "unresolved_placeholders": list(self.unresolved_placeholders),
            "warnings": list(self.warnings),
        }


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
    working_file_path: str | None
    working_filename: str | None
    working_mime_type: str | None
    working_size_bytes: int
    working_checksum_sha256: str | None
    last_resolved_snapshot_id: int | None
    created_at: str | None
    updated_at: str | None
    stored_in_database: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class ContractTemplateDraftRegistryAssignmentRecord:
    assignment_id: int
    draft_id: int
    canonical_symbol: str
    system_key: str
    owner_kind: str
    registry_entry_id: int
    registry_value: str
    created_at: str | None
    updated_at: str | None

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


@dataclass(slots=True)
class ContractTemplateExportResult:
    snapshot: ContractTemplateResolvedSnapshotRecord
    resolved_docx_artifact: ContractTemplateOutputArtifactRecord | None
    resolved_html_artifact: ContractTemplateOutputArtifactRecord | None
    pdf_artifact: ContractTemplateOutputArtifactRecord
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "snapshot": self.snapshot.to_dict(),
            "resolved_docx_artifact": (
                self.resolved_docx_artifact.to_dict()
                if self.resolved_docx_artifact is not None
                else None
            ),
            "resolved_html_artifact": (
                self.resolved_html_artifact.to_dict()
                if self.resolved_html_artifact is not None
                else None
            ),
            "pdf_artifact": self.pdf_artifact.to_dict(),
            "warnings": list(self.warnings),
        }

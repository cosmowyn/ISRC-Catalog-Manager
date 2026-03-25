"""Dynamic fill-form synthesis for contract template workflows."""

from __future__ import annotations

import re

from .models import (
    ContractTemplateCatalogEntry,
    ContractTemplateFormChoice,
    ContractTemplateFormDefinition,
    ContractTemplateFormManualField,
    ContractTemplateFormSelectorField,
    ContractTemplatePlaceholderBindingPayload,
    ContractTemplatePlaceholderBindingRecord,
    ContractTemplatePlaceholderRecord,
)
from .parser import parse_placeholder


def _clean_text(value: object | None) -> str | None:
    clean = str(value or "").strip()
    return clean or None


def _display_label_from_key(key: str) -> str:
    return " ".join(part.capitalize() for part in str(key or "").split("_") if part)


class ContractTemplateFormService:
    """Builds Phase 4 fill-form definitions from persisted placeholder inventories."""

    _DATE_HINT_RE = re.compile(
        r"(^|_)(date|day|deadline|signed|effective|start|end|renewal|termination|reversion|notice)($|_)",
        re.IGNORECASE,
    )
    _NUMBER_HINT_RE = re.compile(
        r"(^|_)(amount|number|count|rate|fee|royalty|share|percent|percentage|days|weeks|months|years|hours|minutes|seconds)($|_)",
        re.IGNORECASE,
    )
    _BOOLEAN_HINT_RE = re.compile(
        r"(^|_)(is|has|allow|approved|exclusive|perpetual|verified|enabled|disabled|signed|waived|consent|consented|confirmed|confirm)($|_)",
        re.IGNORECASE,
    )
    _SELECTOR_LABELS = {
        "track": "Track Selection",
        "release": "Release Selection",
        "work": "Work Selection",
        "contract": "Contract Selection",
        "party": "Party Selection",
        "right": "Right Selection",
        "asset": "Asset Selection",
    }

    def __init__(
        self,
        *,
        template_service,
        catalog_service,
        release_service=None,
        work_service=None,
        contract_service=None,
        party_service=None,
        rights_service=None,
        asset_service=None,
    ):
        self.template_service = template_service
        self.catalog_service = catalog_service
        self.release_service = release_service
        self.work_service = work_service
        self.contract_service = contract_service
        self.party_service = party_service
        self.rights_service = rights_service
        self.asset_service = asset_service

    def synchronize_bindings(
        self, revision_id: int
    ) -> list[ContractTemplatePlaceholderBindingRecord]:
        placeholders = self.template_service.list_placeholders(revision_id)
        existing = {
            item.canonical_symbol: item
            for item in self.template_service.list_placeholder_bindings(revision_id)
        }
        catalog = {
            item.canonical_symbol: item
            for item in self.catalog_service.list_known_symbols()
        }
        bindings = [
            self._merged_binding_payload(
                placeholder,
                catalog_entry=catalog.get(placeholder.canonical_symbol),
                current=existing.get(placeholder.canonical_symbol),
            )
            for placeholder in placeholders
        ]
        return self.template_service.replace_placeholder_bindings(
            revision_id, bindings=bindings
        )

    def build_form_definition(self, revision_id: int) -> ContractTemplateFormDefinition:
        revision = self.template_service.fetch_revision(revision_id)
        if revision is None:
            raise ValueError(f"Contract template revision {revision_id} not found")
        template = self.template_service.fetch_template(revision.template_id)
        if template is None:
            raise ValueError(f"Contract template {revision.template_id} not found")

        placeholders = self.template_service.list_placeholders(revision_id)
        bindings = {
            item.canonical_symbol: item
            for item in self.synchronize_bindings(revision_id)
        }
        catalog = {
            item.canonical_symbol: item
            for item in self.catalog_service.list_known_symbols()
        }

        selector_fields: list[ContractTemplateFormSelectorField] = []
        manual_fields: list[ContractTemplateFormManualField] = []
        unresolved: list[str] = []
        warnings: list[str] = []

        for placeholder in placeholders:
            token = parse_placeholder(placeholder.canonical_symbol)
            binding = bindings.get(placeholder.canonical_symbol)
            if token.binding_kind == "db":
                catalog_entry = catalog.get(placeholder.canonical_symbol)
                selector_field = self._selector_field(
                    placeholder,
                    binding=binding,
                    catalog_entry=catalog_entry,
                )
                if selector_field is None:
                    unresolved.append(placeholder.canonical_symbol)
                    warnings.append(
                        f"No selector mapping could be derived for {placeholder.canonical_symbol}."
                    )
                    continue
                if not selector_field.choices:
                    warnings.append(
                        f"{selector_field.display_label} has no selectable records yet."
                    )
                selector_fields.append(selector_field)
                continue
            manual_fields.append(
                self._manual_field(
                    placeholder,
                    binding=binding,
                )
            )

        return ContractTemplateFormDefinition(
            template_id=template.template_id,
            revision_id=revision.revision_id,
            template_name=template.name,
            revision_label=revision.revision_label,
            scan_status=revision.scan_status,
            selector_fields=tuple(selector_fields),
            manual_fields=tuple(manual_fields),
            unresolved_placeholders=tuple(sorted(unresolved)),
            warnings=tuple(warnings),
        )

    def build_editable_payload(
        self,
        revision_id: int,
        *,
        db_selections: dict[str, object] | None = None,
        manual_values: dict[str, object] | None = None,
        type_overrides: dict[str, str] | None = None,
    ) -> dict[str, object]:
        return {
            "revision_id": int(revision_id),
            "db_selections": dict(db_selections or {}),
            "manual_values": dict(manual_values or {}),
            "type_overrides": dict(type_overrides or {}),
        }

    def _merged_binding_payload(
        self,
        placeholder: ContractTemplatePlaceholderRecord,
        *,
        catalog_entry: ContractTemplateCatalogEntry | None,
        current: ContractTemplatePlaceholderBindingRecord | None,
    ) -> ContractTemplatePlaceholderBindingPayload:
        token = parse_placeholder(placeholder.canonical_symbol)
        if token.binding_kind == "db":
            derived = self._db_binding_payload(
                placeholder,
                catalog_entry=catalog_entry,
            )
        else:
            derived = self._manual_binding_payload(placeholder)
        if current is None:
            return derived
        return ContractTemplatePlaceholderBindingPayload(
            canonical_symbol=derived.canonical_symbol,
            resolver_kind=_clean_text(current.resolver_kind) or derived.resolver_kind,
            resolver_target=current.resolver_target or derived.resolver_target,
            scope_entity_type=current.scope_entity_type or derived.scope_entity_type,
            scope_policy=current.scope_policy or derived.scope_policy,
            widget_hint=current.widget_hint or derived.widget_hint,
            validation=current.validation
            if current.validation is not None
            else derived.validation,
            metadata=current.metadata if current.metadata is not None else derived.metadata,
        )

    def _db_binding_payload(
        self,
        placeholder: ContractTemplatePlaceholderRecord,
        *,
        catalog_entry: ContractTemplateCatalogEntry | None,
    ) -> ContractTemplatePlaceholderBindingPayload:
        token = parse_placeholder(placeholder.canonical_symbol)
        scope_entity_type = None
        scope_policy = None
        field_type = placeholder.inferred_field_type or "text"
        options: tuple[str, ...] = ()
        widget_hint = "entity_selector"
        metadata: dict[str, object] = {}
        if catalog_entry is not None:
            scope_entity_type = catalog_entry.scope_entity_type
            scope_policy = catalog_entry.scope_policy
            field_type = catalog_entry.field_type or field_type
            options = tuple(catalog_entry.options)
            widget_hint = self._selector_widget_hint(
                catalog_entry.scope_entity_type or token.namespace
            )
            metadata = {
                "catalog_label": catalog_entry.display_label,
                "source_table": catalog_entry.source_table,
                "source_column": catalog_entry.source_column,
                "is_custom_field": catalog_entry.is_custom_field,
                "custom_field_id": catalog_entry.custom_field_id,
            }
        if scope_entity_type is None:
            scope_entity_type = self._default_scope_entity_type(token.namespace)
        if scope_policy is None:
            scope_policy = self._default_scope_policy(token.namespace)
        validation = {"field_type": field_type}
        if options:
            validation["options"] = list(options)
        if not metadata:
            metadata = {"catalog_missing": True}
        return ContractTemplatePlaceholderBindingPayload(
            canonical_symbol=placeholder.canonical_symbol,
            resolver_kind="db",
            resolver_target=placeholder.canonical_symbol,
            scope_entity_type=scope_entity_type,
            scope_policy=scope_policy,
            widget_hint=widget_hint,
            validation=validation,
            metadata=metadata,
        )

    def _manual_binding_payload(
        self, placeholder: ContractTemplatePlaceholderRecord
    ) -> ContractTemplatePlaceholderBindingPayload:
        field_type, widget_hint = self._manual_field_type(
            placeholder.placeholder_key,
            placeholder.inferred_field_type,
        )
        validation: dict[str, object] = {"field_type": field_type}
        if field_type == "boolean":
            validation["options"] = ["false", "true"]
        return ContractTemplatePlaceholderBindingPayload(
            canonical_symbol=placeholder.canonical_symbol,
            resolver_kind="manual",
            resolver_target=placeholder.canonical_symbol,
            scope_entity_type=None,
            scope_policy="manual_entry",
            widget_hint=widget_hint,
            validation=validation,
            metadata={"display_label": placeholder.display_label},
        )

    def _selector_field(
        self,
        placeholder: ContractTemplatePlaceholderRecord,
        *,
        binding: ContractTemplatePlaceholderBindingRecord | None,
        catalog_entry: ContractTemplateCatalogEntry | None,
    ) -> ContractTemplateFormSelectorField | None:
        token = parse_placeholder(placeholder.canonical_symbol)
        scope_entity_type = (
            _clean_text(binding.scope_entity_type) if binding is not None else None
        ) or self._default_scope_entity_type(token.namespace)
        if scope_entity_type is None:
            return None
        choices = self._choices_for_entity_type(scope_entity_type)
        label = (
            placeholder.display_label
            or (catalog_entry.display_label if catalog_entry is not None else None)
            or _display_label_from_key(placeholder.placeholder_key)
        )
        description = (
            catalog_entry.description if catalog_entry is not None else None
        ) or f"Select the authoritative {scope_entity_type} record for {label}."
        return ContractTemplateFormSelectorField(
            selector_key=placeholder.canonical_symbol,
            display_label=label,
            scope_entity_type=scope_entity_type,
            scope_policy=(
                (_clean_text(binding.scope_policy) if binding is not None else None)
                or self._default_scope_policy(token.namespace)
            ),
            widget_kind=(
                _clean_text(binding.widget_hint) if binding is not None else None
            )
            or self._selector_widget_hint(scope_entity_type),
            required=placeholder.required,
            placeholder_symbols=(placeholder.canonical_symbol,),
            choices=choices,
            description=description,
        )

    def _manual_field(
        self,
        placeholder: ContractTemplatePlaceholderRecord,
        *,
        binding: ContractTemplatePlaceholderBindingRecord | None,
    ) -> ContractTemplateFormManualField:
        field_type, widget_hint = self._manual_field_type(
            placeholder.placeholder_key,
            placeholder.inferred_field_type,
        )
        options: tuple[str, ...] = ()
        if binding is not None and isinstance(binding.validation, dict):
            field_type = (
                _clean_text(binding.validation.get("field_type")) or field_type
            )
            if binding.validation.get("options"):
                options = tuple(str(item) for item in binding.validation["options"])
        if binding is not None and binding.widget_hint:
            widget_hint = binding.widget_hint
        return ContractTemplateFormManualField(
            canonical_symbol=placeholder.canonical_symbol,
            display_label=placeholder.display_label
            or _display_label_from_key(placeholder.placeholder_key),
            field_type=field_type,
            widget_kind=widget_hint,
            required=placeholder.required,
            placeholder_count=placeholder.source_occurrence_count,
            description=f"Manual value for {placeholder.canonical_symbol}.",
            options=options,
        )

    def _manual_field_type(
        self,
        placeholder_key: str,
        inferred_field_type: str | None,
    ) -> tuple[str, str]:
        clean_inferred = _clean_text(inferred_field_type)
        if clean_inferred:
            normalized = clean_inferred.lower()
            if normalized in {"date"}:
                return "date", "date_input"
            if normalized in {"int", "integer", "number", "float", "decimal"}:
                return "number", "number_input"
            if normalized in {"checkbox", "bool", "boolean"}:
                return "boolean", "checkbox"
        clean_key = str(placeholder_key or "").strip().lower()
        if self._DATE_HINT_RE.search(clean_key):
            return "date", "date_input"
        if clean_key.startswith("is_") or clean_key.startswith("has_"):
            return "boolean", "checkbox"
        if self._BOOLEAN_HINT_RE.search(clean_key):
            return "boolean", "checkbox"
        if self._NUMBER_HINT_RE.search(clean_key):
            return "number", "number_input"
        return "text", "text_input"

    @staticmethod
    def _selector_widget_hint(scope_entity_type: str | None) -> str:
        clean_scope = str(scope_entity_type or "").strip().lower()
        if not clean_scope:
            return "entity_selector"
        return f"{clean_scope}_selector"

    @staticmethod
    def _default_scope_entity_type(namespace: str | None) -> str | None:
        mapping = {
            "track": "track",
            "release": "release",
            "work": "work",
            "contract": "contract",
            "party": "party",
            "right": "right",
            "asset": "asset",
            "custom": "track",
        }
        return mapping.get(str(namespace or "").strip().lower())

    @staticmethod
    def _default_scope_policy(namespace: str | None) -> str | None:
        mapping = {
            "track": "track_context",
            "release": "release_selection_required",
            "work": "work_selection_required",
            "contract": "contract_selection_required",
            "party": "party_selection_required",
            "right": "right_selection_required",
            "asset": "asset_selection_required",
            "custom": "track_context",
        }
        return mapping.get(str(namespace or "").strip().lower())

    def _choices_for_entity_type(
        self, entity_type: str
    ) -> tuple[ContractTemplateFormChoice, ...]:
        clean_type = str(entity_type or "").strip().lower()
        if clean_type == "track":
            return self._track_choices()
        if clean_type == "release":
            return self._release_choices()
        if clean_type == "work":
            return self._work_choices()
        if clean_type == "contract":
            return self._contract_choices()
        if clean_type == "party":
            return self._party_choices()
        if clean_type == "right":
            return self._right_choices()
        if clean_type == "asset":
            return self._asset_choices()
        return ()

    def _track_choices(self) -> tuple[ContractTemplateFormChoice, ...]:
        rows = self.template_service.conn.execute(
            """
            SELECT id, track_title
            FROM Tracks
            ORDER BY track_title COLLATE NOCASE, id
            """
        ).fetchall()
        return tuple(
            ContractTemplateFormChoice(
                value=str(int(row[0])),
                label=f"{str(row[1] or '').strip() or 'Untitled Track'} (#{int(row[0])})",
            )
            for row in rows
        )

    def _release_choices(self) -> tuple[ContractTemplateFormChoice, ...]:
        if self.release_service is None:
            return ()
        return tuple(
            ContractTemplateFormChoice(
                value=str(int(item.id)),
                label=self._release_label(item),
            )
            for item in self.release_service.list_releases()
        )

    def _work_choices(self) -> tuple[ContractTemplateFormChoice, ...]:
        if self.work_service is None:
            return ()
        return tuple(
            ContractTemplateFormChoice(
                value=str(int(item.id)),
                label=self._work_label(item),
            )
            for item in self.work_service.list_works()
        )

    def _contract_choices(self) -> tuple[ContractTemplateFormChoice, ...]:
        if self.contract_service is None:
            return ()
        return tuple(
            ContractTemplateFormChoice(
                value=str(int(item.id)),
                label=self._contract_label(item),
            )
            for item in self.contract_service.list_contracts()
        )

    def _party_choices(self) -> tuple[ContractTemplateFormChoice, ...]:
        if self.party_service is None:
            return ()
        return tuple(
            ContractTemplateFormChoice(
                value=str(int(item.id)),
                label=self._party_label(item),
            )
            for item in self.party_service.list_parties()
        )

    def _right_choices(self) -> tuple[ContractTemplateFormChoice, ...]:
        if self.rights_service is None:
            return ()
        return tuple(
            ContractTemplateFormChoice(
                value=str(int(item.id)),
                label=self._right_label(item),
            )
            for item in self.rights_service.list_rights()
        )

    def _asset_choices(self) -> tuple[ContractTemplateFormChoice, ...]:
        if self.asset_service is None:
            return ()
        return tuple(
            ContractTemplateFormChoice(
                value=str(int(item.id)),
                label=self._asset_label(item),
            )
            for item in self.asset_service.list_assets()
        )

    @staticmethod
    def _release_label(item) -> str:
        artist = _clean_text(getattr(item, "primary_artist", None)) or _clean_text(
            getattr(item, "album_artist", None)
        )
        if artist:
            return f"{item.title} - {artist}"
        return str(item.title or f"Release #{int(item.id)}")

    @staticmethod
    def _work_label(item) -> str:
        iswc = _clean_text(getattr(item, "iswc", None))
        if iswc:
            return f"{item.title} ({iswc})"
        return str(item.title or f"Work #{int(item.id)}")

    @staticmethod
    def _contract_label(item) -> str:
        status = _clean_text(getattr(item, "status", None))
        if status:
            return f"{item.title} [{status}]"
        return str(item.title or f"Contract #{int(item.id)}")

    @staticmethod
    def _party_label(item) -> str:
        name = _clean_text(getattr(item, "display_name", None)) or _clean_text(
            getattr(item, "legal_name", None)
        )
        party_type = _clean_text(getattr(item, "party_type", None))
        if party_type and name:
            return f"{name} ({party_type})"
        return name or f"Party #{int(item.id)}"

    @staticmethod
    def _right_label(item) -> str:
        title = _clean_text(getattr(item, "title", None)) or _clean_text(
            getattr(item, "right_type", None)
        )
        territory = _clean_text(getattr(item, "territory", None))
        if title and territory:
            return f"{title} [{territory}]"
        return title or f"Right #{int(item.id)}"

    @staticmethod
    def _asset_label(item) -> str:
        filename = _clean_text(getattr(item, "filename", None))
        asset_type = _clean_text(getattr(item, "asset_type", None))
        if filename and asset_type:
            return f"{filename} ({asset_type})"
        return filename or asset_type or f"Asset #{int(item.id)}"

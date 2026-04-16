"""Service orchestration for template conversion workflows."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from .adapters import (
    CsvSourceAdapter,
    CsvTemplateAdapter,
    DatabaseTrackSourceAdapter,
    XlsxSourceAdapter,
    XlsxTemplateAdapter,
    XmlSourceAdapter,
    XmlTemplateAdapter,
)
from .mapping import (
    resolve_mapping_value,
    stringify_value,
    suggest_mapping_entries,
    update_entry_sample,
)
from .models import (
    MAPPING_KIND_SKIP,
    MAPPING_KIND_UNMAPPED,
    REQUIRED_STATUS_REQUIRED,
    SOURCE_MODE_DATABASE_TRACKS,
    ConversionMappingEntry,
    ConversionPreview,
    ConversionSession,
    ConversionSourceProfile,
    ConversionTemplateProfile,
)


class ConversionService:
    """Inspects templates and sources, then builds faithful conversion previews."""

    def __init__(self, *, exchange_service=None, settings_read_service=None):
        self.exchange_service = exchange_service
        self.settings_read_service = settings_read_service
        self._template_adapters = {
            "csv": CsvTemplateAdapter(),
            "xlsx": XlsxTemplateAdapter(),
            "xml": XmlTemplateAdapter(),
        }
        self._source_adapters = {
            "csv": CsvSourceAdapter(),
            "xlsx": XlsxSourceAdapter(),
            "xml": XmlSourceAdapter(),
            "json": self,
            SOURCE_MODE_DATABASE_TRACKS: DatabaseTrackSourceAdapter(
                exchange_service,
                settings_read_service=settings_read_service,
            ),
        }

    def inspect_template(self, path) -> ConversionTemplateProfile:
        clean_path = Path(path)
        adapter = self._template_adapter_for_path(clean_path)
        return adapter.inspect_template(clean_path)

    def inspect_template_bytes(
        self,
        filename: str,
        template_bytes: bytes,
        *,
        source_label: str = "",
        source_path: str = "",
    ) -> ConversionTemplateProfile:
        clean_name = str(filename or "").strip() or "saved-template"
        suffix = Path(clean_name).suffix or ".template"
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
                handle.write(bytes(template_bytes))
                temp_path = Path(handle.name)
            profile = self.inspect_template(temp_path)
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except Exception:
                    pass
        profile.template_path = Path(clean_name)
        profile.template_bytes = bytes(template_bytes)
        if source_label:
            profile.adapter_state["source_label"] = str(source_label)
        if source_path:
            profile.adapter_state["source_path"] = str(source_path)
        return profile

    def select_template_scope(
        self,
        profile: ConversionTemplateProfile,
        scope_key: str,
    ) -> ConversionTemplateProfile:
        adapter = self._template_adapters.get(profile.format_name)
        if adapter is None:
            return profile
        return adapter.select_scope(profile, scope_key)

    def inspect_source_file(
        self,
        path,
        *,
        preferred_csv_delimiter: str | None = None,
    ) -> ConversionSourceProfile:
        clean_path = Path(path)
        format_name = self._normalized_format_name(clean_path)
        if format_name not in {"csv", "xlsx", "xml", "json"}:
            raise ValueError("Unsupported source file format. Use CSV, XLSX, XML, or JSON.")
        if format_name == "json":
            return self._inspect_json_source(clean_path)
        adapter = self._source_adapters[format_name]
        return adapter.inspect_source(
            clean_path,
            preferred_csv_delimiter=preferred_csv_delimiter,
        )

    def select_source_scope(
        self,
        profile: ConversionSourceProfile,
        scope_key: str,
    ) -> ConversionSourceProfile:
        adapter = self._source_adapters.get(profile.format_name)
        if adapter is None:
            return profile
        return adapter.select_scope(profile, scope_key)

    def inspect_database_tracks(self, track_ids) -> ConversionSourceProfile:
        adapter = self._source_adapters[SOURCE_MODE_DATABASE_TRACKS]
        return adapter.inspect_source(track_ids)

    def build_session(
        self,
        template_profile: ConversionTemplateProfile,
        source_profile: ConversionSourceProfile,
    ) -> ConversionSession:
        entries = tuple(
            ConversionMappingEntry(
                target_field_key=field.field_key,
                target_display_name=field.display_name,
            )
            for field in template_profile.target_fields
        )
        included_row_indices = tuple(range(len(source_profile.rows)))
        warnings = tuple(dict.fromkeys((*template_profile.warnings, *source_profile.warnings)))
        return ConversionSession(
            template_profile=template_profile,
            source_profile=source_profile,
            mapping_entries=entries,
            included_row_indices=included_row_indices,
            warnings=warnings,
        )

    def suggest_mapping(self, session: ConversionSession) -> dict[str, ConversionMappingEntry]:
        return suggest_mapping_entries(session)

    def build_preview(self, session: ConversionSession) -> ConversionPreview:
        template_profile = session.template_profile
        source_profile = session.source_profile
        included_row_indices = tuple(
            index
            for index in session.included_row_indices
            if 0 <= int(index) < len(source_profile.rows)
        )
        source_rows = tuple(source_profile.rows[index] for index in included_row_indices)
        entry_by_key = {entry.target_field_key: entry for entry in session.mapping_entries}
        updated_entries: list[ConversionMappingEntry] = []
        rendered_field_rows: list[dict[str, object]] = []
        blocking_issues: list[str] = []
        warnings: list[str] = list(
            dict.fromkeys((*template_profile.warnings, *source_profile.warnings))
        )

        if not included_row_indices:
            blocking_issues.append("Select at least one source row to convert.")

        for field in template_profile.target_fields:
            entry = entry_by_key.get(field.field_key) or ConversionMappingEntry(
                target_field_key=field.field_key,
                target_display_name=field.display_name,
            )
            updated_entries.append(update_entry_sample(entry, source_rows))

        updated_by_key = {entry.target_field_key: entry for entry in updated_entries}
        for field in template_profile.target_fields:
            entry = updated_by_key[field.field_key]
            if entry.mapping_kind == MAPPING_KIND_UNMAPPED:
                if field.required_status == REQUIRED_STATUS_REQUIRED:
                    blocking_issues.append(f"Required target '{field.display_name}' is unmapped.")
                else:
                    warnings.append(
                        f"Target '{field.display_name}' is intentionally left unmapped."
                    )
            elif (
                entry.mapping_kind == MAPPING_KIND_SKIP
                and field.required_status == REQUIRED_STATUS_REQUIRED
            ):
                blocking_issues.append(f"Required target '{field.display_name}' is skipped.")

        for row in source_rows:
            rendered_row: dict[str, object] = {}
            for field in template_profile.target_fields:
                entry = updated_by_key[field.field_key]
                rendered_row[field.field_key] = resolve_mapping_value(entry, row)
            rendered_field_rows.append(rendered_row)

        for field in template_profile.target_fields:
            entry = updated_by_key[field.field_key]
            if entry.mapping_kind in {MAPPING_KIND_UNMAPPED, MAPPING_KIND_SKIP}:
                continue
            values = [
                str(rendered.get(field.field_key, "")).strip() for rendered in rendered_field_rows
            ]
            if field.required_status == REQUIRED_STATUS_REQUIRED and any(
                not value for value in values
            ):
                blocking_issues.append(
                    f"Required target '{field.display_name}' resolves empty in one or more rendered rows."
                )
            elif field.required_status != REQUIRED_STATUS_REQUIRED and any(
                not value for value in values
            ):
                warnings.append(
                    f"Target '{field.display_name}' resolves empty in one or more rendered rows."
                )

        adapter = self._template_adapters.get(template_profile.format_name)
        if adapter is None:
            raise ValueError(f"Unsupported template format: {template_profile.format_name}")
        rendered_headers, rendered_rows, rendered_xml_text, adapter_warnings, adapter_state = (
            adapter.build_preview(template_profile, rendered_field_rows)
        )
        warnings.extend(adapter_warnings)
        return ConversionPreview(
            template_profile=template_profile,
            source_profile=source_profile,
            mapping_entries=tuple(updated_entries),
            included_row_indices=included_row_indices,
            rendered_headers=rendered_headers,
            rendered_rows=rendered_rows,
            rendered_field_rows=tuple(
                {
                    field.display_name: stringify_value(rendered.get(field.field_key, ""))
                    for field in template_profile.target_fields
                }
                for rendered in rendered_field_rows
            ),
            rendered_xml_text=rendered_xml_text,
            warnings=tuple(dict.fromkeys(warnings)),
            blocking_issues=tuple(dict.fromkeys(blocking_issues)),
            adapter_state=adapter_state,
        )

    def export_preview(
        self,
        preview: ConversionPreview,
        output_path,
        *,
        progress_callback=None,
    ):
        adapter = self._template_adapters.get(preview.template_profile.format_name)
        if adapter is None:
            raise ValueError(f"Unsupported template format: {preview.template_profile.format_name}")
        return adapter.export_preview(
            preview,
            output_path,
            progress_callback=progress_callback,
        )

    @staticmethod
    def serialize_mapping_entries(entries: tuple[ConversionMappingEntry, ...]) -> str:
        payload = [
            {
                "target_field_key": entry.target_field_key,
                "mapping_kind": entry.mapping_kind,
                "source_field": entry.source_field,
                "constant_value": entry.constant_value,
                "transform_name": entry.transform_name,
            }
            for entry in entries
        ]
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    @staticmethod
    def deserialize_mapping_entries(
        payload: str,
        template_profile: ConversionTemplateProfile,
    ) -> tuple[ConversionMappingEntry, ...]:
        try:
            rows = json.loads(str(payload or "[]"))
        except Exception:
            rows = []
        label_by_key = {
            field.field_key: field.display_name for field in template_profile.target_fields
        }
        entries: list[ConversionMappingEntry] = []
        for row in rows if isinstance(rows, list) else []:
            key = str((row or {}).get("target_field_key") or "").strip()
            if key not in label_by_key:
                continue
            entries.append(
                ConversionMappingEntry(
                    target_field_key=key,
                    target_display_name=label_by_key[key],
                    mapping_kind=str((row or {}).get("mapping_kind") or MAPPING_KIND_UNMAPPED),
                    source_field=str((row or {}).get("source_field") or ""),
                    constant_value=str((row or {}).get("constant_value") or ""),
                    transform_name=str((row or {}).get("transform_name") or "identity"),
                )
            )
        return tuple(entries)

    def _template_adapter_for_path(self, path: Path):
        format_name = self._normalized_format_name(path)
        if format_name not in self._template_adapters:
            raise ValueError("Unsupported template format. Use CSV, XLSX, or XML.")
        return self._template_adapters[format_name]

    @staticmethod
    def _normalized_format_name(path: Path) -> str:
        suffix = path.suffix.lower().lstrip(".")
        if suffix in {"xlsx", "xlsm", "xltx", "xltm"}:
            return "xlsx"
        return suffix

    @staticmethod
    def _inspect_json_source(path: Path) -> ConversionSourceProfile:
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows: list[dict[str, object]]
        if isinstance(payload, list):
            rows = [dict(row) for row in payload if isinstance(row, dict)]
        elif isinstance(payload, dict):
            if isinstance(payload.get("rows"), list):
                rows = [dict(row) for row in payload.get("rows") if isinstance(row, dict)]
            elif isinstance(payload.get("items"), list):
                rows = [dict(row) for row in payload.get("items") if isinstance(row, dict)]
            else:
                nested_lists = [
                    value
                    for value in payload.values()
                    if isinstance(value, list) and all(isinstance(item, dict) for item in value)
                ]
                if len(nested_lists) == 1:
                    rows = [dict(row) for row in nested_lists[0]]
                else:
                    rows = [dict(payload)]
        else:
            raise ValueError("JSON source must be an array of objects or an object wrapper.")
        headers: list[str] = []
        seen: set[str] = set()
        for row in rows:
            for key in row:
                name = str(key)
                if name in seen:
                    continue
                seen.add(name)
                headers.append(name)
        return ConversionSourceProfile(
            source_mode="file",
            format_name="json",
            source_label=str(path),
            source_path=str(path),
            headers=tuple(headers),
            rows=tuple(rows),
            preview_rows=tuple(rows[:10]),
        )

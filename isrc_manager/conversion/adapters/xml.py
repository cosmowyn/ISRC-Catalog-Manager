"""XML template and source adapters for conversion."""

from __future__ import annotations

import copy
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET

from ..mapping import normalize_field_name
from ..models import (
    REQUIRED_STATUS_UNKNOWN,
    SOURCE_MODE_FILE,
    ConversionExportResult,
    ConversionSourceProfile,
    ConversionTargetField,
    ConversionTemplateProfile,
)
from .base import SourceAdapter, TemplateAdapter


def _local_name(tag: str) -> str:
    if "}" in str(tag):
        return str(tag).rsplit("}", 1)[-1]
    return str(tag)


def _build_paths(root: ET.Element) -> dict[int, str]:
    paths: dict[int, str] = {id(root): f"/{_local_name(root.tag)}"}
    for parent in root.iter():
        parent_path = paths.get(id(parent), f"/{_local_name(parent.tag)}")
        counts: dict[str, int] = {}
        for child in list(parent):
            tag_name = _local_name(child.tag)
            counts[tag_name] = counts.get(tag_name, 0) + 1
            suffix = (
                f"[{counts[tag_name]}]"
                if sum(1 for sibling in list(parent) if _local_name(sibling.tag) == tag_name) > 1
                else ""
            )
            paths[id(child)] = f"{parent_path}/{tag_name}{suffix}"
    return paths


def _extract_leaf_fields(
    sample_node: ET.Element, sample_path: str
) -> tuple[ConversionTargetField, ...]:
    fields: list[ConversionTargetField] = []
    for attr_name in sorted(sample_node.attrib):
        fields.append(
            ConversionTargetField(
                field_key=normalize_field_name(attr_name),
                display_name=f"@{attr_name}",
                location=f"{sample_path}/@{attr_name}",
                required_status=REQUIRED_STATUS_UNKNOWN,
                kind="attribute",
                metadata={"path": ".", "attribute_name": attr_name},
            )
        )
    for element in sample_node.iter():
        if element is sample_node:
            continue
        if list(element):
            continue
        element_path = []
        current = element
        while current is not sample_node:
            element_path.insert(0, _local_name(current.tag))
            parent = None
            for candidate in sample_node.iter():
                if current in list(candidate):
                    parent = candidate
                    break
            if parent is None:
                break
            current = parent
        relative_path = "/".join(element_path)
        clean_name = relative_path or _local_name(element.tag)
        fields.append(
            ConversionTargetField(
                field_key=normalize_field_name(clean_name),
                display_name=clean_name,
                location=f"{sample_path}/{clean_name}",
                required_status=REQUIRED_STATUS_UNKNOWN,
                kind="element",
                metadata={"path": relative_path},
            )
        )
        for attr_name in sorted(element.attrib):
            fields.append(
                ConversionTargetField(
                    field_key=normalize_field_name(f"{clean_name}_{attr_name}"),
                    display_name=f"{clean_name}/@{attr_name}",
                    location=f"{sample_path}/{clean_name}/@{attr_name}",
                    required_status=REQUIRED_STATUS_UNKNOWN,
                    kind="attribute",
                    metadata={"path": relative_path, "attribute_name": attr_name},
                )
            )
    seen: set[str] = set()
    ordered: list[ConversionTargetField] = []
    for field in fields:
        if field.location in seen:
            continue
        seen.add(field.location)
        ordered.append(field)
    return tuple(ordered)


def _node_candidates(root: ET.Element) -> list[dict[str, object]]:
    paths = _build_paths(root)
    candidates: list[dict[str, object]] = []
    for parent in root.iter():
        children = [child for child in list(parent) if isinstance(child.tag, str)]
        if not children:
            continue
        counts: dict[str, list[ET.Element]] = {}
        for child in children:
            counts.setdefault(_local_name(child.tag), []).append(child)
        for tag_name, group in counts.items():
            if len(group) >= 2:
                sample_node = group[0]
                sample_path = paths[id(sample_node)]
                candidates.append(
                    {
                        "scope_key": sample_path,
                        "scope_label": sample_path,
                        "sample_path": sample_path,
                        "parent_path": paths[id(parent)],
                        "node_tag": tag_name,
                        "repeated": True,
                        "sample_fields": _extract_leaf_fields(sample_node, sample_path),
                    }
                )
    if candidates:
        return candidates
    for element in root.iter():
        if element is root or not list(element):
            continue
        sample_path = paths[id(element)]
        candidates.append(
            {
                "scope_key": sample_path,
                "scope_label": sample_path,
                "sample_path": sample_path,
                "parent_path": sample_path.rsplit("/", 1)[0] or "/",
                "node_tag": _local_name(element.tag),
                "repeated": False,
                "sample_fields": _extract_leaf_fields(element, sample_path),
            }
        )
    return candidates


def _lookup_by_path(root: ET.Element, path: str) -> ET.Element | None:
    clean_path = str(path or "").strip().strip("/")
    if not clean_path:
        return root
    parts = clean_path.split("/")
    current = root
    if _local_name(current.tag) != parts[0].split("[", 1)[0]:
        return None
    for part in parts[1:]:
        name = part.split("[", 1)[0]
        target_index = 1
        if "[" in part and part.endswith("]"):
            try:
                target_index = int(part.rsplit("[", 1)[-1].rstrip("]"))
            except ValueError:
                target_index = 1
        matches = [child for child in list(current) if _local_name(child.tag) == name]
        if len(matches) < target_index or target_index <= 0:
            return None
        current = matches[target_index - 1]
    return current


def _row_from_node(
    sample_node: ET.Element, fields: tuple[ConversionTargetField, ...]
) -> dict[str, object]:
    row: dict[str, object] = {}
    for field in fields:
        relative_path = str(field.metadata.get("path") or "").strip()
        attribute_name = str(field.metadata.get("attribute_name") or "").strip()
        target = sample_node if relative_path in {"", "."} else sample_node.find(relative_path)
        if target is None:
            row[field.display_name] = ""
            continue
        if attribute_name:
            row[field.display_name] = target.attrib.get(attribute_name, "")
        else:
            row[field.display_name] = target.text or ""
    return row


def _parse_xml_source(source: Path | bytes):
    if isinstance(source, Path):
        return ET.parse(source)
    return ET.parse(BytesIO(bytes(source)))


class XmlTemplateAdapter(TemplateAdapter):
    format_name = "xml"

    def inspect_template(self, path: str | Path) -> ConversionTemplateProfile:
        template_path = Path(path)
        tree = _parse_xml_source(template_path)
        root = tree.getroot()
        candidates = _node_candidates(root)
        if not candidates:
            raise ValueError("The XML template does not expose a usable repeat-node candidate.")
        chosen = candidates[0]
        available_scopes = tuple((item["scope_key"], item["scope_label"]) for item in candidates)
        warnings: list[str] = []
        if len(available_scopes) > 1:
            warnings.append(
                "Multiple XML record nodes were detected. Review the selected node path."
            )
        return ConversionTemplateProfile(
            template_path=template_path,
            format_name=self.format_name,
            output_suffix=template_path.suffix.lower() or ".xml",
            structure_label=f"XML template ({template_path.name})",
            target_fields=tuple(chosen["sample_fields"]),
            template_signature=self._template_signature(
                str(chosen["scope_key"]), tuple(chosen["sample_fields"])
            ),
            template_bytes=None,
            available_scopes=available_scopes,
            chosen_scope=str(chosen["scope_key"]),
            warnings=tuple(warnings),
            adapter_state={
                "candidates": {item["scope_key"]: item for item in candidates},
                "xml_declaration": template_path.read_text(encoding="utf-8", errors="ignore")
                .lstrip()
                .startswith("<?xml"),
            },
        )

    def select_scope(
        self,
        profile: ConversionTemplateProfile,
        scope_key: str,
    ) -> ConversionTemplateProfile:
        candidates = profile.adapter_state.get("candidates") or {}
        chosen = candidates.get(scope_key)
        if not chosen:
            return profile
        return ConversionTemplateProfile(
            template_path=profile.template_path,
            format_name=profile.format_name,
            output_suffix=profile.output_suffix,
            structure_label=profile.structure_label,
            target_fields=tuple(chosen["sample_fields"]),
            template_signature=self._template_signature(
                str(scope_key), tuple(chosen["sample_fields"])
            ),
            template_bytes=profile.template_bytes,
            available_scopes=profile.available_scopes,
            chosen_scope=str(scope_key),
            warnings=profile.warnings,
            adapter_state=profile.adapter_state,
        )

    def build_preview(
        self,
        profile: ConversionTemplateProfile,
        rendered_field_rows: list[dict[str, object]],
    ) -> tuple[
        tuple[str, ...],
        tuple[tuple[str, ...], ...],
        str,
        tuple[str, ...],
        dict[str, object],
    ]:
        headers = tuple(field.display_name for field in profile.target_fields)
        rows = [
            tuple(str(rendered.get(field.field_key, "")) for field in profile.target_fields)
            for rendered in rendered_field_rows
        ]
        xml_text = self._render_xml_text(profile, rendered_field_rows)
        return headers, tuple(rows), xml_text, (), {}

    def export_preview(
        self,
        preview,
        output_path: str | Path,
        *,
        progress_callback=None,
    ) -> ConversionExportResult:
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if callable(progress_callback):
            progress_callback(20, 100, "Preparing XML conversion export...")
        target.write_text(preview.rendered_xml_text, encoding="utf-8")
        if callable(progress_callback):
            progress_callback(90, 100, "XML conversion export written.")
        return ConversionExportResult(
            output_path=target,
            target_format=self.format_name,
            exported_row_count=len(preview.rendered_field_rows),
            summary_lines=(
                f"Template: {preview.template_profile.template_path.name}",
                f"Node path: {preview.template_profile.chosen_scope}",
                f"Rows written: {len(preview.rendered_field_rows)}",
            ),
        )

    def _render_xml_text(
        self,
        profile: ConversionTemplateProfile,
        rendered_field_rows: list[dict[str, object]],
    ) -> str:
        tree = _parse_xml_source(
            profile.template_path if profile.template_bytes is None else profile.template_bytes
        )
        root = tree.getroot()
        candidates = profile.adapter_state.get("candidates") or {}
        chosen = candidates.get(profile.chosen_scope) or {}
        sample_path = str(chosen.get("sample_path") or profile.chosen_scope)
        parent_path = str(chosen.get("parent_path") or sample_path.rsplit("/", 1)[0] or "/")
        sample_node = _lookup_by_path(root, sample_path)
        parent_node = _lookup_by_path(root, parent_path)
        if sample_node is None or parent_node is None:
            raise ValueError("Could not resolve the selected XML repeat-node path.")
        repeated = bool(chosen.get("repeated"))
        node_tag = str(chosen.get("node_tag") or _local_name(sample_node.tag))
        children = list(parent_node)
        insert_index = children.index(sample_node)
        nodes_to_remove = (
            [child for child in children if _local_name(child.tag) == node_tag]
            if repeated
            else [sample_node]
        )
        for child in nodes_to_remove:
            parent_node.remove(child)
        for offset, rendered_row in enumerate(rendered_field_rows):
            clone = copy.deepcopy(sample_node)
            self._apply_rendered_values(clone, tuple(profile.target_fields), rendered_row)
            parent_node.insert(insert_index + offset, clone)
        buffer = BytesIO()
        ET.ElementTree(root).write(
            buffer,
            encoding="utf-8",
            xml_declaration=bool(profile.adapter_state.get("xml_declaration")),
        )
        return buffer.getvalue().decode("utf-8")

    @staticmethod
    def _apply_rendered_values(
        node: ET.Element,
        fields: tuple[ConversionTargetField, ...],
        rendered_row: dict[str, object],
    ) -> None:
        for field in fields:
            value = str(rendered_row.get(field.field_key, ""))
            relative_path = str(field.metadata.get("path") or "").strip()
            attribute_name = str(field.metadata.get("attribute_name") or "").strip()
            target = node if relative_path in {"", "."} else node.find(relative_path)
            if target is None:
                continue
            if attribute_name:
                target.set(attribute_name, value)
            else:
                target.text = value

    @staticmethod
    def _template_signature(
        scope_key: str, target_fields: tuple[ConversionTargetField, ...]
    ) -> str:
        field_ids = ",".join(field.field_key for field in target_fields)
        return f"xml|node:{scope_key}|{field_ids}"


class XmlSourceAdapter(SourceAdapter):
    format_name = "xml"

    def inspect_source(
        self,
        source,
        *,
        preferred_csv_delimiter: str | None = None,
    ) -> ConversionSourceProfile:
        del preferred_csv_delimiter
        source_path = Path(source)
        tree = ET.parse(source_path)
        root = tree.getroot()
        candidates = _node_candidates(root)
        if not candidates:
            raise ValueError("The XML source does not expose a usable repeat-node candidate.")
        available_scopes = tuple((item["scope_key"], item["scope_label"]) for item in candidates)
        chosen_scope = str(candidates[0]["scope_key"])
        return self.select_scope(
            ConversionSourceProfile(
                source_mode=SOURCE_MODE_FILE,
                format_name=self.format_name,
                source_label=str(source_path),
                source_path=str(source_path),
                headers=(),
                rows=(),
                preview_rows=(),
                available_scopes=available_scopes,
                chosen_scope=chosen_scope,
                warnings=tuple(
                    ["Multiple XML record nodes were detected. Review the selected source node."]
                    if len(available_scopes) > 1
                    else []
                ),
                adapter_state={"candidates": {item["scope_key"]: item for item in candidates}},
            ),
            chosen_scope,
        )

    def select_scope(
        self,
        profile: ConversionSourceProfile,
        scope_key: str,
    ) -> ConversionSourceProfile:
        source_path = Path(profile.source_path)
        tree = ET.parse(source_path)
        root = tree.getroot()
        candidates = profile.adapter_state.get("candidates") or {}
        chosen = candidates.get(scope_key)
        if not chosen:
            return profile
        sample_path = str(chosen.get("sample_path") or scope_key)
        parent_path = str(chosen.get("parent_path") or sample_path.rsplit("/", 1)[0] or "/")
        sample_node = _lookup_by_path(root, sample_path)
        parent_node = _lookup_by_path(root, parent_path)
        if sample_node is None or parent_node is None:
            return profile
        repeated = bool(chosen.get("repeated"))
        node_tag = str(chosen.get("node_tag") or _local_name(sample_node.tag))
        nodes = (
            [child for child in list(parent_node) if _local_name(child.tag) == node_tag]
            if repeated
            else [sample_node]
        )
        target_fields = tuple(chosen.get("sample_fields") or ())
        rows = tuple(_row_from_node(node, target_fields) for node in nodes)
        headers = tuple(field.display_name for field in target_fields)
        return ConversionSourceProfile(
            source_mode=profile.source_mode,
            format_name=profile.format_name,
            source_label=profile.source_label,
            source_path=profile.source_path,
            headers=headers,
            rows=rows,
            preview_rows=rows[:10],
            available_scopes=profile.available_scopes,
            chosen_scope=str(scope_key),
            warnings=profile.warnings,
            adapter_state=profile.adapter_state,
        )

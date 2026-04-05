"""Resolved export and PDF generation for contract template workflows."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from io import BytesIO
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile

from PySide6.QtCore import QEventLoop, QMarginsF, QSizeF, QTimer, QUrl
from PySide6.QtGui import QPageLayout, QPageSize, QPdfWriter, QTextDocument
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication

from isrc_manager.file_storage import coalesce_filename, sha256_digest

from .html_support import clone_html_package_tree, decode_html_bytes, replace_html_placeholders
from .ingestion import PagesTemplateAdapter
from .models import (
    ContractTemplateDraftPayload,
    ContractTemplateExportResult,
    ContractTemplateOutputArtifactPayload,
    ContractTemplateResolvedSnapshotPayload,
    build_contract_template_selector_scope_key,
)
from .parser import parse_placeholder

_DOCX_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
_DOCX_PART_RE = re.compile(r"^word/(document|header\d+|footer\d+)\.xml$")
_SLUG_RE = re.compile(r"[^A-Za-z0-9._-]+")
_DEFAULT_SCOPE_ENTITY_BY_NAMESPACE = {
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
_DEFAULT_SCOPE_POLICY_BY_NAMESPACE = {
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


def _clean_text(value: object | None) -> str | None:
    clean = str(value or "").strip()
    return clean or None


def _slugify(value: str, *, fallback: str) -> str:
    cleaned = _SLUG_RE.sub("-", str(value or "").strip()).strip("-._")
    return cleaned or fallback


class ContractTemplateExportError(RuntimeError):
    """Raised when a contract template draft cannot be resolved or exported."""


class TextutilDocxRenderAdapter:
    """Converts resolved DOCX bytes to HTML using local macOS tooling."""

    adapter_name = "textutil_docx_html_qt_pdf"

    def __init__(self, *, textutil_path: str | None = None):
        self.textutil_path = (
            textutil_path if textutil_path is not None else shutil.which("textutil")
        )

    def is_available(self) -> bool:
        return sys.platform == "darwin" and bool(self.textutil_path)

    def availability_message(self) -> str | None:
        if self.is_available():
            return None
        if sys.platform != "darwin":
            return "PDF export is only available on macOS hosts with the local document bridge."
        if not self.textutil_path:
            return "PDF export is unavailable because the macOS 'textutil' tool was not found."
        return "PDF export is unavailable on this machine."

    def docx_bytes_to_html(
        self,
        docx_bytes: bytes,
        *,
        source_filename: str = "contract-template.docx",
    ) -> str:
        if not self.is_available():
            raise ContractTemplateExportError(
                self.availability_message() or "PDF export is unavailable."
            )
        with tempfile.TemporaryDirectory(prefix="contract-template-render-") as tmpdir:
            workdir = Path(tmpdir)
            docx_path = workdir / coalesce_filename(
                source_filename,
                default_stem="contract-template",
                default_suffix=".docx",
            )
            if docx_path.suffix.lower() != ".docx":
                docx_path = docx_path.with_suffix(".docx")
            html_path = docx_path.with_suffix(".html")
            docx_path.write_bytes(docx_bytes)
            result = subprocess.run(
                [
                    str(self.textutil_path),
                    "-convert",
                    "html",
                    "-output",
                    str(html_path),
                    str(docx_path),
                ],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0 or not html_path.exists():
                raise ContractTemplateExportError(
                    "DOCX-to-HTML rendering via textutil failed."
                    + (
                        f" {str(result.stderr or '').strip()}"
                        if str(result.stderr or "").strip()
                        else ""
                    )
                )
            return html_path.read_text(encoding="utf-8", errors="replace")


class QtWebEngineHtmlPdfAdapter:
    """Renders local HTML files to PDF via Qt WebEngine for high-fidelity output."""

    adapter_name = "qt_webengine_html_pdf"

    def __init__(self, *, timeout_ms: int = 15000):
        self.timeout_ms = max(1000, int(timeout_ms))

    def is_available(self) -> bool:
        return True

    def availability_message(self) -> str | None:
        return None

    def create_view(self, parent=None) -> QWebEngineView:
        QApplication.instance() or QApplication([])
        return QWebEngineView(parent)

    def render_file_to_pdf(self, html_path: str | Path, output_path: str | Path) -> Path:
        source = Path(html_path)
        target = Path(output_path)
        if not source.exists():
            raise ContractTemplateExportError(f"HTML render source does not exist: {source}")
        app = QApplication.instance() or QApplication([])
        del app
        target.parent.mkdir(parents=True, exist_ok=True)
        page = QWebEnginePage()
        loop = QEventLoop()
        result: dict[str, object] = {"loaded": False, "printed": False}

        def _finish_with_error(message: str) -> None:
            if result.get("printed"):
                return
            result["printed"] = True
            result["error"] = message
            loop.quit()

        def _on_load_finished(ok: bool) -> None:
            result["loaded"] = bool(ok)
            if not ok:
                _finish_with_error(f"Failed to load HTML source for PDF export: {source}")
                return
            page.printToPdf(str(target))

        def _on_pdf_finished(path: str, success: bool) -> None:
            if not success:
                _finish_with_error(f"Qt WebEngine failed to write PDF output: {path}")
                return
            result["printed"] = True
            loop.quit()

        page.loadFinished.connect(_on_load_finished)
        page.pdfPrintingFinished.connect(_on_pdf_finished)
        page.load(QUrl.fromLocalFile(str(source.resolve())))
        QTimer.singleShot(
            self.timeout_ms,
            lambda: _finish_with_error(
                f"Timed out after {self.timeout_ms} ms waiting for HTML PDF export."
            ),
        )
        loop.exec()
        if result.get("error"):
            raise ContractTemplateExportError(str(result["error"]))
        if not target.exists():
            raise ContractTemplateExportError("Qt WebEngine did not produce a PDF output file.")
        return target

    def render_html_to_pdf(
        self,
        html_text: str,
        *,
        base_url: str | Path | None,
        output_path: str | Path,
    ) -> Path:
        target = Path(output_path)
        app = QApplication.instance() or QApplication([])
        del app
        target.parent.mkdir(parents=True, exist_ok=True)
        page = QWebEnginePage()
        loop = QEventLoop()
        result: dict[str, object] = {"loaded": False, "printed": False}

        def _finish_with_error(message: str) -> None:
            if result.get("printed"):
                return
            result["printed"] = True
            result["error"] = message
            loop.quit()

        def _on_load_finished(ok: bool) -> None:
            result["loaded"] = bool(ok)
            if not ok:
                _finish_with_error("Failed to load HTML content for PDF export.")
                return
            page.printToPdf(str(target))

        def _on_pdf_finished(path: str, success: bool) -> None:
            if not success:
                _finish_with_error(f"Qt WebEngine failed to write PDF output: {path}")
                return
            result["printed"] = True
            loop.quit()

        base = self._as_base_url(base_url)
        page.loadFinished.connect(_on_load_finished)
        page.pdfPrintingFinished.connect(_on_pdf_finished)
        page.setHtml(str(html_text or ""), base)
        QTimer.singleShot(
            self.timeout_ms,
            lambda: _finish_with_error(
                f"Timed out after {self.timeout_ms} ms waiting for HTML PDF export."
            ),
        )
        loop.exec()
        if result.get("error"):
            raise ContractTemplateExportError(str(result["error"]))
        if not target.exists():
            raise ContractTemplateExportError("Qt WebEngine did not produce a PDF output file.")
        return target

    @staticmethod
    def _as_base_url(base_url: str | Path | None) -> QUrl:
        if base_url is None:
            return QUrl()
        base_path = Path(base_url)
        if base_path.exists() and base_path.is_file():
            base_path = base_path.parent
        if str(base_path).endswith("/"):
            return QUrl.fromLocalFile(str(base_path))
        return QUrl.fromLocalFile(f"{base_path.resolve()}/")


class ContractTemplateExportService:
    """Resolves editable payloads into immutable snapshots and PDF artifacts."""

    def __init__(
        self,
        *,
        template_service,
        catalog_service,
        settings_reads=None,
        track_service=None,
        release_service=None,
        work_service=None,
        contract_service=None,
        party_service=None,
        rights_service=None,
        asset_service=None,
        custom_field_definition_service=None,
        custom_field_value_service=None,
        html_adapter: TextutilDocxRenderAdapter | None = None,
        html_pdf_adapter: QtWebEngineHtmlPdfAdapter | None = None,
        pages_adapter: PagesTemplateAdapter | None = None,
    ):
        self.template_service = template_service
        self.catalog_service = catalog_service
        self.settings_reads = settings_reads
        self.track_service = track_service
        self.release_service = release_service
        self.work_service = work_service
        self.contract_service = contract_service
        self.party_service = party_service
        self.rights_service = rights_service
        self.asset_service = asset_service
        self.custom_field_definition_service = custom_field_definition_service
        self.custom_field_value_service = custom_field_value_service
        self.html_adapter = (
            html_adapter if html_adapter is not None else TextutilDocxRenderAdapter()
        )
        self.html_pdf_adapter = (
            html_pdf_adapter
            if html_pdf_adapter is not None
            else QtWebEngineHtmlPdfAdapter()
        )
        self.pages_adapter = (
            pages_adapter if pages_adapter is not None else self.template_service.pages_adapter
        )
        self._owned_qapp = None

    def export_draft_to_pdf(self, draft_id: int) -> ContractTemplateExportResult:
        draft = self.template_service.fetch_draft(draft_id)
        if draft is None:
            raise ContractTemplateExportError(f"Contract template draft {draft_id} not found")
        editable_payload = self.template_service.fetch_draft_payload(draft_id) or {}
        return self.export_editable_payload_to_pdf(
            revision_id=draft.revision_id,
            editable_payload=editable_payload,
            draft_id=draft.draft_id,
            draft_name=draft.name,
        )

    def export_editable_payload_to_pdf(
        self,
        *,
        revision_id: int,
        editable_payload: object,
        draft_id: int,
        draft_name: str | None = None,
    ) -> ContractTemplateExportResult:
        revision = self.template_service.fetch_revision(revision_id)
        if revision is None:
            raise ContractTemplateExportError(f"Contract template revision {revision_id} not found")
        template = self.template_service.fetch_template(revision.template_id)
        if template is None:
            raise ContractTemplateExportError(f"Contract template {revision.template_id} not found")

        editable_map = dict(editable_payload or {})
        if str(revision.source_format or "").strip().lower() == "html":
            return self._export_html_payload_to_pdf(
                revision=revision,
                template=template,
                editable_payload=editable_map,
                draft_id=draft_id,
                draft_name=draft_name,
            )
        resolved_values, resolution_warnings = self._resolve_payload_values(
            revision_id,
            editable_map,
        )
        source_docx_bytes, render_source_name = self._export_source_as_docx(
            revision=revision,
        )
        resolved_docx_bytes, replacement_warnings = self._replace_docx_placeholders(
            source_docx_bytes,
            resolved_values,
        )
        unresolved = self.template_service.docx_scanner.scan_bytes(resolved_docx_bytes).placeholders
        if unresolved:
            unresolved_text = ", ".join(item.canonical_symbol for item in unresolved)
            raise ContractTemplateExportError(
                "Resolved document still contains placeholder tokens after replacement: "
                f"{unresolved_text}"
            )
        warnings = tuple(dict.fromkeys([*resolution_warnings, *replacement_warnings]))

        snapshot = self.template_service.create_resolved_snapshot(
            ContractTemplateResolvedSnapshotPayload(
                draft_id=int(draft_id),
                revision_id=revision.revision_id,
                resolved_values=resolved_values,
                resolution_warnings=list(warnings) if warnings else None,
                preview_payload={
                    "renderer": self._pdf_renderer_name(),
                    "source_format": revision.source_format,
                    "resolved_source_name": render_source_name,
                },
                resolved_checksum_sha256=sha256_digest(
                    str(sorted(resolved_values.items())).encode("utf-8")
                ),
            )
        )
        self.template_service.set_draft_last_resolved_snapshot(
            draft_id,
            snapshot.snapshot_id,
        )

        stem = _slugify(draft_name or template.name, fallback="contract-template-export")
        artifact_subdir = f"template_{template.template_id}/snapshot_{snapshot.snapshot_id}"
        resolved_docx_artifact = self._write_resolved_docx_artifact(
            snapshot_id=snapshot.snapshot_id,
            docx_bytes=resolved_docx_bytes,
            stem=stem,
            subdir=artifact_subdir,
        )
        pdf_artifact = self._write_pdf_artifact(
            snapshot_id=snapshot.snapshot_id,
            docx_bytes=resolved_docx_bytes,
            source_filename=render_source_name,
            stem=stem,
            subdir=artifact_subdir,
        )
        return ContractTemplateExportResult(
            snapshot=snapshot,
            resolved_docx_artifact=resolved_docx_artifact,
            resolved_html_artifact=None,
            pdf_artifact=pdf_artifact,
            warnings=warnings,
        )

    def _resolve_payload_values(
        self,
        revision_id: int,
        editable_payload: dict[str, object],
        *,
        strict: bool = True,
    ) -> tuple[dict[str, str], tuple[str, ...]]:
        placeholders = self.template_service.list_placeholders(revision_id)
        bindings = {
            item.canonical_symbol: item
            for item in self.template_service.list_placeholder_bindings(revision_id)
        }
        catalog = {
            item.canonical_symbol: item for item in self.catalog_service.list_known_symbols()
        }
        db_selections = dict(editable_payload.get("db_selections") or {})
        manual_values = dict(editable_payload.get("manual_values") or {})
        resolved: dict[str, str] = {}
        missing_required: list[str] = []
        group_selections, warnings = self._normalized_group_db_selections(
            placeholders=placeholders,
            bindings=bindings,
            catalog=catalog,
            db_selections=db_selections,
        )
        for placeholder in placeholders:
            canonical = placeholder.canonical_symbol
            token = parse_placeholder(canonical)
            if token.binding_kind == "manual":
                if canonical not in manual_values:
                    if strict:
                        raise ContractTemplateExportError(
                            f"Manual placeholder {canonical} does not have a saved value."
                        )
                    continue
                resolved[canonical] = self._render_output_value(manual_values.get(canonical))
                continue
            catalog_entry = catalog.get(canonical)
            if catalog_entry is None:
                if strict:
                    raise ContractTemplateExportError(
                        f"Database-backed placeholder {canonical} is not present in the symbol catalog."
                    )
                warnings.append(
                    f"Skipped {canonical} because it is no longer present in the symbol catalog."
                )
                continue
            if str(catalog_entry.namespace or "").strip().lower() == "owner":
                try:
                    resolved_value = self._resolve_catalog_value(
                        catalog_entry=catalog_entry,
                        selection_value=None,
                    )
                except ContractTemplateExportError:
                    if strict:
                        raise
                    continue
                rendered = self._render_output_value(resolved_value)
                if not rendered and placeholder.required:
                    if strict and str(catalog_entry.namespace or "").strip().lower() == "owner":
                        missing_required.append(
                            self._missing_required_value_message(
                                placeholder=placeholder,
                                catalog_entry=catalog_entry,
                                selection_value=None,
                            )
                        )
                    else:
                        warnings.append(f"{canonical} resolved to an empty value.")
                resolved[canonical] = rendered
                continue
            selection_value = group_selections.get(
                self._selector_scope_key(
                    placeholder=placeholder,
                    binding=bindings.get(canonical),
                    catalog_entry=catalog_entry,
                ),
                db_selections.get(canonical),
            )
            if selection_value is None:
                if strict:
                    raise ContractTemplateExportError(
                        f"Database-backed placeholder {canonical} does not have a selected record."
                    )
                continue
            try:
                resolved_value = self._resolve_catalog_value(
                    catalog_entry=catalog_entry,
                    selection_value=selection_value,
                )
            except ContractTemplateExportError:
                if strict:
                    raise
                warnings.append(
                    f"Skipped {canonical} because its selected record could not be resolved."
                )
                continue
            rendered = self._render_output_value(resolved_value)
            if not rendered and placeholder.required:
                if strict and str(catalog_entry.namespace or "").strip().lower() == "owner":
                    missing_required.append(
                        self._missing_required_value_message(
                            placeholder=placeholder,
                            catalog_entry=catalog_entry,
                            selection_value=selection_value,
                        )
                    )
                else:
                    warnings.append(f"{canonical} resolved to an empty value.")
            resolved[canonical] = rendered
        if missing_required:
            detail = "\n".join(f"- {message}" for message in missing_required)
            raise ContractTemplateExportError(
                "Required placeholder values are missing in the selected authoritative source:\n"
                f"{detail}"
            )
        return resolved, tuple(warnings)

    def _normalized_group_db_selections(
        self,
        *,
        placeholders,
        bindings: dict[str, object],
        catalog: dict[str, object],
        db_selections: dict[str, object],
    ) -> tuple[dict[str, object], list[str]]:
        grouped_members: dict[str, list[str]] = {}
        for placeholder in placeholders:
            catalog_entry = catalog.get(placeholder.canonical_symbol)
            if catalog_entry is None:
                continue
            group_key = self._selector_scope_key(
                placeholder=placeholder,
                binding=bindings.get(placeholder.canonical_symbol),
                catalog_entry=catalog_entry,
            )
            if group_key is None:
                continue
            grouped_members.setdefault(group_key, []).append(placeholder.canonical_symbol)

        normalized: dict[str, object] = {}
        warnings: list[str] = []
        for group_key, member_symbols in grouped_members.items():
            candidate_pairs: list[tuple[str, object]] = []
            if group_key in db_selections and db_selections[group_key] is not None:
                candidate_pairs.append((group_key, db_selections[group_key]))
            for canonical_symbol in member_symbols:
                if (
                    canonical_symbol in db_selections
                    and db_selections[canonical_symbol] is not None
                ):
                    candidate_pairs.append((canonical_symbol, db_selections[canonical_symbol]))
            distinct_values: list[tuple[str, object]] = []
            seen: set[str] = set()
            for source_key, raw_value in candidate_pairs:
                normalized_value = str(raw_value)
                if normalized_value in seen:
                    continue
                seen.add(normalized_value)
                distinct_values.append((source_key, raw_value))
            if not distinct_values:
                continue
            normalized[group_key] = distinct_values[0][1]
            if len(distinct_values) > 1:
                warnings.append(
                    "Grouped database placeholders contained conflicting saved selections "
                    f"for {group_key}; using {distinct_values[0][0]}."
                )
        return normalized, warnings

    def _selector_scope_key(
        self,
        *,
        placeholder,
        binding,
        catalog_entry,
    ) -> str | None:
        token = parse_placeholder(placeholder.canonical_symbol)
        scope_entity_type = (
            _clean_text(getattr(binding, "scope_entity_type", None))
            or _clean_text(getattr(catalog_entry, "scope_entity_type", None))
            or _DEFAULT_SCOPE_ENTITY_BY_NAMESPACE.get(str(token.namespace or "").strip().lower())
        )
        scope_policy = (
            _clean_text(getattr(binding, "scope_policy", None))
            or _clean_text(getattr(catalog_entry, "scope_policy", None))
            or _DEFAULT_SCOPE_POLICY_BY_NAMESPACE.get(str(token.namespace or "").strip().lower())
        )
        return build_contract_template_selector_scope_key(scope_entity_type, scope_policy)

    def _resolve_catalog_value(
        self,
        *,
        catalog_entry,
        selection_value: object | None,
    ) -> Any:
        namespace = str(catalog_entry.namespace or "").strip().lower()
        key = str(catalog_entry.key or "").strip()
        if namespace == "owner":
            if self.settings_reads is None:
                raise ContractTemplateExportError(
                    "Owner placeholder resolution is unavailable because settings reads are missing."
                )
            owner_settings = self.settings_reads.load_owner_party_settings()
            return getattr(owner_settings, key, None)
        clean_selection = _clean_text(selection_value)
        if clean_selection is None:
            raise ContractTemplateExportError(
                f"{catalog_entry.canonical_symbol} is missing a selected record."
            )
        record_id = int(clean_selection)
        if namespace == "track":
            if self.track_service is None:
                raise ContractTemplateExportError("Track service is unavailable for export.")
            snapshot = self.track_service.fetch_track_snapshot(record_id)
            if snapshot is None:
                raise ContractTemplateExportError(f"Track #{record_id} not found.")
            return getattr(snapshot, key, None)
        if namespace == "release":
            if self.release_service is None:
                raise ContractTemplateExportError("Release service is unavailable for export.")
            record = self.release_service.fetch_release(record_id)
            if record is None:
                raise ContractTemplateExportError(f"Release #{record_id} not found.")
            return getattr(record, key, None)
        if namespace == "work":
            if self.work_service is None:
                raise ContractTemplateExportError("Work service is unavailable for export.")
            record = self.work_service.fetch_work(record_id)
            if record is None:
                raise ContractTemplateExportError(f"Work #{record_id} not found.")
            return getattr(record, key, None)
        if namespace == "contract":
            if self.contract_service is None:
                raise ContractTemplateExportError("Contract service is unavailable for export.")
            record = self.contract_service.fetch_contract(record_id)
            if record is None:
                raise ContractTemplateExportError(f"Contract #{record_id} not found.")
            return getattr(record, key, None)
        if namespace == "party":
            if self.party_service is None:
                raise ContractTemplateExportError("Party service is unavailable for export.")
            record = self.party_service.fetch_party(record_id)
            if record is None:
                raise ContractTemplateExportError(f"Party #{record_id} not found.")
            return getattr(record, key, None)
        if namespace == "right":
            if self.rights_service is None:
                raise ContractTemplateExportError("Rights service is unavailable for export.")
            record = self.rights_service.fetch_right(record_id)
            if record is None:
                raise ContractTemplateExportError(f"Right #{record_id} not found.")
            return getattr(record, key, None)
        if namespace == "asset":
            if self.asset_service is None:
                raise ContractTemplateExportError("Asset service is unavailable for export.")
            record = self.asset_service.fetch_asset(record_id)
            if record is None:
                raise ContractTemplateExportError(f"Asset #{record_id} not found.")
            return getattr(record, key, None)
        if namespace == "custom":
            if self.custom_field_value_service is None:
                raise ContractTemplateExportError(
                    "Custom field value service is unavailable for export."
                )
            field_id = int(catalog_entry.custom_field_id or str(key).replace("cf_", "0"))
            return self.custom_field_value_service.get_text_value(record_id, field_id)
        raise ContractTemplateExportError(
            f"Unsupported placeholder namespace for export: {namespace}"
        )

    def _missing_required_value_message(
        self,
        *,
        placeholder,
        catalog_entry,
        selection_value: object | None,
    ) -> str:
        label = (
            _clean_text(getattr(catalog_entry, "display_label", None))
            or _clean_text(getattr(placeholder, "display_label", None))
            or placeholder.canonical_symbol
        )
        canonical_symbol = str(placeholder.canonical_symbol or "").strip()
        namespace = str(getattr(catalog_entry, "namespace", "") or "").strip().lower()
        if namespace == "owner":
            return f"{label} is blank in Current Owner Party " f"for {canonical_symbol}."
        selected_label = self._selected_record_label(
            namespace=namespace, selection_value=selection_value
        )
        if selected_label:
            return (
                f"{label} is blank for the selected {namespace} record "
                f'"{selected_label}" ({canonical_symbol}).'
            )
        if selection_value is not None:
            return (
                f"{label} is blank for the selected {namespace} record "
                f"#{selection_value} ({canonical_symbol})."
            )
        return f"{label} is blank for {canonical_symbol}."

    def _selected_record_label(
        self,
        *,
        namespace: str,
        selection_value: object | None,
    ) -> str | None:
        clean_selection = _clean_text(selection_value)
        if clean_selection is None:
            return None
        record_id = int(clean_selection)
        if namespace == "track" and self.track_service is not None:
            record = self.track_service.fetch_track_snapshot(record_id)
            if record is not None:
                return _clean_text(getattr(record, "track_title", None)) or _clean_text(
                    getattr(record, "artist_name", None)
                )
            return None
        if namespace == "release" and self.release_service is not None:
            record = self.release_service.fetch_release(record_id)
            if record is not None:
                return _clean_text(getattr(record, "title", None))
            return None
        if namespace == "work" and self.work_service is not None:
            record = self.work_service.fetch_work(record_id)
            if record is not None:
                return _clean_text(getattr(record, "title", None))
            return None
        if namespace == "contract" and self.contract_service is not None:
            record = self.contract_service.fetch_contract(record_id)
            if record is not None:
                return _clean_text(getattr(record, "title", None))
            return None
        if namespace == "party" and self.party_service is not None:
            record = self.party_service.fetch_party(record_id)
            if record is not None:
                return (
                    _clean_text(getattr(record, "display_name", None))
                    or _clean_text(getattr(record, "artist_name", None))
                    or _clean_text(getattr(record, "company_name", None))
                    or _clean_text(getattr(record, "legal_name", None))
                )
            return None
        if namespace == "right" and self.rights_service is not None:
            record = self.rights_service.fetch_right(record_id)
            if record is not None:
                return _clean_text(getattr(record, "title", None)) or _clean_text(
                    getattr(record, "name", None)
                )
            return None
        if namespace == "asset" and self.asset_service is not None:
            record = self.asset_service.fetch_asset(record_id)
            if record is not None:
                return (
                    _clean_text(getattr(record, "title", None))
                    or _clean_text(getattr(record, "name", None))
                    or _clean_text(getattr(record, "filename", None))
                )
            return None
        return None

    def synchronize_html_draft(
        self,
        draft_id: int,
        *,
        require_complete: bool = False,
    ) -> Path:
        draft = self.template_service.fetch_draft(draft_id)
        if draft is None:
            raise ContractTemplateExportError(f"Contract template draft {draft_id} not found")
        revision = self.template_service.fetch_revision(draft.revision_id)
        if revision is None:
            raise ContractTemplateExportError(
                f"Contract template revision {draft.revision_id} not found"
            )
        if str(revision.source_format or "").strip().lower() != "html":
            raise ContractTemplateExportError(
                "HTML draft synchronization is only available for HTML revisions."
            )
        editable_payload = dict(self.template_service.fetch_draft_payload(draft_id) or {})
        source_html_path = self.template_service.resolve_html_revision_source_path(
            revision.revision_id
        )
        if source_html_path is None:
            raise ContractTemplateExportError(
                f"HTML template source is unavailable for revision {revision.revision_id}."
            )
        rendered_html, source_package_root, _warnings = self._render_html_content(
            revision=revision,
            editable_payload=editable_payload,
            strict=require_complete,
        )
        return self._materialize_html_working_copy(
            draft_id=draft_id,
            source_html_path=source_html_path,
            source_package_root=source_package_root,
            rendered_html=rendered_html,
        )

    def _render_html_content(
        self,
        *,
        revision,
        editable_payload: dict[str, object],
        strict: bool,
    ) -> tuple[str, Path, tuple[str, ...]]:
        source_html_path = self.template_service.resolve_html_revision_source_path(
            revision.revision_id
        )
        if source_html_path is None:
            raise ContractTemplateExportError(
                f"HTML template source is unavailable for revision {revision.revision_id}."
            )
        package_root = self.template_service.resolve_html_revision_bundle_root(
            revision.revision_id
        )
        if package_root is None:
            package_root = source_html_path.parent
        resolved_values, warnings = self._resolve_payload_values(
            revision.revision_id,
            editable_payload,
            strict=strict,
        )
        rendered_html = replace_html_placeholders(
            decode_html_bytes(source_html_path.read_bytes()),
            resolved_values,
        )
        return rendered_html, package_root, warnings

    def _export_html_payload_to_pdf(
        self,
        *,
        revision,
        template,
        editable_payload: dict[str, object],
        draft_id: int,
        draft_name: str | None = None,
    ) -> ContractTemplateExportResult:
        resolved_values, resolution_warnings = self._resolve_payload_values(
            revision.revision_id,
            editable_payload,
            strict=True,
        )
        rendered_html, source_package_root, _warnings = self._render_html_content(
            revision=revision,
            editable_payload=editable_payload,
            strict=True,
        )
        source_html_path = self.template_service.resolve_html_revision_source_path(
            revision.revision_id
        )
        if source_html_path is None:
            raise ContractTemplateExportError(
                f"HTML template source is unavailable for revision {revision.revision_id}."
            )
        working_html_path = self._materialize_html_working_copy(
            draft_id=draft_id,
            source_html_path=source_html_path,
            source_package_root=source_package_root,
            rendered_html=rendered_html,
        )
        working_filename = working_html_path.name
        draft_root = self.template_service.draft_store.root_path
        if draft_root is None:
            raise ContractTemplateExportError("Managed draft storage is not configured.")
        try:
            relative_working = working_html_path.relative_to(draft_root)
            working_package_root = draft_root / relative_working.parts[0]
            relative_html = working_html_path.relative_to(working_package_root)
        except Exception:
            working_package_root = working_html_path.parent
            relative_html = Path(working_html_path.name)
        stem = _slugify(draft_name or template.name, fallback="contract-template-export")
        rendered_html_bytes = rendered_html.encode("utf-8")
        warnings = tuple(dict.fromkeys(resolution_warnings))

        snapshot = self.template_service.create_resolved_snapshot(
            ContractTemplateResolvedSnapshotPayload(
                draft_id=int(draft_id),
                revision_id=revision.revision_id,
                resolved_values=resolved_values,
                resolution_warnings=list(warnings) if warnings else None,
                preview_payload={
                    "renderer": self.html_pdf_adapter.adapter_name,
                    "source_format": revision.source_format,
                    "resolved_source_name": working_filename,
                    "working_copy_path": str(working_html_path),
                },
                resolved_checksum_sha256=sha256_digest(rendered_html_bytes),
            )
        )
        self.template_service.set_draft_last_resolved_snapshot(draft_id, snapshot.snapshot_id)

        final_subdir = f"template_{template.template_id}/snapshot_{snapshot.snapshot_id}"
        artifact_root = self.template_service.artifact_store.root_path
        if artifact_root is None:
            raise ContractTemplateExportError("Managed artifact storage is not configured.")
        resolved_root = artifact_root / final_subdir / f"resolved_html_{uuid.uuid4().hex[:10]}"
        clone_html_package_tree(
            source_package_root=working_package_root,
            destination_root=resolved_root,
        )
        final_html_path = resolved_root / relative_html
        final_html_path.parent.mkdir(parents=True, exist_ok=True)
        final_html_path.write_text(rendered_html, encoding="utf-8")
        resolved_html_artifact = self.template_service.create_output_artifact(
            ContractTemplateOutputArtifactPayload(
                snapshot_id=snapshot.snapshot_id,
                artifact_type="resolved_html",
                output_path=str(final_html_path),
                output_filename=final_html_path.name,
                mime_type="text/html",
                size_bytes=len(rendered_html_bytes),
                checksum_sha256=sha256_digest(rendered_html_bytes),
            )
        )
        pdf_path = artifact_root / final_subdir / f"{stem}.pdf"
        self.html_pdf_adapter.render_file_to_pdf(final_html_path, pdf_path)
        pdf_bytes = pdf_path.read_bytes()
        pdf_artifact = self.template_service.create_output_artifact(
            ContractTemplateOutputArtifactPayload(
                snapshot_id=snapshot.snapshot_id,
                artifact_type="pdf",
                output_path=str(pdf_path),
                output_filename=pdf_path.name,
                mime_type="application/pdf",
                size_bytes=len(pdf_bytes),
                checksum_sha256=sha256_digest(pdf_bytes),
            )
        )
        return ContractTemplateExportResult(
            snapshot=snapshot,
            resolved_docx_artifact=None,
            resolved_html_artifact=resolved_html_artifact,
            pdf_artifact=pdf_artifact,
            warnings=warnings,
        )

    def _materialize_html_working_copy(
        self,
        *,
        draft_id: int,
        source_html_path: Path,
        source_package_root: Path,
        rendered_html: str,
    ) -> Path:
        try:
            relative_html = source_html_path.relative_to(source_package_root)
        except Exception:
            relative_html = Path(source_html_path.name)
        draft_root = self.template_service.draft_store.root_path
        if draft_root is None:
            raise ContractTemplateExportError("Managed draft storage is not configured.")
        destination_root = draft_root / f"html_draft_{draft_id}_{uuid.uuid4().hex[:10]}"
        clone_html_package_tree(
            source_package_root=source_package_root,
            destination_root=destination_root,
        )
        target_html_path = destination_root / relative_html
        target_html_path.parent.mkdir(parents=True, exist_ok=True)
        target_html_path.write_text(rendered_html, encoding="utf-8")
        self.template_service.set_draft_working_path(
            draft_id,
            working_path=target_html_path,
            mime_type="text/html",
        )
        html_path = self.template_service.resolve_draft_working_path(draft_id)
        if html_path is None:
            raise ContractTemplateExportError(
                f"Managed HTML draft output could not be resolved for draft {draft_id}."
            )
        return html_path

    @staticmethod
    def _html_output_filename(draft_name: str | None, source_filename: str | None) -> str:
        stem = _slugify(draft_name or Path(str(source_filename or "contract-template")).stem, fallback="contract-template")
        return f"{stem}.html"

    def _export_source_as_docx(
        self,
        *,
        revision,
    ) -> tuple[bytes, str]:
        source_bytes = self.template_service.load_revision_source_bytes(revision.revision_id)
        if str(revision.source_format or "").strip().lower() == "docx":
            return source_bytes, revision.source_filename
        if str(revision.source_format or "").strip().lower() != "pages":
            raise ContractTemplateExportError(
                f"Unsupported template source format for export: {revision.source_format}"
            )
        if self.pages_adapter is None or not self.pages_adapter.is_available():
            raise ContractTemplateExportError(
                self.pages_adapter.availability_message()
                if self.pages_adapter is not None
                else "Pages export is unavailable on this machine."
            )
        with tempfile.TemporaryDirectory(prefix="contract-template-pages-export-") as tmpdir:
            workdir = Path(tmpdir)
            source_name = coalesce_filename(
                revision.source_filename,
                default_stem="contract-template",
                default_suffix=".pages",
            )
            pages_path = workdir / source_name
            if pages_path.suffix.lower() != ".pages":
                pages_path = pages_path.with_suffix(".pages")
            pages_path.write_bytes(source_bytes)
            resolved_docx_path = workdir / f"{pages_path.stem}.docx"
            self.pages_adapter.convert_to_docx(pages_path, resolved_docx_path)
            return resolved_docx_path.read_bytes(), resolved_docx_path.name

    def _replace_docx_placeholders(
        self,
        source_bytes: bytes,
        replacements: dict[str, str],
    ) -> tuple[bytes, tuple[str, ...]]:
        ordered_tokens = tuple(sorted(replacements, key=len, reverse=True))
        warnings: list[str] = []
        rewritten_parts: dict[str, bytes] = {}
        with ZipFile(BytesIO(source_bytes)) as source_archive:
            names = source_archive.namelist()
            for part_name in names:
                part_bytes = source_archive.read(part_name)
                if not _DOCX_PART_RE.match(part_name):
                    rewritten_parts[part_name] = part_bytes
                    continue
                try:
                    root = ET.fromstring(part_bytes)
                except ET.ParseError:
                    rewritten_parts[part_name] = part_bytes
                    warnings.append(f"Skipped unparsable DOCX part during export: {part_name}.")
                    continue
                for element in root.iter():
                    if not element.attrib:
                        continue
                    for attribute_name, attribute_value in list(element.attrib.items()):
                        if not attribute_value:
                            continue
                        element.set(
                            attribute_name,
                            self._replace_tokens_in_text(
                                str(attribute_value),
                                replacements,
                                ordered_tokens,
                            ),
                        )
                for paragraph_index, paragraph in enumerate(
                    root.findall(".//w:p", _DOCX_NS), start=1
                ):
                    text_nodes = paragraph.findall(".//w:t", _DOCX_NS)
                    if not text_nodes:
                        continue
                    before_text = "".join(node.text or "" for node in text_nodes)
                    for node in text_nodes:
                        node.text = self._replace_tokens_in_text(
                            node.text or "",
                            replacements,
                            ordered_tokens,
                        )
                    after_text = "".join(node.text or "" for node in text_nodes)
                    remaining = [token for token in ordered_tokens if token in after_text]
                    if remaining and not self._paragraph_has_layout_nodes(paragraph):
                        replaced_full = self._replace_tokens_in_text(
                            before_text,
                            replacements,
                            ordered_tokens,
                        )
                        if replaced_full != before_text:
                            text_nodes[0].text = replaced_full
                            for node in text_nodes[1:]:
                                node.text = ""
                            warnings.append(
                                f"Collapsed paragraph styling in {part_name} paragraph {paragraph_index} to preserve placeholder replacement."
                            )
                rewritten_parts[part_name] = ET.tostring(
                    root,
                    encoding="utf-8",
                    xml_declaration=True,
                )
        output = BytesIO()
        with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
            for part_name in names:
                archive.writestr(part_name, rewritten_parts[part_name])
        return output.getvalue(), tuple(warnings)

    @staticmethod
    def _replace_tokens_in_text(
        text: str,
        replacements: dict[str, str],
        ordered_tokens: tuple[str, ...],
    ) -> str:
        updated = text
        for token in ordered_tokens:
            updated = updated.replace(token, replacements[token])
        return updated

    @staticmethod
    def _paragraph_has_layout_nodes(paragraph: ET.Element) -> bool:
        for node in paragraph.iter():
            tag = str(node.tag or "")
            if tag.endswith("}tab") or tag.endswith("}br") or tag.endswith("}cr"):
                return True
        return False

    @staticmethod
    def _render_output_value(value: object | None) -> str:
        if value is None:
            return ""
        if isinstance(value, bool):
            return "Yes" if value else "No"
        if isinstance(value, (list, tuple, set)):
            return ", ".join(str(item).strip() for item in value if str(item).strip())
        return str(value)

    def _write_resolved_docx_artifact(
        self,
        *,
        snapshot_id: int,
        docx_bytes: bytes,
        stem: str,
        subdir: str,
    ):
        relative_path = self.template_service.artifact_store.write_bytes(
            docx_bytes,
            filename=f"{stem}.docx",
            subdir=subdir,
        )
        absolute_path = self.template_service.artifact_store.resolve(relative_path)
        if absolute_path is None:
            raise ContractTemplateExportError("Managed artifact storage is not configured.")
        return self.template_service.create_output_artifact(
            ContractTemplateOutputArtifactPayload(
                snapshot_id=snapshot_id,
                artifact_type="resolved_docx",
                output_path=str(absolute_path),
                output_filename=absolute_path.name,
                mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                size_bytes=len(docx_bytes),
                checksum_sha256=sha256_digest(docx_bytes),
            )
        )

    def _write_pdf_artifact(
        self,
        *,
        snapshot_id: int,
        docx_bytes: bytes,
        source_filename: str,
        stem: str,
        subdir: str,
    ):
        with tempfile.TemporaryDirectory(prefix="contract-template-pdf-") as tmpdir:
            workdir = Path(tmpdir)
            pdf_path = workdir / f"{stem}.pdf"
            if self.pages_adapter is not None and self.pages_adapter.is_available():
                docx_path = workdir / coalesce_filename(
                    source_filename,
                    default_stem=stem,
                    default_suffix=".docx",
                )
                if docx_path.suffix.lower() != ".docx":
                    docx_path = docx_path.with_suffix(".docx")
                docx_path.write_bytes(docx_bytes)
                self.pages_adapter.export_to_pdf(docx_path, pdf_path)
            else:
                html_text = self.html_adapter.docx_bytes_to_html(
                    docx_bytes,
                    source_filename=source_filename,
                )
                self._render_html_to_pdf(html_text, pdf_path)
            pdf_bytes = pdf_path.read_bytes()
        relative_path = self.template_service.artifact_store.write_bytes(
            pdf_bytes,
            filename=f"{stem}.pdf",
            subdir=subdir,
        )
        absolute_path = self.template_service.artifact_store.resolve(relative_path)
        if absolute_path is None:
            raise ContractTemplateExportError("Managed artifact storage is not configured.")
        return self.template_service.create_output_artifact(
            ContractTemplateOutputArtifactPayload(
                snapshot_id=snapshot_id,
                artifact_type="pdf",
                output_path=str(absolute_path),
                output_filename=absolute_path.name,
                mime_type="application/pdf",
                size_bytes=len(pdf_bytes),
                checksum_sha256=sha256_digest(pdf_bytes),
            )
        )

    def _pdf_renderer_name(self) -> str:
        if self.pages_adapter is not None and self.pages_adapter.is_available():
            return f"{self.pages_adapter.adapter_name}_pdf"
        return self.html_adapter.adapter_name

    def _ensure_qapplication(self):
        app = QApplication.instance()
        if app is not None:
            return app
        if self._owned_qapp is None:
            self._owned_qapp = QApplication([])
        return self._owned_qapp

    def _render_html_to_pdf(self, html_text: str, output_path: Path) -> None:
        self._ensure_qapplication()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        writer = QPdfWriter(str(output_path))
        writer.setPageSize(QPageSize(QPageSize.A4))
        writer.setPageMargins(QMarginsF(18, 18, 18, 18), QPageLayout.Millimeter)
        document = QTextDocument()
        document.setHtml(html_text)
        document.setPageSize(QSizeF(writer.width(), writer.height()))
        document.print_(writer)

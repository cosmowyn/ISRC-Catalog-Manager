"""Resolved export and PDF generation for contract template workflows."""

from __future__ import annotations

import re
import shutil
import tempfile
import uuid
from datetime import date
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile

from PySide6.QtCore import QEventLoop, QMarginsF, QSizeF, QTimer, QUrl
from PySide6.QtGui import QPageLayout, QPageSize, QPdfWriter, QTextDocument
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication

from isrc_manager.code_registry import CodeRegistryService
from isrc_manager.file_storage import coalesce_filename, sha256_digest
from isrc_manager.invoicing.models import DEFAULT_CURRENCY

from .catalog import registry_binding_for_catalog_entry, registry_binding_for_symbol
from .formatting import DEFAULT_MANUAL_DATE_FORMAT, format_manual_date_value
from .html_support import clone_html_package_tree, decode_html_bytes, replace_html_placeholders
from .ingestion import DOCXHtmlAdapter, PagesTemplateAdapter
from .models import (
    ContractTemplateExportResult,
    ContractTemplateOutputArtifactPayload,
    ContractTemplateResolvedSnapshotPayload,
    build_contract_template_indexed_selection_key,
    build_contract_template_selector_scope_key,
)
from .parser import base_symbol_for_indexed_placeholder, extract_placeholders, parse_placeholder

_DOCX_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
_DOCX_PART_RE = re.compile(r"^word/(document|header\d+|footer\d+)\.xml$")
_SLUG_RE = re.compile(r"[^A-Za-z0-9._-]+")
_DATE_HINT_RE = re.compile(
    r"(^|_)(date|day|deadline|signed|effective|start|end|renewal|termination|reversion|notice)($|_)",
    re.IGNORECASE,
)
_DUPLICATE_START_SYMBOL = "{{duplicate.start}}"
_DUPLICATE_END_SYMBOL = "{{duplicate.end}}"
_DUPLICATE_NUMBER_SYMBOL = "{{duplicate.number}}"
_PAGE_INDEX_SYMBOL = "{{page.index}}"
_PAGE_TOTAL_SYMBOL = "{{page.total}}"
_CUSTOM_INDEX_SYMBOL = "{{custom.index}}"
_DB_INDEX_SYMBOL = "{{db.index}}"
_DUPLICATE_BLOCK_RE = re.compile(
    rf"{re.escape(_DUPLICATE_START_SYMBOL)}(.*?){re.escape(_DUPLICATE_END_SYMBOL)}",
    re.DOTALL,
)
_PAGE_COUNTER_RE = re.compile(rf"{re.escape(_PAGE_INDEX_SYMBOL)}|{re.escape(_PAGE_TOTAL_SYMBOL)}")
_MAX_DUPLICATE_COPIES = 200
_DYNAMIC_INVOICE_TOTAL_KEYS = frozenset(
    {"currency", "subtotal", "vat_total", "total", "lines", "vat_breakdown"}
)
_DEFAULT_SCOPE_ENTITY_BY_NAMESPACE = {
    "track": "track",
    "release": "release",
    "work": "work",
    "contract": "contract",
    "invoice": "invoice",
    "invoice_line": "invoice_catalog_item",
    "royalty": "royalty_statement",
    "royalty_line": "royalty_line_item",
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
    "invoice": "invoice_selection_required",
    "invoice_line": "invoice_catalog_item_selection_required",
    "royalty": "royalty_statement_selection_required",
    "royalty_line": "royalty_line_selection_required",
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


def _use_headless_pdf_fallback() -> bool:
    platform_name = getattr(QApplication, "platformName", None)
    if not callable(platform_name):
        return False
    return (platform_name() or "").strip().lower() == "offscreen"


def _render_file_to_pdf_with_text_document(source: Path, target: Path) -> None:
    document = QTextDocument()
    document.setHtml(source.read_text(encoding="utf-8"))
    writer = QPdfWriter(str(target))
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    writer.setPageMargins(QMarginsF(12, 12, 12, 12), QPageLayout.Unit.Millimeter)
    document.print_(writer)
    if not target.exists() or target.stat().st_size <= 0:
        raise ContractTemplateExportError(f"Headless PDF fallback failed to write: {target}")


class ContractTemplateExportError(RuntimeError):
    """Raised when a contract template draft cannot be resolved or exported."""


class TextutilDocxRenderAdapter(DOCXHtmlAdapter):
    """Converts resolved DOCX bytes to HTML with native tooling and a best-effort fallback."""

    adapter_name = "textutil_docx_html_qt_pdf"


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
        if _use_headless_pdf_fallback():
            _render_file_to_pdf_with_text_document(source, target)
            return target
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

    HTML_PREVIEW_SESSION_DIRNAME = "isrc-catalog-manager-contract-template-previews"

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
        accounting_resolver=None,
        html_adapter: DOCXHtmlAdapter | None = None,
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
        self.accounting_resolver = accounting_resolver
        self.html_adapter = (
            html_adapter
            if html_adapter is not None
            else getattr(self.template_service, "docx_html_adapter", None)
            or TextutilDocxRenderAdapter()
        )
        self.html_pdf_adapter = (
            html_pdf_adapter if html_pdf_adapter is not None else QtWebEngineHtmlPdfAdapter()
        )
        self.pages_adapter = (
            pages_adapter if pages_adapter is not None else self.template_service.pages_adapter
        )
        self._code_registry_service = None
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
        if not self.template_service.revision_supports_html_working_draft(revision.revision_id):
            raise ContractTemplateExportError(
                "The selected template revision cannot be normalized into an HTML working draft "
                "on this machine."
            )
        return self._export_html_payload_to_pdf(
            revision=revision,
            template=template,
            editable_payload=editable_map,
            draft_id=draft_id,
            draft_name=draft_name,
        )

    def _resolve_payload_values(
        self,
        revision_id: int,
        editable_payload: dict[str, object],
        *,
        strict: bool = True,
        draft_id: int | None = None,
        allow_registry_generation: bool = False,
        duplicate_iterated_symbols: set[str] | None = None,
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
        manual_formats = dict(editable_payload.get("manual_formats") or {})
        invoice_line_inputs = dict(editable_payload.get("invoice_line_inputs") or {})
        iterated_symbols = set(duplicate_iterated_symbols or set())
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
            if token.binding_kind == "current":
                resolved[canonical] = self._resolve_current_value(token.key)
                continue
            if token.binding_kind in {"page", "custom"}:
                resolved[canonical] = ""
                continue
            if token.binding_kind == "db_index":
                resolved[canonical] = ""
                continue
            if token.binding_kind == "duplicate":
                if token.key == "number":
                    if canonical not in manual_values:
                        if strict:
                            raise ContractTemplateExportError(
                                f"Duplicate control placeholder {canonical} does not have a saved value."
                            )
                    else:
                        self._duplicate_copy_count(manual_values.get(canonical), strict=strict)
                resolved[canonical] = ""
                continue
            if token.binding_kind == "manual":
                if token.indexed and canonical in iterated_symbols:
                    resolved[canonical] = ""
                    continue
                if canonical not in manual_values:
                    if strict:
                        raise ContractTemplateExportError(
                            f"Manual placeholder {canonical} does not have a saved value."
                        )
                    continue
                if self._is_manual_date_placeholder(
                    placeholder,
                    binding=bindings.get(canonical),
                ):
                    resolved[canonical] = format_manual_date_value(
                        manual_values.get(canonical),
                        manual_formats.get(canonical) or DEFAULT_MANUAL_DATE_FORMAT,
                    )
                else:
                    resolved[canonical] = self._render_output_value(manual_values.get(canonical))
                continue
            catalog_entry = self._catalog_entry_for_symbol(canonical, catalog)
            if catalog_entry is None:
                if strict:
                    raise ContractTemplateExportError(
                        f"Database-backed placeholder {canonical} is not present in the symbol catalog."
                    )
                warnings.append(
                    f"Skipped {canonical} because it is no longer present in the symbol catalog."
                )
                continue
            if token.indexed and canonical in iterated_symbols:
                resolved[canonical] = ""
                continue
            if str(catalog_entry.namespace or "").strip().lower() == "owner":
                try:
                    resolved_value = self._resolve_catalog_value(
                        catalog_entry=catalog_entry,
                        selection_value=None,
                        draft_id=draft_id,
                        allow_registry_generation=allow_registry_generation,
                        strict=strict,
                    )
                except ContractTemplateExportError:
                    if strict:
                        raise
                    continue
                rendered = self._render_catalog_output_value(
                    catalog_entry=catalog_entry,
                    value=resolved_value,
                )
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
            registry_binding = registry_binding_for_catalog_entry(
                getattr(catalog_entry, "namespace", None),
                getattr(catalog_entry, "key", None),
            )
            if selection_value is None:
                handled, dynamic_value = self._dynamic_invoice_value_for_placeholder(
                    catalog_entry=catalog_entry,
                    db_selections=db_selections,
                    invoice_line_inputs=invoice_line_inputs,
                    strict=strict,
                )
                if handled:
                    resolved[canonical] = self._render_catalog_output_value(
                        catalog_entry=catalog_entry,
                        value=dynamic_value,
                    )
                    continue
                if canonical in iterated_symbols:
                    resolved[canonical] = ""
                    continue
                if strict and not (registry_binding is not None and draft_id is not None):
                    raise ContractTemplateExportError(
                        f"Database-backed placeholder {canonical} does not have a selected record."
                    )
                if registry_binding is None or draft_id is None:
                    continue
            try:
                resolved_value = self._resolve_catalog_value(
                    catalog_entry=catalog_entry,
                    selection_value=selection_value,
                    line_input=self._invoice_line_input_for_selection_key(
                        canonical,
                        invoice_line_inputs,
                    ),
                    draft_id=draft_id,
                    allow_registry_generation=allow_registry_generation,
                    strict=strict,
                )
            except ContractTemplateExportError:
                if strict:
                    raise
                warnings.append(
                    f"Skipped {canonical} because its selected record could not be resolved."
                )
                continue
            rendered = self._render_catalog_output_value(
                catalog_entry=catalog_entry,
                value=resolved_value,
            )
            if (
                not strict
                and str(catalog_entry.namespace or "").strip().lower() == "invoice"
                and str(catalog_entry.key or "").strip().lower() == "number"
                and str(rendered or "").startswith("DRAFT-")
            ):
                warnings.append(
                    "Invoice number is showing the draft display ID; issue the invoice before strict export."
                )
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

    @staticmethod
    def _resolve_current_value(key: str) -> str:
        if str(key or "").strip().lower() == "year":
            return str(date.today().year)
        return ""

    def _runtime_replacements_for_text(
        self,
        text: str,
        resolved_values: dict[str, str],
    ) -> dict[str, str]:
        replacements: dict[str, str] = {}
        if "{{current.year}}" in str(text or "") and "{{current.year}}" not in resolved_values:
            replacements["{{current.year}}"] = self._resolve_current_value("year")
        return replacements

    @staticmethod
    def _is_manual_date_placeholder(placeholder, *, binding) -> bool:
        if binding is not None and isinstance(getattr(binding, "validation", None), dict):
            field_type = str(binding.validation.get("field_type") or "").strip().lower()
            if field_type == "date":
                return True
            if field_type:
                return False
        inferred = str(getattr(placeholder, "inferred_field_type", "") or "").strip().lower()
        if inferred == "date":
            return True
        key = str(getattr(placeholder, "placeholder_key", "") or "").strip().lower()
        return bool(_DATE_HINT_RE.search(key))

    @staticmethod
    def _duplicate_copy_count(value: object | None, *, strict: bool) -> int | None:
        text = str(value if value is not None else "").strip()
        if not text:
            if strict:
                raise ContractTemplateExportError(
                    "Duplicate Number is required when duplicate block cymbols are present."
                )
            return None
        try:
            number = float(text)
        except ValueError as exc:
            raise ContractTemplateExportError("Duplicate Number must be a whole number.") from exc
        if not number.is_integer():
            raise ContractTemplateExportError("Duplicate Number must be a whole number.")
        count = int(number)
        if count < 0:
            raise ContractTemplateExportError("Duplicate Number cannot be negative.")
        if count > _MAX_DUPLICATE_COPIES:
            raise ContractTemplateExportError(
                f"Duplicate Number cannot be greater than {_MAX_DUPLICATE_COPIES}."
            )
        return count

    @staticmethod
    def _catalog_entry_for_symbol(
        canonical_symbol: str,
        catalog: dict[str, object],
    ) -> object | None:
        base_symbol = base_symbol_for_indexed_placeholder(canonical_symbol)
        return catalog.get(base_symbol or canonical_symbol)

    @staticmethod
    def _coerce_record_id(value: object | None) -> int | None:
        try:
            record_id = int(str(value if value is not None else "").strip())
        except TypeError, ValueError:
            return None
        return record_id if record_id > 0 else None

    def _indexed_db_symbols_for_text(self, text: str) -> tuple[str, ...]:
        catalog = {
            item.canonical_symbol: item for item in self.catalog_service.list_known_symbols()
        }
        symbols: list[str] = []
        for occurrence in extract_placeholders(str(text or "")):
            token = occurrence.token
            if token.binding_kind != "db" or not token.indexed:
                continue
            base_symbol = base_symbol_for_indexed_placeholder(token.canonical_symbol)
            if base_symbol not in catalog:
                continue
            symbols.append(token.canonical_symbol)
        return tuple(dict.fromkeys(symbols))

    def _indexed_manual_symbols_for_text(self, text: str) -> tuple[str, ...]:
        symbols: list[str] = []
        for occurrence in extract_placeholders(str(text or "")):
            token = occurrence.token
            if token.binding_kind != "manual" or not token.indexed:
                continue
            symbols.append(token.canonical_symbol)
        return tuple(dict.fromkeys(symbols))

    def _duplicate_iterated_indexed_symbols(
        self,
        html_text: str,
    ) -> set[str]:
        block_symbols: set[str] = set()
        for match in _DUPLICATE_BLOCK_RE.finditer(str(html_text or "")):
            block_symbols.update(self._indexed_db_symbols_for_text(str(match.group(1) or "")))
            block_symbols.update(self._indexed_manual_symbols_for_text(str(match.group(1) or "")))
        if not block_symbols:
            return set()
        outside_duplicate_blocks = _DUPLICATE_BLOCK_RE.sub("", str(html_text or ""))
        outside_symbols = set(self._indexed_db_symbols_for_text(outside_duplicate_blocks))
        outside_symbols.update(self._indexed_manual_symbols_for_text(outside_duplicate_blocks))
        return block_symbols - outside_symbols

    def _indexed_manual_replacements(
        self,
        *,
        symbols: tuple[str, ...],
        index: int,
        manual_values: dict[str, object],
        manual_formats: dict[str, str],
        strict: bool,
        warnings: list[str],
    ) -> dict[str, str]:
        replacements: dict[str, str] = {}
        for symbol in symbols:
            token = parse_placeholder(symbol)
            selection_key = build_contract_template_indexed_selection_key(symbol, index)
            if selection_key not in manual_values:
                message = (
                    f"Indexed manual placeholder {symbol} at Duplicate Index {index} does not have "
                    "a saved value."
                )
                if strict:
                    raise ContractTemplateExportError(message)
                warnings.append(message)
                replacements[symbol] = ""
                continue
            value = manual_values.get(selection_key)
            if self._is_manual_date_placeholder(
                SimpleNamespace(
                    inferred_field_type="",
                    placeholder_key=token.key,
                ),
                binding=None,
            ):
                replacements[symbol] = format_manual_date_value(
                    value,
                    manual_formats.get(selection_key) or DEFAULT_MANUAL_DATE_FORMAT,
                )
            else:
                replacements[symbol] = self._render_output_value(value)
        return replacements

    def _indexed_db_replacements(
        self,
        *,
        symbols: tuple[str, ...],
        index: int,
        db_selections: dict[str, object],
        invoice_line_inputs: dict[str, object] | None = None,
        draft_id: int | None,
        allow_registry_generation: bool,
        strict: bool,
        warnings: list[str],
    ) -> dict[str, str]:
        catalog = {
            item.canonical_symbol: item for item in self.catalog_service.list_known_symbols()
        }
        replacements: dict[str, str] = {}
        for symbol in symbols:
            catalog_entry = self._catalog_entry_for_symbol(symbol, catalog)
            if catalog_entry is None:
                continue
            selection_key, selection_value = self._indexed_db_selection_for_symbol(
                symbol=symbol,
                index=index,
                db_selections=db_selections,
            )
            if selection_value is None:
                message = (
                    f"Indexed placeholder {symbol} at DB Index {index} does not have "
                    "a selected record."
                )
                if strict:
                    raise ContractTemplateExportError(message)
                warnings.append(message)
                replacements[symbol] = ""
                continue
            try:
                resolved_value = self._resolve_catalog_value(
                    catalog_entry=catalog_entry,
                    selection_value=selection_value,
                    line_input=self._invoice_line_input_for_selection_key(
                        selection_key,
                        dict(invoice_line_inputs or {}),
                    ),
                    draft_id=draft_id,
                    allow_registry_generation=allow_registry_generation,
                    strict=strict,
                )
            except ContractTemplateExportError:
                if strict:
                    raise
                warnings.append(
                    f"Skipped {symbol} at DB Index {index} because it could not be resolved."
                )
                continue
            replacements[symbol] = self._render_catalog_output_value(
                catalog_entry=catalog_entry,
                value=resolved_value,
            )
        return replacements

    def _indexed_db_selection_for_symbol(
        self,
        *,
        symbol: str,
        index: int,
        db_selections: dict[str, object],
    ) -> tuple[str, object | None]:
        selection_key = build_contract_template_indexed_selection_key(symbol, index)
        selection_value = db_selections.get(selection_key)
        if selection_value is not None:
            return selection_key, selection_value
        try:
            token = parse_placeholder(symbol)
        except ValueError:
            return selection_key, None
        for candidate_key, candidate_value in db_selections.items():
            if candidate_value is None:
                continue
            clean_key = str(candidate_key or "").strip()
            if self._indexed_selection_index(clean_key) != index:
                continue
            base_key = clean_key.rsplit("#index:", 1)[0]
            try:
                candidate_token = parse_placeholder(base_key)
            except ValueError:
                continue
            if (
                candidate_token.binding_kind == token.binding_kind == "db"
                and candidate_token.namespace == token.namespace
            ):
                return clean_key, candidate_value
        return selection_key, None

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

    @staticmethod
    def _indexed_selection_index(selection_key: object | None) -> int | None:
        text = str(selection_key or "").strip()
        marker = "#index:"
        if marker not in text:
            return None
        _prefix, raw_index = text.rsplit(marker, 1)
        try:
            index = int(raw_index)
        except ValueError:
            return None
        return index if index > 0 else None

    @staticmethod
    def _line_input_quantity(line_input: object | None) -> object | None:
        if isinstance(line_input, dict):
            return line_input.get("quantity")
        return line_input

    def _invoice_line_input_for_selection_key(
        self,
        selection_key: object,
        invoice_line_inputs: dict[str, object],
    ) -> object | None:
        clean_key = str(selection_key or "").strip()
        if clean_key in invoice_line_inputs:
            return invoice_line_inputs[clean_key]
        index = self._indexed_selection_index(clean_key)
        if index is None:
            return None
        for candidate_key, candidate_value in invoice_line_inputs.items():
            if self._indexed_selection_index(candidate_key) == index:
                return candidate_value
        return None

    def _invoice_line_rows_from_payload(
        self,
        *,
        db_selections: dict[str, object],
        invoice_line_inputs: dict[str, object],
        strict: bool,
    ) -> tuple[dict[str, object], ...]:
        if self.accounting_resolver is None:
            if strict:
                raise ContractTemplateExportError(
                    "Invoice catalog line calculation is unavailable for export."
                )
            return ()
        grouped: dict[str, tuple[int, object, object | None]] = {}
        for selection_key, selection_value in db_selections.items():
            clean_key = str(selection_key or "").strip()
            base_key = clean_key.rsplit("#index:", 1)[0]
            try:
                token = parse_placeholder(base_key)
            except ValueError:
                continue
            if token.binding_kind != "db" or token.namespace != "invoice_line":
                continue
            index = self._indexed_selection_index(clean_key)
            group_key = f"index:{index}" if index is not None else "single"
            if group_key in grouped:
                continue
            grouped[group_key] = (
                index or 0,
                selection_value,
                self._invoice_line_input_for_selection_key(clean_key, invoice_line_inputs),
            )
        rows: list[dict[str, object]] = []
        for _index, selection_value, line_input in sorted(
            grouped.values(), key=lambda item: item[0]
        ):
            record_id = self._coerce_record_id(selection_value)
            if record_id is None:
                continue
            try:
                rows.append(
                    self.accounting_resolver.preview_invoice_catalog_line(
                        record_id,
                        quantity=self._line_input_quantity(line_input),
                    )
                )
            except ValueError as exc:
                if strict:
                    raise ContractTemplateExportError(str(exc)) from exc
        return tuple(rows)

    @staticmethod
    def _currency_for_invoice_line_rows(rows: tuple[dict[str, object], ...]) -> str:
        currencies = tuple(
            dict.fromkeys(str(row.get("currency") or "").strip().upper() for row in rows)
        )
        currencies = tuple(currency for currency in currencies if currency)
        if not currencies:
            return DEFAULT_CURRENCY
        if len(currencies) > 1:
            raise ContractTemplateExportError(
                "Calculated invoice totals require all selected catalog items to use one currency."
            )
        return currencies[0]

    def _dynamic_invoice_value_for_placeholder(
        self,
        *,
        catalog_entry,
        db_selections: dict[str, object],
        invoice_line_inputs: dict[str, object],
        strict: bool,
    ) -> tuple[bool, object | None]:
        namespace = str(getattr(catalog_entry, "namespace", "") or "").strip().lower()
        key = str(getattr(catalog_entry, "key", "") or "").strip().lower()
        if namespace != "invoice":
            return False, None
        if key.startswith(("party_", "buyer_")):
            party_id = self._party_id_from_db_selections(db_selections)
            if party_id is not None and self.accounting_resolver is not None:
                party_key = key.removeprefix("party_").removeprefix("buyer_")
                if party_key == "name":
                    party_key = "name"
                return True, self.accounting_resolver._resolve_party_key(party_id, party_key) or ""
            return False, None
        if key not in _DYNAMIC_INVOICE_TOTAL_KEYS:
            return False, None
        rows = self._invoice_line_rows_from_payload(
            db_selections=db_selections,
            invoice_line_inputs=invoice_line_inputs,
            strict=strict,
        )
        if not rows:
            return False, None
        if self.accounting_resolver is None:
            return False, None
        currency = self._currency_for_invoice_line_rows(rows)
        if key == "currency":
            return True, currency
        if key == "subtotal":
            return True, self._format_money(
                sum(int(row["net_amount_minor"] or 0) for row in rows), currency=currency
            )
        if key == "vat_total":
            return True, self._format_money(
                sum(int(row["vat_amount_minor"] or 0) for row in rows), currency=currency
            )
        if key == "total":
            return True, self._format_money(
                sum(int(row["gross_amount_minor"] or 0) for row in rows), currency=currency
            )
        if key == "lines":
            return True, self.accounting_resolver.render_calculated_invoice_lines_table(rows)
        if key == "vat_breakdown":
            return True, self.accounting_resolver.render_calculated_invoice_vat_table(rows)
        return False, None

    @staticmethod
    def _party_id_from_db_selections(db_selections: dict[str, object]) -> int | None:
        for selection_key, selection_value in db_selections.items():
            clean_key = str(selection_key or "").strip()
            if clean_key.startswith("db_scope.party."):
                try:
                    return int(str(selection_value).strip())
                except TypeError, ValueError:
                    return None
        for selection_key, selection_value in db_selections.items():
            clean_key = str(selection_key or "").strip().rsplit("#index:", 1)[0]
            try:
                token = parse_placeholder(clean_key)
            except ValueError:
                continue
            if token.binding_kind == "db" and token.namespace == "party":
                try:
                    return int(str(selection_value).strip())
                except TypeError, ValueError:
                    return None
        return None

    @staticmethod
    def _format_money(minor_units: int, *, currency: str) -> str:
        from isrc_manager.invoicing.money import format_money

        return format_money(int(minor_units), currency=currency)

    def _resolve_catalog_value(
        self,
        *,
        catalog_entry,
        selection_value: object | None,
        line_input: object | None = None,
        draft_id: int | None = None,
        allow_registry_generation: bool = False,
        strict: bool = True,
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
        registry_binding = registry_binding_for_catalog_entry(namespace, key)
        if registry_binding is not None and draft_id is not None:
            return self._resolve_draft_registry_value(
                draft_id=draft_id,
                canonical_symbol=catalog_entry.canonical_symbol,
                registry_binding=registry_binding,
                allow_generation=allow_registry_generation,
            )
        clean_selection = _clean_text(selection_value)
        if clean_selection is None:
            raise ContractTemplateExportError(
                f"{catalog_entry.canonical_symbol} does not have a selected record."
            )
        record_id = int(clean_selection)
        if namespace == "invoice":
            if self.accounting_resolver is None:
                raise ContractTemplateExportError(
                    "Invoice placeholder resolution is unavailable for export."
                )
            try:
                return self.accounting_resolver.resolve_invoice_value(
                    key,
                    record_id,
                    strict=strict,
                )
            except ValueError as exc:
                raise ContractTemplateExportError(str(exc)) from exc
        if namespace == "invoice_line":
            if self.accounting_resolver is None:
                raise ContractTemplateExportError(
                    "Invoice line placeholder resolution is unavailable for export."
                )
            try:
                return self.accounting_resolver.resolve_invoice_catalog_line_value(
                    key,
                    record_id,
                    quantity=self._line_input_quantity(line_input),
                )
            except ValueError as exc:
                raise ContractTemplateExportError(str(exc)) from exc
        if namespace == "royalty":
            if self.accounting_resolver is None:
                raise ContractTemplateExportError(
                    "Royalty placeholder resolution is unavailable for export."
                )
            try:
                return self.accounting_resolver.resolve_royalty_value(
                    key,
                    record_id,
                    strict=strict,
                )
            except ValueError as exc:
                raise ContractTemplateExportError(str(exc)) from exc
        if namespace == "royalty_line":
            if self.accounting_resolver is None:
                raise ContractTemplateExportError(
                    "Royalty line placeholder resolution is unavailable for export."
                )
            try:
                return self.accounting_resolver.resolve_royalty_line_value(key, record_id)
            except ValueError as exc:
                raise ContractTemplateExportError(str(exc)) from exc
        if allow_registry_generation and registry_binding is not None:
            try:
                return self._generate_unlinked_registry_value(
                    registry_binding=registry_binding,
                    created_via="contract_template.export.generate",
                )
            except ValueError as exc:
                raise ContractTemplateExportError(str(exc)) from exc
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

    def code_registry_service(self):
        return self._shared_code_registry_service()

    def _shared_code_registry_service(self):
        if self._code_registry_service is None:
            conn = getattr(self.template_service, "conn", None)
            if conn is None:
                raise ContractTemplateExportError("Code registry service is unavailable.")
            self._code_registry_service = CodeRegistryService(conn)
        return self._code_registry_service

    def _registry_service_for_binding(self, registry_binding):
        if registry_binding.owner_kind == "contract":
            if self.contract_service is None:
                raise ContractTemplateExportError(
                    "Contract service is unavailable for draft-backed registry generation."
                )
            registry_service = self.contract_service.code_registry_service()
        elif registry_binding.owner_kind == "track":
            if self.track_service is None:
                raise ContractTemplateExportError(
                    "Track service is unavailable for draft-backed registry generation."
                )
            registry_service = self.track_service.code_registry_service()
        elif registry_binding.owner_kind == "release":
            if self.release_service is None:
                raise ContractTemplateExportError(
                    "Release service is unavailable for draft-backed registry generation."
                )
            registry_service = self.release_service.code_registry_service()
        elif registry_binding.owner_kind == "invoice":
            registry_service = self._shared_code_registry_service()
        else:
            registry_service = None
        if registry_service is None:
            raise ContractTemplateExportError("Code registry service is unavailable.")
        return registry_service

    def validate_draft_registry_generation_for_revision(self, revision_id: int) -> None:
        seen: set[str] = set()
        for placeholder in self.template_service.list_placeholders(int(revision_id)):
            registry_binding = registry_binding_for_symbol(placeholder.canonical_symbol)
            if registry_binding is None or registry_binding.system_key in seen:
                continue
            seen.add(registry_binding.system_key)
            registry_service = self._registry_service_for_binding(registry_binding)
            reason = registry_service.generation_unavailable_reason(
                system_key=registry_binding.system_key
            )
            if reason:
                raise ContractTemplateExportError(
                    f"{placeholder.canonical_symbol} cannot be issued for this draft: {reason}"
                )

    def _generate_unlinked_registry_value(
        self,
        *,
        registry_binding,
        created_via: str,
    ) -> str:
        registry_service = self._registry_service_for_binding(registry_binding)
        category = registry_service.fetch_category_by_system_key(registry_binding.system_key)
        if category is None:
            raise ContractTemplateExportError(
                f"Registry category '{registry_binding.system_key}' is not available."
            )
        result = (
            registry_service.generate_sha256_key(
                category_id=category.id,
                created_via=created_via,
            )
            if str(category.generation_strategy or "").strip().lower() == "sha256"
            else registry_service.generate_next_code(
                category_id=category.id,
                created_via=created_via,
            )
        )
        return result.entry.value

    def _resolve_draft_registry_value(
        self,
        *,
        draft_id: int,
        canonical_symbol: str,
        registry_binding,
        allow_generation: bool,
    ) -> str | None:
        assignment = self.template_service.fetch_draft_registry_assignment(
            int(draft_id),
            canonical_symbol,
        )
        if assignment is not None:
            return assignment.registry_value
        if not allow_generation:
            return None
        try:
            registry_service = self._registry_service_for_binding(registry_binding)
            category = registry_service.fetch_category_by_system_key(registry_binding.system_key)
            if category is None:
                raise ContractTemplateExportError(
                    f"Registry category '{registry_binding.system_key}' is not available."
                )
            result = (
                registry_service.generate_sha256_key(
                    category_id=category.id,
                    created_via="contract_template.export.generate",
                )
                if str(category.generation_strategy or "").strip().lower() == "sha256"
                else registry_service.generate_next_code(
                    category_id=category.id,
                    created_via="contract_template.export.generate",
                )
            )
            created = self.template_service.ensure_draft_registry_assignment(
                int(draft_id),
                canonical_symbol=canonical_symbol,
                system_key=registry_binding.system_key,
                owner_kind=registry_binding.owner_kind,
                registry_entry_id=result.entry.id,
            )
            return created.registry_value
        except ValueError as exc:
            raise ContractTemplateExportError(str(exc)) from exc

    def ensure_registry_assignments_for_draft(
        self,
        draft_id: int,
        *,
        created_via: str = "contract_template.draft.generate",
    ) -> dict[str, str]:
        draft = self.template_service.fetch_draft(int(draft_id))
        if draft is None:
            raise ContractTemplateExportError(f"Contract template draft {int(draft_id)} not found")
        self.validate_draft_registry_generation_for_revision(draft.revision_id)
        values: dict[str, str] = {}
        for placeholder in self.template_service.list_placeholders(draft.revision_id):
            registry_binding = registry_binding_for_symbol(placeholder.canonical_symbol)
            if registry_binding is None:
                continue
            values[placeholder.canonical_symbol] = (
                self._resolve_draft_registry_value(
                    draft_id=int(draft_id),
                    canonical_symbol=placeholder.canonical_symbol,
                    registry_binding=registry_binding,
                    allow_generation=True,
                )
                or ""
            )
        return values

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
        editable_payload = dict(self.template_service.fetch_draft_payload(draft_id) or {})
        source_html_path = self.template_service.ensure_html_revision_source_path(
            revision.revision_id
        )
        if source_html_path is None:
            raise ContractTemplateExportError(
                f"HTML working draft source is unavailable for revision {revision.revision_id}."
            )
        rendered_html, source_package_root, _warnings = self._render_html_content(
            revision=revision,
            editable_payload=editable_payload,
            strict=require_complete,
            draft_id=int(draft_id),
            allow_registry_generation=False,
        )
        return self._materialize_html_working_copy(
            draft_id=draft_id,
            source_html_path=source_html_path,
            source_package_root=source_package_root,
            rendered_html=rendered_html,
        )

    def html_preview_sessions_root(self) -> Path:
        root = Path(tempfile.gettempdir()) / self.HTML_PREVIEW_SESSION_DIRNAME
        root.mkdir(parents=True, exist_ok=True)
        return root

    def create_html_preview_session_root(self) -> Path:
        root = self.html_preview_sessions_root()
        session_root = root / f"preview_{uuid.uuid4().hex[:12]}"
        session_root.mkdir(parents=True, exist_ok=True)
        return session_root

    def prune_html_preview_sessions(self, *, keep_paths: tuple[Path | str, ...] = ()) -> None:
        root = self.html_preview_sessions_root()
        keep_resolved: set[Path] = set()
        for candidate in keep_paths:
            try:
                keep_resolved.add(Path(candidate).resolve())
            except Exception:
                continue
        for child in root.iterdir():
            try:
                resolved = child.resolve()
            except Exception:
                resolved = child
            if resolved in keep_resolved:
                continue
            shutil.rmtree(child, ignore_errors=True)

    def materialize_html_preview_session(
        self,
        *,
        revision_id: int,
        editable_payload: object,
        draft_id: int | None = None,
        session_root: str | Path | None = None,
        strict: bool = False,
    ) -> tuple[Path, Path, tuple[str, ...]]:
        revision = self.template_service.fetch_revision(revision_id)
        if revision is None:
            raise ContractTemplateExportError(f"Contract template revision {revision_id} not found")
        source_html_path = self.template_service.ensure_html_revision_source_path(revision_id)
        if source_html_path is None:
            raise ContractTemplateExportError(
                f"HTML working draft source is unavailable for revision {revision_id}."
            )
        rendered_html, source_package_root, warnings = self._render_html_content(
            revision=revision,
            editable_payload=dict(editable_payload or {}),
            strict=bool(strict),
            draft_id=draft_id,
            allow_registry_generation=False,
        )
        target_root = (
            Path(session_root).resolve()
            if session_root is not None
            else self.create_html_preview_session_root().resolve()
        )
        target_root.mkdir(parents=True, exist_ok=True)
        try:
            relative_html = source_html_path.relative_to(source_package_root)
        except Exception:
            relative_html = Path(source_html_path.name)
        clone_html_package_tree(
            source_package_root=source_package_root,
            destination_root=target_root,
        )
        target_html_path = target_root / relative_html
        target_html_path.parent.mkdir(parents=True, exist_ok=True)
        target_html_path.write_text(rendered_html, encoding="utf-8")
        return target_root, target_html_path, warnings

    def _render_html_content(
        self,
        *,
        revision,
        editable_payload: dict[str, object],
        strict: bool,
        draft_id: int | None = None,
        allow_registry_generation: bool = False,
    ) -> tuple[str, Path, tuple[str, ...]]:
        source_html_path = self.template_service.ensure_html_revision_source_path(
            revision.revision_id
        )
        if source_html_path is None:
            raise ContractTemplateExportError(
                f"HTML working draft source is unavailable for revision {revision.revision_id}."
            )
        package_root = self.template_service.resolve_html_revision_bundle_root(revision.revision_id)
        if package_root is None:
            package_root = source_html_path.parent
        raw_html = decode_html_bytes(source_html_path.read_bytes())
        duplicate_iterated_symbols = self._duplicate_iterated_indexed_symbols(raw_html)
        resolved_values, warnings = self._resolve_payload_values(
            revision.revision_id,
            editable_payload,
            strict=strict,
            draft_id=draft_id,
            allow_registry_generation=allow_registry_generation,
            duplicate_iterated_symbols=duplicate_iterated_symbols,
        )
        source_html, duplicate_warnings = self._apply_duplicate_controls(
            raw_html,
            editable_payload,
            strict=strict,
            draft_id=draft_id,
            allow_registry_generation=allow_registry_generation,
        )
        source_html = self._apply_index_controls(source_html)
        effective_replacements = {
            **resolved_values,
            **self._runtime_replacements_for_text(raw_html, resolved_values),
        }
        rendered_html = replace_html_placeholders(
            source_html,
            effective_replacements,
            raw_tokens=self._html_fragment_replacement_tokens(effective_replacements),
        )
        return rendered_html, package_root, tuple(dict.fromkeys((*warnings, *duplicate_warnings)))

    def _html_fragment_replacement_tokens(self, replacements: dict[str, object]) -> tuple[str, ...]:
        catalog = {
            item.canonical_symbol: item for item in self.catalog_service.list_known_symbols()
        }
        raw_tokens: list[str] = []
        for token in replacements:
            catalog_entry = self._catalog_entry_for_symbol(str(token), catalog)
            field_type = str(getattr(catalog_entry, "field_type", "") or "").strip().lower()
            if field_type == "html_fragment":
                raw_tokens.append(str(token))
        return tuple(raw_tokens)

    def _apply_duplicate_controls(
        self,
        html_text: str,
        editable_payload: dict[str, object],
        *,
        strict: bool,
        draft_id: int | None = None,
        allow_registry_generation: bool = False,
    ) -> tuple[str, tuple[str, ...]]:
        rendered = str(html_text or "")
        has_start = _DUPLICATE_START_SYMBOL in rendered
        has_end = _DUPLICATE_END_SYMBOL in rendered
        has_number = _DUPLICATE_NUMBER_SYMBOL in rendered
        has_db_index = _DB_INDEX_SYMBOL in rendered
        if not (has_start or has_end or has_number or has_db_index):
            return rendered, ()
        manual_values = dict(editable_payload.get("manual_values") or {})
        db_selections = dict(editable_payload.get("db_selections") or {})
        manual_formats = dict(editable_payload.get("manual_formats") or {})
        invoice_line_inputs = dict(editable_payload.get("invoice_line_inputs") or {})
        count = self._duplicate_copy_count(
            manual_values.get(_DUPLICATE_NUMBER_SYMBOL),
            strict=strict,
        )
        warnings: list[str] = []
        matched = False
        missing_count_warning_added = False

        def _repeat_block(match: re.Match[str]) -> str:
            nonlocal matched, missing_count_warning_added
            matched = True
            block = str(match.group(1) or "")
            indexed_symbols = self._indexed_db_symbols_for_text(block)
            indexed_manual_symbols = self._indexed_manual_symbols_for_text(block)
            if count is None:
                copy_count = 1
                message = "Duplicate block preview uses one copy until Duplicate Number is set."
                if not missing_count_warning_added:
                    warnings.append(message)
                    missing_count_warning_added = True
            else:
                copy_count = int(count)
            if not (indexed_symbols or indexed_manual_symbols or _DB_INDEX_SYMBOL in block):
                return block * copy_count
            rendered_blocks: list[str] = []
            for index in range(1, copy_count + 1):
                replacements = {_DB_INDEX_SYMBOL: str(index)}
                replacements.update(
                    self._indexed_db_replacements(
                        symbols=indexed_symbols,
                        index=index,
                        db_selections=db_selections,
                        invoice_line_inputs=invoice_line_inputs,
                        draft_id=draft_id,
                        allow_registry_generation=allow_registry_generation,
                        strict=strict,
                        warnings=warnings,
                    )
                )
                replacements.update(
                    self._indexed_manual_replacements(
                        symbols=indexed_manual_symbols,
                        index=index,
                        manual_values=manual_values,
                        manual_formats=manual_formats,
                        strict=strict,
                        warnings=warnings,
                    )
                )
                rendered_blocks.append(replace_html_placeholders(block, replacements))
            return "".join(rendered_blocks)

        rendered = _DUPLICATE_BLOCK_RE.sub(_repeat_block, rendered)
        if (has_start or has_end) and not matched:
            message = "Duplicate cymbols must use {{duplicate.start}} before {{duplicate.end}}."
            if strict:
                raise ContractTemplateExportError(message)
            warnings.append(message)
        rendered = rendered.replace(_DUPLICATE_START_SYMBOL, "")
        rendered = rendered.replace(_DUPLICATE_END_SYMBOL, "")
        rendered = rendered.replace(_DUPLICATE_NUMBER_SYMBOL, "")
        rendered = rendered.replace(_DB_INDEX_SYMBOL, "")
        return rendered, tuple(warnings)

    def _apply_index_controls(self, html_text: str) -> str:
        rendered = str(html_text or "")
        page_total = rendered.count(_PAGE_INDEX_SYMBOL)
        page_index = 0

        def _replace_page_counter(match: re.Match[str]) -> str:
            nonlocal page_index
            token = match.group(0)
            if token == _PAGE_TOTAL_SYMBOL:
                return str(page_total)
            page_index += 1
            return str(page_index)

        rendered = _PAGE_COUNTER_RE.sub(_replace_page_counter, rendered)
        custom_index = 0

        def _replace_custom_counter(_match: re.Match[str]) -> str:
            nonlocal custom_index
            custom_index += 1
            return str(custom_index)

        return re.sub(re.escape(_CUSTOM_INDEX_SYMBOL), _replace_custom_counter, rendered)

    def _export_html_payload_to_pdf(
        self,
        *,
        revision,
        template,
        editable_payload: dict[str, object],
        draft_id: int,
        draft_name: str | None = None,
    ) -> ContractTemplateExportResult:
        source_html_path = self.template_service.ensure_html_revision_source_path(
            revision.revision_id
        )
        if source_html_path is None:
            raise ContractTemplateExportError(
                f"HTML working draft source is unavailable for revision {revision.revision_id}."
            )
        raw_html = decode_html_bytes(source_html_path.read_bytes())
        duplicate_iterated_symbols = self._duplicate_iterated_indexed_symbols(raw_html)
        resolved_values, resolution_warnings = self._resolve_payload_values(
            revision.revision_id,
            editable_payload,
            strict=True,
            draft_id=int(draft_id),
            allow_registry_generation=True,
            duplicate_iterated_symbols=duplicate_iterated_symbols,
        )
        resolved_docx_bytes = None
        resolved_docx_name = None
        docx_warnings: tuple[str, ...] = ()
        if str(revision.source_format or "").strip().lower() in {"docx", "pages"}:
            resolved_docx_bytes, resolved_docx_name = self._export_source_as_docx(revision=revision)
            resolved_docx_bytes, docx_warnings = self._replace_docx_placeholders(
                resolved_docx_bytes,
                resolved_values,
            )
        rendered_html, source_package_root, html_warnings = self._render_html_content(
            revision=revision,
            editable_payload=editable_payload,
            strict=True,
            draft_id=int(draft_id),
            allow_registry_generation=True,
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
        warnings = tuple(dict.fromkeys((*resolution_warnings, *html_warnings, *docx_warnings)))
        draft_record = self.template_service.fetch_draft(int(draft_id))

        snapshot = self.template_service.create_resolved_snapshot(
            ContractTemplateResolvedSnapshotPayload(
                draft_id=int(draft_id),
                revision_id=revision.revision_id,
                resolved_values=resolved_values,
                resolution_warnings=list(warnings) if warnings else None,
                preview_payload={
                    "renderer": self.html_pdf_adapter.adapter_name,
                    "source_format": revision.source_format,
                    "working_format": "html",
                    "resolved_source_name": working_filename,
                    "working_copy_path": str(working_html_path),
                },
                scope_entity_type=(
                    draft_record.scope_entity_type if draft_record is not None else None
                ),
                scope_entity_id=draft_record.scope_entity_id if draft_record is not None else None,
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
        resolved_docx_artifact = None
        if resolved_docx_bytes is not None and resolved_docx_name is not None:
            resolved_docx_artifact = self._write_resolved_docx_artifact(
                snapshot_id=snapshot.snapshot_id,
                docx_bytes=resolved_docx_bytes,
                stem=_slugify(Path(resolved_docx_name).stem, fallback=stem),
                subdir=final_subdir,
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
            resolved_docx_artifact=resolved_docx_artifact,
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
        stem = _slugify(
            draft_name or Path(str(source_filename or "contract-template")).stem,
            fallback="contract-template",
        )
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

    @classmethod
    def _render_catalog_output_value(cls, *, catalog_entry: object, value: object | None) -> str:
        namespace = str(getattr(catalog_entry, "namespace", "") or "").strip().lower()
        key = str(getattr(catalog_entry, "key", "") or "").strip().lower()
        field_type = str(getattr(catalog_entry, "field_type", "") or "").strip().lower()
        if field_type == "html_fragment":
            return "" if value is None else str(value)
        if namespace == "track" and key == "track_length_sec":
            return cls._render_track_length(value)
        return cls._render_output_value(value)

    @staticmethod
    def _render_track_length(value: object | None) -> str:
        if value is None:
            return ""
        text = str(value).strip()
        if not text:
            return ""
        try:
            seconds = int(float(text))
        except TypeError, ValueError:
            return text
        if seconds < 0:
            return text
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

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

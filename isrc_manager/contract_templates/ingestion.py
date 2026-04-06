"""Template ingestion and placeholder scan helpers for contract templates."""

from __future__ import annotations

import html as html_module
import shutil
import subprocess
import sys
import tempfile
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile

from isrc_manager.file_storage import coalesce_filename

from ..external_launch import run_external_launcher_subprocess
from .html_support import (
    HTMLTemplateBundle,
    build_html_bundle_from_source_bytes,
    collect_html_bundle_from_directory,
)
from .models import (
    ContractTemplateScanDiagnostic,
    ContractTemplateScanEntry,
    ContractTemplateScanOccurrence,
    ContractTemplateScanResult,
)
from .parser import extract_placeholders

SUPPORTED_TEMPLATE_SOURCE_FORMATS = frozenset({"docx", "pages", "html"})

_DOCX_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


class ContractTemplateIngestionError(RuntimeError):
    """Raised when a template source cannot be converted or scanned."""


def detect_template_source_format(
    *,
    source_filename: str | None = None,
    explicit_format: str | None = None,
) -> str:
    suffix = Path(str(source_filename or "").strip()).suffix.lower()
    if suffix == ".docx":
        return "docx"
    if suffix == ".pages":
        return "pages"
    if suffix in {".html", ".htm"}:
        return "html"
    clean_format = str(explicit_format or "").strip().lower().replace("-", "_")
    if suffix == ".zip" and clean_format == "html":
        return "html"
    if clean_format in SUPPORTED_TEMPLATE_SOURCE_FORMATS:
        return clean_format
    raise ContractTemplateIngestionError(
        "Unsupported template source format. Supported contract template sources are "
        ".docx, .pages, and .html. ZIP packages are available only for HTML template imports."
    )


class DOCXTemplateScanner:
    """Scans OOXML Word parts for canonical placeholder tokens."""

    adapter_name = "docx_ooxml_direct"

    def scan_bytes(self, source_bytes: bytes) -> ContractTemplateScanResult:
        try:
            with ZipFile(BytesIO(source_bytes)) as archive:
                part_names = self._scan_parts(archive.namelist())
                if not part_names:
                    return ContractTemplateScanResult(
                        source_format="docx",
                        scan_format="docx",
                        scan_status="scan_blocked",
                        scan_adapter=self.adapter_name,
                        placeholders=(),
                        diagnostics=(
                            ContractTemplateScanDiagnostic(
                                severity="error",
                                code="docx_parts_missing",
                                message="The DOCX file does not contain supported Word body/header/footer XML parts.",
                            ),
                        ),
                    )

                placeholder_map: dict[str, dict[str, object]] = {}
                diagnostics: list[ContractTemplateScanDiagnostic] = []
                for part_name in part_names:
                    try:
                        part_bytes = archive.read(part_name)
                        root = ET.fromstring(part_bytes)
                    except ET.ParseError as exc:
                        diagnostics.append(
                            ContractTemplateScanDiagnostic(
                                severity="warning",
                                code="docx_part_parse_error",
                                message=f"Skipped XML part because it could not be parsed: {exc}",
                                source_part=part_name,
                            )
                        )
                        continue

                    for paragraph_index, paragraph_text in enumerate(
                        self._extract_paragraph_texts(root),
                        start=1,
                    ):
                        for occurrence in extract_placeholders(paragraph_text):
                            token = occurrence.token
                            bucket = placeholder_map.setdefault(
                                token.canonical_symbol,
                                {
                                    "binding_kind": token.binding_kind,
                                    "namespace": token.namespace,
                                    "key": token.key,
                                    "occurrences": [],
                                },
                            )
                            bucket["occurrences"].append(
                                ContractTemplateScanOccurrence(
                                    source_part=part_name,
                                    container_kind="paragraph",
                                    container_index=paragraph_index,
                                    start_index=occurrence.start_index,
                                    end_index=occurrence.end_index,
                                    raw_text=occurrence.raw_text,
                                )
                            )

                placeholders = tuple(
                    ContractTemplateScanEntry(
                        canonical_symbol=canonical_symbol,
                        binding_kind=str(entry["binding_kind"]),
                        namespace=entry["namespace"],
                        key=str(entry["key"]),
                        occurrence_count=len(entry["occurrences"]),
                        occurrences=tuple(entry["occurrences"]),
                    )
                    for canonical_symbol, entry in sorted(placeholder_map.items())
                )
                return ContractTemplateScanResult(
                    source_format="docx",
                    scan_format="docx",
                    scan_status="scan_ready",
                    scan_adapter=self.adapter_name,
                    placeholders=placeholders,
                    diagnostics=tuple(diagnostics),
                )
        except BadZipFile as exc:
            return ContractTemplateScanResult(
                source_format="docx",
                scan_format="docx",
                scan_status="scan_blocked",
                scan_adapter=self.adapter_name,
                placeholders=(),
                diagnostics=(
                    ContractTemplateScanDiagnostic(
                        severity="error",
                        code="docx_bad_zip",
                        message=f"The DOCX file could not be read as an OOXML archive: {exc}",
                    ),
                ),
            )

    @staticmethod
    def _scan_parts(names: list[str]) -> list[str]:
        return [
            name
            for name in sorted(names)
            if name == "word/document.xml"
            or (name.startswith("word/header") and name.endswith(".xml"))
            or (name.startswith("word/footer") and name.endswith(".xml"))
        ]

    def _extract_paragraph_texts(self, root: ET.Element) -> list[str]:
        paragraphs: list[str] = []
        for paragraph in root.findall(".//w:p", _DOCX_NS):
            fragments: list[str] = []
            for node in paragraph.iter():
                tag = self._local_name(node.tag)
                if tag == "t" and node.text:
                    fragments.append(node.text)
                elif tag == "tab":
                    fragments.append("\t")
                elif tag in {"br", "cr"}:
                    fragments.append("\n")
            text = "".join(fragments)
            if text:
                paragraphs.append(text)
        return paragraphs

    @staticmethod
    def _local_name(tag: str) -> str:
        if "}" in tag:
            return tag.rsplit("}", 1)[-1]
        return tag


class DOCXHtmlAdapter:
    """Normalizes DOCX sources into an HTML working bundle."""

    adapter_name = "docx_html_working_draft"

    def __init__(
        self,
        *,
        textutil_path: str | None = None,
        scanner: DOCXTemplateScanner | None = None,
    ):
        self.textutil_path = (
            textutil_path if textutil_path is not None else shutil.which("textutil")
        )
        self.scanner = scanner if scanner is not None else DOCXTemplateScanner()

    def is_available(self) -> bool:
        return True

    def availability_message(self) -> str | None:
        return None

    def docx_bytes_to_html(
        self,
        docx_bytes: bytes,
        *,
        source_filename: str = "contract-template.docx",
    ) -> str:
        bundle = self.docx_bytes_to_html_bundle(
            docx_bytes,
            source_filename=source_filename,
        )
        return bundle.primary_bytes().decode("utf-8", errors="replace")

    def docx_bytes_to_html_bundle(
        self,
        docx_bytes: bytes,
        *,
        source_filename: str = "contract-template.docx",
    ) -> HTMLTemplateBundle:
        try:
            if self._native_textutil_available():
                return self._convert_via_textutil(
                    docx_bytes,
                    source_filename=source_filename,
                )
        except ContractTemplateIngestionError:
            pass
        return self._convert_via_best_effort_html(
            docx_bytes,
            source_filename=source_filename,
        )

    def _native_textutil_available(self) -> bool:
        return sys.platform == "darwin" and bool(self.textutil_path)

    def _convert_via_textutil(
        self,
        docx_bytes: bytes,
        *,
        source_filename: str,
    ) -> HTMLTemplateBundle:
        if not self._native_textutil_available():
            raise ContractTemplateIngestionError(
                "Native DOCX-to-HTML conversion is unavailable on this machine."
            )
        with tempfile.TemporaryDirectory(prefix="contract-template-docx-html-") as tmpdir:
            workdir = Path(tmpdir)
            source_root = workdir / "source"
            rendered_root = workdir / "rendered"
            source_root.mkdir(parents=True, exist_ok=True)
            rendered_root.mkdir(parents=True, exist_ok=True)
            docx_path = source_root / coalesce_filename(
                source_filename,
                default_stem="contract-template",
                default_suffix=".docx",
            )
            if docx_path.suffix.lower() != ".docx":
                docx_path = docx_path.with_suffix(".docx")
            html_path = rendered_root / docx_path.with_suffix(".html").name
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
                raise ContractTemplateIngestionError(
                    "DOCX-to-HTML conversion via textutil failed."
                    + (
                        f" {str(result.stderr or '').strip()}"
                        if str(result.stderr or "").strip()
                        else ""
                    )
                )
            return collect_html_bundle_from_directory(
                rendered_root,
                primary_relative_path=html_path.name,
            )

    def _convert_via_best_effort_html(
        self,
        docx_bytes: bytes,
        *,
        source_filename: str,
    ) -> HTMLTemplateBundle:
        try:
            with ZipFile(BytesIO(docx_bytes)) as archive:
                sections = self._extract_docx_sections(archive)
        except BadZipFile as exc:
            raise ContractTemplateIngestionError(
                f"The DOCX file could not be read as an OOXML archive: {exc}"
            ) from exc
        html_text = self._render_best_effort_html(sections)
        html_filename = Path(
            coalesce_filename(
                source_filename,
                default_stem="contract-template",
                default_suffix=".html",
            )
        ).with_suffix(".html")
        return build_html_bundle_from_source_bytes(
            html_text.encode("utf-8"),
            source_filename=html_filename.name,
        )

    def _extract_docx_sections(self, archive: ZipFile) -> list[tuple[str, str, list[str]]]:
        sections: list[tuple[str, str, list[str]]] = []
        for part_name in self.scanner._scan_parts(archive.namelist()):
            try:
                root = ET.fromstring(archive.read(part_name))
            except ET.ParseError:
                continue
            paragraphs = self.scanner._extract_paragraph_texts(root)
            if not paragraphs:
                continue
            if part_name == "word/document.xml":
                sections.append(("main", part_name, paragraphs))
            elif "header" in part_name:
                sections.append(("header", part_name, paragraphs))
            else:
                sections.append(("footer", part_name, paragraphs))
        if not sections:
            raise ContractTemplateIngestionError(
                "The DOCX file does not contain readable document content."
            )
        return sections

    def _render_best_effort_html(
        self,
        sections: list[tuple[str, str, list[str]]],
    ) -> str:
        fragments = [
            "<!DOCTYPE html>",
            "<html>",
            "<head>",
            '<meta charset="utf-8">',
            "<style>",
            "body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; "
            "margin: 32px; color: #111827; }",
            "header, footer { color: #4b5563; margin: 0 0 20px 0; }",
            "main { margin: 0; }",
            "p { margin: 0 0 12px 0; white-space: normal; }",
            "</style>",
            "</head>",
            "<body>",
        ]
        for role, part_name, paragraphs in sections:
            tag = "main" if role == "main" else role
            fragments.append(
                f'<{tag} data-source-part="{html_module.escape(part_name, quote=True)}">'
            )
            for paragraph in paragraphs:
                fragments.append(f"<p>{self._htmlize_paragraph(paragraph)}</p>")
            fragments.append(f"</{tag}>")
        fragments.extend(["</body>", "</html>"])
        return "".join(fragments)

    @staticmethod
    def _htmlize_paragraph(text: str) -> str:
        escaped = html_module.escape(str(text or ""))
        return escaped.replace("\t", "&emsp;").replace("\n", "<br/>")


class PagesTemplateAdapter:
    """Best-effort `.pages` conversion seam using locally available macOS tooling."""

    adapter_name = "pages_osascript_docx"

    def __init__(
        self,
        *,
        osascript_path: str | None = None,
        textutil_path: str | None = None,
        pages_app_path: str | Path = "/Applications/Pages.app",
    ):
        del textutil_path
        self.osascript_path = (
            osascript_path if osascript_path is not None else shutil.which("osascript")
        )
        self.pages_app_path = Path(pages_app_path)

    def is_available(self) -> bool:
        return (
            sys.platform == "darwin" and bool(self.osascript_path) and self.pages_app_path.exists()
        )

    def availability_message(self) -> str | None:
        if self.is_available():
            return None
        if sys.platform != "darwin":
            return "Pages conversion is only available on macOS hosts."
        if not self.pages_app_path.exists():
            return (
                "Pages conversion is unavailable because Pages.app was not found in /Applications."
            )
        if not self.osascript_path:
            return (
                "Pages conversion is unavailable because the macOS 'osascript' tool was not found."
            )
        return "Pages conversion is unavailable on this machine."

    def convert_to_docx(self, source_path: str | Path, output_path: str | Path) -> Path:
        return self._export_via_pages(
            source_path=source_path,
            output_path=output_path,
            export_kind="Microsoft Word",
            failure_prefix="Pages conversion via Pages.app export failed.",
        )

    def export_to_pdf(self, source_path: str | Path, output_path: str | Path) -> Path:
        return self._export_via_pages(
            source_path=source_path,
            output_path=output_path,
            export_kind="PDF",
            failure_prefix="Pages PDF export via Pages.app failed.",
        )

    def _export_via_pages(
        self,
        *,
        source_path: str | Path,
        output_path: str | Path,
        export_kind: str,
        failure_prefix: str,
    ) -> Path:
        if not self.is_available():
            raise ContractTemplateIngestionError(
                self.availability_message() or "Pages conversion is unavailable."
            )
        source = Path(source_path)
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        script = f"""
set sourcePath to POSIX file "{self._applescript_string(source)}"
set outputPath to POSIX file "{self._applescript_string(target)}"
tell application "Pages"
    set docRef to open sourcePath
    export docRef to outputPath as {export_kind}
    close docRef saving no
end tell
"""
        result = run_external_launcher_subprocess(
            [str(self.osascript_path)],
            input=script,
            capture_output=True,
            text=True,
            source="PagesTemplateAdapter._export_via_pages",
            metadata={
                "integration": "pages_export",
                "export_kind": export_kind,
                "source_path": str(source),
                "output_path": str(target),
            },
        )
        if result.returncode != 0 or not target.exists():
            stderr = str(result.stderr or result.stdout or "").strip()
            raise ContractTemplateIngestionError(failure_prefix + (f" {stderr}" if stderr else ""))
        return target

    @staticmethod
    def _applescript_string(value: str | Path) -> str:
        return str(value).replace("\\", "\\\\").replace('"', '\\"')

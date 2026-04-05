"""Template ingestion and placeholder scan helpers for contract templates."""

from __future__ import annotations

import shutil
import subprocess
import sys
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile

from .html_support import HTMLTemplateScanner
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
        result = subprocess.run(
            [str(self.osascript_path)],
            input=script,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 or not target.exists():
            stderr = str(result.stderr or result.stdout or "").strip()
            raise ContractTemplateIngestionError(failure_prefix + (f" {stderr}" if stderr else ""))
        return target

    @staticmethod
    def _applescript_string(value: str | Path) -> str:
        return str(value).replace("\\", "\\\\").replace('"', '\\"')

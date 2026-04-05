from __future__ import annotations

from html import escape
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from isrc_manager.contract_templates import ContractTemplateIngestionError

_WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def make_docx_bytes(
    *,
    document_paragraphs: tuple[str | tuple[str, ...], ...] = (),
    header_paragraphs: tuple[str | tuple[str, ...], ...] = (),
    footer_paragraphs: tuple[str | tuple[str, ...], ...] = (),
) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="xml" ContentType="application/xml"/>
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/header1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/>
  <Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>
</Types>
""",
        )
        archive.writestr("_rels/.rels", _rels_xml())
        archive.writestr("word/document.xml", _document_xml(document_paragraphs))
        if header_paragraphs:
            archive.writestr("word/header1.xml", _part_xml("hdr", header_paragraphs))
        if footer_paragraphs:
            archive.writestr("word/footer1.xml", _part_xml("ftr", footer_paragraphs))
    return buffer.getvalue()


def _rels_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>
"""


def _document_xml(paragraphs: tuple[str | tuple[str, ...], ...]) -> str:
    body_xml = "".join(_paragraph_xml(item) for item in paragraphs)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="{_WORD_NS}">
  <w:body>{body_xml}</w:body>
</w:document>
"""


def _part_xml(part_tag: str, paragraphs: tuple[str | tuple[str, ...], ...]) -> str:
    body_xml = "".join(_paragraph_xml(item) for item in paragraphs)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<w:{part_tag} xmlns:w="{_WORD_NS}">
  {body_xml}
</w:{part_tag}>
"""


def _paragraph_xml(value: str | tuple[str, ...]) -> str:
    fragments = value if isinstance(value, tuple) else (value,)
    runs = "".join(_run_xml(item) for item in fragments)
    return f"<w:p>{runs}</w:p>"


def _run_xml(fragment: str) -> str:
    if fragment == "\t":
        return "<w:r><w:tab/></w:r>"
    if fragment == "\n":
        return "<w:r><w:br/></w:r>"
    return f'<w:r><w:t xml:space="preserve">{escape(fragment)}</w:t></w:r>'


class FakePagesAdapter:
    adapter_name = "fake_pages_bridge"

    def __init__(
        self,
        *,
        available: bool = True,
        docx_bytes: bytes | None = None,
        error_message: str | None = None,
    ):
        self._available = available
        self._docx_bytes = docx_bytes or make_docx_bytes()
        self._pdf_bytes = b"%PDF-1.4\n% fake-pages-adapter\n"
        self._error_message = error_message
        self.convert_calls: list[tuple[Path, Path]] = []
        self.pdf_calls: list[tuple[Path, Path]] = []

    def is_available(self) -> bool:
        return self._available

    def availability_message(self) -> str | None:
        if self._available:
            return None
        return "Pages bridge unavailable for test"

    def convert_to_docx(self, source_path: str | Path, output_path: str | Path) -> Path:
        source = Path(source_path)
        target = Path(output_path)
        self.convert_calls.append((source, target))
        if not self._available:
            raise ContractTemplateIngestionError(
                self.availability_message() or "Pages bridge unavailable"
            )
        if self._error_message:
            raise ContractTemplateIngestionError(self._error_message)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(self._docx_bytes)
        return target

    def export_to_pdf(self, source_path: str | Path, output_path: str | Path) -> Path:
        source = Path(source_path)
        target = Path(output_path)
        self.pdf_calls.append((source, target))
        if not self._available:
            raise ContractTemplateIngestionError(
                self.availability_message() or "Pages bridge unavailable"
            )
        if self._error_message:
            raise ContractTemplateIngestionError(self._error_message)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(self._pdf_bytes)
        return target


class FakeDocxHtmlAdapter:
    adapter_name = "fake_docx_html"

    def __init__(self, *, html_text: str | None = None):
        self.html_text = html_text or "<html><body><p>Contract Template Export</p></body></html>"
        self.calls: list[tuple[bytes, str]] = []

    def docx_bytes_to_html(
        self,
        docx_bytes: bytes,
        *,
        source_filename: str = "contract-template.docx",
    ) -> str:
        self.calls.append((bytes(docx_bytes), str(source_filename)))
        return self.html_text


class FakeHtmlPdfAdapter:
    adapter_name = "fake_html_pdf"

    def __init__(self):
        self.file_calls: list[tuple[Path, Path]] = []
        self.html_calls: list[tuple[str, str | None, Path]] = []

    def is_available(self) -> bool:
        return True

    def availability_message(self) -> str | None:
        return None

    def render_file_to_pdf(self, html_path: str | Path, output_path: str | Path) -> Path:
        source = Path(html_path)
        target = Path(output_path)
        self.file_calls.append((source, target))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"%PDF-1.4\n% fake-html-pdf-adapter\n")
        return target

    def render_html_to_pdf(
        self,
        html_text: str,
        *,
        base_url: str | Path | None,
        output_path: str | Path,
    ) -> Path:
        target = Path(output_path)
        self.html_calls.append((str(html_text), str(base_url) if base_url is not None else None, target))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"%PDF-1.4\n% fake-html-pdf-adapter\n")
        return target


def make_html_zip_bytes(entries: dict[str, bytes | str]) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        for name, payload in entries.items():
            archive.writestr(name, payload if isinstance(payload, bytes) else str(payload))
    return buffer.getvalue()

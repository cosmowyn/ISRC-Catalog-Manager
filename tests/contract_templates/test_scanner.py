import tempfile
import unittest
from pathlib import Path
from unittest import mock

from isrc_manager.contract_templates import (
    ContractTemplateIngestionError,
    DOCXTemplateScanner,
    PagesTemplateAdapter,
    detect_template_source_format,
)
from isrc_manager.contract_templates import ingestion as ingestion_module
from tests.contract_templates._support import make_docx_bytes


class ContractTemplateScannerTests(unittest.TestCase):
    def test_docx_scanner_extracts_body_header_and_footer_placeholders(self):
        scanner = DOCXTemplateScanner()
        docx_bytes = make_docx_bytes(
            document_paragraphs=(("Agreement for ", "{{db.track.track_title}}"),),
            header_paragraphs=(("Dated ", "{{manual.license_date}}"),),
            footer_paragraphs=(("Repeat ", "{{db.track.track_title}}"),),
        )

        result = scanner.scan_bytes(docx_bytes)

        self.assertEqual(result.scan_status, "scan_ready")
        self.assertEqual(result.scan_adapter, "docx_ooxml_direct")
        self.assertEqual(
            [item.canonical_symbol for item in result.placeholders],
            ["{{db.track.track_title}}", "{{manual.license_date}}"],
        )
        self.assertEqual(result.placeholders[0].occurrence_count, 2)
        self.assertEqual(result.placeholders[1].occurrence_count, 1)

    def test_docx_scanner_blocks_bad_archives(self):
        result = DOCXTemplateScanner().scan_bytes(b"not-a-docx")

        self.assertEqual(result.scan_status, "scan_blocked")
        self.assertEqual(result.diagnostics[0].code, "docx_bad_zip")

    def test_detect_template_source_format_prefers_filename_suffix(self):
        self.assertEqual(
            detect_template_source_format(
                source_filename="agreement.pages",
                explicit_format="docx",
            ),
            "pages",
        )
        self.assertEqual(
            detect_template_source_format(
                source_filename="agreement.unknown",
                explicit_format="pages",
            ),
            "pages",
        )
        with self.assertRaises(ContractTemplateIngestionError):
            detect_template_source_format(source_filename="agreement.txt")

    def test_pages_adapter_uses_pages_app_export_via_osascript(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "agreement.pages"
            target = root / "agreement.docx"
            pages_app = root / "Pages.app"
            pages_app.mkdir()
            source.write_bytes(b"fake-pages")
            captured: dict[str, object] = {}

            def _fake_run(args, **kwargs):
                captured["args"] = list(args)
                captured["input"] = kwargs.get("input")
                target.write_bytes(b"fake-docx")

                class _Result:
                    returncode = 0
                    stdout = ""
                    stderr = ""

                return _Result()

            adapter = PagesTemplateAdapter(
                osascript_path="/usr/bin/osascript",
                pages_app_path=pages_app,
            )
            with mock.patch.object(ingestion_module.sys, "platform", "darwin"):
                with mock.patch.object(ingestion_module.subprocess, "run", side_effect=_fake_run):
                    converted = adapter.convert_to_docx(source, target)
                    output_exists = target.exists()

        self.assertEqual(converted, target)
        self.assertEqual(captured["args"], ["/usr/bin/osascript"])
        self.assertIn('tell application "Pages"', str(captured["input"]))
        self.assertIn("export docRef to outputPath as Microsoft Word", str(captured["input"]))
        self.assertTrue(output_exists)

    def test_pages_adapter_can_export_pdf_via_osascript(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "agreement.docx"
            target = root / "agreement.pdf"
            pages_app = root / "Pages.app"
            pages_app.mkdir()
            source.write_bytes(b"fake-docx")
            captured: dict[str, object] = {}

            def _fake_run(args, **kwargs):
                captured["args"] = list(args)
                captured["input"] = kwargs.get("input")
                target.write_bytes(b"%PDF-1.4\n")

                class _Result:
                    returncode = 0
                    stdout = ""
                    stderr = ""

                return _Result()

            adapter = PagesTemplateAdapter(
                osascript_path="/usr/bin/osascript",
                pages_app_path=pages_app,
            )
            with mock.patch.object(ingestion_module.sys, "platform", "darwin"):
                with mock.patch.object(ingestion_module.subprocess, "run", side_effect=_fake_run):
                    exported = adapter.export_to_pdf(source, target)
                    output_exists = target.exists()

        self.assertEqual(exported, target)
        self.assertEqual(captured["args"], ["/usr/bin/osascript"])
        self.assertIn('tell application "Pages"', str(captured["input"]))
        self.assertIn("export docRef to outputPath as PDF", str(captured["input"]))
        self.assertTrue(output_exists)

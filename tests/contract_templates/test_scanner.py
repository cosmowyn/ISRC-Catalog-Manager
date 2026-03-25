import unittest

from isrc_manager.contract_templates import (
    ContractTemplateIngestionError,
    DOCXTemplateScanner,
    detect_template_source_format,
)

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

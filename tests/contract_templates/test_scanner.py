import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest import mock
from zipfile import ZipFile

from isrc_manager.contract_templates import (
    ContractTemplateIngestionError,
    DOCXTemplateScanner,
    HTMLTemplateScanner,
    PagesTemplateAdapter,
    detect_template_source_format,
)
from isrc_manager.contract_templates import ingestion as ingestion_module
from isrc_manager.contract_templates.html_support import (
    HTMLBundleFile,
    HTMLTemplateBundle,
    build_html_bundle_from_source_bytes,
    build_html_bundle_from_zip_bytes,
    build_scan_diagnostics_payload,
    choose_html_package_entrypoint,
    collect_html_bundle_from_directory,
    copy_html_template_with_local_assets,
    extract_html_package_archive,
    html_bundle_metadata,
    normalize_bundle_relative_path,
    replace_html_placeholders,
    scan_diagnostic_entries,
    write_html_bundle,
)
from isrc_manager.contract_templates.ingestion import DOCXHtmlAdapter
from isrc_manager.external_launch import (
    clear_recorded_external_launches,
    get_recorded_external_launches,
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

    def test_docx_scanner_reports_missing_parts_and_skips_invalid_xml_parts(self):
        empty_docx = BytesIO()
        with ZipFile(empty_docx, "w") as archive:
            archive.writestr("[Content_Types].xml", "<Types/>")

        missing_parts = DOCXTemplateScanner().scan_bytes(empty_docx.getvalue())

        self.assertEqual(missing_parts.scan_status, "scan_blocked")
        self.assertEqual(missing_parts.diagnostics[0].code, "docx_parts_missing")

        mixed_docx = BytesIO()
        with ZipFile(mixed_docx, "w") as archive:
            archive.writestr("word/document.xml", "<broken")
            archive.writestr(
                "word/header1.xml",
                """
                <w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
                  <w:p>
                    <w:r><w:t>Owner</w:t></w:r>
                    <w:r><w:tab/></w:r>
                    <w:r><w:t>{{manual.owner_name}}</w:t></w:r>
                    <w:r><w:br/></w:r>
                    <w:r><w:t>Line two</w:t></w:r>
                  </w:p>
                </w:hdr>
                """,
            )

        parsed = DOCXTemplateScanner().scan_bytes(mixed_docx.getvalue())

        self.assertEqual(parsed.scan_status, "scan_ready")
        self.assertEqual(parsed.diagnostics[0].code, "docx_part_parse_error")
        self.assertEqual(
            [item.canonical_symbol for item in parsed.placeholders],
            ["{{manual.owner_name}}"],
        )

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
        self.assertEqual(
            detect_template_source_format(source_filename="agreement.html"),
            "html",
        )
        with self.assertRaises(ContractTemplateIngestionError):
            detect_template_source_format(source_filename="agreement.txt")

    def test_detect_template_source_format_allows_marked_html_zip_packages(self):
        self.assertEqual(
            detect_template_source_format(
                source_filename="template.zip",
                explicit_format="HTML",
            ),
            "html",
        )

    def test_html_scanner_extracts_placeholders_directly_from_native_html(self):
        result = HTMLTemplateScanner().scan_bytes(
            b"<html><body><img src='assets/banner.png'><p>{{db.track.track_title}}</p>"
            b"<footer>{{manual.license_date}}</footer>{{current.year}}"
            b"{{duplicate.start}}x{{duplicate.end}}{{duplicate.number}}"
            b"{{db.index}}{{db.track.track_title.indexed}}"
            b"{{page.index}}{{page.total}}{{custom.index}}</body></html>",
            source_filename="agreement.html",
        )

        self.assertEqual(result.scan_status, "scan_ready")
        self.assertEqual(result.scan_adapter, "html_source_direct")
        self.assertEqual(
            [item.canonical_symbol for item in result.placeholders],
            [
                "{{current.year}}",
                "{{custom.index}}",
                "{{db.index}}",
                "{{db.track.track_title.indexed}}",
                "{{db.track.track_title}}",
                "{{duplicate.end}}",
                "{{duplicate.number}}",
                "{{duplicate.start}}",
                "{{manual.license_date}}",
                "{{page.index}}",
                "{{page.total}}",
            ],
        )

    def test_docx_html_adapter_best_effort_and_textutil_failure_paths(self):
        adapter = DOCXHtmlAdapter(textutil_path="")
        docx_bytes = make_docx_bytes(
            document_paragraphs=(("Title\t", "{{db.track.track_title}}"),),
            header_paragraphs=(("Header", "{{manual.header_note}}"),),
            footer_paragraphs=(("Footer\n", "{{manual.footer_note}}"),),
        )

        bundle = adapter.docx_bytes_to_html_bundle(docx_bytes, source_filename="template.docx")
        html_text = bundle.primary_bytes().decode("utf-8")

        self.assertFalse(adapter._native_textutil_available())
        self.assertEqual(bundle.primary_filename, "template.html")
        self.assertIn("<main", html_text)
        self.assertIn("<header", html_text)
        self.assertIn("&emsp;", html_text)
        self.assertIn("<br/>", html_text)
        with self.assertRaises(ContractTemplateIngestionError):
            adapter._convert_via_textutil(docx_bytes, source_filename="template.docx")
        with self.assertRaises(ContractTemplateIngestionError):
            adapter._convert_via_best_effort_html(b"not-a-docx", source_filename="bad.docx")

        failing_adapter = DOCXHtmlAdapter(textutil_path="/usr/bin/textutil")

        class Result:
            returncode = 2
            stderr = "conversion failed"

        with mock.patch.object(ingestion_module.sys, "platform", "darwin"):
            with mock.patch.object(ingestion_module.subprocess, "run", return_value=Result()):
                with self.assertRaisesRegex(
                    ContractTemplateIngestionError,
                    "conversion failed",
                ):
                    failing_adapter._convert_via_textutil(
                        docx_bytes,
                        source_filename="template.txt",
                    )

    def test_html_bundle_helpers_reject_unsafe_paths_and_preserve_assets(self):
        self.assertEqual(
            replace_html_placeholders("<p>{{name}}</p>", {"{{name}}": "A&B"}), "<p>A&amp;B</p>"
        )
        self.assertEqual(
            replace_html_placeholders(
                "<section>{{table}}</section>",
                {"{{table}}": "<table><tbody><tr><td>A&B</td></tr></tbody></table>"},
                raw_tokens={"{{table}}"},
            ),
            "<section><table><tbody><tr><td>A&B</td></tr></tbody></table></section>",
        )
        self.assertIsNone(normalize_bundle_relative_path(""))
        self.assertIsNone(normalize_bundle_relative_path("folder/"))
        self.assertIsNone(normalize_bundle_relative_path("__MACOSX/file"))
        self.assertIsNone(normalize_bundle_relative_path("assets/._icon.png"))
        self.assertEqual(normalize_bundle_relative_path("./pages/index.html"), "pages/index.html")
        with self.assertRaises(ContractTemplateIngestionError):
            normalize_bundle_relative_path("/tmp/index.html")
        with self.assertRaises(ContractTemplateIngestionError):
            normalize_bundle_relative_path("../index.html")
        with self.assertRaises(ContractTemplateIngestionError):
            build_html_bundle_from_source_bytes(b"<p/>", source_filename="")

        package = BytesIO()
        with ZipFile(package, "w") as archive:
            archive.writestr("assets/logo.png", b"png")
            archive.writestr("index.html", b"<img src='assets/logo.png'>")
            archive.writestr("__MACOSX/ignored.html", b"ignored")
            archive.writestr("assets/._ignored", b"ignored")

        bundle = build_html_bundle_from_zip_bytes(
            package.getvalue(),
            package_filename="template.zip",
        )

        self.assertEqual(bundle.primary_relative_path, "index.html")
        self.assertEqual(bundle.import_kind, "zip_package")
        self.assertEqual(bundle.package_filename, "template.zip")
        self.assertEqual(
            sorted(item.relative_path for item in bundle.files),
            ["assets/logo.png", "index.html"],
        )

        with self.assertRaises(ContractTemplateIngestionError):
            build_html_bundle_from_zip_bytes(b"not-a-zip")
        no_html = BytesIO()
        with ZipFile(no_html, "w") as archive:
            archive.writestr("assets/readme.txt", b"readme")
        with self.assertRaises(ContractTemplateIngestionError):
            build_html_bundle_from_zip_bytes(no_html.getvalue())
        ambiguous = BytesIO()
        with ZipFile(ambiguous, "w") as archive:
            archive.writestr("one.html", b"one")
            archive.writestr("two.html", b"two")
        with self.assertRaisesRegex(ContractTemplateIngestionError, "ambiguous"):
            build_html_bundle_from_zip_bytes(ambiguous.getvalue())

    def test_html_bundle_filesystem_helpers_cover_empty_ambiguous_and_metadata_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with self.assertRaises(ContractTemplateIngestionError):
                collect_html_bundle_from_directory(root, primary_relative_path="index.html")

            source_root = root / "source"
            source_root.mkdir()
            html_path = source_root / "nested" / "template.html"
            html_path.parent.mkdir()
            html_path.write_text("<p>{{manual.name}}</p>", encoding="utf-8")
            (source_root / "assets").mkdir()
            (source_root / "assets" / "style.css").write_text("body{}", encoding="utf-8")

            bundle = collect_html_bundle_from_directory(
                source_root,
                primary_relative_path="./nested/template.html",
            )
            self.assertEqual(bundle.import_kind, "managed_bundle")
            self.assertEqual(bundle.primary_relative_path, "nested/template.html")

            store = mock.Mock(root_path=root / "managed", data_root=root)
            stored_primary, stored_root = write_html_bundle(
                store,
                bundle,
                bundle_subdir="templates/template-1",
            )
            self.assertTrue((root / stored_primary).exists())
            self.assertEqual(stored_root, "managed/templates/template-1")

            with self.assertRaises(ContractTemplateIngestionError):
                write_html_bundle(
                    store,
                    HTMLTemplateBundle(
                        primary_relative_path="missing.html",
                        files=(HTMLBundleFile("index.html", b"<p/>"),),
                    ),
                    bundle_subdir="templates/missing",
                )
            with self.assertRaises(ValueError):
                write_html_bundle(
                    mock.Mock(root_path=None, data_root=root),
                    bundle,
                    bundle_subdir="templates/no-store",
                )

            package = root / "template.zip"
            with ZipFile(package, "w") as archive:
                archive.writestr("index.html", b"<p/>")
                archive.writestr("assets/style.css", b"body{}")
            extracted = extract_html_package_archive(package, root / "extracted")
            self.assertEqual(sorted(path.name for path in extracted), ["index.html", "style.css"])

            copied = copy_html_template_with_local_assets(
                source_html_path=html_path,
                source_root=root / "other-root",
                destination_root=root / "copied",
            )
            self.assertEqual(copied.name, "template.html")

        self.assertEqual(choose_html_package_entrypoint([Path("only.html")]), Path("only.html"))
        self.assertEqual(
            choose_html_package_entrypoint([Path("page.html"), Path("index.html")]),
            Path("index.html"),
        )
        with self.assertRaises(ContractTemplateIngestionError):
            choose_html_package_entrypoint([Path("readme.txt")])
        with self.assertRaisesRegex(ContractTemplateIngestionError, "ambiguous"):
            choose_html_package_entrypoint([Path("one.html"), Path("two.html")])

        diagnostics_payload = build_scan_diagnostics_payload(
            ["warn"],
            html_bundle={"primary": "index.html"},
        )
        self.assertEqual(scan_diagnostic_entries(diagnostics_payload), ("warn",))
        self.assertEqual(html_bundle_metadata(diagnostics_payload), {"primary": "index.html"})
        self.assertEqual(scan_diagnostic_entries(["warn"]), ("warn",))
        self.assertIsNone(html_bundle_metadata(["warn"]))
        with self.assertRaises(ContractTemplateIngestionError):
            HTMLTemplateBundle(
                primary_relative_path="missing.html",
                files=(HTMLBundleFile("index.html", b""),),
            ).primary_bytes()

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
                with mock.patch.object(
                    ingestion_module,
                    "run_external_launcher_subprocess",
                    side_effect=_fake_run,
                ):
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
                with mock.patch.object(
                    ingestion_module,
                    "run_external_launcher_subprocess",
                    side_effect=_fake_run,
                ):
                    exported = adapter.export_to_pdf(source, target)
                    output_exists = target.exists()

        self.assertEqual(exported, target)
        self.assertEqual(captured["args"], ["/usr/bin/osascript"])
        self.assertIn('tell application "Pages"', str(captured["input"]))
        self.assertIn("export docRef to outputPath as PDF", str(captured["input"]))
        self.assertTrue(output_exists)

    def test_pages_adapter_reports_unavailable_states_and_failed_exports(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / 'source "quote".pages'
            target = root / "target.docx"
            source.write_bytes(b"pages")

            non_macos = PagesTemplateAdapter(
                osascript_path="/usr/bin/osascript",
                pages_app_path=root / "Pages.app",
            )
            with mock.patch.object(ingestion_module.sys, "platform", "linux"):
                self.assertFalse(non_macos.is_available())
                self.assertIn("macOS", non_macos.availability_message())

            missing_app = PagesTemplateAdapter(
                osascript_path="/usr/bin/osascript",
                pages_app_path=root / "MissingPages.app",
            )
            with mock.patch.object(ingestion_module.sys, "platform", "darwin"):
                self.assertIn("Pages.app", missing_app.availability_message())

            missing_script_app = root / "Pages.app"
            missing_script_app.mkdir()
            missing_script = PagesTemplateAdapter(
                osascript_path="",
                pages_app_path=missing_script_app,
            )
            with mock.patch.object(ingestion_module.sys, "platform", "darwin"):
                self.assertIn("osascript", missing_script.availability_message())
                with self.assertRaises(ContractTemplateIngestionError):
                    missing_script.convert_to_docx(source, target)

            failing_adapter = PagesTemplateAdapter(
                osascript_path="/usr/bin/osascript",
                pages_app_path=missing_script_app,
            )

            class Result:
                returncode = 1
                stdout = ""
                stderr = "permission denied"

            with mock.patch.object(ingestion_module.sys, "platform", "darwin"):
                with mock.patch.object(
                    ingestion_module,
                    "run_external_launcher_subprocess",
                    return_value=Result(),
                ):
                    with self.assertRaisesRegex(
                        ContractTemplateIngestionError,
                        "permission denied",
                    ):
                        failing_adapter.convert_to_docx(source, target)

            self.assertEqual(
                PagesTemplateAdapter._applescript_string(source),
                str(source).replace('"', '\\"'),
            )

    def test_pages_adapter_records_central_launch_intent_when_test_guard_blocks_pages(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "agreement.pages"
            target = root / "agreement.docx"
            pages_app = root / "Pages.app"
            pages_app.mkdir()
            source.write_bytes(b"fake-pages")
            adapter = PagesTemplateAdapter(
                osascript_path="/usr/bin/osascript",
                pages_app_path=pages_app,
            )
            clear_recorded_external_launches()

            with mock.patch.object(ingestion_module.sys, "platform", "darwin"):
                with self.assertRaises(ContractTemplateIngestionError):
                    adapter.convert_to_docx(source, target)

        requests = get_recorded_external_launches()
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].via, "external_launch.run_external_launcher_subprocess")
        self.assertEqual(requests[0].source, "PagesTemplateAdapter._export_via_pages")
        self.assertEqual(requests[0].target, "/usr/bin/osascript")
        self.assertEqual(requests[0].metadata.get("integration"), "pages_export")
        self.assertTrue(requests[0].blocked)

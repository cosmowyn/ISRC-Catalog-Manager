import sqlite3
import tempfile
import unittest
from pathlib import Path

from isrc_manager.services import (
    ContractTemplatePayload,
    ContractTemplatePlaceholderBindingPayload,
    ContractTemplateRevisionPayload,
    ContractTemplateService,
    DatabaseSchemaService,
)
from tests.contract_templates._support import (
    FakeDocxHtmlAdapter,
    FakePagesAdapter,
    make_docx_bytes,
    make_html_zip_bytes,
)


class ContractTemplateRevisionImportTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.conn = sqlite3.connect(":memory:")
        self.schema = DatabaseSchemaService(self.conn, data_root=self.root)
        self.schema.init_db()
        self.schema.migrate_schema()
        self.service = ContractTemplateService(self.conn, data_root=self.root)

    def tearDown(self):
        self.conn.close()
        self.tmpdir.cleanup()

    def _create_template(self):
        return self.service.create_template(
            ContractTemplatePayload(
                name="Phase 2 Template",
                description="Import + scan coverage",
                template_family="contract",
                source_format="docx",
            )
        )

    def test_import_revision_from_docx_path_persists_scan_metadata_and_inventory(self):
        template = self._create_template()
        source_path = self.root / "artist-agreement.docx"
        source_bytes = make_docx_bytes(
            document_paragraphs=(("Track ", "{{db.track.track_title}}"),),
            header_paragraphs=(("Signed ", "{{manual.license_date}}"),),
        )
        source_path.write_bytes(source_bytes)

        result = self.service.import_revision_from_path(
            template.template_id,
            source_path,
            payload=ContractTemplateRevisionPayload(storage_mode="managed_file"),
        )
        placeholders = self.service.list_placeholders(result.revision.revision_id)
        template_after = self.service.fetch_template(template.template_id)
        html_source = self.service.resolve_html_revision_source_path(result.revision.revision_id)

        self.assertEqual(result.scan_result.scan_status, "scan_ready")
        self.assertEqual(result.revision.scan_adapter, "docx_ooxml_direct")
        self.assertEqual(result.revision.source_format, "docx")
        self.assertEqual(result.revision.placeholder_count, 2)
        self.assertFalse(result.revision.stored_in_database)
        self.assertEqual(
            [item.canonical_symbol for item in placeholders],
            ["{{db.track.track_title}}", "{{manual.license_date}}"],
        )
        self.assertIsNotNone(placeholders[0].metadata)
        self.assertEqual(template_after.active_revision_id, result.revision.revision_id)
        self.assertEqual(
            self.service.load_revision_source_bytes(result.revision.revision_id),
            source_bytes,
        )
        self.assertIsNotNone(html_source)
        self.assertTrue(html_source.exists())
        self.assertTrue(
            self.service.revision_supports_html_working_draft(result.revision.revision_id)
        )

    def test_import_revision_dedupes_repeated_symbols_and_preserves_occurrence_counts(self):
        template = self._create_template()
        source_path = self.root / "repeat-heavy.docx"
        source_path.write_bytes(
            make_docx_bytes(
                document_paragraphs=(
                    (
                        "Track ",
                        "{{db.track.track_title}}",
                        " and again ",
                        "{{db.track.track_title}}",
                    ),
                    ("Signed on ", "{{manual.license_date}}"),
                ),
                header_paragraphs=(("Signed on ", "{{manual.license_date}}"),),
                footer_paragraphs=(("Track fallback ", "{{db.track.track_title}}"),),
            )
        )

        result = self.service.import_revision_from_path(
            template.template_id,
            source_path,
            payload=ContractTemplateRevisionPayload(storage_mode="managed_file"),
        )
        placeholders = self.service.list_placeholders(result.revision.revision_id)

        self.assertEqual(result.revision.placeholder_count, 2)
        self.assertEqual(
            [item.canonical_symbol for item in placeholders],
            ["{{db.track.track_title}}", "{{manual.license_date}}"],
        )
        self.assertEqual(placeholders[0].source_occurrence_count, 3)
        self.assertEqual(placeholders[1].source_occurrence_count, 2)
        self.assertEqual(result.scan_result.scan_status, "scan_ready")

    def test_import_revision_rejects_unsupported_source_format_before_storing(self):
        template = self._create_template()
        source_path = self.root / "artist-agreement.txt"
        source_path.write_text("{{db.track.track_title}}", encoding="utf-8")

        with self.assertRaisesRegex(Exception, "Unsupported template source format"):
            self.service.import_revision_from_path(template.template_id, source_path)

        self.assertEqual(self.service.list_revisions(template.template_id), [])

    def test_import_revision_from_html_path_copies_assets_and_scans_natively(self):
        template = self.service.create_template(
            ContractTemplatePayload(
                name="HTML Template",
                description="HTML import coverage",
                template_family="contract",
                source_format="html",
            )
        )
        html_root = self.root / "html-template"
        (html_root / "assets").mkdir(parents=True)
        (html_root / "assets" / "banner.png").write_bytes(b"png-bytes")
        source_path = html_root / "agreement.html"
        source_path.write_text(
            "<html><body><img src='assets/banner.png'><p>{{manual.license_date}}</p></body></html>",
            encoding="utf-8",
        )

        result = self.service.import_revision_from_path(
            template.template_id,
            source_path,
            payload=ContractTemplateRevisionPayload(source_filename=source_path.name),
        )
        managed_source = self.service.resolve_html_revision_source_path(result.revision.revision_id)
        revision_assets = self.service.list_revision_assets(result.revision.revision_id)

        self.assertEqual(result.revision.source_format, "html")
        self.assertEqual(result.scan_result.scan_adapter, "html_source_direct")
        self.assertIsNotNone(managed_source)
        self.assertTrue(managed_source.exists())
        self.assertNotEqual(managed_source.read_text(encoding="utf-8"), "")
        self.assertTrue((managed_source.parent / "assets" / "banner.png").exists())
        self.assertEqual(len(revision_assets), 1)
        self.assertEqual(revision_assets[0].package_rel_path, "assets/banner.png")

    def test_import_html_package_from_zip_persists_html_and_assets(self):
        template = self.service.create_template(
            ContractTemplatePayload(
                name="ZIP HTML Template",
                description="ZIP import coverage",
                template_family="license",
                source_format="html",
            )
        )
        package_path = self.root / "agreement.zip"
        package_path.write_bytes(
            make_html_zip_bytes(
                {
                    "bundle/index.html": "<html><body><img src='assets/footer.png'><p>{{manual.license_date}}</p></body></html>",
                    "bundle/assets/footer.png": b"footer-bytes",
                }
            )
        )

        result = self.service.import_html_package_from_path(template.template_id, package_path)
        managed_source = self.service.resolve_html_revision_source_path(result.revision.revision_id)

        self.assertEqual(result.revision.source_format, "html")
        self.assertIsNotNone(managed_source)
        self.assertTrue(managed_source.exists())
        self.assertTrue((managed_source.parent / "assets" / "footer.png").exists())
        self.assertEqual(
            [
                asset.package_rel_path
                for asset in self.service.list_revision_assets(result.revision.revision_id)
            ],
            ["bundle/assets/footer.png"],
        )

    def test_duplicate_html_template_preserves_bundle_assets(self):
        template = self.service.create_template(
            ContractTemplatePayload(
                name="Duplicate HTML Template",
                description="Duplicate HTML coverage",
                template_family="contract",
                source_format="html",
            )
        )
        html_root = self.root / "duplicate-html-template"
        (html_root / "assets").mkdir(parents=True)
        (html_root / "assets" / "seal.png").write_bytes(b"seal")
        source_path = html_root / "license.html"
        original_html = (
            "<html><body><img src='assets/seal.png'><p>{{manual.license_date}}</p></body></html>"
        )
        source_path.write_text(original_html, encoding="utf-8")
        imported = self.service.import_revision_from_path(
            template.template_id,
            source_path,
            payload=ContractTemplateRevisionPayload(source_filename=source_path.name),
        )

        duplicated = self.service.duplicate_template(template.template_id)
        duplicated_revisions = self.service.list_revisions(duplicated.template_id)
        self.assertEqual(len(duplicated_revisions), 1)

        duplicated_revision = duplicated_revisions[0]
        duplicated_source = self.service.resolve_html_revision_source_path(
            duplicated_revision.revision_id
        )
        duplicated_assets = self.service.list_revision_assets(duplicated_revision.revision_id)

        self.assertEqual(imported.revision.source_format, "html")
        self.assertEqual(duplicated_revision.source_format, "html")
        self.assertIsNotNone(duplicated_source)
        self.assertEqual(duplicated_source.read_text(encoding="utf-8"), original_html)
        self.assertTrue((duplicated_source.parent / "assets" / "seal.png").exists())
        self.assertEqual(
            [asset.package_rel_path for asset in duplicated_assets], ["assets/seal.png"]
        )

    def test_rescan_html_revision_preserves_bundle_metadata_and_assets(self):
        template = self.service.create_template(
            ContractTemplatePayload(
                name="Rescan HTML Template",
                description="Rescan HTML coverage",
                template_family="contract",
                source_format="html",
            )
        )
        html_root = self.root / "rescan-html-template"
        (html_root / "assets").mkdir(parents=True)
        (html_root / "assets" / "footer.png").write_bytes(b"footer")
        source_path = html_root / "agreement.html"
        source_path.write_text(
            "<html><body><img src='assets/footer.png'><p>{{manual.license_date}}</p></body></html>",
            encoding="utf-8",
        )

        imported = self.service.import_revision_from_path(template.template_id, source_path)
        before_source = self.service.resolve_html_revision_source_path(
            imported.revision.revision_id
        )
        before_assets = self.service.list_revision_assets(imported.revision.revision_id)

        rescan = self.service.rescan_revision(imported.revision.revision_id, activate_if_ready=True)
        after_revision = self.service.fetch_revision(imported.revision.revision_id)
        after_source = self.service.resolve_html_revision_source_path(imported.revision.revision_id)
        after_assets = self.service.list_revision_assets(imported.revision.revision_id)

        self.assertEqual(rescan.scan_status, "scan_ready")
        self.assertIsNotNone(after_revision)
        self.assertEqual(after_revision.scan_adapter, "html_source_direct")
        self.assertEqual(before_source, after_source)
        self.assertEqual(
            [asset.package_rel_path for asset in before_assets],
            [asset.package_rel_path for asset in after_assets],
        )
        self.assertTrue((after_source.parent / "assets" / "footer.png").exists())

    def test_import_pages_revision_from_bytes_uses_adapter_and_ready_rescan_preserves_bindings(
        self,
    ):
        template = self._create_template()
        pages_adapter = FakePagesAdapter(
            docx_bytes=make_docx_bytes(
                document_paragraphs=(("Track ", "{{db.track.track_title}}"),)
            )
        )
        self.service = ContractTemplateService(
            self.conn,
            data_root=self.root,
            docx_html_adapter=FakeDocxHtmlAdapter(
                html_text="<html><body><p>{{db.track.track_title}}</p></body></html>"
            ),
            pages_adapter=pages_adapter,
        )

        result = self.service.import_revision_from_bytes(
            template.template_id,
            b"pages-source",
            payload=ContractTemplateRevisionPayload(
                source_filename="artist-agreement.pages",
                storage_mode="database",
            ),
            bindings=[
                ContractTemplatePlaceholderBindingPayload(
                    canonical_symbol="{{db.track.track_title}}",
                    resolver_kind="db",
                    resolver_target="Tracks.track_title",
                    scope_entity_type="track",
                    scope_policy="required",
                    widget_hint="picker",
                )
            ],
        )
        rescan = self.service.rescan_revision(result.revision.revision_id)
        bindings = self.service.list_placeholder_bindings(result.revision.revision_id)
        html_source = self.service.resolve_html_revision_source_path(result.revision.revision_id)

        self.assertEqual(result.revision.scan_adapter, "fake_pages_bridge")
        self.assertEqual(result.revision.source_format, "pages")
        self.assertEqual(result.revision.placeholder_count, 1)
        self.assertEqual(rescan.scan_status, "scan_ready")
        self.assertEqual(len(bindings), 1)
        self.assertEqual(bindings[0].canonical_symbol, "{{db.track.track_title}}")
        self.assertEqual(
            self.service.load_revision_source_bytes(result.revision.revision_id),
            b"pages-source",
        )
        self.assertIsNotNone(html_source)
        self.assertTrue(html_source.exists())
        self.assertGreaterEqual(len(pages_adapter.convert_calls), 2)

    def test_blocked_pages_import_persists_revision_without_replacing_active_ready_revision(self):
        template = self._create_template()
        ready_source = self.root / "ready.docx"
        ready_source.write_bytes(
            make_docx_bytes(document_paragraphs=(("Track ", "{{db.track.track_title}}"),))
        )
        ready_result = self.service.import_revision_from_path(template.template_id, ready_source)

        blocked_service = ContractTemplateService(
            self.conn,
            data_root=self.root,
            pages_adapter=FakePagesAdapter(available=False),
        )
        blocked_result = blocked_service.import_revision_from_bytes(
            template.template_id,
            b"blocked-pages-source",
            payload=ContractTemplateRevisionPayload(source_filename="blocked.pages"),
        )
        template_after = blocked_service.fetch_template(template.template_id)

        self.assertEqual(blocked_result.revision.scan_status, "scan_blocked")
        self.assertEqual(blocked_result.revision.placeholder_count, 0)
        self.assertEqual(template_after.active_revision_id, ready_result.revision.revision_id)
        self.assertEqual(len(blocked_service.list_revisions(template.template_id)), 2)
        self.assertIsNone(
            blocked_service.resolve_html_revision_source_path(blocked_result.revision.revision_id)
        )

    def test_blocked_pages_rescan_preserves_existing_inventory_and_bindings(self):
        template = self._create_template()
        self.service = ContractTemplateService(
            self.conn,
            data_root=self.root,
            pages_adapter=FakePagesAdapter(
                docx_bytes=make_docx_bytes(
                    document_paragraphs=(("Track ", "{{db.track.track_title}}"),)
                )
            ),
        )
        ready_result = self.service.import_revision_from_bytes(
            template.template_id,
            b"pages-source",
            payload=ContractTemplateRevisionPayload(source_filename="artist-agreement.pages"),
            bindings=[
                ContractTemplatePlaceholderBindingPayload(
                    canonical_symbol="{{db.track.track_title}}",
                    resolver_kind="db",
                    resolver_target="Tracks.track_title",
                    widget_hint="picker",
                )
            ],
        )

        self.service.pages_adapter = FakePagesAdapter(available=False)
        blocked_rescan = self.service.rescan_revision(ready_result.revision.revision_id)
        revision_after = self.service.fetch_revision(ready_result.revision.revision_id)
        bindings_after = self.service.list_placeholder_bindings(ready_result.revision.revision_id)

        self.assertEqual(blocked_rescan.scan_status, "scan_blocked")
        self.assertEqual(revision_after.scan_status, "scan_blocked")
        self.assertEqual(revision_after.placeholder_count, 1)
        self.assertEqual(len(bindings_after), 1)
